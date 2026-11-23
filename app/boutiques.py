"""Relevé des boutiques de la vue Boutiques, chaque semaine, sans valeur écrite à la main.

`data/boutiques.json` ne donne que l'identité de chaque boutique et les adresses où lire ses champs.
Le service y lit, une requête à la fois avec une pause :
- `/meta.json` (boutiques Shopify) : pays du siège, devise, livraison en France (`ships_to_countries`) ;
- l'API publique de Trusted Shops (`trustedshops` : tsId) : note et nombre d'avis des 12 derniers mois,
  avis vérifiés sur commande ;
- la page d'accueil : avis affichés par la boutique elle-même (badge Judge.me, ou `aggregateRating` en
  JSON-LD), et la mention de TVA comprise ;
- la page de livraison (`livraison_page`, ou celle de la source dans `data/sources.json`), corps de la
  politique seulement : port vers la France (montant qui suit « France »), délai écrit après « France »
  ou, à défaut, après « Europe » (`livraison_france` : page propre à la France, premier délai écrit),
  mention de TVA comprise ou d'IOSS.
- les mentions légales (`mentions_page`), pour une boutique hors Shopify : pays du numéro de TVA
  intracommunautaire, celui où le vendeur acquitte la TVA (préfixe DE, FR…), sinon préfixe de pays du
  code postal de l'adresse (« DK-7190 Billund »).
La page de livraison donne aussi le seuil de gratuité (« gratuit dès 39 € », « free from €99 », montant
en euros de 10 à 500 €) et, pour une boutique hors Shopify, la devise du port et la livraison en France
quand un port vers la France y est publié. Une place de marché a port, délai et douane « selon le
vendeur » (règle). Le pays lu par le numéro de TVA est celui où le vendeur acquitte la TVA, pas celui
d'où part le colis ; il fonde la douane (TVA d'un pays de l'Union) et le délai estimé.
Une lecture en échec garde la dernière valeur lue, avec sa date ; l'échec est noté avec sa cause exacte
(code HTTP et protection qui a répondu : Cloudflare, défi anti-robot, Akamai ; page anti-robot servie à
la place du contenu). Aucun contournement : la cause est dite, la valeur précédente reste.

Champs calculés par une règle, sans lecture (« origine » : « règle », la règle est dite) :
- douane : vendeur dans l'Union européenne → aucune ; hors Union, TVA comprise lue → TVA payée à la
  commande (guichet IOSS, colis de 150 € ou moins) ; hors Union sans cette mention → TVA et frais
  de dédouanement possibles à la livraison ;
- délai, quand la page n'en donne pas : estimé d'après le pays du siège (Union européenne : 2 à 6 jours
  ouvrés ; Chine, Hong Kong : 10 à 30 jours), marqué « estimé » ;
- boîte d'origine : d'après le type (boutique de sets neufs : boîte d'origine ; place de marché : selon
  le vendeur ; pièces à l'unité : sans objet), marquée « estimé » ;
- fiabilité, de 0 à 3 : avis vérifiés (Trusted Shops) d'au moins 4.5 sur 5 et 200 avis sur 12 mois → 3 ;
  d'au moins 4.0 et 50 avis → 2 ; sinon 1. Avis affichés par la boutique seulement : mêmes seuils,
  plafonnés à 2 (la boutique choisit ce qu'elle montre). Aucun avis lisible → 1. Ne livre pas la France → 0.
Port et délai d'une boutique lue comme source, faute de lecture : valeurs saisies le 20/11/2026 dans
`data/sources.json`, d'origine « écrit ». Un champ qu'aucune lecture ni aucune règle ne donne est rendu
dans `manquants`, jamais avec une valeur vide.
"""
from __future__ import annotations

import json
import logging
import re
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit

from . import lien, livraison, normalise as n
from .donnees import _ecrire, _lire

log = logging.getLogger("boutiques")
RACINE = Path(__file__).resolve().parent.parent
PERIODE_J = 7
PAUSE_S = 2.0
TRUSTEDSHOPS = "https://api.trustedshops.com/rest/public/v2/shops/{}/quality.json"
UE = {"AT", "BE", "BG", "CY", "CZ", "DE", "DK", "EE", "ES", "FI", "FR", "GR", "HR", "HU", "IE", "IT", "LT", "LU",
      "LV", "MT", "NL", "PL", "PT", "RO", "SE", "SI", "SK"}
PAYS = {"DE": "Allemagne", "FR": "France", "NL": "Pays-Bas", "BE": "Belgique", "AT": "Autriche", "PL": "Pologne",
        "IT": "Italie", "ES": "Espagne", "DK": "Danemark", "CZ": "Tchéquie", "LU": "Luxembourg", "CH": "Suisse",
        "BG": "Bulgarie", "CY": "Chypre", "EE": "Estonie", "FI": "Finlande", "GR": "Grèce", "HR": "Croatie", "HU": "Hongrie",
        "IE": "Irlande", "LT": "Lituanie", "LV": "Lettonie", "MT": "Malte", "PT": "Portugal", "RO": "Roumanie",
        "SE": "Suède", "SI": "Slovénie", "SK": "Slovaquie",
        "GB": "Royaume-Uni", "US": "États-Unis", "CN": "Chine", "HK": "Hong Kong", "TW": "Taïwan"}
CHAMPS = ("pays", "devise", "livre_france", "port", "delai", "douane", "boite", "avis", "fiabilite")
VERROU = threading.Lock()

_NOMBRE = r"(\d{1,2})"
_DELAI = re.compile(_NOMBRE + r"\s*(?:-|–|à|to|bis|a)\s*" + _NOMBRE + r"\s*(jours? ouvrés|jours?|business days|working days|"
                    r"days|Werktage|Werktagen|Arbeitstage|Tage|Tagen)", re.I)
_TVA_MOTIF = re.compile(r"\b(?:TVA comprise|TVA incluse|TTC|VAT included|incl\.? VAT|including VAT|tax(?:es)? included|"
                        r"inkl\.? MwSt|MwSt\.? inbegriffen|IOSS|duty[- ]free|no customs)\b", re.I)
_NEGATION = re.compile(r"\b(not|no|without|hors|sans|non|pas|excl\.?|exkl\.?|zzgl\.?|nicht|ohne|keine?)\W+(\w+\W+)?$", re.I)


class _Tva:
    """Mention de TVA comprise, sauf précédée d'une négation (au plus un mot entre les deux)."""

    @staticmethod
    def search(texte: str):
        for m in _TVA_MOTIF.finditer(texte or ""):
            if not _NEGATION.search(texte[max(0, m.start() - 40):m.start()]):
                return m
        return None


_TVA = _Tva()
_JUDGEME_NOTE = re.compile(r"jdgm-all-reviews-rating['\"][^>]*?aria-label=['\"]([\d.]+) stars", re.I)
_JUDGEME_NOMBRE = re.compile(r"data-number-of-reviews=['\"](\d+)['\"]", re.I)


# page servie à la place du contenu par une protection anti-robot (réponse 200)
_DEFI = re.compile(r"_____tmd_____/punish|<title>Just a moment\.\.\.|<title>Attention Required! \| Cloudflare|captcha-delivery\.com|"
                   r"Human Verification", re.I)
# numéro de TVA intracommunautaire, dont le préfixe dit le pays où le vendeur acquitte la TVA
# Version stricte (décision du 23/11/2026, après deux corrections qui n'ont pas convergé) : libellés
# précis, aucun faux positif connu ; limite connue : « VAT Reg No: », « VAT-ID », « USt.-IdNr. »,
# « Umsatzsteuer-ID », « TVA intracommunautaire n° », « TVA : », « BTW-nummer » et un numéro séparé de son
# libellé par plus de quelques signes ne sont pas lus. Conception à refaire : validation du numéro par la
# somme de contrôle officielle de chaque pays.
_TVA_ID = re.compile(r"(?i:\b(?:n(?:°|o\.?|uméro)\s*(?:de\s*)?TVA|TVA\s+intracommunautaire|VAT\s*(?:ID|No\.?|number|Reg\w*)|"
                     r"USt-?Id\w*|Umsatzsteuer-?Identifikationsnummer|identification de taxe sur le chiffre d.affaires[^:]{0,90})"
                     r")\W{0,5}(AT|BE|BG|CY|CZ|DE|DK|EE|EL|ES|FI|FR|HR|HU|IE|IT|LT|LU|LV|MT|NL|PL|PT|RO|SE|SI|SK)"
                     r" ?((?:[0-9A-Z] ?){8,13})(?![0-9A-Za-z])")
# adresse à code postal préfixé du pays (« DK-7190 Billund », pied de page de LEGO, 23/11/2026)
# … suivi de la ville puis du nom du pays : une référence comme « DE-2024 Z » n'est pas une adresse
_CODE_POSTAL = re.compile(r"\b(AT|BE|CH|DE|DK|ES|FR|IT|LU|NL|PL|SE)-\d{4,5}\s+[A-ZÀ-Ý][\wÀ-ÿ'-]{1,25}(?:\s[A-ZÀ-Ý][\wÀ-ÿ'-]{1,25})?,?\s+"
                          r"(?:Austria|Autriche|Österreich|Belgium|Belgique|Belgien|Switzerland|Suisse|Schweiz|Germany|Allemagne|"
                          r"Deutschland|Denmark|Danemark|Dänemark|Spain|Espagne|Spanien|Italy|Italie|Italien|Luxembourg|Luxemburg|"
                          r"Netherlands|Pays-Bas|Niederlande|Poland|Pologne|Polen|Sweden|Suède|Schweden|France|Frankreich)\b")
_SEUIL = re.compile(r"(?:gratuit\w*|offert\w*|\bfree\b|kostenlos|versandkostenfrei)\D{0,80}?\b(?:dès|à partir de|from|ab|"
                    r"supérieur à|égal ou supérieur à|au-delà de|over)\s*(?:€\s*(\d{1,4}(?:[.,]\d{2})?)|(\d{1,4}(?:[.,]\d{2})?)\s*(?:€|EUR\b|euros?\b))",
                    re.I)
# « Orders up to 55 € have a delivery cost of 5.95 € » (LEGO, 23/11/2026) : seuil puis port
_SOUS_PORT = re.compile(r"(?:orders?|commandes?|Bestellungen)\s+(?:up to|under|below|jusqu.à|inférieures? à|de moins de|bis|unter)\s+"
                        r"(?:€\s*)?(\d{1,4})\s*(?:€|eur\b)?[^.\d]{0,40}?(\d{1,2}[.,]\d{2})\s*€", re.I)
_PORT_SOUS = re.compile(r"(\d{1,2}[.,]\d{2})\s*€\s*(?:pour les|aux|for|für)\s+(?:commandes?|orders?|Bestellungen)\s+"
                        r"(?:inférieures?|de moins|under|below|unter)\s+(?:à|de)?\s*(?:€\s*)?(\d{1,4})", re.I)


def cause(e: Exception) -> str:
    """Cause d'un échec, avec la protection qui a répondu quand ses en-têtes la nomment."""
    texte = getattr(e, "public", None) or type(e).__name__
    h = {k.lower(): (v or "").lower() for k, v in (getattr(e, "entetes", None) or {}).items()}
    serveur = h.get("server", "")
    if h.get("cf-mitigated") == "challenge":
        return texte + " (Cloudflare, défi anti-robot)"
    if getattr(e, "statut", None) != 403:   # un 404, un 429 ou un 5xx n'est pas un refus de la protection
        return texte
    for nom, protection in (("cloudflare", "Cloudflare"), ("akamai", "Akamai"), ("cloudfront", "CloudFront")):
        if nom in serveur:
            return texte + f" ({protection})"
    return texte


def configuration() -> list[dict]:
    """Boutiques de data/boutiques.json ; nom, hôte et adresse d'une boutique lue comme source viennent de
    data/sources.json (une seule place)."""
    sources = _sources()
    out = []
    for b in json.loads((RACINE / "data" / "boutiques.json").read_text("utf-8"))["boutiques"]:
        s = sources.get(b.get("source") or "")
        if s:
            b = {"nom": s["nom"], "hote": s["hote"].removeprefix("www."), "url": f"https://{s['hote']}{s.get('prefixe') or ''}", **b}
        out.append(b)
    return out


def _sources() -> dict[str, dict]:
    return {s["id"]: s for s in json.loads((RACINE / "data" / "sources.json").read_text("utf-8"))["sources"]}


def _horodatage() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def _page(url: str) -> str:
    return lien.recuperer(url).corps.decode("utf-8", "replace")


# ----- lectures (une fonction par adresse ; chacune lève en cas d'échec) -----
def lire_meta(b: dict) -> dict:
    p = urlsplit(b["url"])
    d = json.loads(_page(f"{p.scheme}://{p.netloc}/meta.json"))
    if not isinstance(d, dict) or not d.get("country"):
        raise ValueError("meta.json sans pays")
    pays = d.get("ships_to_countries")
    # « * » : tous les pays (KBS, meta.json du 23/11/2026)
    return {"pays": d["country"], "devise": d.get("currency"),
            "livre_france": ("FR" in pays or "*" in pays) if isinstance(pays, list) else None}


def lire_trustedshops(ts_id: str) -> dict:
    d = json.loads(_page(TRUSTEDSHOPS.format(ts_id)))
    ind = d["response"]["data"]["shop"]["qualityIndicators"]["reviewIndicator"]
    return {"note": float(ind["overallMark"]), "nombre": int(ind["activeReviewCount"]),
            "periode_j": int(ind.get("activePeriodInDays") or 365), "plateforme": "Trusted Shops", "verifies": True}


def avis_affiches(page: str) -> dict | None:
    """Avis affichés par la boutique sur sa page d'accueil : badge Judge.me, sinon aggregateRating (JSON-LD)."""
    note = _JUDGEME_NOTE.search(page)   # badge « toutes les avis » : le nombre suit dans le même bloc
    nombre = _JUDGEME_NOMBRE.search(page, note.end(), note.end() + 1500) if note else None
    if note and nombre and int(nombre.group(1)) > 0:
        return {"note": float(note.group(1)), "nombre": int(nombre.group(1)), "plateforme": "Judge.me (avis affichés par la boutique)",
                "verifies": False}
    for bloc in re.findall(r"<script[^>]+application/ld\+json[^>]*>(.*?)</script>", page, re.S | re.I):
        try:
            d = json.loads(bloc)
        except ValueError:
            continue
        for x in (d if isinstance(d, list) else [d]):
            agr = isinstance(x, dict) and x.get("@type") in ("Organization", "Store", "OnlineStore", "LocalBusiness") \
                and x.get("aggregateRating")
            if isinstance(agr, dict):
                try:
                    return {"note": float(agr["ratingValue"]), "nombre": int(agr.get("reviewCount") or agr.get("ratingCount")),
                            "plateforme": "avis affichés par la boutique", "verifies": False}
                except (KeyError, TypeError, ValueError):
                    pass
    return None


_FRANCE = re.compile(r"France|Frankreich|Francia", re.I)
_EUROPE = re.compile(r"Europe|Europa|Union européenne|EU-Länder|EU countries|\bEU\b", re.I)
FENETRE = 300   # caractères lus après le nom du pays ou de la zone


def delai(texte: str, page_france: bool = False) -> str | None:
    """Délai de livraison vers la France : premier délai écrit dans les FENETRE caractères qui suivent
    « France » (ou Frankreich), sinon qui suivent « Europe » (ou EU, Europa) ; « 1 à 3 jours ouvrés ».
    Un délai écrit sans pays ni zone n'est pas pris (souvent un délai de préparation ou d'un autre pays),
    sauf sur une page propre à la France (`page_france`), où le premier délai écrit est pris."""
    m = _DELAI.search(texte) if page_france else None
    for zone in (() if m else (_FRANCE, _EUROPE)):
        for z in zone.finditer(texte):
            m = _DELAI.search(texte[z.end():z.end() + FENETRE])
            if m:
                break
        if m:
            break
    if not m:
        return None
    a, z, unite = int(m.group(1)), int(m.group(2)), m.group(3).lower()
    if not 0 < a <= z <= 60:
        return None
    ouvres = any(w in unite for w in ("ouvr", "business", "working", "werk", "arbeit"))
    return f"{a} à {z} jours" + (" ouvrés" if ouvres else "")


def corps_politique(page: str) -> str:
    """Texte d'une page de conditions : le corps de la politique Shopify s'il y en a un (le reste de la page,
    panier, bandeaux et scripts, porte d'autres délais), sinon toute la page."""
    i = page.find("shopify-policy__body")
    return n.texte(page[i:i + 80000] if i >= 0 else page)


_AUTRE_PAYS = re.compile(r"\b(?:Germany|Deutschland|Allemagne|Austria|Österreich|Autriche|Belgium|Belgique|Belgien|Netherlands|"
                         r"Niederlande|Pays-Bas|Italy|Italie|Italien|Spain|Espagne|Spanien|Switzerland|Schweiz|Suisse|Poland|Polen|"
                         r"Pologne|Luxembourg|Denmark|Dänemark|Danemark|Sweden|Schweden|Suède|United Kingdom|Royaume-Uni|Europe|EU)\b")


def _jusqu_au_pays_suivant(fenetre: str) -> str:
    """Fenêtre qui suit « France », coupée au nom du pays ou de la zone suivant (« France €9.95 Austria €12.95
    free from €199 » : le seuil de l'Autriche n'est pas celui de la France)."""
    m = _AUTRE_PAYS.search(fenetre)
    return fenetre[:m.start()] if m else fenetre


def port_et_seuil(texte: str, page_france: bool = False) -> tuple[float | None, float | None]:
    """Port vers la France et seuil de gratuité. Port : montant qui suit « France » ; sur une page propre
    à la France, aussi « 3,90 € pour les commandes inférieures à 39 € ». Seuil : « gratuit dès 39 € »,
    « free from €99 »… dans les FENETRE caractères qui suivent « France » (toute la page si elle est
    propre à la France ; aussi « Orders up to 55 € have a delivery cost of 5.95 € »)."""
    port = livraison.port_du_pays(texte, "France")
    seuil = None
    zones = [texte] if page_france else [_jusqu_au_pays_suivant(texte[m.end():m.end() + FENETRE]) for m in _FRANCE.finditer(texte)]
    for z in zones:
        sous = _PORT_SOUS.search(z) if page_france else None
        if sous and port is None:
            port, seuil = float(sous.group(1).replace(",", ".")), float(sous.group(2))
        inverse = _SOUS_PORT.search(z) if page_france else None
        if inverse and port is None:
            seuil, port = float(inverse.group(1)), float(inverse.group(2).replace(",", "."))
        m = _SEUIL.search(z)
        if m and seuil is None:
            seuil = float((m.group(1) or m.group(2)).replace(",", "."))
        if port is not None and seuil is not None:
            break
    if port is not None and not 0 <= port <= livraison.PORT_MAX:
        port = None
    if seuil is not None and not (10 <= seuil <= 500 and (port is None or seuil > port)):
        seuil = None
    return port, seuil


def lire_livraison(url: str, page_france: bool = False) -> dict:
    page = _page(url)
    if _DEFI.search(page):
        raise ValueError("page anti-robot servie à la place du contenu")
    texte = corps_politique(page)
    out = {"delai": delai(texte, page_france), "tva_comprise": bool(_TVA.search(texte))}
    port, seuil = port_et_seuil(texte, page_france)
    if port is not None:
        out["port"] = port
        if re.search(r"€|\bEUR\b", texte):
            out["devise"] = "EUR"
    if seuil is not None:
        out["seuil"] = seuil
    return out


def lire_mentions(url: str) -> dict:
    """Mentions légales : pays du numéro de TVA intracommunautaire (où le vendeur acquitte la TVA)."""
    page = _page(url)
    if _DEFI.search(page):
        raise ValueError("page anti-robot servie à la place du contenu")
    texte = n.texte(page)
    m = next((x for x in _TVA_ID.finditer(texte) if sum(ch.isdigit() for ch in x.group(2)) >= 7), None) \
        or _CODE_POSTAL.search(texte)
    if not m:
        raise ValueError("ni numéro de TVA intracommunautaire, ni code postal à préfixe de pays")
    code = m.group(1).upper()
    return {"pays": "GR" if code == "EL" else code, "par": "tva" if m.re is _TVA_ID else "adresse"}


def relever(dossier: Path, pause: float = PAUSE_S, ids: list[str] | None = None) -> dict:
    """Relit les boutiques (`ids` : celles-là seulement) et écrit `boutiques_lues.json` :
    {id: {le, lus: {champ: {valeur, source, le}}, echecs, en_pause}}."""
    with VERROU:
        avant = _lire(Path(dossier) / "boutiques_lues.json", {})
        sources = _sources()
        connues = {b["id"] for b in configuration()}
        out = {k: v for k, v in avant.items() if k in connues}   # une boutique retirée de la liste ne reste pas
        for b in configuration():
            if ids is not None and b["id"] not in ids:
                continue
            ancien = avant.get(b["id"]) or {}
            lus, echecs, pauses = dict(ancien.get("lus") or {}), {}, []
            le = _horodatage()

            def garder(champ, valeur, source):
                if valeur is not None:
                    lus[champ] = {"valeur": valeur, "source": source, "le": le}

            def essai(nom, f):
                try:
                    r = f()
                    time.sleep(pause)
                    return r
                except Exception as e:   # refus, réseau, format inattendu : la valeur précédente reste
                    if getattr(e, "pause", False) or getattr(e, "statut", None) == 429:
                        pauses.append(nom)
                    echecs[nom] = cause(e) if not isinstance(e, ValueError) or getattr(e, "public", None) else str(e)
                    time.sleep(pause)
                    return None

            p, lire = urlsplit(b["url"]), set(b.get("lire") or ())
            meta = essai("meta", lambda: lire_meta(b)) if "meta" in lire else None
            if meta:
                for c in ("pays", "devise", "livre_france"):
                    garder(c, meta.get(c), f"{p.scheme}://{p.netloc}/meta.json")
            if b.get("trustedshops"):
                garder("avis", essai("avis", lambda: lire_trustedshops(b["trustedshops"])),
                       f"https://www.trustedshops.de/bewertung/info_{b['trustedshops']}.html")
            accueil = essai("accueil", lambda: _page(b["url"])) if "accueil" in lire else None
            if accueil and _DEFI.search(accueil):
                echecs["accueil"] = "page anti-robot servie à la place du contenu"
                accueil = None
            if accueil:
                if not b.get("trustedshops"):
                    garder("avis", avis_affiches(accueil), b["url"])
                if _TVA.search(n.texte(accueil)):
                    garder("tva_comprise", True, b["url"])
            page_liv = b.get("livraison_page") or ((sources.get(b.get("source") or "") or {}).get("livraison") or {}).get("page")
            if page_liv and "livraison" in lire:
                liv = essai("livraison", lambda: lire_livraison(page_liv, bool(b.get("livraison_france"))))
                if liv:
                    garder("delai", liv.get("delai"), page_liv)
                    garder("port", liv.get("port"), page_liv)
                    garder("seuil", liv.get("seuil"), page_liv)
                    if "devise" not in lus:   # une devise déjà lue (meta.json) n'est jamais remplacée par la page
                        garder("devise", liv.get("devise"), page_liv)
                    if liv.get("port") is not None and "meta" not in lire:   # port vers la France publié : la boutique y livre
                        garder("livre_france", True, page_liv)
                    if liv.get("tva_comprise"):
                        garder("tva_comprise", True, page_liv)
            if b.get("mentions_page") and "mentions" in lire:
                ment = essai("mentions", lambda: lire_mentions(b["mentions_page"]))
                if ment and not meta:   # meta.json, quand il répond, donne le pays du siège : il prime
                    garder("pays", ment["pays"], b["mentions_page"])
                    lus["pays"]["par"] = ment["par"]
            out[b["id"]] = {"le": le, "lus": lus, "echecs": echecs, **({"en_pause": True} if pauses else {})}
        _ecrire(Path(dossier) / "boutiques_lues.json", out)
        return out


# ----- fiche d'une boutique : lu, puis règles -----
def _champ(valeur, origine: str, source: str | None = None, le: str | None = None, methode: str | None = None) -> dict:
    d = {"valeur": valeur, "origine": origine}
    for k, v in (("source", source), ("le", le), ("methode", methode)):
        if v:
            d[k] = v
    return d


def fiabilite(avis: dict | None, livre_france: bool | None) -> tuple[int, str]:
    if livre_france is False:
        return 0, "ne livre pas la France"
    if not avis:
        return 1, "aucun avis lisible"
    note, nombre = avis.get("note") or 0, avis.get("nombre") or 0
    niveau = 3 if note >= 4.5 and nombre >= 200 else 2 if note >= 4.0 and nombre >= 50 else 1
    if not avis.get("verifies"):
        niveau = min(niveau, 2)
        return niveau, f"{note:.2f} sur 5, {nombre} avis affichés par la boutique (plafond 2)"
    return niveau, f"{note:.2f} sur 5, {nombre} avis vérifiés ({avis.get('plateforme')})"


def fiche(b: dict, lue: dict | None, source: dict | None = None, ports_lus: dict | None = None) -> dict:
    lus = (lue or {}).get("lus") or {}
    val = lambda c: (lus.get(c) or {}).get("valeur")
    champs: dict[str, dict] = {}
    for c in ("pays", "devise", "livre_france", "avis", "seuil"):
        if c in lus:
            x = lus[c]
            v = PAYS.get(x["valeur"], x["valeur"]) if c == "pays" else x["valeur"]
            methode = None
            if c == "pays" and x.get("source") == b.get("mentions_page"):
                methode = ("pays du numéro de TVA intracommunautaire" if x.get("par", "tva") == "tva"
                           else "préfixe de pays du code postal de l'adresse")
            champs[c] = _champ(v, "lu", x.get("source"), x.get("le"), methode)
    liv = (source or {}).get("livraison") or {}
    # port : page lue par ce relevé, sinon relevé de livraison.py (boutiques lues), sinon data/sources.json
    if "port" in lus:
        champs["port"] = _champ(lus["port"]["valeur"], "lu", lus["port"].get("source"), lus["port"].get("le"))
    elif source and (ports_lus or {}).get(source["id"]) is not None:
        champs["port"] = _champ(ports_lus[source["id"]], "lu", liv.get("page"))
    elif liv.get("port") is not None:   # valeur saisie le 20/11/2026 d'après la page : dite telle quelle
        champs["port"] = _champ(liv["port"], "écrit", liv.get("page"),
                                methode="relevé à la main le 20/11/2026 (data/sources.json)" + (", partiel" if liv.get("estime") else ""))
    if "delai" in lus:
        champs["delai"] = _champ(val("delai"), "lu", lus["delai"].get("source"), lus["delai"].get("le"))
    elif liv.get("delai"):
        champs["delai"] = _champ(liv["delai"], "écrit", liv.get("page"), methode="relevé à la main le 20/11/2026 (data/sources.json)")
    if b.get("type") == "place_de_marche":   # chaque vendeur a son port, son délai et son pays d'envoi
        for c in ("port", "delai", "douane"):
            if c not in champs:
                champs[c] = _champ("selon le vendeur", "règle", methode="place de marché : fixé par chaque vendeur")
    if val("livre_france") is False:   # ne livre pas la France : port, délai et douane sans objet, dit par une règle
        for c in ("port", "delai", "douane"):
            champs[c] = _champ("sans objet", "règle", lus["livre_france"].get("source"), methode="ne livre pas la France")
    pays = val("pays")
    if "delai" not in champs and pays:
        if pays in UE:
            champs["delai"] = _champ("2 à 6 jours ouvrés", "estimé", methode="envoi depuis l'Union européenne")
        elif pays in ("CN", "HK"):
            champs["delai"] = _champ("10 à 30 jours", "estimé", methode="envoi depuis la Chine")
    if pays and "douane" not in champs:
        if pays in UE:
            champs["douane"] = _champ("aucune", "règle", methode="vendeur dans l'Union européenne")
        elif val("tva_comprise"):
            champs["douane"] = _champ("TVA payée à la commande", "règle", lus["tva_comprise"].get("source"),
                                      methode="vendeur hors Union européenne, TVA comprise lue sur le site (guichet IOSS, colis de 150 € ou moins)")
        else:
            champs["douane"] = _champ("TVA et frais possibles à la livraison", "règle",
                                      methode="vendeur hors Union européenne, sans mention de TVA comprise")
    champs["boite"] = _champ({"boutique": "boîte d'origine", "place_de_marche": "selon le vendeur",
                              "pieces": "sans objet (pièces à l'unité)"}[b.get("type", "boutique")], "estimé",
                             methode="d'après le type de boutique")
    niveau, motif = fiabilite(val("avis"), val("livre_france"))
    champs["fiabilite"] = _champ(niveau, "règle", methode=motif)
    return {"id": b["id"], "nom": b["nom"], "url": b["url"], "hote": b["hote"], "type": b.get("type", "boutique"),
            "source": b.get("source"), "champs": champs, "manquants": [c for c in CHAMPS if c not in champs],
            "echecs": (lue or {}).get("echecs") or {}, "le": (lue or {}).get("le")}


def toutes(dossier: Path) -> dict:
    lues = _lire(Path(dossier) / "boutiques_lues.json", {})
    sources, ports = _sources(), livraison.ports_lus(dossier)
    liste = [fiche(b, lues.get(b["id"]), sources.get(b.get("source") or ""), ports) for b in configuration()]
    return {"boutiques": liste, "le": max((b["le"] for b in liste if b["le"]), default=None),
            "completes": sum(1 for b in liste if not b["manquants"]), "total": len(liste)}


def _instant(le: str | None) -> float:
    try:
        return time.mktime(time.strptime(le, "%Y-%m-%dT%H:%M:%S"))
    except (TypeError, ValueError):
        return 0.0


def a_relire(dossier: Path, maintenant: float) -> list[str]:
    """Boutiques à relire : relevé de plus de PERIODE_J jours, jamais relevées, ou dont une lecture a buté
    sur une pause après un 429 (relue une heure après)."""
    lues = _lire(Path(dossier) / "boutiques_lues.json", {})
    dues = []
    for b in configuration():
        r = lues.get(b["id"]) or {}
        age = maintenant - _instant(r.get("le"))
        if age > PERIODE_J * 86400 or (r.get("en_pause") and age > 3600):
            dues.append(b["id"])
    return dues


def demarrer(dossier: Path) -> None:
    """Chaque heure, relit les boutiques échues (`a_relire`) : 7 jours, ou une heure après une pause 429."""
    def boucle():
        time.sleep(180)
        while True:
            try:
                dues = a_relire(dossier, time.time())
                if dues:
                    r = relever(dossier, ids=dues)
                    log.info("boutiques relevées : %s, %s avec au moins un échec", len(dues),
                             sum(1 for i in dues if (r.get(i) or {}).get("echecs")))
            except Exception:
                log.exception("relevé des boutiques en échec")
            time.sleep(3600)
    threading.Thread(target=boucle, name="boutiques", daemon=True).start()

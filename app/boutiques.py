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
Une lecture en échec garde la dernière valeur lue, avec sa date ; l'échec est noté avec sa raison.

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


def lire_livraison(url: str, page_france: bool = False) -> dict:
    texte = corps_politique(_page(url))
    out = {"delai": delai(texte, page_france), "tva_comprise": bool(_TVA.search(texte))}
    port = livraison.port_du_pays(texte, "France")
    if port is not None and port <= livraison.PORT_MAX:
        out["port"] = port
    return out


def relever(dossier: Path, pause: float = PAUSE_S) -> dict:
    """Relit toutes les boutiques et écrit `boutiques_lues.json` : {id: {le, lus: {champ: {valeur, source, le}}, echecs}}."""
    with VERROU:
        avant = _lire(Path(dossier) / "boutiques_lues.json", {})
        sources = _sources()
        out = {}
        for b in configuration():
            ancien = avant.get(b["id"]) or {}
            lus, echecs = dict(ancien.get("lus") or {}), {}
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
                    echecs[nom] = getattr(e, "public", type(e).__name__)
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
                    if liv.get("tva_comprise"):
                        garder("tva_comprise", True, page_liv)
            out[b["id"]] = {"le": le, "lus": lus, "echecs": echecs}
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
    for c in ("pays", "devise", "livre_france", "avis"):
        if c in lus:
            x = lus[c]
            v = PAYS.get(x["valeur"], x["valeur"]) if c == "pays" else x["valeur"]
            champs[c] = _champ(v, "lu", x.get("source"), x.get("le"))
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
    pays = val("pays")
    if "delai" not in champs and pays:
        if pays in UE:
            champs["delai"] = _champ("2 à 6 jours ouvrés", "estimé", methode="envoi depuis l'Union européenne")
        elif pays in ("CN", "HK"):
            champs["delai"] = _champ("10 à 30 jours", "estimé", methode="envoi depuis la Chine")
    if pays:
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


def a_relire(dossier: Path, maintenant: float) -> bool:
    dates = [r.get("le") for r in _lire(Path(dossier) / "boutiques_lues.json", {}).values() if r.get("le")]
    if not dates:
        return True
    return maintenant - time.mktime(time.strptime(max(dates), "%Y-%m-%dT%H:%M:%S")) > PERIODE_J * 86400


def demarrer(dossier: Path) -> None:
    """Relevé au démarrage s'il date de plus de 7 jours, puis vérifié chaque jour."""
    def boucle():
        time.sleep(180)
        while True:
            try:
                if a_relire(dossier, time.time()):
                    r = relever(dossier)
                    log.info("boutiques relevées : %s, %s avec au moins un échec", len(r), sum(1 for x in r.values() if x["echecs"]))
            except Exception:
                log.exception("relevé des boutiques en échec")
            time.sleep(86400)
    threading.Thread(target=boucle, name="boutiques", daemon=True).start()

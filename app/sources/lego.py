"""LEGO officiel : catalogue de référence Rebrickable et prix français de BricksValue.

- Rebrickable publie chaque jour un export CSV de tous les sets (numéro, nom, année, thème,
  pièces, photo) ; réutilisation permise avec mention de la source. Gardé : 500 pièces et plus.
- BricksValue publie une fiche par set vendu en France, avec des données structurées (JSON-LD) :
  offres des revendeurs français (LEGO.com, Amazon.fr, Fnac, JouéClub…), âge, retrait, photos, et
  le relevé quotidien du prix de chaque revendeur. Ses conditions interdisent la collecte
  automatisée sans accord écrit ; BricksValue a donné son accord par courriel le 20/11/2026 pour
  un usage non commercial et raisonnable (API et JSON). La source reste désactivée par défaut dans
  le dépôt public et s'active par la variable SOURCES. Chaque fiche est lue par sa réponse de
  données (format React Server Components, `?_rsc` avec l'en-tête `RSC: 1` : 58 Ko au lieu de
  675 Ko pour la page), compressée, une à la fois, au rythme de la rotation (synchro.py) ; la page
  HTML sert de secours si cette réponse change de forme.
"""
from __future__ import annotations

import calendar
import csv
import gzip
import io
import json
import re
import time

from .. import lien, normalise as n

REBRICKABLE = "https://cdn.rebrickable.com/media/downloads/{}.csv.gz"
PLAN_FR = "https://bricksvalue.com/sitemaps/sitemap/fr.xml"
SEUIL_PIECES = 500


def _csv(nom: str) -> list[dict]:
    r = lien.recuperer(REBRICKABLE.format(nom), accept="application/gzip,*/*")
    brut = r.corps
    if brut[:2] == b"\x1f\x8b":
        brut = gzip.decompress(brut)
    return list(csv.DictReader(io.StringIO(brut.decode("utf-8"))))


def reference() -> dict[str, dict]:
    """Sets LEGO de 500 pièces et plus, par numéro sans suffixe (75192), avec leur thème racine."""
    themes = {t["id"]: t for t in _csv("themes")}

    def chemin(tid: str) -> list[str]:
        noms = []
        while tid and tid in themes:
            noms.append(themes[tid]["name"])
            tid = themes[tid]["parent_id"]
        return noms[::-1]
    out = {}
    for s in _csv("sets"):
        num, _, version = s["set_num"].partition("-")
        if version != "1" or not num.isdigit():
            continue
        try:
            pieces = int(s["num_parts"])
        except ValueError:
            continue
        if pieces >= SEUIL_PIECES:
            out[num] = {"nom": s["name"], "annee": int(s["year"] or 0), "pieces": pieces,
                        "themes_lego": chemin(s["theme_id"]), "img": s["img_url"] or None}
    return out


def fiches() -> dict[str, str]:
    """Adresse de chaque fiche française de BricksValue, par numéro de set."""
    r = lien.recuperer(PLAN_FR, accept="application/xml,text/xml")
    out = {}
    for url in re.findall(r"<loc>(https://bricksvalue\.com/fr/set/(\d+)-[^<]*)</loc>", r.corps.decode("utf-8", "replace")):
        out[url[1]] = url[0]
    return out


SCHEMA_ORG = ("https://schema.org", "https://schema.org/", "http://schema.org", "http://schema.org/")


def _objets(texte: str, debut: str):
    """Objets JSON qui commencent par `debut` dans un texte (page ou réponse de données)."""
    dec = json.JSONDecoder()
    i = texte.find(debut)
    while i >= 0:
        try:
            yield dec.raw_decode(texte, i)[0]
        except ValueError:
            pass
        i = texte.find(debut, i + len(debut))


def _produit(page: str) -> dict | None:
    blocs = re.findall(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', page, re.S | re.I)
    candidats = []
    for bloc in blocs:
        try:
            candidats.append(json.loads(bloc.strip()))
        except ValueError:
            continue
    candidats += [o for o in _objets(page, '{"@context"') if isinstance(o, dict) and o.get("@context") in SCHEMA_ORG]
    for d in candidats:
        for g in d.get("@graph", [d]) if isinstance(d, dict) else d:
            if isinstance(g, dict) and g.get("@type") == "Product":
                return g
    return None


def _serie(texte: str) -> dict | None:
    """Relevé quotidien des prix par revendeur : {"days": [{"t": ms, "<revendeur>": centimes|None}], "stores": [...]}."""
    for o in _objets(texte, '{"series":'):
        s = o.get("series") if isinstance(o, dict) else None
        if isinstance(s, dict) and isinstance(s.get("days"), list) and isinstance(s.get("stores"), list):
            return s
    return None


def _cle_revendeur(nom: str) -> str:
    return re.sub(r"[^a-z0-9]", "", n.sans_accents(nom))


def _derniers_releves(serie: dict | None) -> dict[str, str]:
    """Jour (AAAA-MM-JJ) du dernier relevé de chaque revendeur dans la série de BricksValue."""
    out: dict[str, str] = {}
    for jour in (serie or {}).get("days", []):
        t = jour.get("t")
        if not isinstance(t, (int, float)):
            continue
        date = time.strftime("%Y-%m-%d", time.gmtime(t / 1000))
        for s in serie.get("stores", []):
            if jour.get(s) is not None and date > out.get(s, ""):
                out[s] = date
    return out


def _releve_pour(vendeur: str, releves: dict[str, str]) -> str | None:
    """Jour du relevé du revendeur : identifiant égal au nom (« kingjouet » pour King Jouet), sinon le plus
    long identifiant contenu dans le nom (« lego » pour LEGO.com) ; aucun si rien ne correspond."""
    v = _cle_revendeur(vendeur)
    cles = {_cle_revendeur(s): date for s, date in releves.items() if _cle_revendeur(s)}
    if v in cles:
        return cles[v]
    contenus = sorted((c for c in cles if c in v), key=len, reverse=True)
    return cles[contenus[0]] if contenus else None


_PUBLIE = re.compile(r'"dateModified"\s*:\s*"(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)(?:\.\d+)?Z"')


def _publie(texte: str) -> str | None:
    """Dernière publication de BricksValue (heure UTC, sans « Z » : AAAA-MM-JJTHH:MM:SS), lue dans le `dateModified` de la
    page : la même pour toutes les fiches (constat du 21/11/2026, 8 fiches : 2026-11-21T14:59:06Z), donc
    l'heure à laquelle le site a republié ses prix."""
    m = _PUBLIE.search(texte)
    return m.group(1) if m else None


def _jour_local(publie: str | None) -> str | None:
    """Jour local (fuseau du service) d'une publication donnée en heure UTC."""
    if not publie:
        return None
    return time.strftime("%Y-%m-%d", time.localtime(calendar.timegm(time.strptime(publie, "%Y-%m-%dT%H:%M:%S"))))


def _lire_donnees(url: str) -> tuple[dict | None, dict | None, str | None]:
    """(produit JSON-LD, série des prix, publication) d'une fiche : réponse de données d'abord, page HTML
    en secours. La série des prix n'est plus dans la fiche depuis novembre 2026 (constat du 21/11) : None."""
    try:
        r = lien.recuperer(url + ("&" if "?" in url else "?") + "_rsc", accept="text/x-component", entetes={"RSC": "1"})
        texte = r.corps.decode("utf-8", "replace")
        p = _produit(texte)
        if p:
            return p, _serie(texte), _publie(texte)
    except lien.LienRefuse as e:
        if getattr(e, "statut", None) == 429:
            raise
    r = lien.recuperer(url)
    texte = r.corps.decode("utf-8", "replace")
    return _produit(texte), _serie(texte), _publie(texte)


def _age(texte: str | None) -> int | None:
    m = re.search(r"\d+", texte or "")
    return int(m.group(0)) if m else None


def lire_fiche(num: str, url: str, ref: dict | None = None) -> dict:
    """Lit une fiche BricksValue. Rend {"adulte", "age", "publie", "offres": [...]}."""
    p, serie, publie = _lire_donnees(url)
    releves = _derniers_releves(serie)
    if not p:
        raise ValueError("fiche sans données structurées")
    props = {x.get("name"): x.get("value") for x in p.get("additionalProperty", []) if isinstance(x, dict)}
    ref = ref or {}
    pieces = props.get("Pièces") if isinstance(props.get("Pièces"), int) else ref.get("pieces")
    age = _age(str(props.get("Âge") or ""))
    nom = ref.get("nom") or re.sub(r"^LEGO\s+|\s+\d{4,6}$", "", p.get("name") or "").strip()
    categorie = (p.get("category") or "").split(">")[-1].strip()
    images = p.get("image") or []
    images = [x if isinstance(x, str) else (x or {}).get("url") for x in (images if isinstance(images, list) else [images])]
    images = [x for x in images if x][:8]
    img = ref.get("img") or (images[0] if images else None)
    themes = n.themes(nom, ref.get("themes_lego", []) + [categorie])
    retrait = props.get("Retrait")
    offres_ld = (p.get("offers") or {})
    offres_ld = offres_ld.get("offers", [offres_ld]) if isinstance(offres_ld, dict) else offres_ld
    offres = []
    for o in offres_ld or []:
        if not isinstance(o, dict) or o.get("priceCurrency", "EUR") != "EUR":
            continue
        try:
            prix = round(float(o.get("price")), 2)
        except (TypeError, ValueError):
            continue
        vendeur = ((o.get("seller") or {}).get("name") or "").strip() or n.sans_accents(o.get("url", ""))[:30]
        dispo = str(o.get("availability", ""))
        offres.append({
            "source": "bricksvalue", "boutique": vendeur, "pays": "France",
            "cle": f"bricksvalue:{num}:{re.sub(r'[^a-z0-9]+', '-', n.sans_accents(vendeur))}",
            "url": o.get("url"), "nom": nom, "marque": "LEGO officiel", "numero": num,
            "prix": prix, "devise": "EUR",
            "dispo": "vente" if "InStock" in dispo else "precommande" if "PreOrder" in dispo else "epuise",
            "img": img, "images": images, "pieces": pieces, "dims": None,
            # jour du dernier relevé du revendeur dans la série ; sans série, jour de la publication de BricksValue
            "releve": _releve_pour(vendeur, releves) or _jour_local(publie), "releve_par": "BricksValue",
            "type": "technic" if "Technic" in " ".join(ref.get("themes_lego", [])) + categorie else "classique",
            "themes": themes, "retrait": retrait if retrait and "Pas de retrait" not in retrait else None,
        })
    return {"adulte": (age or 0) >= 16 or (pieces or 0) >= 2000, "age": age, "publie": publie, "offres": offres}

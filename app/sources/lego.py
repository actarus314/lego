"""LEGO officiel : catalogue de référence Rebrickable et prix français de BricksValue.

- Rebrickable publie chaque jour un export CSV de tous les sets (numéro, nom, année, thème,
  pièces, photo) ; réutilisation permise avec mention de la source. Gardé : 500 pièces et plus.
- BricksValue publie une fiche par set vendu en France, avec des données structurées (JSON-LD) :
  offres des revendeurs français (LEGO.com, Amazon.fr, Fnac, JouéClub…), âge, retrait. Ses
  conditions interdisent la collecte automatisée sans accord écrit : la source est désactivée
  par défaut et s'active par la variable SOURCES. Seules les fiches publiques sont lues (jamais
  /api/, exclu par robots.txt), compressées, une à la fois, au rythme de la rotation (synchro.py).
"""
from __future__ import annotations

import csv
import gzip
import io
import json
import re

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


def _produit(page: str) -> dict | None:
    for bloc in re.findall(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', page, re.S | re.I):
        try:
            d = json.loads(bloc.strip())
        except ValueError:
            continue
        for g in d.get("@graph", [d]) if isinstance(d, dict) else d:
            if isinstance(g, dict) and g.get("@type") == "Product":
                return g
    return None


def _age(texte: str | None) -> int | None:
    m = re.search(r"\d+", texte or "")
    return int(m.group(0)) if m else None


def lire_fiche(num: str, url: str, ref: dict | None = None) -> dict:
    """Lit une fiche BricksValue. Rend {"adulte", "age", "retrait", "offres": [...]}."""
    r = lien.recuperer(url)
    p = _produit(r.corps.decode("utf-8", "replace"))
    if not p:
        raise ValueError("fiche sans données structurées")
    props = {x.get("name"): x.get("value") for x in p.get("additionalProperty", []) if isinstance(x, dict)}
    ref = ref or {}
    pieces = props.get("Pièces") if isinstance(props.get("Pièces"), int) else ref.get("pieces")
    age = _age(str(props.get("Âge") or ""))
    nom = ref.get("nom") or re.sub(r"^LEGO\s+|\s+\d{4,6}$", "", p.get("name") or "").strip()
    categorie = (p.get("category") or "").split(">")[-1].strip()
    images = p.get("image") or []
    img = ref.get("img") or (images[0] if isinstance(images, list) and images else images or None)
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
            "img": img, "pieces": pieces, "dims": None,
            "type": "technic" if "Technic" in " ".join(ref.get("themes_lego", [])) + categorie else "classique",
            "themes": themes, "retrait": retrait if retrait and "Pas de retrait" not in retrait else None,
        })
    return {"adulte": (age or 0) >= 16 or (pieces or 0) >= 2000, "age": age, "offres": offres}

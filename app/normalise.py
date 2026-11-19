"""Normalisation des produits venus des boutiques : marque, numéro, thèmes, type de briques,
pièces, dimensions, disponibilité, et décision « set pour adultes ».

Chaque connecteur produit des offres au même format ; ce module ne connaît aucune boutique.
"""
from __future__ import annotations

import html
import json
import re
import unicodedata
from functools import lru_cache
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent

# Marques reconnues : forme canonique par alias (minuscules, sans accents).
MARQUES = {
    "lego": "LEGO officiel", "mould king": "Mould King", "mouldking": "Mould King", "cada": "CaDA",
    "doublee_cada": "CaDA", "double e": "CaDA", "reobrix": "Reobrix", "jie star": "JIE STAR", "jiestar": "JIE STAR",
    "bole brick": "Bole Brick", "bole": "Bole Brick", "xingbao": "Xingbao", "wange": "Wange", "guly": "Guly",
    "panlos": "Panlos", "cobi": "Cobi", "sembo": "Sembo", "lonestar bricks": "Lonestar", "lonestar": "Lonestar",
"lumibricks": "Lumibricks", "funwhole": "Funwhole", "pantasy": "Pantasy",
    "bluebrixx": "BlueBrixx", "moyu": "MOYU", "rastar": "Rastar", "xinzhuan": "Xinzhuan", "mork": "Mork",
    "kazi": "Kazi", "gobricks": "Gobricks", "tgl": "TGL", "im.master": "iM.Master", "ausini": "Ausini",
}
# Produits qui ne sont pas des sets : lots, pièces détachées, accessoires, éclairages, vitrines.
EXCLUS = re.compile(r"\b(bundle|accessor(y|ies)|zubeh[oö]r|partpacks?|einzelsteine|einzelteile|ersatzteile?|"
                    r"paxxs|light(ing)? kit|led[- ]?(set|kit|beleuchtung)|beleuchtung(sset)?|vitrine|display case|"
                    r"acryl|gutschein|gift card|geschenkkarte|grundplatte|baseplate|sticker)\b", re.I)


def sans_accents(t: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", t or "") if unicodedata.category(c) != "Mn").lower()


def texte(html_brut: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", html_brut or ""))).strip()


def marque(vendeur: str, titre: str = "") -> str | None:
    for source in (vendeur, titre):
        s = sans_accents(source).strip()
        if s in MARQUES:
            return MARQUES[s]
        for alias, nom in MARQUES.items():
            if re.search(r"\b" + re.escape(alias) + r"\b", s):
                return nom
    return None


_NUMERO = re.compile(r"\b(?:[A-Z]{1,3}[- ]?)?\d{4,6}[A-Z]?\b")


def numero(titre: str, sku: str | None = None) -> str | None:
    """Numéro du set (13199, C56032, JJ9093, 99007), pour regrouper les offres de plusieurs boutiques."""
    for cand in ([sku] if sku else []) + _NUMERO.findall(titre or ""):
        c = re.sub(r"[^A-Z0-9]", "", str(cand).upper().split("#")[0])
        c = re.sub(r"^(US|EU|DE|FR|UK|MK|REO|RB|PA|CB|XB|WG)(?=\d)", "", c)
        if re.fullmatch(r"[A-Z]{0,3}\d{4,6}[A-Z]?", c) and not re.fullmatch(r"(19|20)\d\d", c):
            return c
    return None


_PIECES = re.compile(r"(\d{1,2}[.,  ]?\d{3}|\d{2,4})\s*(?:pi[eè]ces|pieces|pcs|parts|bricks|teilen?|steinen?|"
                     r"klemmbausteinen?|bausteinen?|bauteilen?)\b", re.I)


def pieces(*textes: str) -> int | None:
    for t in textes:
        m = _PIECES.search(t or "")
        if m:
            n = int(re.sub(r"\D", "", m.group(1)))
            if n >= 20:
                return n
    return None


_NB = r"(\d{1,3}(?:[.,]\d{1,2})?)"
_DIM_X = re.compile(_NB + r"\s*(?:cm)?\s*[x×*]\s*" + _NB + r"\s*(?:cm)?\s*(?:[x×*]\s*" + _NB + r")?\s*cm", re.I)
_DIM_LISTE = re.compile(r"(?:ma(?:ß|ss)e|dimensions?|abmessungen|size)\s*:?\s*" + _NB + r"\s*cm\s*[;,/]\s*" + _NB
                        + r"\s*cm(?:\s*[;,/]\s*" + _NB + r"\s*cm)?", re.I)
_DIM_LONG = re.compile(r"(?:about|approximately|nearly|around|etwa|ca\.?|rund|environ|plus de|over)\s*" + _NB
                       + r"\s*cm\s*(?:long|lang|de long|high|hoch|tall|de haut|wide|breit)", re.I)


def dimensions(t: str) -> list[float] | None:
    """Dimensions en cm, la plus grande en premier ; None si absentes ou nulles."""
    for motif in (_DIM_X, _DIM_LISTE):
        m = motif.search(t or "")
        if m:
            d = sorted((float(x.replace(",", ".")) for x in m.groups() if x), reverse=True)
            if d and d[0] > 0:
                return d
    m = _DIM_LONG.search(t or "")
    if m:
        v = float(m.group(1).replace(",", "."))
        return [v] if v > 0 else None
    return None


@lru_cache(maxsize=1)
def _themes() -> list[dict]:
    d = json.loads((RACINE / "data" / "themes.json").read_text("utf-8"))
    out = []
    for t in d["themes"]:
        mots = [sans_accents(m) for m in t["mots"]]
        out.append({"id": t["id"], "nom": t["nom"],
                    "etiquettes": [sans_accents(e) for e in t["etiquettes"]],
                    "motif": re.compile(r"(?<!\w)(" + "|".join(re.escape(m) for m in mots) + r")(?!\w)")})
    return out


def themes_disponibles() -> list[dict]:
    """Thèmes et leurs mots-clés sans accents (la page s'en sert comme dictionnaire de recherche)."""
    d = json.loads((RACINE / "data" / "themes.json").read_text("utf-8"))
    return [{"id": t["id"], "nom": t["nom"], "mots": sorted({sans_accents(m) for m in t["mots"]})} for t in d["themes"]]


def themes(titre: str, etiquettes: list[str] | tuple = (), categorie: str = "") -> list[str]:
    tags = [sans_accents(e) for e in etiquettes] + [sans_accents(categorie)]
    nom = sans_accents(titre)
    trouves = []
    for t in _themes():
        if any(e in tag for tag in tags for e in t["etiquettes"]) or t["motif"].search(nom):
            trouves.append(t["id"])
    return trouves


def type_briques(type_produit: str = "", etiquettes: list[str] | tuple = (), titre: str = "") -> str | None:
    s = sans_accents(" ".join([type_produit, titre, *etiquettes]))
    if re.search(r"techni[ck]", s):
        return "technic"
    if re.search(r"brick ?build|brick building|building brick|klemmbaustein|modular", s):
        return "classique"
    return None


def disponibilite(disponible: bool, etiquettes: list[str] | tuple = (), titre: str = "") -> str:
    if not disponible:
        return "epuise"
    s = sans_accents(" ".join([titre, *etiquettes]))
    if re.search(r"vorbestell|pre-?order|precommande|precommande", s):
        return "precommande"
    return "vente"


def pour_adultes(nb_pieces: int | None, prix: float | None, titre: str, type_produit: str = "",
                 etiquettes: list[str] | tuple = (), seuil_pieces: int = 500, seuil_prix: float = 50.0) -> bool:
    if EXCLUS.search(" ".join([titre, type_produit, *etiquettes])):
        return False
    if nb_pieces is not None:
        return nb_pieces >= seuil_pieces
    return prix is not None and prix >= seuil_prix

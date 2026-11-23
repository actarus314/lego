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
    "panlos": "Panlos", "cobi": "Cobi", "sembo": "Sembo", "lonestar bricks": "Lonestar", "lonestar-bricks": "Lonestar", "lonestar": "Lonestar",
"lumibricks": "Lumibricks", "funwhole": "Funwhole", "pantasy": "Pantasy",
    "bluebrixx": "BlueBrixx", "moyu": "MOYU", "rastar": "Rastar", "xinzhuan": "Xinzhuan", "mork": "Mork",
    "kazi": "Kazi", "gobricks": "Gobricks", "tgl": "TGL", "im.master": "iM.Master", "ausini": "Ausini",
}
# Produits qui ne sont pas des sets : lots, pièces détachées, accessoires, éclairages, vitrines.
EXCLUS = re.compile(r"\b(bundle|accessor(y|ies)|zubeh[oö]r|partpacks?|einzelsteine|einzelteile|ersatzteile?|"
                    r"paxxs|light(ing)? kit|led[- ]?(set|kit|beleuchtung)|beleuchtung(sset)?|vitrine|display case|"
                    r"acryl|gutschein|gift card|geschenkkarte|grundplatte|baseplate|sticker|power function pack|power upgrade|"
                    r"motor (?:kit|set|pack)|fidget)\b", re.I)


def sans_accents(t: str) -> str:
    """Minuscules sans accents, apostrophes typographiques (’ ‘ ´) ramenées à « ' »."""
    t = re.sub("[\u2018\u2019\u00b4\u02bc]", "'", t or "")
    return "".join(c for c in unicodedata.normalize("NFD", t) if unicodedata.category(c) != "Mn").lower()


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


_DIM_APRES = re.compile(_NB + r"\s*cm\)?\s*(?:long|tall|high|wide|in length|in height|in width|length|height|width|"
                        r"lang|hoch|breit|de long|de haut|de large)\b", re.I)
_DIM_VERBE = re.compile(r"(?:measures?|measuring|stands?|standing(?: at)?|reaches|spans?|spanning|all|misst)\s+(?:in at\s+)?"
                        r"(?:about |approx\.? |approximately |nearly |over |around |up to )?"
                        r"(?:\d{1,3}(?:\.\d)?\s*(?:\"|”|in(?:ches)?)\s*\(\s*)?" + _NB + r"\s*cm\b", re.I)


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
    # Dimensions données une à une dans le texte (« At 44 cm long », « stands 53.9 cm tall »,
    # « Measuring 43 cm wide and 48 cm tall », « 75.7cm Length ») : jusqu'à trois, la plus grande d'abord.
    vals = [float(x.replace(",", ".")) for x in _DIM_APRES.findall(t or "") + _DIM_VERBE.findall(t or "")]
    vals = sorted({v for v in vals if 5 <= v <= 300}, reverse=True)[:3]
    return vals or None


def _mot(m: str) -> str:
    """Motif d'un mot-clé : mot entier ; « *panzer » accepte un mot composé qui finit par « panzer »
    (Jagdpanzer), « panzer* » un mot qui commence par lui (Panzerspähwagen)."""
    debut, fin = m.startswith("*"), m.endswith("*")
    coeur = re.escape(m.strip("*"))
    return (r"(?<!\w)\w*" if debut else r"(?<!\w)") + coeur + (r"\w*(?!\w)" if fin else r"(?!\w)")


@lru_cache(maxsize=1)
def _donnees_themes() -> dict:
    return json.loads((RACINE / "data" / "themes.json").read_text("utf-8"))


def _motifs(t: dict) -> dict:
    etq = [e for e in t.get("etiquettes", []) if e]
    return {"etiq": re.compile("|".join(r"(?<!\w)" + re.escape(sans_accents(e)) + r"(?!\w)" for e in etq)) if etq else None,
            "motif": re.compile("|".join(_mot(sans_accents(m)) for m in t["mots"])) if t.get("mots") else None}


@lru_cache(maxsize=1)
def _themes() -> list[dict]:
    return [{"id": t["id"], "nom": t["nom"], **_motifs(t)} for t in _donnees_themes()["themes"]]


@lru_cache(maxsize=1)
def _univers() -> list[dict]:
    return [{"id": u["id"], "nom": u["nom"], "sujet": u.get("sujet"), "rebrickable": set(u.get("rebrickable", [])),
             **_motifs(u)} for u in _donnees_themes().get("univers", [])]


def _rebrickable() -> dict[str, list[str]]:
    return {k: v for k, v in (_donnees_themes().get("rebrickable") or {}).items() if not k.startswith("_")}


@lru_cache(maxsize=1)
def ids_connus() -> tuple[frozenset, frozenset]:
    """Identifiants des thèmes et des univers déclarés."""
    d = _donnees_themes()
    return frozenset(t["id"] for t in d["themes"]), frozenset(u["id"] for u in d.get("univers", []))


def themes_disponibles() -> list[dict]:
    """Thèmes et leurs mots-clés sans accents (la page s'en sert comme dictionnaire de recherche)."""
    return [{"id": t["id"], "nom": t["nom"], "mots": sorted({sans_accents(m).strip("*") for m in t["mots"]})}
            for t in _donnees_themes()["themes"]]


def univers_disponibles() -> list[dict]:
    """Univers (licences et mondes de fiction) et leurs mots-clés sans accents."""
    return [{"id": u["id"], "nom": u["nom"], "mots": sorted({sans_accents(m).strip("*") for m in u["mots"]})}
            for u in _donnees_themes().get("univers", [])]


def _trouve(t: dict, tags: list[str], nom: str) -> bool:
    return bool((t["etiq"] and any(t["etiq"].search(tag) for tag in tags if tag)) or (t["motif"] and t["motif"].search(nom)))


def themes(titre: str, etiquettes: list[str] | tuple = (), categorie: str = "", chemin_lego: list[str] | tuple = ()) -> list[str]:
    """Thèmes-sujets d'un produit : étiquettes de la boutique et mots du nom (data/themes.json), puis
    correspondance des thèmes Rebrickable d'un set LEGO officiel (`chemin_lego`, racine d'abord)."""
    tags = [sans_accents(e) for e in list(etiquettes) + list(chemin_lego)] + [sans_accents(categorie)]
    nom = sans_accents(titre)
    table = _rebrickable()
    par_rb = {i for c in chemin_lego for i in table.get(c, [])}
    return [t["id"] for t in _themes() if t["id"] in par_rb or _trouve(t, tags, nom)]


def univers(titre: str, etiquettes: list[str] | tuple = (), categorie: str = "", chemin_lego: list[str] | tuple = ()) -> list[str]:
    """Univers d'un produit (licence, monde de fiction) : chemin Rebrickable, mots du nom, et étiquettes de
    boutique quand l'univers en déclare (`etiquettes`, facultatif)."""
    tags = [sans_accents(e) for e in etiquettes] + [sans_accents(categorie)]
    nom = sans_accents(titre)
    return [u["id"] for u in _univers() if u["rebrickable"] & set(chemin_lego) or _trouve(u, tags, nom)]


def sujet_univers(ids: list[str]) -> str | None:
    """Thème par défaut du premier univers qui en déclare un (dans l'ordre de data/themes.json)."""
    return next((u["sujet"] for u in _univers() if u["id"] in ids and u.get("sujet")), None)


# Étiquettes de boutique qui désignent un type sans le nommer. Mesure du 21/11/2026 contre l'étalon des
# photos (766 sets tranchés au premier relevé ; data/types_photos.json en garde 812 après relecture des
# incertains). La mesure du 20/11 contre la catégorie de KBS était faussée : KBS classe « Technic set »
# 29 sets à picots sur 163 (82 % de justesse, signal gardé faute de mieux, après la série ; « Brickbuild-
# Set » : 105 classiques sur 108). Autres mesures : étiquette « Construction » de Mould King, 48 Technic
# sur 48 ; étiquettes classiques de Mould King, 99 sur 100. Écartées : « Construction & Heavy Duty »
# (43 sur 53), « Motorized Model Building Kit » (2 Technic sur 14), « Technic-Vehicles » (88 sur 132 :
# Mould King y range ses voitures « Creative Idea » à picots) ; le mot « Technic » ne compte donc que
# dans le nom du produit, pas dans ses étiquettes.
_ETIQ_TECHNIC = re.compile(r"^(construction)$")
_ETIQ_CLASSIQUE = re.compile(r"^(modular buildings|movie and anime|ships and pirates|mini-world|mini heavy duty|mini famous cars|"
                             r"mini city & decor|botanicals and home decor)$")
# Marques qui ne vendent que des briques classiques.
CLASSIQUE_SEULEMENT = {"Cobi", "Sembo", "Kazi"}


def type_briques(type_produit: str = "", etiquettes: list[str] | tuple = (), titre: str = "",
                 marque: str | None = None) -> str | None:
    """Technic, classique, ou None si rien ne permet de le dire. Ordre : catégorie de produit de la
    boutique, mot « Technic » du nom, mots classiques du nom et des étiquettes, étiquettes mesurées, marque."""
    pt = sans_accents(type_produit)
    if re.search(r"techni[ck]", pt):
        return "technic"
    if re.search(r"brick|block|baustein", pt):
        return "classique"
    if re.search(r"\btechni[ck]\b", sans_accents(titre)):   # « Technical » ne compte pas
        return "technic"
    s = sans_accents(" ".join([titre, *etiquettes]))
    if re.search(r"brick ?build|brick building|building brick|klemmbaustein|modular", s):
        return "classique"
    tags = [sans_accents(e).strip() for e in etiquettes]
    if any(_ETIQ_TECHNIC.match(t) for t in tags):
        return "technic"
    if any(_ETIQ_CLASSIQUE.match(t) for t in tags):
        return "classique"
    if marque in CLASSIQUE_SEULEMENT:
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


def numero_base(marque: str, num: str | None) -> str | None:
    """Numéro de regroupement : sans le préfixe ou le suffixe de variante d'une boutique
    (Reobrix R55013 = 55013, Wange W6211 = 6211, Mould King 13197S = 13197)."""
    if not num:
        return None
    b = re.sub(r"^[RW](?=\d{4,6}$)", "", num)
    return re.sub(r"(?<=\d)S$", "", b)


_TOUTES_MARQUES = sorted({*MARQUES, *(v.lower() for v in MARQUES.values()), "lego"}, key=len, reverse=True)
_MARQUE_RE = re.compile(r"(?<!\w)(" + "|".join(re.escape(m) for m in _TOUTES_MARQUES) + r")(?!\w)", re.I)


def nom_court(nom: str | None) -> str:
    """Nom lisible : sans marque, numéro, nombre de pièces ni « building set » répétés par les boutiques.
    Le nom des boutiques est souvent « marque numéro – nom – marque numéro » : la plus longue partie
    qui reste après nettoyage est gardée."""
    if not nom:
        return ""
    t = re.sub(r"\s+", " ", html.unescape(nom)).strip()
    parties = re.split(r"\s+[–—-]\s+|\s*\|\s*", t)

    def propre(x: str) -> str:
        x = re.sub(r"\([^)]*\)\s*$", "", x)
        x = re.sub(r"\b\d[\d.,]*\s*(?:pcs|cps|pieces|pièces|teile|stück)\b", "", x, flags=re.I)
        x = _MARQUE_RE.sub("", x)
        x = re.sub(r"(?<!\w)[A-Z]{0,2}-?\d{4,6}[A-Z]?(?:/\d{4,6})?(?!\w)", "", x)
        x = re.sub(r"\b(?:model )?building (?:set|kit|blocks?)\b|\bklemmbausteine?(?: set)?\b|\bbausatz\b", "", x, flags=re.I)
        return re.sub(r"\s+", " ", x).strip(" -–|,:;")
    candidats = [c for c in (propre(x) for x in parties) if len(re.sub(r"\W", "", c)) >= 3]
    return max(candidats, key=len) if candidats else t


@lru_cache(maxsize=1)
def _glossaire() -> dict:
    return json.loads((RACINE / "data" / "glossaire.json").read_text("utf-8"))


def _cle_de(mot: str) -> str:
    return sans_accents(mot.replace("ß", "ss").replace("ẞ", "ss")).strip(",;:()")


def traduire_de(nom: str) -> str | None:
    """Traduction mot à mot d'un nom allemand (`data/glossaire.json`) ; None si aucun nom commun n'est connu.
    Les mots inconnus (noms propres, modèles) restent tels quels ; un adjectif placé devant un nom passe
    après lui (« blaues Motorrad » → « moto bleue »), sauf grand, petit… (« Große Moschee » → « Grande mosquée »)."""
    g = _glossaire()
    sortie: list[tuple[str, str]] = []  # (mot, nature) : nature nom, adj, lien ou autre
    connus = 0
    bruts = (nom or "").split()
    cles = [_cle_de(b) for b in bruts]
    expressions = sorted(((e.split(), t) for e, t in g.get("expressions", {}).items()), key=lambda x: -len(x[0]))
    i = 0
    while i < len(bruts):
        brut, k = bruts[i], cles[i]
        fin = "," if brut.endswith(",") else ""
        trouve = next(((len(e), t) for e, t in expressions if cles[i:i + len(e)] == e), None)
        if trouve:
            sortie.append((trouve[1] + ("," if bruts[i + trouve[0] - 1].endswith(",") else ""), "nom"))
            connus += 1
            i += trouve[0]
            continue
        i += 1
        if k in g["mots"]:
            sortie.append((g["mots"][k] + fin, "nom"))
            connus += 1
        elif k in g["adjectifs"]:
            sortie.append((g["adjectifs"][k] + fin, "adj"))
        elif k in g["liaisons"]:
            sortie.append((g["liaisons"][k] + fin, "lien"))
        else:
            sortie.append((brut, "autre"))
    if not connus:
        return None
    mots = []
    i = 0
    while i < len(sortie):
        mot, nature = sortie[i]
        suivant = sortie[i + 1] if i + 1 < len(sortie) else None
        if nature == "adj" and suivant and suivant[1] == "nom" and mot not in g.get("prefixes", []):
            mots += [suivant[0], mot]
            i += 2
            continue
        mots.append(mot)
        i += 1
    texte = " ".join(mots)
    return texte[:1].upper() + texte[1:]

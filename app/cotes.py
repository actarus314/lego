"""Dimensions du modèle lues dans un texte (description d'une boutique, description de LEGO officiel).

Sans modèle de langue. Les cotes sont ramenées en centimètres (`app/cotes_unites.py`), puis :
- trois cotes ensemble (« 45 x 22 x 13 cm », « Maße : 29 cm; 21,6 cm; 4,5 cm »), sauf celles d'un objet joint ;
- sinon cotes une à une. Le texte est coupé en propositions (phrase, « ; », « / », point de liste) puis en mots ;
  chaque cote est rattachée à un axe (longueur, hauteur, largeur, profondeur) par le nom d'axe qui la précède
  (« width of 70 cm », « Height: 40 cm », « hauteur de 30 cm ») ou par le mot d'axe qui la suit (« 44 cm long »,
  « 21 cm de haut »). Un nom d'axe entre deux cotes est l'étiquette de la suivante s'il en est séparé par « : »
  ou « of », sinon il suit l'ordre de la proposition : étiquette d'abord (« Length 45 cm Width 20 cm ») ou cote
  d'abord (« 128 cm Height 134 cm »). Un verbe de mesure donne une cote ; un verbe de hauteur, une hauteur.
Règles nommées qui écartent une cote : pièce ou objet joint (`PIECES`) collé à son nom d'axe, à son verbe ou aux
trois cotes, des mots de liaison seuls entre eux (« Wheel width 6 cm », « Each wheel has a width of 6 cm »,
« The stand is 45 cm long », « … cm baseplate ») ; nom d'axe suivi de « of the » et d'une pièce (« Height of the
Crane Arm ») ; cote suivie de « diameter ». Une pièce complément du modèle (« The motorcycle with wheels has a
length of 45 cm ») ou comprise (« Socle compris ») n'écarte rien. Devant un nom d'axe, un mot inconnu fait d'elle
la cote d'une pièce, non lue (« Antenna height 20 cm »), sauf étiquette de liste en majuscule suivie de « : ».
Une cote par axe (la plus grande si l'axe est redit).

Filet de non-régression (décision du 23/11/2026) : la lecture de la v3.20.0, gardée telle quelle dans
`app/cotes_v320.py`, tourne aussi. Chaque cote lue ici (gardée, écartée par une règle nommée, ou redite plus petite
sur son axe) explique au plus une cote de la v3.20.0 ; une cote de la v3.20.0 non expliquée est ajoutée si le
texte la porte encore. Une cote juste de la v3.20.0 n'est perdue que par une règle nommée. Limites : une pièce
absente de la liste, ou séparée de sa cote par d'autres mots, donne une cote de pièce, comme en v3.20.0.
Étalon : `tests/test_carnet.py`, classe `Cotes`.
"""
from __future__ import annotations

import re
from collections import Counter

from . import cotes_v320
from .cotes_unites import en_cm

_NB = r"(\d{1,3}(?:[.,]\d{1,2})?)"
_DIM_X = re.compile(_NB + r"\s*(?:cm)?\s*[x×*]\s*" + _NB + r"\s*(?:cm)?\s*(?:[x×*]\s*" + _NB + r")?\s*cm", re.I)
_DIM_LISTE = re.compile(r"(?:ma(?:ß|ss)e|dimensions?|abmessungen|size)\s*:?\s*" + _NB + r"\s*cm\s*[;,/]\s*" + _NB
                        + r"\s*cm(?:\s*[;,/]\s*" + _NB + r"\s*cm)?", re.I)

# ----- vocabulaire -----
# nom d'axe : peut précéder sa cote (« width of 70 cm », « Höhe: 30 cm ») ou la suivre (« 75.7 cm Length »)
NOMS_AXE = {"length": "L", "länge": "L", "longueur": "L", "height": "H", "höhe": "H", "hauteur": "H",
            "width": "W", "breite": "W", "largeur": "W", "wingspan": "W", "spannweite": "W", "envergure": "W",
            "depth": "D", "tiefe": "D", "profondeur": "D"}
# adjectif d'axe : suit sa cote seulement (« 44 cm long », « 53.9 cm tall », « 21 cm de haut »)
ADJ_AXE = {"long": "L", "lang": "L", "tall": "H", "high": "H", "hoch": "H", "haut": "H", "wide": "W", "breit": "W",
           "large": "W", "deep": "D", "tief": "D"}
# mots sautés entre une cote et son axe : approximation, liaison, verbe d'état
_LIENS = {"of", "von", "de", "d", "du", "is", "ist", "est", "be", "about", "approx", "approximately", "nearly", "almost",
          "around", "over", "up", "to", "etwa", "ca", "rund", "knapp", "über", "environ", "plus", "près", "presque",
          "jusqu", "à", "total", "in", "en", "max", "maximum", "roughly", "just", "some", "only", "a", "an",
          "at", "staggering", "impressive", "massive", "whopping", "amazing", "einer", "eine", "ein", "une", "un"}
_PONCT_LIEN = {":", "=", "-", "–", ")", "("}
_VERBES = {"measures", "measure", "measured", "measuring", "stands", "stand", "standing", "reaches", "reaching", "spans",
           "spanning", "misst", "mesure", "mesurant", "atteint", "erreicht", "towering", "all", "overall"}
# verbe qui dit la hauteur : la cote qu'il donne est la hauteur (« At a towering 63cm », « stands 32.3 cm »)
VERBES_HAUTEUR = {"stands": "H", "stand": "H", "standing": "H", "towering": "H"}
# pièce ou objet joint : sa cote n'est pas celle du modèle (liste ouverte, limite dite plus haut)
PIECES = {
    "wheel", "wheels", "tire", "tires", "tyre", "tyres", "rad", "räder", "reifen", "roue", "roues", "pneu", "pneus",
    "cable", "cables", "kabel", "câble", "câbles", "rope", "seil", "corde", "cord", "track", "tracks", "rail", "schiene",
    "stand", "sockel", "socle", "support", "baseplate", "grundplatte",
    "barrel", "lauf", "canon", "gun", "cannon", "kanone", "rohr", "muzzle", "blade", "klinge", "lame",
    "chenille", "chenilles", "suspension", "travel",
    "lift", "hub", "fork", "gabel", "fourche", "ladder", "leiter", "échelle", "présentoir",
    "minifigure", "minifigures", "minifig", "figurine", "figurines",
    "karton", "verpackung", "packaging", "package", "emballage", "carton",
    "manual", "instructions", "instruction", "anleitung", "notice", "booklet", "poster", "sticker", "stickers",
    "screen", "shell", "shells", "bullet", "bullets", "magazine", "cartridge", "door", "doors",
}
DIAMETRE = {"diameter", "durchmesser", "diamètre"}
# objet nommé juste après une cote suivie de son axe (« 7.6 cm wide stand ») : la cote est la sienne
APRES_AXE = {"stand", "sockel", "socle", "baseplate", "cable", "rope", "barrel", "blade", "screen"}
# mot du modèle : la cote qui suit est celle du modèle même si une pièce a été nommée avant dans la phrase
MODELE = {"model", "modell", "modèle", "maquette", "set", "kit", "replica", "réplique", "nachbau", "build", "bauwerk",
          "vehicle", "fahrzeug", "véhicule", "train", "zug", "ship", "schiff", "navire", "car", "auto", "voiture",
          "truck", "lkw", "camion", "crane", "kran", "grue", "castle", "burg", "château", "building", "gebäude",
          "aircraft", "flugzeug", "avion", "plane", "tank", "panzer", "char", "locomotive", "lok", "lokomotive",
          "excavator", "bagger", "pelleteuse", "tractor", "traktor", "tracteur", "machine", "maschine", "robot",
          "sculpture", "skulptur", "statue", "diorama", "scene", "szene", "scène", "piece", "pièce", "structure",
          "tower", "turm", "tour", "bridge", "brücke", "pont", "house", "haus", "maison", "ride", "boat", "boot",
          "bateau", "rocket", "rakete", "fusée", "station", "sword", "schwert", "épée", "katana", "lightsaber",
          # en-tête d'une liste de cotes : ce qui suit décrit le modèle
          "dimensions", "dimension", "size", "maße", "masse", "abmessungen", "größe", "taille", "mesures", "aufgebaut"}

_FIN_PROP = re.compile(r"(?<=[.!?•])\s+(?=[A-ZÀ-ÖØ-Ý\"“(])|;\s*|\s/\s|\n+|\s[•·|]\s")
_JETON = re.compile(r"(?P<v>\d{1,3}(?:[.,]\d{1,2})?)\s*cm\b|(?P<n>\d[\d.,]*)|(?P<m>[^\W\d_]+)|(?P<p>[:=()\-–,])", re.I)


class _Jetons(list):
    """Jetons d'une proposition ; `maj` : indices des mots écrits avec une majuscule initiale."""
    maj: set


def _jetons(prop: str) -> list[tuple[str, str]]:
    out = _Jetons()
    out.maj = set()
    for m in _JETON.finditer(prop):
        if m.group("v"):
            out.append(("v", m.group("v")))
        elif m.group("n"):
            out.append(("n", m.group("n")))
        elif m.group("m"):
            if m.group("m")[0].isupper():
                out.maj.add(len(out))
            out.append(("m", m.group("m").lower()))
        else:
            out.append(("p", m.group("p")))
    return out


def _passe_lien(j: list, i: int, pas: int) -> int:
    """Indice du premier jeton après `i` (dans le sens `pas`) qui n'est ni un mot de liaison, ni une ponctuation de
    liaison, ni dans une parenthèse (« 91.2cm (nearly 1 meter) in length »)."""
    ouvre, ferme = ("(", ")") if pas > 0 else (")", "(")
    depart = i
    i += pas
    while 0 <= i < len(j) and abs(i - depart) <= 30:
        if j[i] == ("p", ouvre):
            k = i + pas
            while 0 <= k < len(j) and j[k] != ("p", ferme) and abs(k - i) <= 12:
                k += pas
            if 0 <= k < len(j) and j[k] == ("p", ferme):
                i = k + pas
                continue
            break
        if (j[i][0] == "m" and j[i][1] in _LIENS) or (j[i][0] == "p" and j[i][1] in _PONCT_LIEN):
            i += pas
            continue
        break
    return i


_POSSESSION = {"has", "have", "with", "hat", "mit", "a", "avec", "of", "von", "de", "d", "du"}
_DETERMINANTS = {"the", "an", "a", "la", "le", "les", "die", "der", "das", "each", "every", "its", "this", "that", "his",
                 "her", "their", "our", "your", "ce", "cette", "son", "sa", "ses", "dieser", "diese", "dieses", "sein", "seine"}
_COMPLEMENT = {"with", "on", "mit", "auf", "avec", "sur", "and", "und", "et", "including", "inklusive"}
# mot qui fait d'une « pièce » le nom du modèle (« Ferris wheel », « Riesenrad » est un seul mot)
_NOM_DU_MODELE = {"ferris"}


def _piece_collee(j: list, k: int) -> bool:
    """Une pièce ou un objet joint est-il nommé juste avant le jeton `k` (nom d'axe, verbe ou trois cotes) :
    « Wheel width », « rope of length », « Each wheel has a width », « a stand with a height », « La figurine
    mesure » ? Seuls des mots de liaison (has, with, a, the, of…) peuvent les séparer. N'est pas collée : une pièce
    complément du modèle (« The truck with wheels has a length », « The model on a stand stands ») ni une pièce
    qui nomme le modèle (« The Ferris wheel stands 63 cm »)."""
    k -= 1
    while k >= 0 and j[k][0] == "m" and (j[k][1] in _POSSESSION or j[k][1] in _DETERMINANTS):
        k -= 1
    if not (k >= 0 and j[k][0] == "m" and j[k][1] in PIECES):
        return False
    a = k - 1
    if a >= 0 and j[a][0] == "m" and j[a][1] in _NOM_DU_MODELE:
        return False
    return not _complement_du_modele(j, k)


_SUJETS_DE_STAND = {"will", "would", "can", "could", "may", "might", "must", "should", "to", "they", "we", "you", "i",
                    "models", "sets", "towers", "pillars", "figures", "buildings", "both", "all"}


def _nom_stand(j: list, p: int) -> bool:
    """« stand » est-il le socle plutôt que le verbe ? « stands » est toujours le verbe (« a build that stands 44 cm
    tall », « This stands 40 cm ») ; « stand » n'est le verbe qu'après un sujet ou un auxiliaire (« will stand »,
    « Models stand ») ; ailleurs il est le socle (« The stand is 10 cm », « Display stand is 45 cm »)."""
    if j[p][1] != "stand":
        return False
    avant = j[p - 1][1] if p >= 1 and j[p - 1][0] == "m" else None
    return not (avant and avant not in _DETERMINANTS and (avant in _SUJETS_DE_STAND or avant.endswith("s")))


# verbe qui introduit un objet joint : « Comes with a stand », « Includes a cable with a length »
_VERBES_JOINT = {"comes", "come", "includes", "include", "included", "including", "equipped", "ships", "supplied",
                 "delivered", "provided", "features", "featuring", "kommt", "enthält", "geliefert", "livré", "fourni",
                 "accompagné", "is", "are", "has", "have", "with"}


def _complement_du_modele(j: list, k: int) -> bool:
    """La pièce en `k` est-elle un complément du modèle (« The model on a stand », « The motorcycle with wheels »,
    « Bulldozer on tracks ») : introduite par with, on, and… après un nom, pas après un verbe d'objet joint ?"""
    a = k - 1
    while a >= 0 and j[a][0] == "m" and j[a][1] in _DETERMINANTS:
        a -= 1
    if not (a >= 1 and j[a][0] == "m" and j[a][1] in _COMPLEMENT):
        return False
    b = a - 1
    return (j[b][0] == "m" and j[b][1] not in _VERBES_JOINT and j[b][1] not in _DETERMINANTS and j[b][1] not in _LIENS
            and j[b][1] not in PIECES)


_PARTIES = {"arm", "boom", "jib", "mast", "ausleger", "flèche"}


def _axe_d_une_partie(j: list, k: int) -> bool:
    """Le nom d'axe en `k` est-il suivi de « of the <pièce> » (« Height of the Crane Arm ») ?"""
    if not (k + 1 < len(j) and j[k + 1][0] == "m" and j[k + 1][1] in ("of", "von", "de", "du", "der", "des")):
        return False
    return any(j[x][0] == "m" and (j[x][1] in PIECES or j[x][1] in _PARTIES) for x in range(k + 2, min(k + 6, len(j))))


# devant un nom d'axe sans « : », un mot que la lecture ne connaît pas en fait le nom d'une pièce (« Antenna height
# 20 cm », « Motor length 12 cm ») : la cote n'est pas lue ; mots qui laissent la cote au modèle
_AVANT_NOM_AXE = {"finished", "completed", "assembled", "built", "final", "overall", "total", "full", "whole", "entire",
                  "maximum", "max", "approximate", "approx", "large", "huge", "impressive", "massive", "s", "model", "modell",
                  "product", "item", "gesamt", "fertig", "aufgebaut", "and", "und", "et", "or", "oder", "ou",
                  "pcs", "pieces", "teile", "pièces", "bricks", "steine"}


_EXPLICITE = {"of", "von", "de", "d"}


def _etiquette_de_la_suivante(j: list, k: int, etiquettes_d_abord: bool) -> bool:
    """Le nom d'axe en `k` est-il l'étiquette de la cote qui le suit (« Width: 20 cm », « width of 20 cm ») plutôt
    que l'axe de la cote qui le précède (« 128 cm Height 134 cm ») ? Dans une proposition « cote d'abord », un nom
    placé juste après une cote, ou à un mot d'elle (« 134 cm Boom Length: 36.4 cm Base Width »), est l'axe de
    cette cote ; sinon il est l'étiquette de la suivante quand « : » ou « of » l'en sépare, ou quand aucune cote
    ne le précède juste avant."""
    s = _passe_lien(j, k, 1)
    if not (s < len(j) and j[s][0] == "v"):
        return False
    a = k - 1
    while a >= 0 and j[a] == ("p", ")"):
        a -= 1
    juste_apres_cote = a >= 0 and (j[a][0] == "v" or (j[a][0] == "m" and j[a][1] not in ADJ_AXE and j[a][1] not in NOMS_AXE
                                                      and a >= 1 and j[a - 1][0] == "v"))
    if not etiquettes_d_abord and juste_apres_cote:
        return False
    if any(j[x] == ("p", ":") or (j[x][0] == "m" and j[x][1] in _EXPLICITE) for x in range(k + 1, s)):
        return True
    return etiquettes_d_abord or not (a >= 0 and j[a][0] == "v")


def _etiquettes_d_abord(j: list) -> bool:
    """La proposition donne-t-elle le nom de l'axe avant la cote (« Length 45 cm Width 20 cm ») ?"""
    for genre, val in j:
        if genre == "v":
            return False
        if genre == "m" and val in NOMS_AXE:
            return True
    return False


def _une_a_une(texte: str) -> tuple[dict[str, float], list[float], list[float]]:
    """Cotes rattachées à un axe (la plus grande par axe), cotes sans axe, et cotes lues mais non gardées : écartées
    par une règle nommée (pièce collée à sa cote, diamètre, objet joint) ou redites sur un axe qui en a une plus
    grande, d'un texte en centimètres."""
    par_axe: dict[str, float] = {}
    sans_axe: list[float] = []
    ecartees: list[float] = []
    for prop in _FIN_PROP.split(texte):
        j = _jetons(prop)
        ordre = _etiquettes_d_abord(j)
        for i, (genre, val) in enumerate(j):
            if genre != "v":
                continue
            v = float(val.replace(",", "."))
            if not 5 <= v <= 300:
                continue
            axe = None
            p = _passe_lien(j, i, -1)
            s = _passe_lien(j, i, 1)
            verbe = p >= 0 and j[p][0] == "m" and j[p][1] in _VERBES
            if s < len(j) and j[s][0] == "m" and j[s][1] in DIAMETRE and not _etiquette_de_la_suivante(j, s, ordre):
                ecartees.append(v)   # « 40 cm in diameter » : une roue, un plateau, pas le modèle
                continue
            # axe qui précède : « width of 70 cm », « Height: 40 cm », « hauteur de 30 cm »
            if p >= 0 and j[p][0] == "m" and j[p][1] in NOMS_AXE and _etiquette_de_la_suivante(j, p, ordre):
                if _piece_collee(j, p):
                    ecartees.append(v)   # « Wheel width 6 cm », « Each wheel has a width of 6 cm »
                    continue
                w = j[p - 1] if p >= 1 else None
                etiquette_de_liste = p in j.maj and any(j[x] == ("p", ":") for x in range(p + 1, i))
                if (w and w[0] == "m" and not etiquette_de_liste and w[1] not in _AVANT_NOM_AXE and w[1] not in _DETERMINANTS
                        and w[1] not in _LIENS and w[1] not in _POSSESSION and w[1] not in MODELE
                        and w[1] not in ADJ_AXE and w[1] not in NOMS_AXE):
                    continue   # « Antenna height 20 cm » : nom composé inconnu, comme en v3.20.0
                axe = NOMS_AXE[j[p][1]]
            elif i >= 2 and j[i - 1] == ("p", "(") and j[i - 2][0] == "m" and j[i - 2][1] in ADJ_AXE:
                axe = ADJ_AXE[j[i - 2][1]]   # « over half a meter long (57.8cm) »
            elif (p >= 1 and j[p][0] == "m" and j[p][1] in ADJ_AXE and (q := _passe_lien(j, p, -1)) >= 0
                  and j[q][1] in _VERBES):
                axe = ADJ_AXE[j[p][1]]   # « stands tall at 40 cm »
            else:
                # axe qui suit : « 44 cm long », « 21 cm de haut », « 75.7 cm Length » (pas l'étiquette de la cote suivante)
                if s < len(j) and j[s][0] == "m":
                    if j[s][1] in ADJ_AXE:
                        axe = ADJ_AXE[j[s][1]]
                    elif j[s][1] in NOMS_AXE and not _etiquette_de_la_suivante(j, s, ordre):
                        if _axe_d_une_partie(j, s):
                            ecartees.append(v)   # « 80cm - Height of the Crane Arm » : la flèche, pas le modèle
                            continue
                        axe = NOMS_AXE[j[s][1]]
                    if axe and s + 1 < len(j) and j[s + 1][0] == "m" and j[s + 1][1] in APRES_AXE and not _objet_inclus(j, s + 1):
                        ecartees.append(v)   # « 7.6 cm wide stand »
                        continue
                if axe is None:
                    if not verbe:
                        continue   # sans axe, une cote ne compte que mesurée par un verbe
                    if _nom_stand(j, p) and _complement_du_modele(j, p):
                        continue   # « The model on a stand is 45 cm » : ni verbe ni sujet
                    if _piece_collee(j, p) or _nom_stand(j, p):
                        ecartees.append(v)   # « the stand measures 10 cm », « The stand is 10 cm »
                        continue
                    axe = VERBES_HAUTEUR.get(j[p][1])
            if verbe and _nom_stand(j, p):
                verbe = False   # « stand » est le socle, pas le verbe
                if p >= 1 and j[p - 1][0] == "m" and j[p - 1][1] in _DETERMINANTS and not _complement_du_modele(j, p):
                    ecartees.append(v)   # « The stand is 45 cm long » : le socle est le sujet
                    continue
            if axe:
                if axe in par_axe:
                    ecartees.append(min(v, par_axe[axe]))   # même axe redit : la plus petite est lue, non gardée
                par_axe[axe] = max(v, par_axe.get(axe, 0))
            if not axe or verbe:
                sans_axe.append(v)   # cote d'un verbe de mesure : gardée aussi sans axe (« A measures 60 cm long; B measures 54 cm long »)
    return par_axe, sans_axe, ecartees


def _avant_est_piece(t: str, debut: int) -> bool:
    """Trois cotes précédées juste avant d'une pièce ou d'un objet joint, ou de son verbe de mesure (« baseplate
    30 x 30 x 1 cm », « The instruction manual measures 30 x 21 cm »)."""
    j = _jetons(_FIN_PROP.split(t[max(0, debut - 200):debut])[-1])
    k = len(j)
    while k > 0 and j[k - 1][0] == "m" and j[k - 1][1] in _VERBES | _LIENS:
        k -= 1
    return _piece_collee(j + [("m", "")], k) if k < len(j) else _piece_collee(j + [("m", "")], len(j))


def _apres_est_piece(t: str, fin: int) -> bool:
    """Trois cotes suivies d'une pièce ou d'un objet joint (« 30.5 x 30.5 x 2.5 cm baseplate »), sauf compris dans
    la cote (« 45 x 22 x 13 cm Socle compris »)."""
    j = _jetons(t[fin:fin + 80])
    return bool(j and j[0][0] == "m" and j[0][1] in APRES_AXE and not _objet_inclus(j, 0))


INCLUS = {"compris", "inclus", "included", "including", "inclusive", "inklusive", "inkl", "incl"}


def _objet_inclus(j: list, k: int) -> bool:
    """L'objet joint en `k` est-il compris dans la cote (« Sockel inklusive ») ou le début d'un mot composé
    (« stand-alone ») ?"""
    return k + 1 < len(j) and (j[k + 1] == ("p", "-") or (j[k + 1][0] == "m" and j[k + 1][1] in INCLUS))


def _proche(v: float, valeurs) -> bool:
    """Même cote redite arrondie (57 et 56.9 cm) ?"""
    return any(abs(g - v) <= 0.016 * max(g, v) for g in valeurs)


def _ajouter_filet(texte: str, garde: list[float], lues: list[float], anciennes: list[float]) -> None:
    """Ajoute à `garde` les cotes de la v3.20.0 qu'aucune cote lue n'explique. Chaque cote lue (gardée, écartée par
    une règle nommée, ou redite plus petite sur son axe) explique au plus une cote de la v3.20.0 : la même d'abord,
    sinon une redite arrondie (1.6 % au plus). Une cote non expliquée n'est ajoutée que si le texte la porte encore
    une fois de plus que le résultat : « Length: 45 cm Width: 20 cm » (la v3.20.0 y lit 45 deux fois) ne gagne pas
    un second 45 ; « 45 cm long / Height 45.5 cm » garde 45.5."""
    libres = garde + lues
    restes = []
    for v in sorted(anciennes, reverse=True):
        if v in libres:
            libres.remove(v)
        else:
            restes.append(v)
    dans_le_texte = Counter(float(m.group(1).replace(",", ".")) for m in re.finditer(_NB + r"\s*cm\b", texte, re.I))
    for v in restes:
        proches = [g for g in libres if abs(g - v) <= 0.016 * max(g, v)]
        if proches:
            libres.remove(min(proches, key=lambda g: abs(g - v)))
        elif garde.count(v) < max(dans_le_texte[v], 1):
            garde.append(v)


_LONG_MOT = re.compile(r"[^\W\d_]{60,}")


def dimensions(t: str) -> list[float] | None:
    """Dimensions en cm, la plus grande en premier ; None si absentes ou nulles. Lecture d'`app/cotes.py`, complétée
    des cotes que la lecture de la v3.20.0 (`app/cotes_v320.py`) trouve en plus, sauf celles qu'une règle nommée
    écarte : aucune cote de la v3.20.0 n'est perdue sans une règle qui le dise."""
    # espaces réduits et mots de 60 lettres ou plus coupés (aucun mot réel n'y arrive) : pas de borne de longueur
    # (limite : une conversion en pouces reste quadratique sur un texte hostile, comme en v3.20.0)
    brut = _LONG_MOT.sub(" ", re.sub(r"\s+", " ", t or ""))
    t = en_cm(brut)
    ecartees: list[float] = []
    garde = None
    for motif in (_DIM_X, _DIM_LISTE):
        for m in motif.finditer(t):
            d = sorted((float(x.replace(",", ".")) for x in m.groups() if x), reverse=True)
            if not (d and d[0] > 0):
                continue
            if _avant_est_piece(t, m.start()) or _apres_est_piece(t, m.end()):
                ecartees += d   # « baseplate 30 x 30 x 1 cm », « The instruction manual measures 30 x 21 cm »
                continue
            garde = d
            break
        if garde:
            break
    if garde is None:
        par_axe, sans_axe, ecartees_une = _une_a_une(t)
        ecartees += ecartees_une
        garde = list(par_axe.values())
        for v in sorted(sans_axe, reverse=True):
            if not _proche(v, garde):
                garde.append(v)
            else:
                ecartees.append(v)   # redite arrondie d'une cote gardée : lue, non gardée
    # filet : cotes de la v3.20.0 absentes de la nouvelle lecture et qu'aucune règle nommée n'écarte
    _ajouter_filet(t, garde, ecartees, cotes_v320.dimensions(brut) or [])
    return sorted(garde, reverse=True)[:3] or None

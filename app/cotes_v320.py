"""Lecture des dimensions de la v3.20.0, gardée telle quelle comme filet de la lecture d'`app/cotes.py`.

Une cote que cette lecture trouve et que la nouvelle ne trouve pas est ajoutée au résultat, sauf si une règle nommée
de la nouvelle lecture l'a écartée (pièce collée à sa cote, diamètre, objet joint) : aucune cote juste de la v3.20.0
n'est perdue par construction. Ne pas modifier : ce fichier est la référence de non-régression.
"""
from __future__ import annotations

import re

from .cotes_unites import en_cm

_NB = r"(\d{1,3}(?:[.,]\d{1,2})?)"
_DIM_X = re.compile(_NB + r"\s*(?:cm)?\s*[x×*]\s*" + _NB + r"\s*(?:cm)?\s*(?:[x×*]\s*" + _NB + r")?\s*cm", re.I)
_DIM_LISTE = re.compile(r"(?:ma(?:ß|ss)e|dimensions?|abmessungen|size)\s*:?\s*" + _NB + r"\s*cm\s*[;,/]\s*" + _NB
                        + r"\s*cm(?:\s*[;,/]\s*" + _NB + r"\s*cm)?", re.I)
_ENV = r"(?:about|approx\.?|approximately|nearly|almost|around|over|up to|etwa|ca\.?|rund|knapp|über|environ|plus de|près de)"
# mot d'axe qui suit une cote (« 44 cm long », « 21 cm de haut ») ou la précède (« width of 70 cm »)
_AXE_APRES = (r"long|tall|high|wide|deep|in length|in height|in width|in depth|(?:total\s+)?length|height|width|depth|"
              r"lang|hoch|breit|tief|de long|de haut|de large|de longueur|de hauteur|de largeur|de profondeur|d'envergure")
_AXE_AVANT = r"height|width|length|depth|wingspan|höhe|länge|breite|tiefe|spannweite|hauteur|longueur|largeur|profondeur|envergure"
_AXES = (("L", r"long|length|lang|länge|longueur"), ("H", r"tall|high|height|hoch|höhe|haut|hauteur"),
         ("D", r"deep|depth|tief|tiefe|profondeur"), ("W", r"wide|width|breit|breite|large|largeur|wingspan|spannweite|envergure"))
_DIM_APRES = re.compile(_NB + r"\s*cm\)?\s*(" + _AXE_APRES + r")\b", re.I)
_DIM_VERBE = re.compile(r"(?:measures?|measuring|stands?|standing(?: at)?|reaches|spans?|spanning|all|misst|mesure)\s+(?:in at\s+)?"
                        r"(?:(?:about|approx\.?|approximately|nearly|almost|over|around|up to|roughly|just|some|a staggering|"
                        r"an impressive|a massive|a whopping|an amazing|at|plus de|près de|environ|etwa|über|rund)\s+){0,2}"
                        r"(?:\d{1,3}(?:\.\d)?\s*(?:\"|”|in(?:ches)?)\s*\(\s*)?" + _NB + r"\s*cm\b", re.I)
# cote précédée de son nom (« a finished width of 70 cm », « wingspan of around 70 cm », « Länge: 45 cm ») ;
# ni diamètre ni course (une pièce du modèle, pas le modèle)
# le mot qui précède le nom de l'axe dit si la cote est celle du modèle : déterminant ou mot du modèle
# (« a height of », « finished width of », « Model height: », « Länge: » en tête), jamais une pièce
# (« Wheel width », « cable length », « Stand height », « lift height »)
_AVANT_AXE = {"a", "an", "the", "its", "total", "overall", "finished", "completed", "model", "modell", "gesamt", "die", "der",
              "une", "la", "sa", "maximum", "impressive", "full", "whole"}
_DIM_NOM = re.compile(r"(?:([^\W\d_]+)\s+)?(?<![^\W\d_])(" + _AXE_AVANT + r")\s*(?:of|von|de|d')?\s*:?\s*(?:" + _ENV + r"\s*)?" + _NB + r"\s*cm\b", re.I)


def _axe(mot: str) -> str:
    return next(a for a, motif in _AXES if re.search(motif, mot, re.I))


def dimensions(t: str) -> list[float] | None:
    """Dimensions en cm, la plus grande en premier ; None si absentes ou nulles."""
    t = en_cm(t)
    for motif in (_DIM_X, _DIM_LISTE):
        m = motif.search(t)
        if m:
            d = sorted((float(x.replace(",", ".")) for x in m.groups() if x), reverse=True)
            if d and d[0] > 0:
                return d
    # Dimensions données une à une dans le texte (« At 44 cm long », « stands 53.9 cm tall », « Mesure plus
    # de 21 cm de haut, 84 cm de long et 60 cm de large », « 75.7cm Length », « a finished width of
    # 70 cm ») : jusqu'à trois, la plus grande d'abord.
    # Une cote par axe nommé (longueur, hauteur, largeur, profondeur : la plus grande s'il est redit) ; une
    # cote sans axe (« stands 32.3 cm ») est gardée si elle ne redit pas, arrondie, une cote déjà gardée.
    ok = lambda v: 5 <= v <= 300
    par_axe: dict[str, float] = {}
    nommees = [(x, m) for avant, m, x in _DIM_NOM.findall(t) if not avant or avant.lower() in _AVANT_AXE]
    for v, mot in [(x, m) for x, m in _DIM_APRES.findall(t)] + nommees:
        v = float(v.replace(",", "."))
        if ok(v):
            a = _axe(mot)
            par_axe[a] = max(v, par_axe.get(a, 0))
    garde = list(par_axe.values())
    for v in sorted((float(x.replace(",", ".")) for x in _DIM_VERBE.findall(t)), reverse=True):
        if ok(v) and all(abs(g - v) > 0.016 * g for g in garde):   # même cote redite arrondie (57 et 56.9 cm) : une fois
            garde.append(v)
    return sorted(garde, reverse=True)[:3] or None

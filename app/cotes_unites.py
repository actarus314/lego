"""Cotes ramenées en centimètres (pouces, millimètres, équivalents entre parenthèses, repères d'axe), pour les
lectures d'`app/cotes.py` et d'`app/cotes_v320.py`."""
from __future__ import annotations

import re

_EN_CM = re.compile(r"(\d{1,3}(?:[.,]\d{1,2})?)\s*cm\s*\(\s*(?:[\w ]{0,12}?\s*)?\d{1,3}(?:[.,]\d{1,2})?\s*(?:in(?:ch(?:es)?)?\.?|\"|”|″)\s*\)", re.I)
_EN_POUCES_CM = re.compile(r"\d{1,3}(?:[.,]\d{1,2})?\s*(?:in(?:ch(?:es)?)?\.?|\"|”|″)\s*\(\s*(\d{1,3}(?:[.,]\d{1,2})?)\s*cm\s*\)", re.I)
_ETIQUETTE = re.compile(r"cm\s*\(\s*(?:l|w|h|d|b|t|length|width|height|depth|long|wide|high|tall|länge|breite|höhe|tiefe)\s*\)", re.I)
# millimètres : une cote seule à partir de 200 mm (une pièce du modèle, « Lauf 150 mm lang », un calibre
# « 7.62×51mm », « 90 mm gun » restent) ; trois cotes de 50 mm et plus chacune
_MM = re.compile(r"(?<![\d.,x×*])(?<![x×*]\s)(\d{1,2}[,.]\d{3}|\d{3,4})\s*mm\b", re.I)
_X_MM = re.compile(r"(?<![\d.,])(\d{2,4})\s*(?:mm)?\s*[x×*]\s*(\d{2,4})\s*(?:mm)?\s*[x×*]\s*(\d{2,4})\s*mm\b", re.I)
_X_POUCES = re.compile(r"(?<![\d.,])(\d{1,2}(?:[.,]\d{1,2})?)\s*[x×*]\s*(\d{1,2}(?:[.,]\d{1,2})?)(?:\s*[x×*]\s*(\d{1,2}(?:[.,]\d{1,2})?))?"
                       r"\s*(?:inches|inch|in\.|\"|”|″)(\s*\(\s*[^)]*\bcm\s*\))?", re.I)
_POUCES = re.compile(r"(?<![\d.,])(\d{1,2}(?:[.,]\d{1,2})?)\s*(?:inches|inch|in\.)(?!\w)", re.I)


def en_cm(t: str) -> str:
    """Texte aux cotes ramenées en centimètres : équivalent en pouces entre parenthèses retiré, repère
    d'axe retiré (« 28.7 cm (L) × 13.7 cm (W) »), millimètres et pouces convertis (« 1040 mm »,
    « 11 inches », « 16.5 x 8.7 x 5 inches »)."""
    # « 16.5 x 8.7 x 5 inches » : converti ; suivi de son équivalent en cm entre parenthèses, l'équivalent seul
    # reste ; deux cotes seules (« poster 24 x 36 in. », « 12 x 12 inches baseplate ») : un objet joint, retirées
    t = _X_POUCES.sub(lambda m: m.group(4).strip(" ()") if m.group(4) else
                      " x ".join(f"{float(x.replace(',', '.')) * 2.54:.1f}" for x in m.groups()[:3]) + " cm"
                      if m.group(3) else " ", t or "")
    # « 450 x 220 x 130 mm », « 450 mm x 220 mm x 130 mm » : converti si chaque cote fait au moins 50 mm
    t = _X_MM.sub(lambda m: " x ".join(f"{int(x) / 10:g}" for x in m.groups()) + " cm"
                  if all(int(x) >= 50 for x in m.groups()) else m.group(0), t)
    t = _MM.sub(lambda m: f"{v / 10:g} cm" if (v := int(re.sub(r"[,.]", "", m.group(1)))) >= 200 else m.group(0), t)
    t = _EN_CM.sub(r"\1 cm", t)
    t = _EN_POUCES_CM.sub(r"\1 cm", t)
    t = _ETIQUETTE.sub("cm", t)
    return _POUCES.sub(lambda m: f"{float(m.group(1).replace(',', '.')) * 2.54:.1f} cm", t)

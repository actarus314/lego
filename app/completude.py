"""Complétude du catalogue : pour chaque champ affiché, combien de sets ont une valeur mesurée à la
source, une valeur estimée (par une règle, marquée comme telle : thème par `themes_estimes`, type de
briques par `type_estime`, port par `port_estime` de la meilleure offre), ou aucune valeur.

Deux populations : tous les sets du catalogue, et ceux en vente ou en précommande (les épuisés
gardent souvent des données incomplètes sans gêner un achat). Le compte est servi en direct par
`/api/synchro` (`completude`, celui du dernier passage) et noté dans le journal à la fin de chaque
synchronisation ; la surveillance (surveillance.py) compare la part mesurée du dernier passage à celle
des passages précédents et prévient quand elle baisse (`degradations`).

Un champ « facultatif » (univers : un set sans licence n'en a pas) a des sets « sans valeur » qui ne
sont pas des manques ; il est compté sans être surveillé.
"""
from __future__ import annotations

import statistics

from .index import TYPES

# Baisse signalée : part mesurée (sets en vente) inférieure de 5 points ou plus à la médiane des passages
# précédents (deux au moins, cinq au plus), 10 sets au moins de moins qu'attendu, 20 sets en vente au moins.
# La part mesurée, et non renseignée : un set qui perd sa valeur lue reçoit souvent une estimation (thème,
# port), qui masquerait la baisse.
BAISSE_POINTS, BAISSE_SETS, HISTOIRE, MIN_SETS = 0.05, 10, 5, 20


def _meilleure(s: dict) -> dict:
    return (s.get("offres") or [{}])[0]


def _theme(s):
    if not s.get("themes"):
        return None
    return "estime" if s.get("themes_estimes") else "mesure"


def _univers(s):
    return "mesure" if s.get("univers") else None


def _type(s):
    if s.get("type") not in TYPES:
        return None
    return "estime" if s.get("type_estime") else "mesure"


def _dims(s):
    return "mesure" if s.get("dims") else None


def _avis(s):
    return "mesure" if s.get("tests") or s.get("avis") or s.get("liens_tests") or s.get("nb_tests") else None


def _port(s):
    o = _meilleure(s)
    if o.get("port") is None:
        return None
    return "estime" if o.get("port_estime") else "mesure"


def _delai(s):
    return "mesure" if _meilleure(s).get("delai") else None


# (clé, libellé, fonction, facultatif)
CHAMPS = (
    ("theme", "Thème", _theme, False),
    ("univers", "Univers", _univers, True),
    ("type", "Type de briques", _type, False),
    ("dimensions", "Dimensions", _dims, False),
    ("avis", "Avis", _avis, False),
    ("port", "Port", _port, False),
    ("delai", "Délai", _delai, False),
)


def compter(sets: list[dict]) -> dict:
    """{"sets", "en_vente", "champs": {clé: {"libelle", "facultatif", "tous": {...}, "en_vente": {...}}}},
    chaque population comptée en « mesure », « estime », « manque »."""
    vente = [s for s in sets if s.get("dispo") != "epuise"]
    champs = {}
    for cle, libelle, f, facultatif in CHAMPS:
        c = {"libelle": libelle, "facultatif": facultatif}
        for pop, liste in (("tous", sets), ("en_vente", vente)):
            n = {"mesure": 0, "estime": 0, "manque": 0}
            for s in liste:
                n[f(s) or "manque"] += 1
            c[pop] = n
        champs[cle] = c
    return {"sets": len(sets), "en_vente": len(vente), "champs": champs}


def _part(c: dict) -> tuple[int, int]:
    v = c.get("en_vente") or {}
    total = sum(v.get(k, 0) for k in ("mesure", "estime", "manque"))
    return v.get("mesure", 0), total


def degradations(historique: list[dict]) -> dict[str, str]:
    """{clé: message} des champs dont la part mesurée (sets en vente) a baissé au dernier passage,
    d'après les passages du journal (du plus récent au plus ancien) qui portent `completude`."""
    comptes = [p["completude"] for p in historique if isinstance(p.get("completude"), dict)]
    if len(comptes) < 3:
        return {}
    dernier, avant = comptes[0], comptes[1:1 + HISTOIRE]
    out = {}
    for cle, libelle, _, facultatif in CHAMPS:
        c = (dernier.get("champs") or {}).get(cle)
        if facultatif:   # sa part suit la composition du catalogue (sets sans licence ajoutés), pas une panne
            continue
        if not c:
            continue
        rens, total = _part(c)
        parts = []
        for a in avant:
            ca = (a.get("champs") or {}).get(cle)
            if ca:
                r, t = _part(ca)
                if t >= MIN_SETS:
                    parts.append(r / t)
        if len(parts) < 2 or total < MIN_SETS:
            continue
        attendue = statistics.median(parts)
        part = rens / total
        if part <= attendue - BAISSE_POINTS + 1e-9 and attendue * total - rens >= BAISSE_SETS - 1e-9:
            out[f"completude:{cle}"] = (f"{libelle} : {rens} sets en vente avec une valeur mesurée sur {total} au dernier passage "
                                        f"({round(100 * part)} %), contre {round(100 * attendue)} % d'habitude ; "
                                        "une source ou une règle a peut-être changé.")
    return out

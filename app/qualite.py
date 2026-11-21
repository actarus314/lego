"""Qualité des briques par marque : constats de sources indépendantes (`data/qualite.json`) et verdict
calculé par une règle fixe, la même pour toutes les marques.

Les constats ont été relevés une fois par recherche (tests, forums, avis d'acheteurs), critère par
critère, avec le lien et la date de chaque source ; ils ne sont pas relus par le service. Seuls les
trois critères du plastique (serrage, teintes, finition) comptent pour le verdict ; décors, notice,
pièces et fabricant sont montrés à côté.

Règle (seuils posés le 21/11/2026, sans mesure) : un constat compte s'il porte sur le plastique, s'il
date de ANNEE_MIN ou après et s'il ne vient pas de la marque elle-même. Le verdict ne lit que les
jugements d'ensemble, comparés au LEGO officiel : favorable (égal ou proche) ou défavorable (nettement
en retrait). Les défauts précis (une pièce rayée, une teinte fausse dans un set) sont comptés à part :
une marque très testée en accumule davantage, ce qui fausserait une comparaison entre marques.
Moins de JUGEMENTS_MIN jugements, ou moins de SITES_MIN sites différents : « Peu de sources ». Sinon,
selon la part de jugements défavorables : PROCHE_MAX au plus, « Proche du LEGO officiel » ;
INEGALE_MAX au plus, « Inégale » ; au-delà, « En retrait ».
"""
from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlsplit

RACINE = Path(__file__).resolve().parent.parent
PLASTIQUE = ("serrage", "teintes", "finition")
CRITERES = ("serrage", "teintes", "finition", "decors", "notice", "pieces", "fabricant")
FAVORABLE = {"comme_lego", "proche"}
DEFAVORABLE = {"en_retrait"}
DEFAUT = "probleme"
ANNEE_MIN = 2023
JUGEMENTS_MIN = 3
SITES_MIN = 2
PROCHE_MAX = 0.34
INEGALE_MAX = 0.6
VERDICTS = ("Proche du LEGO officiel", "Inégale", "En retrait", "Peu de sources")


# Un même auteur sous deux adresses compte pour un seul site ; un miroir compte pour l'original.
MEMES_SITES = {"merlinssteine.de": "merlinsbricks.com", "enmlounge.com": "reddit.com", "old.reddit.com": "reddit.com"}


def _site(url: str) -> str:
    h = (urlsplit(url).hostname or "").lower()
    h = h[4:] if h.startswith("www.") else h
    return MEMES_SITES.get(h, h)


def _annee(date: str) -> int | None:
    try:
        return int(str(date)[:4])
    except ValueError:
        return None


def compte(constat: dict) -> bool:
    """Vrai si le constat entre dans le verdict (jugement) ou dans le compte des défauts."""
    return (constat.get("critere") in PLASTIQUE and constat.get("rang") != "marque"
            and constat.get("sens") in FAVORABLE | DEFAVORABLE | {DEFAUT}
            and (_annee(constat.get("date", "")) or 0) >= ANNEE_MIN)


def verdict(constats: list[dict]) -> dict:
    """{verdict, favorables, defavorables, defauts, sites} selon la règle du module."""
    pris = [c for c in constats if compte(c)]
    jugements = [c for c in pris if c["sens"] != DEFAUT]
    defav = sum(c["sens"] in DEFAVORABLE for c in jugements)
    sites = len({_site(c.get("url", "")) for c in jugements} - {""})
    if len(jugements) < JUGEMENTS_MIN or sites < SITES_MIN:
        v = VERDICTS[3]
    else:
        part = defav / len(jugements)
        v = VERDICTS[0] if part <= PROCHE_MAX else VERDICTS[1] if part <= INEGALE_MAX else VERDICTS[2]
    return {"verdict": v, "favorables": len(jugements) - defav, "defavorables": defav,
            "defauts": len(pris) - len(jugements), "sites": sites}


def lire(chemin: Path | None = None) -> dict:
    return json.loads((chemin or RACINE / "data" / "qualite.json").read_text("utf-8"))


def pour_la_page(chemin: Path | None = None) -> dict:
    """{marque: {verdict, favorables, defavorables, sites, releve, remarque, constats}} ; constats
    triés par critère puis du plus récent au plus ancien, chacun marqué `compte`."""
    d = lire(chemin)
    sortie = {}
    for marque, m in d["marques"].items():
        constats = [c for c in m.get("constats", []) if str(c.get("url", "")).startswith("https://")]
        constats.sort(key=lambda c: str(c.get("date", "")), reverse=True)
        constats.sort(key=lambda c: CRITERES.index(c["critere"]) if c.get("critere") in CRITERES else len(CRITERES))
        sortie[marque] = {**verdict(constats), "releve": d.get("releve"), "remarque": m.get("remarque") or "",
                          "constats": [{**c, "compte": compte(c)} for c in constats]}
    return sortie

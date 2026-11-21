"""Qualité des briques par marque : constats de sources indépendantes (`data/qualite.json`) et verdict
calculé par une règle fixe, la même pour toutes les marques.

Les constats ont été relevés une fois par recherche (tests, forums, avis d'acheteurs), critère par
critère, avec le lien et la date de chaque source ; ils ne sont pas relus par le service. Seuls les
trois critères du plastique (serrage, teintes, finition) comptent pour le verdict ; décors, notice,
pièces et fabricant sont montrés à côté.

Règle (décision du 21/11/2026 : vote par site) : un constat compte s'il porte sur le
plastique, s'il date de ANNEE_MIN ou après et s'il ne vient ni d'une page commerciale ni d'une source liée à la
marque ou au revendeur (rangs « marque » et « lie »). Seuls les
jugements d'ensemble, comparés au LEGO officiel, votent : favorable (égal ou proche) ou défavorable
(nettement en retrait). Chaque site compte pour une voix, quel que soit son nombre d'articles (un
testeur très actif portait à lui seul 62 % des constats) : sa voix suit la majorité de ses jugements,
et un site à égalité ne vote pas. Verdict : aucun site qui vote, « Peu de sources » ; un seul,
« Un seul site » ; sinon « Favorable » si aucun site ne vote contre, « Défavorable » si aucun ne vote
pour, « Partagé » entre les deux. Les défauts précis (une pièce rayée, une teinte fausse dans un set)
ne votent pas, parce qu'une marque très testée en accumule davantage : ils sont comptés à part.
Jugement d'ensemble défavorable (« en_retrait ») : nettement en dessous du LEGO officiel, ou serrage,
teintes ou finition jugés mauvais dans l'ensemble ; défaut précis (« probleme ») : défaut décrit sur
des pièces ou un aspect, sans jugement d'ensemble. Un site est un nom d'hôte sans « www. » ; un même
auteur sous deux adresses, ou un miroir, compte pour un seul site (MEMES_SITES).
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
FAVORABLE_V, PARTAGE, DEFAVORABLE_V, UN_SITE, PEU = "Favorable", "Partagé", "Défavorable", "Un seul site", "Peu de sources"
VERDICTS = (FAVORABLE_V, PARTAGE, DEFAVORABLE_V, UN_SITE, PEU)
RANGS_EXCLUS = {"marque", "lie"}


# Un même auteur sous deux adresses compte pour un seul site ; un miroir compte pour l'original.
MEMES_SITES = {"merlinssteine.de": "merlinsbricks.com", "enmlounge.com": "reddit.com", "old.reddit.com": "reddit.com",
               "mochome.com": "sanwenwang.com"}


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
    return (constat.get("critere") in PLASTIQUE and constat.get("rang") not in RANGS_EXCLUS
            and constat.get("sens") in FAVORABLE | DEFAVORABLE | {DEFAUT}
            and (_annee(constat.get("date", "")) or 0) >= ANNEE_MIN)


def verdict(constats: list[dict]) -> dict:
    """{verdict, pour, contre, sites, favorables, defavorables, defauts} selon la règle du module :
    `pour` et `contre`, sites qui votent ; `sites`, sites qui jugent (égalités comprises)."""
    pris = [c for c in constats if compte(c) and _site(c.get("url", ""))]
    jugements = [c for c in pris if c["sens"] != DEFAUT]
    solde: dict[str, int] = {}
    for c in jugements:
        site = _site(c.get("url", ""))
        if site:
            solde[site] = solde.get(site, 0) + (1 if c["sens"] in FAVORABLE else -1)
    pour = sum(v > 0 for v in solde.values())
    contre = sum(v < 0 for v in solde.values())
    if pour + contre == 0:
        v = PEU
    elif pour + contre == 1:
        v = UN_SITE
    else:
        v = FAVORABLE_V if not contre else DEFAVORABLE_V if not pour else PARTAGE
    defav = sum(c["sens"] in DEFAVORABLE for c in jugements)
    return {"verdict": v, "pour": pour, "contre": contre, "sites": len(solde),
            "favorables": len(jugements) - defav, "defavorables": defav, "defauts": len(pris) - len(jugements)}


def lire(chemin: Path | None = None) -> dict:
    return json.loads((chemin or RACINE / "data" / "qualite.json").read_text("utf-8"))


_CACHE: dict = {}


def pour_la_page(chemin: Path | None = None) -> dict:
    """Comme calculer(), relu seulement quand le fichier change (la page est servie à chaque visite)."""
    chemin = chemin or RACINE / "data" / "qualite.json"
    cle = (str(chemin), chemin.stat().st_mtime_ns)
    if _CACHE.get("cle") != cle:
        _CACHE.update(cle=cle, valeur=calculer(chemin))
    return _CACHE["valeur"]


def calculer(chemin: Path | None = None) -> dict:
    """{marque: {verdict, pour, contre, sites, favorables, defavorables, defauts, releve, remarque,
    constats}} ; constats en https seulement, triés par critère puis du plus récent au plus ancien,
    chacun marqué `compte` ; ANNEE_MIN est rendue sous la clé « _annee_min »."""
    d = lire(chemin)
    sortie = {}
    for marque, m in d["marques"].items():
        constats = [c for c in m.get("constats", []) if str(c.get("url", "")).startswith("https://")]
        constats.sort(key=lambda c: str(c.get("date", "")), reverse=True)
        constats.sort(key=lambda c: CRITERES.index(c["critere"]) if c.get("critere") in CRITERES else len(CRITERES))
        sortie[marque] = {**verdict(constats), "releve": d.get("releve"), "remarque": m.get("remarque") or "",
                          "constats": [{k: c[k] for k in ("critere", "sens", "resume", "url", "date", "rang") if k in c}
                                       | {"compte": compte(c)} for c in constats]}
    return {"_annee_min": ANNEE_MIN, "marques": sortie}

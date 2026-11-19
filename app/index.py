"""Index du moteur de recherche : offres de chaque source, regroupées en sets.

Chaque source a son fichier `sources/<id>.json` dans le dossier de données (offres du dernier
passage réussi, date de première apparition de chaque produit). Le catalogue éditorial
(`data/catalogue.json` : noms français, tests indépendants, verdicts, sets LEGO officiel relevés
à la main) se superpose par marque et numéro, ou par adresse de la boutique.
"""
from __future__ import annotations

import json
import re
import threading
import time
from pathlib import Path

from . import normalise as n
from .donnees import _ecrire, _lire

RACINE = Path(__file__).resolve().parent.parent
VERROU = threading.RLock()
DISPO_RANG = {"vente": 0, "precommande": 1, "epuise": 2}
# Ordre de préférence pour le nom affiché d'un set vendu par plusieurs boutiques (anglais avant allemand).
PREFERENCE_NOM = ["editorial", "kbs", "mouldkingcorp", "bricksvalue", "bausteinreich"]


def sources_config() -> list[dict]:
    return json.loads((RACINE / "data" / "sources.json").read_text("utf-8"))["sources"]


def _cle_set(o: dict) -> str:
    return f"{n.sans_accents(o['marque'])}|{o['numero']}" if o.get("numero") else o["cle"]


def _slug(cle: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", n.sans_accents(cle)).strip("-")[:60]


class Index:
    def __init__(self, dossier: Path):
        self.dossier = Path(dossier) / "sources"
        self._cache: tuple[float, list] | None = None

    def fichier(self, source_id: str) -> Path:
        return self.dossier / f"{re.sub(r'[^a-z0-9_-]', '', source_id)}.json"

    def lire(self, source_id: str) -> dict:
        return _lire(self.fichier(source_id), {"offres": [], "vus": {}})

    def enregistrer(self, source_id: str, offres: list[dict]) -> dict:
        """Remplace les offres d'une source ; rend le nombre de nouveaux et de disparus."""
        with VERROU:
            ancien = self.lire(source_id)
            avant = {o["cle"] for o in ancien.get("offres", [])}
            apres = {o["cle"] for o in offres}
            vus = ancien.get("vus", {})
            aujourd_hui = time.strftime("%Y-%m-%d")
            for o in offres:
                o["depuis"] = vus.setdefault(o["cle"], aujourd_hui)
            _ecrire(self.fichier(source_id), {"le": time.strftime("%Y-%m-%dT%H:%M:%S"), "offres": offres, "vus": vus})
            self._cache = None
            return {"nouveaux": len(apres - avant) if avant else 0, "disparus": len(avant - apres)}

    def maj_offre(self, source_id: str, cle: str, champs: dict) -> None:
        """Met à jour une offre relue en direct (prix, disponibilité)."""
        with VERROU:
            d = self.lire(source_id)
            for o in d.get("offres", []):
                if o["cle"] == cle:
                    o.update(champs, releve=time.strftime("%Y-%m-%dT%H:%M:%S"))
            _ecrire(self.fichier(source_id), d)
            self._cache = None

    # ----- catalogue regroupé -----
    def sets(self, actives: list[str]) -> list[dict]:
        cle_cache = tuple(sorted(actives)), max((self.fichier(s).stat().st_mtime for s in actives
                                                  if self.fichier(s).exists()), default=0)
        if self._cache and self._cache[0] == cle_cache:
            return self._cache[1]
        conf = {s["id"]: s for s in sources_config()}
        offres = []
        for sid in actives:
            d = self.lire(sid)
            for o in d.get("offres", []):
                o.setdefault("releve", d.get("le"))
                liv = (conf.get(sid) or {}).get("livraison") or {}
                o["port"], o["delai"], o["port_estime"] = liv.get("port"), liv.get("delai"), liv.get("estime", False)
                offres.append(o)
        offres += editoriales()
        groupes: dict[str, list[dict]] = {}
        for o in offres:
            groupes.setdefault(_cle_set(o), []).append(o)
        edito = {e["cle"]: e for e in editorial()}
        for e in editorial():
            if e.get("cle_numero"):
                edito.setdefault(e["cle_numero"], e)
        out = [_set(cle, g, edito) for cle, g in groupes.items()]
        out = [s for s in out if s]
        self._cache = (cle_cache, out)
        return out


def _total(o: dict) -> float:
    return o["prix"] + (o.get("port") or 0)


def _set(cle: str, offres: list[dict], edito: dict) -> dict | None:
    offres.sort(key=lambda o: (DISPO_RANG[o["dispo"]], _total(o)))
    ed = next((edito[o["cle"]] for o in offres if o["cle"] in edito), None)
    if ed is None and offres[0].get("numero"):
        ed = edito.get(f"{n.sans_accents(offres[0]['marque'])}|{offres[0]['numero']}")
    par_pref = sorted(offres, key=lambda o: PREFERENCE_NOM.index(o["source"]) if o["source"] in PREFERENCE_NOM else 99)
    premier = lambda k: next((o.get(k) for o in par_pref if o.get(k)), None)
    meilleure = offres[0]
    themes = sorted({t for o in offres for t in o.get("themes", [])})
    s = {
        "id": _slug(cle), "nom": (ed or {}).get("nom") or _nom_court(premier("nom"), meilleure["marque"]),
        "marque": meilleure["marque"], "numero": premier("numero"),
        "themes": themes, "type": premier("type"), "pieces": premier("pieces"),
        "dims": (ed or {}).get("dims") or premier("dims"), "img": premier("img"),
        "dispo": meilleure["dispo"], "prix": meilleure["prix"], "port": meilleure.get("port"),
        "depuis": min((o.get("depuis") or "9999") for o in offres),
        "offres": [{k: o.get(k) for k in ("source", "boutique", "pays", "cle", "url", "prix", "port", "port_estime",
                                           "delai", "dispo", "releve")} for o in offres],
    }
    if ed:
        for k in ("tests", "avis", "tags", "retrait"):
            if ed.get(k):
                s[k] = ed[k]
    return s


def _nom_court(nom: str | None, marque: str) -> str:
    """Retire du nom la marque et le numéro répétés par les boutiques (« … – Mould King 13199 »)."""
    if not nom:
        return ""
    t = re.sub(r"\s*[-–|]\s*(" + re.escape(marque) + r"|mould king|cada|reobrix|jie star)[^-–|]*$", "", nom, flags=re.I)
    t = re.sub(r"^(" + re.escape(marque) + r"|mould king|cada|reobrix|jie star)\s+", "", t, flags=re.I)
    t = re.sub(r"\s*\((?:" + re.escape(marque) + r"|[^)]{2,20})\)\s*$", "", t)
    t = re.sub(r"\b(building (set|kit|blocks?)|klemmbausteine?( set)?|bausatz|set)\b.*$", "", t, flags=re.I).strip(" -–|(")
    t = re.sub(r"^(?:[A-Z]{0,3}[- ]?\d{4,6}[A-Z]?(?:/\d{4,6})?)\s*[-–]?\s*", "", t).strip()
    t = re.sub(r"^(" + re.escape(marque) + r")\s+", "", t, flags=re.I).strip()
    return t or nom


# ----- couche éditoriale -----
_EDITO: list | None = None


def editorial() -> list[dict]:
    """Sets du catalogue éditorial, avec la clé qui les rattache aux offres des boutiques."""
    global _EDITO
    if _EDITO is None:
        cat = json.loads((RACINE / "data" / "catalogue.json").read_text("utf-8"))
        _EDITO = []
        for it in cat:
            m = re.search(r"kbs-shop\.com/(?:\w\w/)?products/([^/?#]+)", it["url"])
            cle = f"kbs:{m.group(1)}" if m else f"{n.sans_accents(it['marque'])}|{n.numero(it.get('ref') or '', it.get('ref'))}"
            dims = sorted((float(x) for x in re.findall(r"\d+(?:\.\d+)?", it.get("dim") or "")), reverse=True) or None
            num = n.numero(it.get("ref") or "", it.get("ref"))
            _EDITO.append({**it, "cle": cle, "dims": dims,
                           "cle_numero": f"{n.sans_accents(it['marque'])}|{num}" if num else None})
    return _EDITO


def editoriales() -> list[dict]:
    """Offres du catalogue éditorial pour les sets qu'aucun connecteur ne couvre encore (LEGO officiel)."""
    out = []
    for it in editorial():
        if "lego.com" not in it["url"]:
            continue
        out.append({
            "source": "editorial", "boutique": "LEGO.com", "pays": "France", "cle": it["cle"], "url": it["url"],
            "nom": it["nom"], "marque": it["marque"], "numero": n.numero(it.get("ref") or "", it.get("ref")),
            "prix": it["prix"], "port": None, "delai": None,
            "dispo": "vente" if it.get("dispo", True) else "epuise",
            "img": it.get("img"), "pieces": it.get("pcs"), "dims": None,
            "type": "technic" if it.get("type") == "Technic" else "classique",
            "themes": n.themes(it["nom"] + " " + (it.get("theme") or ""), [it.get("theme") or ""]),
            "releve": "2026-11-19T00:00:00", "depuis": "2026-11-19",
        })
    return out


def sets_hors_ligne() -> list[dict]:
    """Sets de la page autonome : le seul catalogue éditorial, avec les prix relevés à la main."""
    offres = editoriales()
    for it in editorial():
        if "kbs-shop.com" in it["url"]:
            offres.append({
                "source": "kbs", "boutique": "KBS", "pays": "Allemagne", "cle": it["cle"], "url": it["url"],
                "nom": it["nom"], "marque": it["marque"], "numero": n.numero(it.get("ref") or "", it.get("ref")),
                "prix": it["prix"], "port": 4.95, "delai": "1 à 3 jours",
                "dispo": "precommande" if it.get("precommande") else "vente" if it.get("dispo", True) else "epuise",
                "img": it.get("img"), "pieces": it.get("pcs"), "dims": it.get("dims"),
                "type": "technic" if it.get("type") == "Technic" else "classique",
                "themes": n.themes(it["nom"] + " " + (it.get("theme") or ""), [it.get("theme") or ""]),
                "releve": "2026-11-19T00:00:00", "depuis": "2026-11-19"})
    groupes: dict[str, list[dict]] = {}
    for o in offres:
        groupes.setdefault(_cle_set(o), []).append(o)
    edito = {e["cle"]: e for e in editorial()}
    return [_set(cle, g, edito) for cle, g in groupes.items()]

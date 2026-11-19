"""Synchronisation des sources du moteur de recherche, programmée et à la demande.

L'état de la synchronisation en cours (`etat()`) est tenu en mémoire et lu par la page ; le
journal de chaque passage (une ligne par source) et l'historique vont dans `synchro.json`.
Une source en échec n'arrête pas les autres. `sante()` sert au contrôle de santé du conteneur.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from pathlib import Path

from . import lien
from .donnees import _ecrire, _lire
from .index import Index, sources_config
from .sources import shopify

log = logging.getLogger("synchro")
EN_COURS = threading.Lock()
_VERROU = threading.Lock()
_ETAT: dict = {"en_cours": False}
_PROG: dict = {"heures": 0.0, "fil": None, "prochain": None, "demarre": time.time()}
HISTORIQUE = 30
CONNECTEURS = {"shopify": shopify.lire}


def actives() -> list[dict]:
    """Sources lues : celles de la variable SOURCES si elle est posée, sinon celles marquées actives."""
    conf = sources_config()
    choix = [x.strip() for x in os.environ.get("SOURCES", "").split(",") if x.strip()]
    if choix:
        return [s for s in conf if s["id"] in choix and s["type"] in CONNECTEURS]
    return [s for s in conf if s.get("actif") and s["type"] in CONNECTEURS]


def _maintenant() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def _maj(**k) -> None:
    with _VERROU:
        _ETAT.update(k)


def etat() -> dict:
    with _VERROU:
        e = dict(_ETAT)
    debut_t = e.pop("debut_t", None)
    if e.get("en_cours") and debut_t:
        e["ecoule_s"] = round(time.time() - debut_t)
    e["heures"], e["prochain"] = _PROG["heures"], _PROG["prochain"]
    e["programme_actif"] = bool(_PROG["fil"] and _PROG["fil"].is_alive())
    return e


def _raison(e: Exception) -> str:
    if isinstance(e, lien.LienRefuse):
        return e.public
    if isinstance(e, TimeoutError):
        return "délai dépassé"
    if isinstance(e, OSError):
        return "boutique injoignable"
    if isinstance(e, ValueError):
        return "catalogue illisible"
    return "erreur inattendue, détail dans le journal du conteneur"


class Journal:
    def __init__(self, dossier: Path):
        self.fichier = Path(dossier) / "synchro.json"

    def lire(self) -> dict:
        return _lire(self.fichier, {"dernier": None, "historique": [], "sources": {}})

    def enregistrer(self, journal: dict) -> None:
        d = self.lire()
        d["dernier"] = journal
        d["historique"] = ([journal] + d.get("historique", []))[:HISTORIQUE]
        for r in journal["sources"]:
            d.setdefault("sources", {})[r["id"]] = r
        _ecrire(self.fichier, d)


def synchroniser(index: Index, journal: Journal, par: str = "programme", ids: list[str] | None = None,
                 pause: float = 1.5) -> dict:
    if not EN_COURS.acquire(blocking=False):
        return {"etat": "deja_en_cours"}
    debut = time.time()
    liste = [s for s in actives() if ids is None or s["id"] in ids]
    _maj(en_cours=True, debut=_maintenant(), debut_t=debut, par=par, total=len(liste), fait=0,
         courant=None, produits=0, echecs=0)
    log.info("synchronisation lancée (%s) : %s sources", par, len(liste))
    resultats = []
    try:
        for i, src in enumerate(liste):
            _maj(courant=src["nom"], produits=0)
            t0 = time.time()
            r = {"id": src["id"], "nom": src["nom"], "debut": _maintenant()}
            try:
                offres = CONNECTEURS[src["type"]](src, pause=pause, progres=lambda k: _maj(produits=k))
                r.update(etat="ok", lus=len(offres), **index.enregistrer(src["id"], offres))
                log.info("source %s : %s sets (%s nouveaux, %s disparus)", src["nom"], r["lus"], r["nouveaux"], r["disparus"])
            except Exception as e:  # une source en panne n'arrête pas les autres
                r.update(etat="echec", raison=_raison(e))
                if isinstance(e, (lien.LienRefuse, OSError, ValueError)):
                    log.warning("source %s en échec : %s", src["nom"], r["raison"])
                else:
                    log.exception("source %s en échec inattendu", src["nom"])
            r["duree_s"] = round(time.time() - t0)
            resultats.append(r)
            with _VERROU:
                _ETAT["fait"] = i + 1
                _ETAT["echecs"] += r["etat"] == "echec"
    finally:
        j = {"le": _maintenant(), "debut": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(debut)),
             "duree_s": round(time.time() - debut), "par": par, "portee": "toutes" if ids is None else "choix",
             "sources": resultats, "echecs": sum(1 for r in resultats if r["etat"] == "echec"),
             "lus": sum(r.get("lus", 0) for r in resultats)}
        try:
            journal.enregistrer(j)
        except Exception:
            log.exception("journal de synchronisation impossible à écrire")
        _maj(en_cours=False, courant=None)
        EN_COURS.release()
    log.info("synchronisation finie : %s sets, %s sources en échec, %s s", j["lus"], j["echecs"], j["duree_s"])
    return j


def programmer(index: Index, journal: Journal, heures: float) -> None:
    _PROG["heures"] = heures
    if heures <= 0:
        return

    def boucle():
        attente = 60
        while True:
            _PROG["prochain"] = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(time.time() + attente))
            time.sleep(attente)
            try:
                synchroniser(index, journal)
            except Exception:
                log.exception("synchronisation programmée en échec")
            attente = heures * 3600

    fil = threading.Thread(target=boucle, name="synchro", daemon=True)
    _PROG["fil"] = fil
    fil.start()


def sante(journal: Journal, maintenant: float | None = None) -> tuple[bool, str]:
    """Mauvaise si la synchronisation programmée est arrêtée, si toutes les sources du dernier passage
    complet ont échoué, ou si aucune source n'a réussi depuis deux périodes."""
    maintenant = maintenant or time.time()
    heures = _PROG["heures"]
    if heures > 0 and not (_PROG["fil"] and _PROG["fil"].is_alive()):
        return False, "synchronisation programmée arrêtée"
    d = journal.lire()
    complet = next((h for h in d.get("historique", []) if h.get("portee") == "toutes"), None)
    if complet and complet["sources"] and all(r["etat"] == "echec" for r in complet["sources"]):
        return False, "dernière synchronisation : toutes les sources en échec"
    if heures > 0:
        reussi = next((h["le"] for h in d.get("historique", []) if any(r["etat"] == "ok" for r in h["sources"])), None)
        age = maintenant - (time.mktime(time.strptime(reussi, "%Y-%m-%dT%H:%M:%S")) if reussi else _PROG["demarre"])
        if age > 2 * heures * 3600 + 600:
            return False, "aucune source synchronisée depuis plus de deux périodes"
    return True, "ok"


def offre_directe(index: Index, cle: str) -> dict:
    """Relit une offre sur sa boutique (prix, disponibilité) et met l'index à jour."""
    sid, _, handle = cle.partition(":")
    src = next((s for s in sources_config() if s["id"] == sid), None)
    if not src or src["type"] != "shopify" or not handle:
        raise LienRefuse("offre non relisible en direct")
    url = f"https://{src['hote']}{src.get('prefixe', '')}/products/{handle}.js"
    r = lien.recuperer(url, accept="application/json",
                       entetes={"Cookie": f"localization={src.get('pays', 'FR')}; cart_currency={src.get('devise', 'EUR')}"})
    d = json.loads(r.corps)
    v = next((x for x in d.get("variants", []) if x.get("available")), (d.get("variants") or [{}])[0])
    prix = round(v.get("price", d.get("price", 0)) / 100, 2)
    tags = d.get("tags") or []
    from . import normalise as n
    champs = {"prix": prix, "dispo": n.disponibilite(bool(d.get("available")), tags, d.get("title", ""))}
    index.maj_offre(sid, cle, champs)
    return {**champs, "releve": _maintenant()}


LienRefuse = lien.LienRefuse

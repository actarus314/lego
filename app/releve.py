"""Relevé des prix et disponibilités à la source, set par set."""
from __future__ import annotations

import logging
import threading
import time

from . import lien

log = logging.getLogger("releve")
EN_COURS = threading.Lock()


def releve(depot, pause: float = 1.0) -> dict:
    """Relit chaque set du catalogue. Rend le journal du relevé."""
    if not EN_COURS.acquire(blocking=False):
        return {"etat": "deja_en_cours"}
    try:
        debut = time.time()
        sets, changes, echecs = {}, [], []
        cat = depot.catalogue()
        for it in cat:
            try:
                d = lien.lire(it["url"])
            except (lien.LienRefuse, OSError, ValueError) as e:
                echecs.append({"id": it["id"], "raison": str(e)[:120]})
                continue
            nouveau = {k: d.get(k) for k in ("prix", "dispo", "img", "pcs") if d.get(k) is not None}
            for k, v in nouveau.items():
                if it.get(k) != v:
                    changes.append({"id": it["id"], "nom": it["nom"], "champ": k, "avant": it.get(k), "apres": v})
            nouveau["le"] = time.strftime("%Y-%m-%dT%H:%M:%S")
            sets[it["id"]] = nouveau
            time.sleep(pause)
        journal = {"le": time.strftime("%Y-%m-%dT%H:%M:%S"), "duree_s": round(time.time() - debut),
                   "lus": len(sets), "total": len(cat), "changes": changes, "echecs": echecs}
        depot.enregistrer_releve(sets, journal)
        log.info("relevé : %s lus sur %s, %s changements, %s échecs", len(sets), len(cat), len(changes), len(echecs))
        return {"etat": "fini", **journal}
    finally:
        EN_COURS.release()


def programmer(depot, heures: float) -> None:
    if heures <= 0:
        return

    def boucle():
        time.sleep(60)
        while True:
            try:
                releve(depot)
            except Exception:  # le service continue même si un relevé échoue
                log.exception("relevé programmé en échec")
            time.sleep(heures * 3600)

    threading.Thread(target=boucle, name="releve", daemon=True).start()

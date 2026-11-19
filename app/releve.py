"""Relevé des prix et disponibilités à la source, set par set.

L'état du relevé en cours (`etat()`) est tenu en mémoire et lu par la page ; le
journal de chaque relevé (un résultat par set) et l'historique sont écrits dans
le dossier de données. `sante()` dit si le relevé programmé tourne et réussit :
le contrôle de santé du conteneur s'en sert.
"""
from __future__ import annotations

import logging
import threading
import time
from urllib.parse import urlsplit

from . import lien

log = logging.getLogger("releve")
EN_COURS = threading.Lock()
_VERROU = threading.Lock()
_ETAT: dict = {"en_cours": False}
_PROG: dict = {"heures": 0.0, "fil": None, "prochain": None, "demarre": time.time()}
# Sites qui refusent les robots : leurs sets sont sautés (prix du catalogue gardé).
REFUS_CONNUS = {"lego.com": "LEGO.com refuse les robots : prix du catalogue"}


def _saute(url: str) -> str | None:
    hote = (urlsplit(url).hostname or "").lower()
    return next((m for h, m in REFUS_CONNUS.items() if hote == h or hote.endswith("." + h)), None)


def _maintenant() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def etat() -> dict:
    """Relevé en cours (avancement, set lu) et prochain relevé programmé."""
    with _VERROU:
        e = dict(_ETAT)
    depuis, debut_t = e.pop("courant_depuis", None), e.pop("debut_t", None)
    if e.get("en_cours"):
        e["courant_s"] = round(time.time() - depuis) if depuis else 0
        e["ecoule_s"] = round(time.time() - debut_t) if debut_t else 0
    e["heures"] = _PROG["heures"]
    e["prochain"] = _PROG["prochain"]
    fil = _PROG["fil"]
    e["programme_actif"] = bool(fil and fil.is_alive())
    return e


def _maj(**k) -> None:
    with _VERROU:
        _ETAT.update(k)


def _raison(e: Exception) -> str:
    if isinstance(e, lien.LienRefuse):
        return e.public
    if isinstance(e, TimeoutError):
        return "délai dépassé"
    if isinstance(e, OSError):
        return "boutique injoignable"
    if isinstance(e, ValueError):
        return "page illisible"
    return "erreur inattendue, détail dans le journal du conteneur"


def releve(depot, pause: float = 1.0, par: str = "programme", ids: list[str] | None = None) -> dict:
    """Relit les sets du catalogue (tous, ou ceux de `ids`). Rend le journal du relevé."""
    if not EN_COURS.acquire(blocking=False):
        return {"etat": "deja_en_cours"}
    debut, sets, resultats = time.time(), {}, []
    cat = [it for it in depot.catalogue() if ids is None or it["id"] in ids]
    _maj(en_cours=True, debut=_maintenant(), debut_t=debut, par=par, fait=0, total=len(cat), echecs=0, courant=None, courant_depuis=None)
    log.info("relevé lancé (%s) : %s sets", par, len(cat))
    etat_final, panne = "fini", None
    try:
        for n, it in enumerate(cat):
            _maj(courant=it["nom"], courant_depuis=time.time())
            t0 = time.time()
            r = {"id": it["id"], "nom": it["nom"], "url": it["url"], "prix_avant": it.get("prix")}
            motif = _saute(it["url"])
            if motif:
                r.update(statut="saute", raison=motif, ms=0)
                resultats.append(r)
                _maj(fait=n + 1)
                continue
            try:
                d = lien.lire(it["url"])
                nouveau = {k: d.get(k) for k in ("prix", "dispo", "img", "pcs") if d.get(k) is not None}
                r.update(statut="ok", prix=nouveau.get("prix"), dispo=nouveau.get("dispo"),
                         changes=[k for k, v in nouveau.items() if it.get(k) != v])
                nouveau["le"] = _maintenant()
                sets[it["id"]] = nouveau
            except Exception as e:  # un set en échec n'arrête pas le relevé
                r.update(statut="echec", raison=_raison(e))
                if isinstance(e, (lien.LienRefuse, OSError, ValueError)):
                    log.warning("relevé : %s en échec : %s", it["nom"], r["raison"])
                else:
                    log.exception("relevé : %s en échec inattendu", it["nom"])
            r["ms"] = round((time.time() - t0) * 1000)
            resultats.append(r)
            with _VERROU:
                _ETAT["fait"] = n + 1
                _ETAT["echecs"] += r["statut"] == "echec"
            if n + 1 < len(cat):
                time.sleep(pause)
    except Exception as e:  # panne hors d'un set : le relevé s'arrête mais reste consigné
        etat_final, panne = "interrompu", _raison(e)
        log.exception("relevé interrompu")
    finally:
        journal = {
            "etat": etat_final, "debut": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(debut)),
            "le": _maintenant(), "duree_s": round(time.time() - debut), "par": par,
            "portee": "tous" if ids is None else "echecs",
            "total": len(cat), "lus": sum(1 for r in resultats if r["statut"] == "ok"),
            "echecs": sum(1 for r in resultats if r["statut"] == "echec"),
            "sautes": sum(1 for r in resultats if r["statut"] == "saute"),
            "changes": sum(1 for r in resultats if r.get("changes")),
            "sets": resultats,
        }
        if panne:
            journal["raison"] = panne
        try:
            depot.enregistrer_releve(sets, journal)
        except Exception:
            log.exception("relevé : écriture du journal impossible")
        _maj(en_cours=False, courant=None, courant_depuis=None)
        EN_COURS.release()
    log.info("relevé %s : %s lus sur %s, %s changés, %s échecs, %s sautés, %s s", etat_final, journal["lus"],
             journal["total"], journal["changes"], journal["echecs"], journal["sautes"], journal["duree_s"])
    return journal


def programmer(depot, heures: float) -> None:
    _PROG["heures"] = heures
    if heures <= 0:
        return

    def boucle():
        _PROG["prochain"] = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(time.time() + 60))
        time.sleep(60)
        while True:
            try:
                releve(depot)
            except Exception:  # le service continue même si un relevé échoue
                log.exception("relevé programmé en échec")
            _PROG["prochain"] = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(time.time() + heures * 3600))
            time.sleep(heures * 3600)

    fil = threading.Thread(target=boucle, name="releve", daemon=True)
    _PROG["fil"] = fil
    fil.start()


def sante(depot, maintenant: float | None = None) -> tuple[bool, str]:
    """(bon, raison). Mauvais si le relevé programmé est arrêté, si le dernier relevé
    complet n'a lu aucun des sets qu'il devait lire, ou si aucun relevé n'a réussi
    depuis deux périodes. Une relance des seuls échecs ne compte pas."""
    maintenant = maintenant or time.time()
    heures = _PROG["heures"]
    if heures > 0 and not (_PROG["fil"] and _PROG["fil"].is_alive()):
        return False, "relevé programmé arrêté"
    complet = next((h for h in depot.historique() if h.get("portee", "tous") == "tous"), {})
    if complet.get("etat") == "interrompu":
        return False, "dernier relevé interrompu"
    if complet.get("total", 0) - complet.get("sautes", 0) > 0 and not complet.get("lus"):
        return False, "dernier relevé : aucun set lu"
    if heures > 0:
        limite = 2 * heures * 3600 + 600
        reussi = next((h["le"] for h in depot.historique() if h.get("lus")), None)
        if reussi:
            age = maintenant - time.mktime(time.strptime(reussi, "%Y-%m-%dT%H:%M:%S"))
        else:
            age = maintenant - _PROG["demarre"]
        if age > limite:
            return False, "aucun relevé réussi depuis plus de deux périodes"
    return True, "ok"

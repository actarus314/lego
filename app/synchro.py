"""Synchronisation des sources du moteur de recherche, programmée et à la demande.

L'état de la synchronisation en cours (`etat()`) est tenu en mémoire et lu par la page ; le
journal de chaque passage (une ligne par source) et l'historique vont dans `synchro.json`.
Une source en échec n'arrête pas les autres. `sante()` sert au contrôle de santé du conteneur.
"""
from __future__ import annotations

import calendar
import json
import logging
import math
import re
import os
import threading
import time
from pathlib import Path

from . import completude, lien
from .reglage import reglage
from .donnees import _ecrire, _lire
from .index import Index, sources_config
from .sources import lego as lego_src, shopify

log = logging.getLogger("synchro")
EN_COURS = threading.Lock()
_VERROU = threading.Lock()
_ETAT: dict = {"en_cours": False}
_PROG: dict = {"heures": 0.0, "fil": None, "prochain": None, "demarre": time.time()}
HISTORIQUE = 30
CONNECTEURS = {"shopify": shopify.lire}
TYPES = {"shopify", "bricksvalue"}
# Fiches LEGO officiel : BricksValue republie ses prix (« mis à jour chaque jour ») ; chaque fiche porte
# l'heure de la dernière publication, la même pour toutes (`publie`, voir sources/lego.py). Chaque fiche d'un
# set pour adultes lue avant la dernière publication connue est relue, celles de la sélection d'abord, en
# FENETRE_H heures au plus ; quand toutes sont à jour, une fiche (la plus ancienne) est relue toutes les
# SONDE_S secondes pour voir arriver la publication suivante. Sans publication connue : fiche relue après 24 h.
FENETRE_H, SONDE_S = 6, 3600
REESSAIS_S = (3600, 6 * 3600, 24 * 3600)   # pause après 1, 2, puis 3 échecs de suite ou plus
PAS_MIN, PAS_MAX, PAS_AMORCE = 20, 900, 10
# Relecture horaire de la sélection : pause entre deux produits relus.
SELECTION_PAUSE_S = 3


def actives() -> list[dict]:
    """Sources lues : celles de la variable SOURCES si elle est posée, sinon celles marquées actives."""
    conf = sources_config()
    choix = [x.strip() for x in reglage("SOURCES", "").split(",") if x.strip()]
    if choix:
        return [s for s in conf if s["id"] in choix and s["type"] in TYPES]
    return [s for s in conf if s.get("actif") and s["type"] in TYPES]


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
                if src["type"] == "bricksvalue":
                    r.update(etat="ok", **liste_lego(index, src))
                else:
                    compte: dict = {}
                    pages = shopify.Pages(index.dossier.parent / "pages" / re.sub(r"[^a-z0-9_-]", "", src["id"]))
                    offres = CONNECTEURS[src["type"]](src, pause=pause, progres=lambda k: _maj(produits=k),
                                                      pages=pages, compte=compte)
                    if src.get("cartes"):
                        completer_dimensions(index, src, offres, pause)
                    r.update(etat="ok", lus=len(offres), dims=sum(1 for o in offres if o.get("dims")), **compte,
                             **index.enregistrer(src["id"], offres))
                log.info("source %s : %s offres (%s nouveaux, %s disparus)", src["nom"], r["lus"], r["nouveaux"], r["disparus"])
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
        try:   # complétude du catalogue à la fin du passage, comparée aux passages précédents par la surveillance
            j["completude"] = completude.compter(index.sets([s["id"] for s in actives()]))
        except Exception:
            log.exception("complétude du catalogue non comptée")
        try:
            journal.enregistrer(j)
        except Exception:
            log.exception("journal de synchronisation impossible à écrire")
        _maj(en_cours=False, courant=None)
        EN_COURS.release()
    log.info("synchronisation finie : %s offres, %s sources en échec, %s s", j["lus"], j["echecs"], j["duree_s"])
    return j


def completer_dimensions(index: Index, src: dict, offres: list[dict], pause: float) -> None:
    """Complète les dimensions absentes du catalogue JSON : d'abord par les cartes des pages de
    collection (une douzaine de produits par page, relues chaque semaine), puis par la page de chaque
    produit encore sans dimension (une fois par produit ; nouvel essai après 30 jours)."""
    fichier = index.dossier.parent / f"dimensions_{src['id']}.json"
    cache = _lire(fichier, {"le": None, "dims": {}, "sans": {}})
    cache.setdefault("sans", {})
    if not cache["le"] or _age_h(cache["le"], time.time()) > 7 * 24:
        try:
            cache["dims"].update(shopify.dimensions_cartes(src, pause))
            cache["le"] = _maintenant()
        except (lien.LienRefuse, OSError, ValueError) as e:
            log.warning("dimensions %s : cartes non lues : %s", src["nom"], _raison(e))
    a_lire = [o["cle"].split(":", 1)[1] for o in offres if not o.get("dims")]
    a_lire = [h for h in a_lire if h not in cache["dims"] and _age_h(cache["sans"].get(h), time.time()) > 30 * 24]
    for k, h in enumerate(a_lire):
        _maj(produits=f"{k + 1} / {len(a_lire)} pages produit")
        try:
            d = shopify.dimensions_fiche(src, h)
        except (lien.LienRefuse, OSError, ValueError) as e:
            log.info("dimensions %s : page %s non lue : %s", src["nom"], h, _raison(e))
            continue
        if d:
            cache["dims"][h] = d
        else:
            cache["sans"][h] = _maintenant()
        if k % 20 == 19:
            _ecrire(fichier, cache)
        time.sleep(pause)
    _ecrire(fichier, cache)
    for o in offres:
        h = o["cle"].split(":", 1)[1]
        if not o.get("dims") and cache["dims"].get(h):
            o["dims"] = cache["dims"][h]


def _a(jour: time.struct_time, decalage_j: int, heure: int) -> float:
    """Instant de `heure` h locale, `decalage_j` jours après `jour` (changements d'heure compris)."""
    return time.mktime((jour.tm_year, jour.tm_mon, jour.tm_mday + decalage_j, heure, 0, 0, 0, 0, -1))


def creneaux(heures: float, heure: int, maintenant: float) -> list[float]:
    """Passages programmés autour de maintenant, en heure locale : chaque jour à `heure`, puis toutes les
    `heures` heures (diviseur de 24) ; ou tous les `heures` / 24 jours à `heure` (multiple de 24)."""
    t = time.localtime(maintenant)
    if heures >= 24:
        pas_j = int(heures // 24)
        jour0 = int(_a(t, 0, 12) // 86400)
        return [_a(t, j, heure) for j in range(-2 * pas_j, 2 * pas_j + 1) if (jour0 + j) % pas_j == 0]
    return sorted(_a(t, j, (heure + i * int(heures)) % 24) for j in (-1, 0, 1) for i in range(int(24 // heures)))


def prochain_passage(heures: float, heure: int | None, maintenant: float, dernier: float | None) -> float:
    """Instant du prochain passage programmé. Avec `heure` (heure locale, RELEVE_HEURE) : aux créneaux
    de `creneaux` ; un créneau manqué (conteneur arrêté à l'heure prévue) est rattrapé une minute après le
    démarrage. Sans `heure` : `heures` heures après le passage précédent."""
    if heure is None:
        return maintenant + (60 if dernier is None else max(60, heures * 3600 - (maintenant - dernier)))
    c = creneaux(heures, heure, maintenant)
    suivant = next(x for x in c if x > maintenant + 30)
    precedent = max((x for x in c if x <= maintenant + 30), default=None)
    if dernier is None or (precedent is not None and dernier < precedent):   # jamais lancé, ou créneau manqué
        return min(suivant, maintenant + 60)
    return max(suivant, maintenant + 60)


def heure_programmee(heures: float | None = None) -> int | None:
    """RELEVE_HEURE : heure locale (0 à 23) des passages programmés, 6 par défaut ; « aucune » : chaque
    passage RELEVE_HEURES heures après le précédent (fonctionnement d'avant la v3.15). Avec une heure,
    RELEVE_HEURES doit diviser 24 ou en être un multiple. Sinon, le service refuse de démarrer."""
    v = reglage("RELEVE_HEURE", "6").lower()
    if v == "aucune":
        return None
    if not v.isdigit() or not 0 <= int(v) <= 23:
        raise SystemExit("RELEVE_HEURE : heure de 0 à 23, ou « aucune »")
    if heures and heures > 0 and (heures != int(heures) or not (24 % heures == 0 or heures % 24 == 0)):
        raise SystemExit("RELEVE_HEURES doit être un nombre entier d'heures qui divise 24 ou en est un multiple avec "
                         "RELEVE_HEURE (sinon RELEVE_HEURE=aucune)")
    return int(v)


def programmer(index: Index, journal: Journal, heures: float, heure: int | None = None) -> None:
    _PROG["heures"] = heures
    if heures <= 0:
        return

    def boucle():
        lance = None   # dernier lancement, au cas où le journal n'aurait pas pu être écrit
        while True:
            try:
                try:   # dernier passage complet (une synchronisation de quelques sources ne compte pas)
                    h = journal.lire().get("historique") or []
                    dernier = next((x["le"] for x in h if x.get("portee") == "toutes"), None)
                    dernier_t = time.mktime(time.strptime(dernier, "%Y-%m-%dT%H:%M:%S")) if dernier else None
                except Exception:   # journal illisible : le dernier lancement connu fait foi
                    log.exception("journal de synchronisation illisible")
                    dernier_t = None
                if lance and (dernier_t is None or lance > dernier_t):
                    dernier_t = lance
                quand = prochain_passage(heures, heure, time.time(), dernier_t)
                _PROG["prochain"] = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(quand))
                time.sleep(max(1, quand - time.time()))
                lance = time.time()
                synchroniser(index, journal)
            except Exception:
                log.exception("synchronisation programmée en échec")
                time.sleep(60)

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
    if sid == "bricksvalue":
        num = handle.split(":")[0]
        etat = (index.lire("bricksvalue").get("fiches") or {}).get(num)
        if not etat:
            raise LienRefuse("fiche inconnue")
        offres = lire_une(index, num, etat["url"])
        o = next((x for x in offres if x["cle"] == cle), None)
        if not o:
            raise LienRefuse("offre absente de la fiche")
        return {"prix": o["prix"], "dispo": o["dispo"], "releve": o.get("releve"), "releve_par": "BricksValue"}
    src = next((s for s in sources_config() if s["id"] == sid), None)
    if not src or src["type"] != "shopify" or not re.fullmatch(r"[A-Za-z0-9._-]{1,200}", handle or ""):
        raise LienRefuse("offre non relisible en direct")
    url = f"https://{src['hote']}{src.get('prefixe', '')}/products/{handle}.js"
    r = lien.recuperer(url, accept="application/json",
                       entetes={"Cookie": f"localization={src.get('pays', 'FR')}; cart_currency={src.get('devise', 'EUR')}"})
    d = json.loads(r.corps)
    v = next((x for x in d.get("variants", []) if x.get("available")), (d.get("variants") or [{}])[0])
    brut = v.get("price", d.get("price"))
    if not isinstance(brut, (int, float)) or not math.isfinite(brut) or brut <= 0:
        raise LienRefuse("prix illisible")
    prix = round(brut / 100, 2)
    tags = d.get("tags") or []
    from . import normalise as n
    champs = {"prix": prix, "barre": shopify._barre(v, prix, centimes=True),
              "dispo": n.disponibilite(bool(d.get("available")), tags, d.get("title", ""))}
    index.maj_offre(sid, cle, champs)
    return {**champs, "releve": _maintenant()}


LienRefuse = lien.LienRefuse


RELIRE_MAX = 40          # offres d'un set relues par une requête (un set LEGO officiel en compte une dizaine)
RELIRE_PAUSE_S = 60      # une même offre ou fiche n'est pas relue deux fois en moins d'une minute
_RELUES: dict[str, tuple[float, dict]] = {}


def _recent(cle: str) -> dict | None:
    t = _RELUES.get(cle)
    return t[1] if t and time.time() - t[0] < RELIRE_PAUSE_S else None


def _retenir(cle: str, valeur: dict) -> dict:
    if len(_RELUES) > 2000:
        _RELUES.clear()
    _RELUES[cle] = (time.time(), valeur)
    return valeur


def relire(index: Index, cles: list[str]) -> dict[str, dict]:
    """Relit les offres d'un set : une lecture par fiche BricksValue (elle donne toutes les offres
    LEGO officiel du set), une par produit de boutique. Rend {clé: champs relus, ou {"erreur": …}}."""
    out: dict[str, dict] = {}
    fiches: dict[str, list[str]] = {}
    cles = list(dict.fromkeys(cles))[:RELIRE_MAX]
    for cle in cles:
        sid, _, reste = cle.partition(":")
        if sid == "bricksvalue":
            fiches.setdefault(reste.split(":")[0], []).append(cle)
        else:
            try:
                recent = _recent(cle)
                out[cle] = recent if recent else _retenir(cle, offre_directe(index, cle))
            except LienRefuse as e:
                out[cle] = {"erreur": e.public}
            except Exception:  # réseau, réponse tronquée ou illisible
                log.info("relecture de %s en échec", cle, exc_info=True)
                out[cle] = {"erreur": "boutique injoignable ou réponse illisible"}
    for num, liste in fiches.items():
        etat = (index.lire("bricksvalue").get("fiches") or {}).get(num)
        try:
            if not etat:
                raise LienRefuse("fiche inconnue")
            if _en_pause(etat, time.time()):   # en échec récent : pas de relecture à chaque clic
                raise LienRefuse(etat.get("erreur") or "fiche en échec, réessai plus tard")
            if _age_h(etat.get("lu"), time.time()) * 3600 < RELIRE_PAUSE_S:  # lue à l'instant : pas de seconde lecture
                offres = {o["cle"]: o for o in index.lire("bricksvalue").get("offres", []) if o["cle"].startswith(f"bricksvalue:{num}:")}
            else:
                offres = {o["cle"]: o for o in lire_une(index, num, etat["url"])}
        except LienRefuse as e:
            out.update({c: {"erreur": e.public} for c in liste})
            continue
        except Exception:
            log.info("relecture de la fiche %s en échec", num, exc_info=True)
            out.update({c: {"erreur": "BricksValue injoignable ou réponse illisible"} for c in liste})
            continue
        for c in liste:
            o = offres.get(c)
            out[c] = ({"prix": o["prix"], "dispo": o["dispo"], "releve": o.get("releve"), "releve_par": "BricksValue"}
                      if o else {"erreur": "offre retirée de la fiche"})
    return out


# ----- relecture horaire de la sélection -----
_SELECTION: dict = {}


def relire_selection(index: Index, items: list[dict], pause: float = SELECTION_PAUSE_S) -> dict:
    """Relit sur leur boutique (une requête /products/<poignée>.js par produit) toutes les offres de
    boutique des sets de la sélection, pour que les alertes partent dans l'heure. Les offres LEGO
    officiel ne changent qu'à la publication quotidienne de BricksValue (rotation des fiches). Un produit
    « Acheté » n'est pas relu ; rien n'est relu pendant une synchronisation."""
    if EN_COURS.locked():
        return dict(_SELECTION)
    from .alertes import norm
    par_url = {norm(o["url"]): s for s in index.sets([x["id"] for x in actives()]) for o in s["offres"]}
    cles: list[str] = []
    for it in items:
        s = par_url.get(norm(it.get("url"))) if it.get("statut") != "achete" else None
        cles += [o["cle"] for o in (s or {}).get("offres", []) if o["source"] not in ("bricksvalue", "editorial")]
    cles = list(dict.fromkeys(cles))
    lus = echecs = 0
    en_pause: set[str] = set()   # boutiques qui ont répondu 429 ou 5xx : laissées jusqu'au passage suivant
    for k, cle in enumerate(cles):
        sid = cle.partition(":")[0]
        if sid in en_pause:
            echecs += 1
            continue
        if k:
            time.sleep(pause)
        try:
            offre_directe(index, cle)
            lus += 1
        except Exception as e:   # une offre illisible n'arrête pas les autres
            echecs += 1
            statut = getattr(e, "statut", None) or 0
            if statut == 429 or statut >= 500:
                en_pause.add(sid)
            log.info("sélection : %s non relue : %s", cle, _raison(e), exc_info=not isinstance(e, (LienRefuse, OSError)))
    _SELECTION.clear()
    _SELECTION.update(le=_maintenant(), offres=len(cles), lus=lus, echecs=echecs)
    return dict(_SELECTION)


def etat_selection() -> dict:
    return dict(_SELECTION)


# ----- LEGO officiel : liste des fiches (à chaque synchronisation) et lecture après chaque publication -----
def _reference(index: Index) -> dict:
    return _lire(index.dossier.parent / "reference_lego.json", {})


def liste_lego(index: Index, src: dict) -> dict:
    """Met à jour la référence Rebrickable et la liste des fiches BricksValue à suivre."""
    ref = lego_src.reference()
    _ecrire(index.dossier.parent / "reference_lego.json", ref)
    plan = lego_src.fiches()
    candidats = {num: url for num, url in plan.items() if num in ref}
    with index_verrou():
        d = index.lire(src["id"])
        fiches = d.setdefault("fiches", {})
        nouveaux = [k for k in candidats if k not in fiches]
        for k, url in candidats.items():
            fiches.setdefault(k, {"lu": None, "adulte": None})["url"] = url
        partis = [k for k in fiches if k not in candidats]
        for k in partis:
            del fiches[k]
        d["offres"] = [o for o in d.get("offres", []) if o["numero"] in fiches]
        d["le"] = _maintenant()
        _ecrire(index.fichier(src["id"]), d)
        index._cache = None
    adultes = sum(1 for f in fiches.values() if f.get("adulte"))
    return {"lus": adultes, "nouveaux": len(nouveaux), "disparus": len(partis), "fiches": len(fiches)}


def index_verrou():
    from .index import VERROU
    return VERROU


def lire_une(index: Index, num: str, url: str) -> list[dict]:
    ref = _reference(index).get(num)
    try:
        d = lego_src.lire_fiche(num, url, ref)
    except Exception as e:
        # « lu » n'avance pas : la fiche reste à lire, réessayée après une pause croissante (REESSAIS_S)
        avant = (index.lire("bricksvalue").get("fiches") or {}).get(num) or {}
        index.etat_fiche("bricksvalue", num, {"echec": _maintenant(), "erreur": _raison(e),
                                              "echecs": int(avant.get("echecs") or 0) + 1})
        raise
    offres = d["offres"] if d["adulte"] else []
    index.maj_fiche("bricksvalue", f"bricksvalue:{num}:", offres,
                    {"url": url, "lu": _maintenant(), "adulte": d["adulte"], "age": d["age"], "publie": d.get("publie")})
    return offres


def _age_h(lu: str | None, maintenant: float) -> float:
    return 1e9 if not lu else (maintenant - time.mktime(time.strptime(lu, "%Y-%m-%dT%H:%M:%S"))) / 3600


def _instant(texte: str | None, utc: bool = False) -> float | None:
    if not texte:
        return None
    try:
        t = time.strptime(texte[:19], "%Y-%m-%dT%H:%M:%S")
    except ValueError:
        return None
    return calendar.timegm(t) if utc else time.mktime(t)


def publication(fiches: dict, maintenant: float) -> float:
    """Dernière publication de BricksValue connue (instant) ; sans aucune, il y a 24 h."""
    connues = [x for x in (_instant(f.get("publie"), utc=True) for f in fiches.values()) if x and x <= maintenant + 600]
    return max(connues) if connues else maintenant - 86400


def _en_pause(f: dict, maintenant: float) -> bool:
    """Fiche dont la dernière lecture a échoué il y a moins que la pause de réessai (croissante)."""
    echec = _instant(f.get("echec"))
    pause = REESSAIS_S[min(int(f.get("echecs") or 1), len(REESSAIS_S)) - 1]
    return bool(echec and echec > (_instant(f.get("lu")) or 0) and maintenant - echec < pause)


def _a_lire(f: dict) -> bool:
    """Jamais lue avec succès : sans lecture, ou en erreur avant la v3.15 (« lu » avançait à l'échec)."""
    return not f.get("lu") or (f.get("adulte") is None and bool(f.get("erreur")))


def prochaine_fiche(index: Index, selection: set[str], maintenant: float | None = None) -> tuple[str | None, float]:
    """Rend (numéro de la fiche à lire ou None, pause avant la suivante)."""
    maintenant = maintenant or time.time()
    fiches = index.lire("bricksvalue").get("fiches") or {}
    if not fiches:
        return None, PAS_MAX
    jamais = [k for k, f in fiches.items() if _a_lire(f) and not _en_pause(f, maintenant)]
    if jamais:
        return jamais[0], PAS_AMORCE
    adultes = {k: f for k, f in fiches.items() if f.get("adulte") and f.get("lu")}
    if not adultes:
        return None, PAS_MAX
    pub = publication(fiches, maintenant)

    def due(f: dict) -> bool:
        if _en_pause(f, maintenant):
            return False
        lu = _instant(f["lu"]) or 0
        # lue avant la publication ; ou lue juste après mais servie d'avant elle (cache) : une relecture, une heure après
        servie_avant = (_instant(f.get("publie"), utc=True) or pub) < pub and lu < pub + SONDE_S
        return lu < pub or (servie_avant and maintenant - lu >= SONDE_S)
    dues = [k for k, f in adultes.items() if due(f)]
    if not dues:   # toutes lues depuis la publication : une sonde par heure pour voir arriver la suivante
        derniere = max((_instant(f["lu"]) or 0) for f in adultes.values())
        sonde = min((k for k, f in adultes.items() if not _en_pause(f, maintenant)), key=lambda k: adultes[k]["lu"], default=None)
        return (sonde if maintenant - derniere >= SONDE_S else None), PAS_MAX
    pas = min(PAS_MAX, max(PAS_MIN, FENETRE_H * 3600 / len(adultes)))
    sel = sorted((k for k in dues if k in selection), key=lambda k: adultes[k]["lu"])
    return (sel[0] if sel else min(dues, key=lambda k: adultes[k]["lu"])), pas


def numeros_selection(index: Index, urls: list[str]) -> set[str]:
    """Numéros des sets LEGO officiel présents dans la sélection (par l'adresse de l'offre choisie)."""
    cibles = {u.rstrip("/").lower() for u in urls if u}
    nums = {o["numero"] for o in index.lire("bricksvalue").get("offres", []) if (o.get("url") or "").rstrip("/").lower() in cibles}
    for u in cibles:
        m = re.search(r"lego\.com/.*?-(\d{4,6})$", u)
        if m:
            nums.add(m.group(1))
    return nums


def etat_rotation(index: Index) -> dict | None:
    fiches = index.lire("bricksvalue").get("fiches") or {}
    if not fiches:
        return None
    maintenant = time.time()
    adultes = [f for f in fiches.values() if f.get("adulte")]
    pub = publication(fiches, maintenant)
    return {"fiches": len(fiches), "lues": sum(1 for f in fiches.values() if f.get("lu") or f.get("echec")), "adultes": len(adultes),
            "erreurs": sum(1 for f in fiches.values() if f.get("erreur")),
            "publication": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(pub)) if any(f.get("publie") for f in fiches.values()) else None,
            "a_jour": sum(1 for f in adultes if (_instant(f.get("lu")) or 0) >= pub and not _en_pause(f, maintenant)),
            "plus_ancienne_h": round(max((_age_h(f["lu"], maintenant) for f in adultes), default=0), 1)}


def demarrer_rotation(index: Index, selection) -> None:
    """Lit les fiches LEGO officiel une à une, en continu, si la source BricksValue est active."""
    if not any(s["type"] == "bricksvalue" for s in actives()):
        return

    def boucle():
        time.sleep(90)
        while True:
            pas = PAS_MAX
            try:
                num, pas = prochaine_fiche(index, numeros_selection(index, selection()))
                if num:
                    url = (index.lire("bricksvalue").get("fiches") or {})[num]["url"]
                    try:
                        lire_une(index, num, url)
                    except lien.LienRefuse as e:
                        log.warning("fiche %s en échec : %s", num, e.public)
                        if getattr(e, "statut", None) == 429:
                            pas = max(pas, lien._attente_s(getattr(e, "attente", None)))   # Retry-After borné (date HTTP, 0, nan compris)
                    except (OSError, ValueError) as e:
                        log.warning("fiche %s en échec : %s", num, _raison(e))
            except Exception:
                log.exception("rotation des fiches en échec")
            time.sleep(pas)

    threading.Thread(target=boucle, name="rotation", daemon=True).start()

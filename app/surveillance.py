"""Surveillance du service : prévient l'administrateur quand le service se dégrade ou se rétablit,
quand une source lit nettement moins que d'habitude ou qu'une condition de livraison a changé
(module livraison, relu chaque semaine), et garde une copie quotidienne de la sélection.

Le conteneur passe « unhealthy » quand `synchro.sante()` est mauvaise, mais Docker n'en fait rien :
ce module envoie le message lui-même, par les canaux de la variable ALERTES_SERVICE (même écriture
que les canaux d'ALERTES : « courriel:adresse,signal:+33… » ; vide : surveillance sans message).

Baisse de lecture : une source dont le dernier passage réussi lit moins de 70 % de la médiane de ses
cinq passages réussis précédents (sets, ou sets avec dimensions), ou une rotation de fiches LEGO
officiel dont plus d'un cinquième des fiches est en erreur. Ce signal vise une boutique qui a changé
la présentation de ses pages : la source ne tombe pas en panne, elle rend moins. Même principe pour la
complétude du catalogue (completude.py) : un champ dont la part mesurée à la source baisse nettement.
"""
from __future__ import annotations

import logging
import shutil
import statistics
import threading
import time
from pathlib import Path

from . import alertes, completude, livraison, synchro
from .donnees import _ecrire, _lire
from .reglage import reglage

log = logging.getLogger("surveillance")
PERIODE_S = 600
SEUIL = 0.7
HISTOIRE = 5
COPIES = 14


def canaux() -> list[tuple[str, str]]:
    out = []
    for c in reglage("ALERTES_SERVICE", "").split(","):
        canal, _, adresse = c.strip().partition(":")
        if canal and adresse:
            out.append((canal.strip(), adresse.strip()))
    return out


def mal_ecrits() -> list[str]:
    """Entrées d'ALERTES_SERVICE sans « canal:adresse » : refusées au démarrage plutôt qu'ignorées."""
    return [c.strip() for c in reglage("ALERTES_SERVICE", "").split(",") if c.strip() and ":" not in c]


def envoyer(sujet: str, texte: str) -> list[str]:
    erreurs = []
    for canal, adresse in canaux():
        f = alertes.CANAUX.get(canal)
        if not f:
            erreurs.append(f"canal inconnu : {canal}")
            continue
        try:
            f(adresse, sujet, texte)
        except Exception as e:  # un canal en panne n'empêche pas les autres
            log.warning("message de surveillance par %s en échec : %s", canal, e)
            erreurs.append(f"{canal} : {type(e).__name__}")
    return erreurs


def baisses(journal: dict, rotation: dict | None = None) -> dict[str, str]:
    """{clé: message} des lectures en baisse, d'après l'historique de la synchronisation."""
    out: dict[str, str] = {}
    par_source: dict[str, list[dict]] = {}
    for passage in journal.get("historique", []):  # du plus récent au plus ancien
        for r in passage.get("sources", []):
            if r.get("etat") == "ok":
                par_source.setdefault(r["id"], []).append(r)
    for sid, runs in par_source.items():
        dernier, avant = runs[0], runs[1:1 + HISTOIRE]
        if len(avant) < 2:
            continue
        for champ, quoi in (("lus", "sets lus"), ("dims", "sets avec dimensions")):
            passe = [r[champ] for r in avant if isinstance(r.get(champ), int)]
            if len(passe) < 2 or not isinstance(dernier.get(champ), int):
                continue
            mediane = statistics.median(passe)
            if mediane >= 10 and dernier[champ] < SEUIL * mediane:
                out[f"{sid}:{champ}"] = (f"{dernier.get('nom', sid)} : {dernier[champ]} {quoi} au dernier passage, "
                                         f"contre {round(mediane)} d'habitude ; la boutique a peut-être changé ses pages.")
    if rotation and rotation.get("lues", 0) >= 20 and rotation.get("erreurs", 0) > rotation["lues"] / 5:
        out["bricksvalue:erreurs"] = (f"LEGO officiel (BricksValue) : {rotation['erreurs']} fiches en erreur sur "
                                      f"{rotation['lues']} lues ; le format des fiches a peut-être changé.")
    return out


class Surveillance:
    def __init__(self, dossier: Path, journal, index, envoi=envoyer, relire_livraison: bool = True):
        self.dossier = Path(dossier)
        self.relire_livraison = relire_livraison
        self.fichier = self.dossier / "surveillance.json"
        self.journal, self.index, self.envoi = journal, index, envoi

    def verifier(self, maintenant: float | None = None) -> list[str]:
        """Compare l'état du service à l'état noté ; envoie les changements et rend leurs sujets."""
        maintenant = maintenant or time.time()
        note = _lire(self.fichier, {"sante": "ok", "baisses": {}})
        bon, raison = synchro.sante(self.journal, maintenant)
        envoyes = []
        adresse = reglage("ADRESSE_PUBLIQUE", "").rstrip("/")
        lien_synchro = f"\n\nSynchronisation : {adresse}/#synchro" if adresse else ""
        # L'état n'est noté « prévenu » que si le message est parti : sinon il repart au passage suivant.
        sante_notee, raison_notee = note.get("sante", "ok"), note.get("raison")
        if not bon and sante_notee == "ok":
            envoyes.append("Carnet de briques : service dégradé")
            if not self.envoi(envoyes[-1], f"{raison}.{lien_synchro}"):
                sante_notee, raison_notee = "mauvaise", raison
        elif bon and sante_notee != "ok":
            envoyes.append("Carnet de briques : service rétabli")
            if not self.envoi(envoyes[-1], f"Le service fonctionne de nouveau (précédemment : {note.get('raison')}).{lien_synchro}"):
                sante_notee, raison_notee = "ok", raison
        if livraison.a_relire(self.dossier, maintenant) and self.relire_livraison:
            try:
                livraison.relire(self.dossier)
                self.index._cache = None  # un port relu change le meilleur prix
            except Exception:
                log.exception("relecture des pages de livraison en échec")
        j = self.journal.lire()
        actuelles = {**baisses(j, synchro.etat_rotation(self.index)), **completude.degradations(j.get("historique", [])),
                     **livraison.ecarts(self.dossier)}
        prevenus = {k: v for k, v in note.get("prevenus", note.get("baisses", {})).items() if k in actuelles}
        nouvelles = {k: v for k, v in actuelles.items() if k not in prevenus}
        if nouvelles:
            envoyes.append(f"Carnet de briques : {len(nouvelles)} point{'s' if len(nouvelles) > 1 else ''} à vérifier")
            if not self.envoi(envoyes[-1], "\n".join("• " + v for v in nouvelles.values()) + lien_synchro):
                prevenus.update(nouvelles)
        _ecrire(self.fichier, {"sante": sante_notee, "raison": raison_notee, "le": synchro._maintenant(),
                               "baisses": actuelles, "prevenus": prevenus})
        self.copier_selection(maintenant)
        return envoyes

    def copier_selection(self, maintenant: float) -> Path | None:
        """Une copie de selection.json par jour dans sauvegardes/, les 14 dernières gardées."""
        source = self.dossier / "selection.json"
        if not source.is_file():
            return None
        dossier = self.dossier / "sauvegardes"
        dossier.mkdir(exist_ok=True)
        cible = dossier / f"selection-{time.strftime('%Y-%m-%d', time.localtime(maintenant))}.json"
        if not cible.exists():
            shutil.copy2(source, cible)
        for vieille in sorted(dossier.glob("selection-*.json"))[:-COPIES]:
            vieille.unlink()
        return cible

    def etat(self) -> dict:
        note = _lire(self.fichier, {"baisses": {}})
        return {"baisses": list(note.get("baisses", {}).values()), "canaux": len(canaux())}

    def demarrer(self) -> None:
        def boucle():
            time.sleep(120)
            while True:
                try:
                    self.verifier()
                except Exception:
                    log.exception("surveillance en échec")
                time.sleep(PERIODE_S)
        threading.Thread(target=boucle, name="surveillance", daemon=True).start()

"""Historique des prix : prix, prix barré et disponibilité de chaque offre, une valeur par jour (la
dernière lue ce jour-là), gardée JOURS_GARDES jours dans `historique_prix.json` du dossier de données.

Alimenté par chaque lecture : synchronisation des boutiques, relecture horaire de la sélection,
relecture d'une fiche, fiches LEGO officiel. Il sert à dire si un prix du jour est bas (« plus bas
relevé sur 30 jours », ou sur moins de jours tant que l'historique est plus court) et à juger un prix
barré : une boutique peut barrer un prix supérieur à ce qu'elle pratiquait avant sa remise.
"""
from __future__ import annotations

import json
import logging
import math
import os
import tempfile
import threading
import time
from pathlib import Path

JOURS_GARDES = 120
FENETRE_J = 30            # « plus bas relevé sur 30 jours »
ECRITURE_S = 300          # le fichier (quelques Mo) est réécrit au plus toutes les 5 minutes
VERROU = threading.Lock()
log = logging.getLogger("historique")


def _jour(t: float | None = None) -> str:
    return time.strftime("%Y-%m-%d", time.localtime(t))


def _depuis(jours: int, aujourd_hui: str) -> str:
    t = time.mktime(time.strptime(aujourd_hui, "%Y-%m-%d")) - jours * 86400
    return time.strftime("%Y-%m-%d", time.localtime(t + 3600))   # + 1 h : changement d'heure


def _nombre(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def _point_valide(p) -> bool:
    """[jour, prix, prix barré ou None, disponibilité ou None] ; un point mal formé est ignoré."""
    return (isinstance(p, list) and len(p) == 4 and isinstance(p[0], str) and len(p[0]) == 10 and _nombre(p[1])
            and (p[2] is None or _nombre(p[2])) and (p[3] is None or isinstance(p[3], str)))


def _ecart_j(a: str, b: str) -> int:
    return round((time.mktime(time.strptime(b, "%Y-%m-%d")) - time.mktime(time.strptime(a, "%Y-%m-%d"))) / 86400)


class Historique:
    def __init__(self, dossier: Path, ecriture_s: float = ECRITURE_S):
        self.fichier = Path(dossier) / "historique_prix.json"
        self._d: dict | None = None
        # Écriture différée : la lecture des fiches LEGO officiel note un point par fiche, quelques
        # centaines par jour ; un arrêt du conteneur perd au plus ECRITURE_S secondes de points, que la
        # lecture suivante de chaque offre rétablit.
        self.ecriture_s, self._ecrit, self._minuteur = ecriture_s, 0.0, None

    def _charger(self) -> dict:
        """Fichier absent : historique vide. Illisible (coupure pendant une écriture) : mis de côté sous
        `.illisible` et historique repris à zéro, pour que le catalogue reste servi."""
        if self._d is None:
            try:
                d = json.loads(self.fichier.read_text("utf-8"))
            except FileNotFoundError:
                d = {}
            except ValueError as e:   # JSON ou encodage abîmé ; OSError (lecture impossible) : levée, fichier intact
                d = self._mettre_de_cote(e)
            offres = d.get("offres") if isinstance(d, dict) else None
            self._d = {k: [p for p in v if _point_valide(p)] for k, v in offres.items()
                       if isinstance(v, list)} if isinstance(offres, dict) else {}
        return self._d

    def _mettre_de_cote(self, e: Exception) -> dict:
        log.error("historique des prix illisible (%s) : mis de côté, historique repris à zéro", e)
        try:
            os.replace(self.fichier, self.fichier.with_suffix(".illisible"))
        except OSError:
            pass
        return {}

    def noter(self, offres: list[dict], jour: str | None = None) -> None:
        """Note le prix du jour de chaque offre ; une seconde lecture le même jour remplace la première."""
        jour = jour or _jour()
        limite = _depuis(JOURS_GARDES, jour)
        with VERROU:
            d = self._charger()
            change = False
            for o in offres:
                prix = o.get("prix")
                if not _nombre(prix) or prix <= 0 or not o.get("cle"):
                    continue
                barre = o.get("barre") if _nombre(o.get("barre")) and o["barre"] > prix else None
                point = [jour, round(float(prix), 2), barre, o.get("dispo")]
                serie = d.setdefault(o["cle"], [])
                if serie and serie[-1][0] == jour:
                    if serie[-1] == point:
                        continue
                    serie[-1] = point
                else:
                    serie.append(point)
                change = True
            if change:
                # séries trop anciennes retirées : points de plus de JOURS_GARDES jours, offres disparues
                for cle in list(d):
                    serie = [p for p in d[cle] if p[0] >= limite]
                    if serie:
                        d[cle] = serie
                    else:
                        del d[cle]
                self._planifier()

    def _planifier(self) -> None:
        """Écrit tout de suite si la dernière écriture est assez ancienne, sinon une fois le délai passé."""
        attente = self._ecrit + self.ecriture_s - time.time()
        if attente <= 0:
            self._ecrire()
        elif self._minuteur is None:
            self._minuteur = threading.Timer(attente, self.vider)
            self._minuteur.daemon = True
            self._minuteur.start()

    def _ecrire(self) -> None:
        """JSON compact (une ligne), écrit à côté puis renommé : jamais de fichier à moitié écrit."""
        try:
            self.fichier.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=self.fichier.parent, prefix=".tmp-")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump({"offres": self._charger()}, f, ensure_ascii=False, separators=(",", ":"))
                os.replace(tmp, self.fichier)
            except BaseException:
                os.unlink(tmp)
                raise
        except OSError:
            log.exception("historique des prix non écrit")
        self._ecrit = time.time()

    def vider(self) -> None:
        with VERROU:
            self._minuteur = None
            self._ecrire()

    def serie(self, cle: str, jours: int = 90) -> list[list]:
        limite = _depuis(jours, _jour())
        with VERROU:
            return [p for p in self._charger().get(cle, []) if p[0] >= limite]

    def resume(self, cle: str, aujourd_hui: str | None = None) -> dict | None:
        """{min30, jours, avant_remise, avant_remise_j}, chaque paire absente faute de relevé :
        - min30 : plus bas prix relevé hors épuisement sur les FENETRE_J jours précédant aujourd'hui (le
          jour même exclu, pour juger le prix du jour) ; `jours` : jours couverts par ce relevé ;
        - avant_remise : plus bas prix relevé hors épuisement sur les FENETRE_J jours précédant le début de
          la remise en cours (jours de suite avec un prix barré, jusqu'au dernier point) ; `avant_remise_j` :
          jours couverts. Une promotion stable n'est donc pas jugée contre ses propres prix.
        None sans aucun point utile."""
        aujourd_hui = aujourd_hui or _jour()
        limite = _depuis(FENETRE_J, aujourd_hui)
        with VERROU:
            serie = list(self._charger().get(cle) or [])
        vendus = [p for p in serie if p[3] != "epuise"]
        out = {}
        avant = [p for p in vendus if limite <= p[0] < aujourd_hui]
        if avant:
            out.update(min30=min(p[1] for p in avant), jours=_ecart_j(avant[0][0], aujourd_hui))
        if serie and serie[-1][2] is not None:
            debut = len(serie) - 1   # jours épuisés (sans prix barré lisible) sautés : ils ne coupent pas la remise
            while debut > 0 and (serie[debut - 1][2] is not None or serie[debut - 1][3] == "epuise"):
                debut -= 1
            while serie[debut][2] is None:
                debut += 1
            jour_remise = serie[debut][0]
            ref = [p for p in vendus if _depuis(FENETRE_J, jour_remise) <= p[0] < jour_remise]
            if ref:
                out.update(avant_remise=min(p[1] for p in ref), avant_remise_j=_ecart_j(ref[0][0], jour_remise))
        return out or None

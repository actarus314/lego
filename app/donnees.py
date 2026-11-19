"""Données persistantes : relevés de prix et sélection partagée.

Le catalogue (sets, tests, avis) vient de l'image ; seuls les relevés et la
sélection vivent dans le dossier de données, en JSON, écrits de façon
atomique (fichier temporaire puis renommage).
"""
from __future__ import annotations

import json
import os
import re
import tempfile
import threading
import time
from pathlib import Path

VERROU = threading.RLock()
STATUTS = ("idee", "retenu", "achete")
HISTORIQUE = 30
CHAMPS = {"url": 2048, "nom": 200, "note": 1000, "img": 2048}


def _lire(chemin: Path, defaut):
    try:
        return json.loads(chemin.read_text("utf-8"))
    except FileNotFoundError:
        return defaut


def _ecrire(chemin: Path, valeur) -> None:
    chemin.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=chemin.parent, prefix=".tmp-")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(valeur, f, ensure_ascii=False, indent=1)
    os.replace(tmp, chemin)


class Depot:
    def __init__(self, dossier: Path, catalogue: Path):
        self.dossier = Path(dossier)
        self.catalogue_fichier = Path(catalogue)
        self.f_releves = self.dossier / "releves.json"
        self.f_selection = self.dossier / "selection.json"

    # ----- catalogue et relevés -----
    def catalogue(self) -> list[dict]:
        cat = json.loads(self.catalogue_fichier.read_text("utf-8"))
        rel = _lire(self.f_releves, {}).get("sets", {})
        for it in cat:
            r = rel.get(it["id"])
            if r:
                for k in ("prix", "dispo", "img", "pcs"):
                    if r.get(k) is not None:
                        it[k] = r[k]
                it["releve"] = r.get("le")
        return cat

    def releves(self) -> dict:
        return _lire(self.f_releves, {"sets": {}, "dernier": None})

    def enregistrer_releve(self, sets: dict, journal: dict) -> None:
        """Fusionne les sets lus, garde le journal complet du dernier relevé et
        un résumé des HISTORIQUE derniers (le plus récent en tête)."""
        with VERROU:
            d = self.releves()
            d["sets"].update(sets)
            resume = {k: v for k, v in journal.items() if k != "sets"}
            ancien = d.get("dernier") or {}
            if journal.get("portee") == "echecs" and ancien.get("sets"):
                # Relance des échecs : le relevé complet reste la référence, ses lignes relancées sont remplacées.
                neuves = {s["id"]: s for s in journal.get("sets", [])}
                lignes = [neuves.get(s["id"], s) for s in ancien["sets"]]
                compte = lambda st: sum(1 for s in lignes if s.get("statut") == st)
                journal = {**ancien, "sets": lignes, "lus": compte("ok"), "echecs": compte("echec"),
                           "sautes": compte("saute"), "changes": sum(1 for s in lignes if s.get("changes")),
                           "relance": {"le": journal.get("le"), "par": journal.get("par"), "total": journal.get("total")}}
            d["dernier"] = journal
            d["historique"] = ([resume] + d.get("historique", []))[:HISTORIQUE]
            _ecrire(self.f_releves, d)

    def historique(self) -> list[dict]:
        return self.releves().get("historique", [])

    # ----- sélection -----
    def selection(self) -> list[dict]:
        return _lire(self.f_selection, [])

    @staticmethod
    def valider(item: dict) -> dict:
        if not isinstance(item, dict):
            raise ValueError("format invalide")
        out = {}
        for k, n in CHAMPS.items():
            v = item.get(k)
            if v is not None:
                v = str(v).strip()[:n]
            out[k] = v or ""
        if not re.match(r"^https?://", out["url"]):
            raise ValueError("lien invalide : il doit commencer par https://")
        if out["img"] and not re.match(r"^https?://", out["img"]):
            out["img"] = ""
        for k in ("prix",):
            v = item.get(k)
            out[k] = round(float(v), 2) if isinstance(v, (int, float)) and 0 <= v < 100000 else None
        v = item.get("pcs")
        out["pcs"] = int(v) if isinstance(v, (int, float)) and 0 < v < 100000 else None
        out["statut"] = item.get("statut") if item.get("statut") in STATUTS else "idee"
        return out

    def enregistrer(self, ident: str, item: dict, par: str) -> dict:
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", ident):
            raise ValueError("identifiant invalide")
        propre = self.valider(item)
        with VERROU:
            sel = self.selection()
            ex = next((s for s in sel if s["id"] == ident), None)
            if ex:
                ex.update(propre)
                ex["modifie"] = time.strftime("%Y-%m-%dT%H:%M:%S")
                ex["modifie_par"] = par
                res = ex
            else:
                res = {"id": ident, **propre, "cree": time.strftime("%Y-%m-%dT%H:%M:%S"), "par": par}
                sel.append(res)
            _ecrire(self.f_selection, sel)
            return res

    def supprimer(self, ident: str) -> bool:
        with VERROU:
            sel = self.selection()
            reste = [s for s in sel if s["id"] != ident]
            if len(reste) == len(sel):
                return False
            _ecrire(self.f_selection, reste)
            return True

"""Logos des marques : l'icône du site officiel de chaque marque (`data/marques.json`), récupérée
par le service et gardée dans son dossier de données. Le dépôt ne contient aucun logo.

Une icône est cherchée dans la page d'accueil (apple-touch-icon, puis la plus grande icône
déclarée, puis /favicon.ico), vérifiée par sa signature (PNG, ICO, JPEG, GIF, WebP, SVG) et
relue une fois par mois. Une marque sans site connu garde la pastille à initiales.
"""
from __future__ import annotations

import json
import logging
import re
import threading
import time
from pathlib import Path
from urllib.parse import urljoin

from . import lien, normalise as n
from .donnees import _ecrire, _lire

log = logging.getLogger("logos")
RACINE = Path(__file__).resolve().parent.parent
TAILLE_MAX = 500 * 1024
SIGNATURES = [(b"\x89PNG", "png"), (b"\x00\x00\x01\x00", "ico"), (b"\xff\xd8", "jpg"), (b"GIF8", "gif")]
TYPES = {"png": "image/png", "ico": "image/x-icon", "jpg": "image/jpeg", "gif": "image/gif",
         "webp": "image/webp", "svg": "image/svg+xml"}
VERROU = threading.Lock()


def slug(marque: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", n.sans_accents(marque)).strip("-")


def sites() -> dict[str, dict]:
    return json.loads((RACINE / "data" / "marques.json").read_text("utf-8"))["marques"]


def _format(corps: bytes) -> str | None:
    for sig, ext in SIGNATURES:
        if corps.startswith(sig):
            return ext
    if corps[:4] == b"RIFF" and corps[8:12] == b"WEBP":
        return "webp"
    if re.match(rb"\s*(<\?xml[^>]*>\s*)?(<!--.*?-->\s*)*<svg\b", corps[:2000], re.S):
        return "svg"
    return None


def _candidats(site: str) -> list[str]:
    r = lien.recuperer("https://" + site)
    page = r.corps.decode("utf-8", "replace")
    liens = []
    for balise in re.findall(r"<link\b[^>]*>", page, re.I):
        rel = re.search(r'rel=["\']([^"\']+)["\']', balise, re.I)
        href = re.search(r'href=["\']([^"\']+)["\']', balise, re.I)
        if not (rel and href and "icon" in rel.group(1).lower()):
            continue
        tailles = [int(x) for x in re.findall(r"(\d+)x\d+", (re.search(r'sizes=["\']([^"\']+)', balise) or [None, ""])[1])]
        rang = (2 if "apple-touch" in rel.group(1).lower() else 1, max(tailles, default=32))
        liens.append((rang, urljoin(r.url, href.group(1).replace("&amp;", "&"))))
    liens.sort(key=lambda x: x[0], reverse=True)
    return [u for _, u in liens] + [urljoin(r.url, "/favicon.ico")]


def recuperer(conf: dict) -> tuple[bytes, str]:
    for url in ([conf["icone"]] if conf.get("icone") else _candidats(conf["site"])):
        if url.startswith("//"):
            url = "https:" + url
        try:
            r = lien.recuperer(url, accept="image/*,*/*;q=0.5")
        except (lien.LienRefuse, OSError, ValueError):
            continue
        ext = _format(r.corps)
        if ext and len(r.corps) <= TAILLE_MAX:
            return r.corps, ext
    raise ValueError("aucune icône lisible")


class Logos:
    def __init__(self, dossier: Path):
        self.dossier = Path(dossier) / "logos"
        self.fichier = self.dossier / "logos.json"

    def etat(self) -> dict:
        return _lire(self.fichier, {})

    def disponibles(self) -> dict[str, str]:
        """{slug: adresse} des logos présents, pour la page."""
        return {s: f"logos/{s}?v={e['le'][:10]}" for s, e in self.etat().items() if e.get("fichier")}

    def chemin(self, s: str) -> tuple[Path, str] | None:
        e = self.etat().get(s)
        if not e or not e.get("fichier"):
            return None
        p = self.dossier / e["fichier"]
        return (p, TYPES[e["format"]]) if p.is_file() else None

    def actualiser(self, age_max_j: float = 30) -> dict:
        """Récupère les logos absents ou de plus de `age_max_j` jours. Rend {lus, echecs}."""
        with VERROU:
            etat = self.etat()
            lus, echecs = 0, 0
            for marque, conf in sites().items():
                s = slug(marque)
                e = etat.get(s) or {}
                if e.get("le") and time.time() - time.mktime(time.strptime(e["le"], "%Y-%m-%dT%H:%M:%S")) < age_max_j * 86400:
                    continue
                try:
                    corps, ext = recuperer(conf)
                    self.dossier.mkdir(parents=True, exist_ok=True)
                    (self.dossier / f"{s}.{ext}").write_bytes(corps)
                    etat[s] = {"marque": marque, "fichier": f"{s}.{ext}", "format": ext,
                               "le": time.strftime("%Y-%m-%dT%H:%M:%S"), "source": conf.get("icone") or conf["site"]}
                    lus += 1
                except Exception as ex:  # une marque sans logo garde sa pastille
                    log.info("logo %s non récupéré : %s", marque, getattr(ex, "public", ex))
                    etat[s] = {**e, "marque": marque, "le": time.strftime("%Y-%m-%dT%H:%M:%S"), "erreur": True}
                    echecs += 1
                time.sleep(1)
            _ecrire(self.fichier, etat)
            return {"lus": lus, "echecs": echecs}

    def demarrer(self) -> None:
        def boucle():
            time.sleep(30)
            while True:
                try:
                    self.actualiser()
                except Exception:
                    log.exception("actualisation des logos en échec")
                time.sleep(86400)
        threading.Thread(target=boucle, name="logos", daemon=True).start()

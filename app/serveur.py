"""Serveur HTTP du Carnet de briques (bibliothèque standard uniquement).

Routes :
  GET    /                       page
  GET    /api/sante              état du service et de la synchronisation (sans authentification ; 503 en panne)
  GET    /api/catalogue          sets de toutes les sources actives, regroupés (compressé si le client l'accepte)
  GET    /api/offre?cle=…        relit une offre sur sa boutique
  GET    /api/synchro            synchronisation en cours, dernier passage, historique
  POST   /api/synchro            synchronise maintenant ({"sources": [...]} : seulement celles-ci)
  GET    /api/selection          sélection visible par le compte connecté
  PUT    /api/selection/<id>     ajoute ou modifie un produit
  DELETE /api/selection/<id>     retire un produit
  GET    /api/lien?url=…         lit une page produit (nom, prix, photo, pièces)
"""
from __future__ import annotations

import gzip
import json
import logging
import os
import re
import secrets
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from . import acces, lien, normalise, synchro
from .donnees import Depot
from .index import Index

VERSION = os.environ.get("VERSION_APP", "dev")
RACINE = Path(__file__).resolve().parent.parent
MODELE = RACINE / "web" / "index.html"
log = logging.getLogger("serveur")


def injecter(page: str, catalogue: list, mode: dict, nonce: str) -> str:
    def bloc(nom, valeur):
        nonlocal page
        motif = re.compile(r"/\*" + nom + r"\*/.*?/\*FIN-" + nom + r"\*/", re.S)
        txt = json.dumps(valeur, ensure_ascii=False).replace("</", "<\\/")
        page = motif.sub(lambda _: f"/*{nom}*/{txt}/*FIN-{nom}*/", page, count=1)
    bloc("CATALOGUE", catalogue)
    bloc("MODE", mode)
    return page.replace("<script>", f'<script nonce="{nonce}">')


class Gestionnaire(BaseHTTPRequestHandler):
    server_version = "carnet-briques"
    sys_version = ""
    depot: Depot
    index: Index
    journal: synchro.Journal
    gardien: acces.Gardien | None
    masquer: set[str]

    # ---------- réponses ----------
    def _entetes_securite(self, nonce: str | None = None):
        csp = ("default-src 'none'; img-src https: data:; font-src https://fonts.gstatic.com; "
               "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; connect-src 'self'; "
               "base-uri 'none'; form-action 'self'; frame-ancestors 'none'")
        if nonce:
            csp += f"; script-src 'nonce-{nonce}'"
        self.send_header("Content-Security-Policy", csp)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Cache-Control", "no-store")

    def _json(self, code: int, valeur) -> None:
        corps = json.dumps(valeur, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(corps)))
        self._entetes_securite()
        self.end_headers()
        self.wfile.write(corps)

    def _erreur(self, code: int, message: str) -> None:
        self._json(code, {"erreur": message})

    def log_message(self, fmt, *args):
        log.info("%s %s", self.address_string(), fmt % args)

    # ---------- accès ----------
    def _compte(self) -> str | None:
        if self.gardien is None:
            return "partage"
        nom = self.gardien.authentifier(self.headers.get("Authorization"))
        if nom:
            return nom
        self.send_response(HTTPStatus.UNAUTHORIZED)
        self.send_header("WWW-Authenticate", 'Basic realm="Carnet de briques", charset="UTF-8"')
        self.send_header("Content-Length", "0")
        self._entetes_securite()
        self.end_headers()
        return None

    def _corps_json(self, limite: int = 64 * 1024):
        n = int(self.headers.get("Content-Length") or 0)
        if n > limite:
            raise ValueError("requête trop volumineuse")
        return json.loads(self.rfile.read(n) or b"{}")

    def _visible(self, compte: str, item: dict) -> bool:
        return not (compte in self.masquer and item.get("statut") == "achete")

    def _json_compresse(self, valeur) -> None:
        corps = json.dumps(valeur, ensure_ascii=False, separators=(",", ":")).encode()
        gz = "gzip" in (self.headers.get("Accept-Encoding") or "")
        if gz:
            corps = gzip.compress(corps, 6)
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        if gz:
            self.send_header("Content-Encoding", "gzip")
        self.send_header("Content-Length", str(len(corps)))
        self._entetes_securite()
        self.end_headers()
        self.wfile.write(corps)

    def _catalogue(self) -> dict:
        ids = [s["id"] for s in synchro.actives()]
        return {"sets": self.index.sets(ids), "themes": normalise.themes_disponibles(),
                "sources": [{k: s.get(k) for k in ("id", "nom", "pays_boutique", "livraison")} for s in synchro.actives()]}

    # ---------- routes ----------
    def do_GET(self):
        url = urlsplit(self.path)
        if url.path == "/api/sante":
            bon, raison = synchro.sante(self.journal)
            return self._json(200 if bon else 503, {"etat": "ok" if bon else "degrade", "raison": raison, "version": VERSION})
        compte = self._compte()
        if not compte:
            return
        if url.path == "/":
            return self._page(compte)
        if url.path == "/api/selection":
            return self._json(200, [s for s in self.depot.selection() if self._visible(compte, s)])
        if url.path == "/api/catalogue":
            return self._json_compresse(self._catalogue())
        if url.path == "/api/synchro":
            d = self.journal.lire()
            return self._json(200, {"etat": synchro.etat(), "dernier": d.get("dernier"),
                                    "historique": d.get("historique", []), "sources": synchro.actives(),
                                    "rotation": synchro.etat_rotation(self.index)})
        if url.path == "/api/offre":
            cle = (parse_qs(url.query).get("cle") or [""])[0]
            try:
                return self._json(200, synchro.offre_directe(self.index, cle))
            except lien.LienRefuse as e:
                return self._erreur(422, f"Relecture impossible : {e.public}")
            except (OSError, ValueError):
                log.info("relecture d'offre en échec", exc_info=True)
                return self._erreur(422, "Relecture impossible : boutique injoignable ou réponse illisible")
        if url.path == "/api/lien":
            cible = (parse_qs(url.query).get("url") or [""])[0]
            try:
                return self._json(200, lien.lire(cible))
            except lien.LienRefuse as e:
                return self._erreur(422, f"Lecture impossible : {e.public}")
            except (OSError, ValueError):
                log.info("lecture de lien en échec", exc_info=True)
                return self._erreur(422, "Lecture impossible : page injoignable ou illisible")
        self._erreur(404, "introuvable")

    def do_PUT(self):
        compte = self._compte()
        if not compte:
            return
        m = re.fullmatch(r"/api/selection/([A-Za-z0-9_-]{1,40})", urlsplit(self.path).path)
        if not m:
            return self._erreur(404, "introuvable")
        ex = next((s for s in self.depot.selection() if s["id"] == m.group(1)), None)
        if ex and not self._visible(compte, ex):
            return self._erreur(404, "introuvable")
        try:
            item = self.depot.enregistrer(m.group(1), self._corps_json(), compte)
        except ValueError as e:
            return self._erreur(400, str(e))
        self._json(200, item if self._visible(compte, item) else {"id": item["id"], "masque": True})

    def do_DELETE(self):
        compte = self._compte()
        if not compte:
            return
        m = re.fullmatch(r"/api/selection/([A-Za-z0-9_-]{1,40})", urlsplit(self.path).path)
        if not m:
            return self._erreur(404, "introuvable")
        ex = next((s for s in self.depot.selection() if s["id"] == m.group(1)), None)
        if not ex or not self._visible(compte, ex):
            return self._erreur(404, "introuvable")
        self.depot.supprimer(m.group(1))
        self._json(200, {"retire": m.group(1)})

    def do_POST(self):
        compte = self._compte()
        if not compte:
            return
        if urlsplit(self.path).path == "/api/synchro":
            try:
                corps = self._corps_json()
            except ValueError:
                return self._erreur(400, "requête invalide")
            ids = corps.get("sources") if isinstance(corps, dict) else None
            if ids is not None and not (isinstance(ids, list) and all(isinstance(x, str) for x in ids)):
                return self._erreur(400, "liste de sources invalide")
            if synchro.EN_COURS.locked():
                return self._json(202, {"etat": "deja_en_cours"})
            threading.Thread(target=synchro.synchroniser, args=(self.index, self.journal),
                             kwargs={"par": compte, "ids": ids}, daemon=True).start()
            total = len([s for s in synchro.actives() if ids is None or s["id"] in ids])
            return self._json(202, {"etat": "lance", "total": total})
        self._erreur(404, "introuvable")

    def _page(self, compte: str):
        nonce = secrets.token_urlsafe(16)
        mode = {"serveur": True, "compte": compte, "version": VERSION, "achats_masques": compte in self.masquer}
        corps = injecter(MODELE.read_text("utf-8"), {"sets": [], "themes": [], "sources": []}, mode, nonce).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(corps)))
        self._entetes_securite(nonce)
        self.end_headers()
        self.wfile.write(corps)


def main():
    logging.basicConfig(level=os.environ.get("JOURNAL", "INFO"), format="%(asctime)s %(name)s %(message)s")
    donnees = Path(os.environ.get("DOSSIER_DONNEES", "/donnees"))
    Gestionnaire.depot = Depot(donnees)
    Gestionnaire.gardien = acces.depuis_env()
    Gestionnaire.masquer = {n.strip() for n in os.environ.get("ACHATS_MASQUES_POUR", "").split(",") if n.strip()}
    Gestionnaire.index = Index(donnees)
    Gestionnaire.journal = synchro.Journal(donnees)
    heures = float(os.environ.get("RELEVE_HEURES", "24"))
    synchro.programmer(Gestionnaire.index, Gestionnaire.journal, heures)
    if heures > 0:
        synchro.demarrer_rotation(Gestionnaire.index, lambda: [s.get("url") for s in Gestionnaire.depot.selection()])
    port = int(os.environ.get("PORT", "8080"))
    srv = ThreadingHTTPServer(("0.0.0.0", port), Gestionnaire)
    log.info("Carnet de briques %s sur le port %s, données dans %s", VERSION, port, donnees)
    srv.serve_forever()


if __name__ == "__main__":
    main()

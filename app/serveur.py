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
  GET    /api/alertes            canaux d'alerte du compte connecté (adresses masquées)
  GET    /api/boutiques          champs relevés de chaque boutique, avec leur origine (boutiques.py)
  GET    /photo?u=…&l=…          photo du catalogue ou de la sélection, depuis le cache local (cache_photos.py)
  POST   /api/alertes/essai      envoie un message d'essai sur ces canaux
"""
from __future__ import annotations

import gzip
import json
import logging
import os
import re
import signal
import secrets
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from . import acces, alertes as alertes_mod, boutiques as boutiques_mod, index as index_mod, lien, logos as logos_mod, normalise, qualite, surveillance, synchro, tests_auto
from .reglage import reglage
from .donnees import Depot, dans
from .index import Index
from .sources.occasion import Occasion

VERSION = reglage("VERSION_APP", "dev")
RACINE = Path(__file__).resolve().parent.parent
MODELE = RACINE / "web" / "index.html"
POLICES = RACINE / "web" / "polices"
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


def _masquer(adresse: str) -> str:
    """j…@exemple.fr : l'adresse reste reconnaissable sans être affichée en entier."""
    nom, arobase, domaine = adresse.partition("@")
    return (nom[:1] + "…" + arobase + domaine) if arobase else (adresse[:3] + "…" + adresse[-2:])


class Gestionnaire(BaseHTTPRequestHandler):
    server_version = "carnet-briques"
    sys_version = ""
    depot: Depot
    index: Index
    journal: synchro.Journal
    logos: logos_mod.Logos
    alertes: alertes_mod.Alertes
    surveillance: surveillance.Surveillance | None = None
    gardien: acces.Gardien | None
    masquer: set[str]
    admins: set[str] = set()
    donnees: Path = Path("/donnees")
    occasion: Occasion | None = None
    _photos_connues: tuple = (None, frozenset())
    _construction = threading.Lock()

    # ---------- réponses ----------
    def _entetes_securite(self, nonce: str | None = None):
        csp = ("default-src 'none'; img-src 'self' https: data:; font-src 'self'; "
               "style-src 'self' 'unsafe-inline'; connect-src 'self'; "
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

    def _statique(self, dossier: Path, nom: str, type_: str, bac_a_sable: bool = False) -> None:
        try:
            chemin = dans(dossier, nom)
        except ValueError:
            return self._erreur(404, "introuvable")
        if not chemin.is_file():
            return self._erreur(404, "introuvable")
        corps = chemin.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", type_)
        if bac_a_sable:  # image venue d'un site tiers (SVG compris) : aucun script, aucune ressource
            self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'; sandbox")
        self.send_header("Content-Length", str(len(corps)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "public, max-age=604800")
        self.end_headers()
        self.wfile.write(corps)

    def _photo_connue(self, url: str) -> bool:
        """Adresse d'une photo du catalogue ou de la sélection : seules celles-là sont servies."""
        brutes = self.index.photos_brutes
        if Gestionnaire._photos_connues[0] is not brutes:   # référence gardée : jamais confondue avec une liste plus récente
            Gestionnaire._photos_connues = (brutes, frozenset(brutes[0]) | frozenset(brutes[1]))
        return url in Gestionnaire._photos_connues[1] or any(x.get("img") == url for x in self.depot.selection())

    def _photo(self, requete: str) -> None:
        q = parse_qs(requete)
        u = (q.get("u") or [""])[0]
        try:
            largeur = int((q.get("l") or ["400"])[0])
        except ValueError:
            largeur = 400
        if not self.index.photos_brutes[0]:   # index jamais construit depuis le démarrage : une fois, sous verrou
            with Gestionnaire._construction:
                if not self.index.photos_brutes[0]:
                    self.index.sets([s["id"] for s in synchro.actives()])
        if not u.startswith("https://") or not self._photo_connue(u):
            return self._erreur(404, "photo inconnue")
        r = self.index.photos.cache.servir(u, largeur)
        if not r:
            return self._erreur(404, "photo indisponible")
        corps, type_ = r
        self.send_response(200)
        self.send_header("Content-Type", type_)
        self.send_header("Content-Length", str(len(corps)))
        self.send_header("Content-Security-Policy", "default-src 'none'; sandbox")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "private, max-age=604800")
        self.end_headers()
        self.wfile.write(corps)

    def _catalogue(self) -> dict:
        ids = [s["id"] for s in synchro.actives()]
        return {"sets": self.index.sets(ids), "themes": normalise.themes_disponibles(),
                "sources": [{k: s.get(k) for k in ("id", "nom", "pays_boutique", "livraison")} for s in synchro.actives()]}

    # ---------- routes ----------
    def do_GET(self):
        url = urlsplit(self.path)
        m = re.fullmatch(r"/polices/([a-z0-9-]+\.(woff2|css))", url.path)
        if m:
            return self._statique(POLICES, m.group(1), "font/woff2" if m.group(2) == "woff2" else "text/css; charset=utf-8")
        m = re.fullmatch(r"/logos/([a-z0-9-]{1,40})", url.path)
        if m:
            fichier = self.logos.chemin(m.group(1))
            if not fichier:
                return self._erreur(404, "introuvable")
            return self._statique(self.logos.dossier, fichier[0], fichier[1], bac_a_sable=True)
        if url.path == "/api/sante":
            bon, raison = synchro.sante(self.journal)
            return self._json(200 if bon else 503, {"etat": "ok" if bon else "degrade", "raison": raison, "version": VERSION})
        compte = self._compte()
        if not compte:
            return
        if url.path == "/":
            return self._page(compte)
        if url.path == "/photo":
            return self._photo(url.query)
        if url.path == "/api/selection":
            ecartees = self.index.photos.ecartees()  # photo écartée : la page montre celle du catalogue
            return self._json(200, [({**s, "img_ecartee": True} if s.get("img") in ecartees else s)
                                    for s in self.depot.selection() if self._visible(compte, s)])
        if url.path == "/api/catalogue":
            cat = self._catalogue()  # photos et liens de tests servis à l'ouverture d'une fiche (/api/fiche)
            cat["sets"] = [{k: v for k, v in x.items() if k not in ("images", "liens_tests")} for x in cat["sets"]]
            return self._json_compresse(cat)
        if url.path == "/api/synchro":
            d = self.journal.lire()
            return self._json(200, {"etat": synchro.etat(), "dernier": d.get("dernier"),
                                    "historique": d.get("historique", []), "sources": synchro.actives(),
                                    "rotation": synchro.etat_rotation(self.index),
                                    "selection": synchro.etat_selection(),
                                    "photos": self.index.photos.resume(),
                                    "occasion": self.occasion.etat() if self.occasion else {},
                                    "baisses": self.surveillance.etat()["baisses"] if self.surveillance else []})
        if url.path == "/api/offre":
            cle = (parse_qs(url.query).get("cle") or [""])[0]
            try:
                return self._json(200, synchro.offre_directe(self.index, cle))
            except lien.LienRefuse as e:
                return self._erreur(422, f"Relecture impossible : {e.public}")
            except (OSError, ValueError):
                log.info("relecture d'offre en échec", exc_info=True)
                return self._erreur(422, "Relecture impossible : boutique injoignable ou réponse illisible")
        if url.path == "/api/relire":
            cles = [c for c in (parse_qs(url.query).get("cle") or []) if re.fullmatch(r"[a-z0-9_-]{1,40}:[A-Za-z0-9._:-]{1,200}", c)]
            if not cles:
                return self._erreur(400, "aucune offre à relire")
            return self._json(200, synchro.relire(self.index, cles))
        if url.path == "/api/fiche":
            sid = (parse_qs(url.query).get("id") or [""])[0]
            s = next((x for x in self._catalogue()["sets"] if x["id"] == sid), None)
            if not s:
                return self._erreur(404, "set introuvable")
            occ = self.occasion.pour(s.get("numero")) if self.occasion and s.get("marque") == "LEGO officiel" else {}
            return self._json(200, {"images": s.get("images") or ([s["img"]] if s.get("img") else []),
                                    "liens_tests": s.get("liens_tests", []), "occasion": occ,
                                    "historique": {o["cle"]: self.index.historique.serie(o["cle"]) for o in s["offres"]}})
        if url.path == "/api/boutiques":
            return self._json(200, boutiques_mod.toutes(Gestionnaire.donnees))
        if url.path == "/api/alertes":
            canaux = alertes_mod.destinataires().get(compte, [])
            return self._json(200, {"canaux": [{"canal": c, "adresse": _masquer(a)} for c, a in canaux],
                                    "comptes": len(alertes_mod.destinataires())})
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
        if urlsplit(self.path).path == "/api/alertes/essai":
            if not alertes_mod.destinataires().get(compte):
                return self._erreur(409, "aucun canal d'alerte pour ce compte")
            erreurs = alertes_mod.envoyer(compte, "Carnet de briques : essai des alertes",
                                          "Les alertes de la sélection arriveront ici.")
            if erreurs:
                return self._json(502, {"erreur": "; ".join(erreurs), "erreurs": erreurs})
            return self._json(200, {"erreurs": []})
        if urlsplit(self.path).path == "/api/type":
            return self._imposer_type(compte)
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

    def _imposer_type(self, compte: str):
        """Type de briques imposé à un set depuis sa fiche, par un compte de ADMINS seulement. Requête
        JSON du même site exigée (une page tierce ne peut pas l'envoyer avec les identifiants du navigateur)."""
        if compte not in self.admins:
            return self._erreur(403, "réservé aux comptes administrateurs")
        if (self.headers.get("Content-Type") or "").split(";")[0].strip() != "application/json" \
                or self.headers.get("Sec-Fetch-Site", "same-origin") not in ("same-origin", "none"):
            return self._erreur(403, "requête refusée")
        try:
            corps = self._corps_json(4096)
        except ValueError:
            return self._erreur(400, "requête invalide")
        ident = corps.get("id") if isinstance(corps, dict) else None
        type_ = corps.get("type") if isinstance(corps, dict) else None
        if not isinstance(ident, str) or (type_ is not None and type_ not in index_mod.TYPES):
            return self._erreur(400, "requête invalide")
        if not any(x["id"] == ident for x in self._catalogue()["sets"]):
            return self._erreur(404, "set introuvable")
        self.index.imposer_type(ident, type_, compte)
        log.info("type de %s imposé à %s par %s", ident, type_, compte)
        return self._json(200, {"id": ident, "type": type_})

    def _page(self, compte: str):
        nonce = secrets.token_urlsafe(16)
        mode = {"serveur": True, "compte": compte, "version": VERSION, "achats_masques": compte in self.masquer,
                "admin": compte in self.admins,
                "logos": self.logos.disponibles(), "liens_marques": self.logos.liens(),
                "qualite": qualite.pour_la_page()}
        corps = injecter(MODELE.read_text("utf-8"), {"sets": [], "themes": [], "sources": []}, mode, nonce).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(corps)))
        self._entetes_securite(nonce)
        self.end_headers()
        self.wfile.write(corps)


def photos_a_verifier() -> list[str]:
    """Photos principales des sets, puis celles de la sélection, puis les galeries."""
    idx = Gestionnaire.index
    idx.sets([s["id"] for s in synchro.actives()])
    principales, galeries = idx.photos_brutes
    choisies = [x.get("img") for x in Gestionnaire.depot.selection() if x.get("img")]
    return list(dict.fromkeys(principales + choisies + galeries))


def numeros_lego() -> list[str]:
    """Numéros des sets LEGO officiel : ceux de la sélection d'abord, puis le catalogue."""
    sets = Gestionnaire.index.sets([s["id"] for s in synchro.actives()])
    lego = {s["id"]: s["numero"] for s in sets if s.get("marque") == "LEGO officiel" and s.get("numero")}
    choisis = synchro.numeros_selection(Gestionnaire.index, [x.get("url") for x in Gestionnaire.depot.selection()])
    return list(dict.fromkeys([n for n in lego.values() if n in choisis] + list(lego.values())))


def main():
    logging.basicConfig(level=reglage("JOURNAL", "INFO"), format="%(asctime)s %(name)s %(message)s")
    donnees = Path(reglage("CHEMIN_DONNEES", "/donnees"))
    Gestionnaire.donnees = donnees
    Gestionnaire.depot = Depot(donnees)
    Gestionnaire.gardien = acces.depuis_env()
    manque = alertes_mod.reglages_manquants()
    if manque:
        raise SystemExit("Réglages obligatoires absents du .env : " + " ; ".join(manque))
    Gestionnaire.masquer = {n.strip() for n in reglage("ACHATS_MASQUES_POUR", "").split(",") if n.strip()}
    Gestionnaire.admins = {n.strip() for n in reglage("ADMINS", "").split(",") if n.strip()}
    Gestionnaire.index = Index(donnees)
    Gestionnaire.journal = synchro.Journal(donnees)
    Gestionnaire.logos = logos_mod.Logos(donnees, synchro.actives)
    Gestionnaire.logos.demarrer()
    Gestionnaire.alertes = alertes_mod.Alertes(donnees, Gestionnaire.index, Gestionnaire.depot,
                                               lambda: [s["id"] for s in synchro.actives()])
    heures = float(reglage("RELEVE_HEURES", "24"))
    heure = synchro.heure_programmee(heures)
    Gestionnaire.alertes.demarrer(   # relecture horaire de la sélection, puis alertes
        (lambda: synchro.relire_selection(Gestionnaire.index, Gestionnaire.depot.selection())) if heures > 0 else None)
    Gestionnaire.surveillance = surveillance.Surveillance(donnees, Gestionnaire.journal, Gestionnaire.index)
    Gestionnaire.surveillance.demarrer()
    if heures > 0:   # vérification continue des photos (photos.py)
        Gestionnaire.index.photos.demarrer(photos_a_verifier)
    synchro.programmer(Gestionnaire.index, Gestionnaire.journal, heures, heure)
    if heures > 0:
        synchro.demarrer_rotation(Gestionnaire.index, lambda: [s.get("url") for s in Gestionnaire.depot.selection()])
    if heures > 0:   # relève quotidienne des liens de tests indépendants
        tests_auto.demarrer(Gestionnaire.index.tests)
    if heures > 0:   # relevé hebdomadaire des boutiques (boutiques.py)
        boutiques_mod.demarrer(donnees)
    Gestionnaire.occasion = Occasion(donnees)
    if heures > 0:   # occasion des sets LEGO officiel : boutiques d'occasion, BrickLink avec ses clés (sources/occasion.py)
        Gestionnaire.occasion.demarrer(numeros_lego)
    def arret(*_):   # arrêt du conteneur : l'historique des prix en attente d'écriture est écrit
        Gestionnaire.index.historique.vider()
        raise SystemExit(0)
    signal.signal(signal.SIGTERM, arret)
    port = int(reglage("PORT", "8080"))
    srv = ThreadingHTTPServer(("0.0.0.0", port), Gestionnaire)
    log.info("Carnet de briques %s sur le port %s, données dans %s", VERSION, port, donnees)
    srv.serve_forever()


if __name__ == "__main__":
    main()

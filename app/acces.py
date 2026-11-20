"""Comptes et authentification HTTP Basic.

Les comptes viennent de la variable UTILISATEURS :
    nom=empreinte;nom2=empreinte2
L'empreinte se calcule avec `python -m app.motdepasse` (PBKDF2-SHA256) ; elle ne contient
ni « $ » ni « : » et se colle telle quelle dans un fichier .env.
Après 8 échecs sur un compte en 15 minutes, ce compte est bloqué 15 minutes.
Le navigateur renvoie le mot de passe à chaque requête : une connexion réussie est retenue 10 minutes en
mémoire vive, sous forme d'empreinte HMAC à clé aléatoire (jamais le mot de passe), pour ne pas refaire le
calcul PBKDF2 à chaque requête. Un échec n'est jamais retenu ; la mémoire disparaît au redémarrage.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os

from .reglage import reglage
import secrets
import threading
import time

ITERATIONS = 600000  # recommandation OWASP pour PBKDF2-SHA256 (Password Storage Cheat Sheet, 2026)
MEMOIRE_S = 10 * 60   # durée de la mémoire des connexions réussies
FENETRE = 15 * 60
ECHECS_MAX = 8


def empreinte(mot_de_passe: str, sel: str | None = None, iterations: int = ITERATIONS) -> str:
    sel = sel or secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac("sha256", mot_de_passe.encode(), sel.encode(), iterations)
    return f"pbkdf2_sha256.{iterations}.{sel}.{h.hex()}"


def verifier(mot_de_passe: str, attendu: str) -> bool:
    try:
        algo, it, sel, h = attendu.split(".")
    except ValueError:
        return False
    if algo != "pbkdf2_sha256" or not it.isdigit():
        return False
    calc = hashlib.pbkdf2_hmac("sha256", mot_de_passe.encode(), sel.encode(), int(it))
    return hmac.compare_digest(calc.hex(), h)


def lire_comptes(valeur: str) -> dict[str, str]:
    comptes = {}
    for morceau in (valeur or "").split(";"):
        morceau = morceau.strip()
        if not morceau:
            continue
        nom, _, h = morceau.partition("=")
        if nom and h.startswith("pbkdf2_sha256."):
            comptes[nom.strip()] = h.strip()
    return comptes


class Gardien:
    def __init__(self, comptes: dict[str, str]):
        self.comptes = comptes
        self.echecs: dict[str, list[float]] = {}
        self.verrou = threading.Lock()
        self._leurre = empreinte(secrets.token_hex(8))
        self._cle = secrets.token_bytes(32)
        self._reussites: dict[bytes, tuple[str, float]] = {}

    def bloque(self, nom: str) -> bool:
        now = time.time()
        with self.verrou:
            l = [t for t in self.echecs.get(nom, []) if now - t < FENETRE]
            self.echecs[nom] = l
            return len(l) >= ECHECS_MAX

    def authentifier(self, entete: str | None) -> str | None:
        if not entete or not entete.startswith("Basic "):
            return None
        try:
            nom, _, mdp = base64.b64decode(entete[6:]).decode("utf-8").partition(":")
        except (ValueError, UnicodeDecodeError):
            return None
        if self.bloque(nom):
            return None
        marque = hmac.new(self._cle, entete.encode(), hashlib.sha256).digest()
        now = time.time()
        with self.verrou:
            connu = self._reussites.get(marque)
            if connu and connu[0] == nom and connu[1] > now:
                return nom
        attendu = self.comptes.get(nom)
        ok = verifier(mdp, attendu if attendu else self._leurre) and attendu is not None
        if ok:
            with self.verrou:
                self._reussites = {k: v for k, v in self._reussites.items() if v[1] > now}
                self._reussites[marque] = (nom, now + MEMOIRE_S)
            return nom
        with self.verrou:
            self.echecs.setdefault(nom, []).append(time.time())
        return None


def depuis_env() -> Gardien | None:
    """Rend None si l'authentification est volontairement désactivée."""
    if reglage("AUTH_DESACTIVEE", "0").lower() in ("1", "oui", "true"):
        return None
    comptes = lire_comptes(reglage("UTILISATEURS", ""))
    if not comptes:
        raise SystemExit("UTILISATEURS est vide : définir au moins un compte (python -m app.motdepasse), "
                         "ou AUTH_DESACTIVEE=1 si l'accès est déjà protégé en amont.")
    return Gardien(comptes)

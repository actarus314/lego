"""Comptes et authentification HTTP Basic.

Les comptes viennent de la variable UTILISATEURS :
    nom=empreinte;nom2=empreinte2
L'empreinte se calcule avec `python -m app.motdepasse` (PBKDF2-SHA256) ; elle ne contient
ni « $ » ni « : » et se colle telle quelle dans un fichier .env.
Après 8 échecs sur un compte en 15 minutes, ce compte est bloqué 15 minutes.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import threading
import time

ITERATIONS = 310000
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
        attendu = self.comptes.get(nom)
        ok = verifier(mdp, attendu if attendu else self._leurre) and attendu is not None
        if ok:
            return nom
        with self.verrou:
            self.echecs.setdefault(nom, []).append(time.time())
        return None


def depuis_env() -> Gardien | None:
    """Rend None si l'authentification est volontairement désactivée."""
    if os.environ.get("AUTH_DESACTIVEE", "").lower() in ("1", "oui", "true"):
        return None
    comptes = lire_comptes(os.environ.get("UTILISATEURS", ""))
    if not comptes:
        raise SystemExit("UTILISATEURS est vide : définir au moins un compte (python -m app.motdepasse), "
                         "ou AUTH_DESACTIVEE=1 si l'accès est déjà protégé en amont.")
    return Gardien(comptes)

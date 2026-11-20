"""Alertes sur la sélection : baisse de prix, rupture, retour en vente, retrait annoncé, offre moins
chère ailleurs. Chaque heure, l'état du jour de chaque produit suivi (retrouvé dans l'index par
l'adresse de l'offre choisie) est comparé au dernier état connu ; les changements partent en un seul
message par compte, par les canaux de la variable ALERTES. Un produit « Acheté » ne déclenche rien.

ALERTES : comptes séparés par « ; », canaux par « , » :
    julie=courriel:julie@exemple.fr;romain=courriel:romain@exemple.fr
Un groupe Signal s'écrit « signal:group.… » ; une même destination citée par deux comptes ne reçoit
le message qu'une fois.
Envoi des courriels : variables SMTP_HOTE, SMTP_PORT, SMTP_SECURITE (starttls, ssl ou aucune),
SMTP_UTILISATEUR, SMTP_MOT_DE_PASSE, SMTP_EXPEDITEUR. Signal : canal « signal:+33… », envoyé par
signal-cli-rest-api (SIGNAL_URL, par exemple http://signal:8080) depuis le numéro SIGNAL_NUMERO.
"""
from __future__ import annotations

import http.client
import json
import logging
import os
import re
import smtplib
import ssl
import threading
import time
from email.message import EmailMessage
from pathlib import Path
from urllib.parse import urlsplit

from .donnees import _ecrire, _lire
from .reglage import reglage

log = logging.getLogger("alertes")
SEUIL_EUROS, SEUIL_PART = 2.0, 0.02  # une baisse compte à partir de 2 € et de 2 %
PERIODE_S = 3600


def norm(url: str | None) -> str:
    """Même normalisation que la page : hôte sans www, chemin sans barre finale, en minuscules."""
    p = urlsplit(url or "")
    if not p.hostname:
        return (url or "").strip().lower()
    return (re.sub(r"^www\.", "", p.hostname) + p.path.rstrip("/")).lower()


def destinataires() -> dict[str, list[tuple[str, str]]]:
    """{compte: [(canal, adresse), …]} d'après la variable ALERTES."""
    out: dict[str, list[tuple[str, str]]] = {}
    for bloc in reglage("ALERTES", "").split(";"):
        compte, _, canaux = bloc.partition("=")
        for c in canaux.split(","):
            canal, _, adresse = c.strip().partition(":")
            if compte.strip() and canal and adresse:
                out.setdefault(compte.strip(), []).append((canal.strip(), adresse.strip()))
    return out


def eur(x: float) -> str:
    return f"{x:.2f} €"


def total(o: dict) -> float:
    return o["prix"] + (o.get("port") or 0)


def etat_du_jour(item: dict, par_url: dict) -> dict | None:
    """État du jour d'un produit de la sélection, ou None s'il n'est pas dans l'index."""
    trouve = par_url.get(norm(item.get("url")))
    if not trouve:
        return None
    s, o = trouve
    m = s["offres"][0]
    mieux = m if m is not o and total(m) < total(o) - max(SEUIL_EUROS, SEUIL_PART * total(o)) else None
    return {"total": round(total(o), 2), "dispo": o["dispo"], "boutique": o["boutique"], "retrait": s.get("retrait"),
            "mieux": [mieux["boutique"], round(total(mieux), 2), mieux["url"]] if mieux else None}


def changements(nom: str, avant: dict, apres: dict) -> list[str]:
    lignes = []
    b, a = avant["total"], apres["total"]
    if a <= b - max(SEUIL_EUROS, SEUIL_PART * b):
        lignes.append(f"{nom} : {eur(a)} chez {apres['boutique']}, au lieu de {eur(b)}")
    if avant["dispo"] == "vente" and apres["dispo"] != "vente":
        lignes.append(f"{nom} : {'épuisé' if apres['dispo'] == 'epuise' else 'en précommande'} chez {apres['boutique']}")
    if avant["dispo"] != "vente" and apres["dispo"] == "vente":
        lignes.append(f"{nom} : de nouveau en vente chez {apres['boutique']}, {eur(a)}")
    if apres["retrait"] and not avant.get("retrait"):
        lignes.append(f"{nom} : {apres['retrait'][0].lower() + apres['retrait'][1:]}")
    if apres["mieux"] and (not avant.get("mieux") or apres["mieux"][1] < avant["mieux"][1] - SEUIL_EUROS):
        lignes.append(f"{nom} : {eur(apres['mieux'][1])} chez {apres['mieux'][0]} ({apres['mieux'][2]})")
    return lignes


# ----- canaux -----
def envoyer_courriel(adresse: str, sujet: str, texte: str) -> None:
    hote = reglage("SMTP_HOTE")
    if not hote:
        raise RuntimeError("SMTP_HOTE absent")
    securite = reglage("SMTP_SECURITE", "ssl")
    port = int(reglage("SMTP_PORT", "465" if securite == "ssl" else "587"))
    msg = EmailMessage()
    msg["From"] = reglage("SMTP_EXPEDITEUR") or reglage("SMTP_UTILISATEUR", "")
    msg["To"], msg["Subject"] = adresse, sujet
    msg.set_content(texte)
    ctx = ssl.create_default_context()
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    cls = smtplib.SMTP_SSL if securite == "ssl" else smtplib.SMTP
    kw = {"context": ctx} if securite == "ssl" else {}
    with cls(hote, port, timeout=20, **kw) as smtp:
        if securite == "starttls":
            smtp.starttls(context=ctx)
        if reglage("SMTP_UTILISATEUR"):
            smtp.login(reglage("SMTP_UTILISATEUR"), reglage("SMTP_MOT_DE_PASSE", ""))
        smtp.send_message(msg)


def envoyer_signal(numero: str, sujet: str, texte: str) -> None:
    """Message Signal par signal-cli-rest-api (conteneur voisin, SIGNAL_URL) depuis le numéro SIGNAL_NUMERO."""
    base, expediteur = reglage("SIGNAL_URL", "http://signal:8080").rstrip("/"), reglage("SIGNAL_NUMERO", "")
    if not base or not expediteur:
        raise RuntimeError("SIGNAL_NUMERO absent")
    p = urlsplit(base)
    if p.scheme not in ("http", "https") or not p.hostname:
        raise RuntimeError("SIGNAL_URL invalide")
    conn = (http.client.HTTPSConnection if p.scheme == "https" else http.client.HTTPConnection)(
        p.hostname, p.port or (443 if p.scheme == "https" else 80), timeout=30)
    corps = json.dumps({"message": f"{sujet}\n\n{texte}", "number": expediteur, "recipients": [numero]})
    try:
        conn.request("POST", (p.path or "") + "/v2/send", body=corps, headers={"Content-Type": "application/json"})
        r = conn.getresponse()
        detail = r.read(2000).decode("utf-8", "replace")
        if r.status >= 300:
            raise RuntimeError(f"signal-cli-rest-api a répondu {r.status} : {detail[:200]}")
    finally:
        conn.close()


CANAUX = {"courriel": envoyer_courriel, "signal": envoyer_signal}


REQUIS = {"courriel": ["SMTP_HOTE"], "signal": ["SIGNAL_NUMERO"]}


def reglages_manquants() -> list[str]:
    """Réglages obligatoires des canaux cités dans ALERTES et absents : le service refuse alors de démarrer."""
    manque = []
    for canal in sorted({c for d in destinataires().values() for c, _ in d}):
        if canal not in CANAUX:
            manque.append(f"canal inconnu dans ALERTES : {canal}")
        manque += [f"{v} (canal {canal})" for v in REQUIS.get(canal, []) if not reglage(v)]
    from .surveillance import canaux as canaux_service, mal_ecrits
    manque += [f"ALERTES_SERVICE : « {c} » sans « canal:adresse »" for c in mal_ecrits()]
    for canal in sorted({c for c, _ in canaux_service()} - {c for d in destinataires().values() for c, _ in d}):
        if canal not in CANAUX:
            manque.append(f"canal inconnu dans ALERTES_SERVICE : {canal}")
        manque += [f"{v} (canal {canal})" for v in REQUIS.get(canal, []) if not reglage(v)]
    utilises = {c for d in destinataires().values() for c, _ in d} | {c for c, _ in canaux_service()}
    if "courriel" in utilises and not (
            reglage("SMTP_EXPEDITEUR") or reglage("SMTP_UTILISATEUR")):
        manque.append("SMTP_EXPEDITEUR ou SMTP_UTILISATEUR (canal courriel)")
    return manque


def envoyer(compte: str, sujet: str, texte: str, deja: set | None = None) -> list[str]:
    """Envoie à tous les canaux du compte ; rend la liste des erreurs (vide si tout est parti).
    `deja` : destinations déjà servies par ce même message (groupe Signal commun à deux comptes)."""
    erreurs = []
    for canal, adresse in destinataires().get(compte, []):
        if deja is not None:
            if (canal, adresse) in deja:
                continue
            deja.add((canal, adresse))
        f = CANAUX.get(canal)
        if not f:
            erreurs.append(f"canal inconnu : {canal}")
            continue
        try:
            f(adresse, sujet, texte)
        except Exception as e:  # un canal en panne n'empêche pas les autres
            log.warning("alerte %s par %s en échec : %s", compte, canal, e)
            # message propre au service (RuntimeError) gardé, type seul pour le reste (texte d'un serveur tiers)
            erreurs.append(f"{canal} : {str(e)[:160] if type(e) is RuntimeError else type(e).__name__}")
    return erreurs


class Alertes:
    def __init__(self, dossier: Path, index, depot, actives):
        self.fichier = Path(dossier) / "alertes.json"
        self.index, self.depot, self.actives = index, depot, actives

    def verifier(self, envoi=envoyer) -> dict[str, list[str]]:
        """Compare l'état du jour au dernier état connu ; envoie et rend {compte: lignes}."""
        sets = self.index.sets(self.actives())
        par_url = {norm(o["url"]): (s, o) for s in sets for o in s["offres"]}
        connu = _lire(self.fichier, {})
        lignes: list[str] = []
        nouveau = {}
        for item in self.depot.selection():
            if item.get("statut") == "achete":
                continue
            e = etat_du_jour(item, par_url)
            if not e:
                continue
            nouveau[item["id"]] = e
            if item["id"] in connu:  # premier passage : état de référence, sans alerte
                lignes += changements(item.get("nom") or "Produit", connu[item["id"]], e)
        _ecrire(self.fichier, nouveau)
        envoyes: dict[str, list[str]] = {}
        if lignes:
            adresse = reglage("ADRESSE_PUBLIQUE", "").rstrip("/")
            texte = "\n".join("• " + x for x in lignes) + (f"\n\nSélection : {adresse}/#selection" if adresse else "")
            sujet = f"Carnet de briques : {len(lignes)} changement{'s' if len(lignes) > 1 else ''} dans la sélection"
            deja: set = set()
            for compte in destinataires():
                envoi(compte, sujet, texte, deja)
                envoyes[compte] = lignes
        return envoyes

    def demarrer(self) -> None:
        if not destinataires():
            return

        def boucle():
            time.sleep(300)
            while True:
                try:
                    self.verifier()
                except Exception:
                    log.exception("vérification des alertes en échec")
                time.sleep(PERIODE_S)
        threading.Thread(target=boucle, name="alertes", daemon=True).start()

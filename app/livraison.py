"""Frais de port relus sur les pages de livraison des boutiques et des revendeurs, chaque semaine.

Les conditions de livraison sont écrites dans `data/sources.json` (boutiques) et `data/livraison.json`
(revendeurs LEGO officiel), d'après leurs pages officielles. Ce module relit chaque page déclarée
(`livraison.page` d'une source, `source` d'un revendeur) et vérifie que les montants écrits (port,
seuil de port offert) y figurent toujours ; un montant disparu est signalé à l'administrateur par la
surveillance. Quand la page donne une ligne par pays (« France 4,95 € » chez KBS, motif
`livraison.motif_pays`), le port lu remplace le port écrit, sans intervention.

Une page illisible (refus du site, page rendue par script) n'est pas une alerte : la valeur écrite
reste en vigueur, et l'état « illisible » se lit dans `livraison_lue.json`.
"""
from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path

from . import lien, normalise as n
from .donnees import _ecrire, _lire

log = logging.getLogger("livraison")
RACINE = Path(__file__).resolve().parent.parent
PERIODE_J = 7
_MONTANT = re.compile(r"€\s*(\d{1,3}(?:[.,]\d{2})?)(?!\d)|(?<![\d.,])(\d{1,3}(?:[.,]\d{2})?)\s*(?:€|eur\b|euros?\b)", re.I)


def montants(texte: str) -> set[float]:
    return {float((a or b).replace(",", ".")) for a, b in _MONTANT.findall(texte or "")}


PORT_MAX = 25.0  # un port lu au-delà (ou au-delà du double du port écrit) est signalé, jamais appliqué


def port_du_pays(texte: str, motif: str) -> float | None:
    """Montant qui suit immédiatement le nom du pays (« France 4,95 € » : au plus cinq signes entre les deux)."""
    m = re.search(r"(?<!\w)" + motif + r"(?!\w)\W{0,5}(?:€\s*)?(\d{1,3}(?:[.,]\d{2}))\s*(?:€|eur\b)?", texte or "", re.I)
    return float(m.group(1).replace(",", ".")) if m else None


def pages() -> list[dict]:
    """Pages à relire : {nom, url, attendus, motif_pays, source_id}."""
    out = []
    for s in json.loads((RACINE / "data" / "sources.json").read_text("utf-8"))["sources"]:
        liv = s.get("livraison") or {}
        if liv.get("page"):
            att = [] if liv.get("estime") else [v for v in (liv.get("port"), liv.get("gratuit_des")) if v]
            out.append({"nom": s["nom"], "url": liv["page"], "attendus": att, "motif_pays": liv.get("motif_pays"),
                        "source_id": s["id"], "port_ecrit": liv.get("port")})
    rev = json.loads((RACINE / "data" / "livraison.json").read_text("utf-8"))["revendeurs"]
    for nom, r in rev.items():
        if r.get("source"):
            att = [] if r.get("estime") else [v for v in (r.get("port"), r.get("gratuit_des")) if v]
            out.append({"nom": nom, "url": r["source"], "attendus": att, "motif_pays": None, "source_id": None,
                        "port_ecrit": r.get("port")})
    return out


def relire(dossier: Path, pause: float = 2.0) -> dict:
    """Relit toutes les pages et écrit `livraison_lue.json` : {nom: {le, etat, manquants, port_lu}}."""
    resultat, avant = {}, lue(dossier)
    for p in pages():
        r = {"le": time.strftime("%Y-%m-%dT%H:%M:%S"), "url": p["url"], "source_id": p["source_id"]}
        try:
            texte = n.texte(lien.recuperer(p["url"]).corps.decode("utf-8", "replace"))
        except Exception as e:  # refus, réseau, réponse tronquée : la valeur écrite reste en vigueur
            if getattr(e, "pause", False) and p["nom"] in avant:   # site en pause après un 429 : relevé précédent gardé
                resultat[p["nom"]] = avant[p["nom"]]
                continue
            r.update(etat="illisible", raison=getattr(e, "public", type(e).__name__))
            resultat[p["nom"]] = r
            time.sleep(pause)
            continue
        vus = montants(texte)
        manquants = [v for v in p["attendus"] if v not in vus]
        if p["motif_pays"]:
            lu = port_du_pays(texte, p["motif_pays"])
            ecrit = p["port_ecrit"]
            if lu is not None and lu <= PORT_MAX and (not ecrit or lu <= 2 * ecrit):
                r["port_lu"] = lu
                manquants = [v for v in manquants if v != ecrit]
            elif lu is not None:
                r["port_douteux"] = lu  # signalé par ecarts(), non appliqué
        r.update(etat="ecart" if manquants else "ok", manquants=manquants)
        resultat[p["nom"]] = r
        time.sleep(pause)
    _ecrire(Path(dossier) / "livraison_lue.json", resultat)
    return resultat


def lue(dossier: Path) -> dict:
    return _lire(Path(dossier) / "livraison_lue.json", {})


def ports_lus(dossier: Path) -> dict[str, float]:
    """{identifiant de source: port lu sur la page} pour les boutiques à ligne par pays."""
    return {r["source_id"]: r["port_lu"] for r in lue(dossier).values()
            if r.get("source_id") and isinstance(r.get("port_lu"), (int, float))}


def ecarts(dossier: Path) -> dict[str, str]:
    """{clé: message} pour la surveillance : montants écrits introuvables sur leur page."""
    out = {}
    for nom, r in lue(dossier).items():
        if r.get("etat") == "ecart":
            m = ", ".join(f"{v:.2f} €" for v in r.get("manquants", []))
            out[f"livraison:{nom}"] = (f"Livraison de {nom} : {m} introuvable sur sa page ; conditions à revoir "
                                       f"(data/livraison.json ou data/sources.json).")
        if r.get("port_douteux") is not None:
            out[f"livraison-douteux:{nom}"] = (f"Livraison de {nom} : {r['port_douteux']:.2f} € lu après « France », "
                                               f"montant invraisemblable, non appliqué ; page à revoir.")
        port, ecrit = r.get("port_lu"), None
        if r.get("source_id") and port is not None:
            conf = next((s for s in json.loads((RACINE / "data" / "sources.json").read_text("utf-8"))["sources"]
                         if s["id"] == r["source_id"]), {})
            ecrit = (conf.get("livraison") or {}).get("port")
            if ecrit is not None and abs(port - ecrit) > 0.004:
                out[f"livraison-port:{nom}"] = f"Livraison de {nom} : port vers la France passé de {ecrit:.2f} € à {port:.2f} €, appliqué."
    return out


def a_relire(dossier: Path, maintenant: float) -> bool:
    dates = [r.get("le") for r in lue(dossier).values() if r.get("le")]
    if not dates:
        return True
    dernier = time.mktime(time.strptime(max(dates), "%Y-%m-%dT%H:%M:%S"))
    return maintenant - dernier > PERIODE_J * 86400

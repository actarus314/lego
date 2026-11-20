#!/usr/bin/env python3
"""Outil de mainteneur : récupère l'historique complet des sources de tests déclarées dans
`data/tests_sources.json` et écrit `data/tests_amorce.json` (liste de {source, titre, url, date si
connue, langue}). Hors du service : le service, lui, ne lit que les flux récents.

- Chaînes YouTube : liste de la playlist des envois de la chaîne par `yt-dlp --flat-playlist`
  (titres et identifiants seulement, sans clé ni compte) ; `pip install yt-dlp` requis. Cette liste
  ne donne pas les dates ; celles des 15 dernières vidéos viennent du flux Atom, celles déjà connues
  d'un amorçage précédent sont gardées.
- Blogs WordPress : pages successives du flux (`/feed/?paged=N`) jusqu'à la dernière page.
- Seuls les titres où `tests_auto.numeros_titre` repère un numéro de set (et, pour un blog d'actualités,
  qui annoncent un test : `tests_auto.retenu`) sont gardés (les autres ne
  peuvent être rattachés à aucun set et alourdiraient le dépôt) ; `--tout` garde tout.
- Une source en échec garde ses liens de l'amorçage précédent.

Conditions d'utilisation de YouTube : l'extraction par yt-dlp relève de ses conditions de service
(accès automatisé hors API) ; usage de mainteneur occasionnel, titres et adresses publics seulement,
rien n'est téléchargé. Point non tranché, à décider par le mainteneur.

Usage : python tools/amorcer_tests.py [--pages-max 150] [--pause 1.5] [--source ID ...]
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE))

from app import lien, tests_auto  # noqa: E402

AMORCE = RACINE / "data" / "tests_amorce.json"


def historique_youtube(src: dict) -> list[dict]:
    exe = shutil.which("yt-dlp")
    if not exe:
        raise SystemExit("yt-dlp introuvable : pip install yt-dlp")
    playlist = "https://www.youtube.com/playlist?list=UU" + src["chaine"][2:]
    r = subprocess.run([exe, "--flat-playlist", "--print", "%(id)s|%(title)s", playlist],
                       capture_output=True, text=True, encoding="utf-8", timeout=900)
    liens = []
    for ligne in r.stdout.splitlines():
        vid, _, titre = ligne.partition("|")
        titre = tests_auto._nettoyer(titre)[:tests_auto.TITRE_MAX]
        if len(vid) == 11 and titre and titre != "[Private video]" and titre != "[Deleted video]":
            liens.append({"source": src["id"], "titre": titre, "url": f"https://www.youtube.com/watch?v={vid}",
                          "langue": src.get("langue")})
    if not liens:
        raise RuntimeError(f"aucune vidéo lue (code {r.returncode}) : {r.stderr.strip()[-300:]}")
    return liens


def historique_blog(src: dict, pages_max: int, pause: float) -> list[dict]:
    liens, vus = [], set()
    for page in range(1, pages_max + 1):
        try:
            r = lien.recuperer(f"{src['flux']}?paged={page}", accept=tests_auto.FLUX_ACCEPT)
            lot = tests_auto.lire_flux(r.corps, src)
        except lien.LienRefuse as e:
            if getattr(e, "statut", None) == 404:   # au-delà de la dernière page
                break
            raise
        except ET.ParseError:
            break
        neufs = [x for x in lot if x["url"] not in vus]
        if not neufs:
            break
        vus.update(x["url"] for x in neufs)
        liens += neufs
        time.sleep(pause)
    return liens


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--pages-max", type=int, default=150, help="pages de flux au plus par blog")
    ap.add_argument("--pause", type=float, default=1.5, help="secondes entre deux requêtes")
    ap.add_argument("--tout", action="store_true", help="garder aussi les titres sans numéro de set")
    ap.add_argument("--source", action="append", help="limiter à ces identifiants")
    a = ap.parse_args()
    ancien = json.loads(AMORCE.read_text("utf-8")) if AMORCE.exists() else []
    dates = {x["url"]: x["date"] for x in ancien if x.get("date")}
    resultat = []
    for src in tests_auto.sources_tests():
        if a.source and src["id"] not in a.source:
            resultat += [x for x in ancien if x["source"] == src["id"]]
            continue
        try:
            liens = historique_youtube(src) if src["type"] == "youtube" else historique_blog(src, a.pages_max, a.pause)
            if src["type"] == "youtube":   # dates des dernières vidéos, par le flux Atom
                flux = tests_auto.lire_flux(lien.recuperer(src["flux"], accept=tests_auto.FLUX_ACCEPT).corps, src)
                dates.update({x["url"]: x["date"] for x in flux if x.get("date")})
        except (SystemExit, KeyboardInterrupt):
            raise
        except Exception as e:  # une source en échec garde l'amorçage précédent
            print(f"{src['id']} : échec ({e}), amorçage précédent gardé", file=sys.stderr)
            resultat += [x for x in ancien if x["source"] == src["id"]]
            continue
        lus = len(liens)
        if not a.tout:
            liens = [x for x in liens if tests_auto.retenu(x["titre"], src)
                     and tests_auto.numeros_titre(x["titre"], src.get("marque_implicite"))]
        for x in liens:
            if x["url"] in dates:
                x["date"] = dates[x["url"]]
        print(f"{src['id']} : {lus} liens lus, {len(liens)} avec un numéro de set", file=sys.stderr)
        resultat += liens
        time.sleep(a.pause)
    AMORCE.write_text(json.dumps(resultat, ensure_ascii=False, indent=1) + "\n", "utf-8")
    print(f"{len(resultat)} liens écrits dans {AMORCE}", file=sys.stderr)


if __name__ == "__main__":
    main()

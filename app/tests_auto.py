"""Liens de tests indépendants (vidéos, articles) rattachés aux sets par marque et numéro, par script.

Aucun verdict n'est synthétisé : seulement des liens (source, titre, adresse, date, langue).

- Sources déclarées dans `data/tests_sources.json` : flux Atom de chaînes YouTube et flux RSS de
  blogs WordPress. Chaque jour, le service relit ces flux (par `lien.recuperer`) et cumule les
  liens vus dans `tests_vus.json` (dossier de données ; sans doublon, borné).
- L'historique des chaînes et des blogs vient de `data/tests_amorce.json`, produit par l'outil de
  mainteneur `tools/amorcer_tests.py`.
- Rattachement : un lien va à un set si son titre contient le numéro du set (aux préfixes et
  suffixes de boutique près) ET sa marque. Dans un titre qui nomme plusieurs marques, chaque numéro
  est attribué à la marque nommée juste avant lui. LEGO officiel : « LEGO » dans le titre ; un blog
  déclaré consacré à LEGO n'a pas besoin de le nommer, mais le numéro doit alors faire 5 chiffres au
  moins. Les nombres de 4 chiffres qui ressemblent à une année (1900 à 2099) sont écartés.
- Un index par numéro est précalculé : `pour` est un simple accès de dictionnaire, car l'index
  complet des sets le demande pour chaque set à chaque reconstruction.
"""
from __future__ import annotations

import html
import json
import logging
import re
import threading
import time
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urlsplit

from . import lien, normalise as n
from .donnees import _ecrire, _lire

log = logging.getLogger("tests_auto")
RACINE = Path(__file__).resolve().parent.parent
VUS_MAX = 2000          # liens gardés dans tests_vus.json (les plus récents)
TITRE_MAX = 200
PAUSE_DEMARRAGE = 150   # secondes avant la première relève
PERIODE_H = 24
LEGO = "LEGO officiel"
FLUX_ACCEPT = "application/atom+xml,application/rss+xml,application/xml;q=0.9,text/xml;q=0.8,*/*;q=0.5"

# Écritures de marques dans les titres, en plus des alias de normalise.MARQUES.
ALIAS_TITRES = {"reobricks": "Reobrix", "xmork": "Mork", "blue brixx": "BlueBrixx", "mould-king": "Mould King",
                "doublee": "CaDA"}
_ALIAS = {**n.MARQUES, **ALIAS_TITRES}
_MARQUES_RE = re.compile(r"(?<!\w)(" + "|".join(re.escape(a) for a in sorted(_ALIAS, key=len, reverse=True))
                         + r")s?(?!\w)")
# Numéro : préfixe de 0 à 3 lettres, 4 à 6 chiffres, suffixe de 0 ou 1 lettre ; pas collé à un autre
# nombre (7.300, 1,5, 12/2026), ni à un prix.
_NUMERO = re.compile(r"(?<![\w.,/€$£])([A-Za-z]{0,3})(\d{4,6})([A-Za-z]?)(?!\w)")
# Un nombre suivi d'une unité n'est pas un numéro de set (« 7300 Teile », « 1500 €», « 3600 pcs »).
_UNITE = re.compile(r"\s*(?:teile[n]?|pcs|pieces?|pi[eè]ces|st[uü]ck|steine[n]?|parts|bricks|euro|eur|€|cm|mm|kg|"
                    r"%|jahre|years|mal|x)\b", re.I)
# Blog d'actualités et d'offres (`filtre_tests` dans tests_sources.json) : seuls les articles dont le titre
# annonce un test, un avis ou une comparaison sont gardés (les annonces, fuites et offres ne sont pas des tests).
_MOTS_TEST = re.compile(r"\b(review|reviews|im test|test|getestet|testbericht|rezension|vergleich|eindruck|fazit|"
                        r"im check|ausprobiert|baubericht)\b", re.I)
_PREFIXES_BOUTIQUE = re.compile(r"^(US|EU|DE|FR|UK|MK|REO|RB|PA|CB|XB|WG)(?=\d)")


def _nettoyer(titre: str) -> str:
    t = html.unescape(titre or "").replace("®", "").replace("™", "").replace("©", "")
    return re.sub(r"\s+", " ", t).strip()


def retenu(titre: str, src: dict) -> bool:
    """Le titre convient-il à la source ? Toujours pour une chaîne de tests ; pour un blog d'actualités
    (`filtre_tests`), seulement s'il annonce un test."""
    return not src.get("filtre_tests") or bool(_MOTS_TEST.search(titre))


def _marque_alias(texte: str) -> str | None:
    s = n.sans_accents(texte)
    return _ALIAS.get(s) or _ALIAS.get(s[:-1])


def _cles(prefixe: str, chiffres: str, suffixe: str, marque: str) -> set[str]:
    """Clés d'index d'un numéro : forme de regroupement (numero_base) et chiffres seuls."""
    complet = _PREFIXES_BOUTIQUE.sub("", (prefixe + chiffres + suffixe).upper())
    return {n.numero_base(marque, complet) or complet, chiffres}


def numeros_titre(titre: str, marque_implicite: str | None = None) -> list[tuple[set[str], str]]:
    """Numéros de set d'un titre : liste de (clés d'index, marque attribuée). La marque attribuée est
    la seule nommée, sinon la dernière nommée avant le numéro (à défaut la première après), sinon la
    marque implicite de la source. Un numéro sans marque attribuée est écarté."""
    t = _nettoyer(titre)
    marques = [(m.start(), _marque_alias(m.group(1))) for m in _MARQUES_RE.finditer(n.sans_accents(t))]
    marques = [(p, c) for p, c in marques if c]
    distinctes = {c for _, c in marques}
    out = []
    for m in _NUMERO.finditer(t):
        prefixe, chiffres, suffixe = m.groups()
        if _UNITE.match(t, m.end()):
            continue
        if len(chiffres) == 4 and not prefixe and not suffixe and 1900 <= int(chiffres) <= 2099:
            continue
        if len(distinctes) == 1:
            marque = next(iter(distinctes))
        elif distinctes:
            avant = [c for p, c in marques if p < m.start()]
            marque = avant[-1] if avant else next(c for p, c in marques if p >= m.start())
        else:
            marque = marque_implicite
        if not marque:
            continue
        if marque == LEGO and len(chiffres) < (4 if distinctes else 5):
            continue
        out.append((_cles(prefixe, chiffres, suffixe, marque), marque))
    return out


# ----- lecture des flux -----
def _local(balise: str) -> str:
    return balise.rsplit("}", 1)[-1]


def _texte(el: ET.Element, nom: str) -> str:
    for e in el:
        if _local(e.tag) == nom and e.text:
            return e.text.strip()
    return ""


def _http(url: str) -> bool:
    p = urlsplit(url or "")
    return p.scheme in ("http", "https") and bool(p.hostname)


def _date_iso(brut: str) -> str | None:
    brut = (brut or "").strip()
    if re.match(r"\d{4}-\d{2}-\d{2}", brut):
        return brut[:10]
    try:
        return parsedate_to_datetime(brut).strftime("%Y-%m-%d")
    except (TypeError, ValueError):
        return None


def lire_flux(corps: bytes, src: dict) -> list[dict]:
    """Liens d'un flux Atom (YouTube) ou RSS (WordPress) : {source, titre, url, date, langue}.
    Lève ET.ParseError si le flux est illisible."""
    racine = ET.fromstring(corps)
    out = []
    if _local(racine.tag) == "feed":
        entrees = [e for e in racine if _local(e.tag) == "entry"]
        for e in entrees:
            lien_el = next((x for x in e if _local(x.tag) == "link" and x.get("rel", "alternate") == "alternate"), None)
            url = lien_el.get("href", "") if lien_el is not None else ""
            out.append((_texte(e, "title"), url, _texte(e, "published") or _texte(e, "updated")))
    else:
        for e in racine.iter():
            if _local(e.tag) == "item":
                out.append((_texte(e, "title"), _texte(e, "link"), _texte(e, "pubDate") or _texte(e, "date")))
    liens = []
    for titre, url, date in out:
        titre = _nettoyer(titre)[:TITRE_MAX]
        if not titre or not _http(url) or not retenu(titre, src):
            continue
        item = {"source": src["id"], "titre": titre, "url": url.strip(), "langue": src.get("langue")}
        d = _date_iso(date)
        if d:
            item["date"] = d
        liens.append(item)
    return liens


def sources_tests() -> list[dict]:
    return json.loads((RACINE / "data" / "tests_sources.json").read_text("utf-8"))["sources"]


# ----- index et rattachement -----
class Tests:
    """Liens de tests : amorce (dépôt) + liens vus par la relève quotidienne (dossier de données)."""

    def __init__(self, dossier: Path, amorce: Path | None = None, sources: list[dict] | None = None):
        self.dossier = Path(dossier)
        self.f_vus = self.dossier / "tests_vus.json"
        self.f_amorce = amorce or RACINE / "data" / "tests_amorce.json"
        self._sources = sources
        self._verrou = threading.RLock()
        self._etat = None          # signature des fichiers à la dernière construction
        self._index: dict[str, list[dict]] = {}

    def sources(self) -> dict[str, dict]:
        if self._sources is None:
            self._sources = sources_tests()
        return {s["id"]: s for s in self._sources}

    def signature(self) -> tuple:
        """Change quand l'amorce ou les liens vus changent : sert à invalider le cache de l'index des sets."""
        def mt(p: Path) -> int:
            try:
                return p.stat().st_mtime_ns
            except OSError:
                return 0
        return (mt(self.f_amorce), mt(self.f_vus))

    def _liens(self) -> list[dict]:
        """Amorce puis liens vus, sans doublon d'adresse (la date connue l'emporte), sources inconnues écartées."""
        src = self.sources()
        try:
            vus = _lire(self.f_vus, {}).get("liens", []) if self.f_vus.exists() else []
        except ValueError:
            log.exception("tests_vus.json illisible : ignoré")
            vus = []
        try:
            amorce = _lire(self.f_amorce, []) if self.f_amorce.exists() else []
        except ValueError:
            log.exception("amorce des tests illisible : ignorée")
            amorce = []
        par_url: dict[str, dict] = {}
        for rang, x in enumerate([*amorce, *vus]):
            if not isinstance(x, dict) or x.get("source") not in src or not x.get("url") or not x.get("titre") \
                    or not _http(x["url"]):
                continue
            ex = par_url.get(x["url"])
            if ex is None:
                par_url[x["url"]] = {**x, "ordre": rang}
            elif x.get("date") and not ex.get("date"):
                ex["date"] = x["date"]
        return list(par_url.values())

    def _construire(self) -> None:
        src = self.sources()
        index: dict[str, list[dict]] = {}
        for x in self._liens():
            s = src[x["source"]]
            vu = set()
            for cles, marque in numeros_titre(x["titre"], s.get("marque_implicite")):
                for c in cles:
                    if (c, marque) not in vu:
                        vu.add((c, marque))
                        index.setdefault(c, []).append({"marque": marque, "x": x})
        for lst in index.values():
            lst.sort(key=lambda e: (e["x"].get("date") or "", -e["x"]["ordre"]), reverse=True)
        self._index = index

    def _a_jour(self) -> None:
        sig = self.signature()
        if sig != self._etat:
            with self._verrou:
                if sig != self._etat:
                    self._construire()
                    self._etat = sig

    def pour(self, marque: str, *numeros: str | None) -> list[dict]:
        """Liens de tests d'un set, du plus récent au plus ancien, tous.
        Chacun : {source, titre, url, langue, type} et `date` quand elle est connue."""
        self._a_jour()
        src = self.sources()
        trouves: dict[str, dict] = {}
        for num in numeros:
            base = n.numero_base(marque, (num or "").upper())
            if not base:
                continue
            noyau = re.sub(r"^[A-Z]+|[A-Z]$", "", base)
            if len(noyau) == 4 and 1900 <= int(noyau or 0) <= 2099 and noyau == base:
                continue
            if marque == LEGO and len(noyau) < 4:
                continue
            for cle in {base, noyau}:
                for e in self._index.get(cle, ()):
                    if e["marque"] == marque:
                        trouves.setdefault(e["x"]["url"], e["x"])
        tries = sorted(trouves.values(), key=lambda x: (x.get("date") or "", -x["ordre"]), reverse=True)
        out = []
        for x in tries:
            s = src[x["source"]]
            item = {"source": s["nom"], "titre": x["titre"], "url": x["url"], "langue": x.get("langue") or s.get("langue"),
                    "type": "video" if s["type"] == "youtube" else "article"}
            if x.get("date"):
                item["date"] = x["date"]
            out.append(item)
        return out

    # ----- relève quotidienne -----
    def derniere_releve(self) -> str | None:
        return _lire(self.f_vus, {}).get("le")

    def relever(self, pause: float = 1.0) -> dict:
        """Relit les flux déclarés et cumule les nouveaux liens. Une source en échec n'arrête pas les autres.
        Rend {id de source : nombre de liens lus, ou "echec"} et "nouveaux" : liens jamais vus. Si toutes les
        sources échouent, rien n'est écrit (la date de dernière relève ne bouge pas)."""
        resultat: dict[str, int | str] = {}
        nouveaux: list[dict] = []
        for i, s in enumerate(self.sources().values()):
            if i:
                time.sleep(pause)
            try:
                r = lien.recuperer(s["flux"], accept=FLUX_ACCEPT)
                lus = lire_flux(r.corps, s)
                nouveaux += lus
                resultat[s["id"]] = len(lus)
            except Exception as e:  # une source en échec (réseau, flux illisible) n'arrête pas les autres
                log.warning("flux de tests %s en échec : %s", s["id"], getattr(e, "public", None) or type(e).__name__)
                resultat[s["id"]] = "echec"
        if all(v == "echec" for v in resultat.values()):
            resultat["nouveaux"] = 0
            resultat["tous_en_echec"] = True
            return resultat
        with self._verrou:
            d = _lire(self.f_vus, {})
            liens = d.get("liens", [])
            connus = {x["url"] for x in liens}
            ajoutes = [x for x in nouveaux if x["url"] not in connus]
            # dates des liens déjà vus, complétées si le flux les donne
            par_url = {x["url"]: x for x in liens}
            for x in nouveaux:
                if x["url"] in par_url and x.get("date") and not par_url[x["url"]].get("date"):
                    par_url[x["url"]]["date"] = x["date"]
            liens = sorted([*ajoutes, *liens], key=lambda x: x.get("date") or "", reverse=True)[:VUS_MAX]
            _ecrire(self.f_vus, {"le": time.strftime("%Y-%m-%dT%H:%M:%S"), "liens": liens})
        resultat["nouveaux"] = len(ajoutes)
        return resultat


def demarrer(tests: Tests, periode_h: float = PERIODE_H, pause_demarrage: float = PAUSE_DEMARRAGE) -> threading.Thread:
    """Fil quotidien de relève des flux : première relève après une pause de démarrage, ou à l'échéance
    si la dernière date de moins d'une période. Une erreur est journalisée et n'arrête jamais le fil."""
    def boucle():
        time.sleep(pause_demarrage)
        while True:
            attente = periode_h * 3600
            try:
                derniere = tests.derniere_releve()
                age = time.time() - time.mktime(time.strptime(derniere, "%Y-%m-%dT%H:%M:%S")) if derniere else None
                if age is None or age >= attente:
                    r = tests.relever()
                    log.info("relève des liens de tests : %s nouveaux", r.get("nouveaux"))
                    if r.get("tous_en_echec"):
                        attente = 3600
                else:
                    attente -= age
            except Exception:
                log.exception("relève des liens de tests en échec")
                attente = min(attente, 3600)
            time.sleep(attente)

    fil = threading.Thread(target=boucle, name="tests-liens", daemon=True)
    fil.start()
    return fil

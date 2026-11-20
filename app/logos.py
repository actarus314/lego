"""Logos des marques : l'icône du site officiel de chaque marque (`data/marques.json`), récupérée
par le service et gardée dans son dossier de données. Le dépôt ne contient aucun logo.

Une icône est cherchée dans la page d'accueil (apple-touch-icon, puis les icônes déclarées,
puis /favicon.ico), vérifiée par sa signature (PNG, ICO, JPEG, GIF, WebP, SVG). Parmi les icônes
lisibles, la plus grande est gardée (un SVG compte comme la plus grande). Un logo réussi est relu
tous les 30 jours ; un échec est retenté au bout de 1 jour, puis 3, 7 et 30 jours. Une marque sans
site connu garde la pastille à initiales.
"""
from __future__ import annotations

import html
import json
import logging
import re
import threading
import time
from pathlib import Path
from urllib.parse import urljoin, urlsplit

from . import lien, normalise as n
from .donnees import _ecrire, _lire

log = logging.getLogger("logos")
RACINE = Path(__file__).resolve().parent.parent
TAILLE_MAX = 500 * 1024
VALIDITE_J = 30                  # durée d'un logo récupéré avant relecture
ECHELLE_J = (1, 3, 7, 30)        # délai avant un nouvel essai après le 1er, 2e, 3e, 4e échec (et suivants)
MARGE_S = 3600                   # tolérance : la boucle quotidienne ne tombe pas à la seconde près
CANDIDATES_MAX = 6               # icônes essayées au plus par marque
TAILLE_SUFFISANTE = 96           # pixels : au-delà, inutile de chercher une icône plus grande
PAUSE_S = 1                      # pause entre deux marques, par politesse envers les sites
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
    if _est_svg(corps[:2000]):
        return "svg"
    return None


def _est_svg(debut: bytes) -> bool:
    """Prologue XML et commentaires facultatifs, puis `<svg`. Lecture d'un seul passage, sans
    retour arrière : une expression régulière à répétition imbriquée prenait un temps
    exponentiel sur une suite de commentaires sans `<svg`."""
    s = debut.lstrip()
    if s.startswith(b"<?xml"):
        fin = s.find(b">")
        if fin < 0:
            return False
        s = s[fin + 1:].lstrip()
    while s.startswith(b"<!--"):
        fin = s.find(b"-->", 4)
        if fin < 0:
            return False
        s = s[fin + 3:].lstrip()
    return re.match(rb"<svg\b", s) is not None


def dimension(corps: bytes, ext: str) -> int | None:
    """Plus grand côté en pixels d'une image PNG, GIF, ICO, JPEG ou WebP ; None si illisible ou SVG."""
    try:
        if ext == "png" and len(corps) >= 24:
            return max(int.from_bytes(corps[16:20], "big"), int.from_bytes(corps[20:24], "big"))
        if ext == "gif" and len(corps) >= 10:
            return max(int.from_bytes(corps[6:8], "little"), int.from_bytes(corps[8:10], "little"))
        if ext == "ico":
            nb = int.from_bytes(corps[4:6], "little")
            tailles = [max(corps[6 + 16 * k] or 256, corps[7 + 16 * k] or 256) for k in range(min(nb, 64))
                       if len(corps) >= 8 + 16 * k]
            return max(tailles, default=None)
        if ext == "webp":
            fmt = corps[12:16]
            if fmt == b"VP8X":
                return max(int.from_bytes(corps[24:27], "little"), int.from_bytes(corps[27:30], "little")) + 1
            if fmt == b"VP8L":
                v = int.from_bytes(corps[21:25], "little")
                return max(v & 0x3FFF, (v >> 14) & 0x3FFF) + 1
            if fmt == b"VP8 ":
                return max(int.from_bytes(corps[26:28], "little") & 0x3FFF, int.from_bytes(corps[28:30], "little") & 0x3FFF)
        if ext == "jpg":
            i = 2
            while i + 9 < len(corps):
                if corps[i] != 0xFF:
                    i += 1
                    continue
                marqueur = corps[i + 1]
                if marqueur in (0xD8, 0x01) or 0xD0 <= marqueur <= 0xD7 or marqueur == 0xFF:
                    i += 1 if marqueur == 0xFF else 2
                    continue
                if 0xC0 <= marqueur <= 0xCF and marqueur not in (0xC4, 0xC8, 0xCC):
                    return max(int.from_bytes(corps[i + 5:i + 7], "big"), int.from_bytes(corps[i + 7:i + 9], "big"))
                i += 2 + int.from_bytes(corps[i + 2:i + 4], "big")
    except (IndexError, ValueError):
        pass
    return None


def _attribut(balise: str, nom: str) -> str | None:
    m = re.search(r"(?<![\w-])" + nom + r"""\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'>]+))""", balise, re.I)
    return html.unescape(next(g for g in m.groups() if g is not None)).strip() if m else None


def _agrandie(url: str) -> str | None:
    """Boutiques Shopify : l'icône déclarée est souvent une miniature (`…_32x32.png`, `?height=32`).
    Rend l'adresse du même fichier en 256 pixels de large, ou None si l'adresse n'est pas une miniature."""
    p = urlsplit(url)
    if "/cdn/shop/" not in p.path and "cdn.shopify.com" not in (p.hostname or ""):
        return None
    chemin = re.sub(r"_(?:\d+x\d*|x\d+)(?=\.\w+$)", "", p.path)
    requete = [kv for kv in p.query.split("&") if kv and kv.split("=")[0] not in ("width", "height", "crop")]
    petite = chemin != p.path or any(
        kv.split("=")[0] in ("width", "height") and kv.split("=")[-1].isdigit() and int(kv.split("=")[-1]) < 256
        for kv in p.query.split("&"))
    if not petite:
        return None
    return p._replace(path=chemin, query="&".join(requete + ["width=256"])).geturl()


def _page_accueil(site: str):
    """Page d'accueil du site, en suivant jusqu'à 2 redirections écrites dans la page (`<meta
    http-equiv="refresh">` ou une ligne de script sur une page courte), que lien.recuperer ne voit pas,
    quand la page n'a pas d'icône."""
    r = lien.recuperer("https://" + site)
    for _ in range(2):
        page = r.corps.decode("utf-8", "replace")
        if re.search(r"<link\b[^>]*icon", page, re.I):
            break
        m = re.search(r"<meta\b[^>]*http-equiv=[\"']?refresh[^>]*>", page, re.I)
        cible = _attribut(m.group(0), "content") if m else None
        cible = re.search(r"url\s*=\s*['\"]?([^'\";]+)", cible or "", re.I)
        if cible:
            cible = cible.group(1)
        else:  # redirection par script : window.location(.href) = "/adresse"
            js = re.search(r"(?:window\.|document\.)?location(?:\.href)?\s*=\s*['\"]([^'\"]+)['\"]|location\.replace\(\s*['\"]([^'\"]+)['\"]", page)
            cible = (js.group(1) or js.group(2)) if js and len(page) < 4000 else None
        if not cible:
            break
        r = lien.recuperer(urljoin(r.url, cible.strip()))
    return r


def _candidats(site: str) -> list[str]:
    """Adresses d'icônes de la page d'accueil, de la plus prometteuse à la moins : apple-touch-icon,
    puis les autres icônes déclarées par taille décroissante (SVG compté comme très grand), puis le
    logo de la page (microdonnées, `og:logo`, JSON-LD, image nommée « logo »), puis /favicon.ico. Les adresses
    relatives, y compris `//hôte/…`, sont résolues (balise `<base>` comprise)."""
    r = _page_accueil(site)
    page = r.corps.decode("utf-8", "replace")
    base = r.url
    b = re.search(r"<base\b[^>]*>", page, re.I)
    if b and _attribut(b.group(0), "href"):
        base = urljoin(r.url, _attribut(b.group(0), "href"))
    liens = []
    for balise in re.findall(r"<link\b[^>]*>", page, re.I):
        rel = (_attribut(balise, "rel") or "").lower()
        href = _attribut(balise, "href")
        # « mask-icon » est un pictogramme monochrome de Safari, pas un logo
        if not href or "icon" not in rel or "mask-icon" in rel or href.startswith("data:"):
            continue
        sizes = (_attribut(balise, "sizes") or "").lower()
        tailles = [int(x) for x in re.findall(r"(\d+)x\d+", sizes)]
        vecteur = "any" in sizes or href.split("?")[0].lower().endswith(".svg") or "svg" in (_attribut(balise, "type") or "")
        taille = 4096 if vecteur else max(tailles, default=32)
        liens.append(((2 if "apple-touch" in rel else 1, taille), urljoin(base, href)))
    liens.sort(key=lambda x: x[0], reverse=True)
    logos_page = []
    for balise in re.findall(r"<(?:img|meta)\b[^>]*>", page, re.I):
        if _attribut(balise, "itemprop") == "logo" and _attribut(balise, "src"):
            logos_page.append(_attribut(balise, "src"))
        elif (_attribut(balise, "property") or "").lower() == "og:logo" and _attribut(balise, "content"):
            logos_page.append(_attribut(balise, "content"))
    # dernier recours : les premières images de la page dont le nom, la classe ou l'identifiant dit « logo »
    # (page sans icône déclarée) ; les microdonnées et JSON-LD passent avant
    images = [bal for bal in re.findall(r"<img\b[^>]*>", page, re.I)
              if re.search(r"logo", " ".join(_attribut(bal, k) or "" for k in ("src", "class", "id", "alt")), re.I)
              and _attribut(bal, "src") and not _attribut(bal, "src").startswith("data:")]
    for bloc in re.findall(r"<script[^>]+ld\+json[^>]*>(.*?)</script>", page, re.S | re.I):
        for m in re.finditer(r'"logo"\s*:\s*(?:"([^"]+)"|\{[^{}]*?"url"\s*:\s*"([^"]+)")', bloc):
            logos_page.append((m.group(1) or m.group(2)).replace("\\/", "/"))
    logos_page += [_attribut(bal, "src") for bal in images[:3]]
    vus, sortie = set(), []
    for u in [u for _, u in liens] + [urljoin(base, x) for x in logos_page] + [urljoin(r.url, "/favicon.ico")]:
        for v in (_agrandie(u), u):
            if v and v not in vus:
                vus.add(v)
                sortie.append(v)
    return sortie


def _lire_icone(url: str) -> tuple[bytes, str] | None:
    """Télécharge `url` ; rend (octets, format) si c'est une image reconnue de taille permise, sinon None."""
    if url.startswith("//"):
        url = "https:" + url
    try:
        r = lien.recuperer(url, accept="image/*,*/*;q=0.5")
    except Exception as ex:  # refus, délai, réponse illisible : on passe à l'icône suivante
        log.debug("icône %s refusée : %s", url, getattr(ex, "public", ex))
        return None
    ext = _format(r.corps)
    if ext and 0 < len(r.corps) <= TAILLE_MAX:
        return r.corps, ext
    return None


def _adresses(conf: dict):
    """Adresses à essayer : l'adresse directe `icone`, puis (lues seulement si elle ne suffit pas)
    les icônes de la page d'accueil de `site`. Rend aussi, en dernier, l'erreur de lecture de la page."""
    if conf.get("icone"):
        yield conf["icone"]
    if conf.get("site"):
        try:
            yield from _candidats(conf["site"])
        except Exception as ex:  # page d'accueil illisible : seule l'adresse directe reste
            yield ex


def recuperer(conf: dict) -> tuple[bytes, str]:
    """Rend (octets, format) de la meilleure icône : l'adresse directe `icone` si elle est donnée et
    lisible, sinon les icônes de la page d'accueil de `site`. Dès qu'une icône d'au moins
    TAILLE_SUFFISANTE pixels (ou un SVG) est trouvée, elle est gardée et la page n'est pas lue ;
    sinon la plus grande des CANDIDATES_MAX premières. Lève la cause (LienRefuse) si la page
    d'accueil est illisible et qu'aucune adresse directe n'a servi, sinon ValueError."""
    meilleure, meilleur_score, essais, erreur_page = None, -1, 0, None
    for url in _adresses(conf):
        if isinstance(url, Exception):
            erreur_page = url
            break
        if essais >= CANDIDATES_MAX:
            break
        essais += 1
        icone = _lire_icone(url)
        if not icone:
            continue
        corps, ext = icone
        score = 1 << 20 if ext == "svg" else (dimension(corps, ext) or 1)
        if score > meilleur_score:
            meilleure, meilleur_score = icone, score
        if meilleur_score >= TAILLE_SUFFISANTE:
            break
    if meilleure:
        return meilleure
    if erreur_page is not None and not essais:
        raise erreur_page
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

    def chemin(self, s: str) -> tuple[str, str] | None:
        """(nom du fichier dans `dossier`, type) du logo `s` ; le serveur vérifie le chemin."""
        e = self.etat().get(s)
        if not e or not e.get("fichier") or e.get("format") not in TYPES:
            return None
        return e["fichier"], TYPES[e["format"]]

    @staticmethod
    def _instant(texte: str) -> float:
        return time.mktime(time.strptime(texte, "%Y-%m-%dT%H:%M:%S"))

    def a_relire(self, e: dict | None, age_max_j: float = VALIDITE_J) -> bool:
        """Vrai si la marque n'a jamais été essayée ou si son délai est écoulé : `age_max_j` jours après
        un logo récupéré, après un échec le délai de ECHELLE_J selon le nombre d'échecs de suite."""
        if not e:
            return True
        essai = e.get("essai") or e.get("le")  # anciens états : « le » est la date du dernier essai
        if not essai:
            return True
        if e.get("erreur"):
            n_echecs = max(1, int(e.get("echecs") or 1))
            delai = ECHELLE_J[min(n_echecs, len(ECHELLE_J)) - 1]
        else:
            delai = age_max_j
        return time.time() - self._instant(essai) >= delai * 86400 - MARGE_S

    def actualiser(self, age_max_j: float = VALIDITE_J) -> dict:
        """Récupère les logos absents, échus (`age_max_j` jours) ou en échec dont le délai de nouvel
        essai est écoulé. Rend {lus, echecs}."""
        with VERROU:
            etat = self.etat()
            lus, echecs = 0, 0
            for marque, conf in sites().items():
                s = slug(marque)
                e = etat.get(s) or {}
                if not self.a_relire(e, age_max_j):
                    continue
                maintenant = time.strftime("%Y-%m-%dT%H:%M:%S")
                try:
                    corps, ext = recuperer(conf)
                    self.dossier.mkdir(parents=True, exist_ok=True)
                    (self.dossier / f"{s}.{ext}").write_bytes(corps)
                    ancien = e.get("fichier") or ""
                    if ancien != f"{s}.{ext}" and re.fullmatch(r"[a-z0-9-]+\.[a-z]+", ancien):
                        (self.dossier / ancien).unlink(missing_ok=True)  # ancien format du même logo
                    etat[s] = {"marque": marque, "fichier": f"{s}.{ext}", "format": ext, "le": maintenant,
                               "essai": maintenant, "taille": dimension(corps, ext),
                               "source": conf.get("icone") or conf["site"]}
                    lus += 1
                except Exception as ex:  # une marque sans logo garde sa pastille
                    log.info("logo %s non récupéré : %s", marque, getattr(ex, "public", ex))
                    # un logo déjà récupéré reste servi ; « le » garde la date de ce logo
                    etat[s] = {**e, "marque": marque, "essai": maintenant, "erreur": True,
                               "echecs": max(1, int(e.get("echecs") or 1)) + 1 if e.get("erreur") else 1,
                               "motif": str(getattr(ex, "public", ex))[:200]}
                    if not e.get("fichier"):
                        etat[s]["le"] = maintenant
                    echecs += 1
                time.sleep(PAUSE_S)
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

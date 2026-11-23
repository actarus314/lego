"""Lecture d'une page produit : nom, prix, photo, nombre de pièces, disponibilité.

La lecture passe par `recuperer`, qui refuse toute adresse du réseau local
(boucle locale, réseaux privés, adresses de lien local, réservées ou de
diffusion) et se connecte à l'adresse IP déjà vérifiée, ce qui empêche un
nom de domaine de changer de résolution entre la vérification et la
connexion. Seuls les ports 80 et 443 sont acceptés. Les redirections sont
suivies une à une, chacune revérifiée.

`recuperer` tient aussi le débit par site commun à tout le service : une seconde au moins entre deux
départs de requête vers un même site, quel que soit le module, et une pause de tout le service sur un
site qui répond 429 (voir `INTERVALLE_SITE_S` et la suite) ; les boutiques Shopify et leurs photos forment
une seule famille, avec une file et une pause communes.
"""
from __future__ import annotations

import zlib
import html
import http.client
import ipaddress
import json
import re
import socket
import ssl
import threading
import time
from dataclasses import dataclass
from urllib.parse import quote, urljoin, urlsplit

TAILLE_MAX = 3 * 1024 * 1024
DELAI = 12
REDIRECTIONS_MAX = 4
PORTS = (80, 443)  # ports web standard : une boutique n'en emploie pas d'autre
# photo affichable sur un autre site ; version de la page (requête conditionnelle) ; serveur et protection
# anti-robot, pour dire la cause exacte d'un refus
ENTETES_LUS = ("Cross-Origin-Resource-Policy", "ETag", "Server", "cf-mitigated", "Powered-By")
AGENT = "carnet-briques (+https://github.com/actarus314/lego)"

# Débit par site, commun à tout le service (synchronisation, sélection, photos, logos, boutiques, occasion,
# tests) : chaque module a sa pause, mais deux modules qui passent en même temps sur une même boutique
# s'additionnaient (429 de KBS, Bausteinreich et Mould King signalés le 23/11/2026). Une requête vers un
# site part INTERVALLE_SITE_S au moins après le départ de la précédente vers ce site, quel que soit le
# module ; un 429 met le site en pause pour tout le service (durée de Retry-After, bornée entre
# PAUSE_429_MIN_S et PAUSE_429_MAX_S, sinon PAUSE_429_S), et toute requête pendant la pause échoue
# aussitôt, sans réseau : LienRefuse de statut 429 et d'attribut `pause` vrai (la pause restante est dans
# `attente`), pour que l'appelant reporte l'essai sans compter un échec du site.
INTERVALLE_SITE_S = 1.0
INTERVALLES = {"cdn.rebrickable.com": 0.3, "images.brickset.com": 0.5,
               "cdn.bricksvalue.com": 0.3}   # serveurs de photos des boutiques, pas les boutiques
# Famille Shopify : toutes les boutiques hébergées par Shopify et son serveur de photos passent par une même
# protection contre les robots, qui juge l'adresse IP du service dans son ensemble (23/11/2026 : depuis le NUC,
# 429 sur toutes les boutiques Shopify à la fois, 200 depuis une autre adresse avec le même client). La famille
# partage donc une seule file (INTERVALLE_FAMILLE_S entre deux requêtes, toutes boutiques et photos confondues)
# et une seule pause : un 429 d'un membre arrête toute la famille. Membres : cdn.shopify.com, *.myshopify.com,
# les hôtes déclarés par `rattacher` (sources Shopify) et tout hôte qui répond « Powered-By: Shopify ».
INTERVALLE_FAMILLE_S = 1.0
SHOPIFY = "shopify"
_famille: dict[str, str] = {"cdn.shopify.com": SHOPIFY}
PAUSE_429_S = 600
PAUSE_429_MIN_S = 60
PAUSE_429_MAX_S = 3600
_prochaine: dict[str, float] = {}   # site ou famille : instant du prochain départ permis
_pause: dict[str, float] = {}       # site ou famille : fin de la pause après un 429
_suite_429: dict[str, int] = {}     # site ou famille : 429 reçus de suite (la pause double à chacun)
_dernier_429: dict[str, float] = {}  # site ou famille : instant du dernier 429 reçu
_verrou_sites = threading.Lock()


def site(hote: str) -> str:
    return (hote or "").lower().rstrip(".").removeprefix("www.")


def _attente_s(valeur) -> float:
    """Pause après un 429 : Retry-After en secondes, bornée ; une date HTTP, une valeur absente,
    nulle, négative ou non finie : PAUSE_429_S."""
    try:
        v = float(valeur)
    except (TypeError, ValueError):
        return float(PAUSE_429_S)
    if v != v or v in (float("inf"), float("-inf")) or v <= 0:
        return float(PAUSE_429_S)
    return min(max(v, PAUSE_429_MIN_S), PAUSE_429_MAX_S)


def rattacher(hotes, famille: str = SHOPIFY) -> None:
    """Range des hôtes dans une famille (file et pause communes)."""
    with _verrou_sites:
        for h in hotes:
            if h:
                _famille[site(h)] = famille


def cle(hote: str) -> str:
    """Clé de débit et de pause : la famille de l'hôte, sinon son site."""
    s = site(hote)
    if s.endswith(".myshopify.com"):
        return SHOPIFY
    return _famille.get(s, s)


def _intervalle(c: str) -> float:
    return INTERVALLE_FAMILLE_S if c == SHOPIFY else INTERVALLES.get(c, INTERVALLE_SITE_S)


def en_pause(hote: str, maintenant: float | None = None) -> float:
    """Secondes de pause restantes pour ce site (ou sa famille) après un 429 (0 : pas en pause)."""
    return max(_pause.get(cle(hote), 0.0) - (maintenant or time.time()), 0.0)


def pauses() -> dict[str, int]:
    """Sites et familles en pause : secondes restantes."""
    maintenant = time.time()
    return {c: int(fin - maintenant) + 1 for c, fin in list(_pause.items()) if fin > maintenant}


def _refus_pause(reste: float) -> "LienRefuse":
    e = LienRefuse(f"site en pause après un refus 429 (encore {int(reste) + 1} s)")
    e.statut, e.attente, e.pause, e.entetes = 429, str(int(reste) + 1), True, {}
    return e


def _reserver(hote: str) -> None:
    """Attend le tour de ce site (ou de sa famille), puis vérifie encore la pause (un 429 reçu par une autre
    requête pendant l'attente arrête aussi celle-ci). En pause : LienRefuse sans attendre."""
    c = cle(hote)
    with _verrou_sites:
        maintenant = time.time()
        reste = _pause.get(c, 0.0) - maintenant
        if reste > 0:
            raise _refus_pause(reste)
        depart = max(maintenant, _prochaine.get(c, 0.0))
        _prochaine[c] = depart + _intervalle(c)
    if depart > maintenant:
        time.sleep(depart - maintenant)
        reste = en_pause(hote)
        if reste > 0:
            raise _refus_pause(reste)


def _noter_429(hote: str, attente) -> None:
    """Pause après un 429 : Retry-After borné, doublé à chaque nouvel épisode de 429 reçus de suite (avec
    Retry-After: 60, 1, 2, 4… minutes ; une heure au plus), pour ne pas revenir chaque minute vers une
    adresse refusée. Les 429 des requêtes déjà parties, reçus pendant la pause, ne la doublent pas."""
    c = cle(hote)
    with _verrou_sites:
        maintenant = time.time()
        _dernier_429[c] = maintenant
        if _pause.get(c, 0.0) > maintenant:   # même épisode : la pause en cours tient
            return
        n = _suite_429.get(c, 0) + 1
        _suite_429[c] = n
        _pause[c] = maintenant + min(_attente_s(attente) * 2 ** min(n - 1, 12), PAUSE_429_MAX_S)


def _noter_reponse(hote: str, r: "Reponse", depart: float) -> None:
    """Réponse autre qu'un 429 : un hôte Shopify rejoint sa famille ; la suite de 429 repart de zéro sur une
    réponse acceptée (2xx, 304) d'une boutique, partie après le dernier 429 : une photo servie par le CDN
    pendant que les boutiques refusent, une redirection ou une erreur ne la remettent pas à zéro."""
    if (r.entetes or {}).get("powered-by", "").strip().lower() == "shopify" and cle(hote) != SHOPIFY:
        rattacher([hote])
    c = cle(hote)
    if c in _suite_429 and (200 <= r.statut < 300 or r.statut == 304) and site(hote) != "cdn.shopify.com":
        with _verrou_sites:   # revu sous verrou : un 429 noté entre-temps par un autre fil garde la suite
            if depart > _dernier_429.get(c, 0.0):
                _suite_429.pop(c, None)


class LienRefuse(ValueError):
    """Adresse refusée ou page illisible. `public` : message sûr à montrer à l'utilisateur."""

    def __init__(self, message: str):
        super().__init__(message)
        self.public = message


@dataclass
class Reponse:
    url: str
    statut: int
    type: str
    corps: bytes
    attente: str | None = None
    entetes: dict | None = None   # en-têtes de ENTETES_LUS présents dans la réponse, noms en minuscules


def _ip_publique(ip: str) -> bool:
    a = ipaddress.ip_address(ip)
    if isinstance(a, ipaddress.IPv6Address) and a.ipv4_mapped:
        a = a.ipv4_mapped
    return a.is_global and not (a.is_multicast or a.is_reserved)


def resoudre(hote: str, port: int) -> str:
    """Rend une adresse IP publique de l'hôte, ou lève LienRefuse."""
    try:
        infos = socket.getaddrinfo(hote, port, type=socket.SOCK_STREAM)
    except socket.gaierror as e:
        raise LienRefuse(f"adresse introuvable : {hote}") from e
    ips = [i[4][0] for i in infos]
    if not ips or not all(_ip_publique(ip) for ip in ips):
        raise LienRefuse("adresse refusée : réseau local ou réservé")
    return ips[0]


def contexte_tls() -> ssl.SSLContext:
    """Vérification du certificat et du nom d'hôte, TLS 1.2 au minimum."""
    ctx = ssl.create_default_context()
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    return ctx


def _chemin(p) -> str:
    """Chemin et requête en ASCII : les caractères non ASCII et les espaces sont encodés (UTF-8),
    les séquences %XX déjà présentes et les séparateurs d'URL sont gardés tels quels. http.client
    refuse un chemin non ASCII (UnicodeEncodeError) et un saut de ligne y ouvrirait une injection."""
    chemin = quote(p.path or "/", safe="/%:@!$&'()*+,;=~-._")
    return chemin + (("?" + quote(p.query, safe="/%:@!$&'()*+,;=~-._?")) if p.query else "")


def _get(url: str, accept: str, entetes: dict | None = None, max_octets: int | None = None) -> Reponse:
    """Une requête GET, sans suivre de redirection. `max_octets` : n'en lire que ce début, sans
    dépassement ni décompression (essai d'une photo dont le site ignore l'en-tête Range)."""
    p = urlsplit(url)
    if p.scheme not in ("http", "https") or not p.hostname:
        raise LienRefuse("seuls les liens http et https sont acceptés")
    if p.username or p.password:
        raise LienRefuse("lien avec identifiants refusé")
    port = p.port if p.port is not None else (443 if p.scheme == "https" else 80)  # « :0 » est refusé, pas remplacé
    if port not in PORTS:
        raise LienRefuse("seuls les ports 80 et 443 sont acceptés")
    try:
        hote = p.hostname.encode("idna").decode("ascii")  # nom de domaine accentué : forme ASCII
    except UnicodeError as e:
        raise LienRefuse(f"nom de domaine invalide : {p.hostname}") from e
    ip = resoudre(hote, port)
    chemin = _chemin(p)
    sock = socket.create_connection((ip, port), timeout=DELAI)
    try:
        if p.scheme == "https":
            sock = contexte_tls().wrap_socket(sock, server_hostname=hote)
        conn = http.client.HTTPConnection(hote, port, timeout=DELAI)
        conn.sock = sock
        conn.request("GET", chemin, headers={
            "Host": (f"[{hote}]" if ":" in hote else hote) + (f":{p.port}" if p.port is not None else ""), "User-Agent": AGENT,
            "Accept": accept, "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.7", "Accept-Encoding": "gzip",
            **(entetes or {})})
        r = conn.getresponse()
        if 300 <= r.status < 400 and r.getheader("Location"):
            return Reponse(urljoin(url, r.getheader("Location")), r.status, "", b"")
        if max_octets:
            return Reponse(url, r.status, r.getheader("Content-Type", ""), r.read(max_octets), r.getheader("Retry-After"),
                           {k.lower(): r.getheader(k) for k in ENTETES_LUS if r.getheader(k)})
        corps = r.read(TAILLE_MAX + 1)
        if len(corps) > TAILLE_MAX:
            raise LienRefuse("page trop volumineuse")
        if r.getheader("Content-Encoding", "").lower() == "gzip":
            # décompression bornée : une petite réponse compressée ne peut pas occuper toute la mémoire
            try:
                corps = zlib.decompressobj(16 + zlib.MAX_WBITS).decompress(corps, TAILLE_MAX + 1)
            except zlib.error as e:
                raise LienRefuse("réponse compressée illisible") from e
            if len(corps) > TAILLE_MAX:
                raise LienRefuse("page trop volumineuse")
        return Reponse(url, r.status, r.getheader("Content-Type", ""), corps, r.getheader("Retry-After"),
                       {k.lower(): r.getheader(k) for k in ENTETES_LUS if r.getheader(k)})
    finally:
        sock.close()


def recuperer(url: str, accept: str = "text/html,application/json;q=0.9,*/*;q=0.5",
              entetes: dict | None = None, statuts: tuple[int, ...] = (200,), max_octets: int | None = None) -> Reponse:
    for _ in range(REDIRECTIONS_MAX + 1):
        p = urlsplit(url)
        hote = p.hostname or ""
        if p.scheme in ("http", "https") and hote:   # adresse refusée d'avance : sans attendre son tour
            _reserver(hote)
        depart = time.time()
        r = _get(url, accept, entetes, max_octets)
        if r.statut == 429:
            _noter_429(hote, r.attente)
        else:
            _noter_reponse(hote, r, depart)
        if 300 <= r.statut < 400 and r.url != url:   # redirection ; un 3xx sans Location est refusé plus bas
            url = r.url
            continue
        if r.statut not in statuts:
            e = LienRefuse(f"le site a répondu {r.statut}")
            e.statut, e.attente, e.entetes = r.statut, r.attente, r.entetes or {}
            if r.statut == 429:   # la pause commune commence : l'appelant la traite comme les requêtes suivantes
                e.pause, e.attente = True, str(int(en_pause(hote)) + 1)
            raise e
        return r
    raise LienRefuse("trop de redirections")


# ---------- Extraction ----------

_PIECES = re.compile(r"(\d{1,2}[ ., ]?\d{3}|\d{3,4})\s*(?:pi[eè]ces|pieces|pcs|parts|bricks|Teile|Steine)\b", re.I)


def nombre_pieces(texte: str) -> int | None:
    m = _PIECES.search(texte)
    return int(re.sub(r"\D", "", m.group(1))) if m else None


def _nettoyer(t: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", t or ""))).strip()


def depuis_shopify(d: dict) -> dict:
    img = d.get("featured_image") or ""
    return {
        "nom": d.get("title", "").strip(),
        "prix": round(d["price"] / 100, 2) if isinstance(d.get("price"), (int, float)) else None,
        "dispo": bool(d.get("available")),
        "img": ("https:" + img) if img.startswith("//") else img,
        "pcs": nombre_pieces(_nettoyer(d.get("description", ""))),
        "source": "shopify",
    }


def _meta(page: str, *noms: str) -> str | None:
    for n in noms:
        m = re.search(r'<meta[^>]+(?:property|name|itemprop)=["\']' + re.escape(n) + r'["\'][^>]*content=["\']([^"\']+)', page, re.I) \
            or re.search(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]*(?:property|name|itemprop)=["\']' + re.escape(n) + r'["\']', page, re.I)
        if m:
            return html.unescape(m.group(1)).strip()
    return None


def _prix(v) -> float | None:
    if v is None:
        return None
    s = str(v).strip().replace(" ", "").replace(" ", "")
    if re.fullmatch(r"\d+,\d{1,2}", s):
        s = s.replace(",", ".")
    s = s.replace(",", "")
    try:
        return round(float(s), 2)
    except ValueError:
        return None


def _jsonld_produit(page: str) -> dict | None:
    for bloc in re.findall(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', page, re.S | re.I):
        try:
            d = json.loads(bloc.strip())
        except ValueError:
            continue
        pile = d if isinstance(d, list) else [d]
        while pile:
            x = pile.pop()
            if isinstance(x, dict):
                if "@graph" in x:
                    pile.extend(x["@graph"] if isinstance(x["@graph"], list) else [x["@graph"]])
                t = x.get("@type")
                if t == "Product" or (isinstance(t, list) and "Product" in t):
                    return x
    return None


def depuis_html(page: str) -> dict:
    out = {"nom": None, "prix": None, "dispo": None, "img": None, "pcs": None, "source": "page"}
    p = _jsonld_produit(page)
    if p:
        out["nom"] = p.get("name")
        img = p.get("image")
        out["img"] = img[0] if isinstance(img, list) and img else (img.get("url") if isinstance(img, dict) else img)
        offres = p.get("offers")
        offres = offres[0] if isinstance(offres, list) and offres else offres
        if isinstance(offres, dict):
            out["prix"] = _prix(offres.get("price") or offres.get("lowPrice"))
            dispo = str(offres.get("availability", ""))
            if dispo:
                out["dispo"] = "InStock" in dispo or "PreOrder" in dispo
    out["nom"] = out["nom"] or _meta(page, "og:title", "twitter:title")
    out["img"] = out["img"] or _meta(page, "og:image", "twitter:image")
    out["prix"] = out["prix"] or _prix(_meta(page, "product:price:amount", "og:price:amount", "price"))
    # Pièces : seulement dans la description du produit, jamais dans le reste de la page
    # (les blocs « produits similaires » donnent de faux nombres).
    desc = (p or {}).get("description") or _meta(page, "og:description", "description", "twitter:description") or ""
    out["pcs"] = nombre_pieces(_nettoyer(str(desc)))
    if out["nom"]:
        out["nom"] = _nettoyer(out["nom"])[:120]
    return out


def lire(url: str) -> dict:
    """Lit une page produit. Essaie d'abord le point d'accès Shopify (`.js`)."""
    p = urlsplit(url)
    if "/products/" in p.path:
        base = f"{p.scheme}://{p.netloc}{p.path.rstrip('/')}"
        try:
            r = recuperer(base + ".js", accept="application/json")
            d = depuis_shopify(json.loads(r.corps))
            d["url"] = base
            return d
        except (LienRefuse, ValueError, OSError):
            pass
    r = recuperer(url)
    page = r.corps.decode("utf-8", "replace")
    d = depuis_html(page)
    d["url"] = r.url
    if not (d["nom"] or d["prix"]):
        raise LienRefuse("aucune information produit lisible sur cette page")
    return d

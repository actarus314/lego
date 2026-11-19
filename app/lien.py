"""Lecture d'une page produit : nom, prix, photo, nombre de pièces, disponibilité.

La lecture passe par `recuperer`, qui refuse toute adresse du réseau local
(boucle locale, réseaux privés, adresses de lien local, réservées ou de
diffusion) et se connecte à l'adresse IP déjà vérifiée, ce qui empêche un
nom de domaine de changer de résolution entre la vérification et la
connexion. Les redirections sont suivies une à une, chacune revérifiée.
"""
from __future__ import annotations

import html
import http.client
import ipaddress
import json
import re
import socket
import ssl
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit

TAILLE_MAX = 3 * 1024 * 1024
DELAI = 12
REDIRECTIONS_MAX = 4
AGENT = "carnet-briques (+https://github.com/actarus314/lego)"


class LienRefuse(ValueError):
    """Adresse refusée ou page illisible."""


@dataclass
class Reponse:
    url: str
    statut: int
    type: str
    corps: bytes


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


def _get(url: str, accept: str) -> Reponse:
    p = urlsplit(url)
    if p.scheme not in ("http", "https") or not p.hostname:
        raise LienRefuse("seuls les liens http et https sont acceptés")
    if p.username or p.password:
        raise LienRefuse("lien avec identifiants refusé")
    port = p.port or (443 if p.scheme == "https" else 80)
    ip = resoudre(p.hostname, port)
    chemin = (p.path or "/") + (f"?{p.query}" if p.query else "")
    sock = socket.create_connection((ip, port), timeout=DELAI)
    try:
        if p.scheme == "https":
            ctx = ssl.create_default_context()
            sock = ctx.wrap_socket(sock, server_hostname=p.hostname)
        conn = http.client.HTTPConnection(p.hostname, port, timeout=DELAI)
        conn.sock = sock
        conn.request("GET", chemin, headers={
            "Host": p.netloc.split("@")[-1], "User-Agent": AGENT,
            "Accept": accept, "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.7"})
        r = conn.getresponse()
        if 300 <= r.status < 400 and r.getheader("Location"):
            return Reponse(urljoin(url, r.getheader("Location")), r.status, "", b"")
        corps = r.read(TAILLE_MAX + 1)
        if len(corps) > TAILLE_MAX:
            raise LienRefuse("page trop volumineuse")
        return Reponse(url, r.status, r.getheader("Content-Type", ""), corps)
    finally:
        sock.close()


def recuperer(url: str, accept: str = "text/html,application/json;q=0.9,*/*;q=0.5") -> Reponse:
    for _ in range(REDIRECTIONS_MAX + 1):
        r = _get(url, accept)
        if 300 <= r.statut < 400:
            url = r.url
            continue
        if r.statut != 200:
            raise LienRefuse(f"le site a répondu {r.statut}")
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

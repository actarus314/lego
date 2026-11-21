"""Connecteur des boutiques Shopify : catalogue public `/products.json`, page par page.

Le pays de livraison est déclaré par le cookie `localization` (les boutiques à plusieurs
marchés rendent alors leurs prix dans la devise de ce pays). Une page de 250 produits par
requête, une pause entre deux pages, et l'attente demandée par le site en cas de refus 429.
"""
from __future__ import annotations

import gzip
import json
import logging
import math
import os
import re
import time
from pathlib import Path

from .. import lien, normalise as n

log = logging.getLogger("shopify")
PAGE = 250
PAGES_MAX = 40


class Pages:
    """Pages du catalogue déjà lues, avec leur version (en-tête ETag), dans `dossier` : la synchronisation
    suivante les redemande sous condition (If-None-Match) et la boutique répond 304, sans corps, pour
    une page inchangée. Vérifié le 21/11/2026 sur KBS, Bausteinreich et Mould King officiel. Une page sans
    ETag n'est pas gardée ; une page gardée pour une autre adresse ou illisible fait relire la page en
    entier. Garder une page est un plus : un disque plein ou en lecture seule n'arrête pas la lecture."""

    def __init__(self, dossier):
        self.dossier = Path(dossier)

    def _fichier(self, page: int):
        return self.dossier / f"{page}.json.gz"

    def lire(self, page: int, url: str) -> tuple[str, bytes] | None:
        try:
            d = json.loads(gzip.decompress(self._fichier(page).read_bytes()))
            if d["url"] != url:
                return None
            return d["etag"], d["corps"].encode("utf-8")
        except (OSError, ValueError, KeyError, TypeError, EOFError):
            return None

    def ecrire(self, page: int, url: str, etag: str | None, corps: bytes) -> None:
        f = self._fichier(page)
        try:
            if not etag:
                f.unlink(missing_ok=True)
                return
            self.dossier.mkdir(parents=True, exist_ok=True)
            tmp = f.with_suffix(".tmp")
            tmp.write_bytes(gzip.compress(json.dumps(
                {"url": url, "etag": etag, "corps": corps.decode("utf-8", "replace")}).encode("utf-8")))
            os.replace(tmp, f)
        except OSError as e:
            log.warning("page %s non gardée : %s", f, e)

    def oublier(self, page: int) -> None:
        try:
            self._fichier(page).unlink(missing_ok=True)
        except OSError:
            pass


def lire(source: dict, pause: float = 1.5, progres=None, pages: Pages | None = None, compte: dict | None = None) -> list[dict]:
    """Rend les offres normalisées d'une boutique. `source` : voir data/sources.json. `pages` : pages
    gardées pour les requêtes conditionnelles ; `compte` reçoit pages lues, inchangées et octets reçus."""
    base = "https://" + source["hote"] + source.get("prefixe", "")
    entetes = {"Cookie": f"localization={source.get('pays', 'FR')}; cart_currency={source.get('devise', 'EUR')}"}
    compte = compte if compte is not None else {}
    compte.update(pages=0, inchangees=0, octets=0)
    produits = []
    for page in range(1, PAGES_MAX + 1):
        url = f"{base}/products.json?limit={PAGE}&page={page}"
        garde = pages.lire(page, url) if pages else None
        r = _page(url, entetes, garde)
        compte["pages"] += 1
        lot = None
        if r.statut == 304:
            try:
                lot = _produits(garde[1])
                compte["inchangees"] += 1
            except ValueError:   # page gardée abîmée : oubliée, relue en entier
                pages.oublier(page)
                r = _page(url, entetes, None)
        if lot is None:
            lot = _produits(r.corps)   # page illisible : erreur avant d'être gardée
            compte["octets"] += len(r.corps)
            if pages:
                pages.ecrire(page, url, (r.entetes or {}).get("etag"), r.corps)
        produits += lot
        if progres:
            progres(len(produits))
        if len(lot) < PAGE:
            break
        time.sleep(pause)
    return [o for o in (offre(p, source) for p in produits) if o]


def _page(url: str, entetes: dict, garde: tuple[str, bytes] | None) -> lien.Reponse:
    """Une page du catalogue, sous condition si elle est gardée ; attend et réessaie sur un refus 429."""
    condition = {"If-None-Match": garde[0]} if garde else {}
    for essai in range(3):
        try:
            return lien.recuperer(url, accept="application/json", entetes={**entetes, **condition},
                                  statuts=(200, 304) if garde else (200,))
        except lien.LienRefuse as e:
            if getattr(e, "statut", None) == 429 and essai < 2:
                time.sleep(min(float(getattr(e, "attente", None) or 30), 120))
                continue
            raise
    raise lien.LienRefuse("trop de refus")


def _produits(corps: bytes) -> list:
    d = json.loads(corps)
    lot = d.get("products") if isinstance(d, dict) else None
    if not isinstance(lot, list):
        raise ValueError("catalogue sans liste de produits")
    return lot


def _barre(v: dict, prix: float | None, centimes: bool = False) -> float | None:
    """Prix barré de la variante (compare_at_price), s'il est supérieur au prix ; en centimes dans /products/<poignée>.js."""
    try:
        b = float(v.get("compare_at_price"))
    except (TypeError, ValueError):
        return None
    if not math.isfinite(b):
        return None
    b = round(b / 100 if centimes else b, 2)
    return b if prix and b > prix else None


def offre(p: dict, source: dict) -> dict | None:
    variantes = p.get("variants") or [{}]
    v = next((x for x in variantes if x.get("available")), variantes[0])
    try:
        prix = round(float(v.get("price")), 2)
    except (TypeError, ValueError):
        prix = None
    if prix is not None and not math.isfinite(prix):
        prix = None
    titre = (p.get("title") or "").strip()
    tags = p.get("tags") or []
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",")]
    desc = n.texte(p.get("body_html"))
    nb = n.pieces(desc, titre)
    if nb and prix and prix / nb < 0.02:  # moins de 2 centimes la pièce : nombre mal lu, ou micro-briques
        nb = None
    if not prix or prix <= 0 or not n.pour_adultes(nb, prix, titre, p.get("product_type") or "", tags,
                                      source.get("seuil_pieces", 500), source.get("seuil_prix", 50.0)):
        return None
    marque = n.marque(p.get("vendor") or "", titre) or source.get("marque")
    if not marque:
        return None
    images = p.get("images") or []
    dims = n.dimensions(desc)
    return {
        "source": source["id"], "boutique": source["nom"], "pays": source.get("pays_boutique"),
        "cle": f"{source['id']}:{p.get('handle')}",
        "url": f"https://{source['hote']}{source.get('prefixe', '')}/products/{p.get('handle')}",
        "nom": titre, "marque": marque, "numero": n.numero(titre, v.get("sku")),
        "prix": prix, "barre": _barre(v, prix), "devise": source.get("devise", "EUR"),
        "dispo": n.disponibilite(any(x.get("available") for x in variantes), tags, titre),
        "img": images[0].get("src") if images else None,
        "images": [i["src"] for i in images[1:8] if i.get("src")],
        "pieces": nb, "dims": dims,
        "type": n.type_briques(p.get("product_type") or "", tags, titre, marque),
        "themes": n.themes(titre, tags, p.get("product_type") or ""),
        # signaux bruts de la boutique : type et thèmes recalculés à chaque reconstruction (index.py), sans
        # attendre la synchronisation suivante quand une règle change
        "signaux": {"categorie": p.get("product_type") or "", "etiquettes": tags, "titre": titre},
        "publie": (p.get("published_at") or p.get("created_at") or "")[:10] or None,
    }


def dimensions_cartes(source: dict, pause: float = 1.5) -> dict[str, list[float]]:
    """Dimensions affichées sur les cartes produit des pages de collection (KBS : « 69 × 19 × 110 cm »),
    absentes du catalogue JSON. Une page de collection donne une vingtaine de produits d'un coup."""
    base = "https://" + source["hote"] + source.get("prefixe", "") + source["cartes"]
    out: dict[str, list[float]] = {}
    for page in range(1, 80):  # une douzaine de produits par page de collection
        r = lien.recuperer(f"{base}?page={page}")
        texte_page = r.corps.decode("utf-8", "replace")
        cartes = texte_page.split('class="resource-card"')[1:]
        if not cartes:
            break
        for c in cartes:
            m = re.search(r'href="[^"]*/products/([a-z0-9-]+)"', c)
            lignes = re.findall(r'kbs-card-info__row"[^>]*>([^<]+)<', c)
            dims = next((n.dimensions(x) for x in lignes if n.dimensions(x)), None)
            if m and dims:
                out[m.group(1)] = dims
        if 'rel="next"' not in texte_page:  # dernière page de la collection
            break
        time.sleep(pause)
    return out


_DIM_FICHE = re.compile(r"(\d{1,3}(?:[.,]\d{1,2})?)\s*[x×]\s*(\d{1,3}(?:[.,]\d{1,2})?)\s*[x×]\s*(\d{1,3}(?:[.,]\d{1,2})?)"
                        r"[\s|]*(?:L\s*x\s*W\s*x\s*H|L\s*x\s*B\s*x\s*H|dimensions?)[^|]{0,12}\bcm", re.I)


def dimensions_fiche(source: dict, poignee: str) -> list[float] | None:
    """Dimensions lues sur la page produit (KBS : « 64 x 31 x 41 · L x W x H in cm »)."""
    r = lien.recuperer(f"https://{source['hote']}{source.get('prefixe', '')}/products/{poignee}")
    page = re.sub(r"<[^>]+>", " | ", r.corps.decode("utf-8", "replace"))
    m = _DIM_FICHE.search(page)
    if not m:
        return None
    d = sorted((float(x.replace(",", ".")) for x in m.groups()), reverse=True)
    return d if d[0] > 0 else None

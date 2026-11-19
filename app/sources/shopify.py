"""Connecteur des boutiques Shopify : catalogue public `/products.json`, page par page.

Le pays de livraison est déclaré par le cookie `localization` (les boutiques à plusieurs
marchés rendent alors leurs prix dans la devise de ce pays). Une page de 250 produits par
requête, une pause entre deux pages, et l'attente demandée par le site en cas de refus 429.
"""
from __future__ import annotations

import json
import re
import time

from .. import lien, normalise as n

PAGE = 250
PAGES_MAX = 40


def lire(source: dict, pause: float = 1.5, progres=None) -> list[dict]:
    """Rend les offres normalisées d'une boutique. `source` : voir data/sources.json."""
    base = "https://" + source["hote"] + source.get("prefixe", "")
    entetes = {"Cookie": f"localization={source.get('pays', 'FR')}; cart_currency={source.get('devise', 'EUR')}"}
    produits = []
    for page in range(1, PAGES_MAX + 1):
        url = f"{base}/products.json?limit={PAGE}&page={page}"
        for essai in range(3):
            try:
                r = lien.recuperer(url, accept="application/json", entetes=entetes)
                break
            except lien.LienRefuse as e:
                if getattr(e, "statut", None) == 429 and essai < 2:
                    time.sleep(min(float(getattr(e, "attente", None) or 30), 120))
                    continue
                raise
        lot = json.loads(r.corps).get("products", [])
        produits += lot
        if progres:
            progres(len(produits))
        if len(lot) < PAGE:
            break
        time.sleep(pause)
    return [o for o in (offre(p, source) for p in produits) if o]


def offre(p: dict, source: dict) -> dict | None:
    variantes = p.get("variants") or [{}]
    v = next((x for x in variantes if x.get("available")), variantes[0])
    try:
        prix = round(float(v.get("price")), 2)
    except (TypeError, ValueError):
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
        "prix": prix, "devise": source.get("devise", "EUR"),
        "dispo": n.disponibilite(any(x.get("available") for x in variantes), tags, titre),
        "img": images[0].get("src") if images else None,
        "pieces": nb, "dims": dims,
        "type": n.type_briques(p.get("product_type") or "", tags, titre),
        "themes": n.themes(titre, tags, p.get("product_type") or ""),
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

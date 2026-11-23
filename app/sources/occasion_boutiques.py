"""Sets LEGO officiel d'occasion vendus par des boutiques spécialisées, catalogues publics lus sans clé.

- De BrickPlaats (Oss, Pays-Bas, site en français) : catalogue Shopify (`/products.json`), neuf et occasion
  mêlés ; l'occasion se lit dans l'option « État » ou « Conditie » de chaque variante (« D'occasion »,
  « Utilisé », « Gebruikt ») ; numéro du set lu dans le titre.
- Brickland (France) : sets reconditionnés, API publique de la boutique WooCommerce
  (`/wp-json/wc/store/v1/products`, catégorie 20 « Sets reconditionnés ») ; numéro du set dans le SKU ;
  état dans l'attribut « état du set » (boîte oui ou non, notice papier ou PDF).
Évaluées le 23/11/2026 (recherche des sources d'occasion : aucune API gratuite d'annonces achetables
depuis la France ; ces deux catalogues sont lisibles sans clé). Vendeurs professionnels de l'Union
européenne, prix en euros taxes comprises (vente aux particuliers), un exemplaire par référence en général.
Port vers la France : publié par aucune des deux (pages lues le 23/11/2026) ; chaque annonce porte
`port: None` et la raison dans `port_note`.

Un catalogue entier est lu en une passe (une pause entre deux pages, chaque page filtrée aussitôt : rien
du catalogue brut n'est gardé en mémoire), une fois par jour au plus ; seuls les sets dont le numéro est au
catalogue de l'outil sont gardés, hors annonces qui ne sont pas un set complet (`EXCLUS`). Une lecture
vide ou coupée à `PAGES_MAX` pages est une erreur : les annonces précédentes restent.
"""
from __future__ import annotations

import html
import json
import re
import time
from urllib.parse import quote, urlsplit

from .. import lien

PAUSE_S = 2.0
PAGES_MAX = 100                   # BrickPlaats : 40 pages de 250 produits le 23/11/2026
BRICKPLAATS = "https://brickplaats.fr/products.json?limit=250&page={}"
BRICKLAND = "https://www.brickland.fr/wp-json/wc/store/v1/products?per_page=100&category=20&page={}"
OCCASION = re.compile(r"(?<!un)(?<!in)(?<!non )(?<!non-)(?<!jamais )(?<!not )(?<!niet )(?<!on)"
                      r"(?:occasion|utilis|gebruikt|used|reconditionn)", re.I)
_NUMERO = re.compile(r"(?<![\d.,])(\d{4,6})(?![\d.,])")
PORT_NOTE = "port vers la France non publié par la boutique (pages lues le 23/11/2026)"
# annonce qui n'est pas un set complet : notice ou boîte seule, minifigurines, autocollants, pièces, copie
EXCLUS = re.compile(r"^\W*(notice|instructions?|manuel|bo[iî]te|box|minifig\w*|autocollants?|stickers?)\b|"
                    r"\b(notice|instructions?|bo[iî]te|box|minifig\w*|autocollants?|stickers?)\s+(seule?s?|uniquement|only)\b|"
                    r"\b(bo[iî]te vide|empty box|sans briques|planche d.autocollants|sticker sheet|pi[eè]ces? d[ée]tach[ée]es|"
                    r"lot de pi[eè]ces|compatible|moc|incompl[eè]te?s?|incomplete|pour pi[eè]ces|pi[eè]ces? manquantes?|manque \d+ pi[eè]ces?|"
                    r"missing pieces?|unvollst[aä]ndig\w*|defekt|teile fehlen|fehlende teile)\b", re.I)


class LectureIncomplete(ValueError):
    def __init__(self, message: str):
        super().__init__(message)
        self.public = message


def _json(url: str):
    return json.loads(lien.recuperer(url, accept="application/json").corps)


def numero_du_titre(titre: str, connus: set[str]) -> str | None:
    """Le seul numéro de 4 à 6 chiffres du titre qui est un set du catalogue ; aucun ou plusieurs : None."""
    vus = {m for m in _NUMERO.findall(titre or "") if m in connus}
    return vus.pop() if len(vus) == 1 else None


def _annonce(**k) -> dict:
    return {**k, "vendeur": "professionnel", "port": None, "port_note": PORT_NOTE}


def annonces_brickplaats(produits: list[dict], connus: set[str]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for p in produits:
        try:
            titre = html.unescape(p.get("title") or "")
            num = numero_du_titre(titre, connus)
            if not num or EXCLUS.search(titre) or not re.fullmatch(r"[^/?#\s]{1,200}", p.get("handle") or ""):
                continue
            options = p.get("options") or []
            i_etat = next((i for i, o in enumerate(options) if (o.get("name") or "").lower() in ("état", "etat", "conditie", "condition")), None)
            if i_etat is None:
                continue
            for v in p.get("variants") or []:
                etat = v.get(f"option{i_etat + 1}") or ""
                if not OCCASION.search(etat):
                    continue
                try:
                    prix = round(float(v["price"]), 2)
                except (KeyError, TypeError, ValueError):
                    continue
                variante = f"?variant={int(v['id'])}" if isinstance(v.get("id"), int) else ""
                annonce = _annonce(prix=prix, etat=etat.replace("’", "'"), dispo=bool(v.get("available")), titre=titre[:160],
                                   pays="NL", url=f"https://brickplaats.fr/products/{quote(p['handle'], safe='')}{variante}")
                out.setdefault(num, []).append(annonce)   # après la construction : jamais de liste vide
        except (AttributeError, TypeError, KeyError, ValueError):   # produit mal formé : ignoré, le reste du catalogue est lu
            continue
    return out


def annonces_brickland(produits: list[dict], connus: set[str]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for p in produits:
        try:
            nom = html.unescape(p.get("name") or "")
            num = re.sub(r"\D", "", p.get("sku") or "")
            if num not in connus:
                num = numero_du_titre(nom, connus)
            lienp = p.get("permalink") or ""
            hote = (urlsplit(lienp).hostname or "") if lienp.startswith("https://") and "\\" not in lienp else ""
            if not num or EXCLUS.search(nom) or hote not in ("brickland.fr", "www.brickland.fr"):
                continue
            prix = p.get("prices") or {}
            try:
                montant = round(int(prix["price"]) / 10 ** int(prix.get("currency_minor_unit", 2)), 2)
            except (KeyError, TypeError, ValueError):
                continue
            if prix.get("currency_code", "EUR") != "EUR":
                continue
            etat = next((", ".join(t.get("name") or "" for t in a.get("terms") or []) for a in p.get("attributes") or []
                         if "état" in (a.get("name") or "").lower()), "")
            out.setdefault(num, []).append(_annonce(
                prix=montant, etat="reconditionné" + (f" ({etat})" if etat else ""), dispo=bool(p.get("is_in_stock")),
                titre=nom[:160], pays="FR", url=lienp))
        except (AttributeError, TypeError, KeyError, ValueError):   # dont une adresse illisible
            continue
    return out


def lire_catalogue(gabarit: str, extraire, connus: set[str], pause: float = PAUSE_S, cle: str | None = None) -> dict[str, list[dict]]:
    """Toutes les pages d'un catalogue, chacune filtrée par `extraire` dès sa lecture, jusqu'à une page vide.
    Aucune page, ou PAGES_MAX atteint sans page vide : LectureIncomplete."""
    out: dict[str, list[dict]] = {}
    pages = 0
    for page in range(1, PAGES_MAX + 1):
        d = _json(gabarit.format(page))
        lot = d.get(cle) if cle and isinstance(d, dict) else d
        if not isinstance(lot, list) or not lot:
            break
        pages += 1
        for num, annonces in extraire(lot, connus).items():
            out.setdefault(num, []).extend(annonces)
        del lot, d
        time.sleep(pause)
    else:
        raise LectureIncomplete(f"catalogue de plus de {PAGES_MAX} pages : lecture coupée")
    if not pages:
        raise LectureIncomplete("catalogue vide")
    return out


LECTEURS = {
    "brickplaats": lambda connus, pause: lire_catalogue(BRICKPLAATS, annonces_brickplaats, connus, pause, "products"),
    "brickland": lambda connus, pause: lire_catalogue(BRICKLAND, annonces_brickland, connus, pause),
}

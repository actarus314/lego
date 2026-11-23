"""Offres et prix d'occasion des sets LEGO officiel.

Sans clé, chaque jour : boutiques spécialisées dont le catalogue public se lit sans clé
(`occasion_boutiques.py` : De BrickPlaats, Brickland), vendeurs professionnels.

Avec les clés du compte de l'administrateur, dans le `.env` (jamais dans le dépôt) :
- BrickLink : `BRICKLINK_CONSUMER_KEY`, `BRICKLINK_CONSUMER_SECRET`, `BRICKLINK_TOKEN`, `BRICKLINK_TOKEN_SECRET`
  (https://www.bricklink.com/v2/api/register_consumer.page). Requêtes signées OAuth 1.0 (HMAC-SHA1) ;
  guide des prix d'occasion (`new_or_used=U`), en euros, TVA comprise, vendeurs d'Europe : annonces en
  cours (`guide_type=stock`) et ventes des six derniers mois (`guide_type=sold`). 5000 appels par jour.
  Relu chaque semaine par set ; un set inconnu de BrickLink est noté « absent ».
- eBay : `EBAY_APP_ID`, `EBAY_CERT_ID` (jeu de clés « Production » de https://developer.ebay.com).
  Jeton d'application (client credentials), API Browse, place de marché française (`EBAY_FR`) : annonces
  à prix fixe d'occasion (`conditionIds` 3000) de la catégorie LEGO sets complets (19006), livrables en
  France, dont le titre porte « LEGO » et le numéro du set sans mot d'exclusion ; port vers la France et
  type de vendeur (particulier ou professionnel) quand eBay les donne. Lues à l'ouverture d'une fiche
  et gardées en mémoire 6 h au plus : la licence de l'API eBay (article 8.1) demande des annonces
  affichées à moins de 6 h du site et le retrait de celles qui ne sont plus publiques.
Sans clé, la source est éteinte et la vue Synchronisation le dit.

Relevés gardés dans `occasion.json` du dossier de données : {numéro: {source: {le, ...}}} (eBay excepté).

Connecteurs BrickLink et eBay écrits le 23/11/2026 d'après la documentation publique des deux API, sans
appel réel (clés absentes) : le premier relevé sur le serveur vaut essai
(`python -m app.sources.occasion essai 10294`).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import re
import secrets
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from .. import lien
from ..donnees import _ecrire, _lire
from ..lien import AGENT
from ..reglage import reglage
from . import occasion_boutiques
from .occasion_boutiques import LECTEURS as _LECTEURS

log = logging.getLogger("occasion")
PERIODE_J = 7                      # BrickLink : guide des prix relu chaque semaine
EBAY_FRAIS_S = 6 * 3600            # eBay : annonces lues à la demande, montrées 6 h au plus
EBAY_ECHEC_S = 600                 # eBay en échec (clés refusées, quota, panne) : pas de nouvel essai avant ce délai
BOUTIQUES_PERIODE_S = 20 * 3600    # boutiques d'occasion : catalogue relu une fois par jour au plus
BOUTIQUES_OCCASION = tuple(_LECTEURS)
RELEVES = "_releves"               # clé de occasion.json : date de la dernière lecture réussie de chaque boutique
PAUSE_S = 1.5
LOT_MAX = 150                      # BrickLink : sets relus par passage horaire au plus
DELAI = 15
BRICKLINK = "https://api.bricklink.com/api/store/v1"
EBAY_JETON = "https://api.ebay.com/identity/v1/oauth2/token"
EBAY_RECHERCHE = "https://api.ebay.com/buy/browse/v1/item_summary/search"
EBAY_CATEGORIE = "19006"           # LEGO : sets complets et packs
EXCLUS = occasion_boutiques.EXCLUS   # une seule liste pour eBay et les boutiques
VERROU = threading.Lock()


# ----- BrickLink : OAuth 1.0 -----
def _pct(s: str) -> str:
    return urllib.parse.quote(str(s), safe="~-._")


def signature_oauth1(methode: str, url: str, params: dict, consumer_secret: str, token_secret: str) -> str:
    """Signature HMAC-SHA1 (RFC 5849, 3.4) : `params` réunit paramètres de requête et paramètres oauth_*."""
    norm = "&".join(f"{k}={v}" for k, v in sorted((_pct(k), _pct(v)) for k, v in params.items()))
    base = "&".join([methode.upper(), _pct(url), _pct(norm)])
    cle = f"{_pct(consumer_secret)}&{_pct(token_secret)}"
    return base64.b64encode(hmac.new(cle.encode(), base.encode(), hashlib.sha1).digest()).decode()


def entete_oauth1(methode: str, url: str, requete: dict, cles: dict, nonce: str | None = None,
                  horodatage: int | None = None) -> str:
    o = {"oauth_consumer_key": cles["consumer_key"], "oauth_token": cles["token"], "oauth_signature_method": "HMAC-SHA1",
         "oauth_timestamp": str(horodatage or int(time.time())), "oauth_nonce": nonce or secrets.token_hex(16),
         "oauth_version": "1.0"}
    o["oauth_signature"] = signature_oauth1(methode, url, {**requete, **o}, cles["consumer_secret"], cles["token_secret"])
    return 'OAuth realm="", ' + ", ".join(f'{k}="{_pct(v)}"' for k, v in o.items())


def cles_bricklink() -> dict | None:
    c = {"consumer_key": reglage("BRICKLINK_CONSUMER_KEY", ""), "consumer_secret": reglage("BRICKLINK_CONSUMER_SECRET", ""),
         "token": reglage("BRICKLINK_TOKEN", ""), "token_secret": reglage("BRICKLINK_TOKEN_SECRET", "")}
    return c if all(c.values()) else None


def cles_ebay() -> tuple[str, str] | None:
    a, c = reglage("EBAY_APP_ID", ""), reglage("EBAY_CERT_ID", "")
    return (a, c) if a and c else None


class _SansRedirection(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):   # une redirection emporterait l'en-tête Authorization ailleurs
        return None


_OUVREUR = urllib.request.build_opener(_SansRedirection)


def _requete(url: str, entetes: dict, donnees: bytes | None = None) -> dict:
    r = urllib.request.Request(url, data=donnees, headers={"User-Agent": AGENT, "Accept": "application/json", **entetes})
    with _OUVREUR.open(r, timeout=DELAI) as rep:   # hôtes fixes des deux API, en https
        return json.loads(rep.read(2 * 1024 * 1024))


def guide_bricklink(numero: str, cles: dict, type_guide: str) -> dict:
    """Guide des prix d'occasion du set `numero` (sans suffixe), `type_guide` : stock ou sold."""
    if not re.fullmatch(r"\d{3,7}", numero or ""):
        raise SetAbsent(f"numéro {numero!r}")
    url = f"{BRICKLINK}/items/SET/{numero}-1/price"
    q = {"guide_type": type_guide, "new_or_used": "U", "region": "europe", "currency_code": "EUR", "vat": "Y"}
    d = _requete(url + "?" + urllib.parse.urlencode(q), {"Authorization": entete_oauth1("GET", url, q, cles)})
    meta = d.get("meta") or {}
    if meta.get("code") == 404:
        raise SetAbsent(numero)
    if meta.get("code") != 200:
        raise ValueError(f"BrickLink : {meta.get('code')} {meta.get('message') or ''} {meta.get('description') or ''}".strip())
    return d.get("data") or {}


def resume_bricklink(stock: dict, vendu: dict, numero: str) -> dict:
    f = lambda x: round(float(x), 2) if x not in (None, "") else None
    return {"annonces": {"min": f(stock.get("min_price")), "moyen": f(stock.get("avg_price")), "max": f(stock.get("max_price")),
                         "lots": stock.get("unit_quantity"), "exemplaires": stock.get("total_quantity")},
            "ventes_6_mois": {"moyen": f(vendu.get("avg_price")), "min": f(vendu.get("min_price")), "max": f(vendu.get("max_price")),
                              "exemplaires": vendu.get("total_quantity")},
            "devise": stock.get("currency_code") or "EUR", "tva": "comprise", "region": "Europe",
            "url": f"https://www.bricklink.com/v2/catalog/catalogitem.page?S={numero}-1#T=P"}


# ----- eBay -----
class JetonEbay:
    def __init__(self):
        self.valeur, self.fin = None, 0.0

    def obtenir(self, cles: tuple[str, str]) -> str:
        if self.valeur and time.time() < self.fin - 300:
            return self.valeur
        auth = base64.b64encode(f"{cles[0]}:{cles[1]}".encode()).decode()
        d = _requete(EBAY_JETON, {"Authorization": f"Basic {auth}", "Content-Type": "application/x-www-form-urlencoded"},
                     urllib.parse.urlencode({"grant_type": "client_credentials",
                                             "scope": "https://api.ebay.com/oauth/api_scope"}).encode())
        self.valeur, self.fin = d["access_token"], time.time() + int(d.get("expires_in") or 7200)
        return self.valeur


JETON = JetonEbay()


def titre_du_set(titre: str, numero: str) -> bool:
    """Annonce d'un set complet : « LEGO » et le numéro en mot entier, aucun mot d'exclusion (notice seule,
    boîte vide, minifigurines, compatible…)."""
    return bool(re.search(r"\blego\b", titre, re.I) and re.search(rf"(?<![\d-]){re.escape(numero)}(?![\d])", titre)
                and not EXCLUS.search(titre))


def annonces_ebay(numero: str, cles: tuple[str, str]) -> list[dict]:
    q = {"q": f"lego {numero}", "category_ids": EBAY_CATEGORIE, "limit": "50", "sort": "price",
         "filter": "conditionIds:{3000},buyingOptions:{FIXED_PRICE},deliveryCountry:FR,priceCurrency:EUR"}
    d = _requete(EBAY_RECHERCHE + "?" + urllib.parse.urlencode(q),
                 {"Authorization": f"Bearer {JETON.obtenir(cles)}", "X-EBAY-C-MARKETPLACE-ID": "EBAY_FR",
                  "X-EBAY-C-ENDUSERCTX": "contextualLocation=country%3DFR%2Czip%3D75001"})
    return [a for a in (annonce_ebay(x) for x in d.get("itemSummaries") or [] if titre_du_set(x.get("title") or "", numero)) if a]


def annonce_ebay(x: dict) -> dict | None:
    try:
        prix = round(float(x["price"]["value"]), 2)
    except (KeyError, TypeError, ValueError):
        return None
    port = None
    for o in x.get("shippingOptions") or []:
        try:
            v = round(float((o.get("shippingCost") or {})["value"]), 2)
        except (KeyError, TypeError, ValueError):
            continue
        port = v if port is None else min(port, v)
    vendeur = x.get("seller") or {}
    type_ = {"BUSINESS": "professionnel", "INDIVIDUAL": "particulier"}.get(x.get("sellerAccountType") or vendeur.get("sellerAccountType") or "")
    return {"prix": prix, "port": port, "etat": x.get("condition") or "Occasion", "titre": (x.get("title") or "")[:160],
            "vendeur": type_, "evaluations": vendeur.get("feedbackScore"), "satisfaction": vendeur.get("feedbackPercentage"),
            "pays": (x.get("itemLocation") or {}).get("country"), "url": x.get("itemWebUrl")}


def resume_ebay(annonces: list[dict]) -> dict:
    """Dix annonces au plus, port connu d'abord par total croissant, puis port inconnu par prix ;
    `min_port_compris` : la première, si son port est connu."""
    nombre = len(annonces)
    annonces = sorted(annonces, key=lambda a: (a["port"] is None, a["prix"] + (a["port"] or 0)))[:10]
    premier = annonces[0] if annonces and annonces[0]["port"] is not None else None
    return {"annonces": annonces, "nombre": nombre,
            "min_port_compris": round(premier["prix"] + premier["port"], 2) if premier else None, "devise": "EUR"}


# ----- relevé -----
class SetAbsent(ValueError):
    """La source ne connaît pas ce set (BrickLink : 404) : relevé « absent », pas une panne."""


class Occasion:
    def __init__(self, dossier: Path):
        self.fichier = Path(dossier) / "occasion.json"
        self.erreurs: dict[str, str] = {}
        self._ebay: dict[str, dict] = {}   # numéro : annonces eBay de moins de EBAY_FRAIS_S (mémoire seulement)
        self._ebay_echec = 0.0
        self._verrou_ebay = threading.Lock()

    def lire(self) -> dict:
        return _lire(self.fichier, {})

    def pour(self, numero: str | None, maintenant: float | None = None) -> dict:
        """Relevés d'occasion du set : BrickLink et boutiques (fichier), eBay lu à la demande et gardé
        EBAY_FRAIS_S au plus (licence de l'API eBay : annonces affichées à moins de 6 h du site)."""
        if not numero:
            return {}
        out = dict(self.lire().get(numero) or {}) if numero != RELEVES else {}
        for src in BOUTIQUES_OCCASION:   # catalogue d'une boutique relu chaque jour : au-delà de 2 jours, périmé
            if src in out and _age_s(out[src].get("le"), maintenant) > 2 * 86400:
                del out[src]
        eb = cles_ebay()
        if eb:
            t = maintenant or time.time()
            with self._verrou_ebay:   # une lecture à la fois : deux ouvertures du même set n'en font qu'une
                frais = self._ebay.get(numero)
                if (not frais or t - frais["t"] > EBAY_FRAIS_S) and t - self._ebay_echec >= EBAY_ECHEC_S:
                    try:
                        frais = {"t": t, "releve": {"le": _horodatage(), **resume_ebay(annonces_ebay(numero, eb))}}
                        self._ebay[numero] = frais
                        self.erreurs.pop("ebay", None)
                    except (urllib.error.URLError, OSError, ValueError, KeyError, TypeError, AttributeError) as e:
                        self.erreurs["ebay"] = f"{type(e).__name__} : {str(e)[:160]}"
                        self._ebay_echec = t
                        frais = None
            if frais and t - frais["t"] <= EBAY_FRAIS_S:
                out["ebay"] = frais["releve"]
        return out

    @staticmethod
    def actives() -> dict[str, bool]:
        return {"bricklink": cles_bricklink() is not None, "ebay": cles_ebay() is not None,
                **{src: True for src in BOUTIQUES_OCCASION}}

    def etat(self) -> dict:
        d = self.lire()
        out = {}
        d = {k: v for k, v in d.items() if k != RELEVES}
        for src, active in self.actives().items():
            if src == "ebay":
                out[src] = {"active": active, "lecture": "à l'ouverture d'une fiche, gardée 6 h", "sets_en_memoire": len(self._ebay),
                            "erreur": self.erreurs.get("ebay")}
                continue
            vus = [v[src] for v in d.values() if src in v
                   and (src not in BOUTIQUES_OCCASION or _age_s(v[src].get("le")) <= 2 * 86400)]   # comme pour()
            out[src] = {"active": active, "sets": len(vus),
                        "avec_offre": sum(1 for v in vus if not v.get("absent") and (
                            (v.get("annonces") or {}).get("lots") if src == "bricklink" else v.get("annonces"))),
                        "dernier": max((v["le"] for v in vus), default=None), "erreur": self.erreurs.get(src)}
        return out

    def relever(self, numeros: list[str], maintenant: float | None = None, pause: float = PAUSE_S,
                lot_max: int = LOT_MAX) -> dict:
        """BrickLink : sets relevés il y a plus de PERIODE_J jours, dans l'ordre donné. Rend {source: relus}.
        Trois échecs de suite (clés refusées, quota, panne) laissent la source jusqu'au passage suivant ;
        un set inconnu de la source est noté « absent » et relu une semaine plus tard."""
        maintenant = maintenant or time.time()
        limite = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(maintenant - PERIODE_J * 86400))
        bl = cles_bricklink()
        relus = {"bricklink": 0}
        if not bl:
            return relus
        with VERROU:
            d = self.lire()
            self.erreurs.pop("bricklink", None)
            de_suite = 0
            for num in [x for x in dict.fromkeys(numeros) if (d.get(x, {}).get("bricklink") or {}).get("le", "") < limite][:lot_max]:
                try:
                    r = resume_bricklink(guide_bricklink(num, bl, "stock"), guide_bricklink(num, bl, "sold"), num)
                except SetAbsent:
                    r = {"absent": True}
                except (urllib.error.URLError, OSError, ValueError, KeyError, TypeError, AttributeError) as e:
                    de_suite += 1
                    self.erreurs["bricklink"] = f"{type(e).__name__} : {str(e)[:160]}"
                    log.info("occasion BrickLink, set %s : %s", num, self.erreurs["bricklink"])
                    if de_suite >= 3:
                        break
                    time.sleep(pause)
                    continue
                de_suite = 0
                d.setdefault(num, {})["bricklink"] = {"le": _horodatage(), **r}
                relus["bricklink"] += 1
                if relus["bricklink"] % 20 == 0:   # écriture en cours de passage : un arrêt ne perd pas tout
                    _ecrire(self.fichier, d)
                time.sleep(pause)
            if relus["bricklink"]:
                _ecrire(self.fichier, d)
        return relus

    def relever_boutiques(self, numeros: list[str], pause: float = occasion_boutiques.PAUSE_S,
                          sources: list[str] | None = None) -> dict:
        """Catalogue entier de chaque boutique d'occasion (`sources` : celles-là seulement) ; les sets du
        catalogue de l'outil seuls gardés. Les annonces d'une boutique remplacent les précédentes (un set
        vendu disparaît) ; la date de la lecture réussie est gardée sous RELEVES."""
        connus, relus = set(numeros), {}
        if not connus:   # catalogue pas encore prêt : rien à rapprocher
            return relus
        for src, lire in occasion_boutiques.LECTEURS.items():
            if sources is not None and src not in sources:
                continue
            try:
                trouve = lire(connus, pause)
            except (lien.LienRefuse, OSError, ValueError, KeyError, TypeError, AttributeError) as e:
                self.erreurs[src] = f"{getattr(e, 'public', type(e).__name__)}"
                log.info("occasion %s : %s", src, self.erreurs[src])
                continue
            self.erreurs.pop(src, None)
            with VERROU:
                d = self.lire()
                for k, v in d.items():
                    if k != RELEVES:
                        v.pop(src, None)
                le = _horodatage()
                d.setdefault(RELEVES, {})[src] = le
                for num, annonces in trouve.items():
                    annonces = sorted(annonces, key=lambda a: (not a["dispo"], a["prix"]))
                    d.setdefault(num, {})[src] = {"le": le, "annonces": annonces[:10], "nombre": len(annonces)}
                _ecrire(self.fichier, {k: v for k, v in d.items() if v})
            relus[src] = len(trouve)
        return relus

    def boutiques_a_relire(self, maintenant: float | None = None) -> list[str]:
        """Boutiques d'occasion dont la dernière lecture réussie (même sans aucun set rapproché) date de
        BOUTIQUES_PERIODE_S au moins, redémarrage compris ; chacune à part : une boutique en panne est
        retentée au passage horaire suivant."""
        lues = self.lire().get(RELEVES) or {}
        return [src for src in BOUTIQUES_OCCASION if _age_s(lues.get(src), maintenant) >= BOUTIQUES_PERIODE_S]

    def demarrer(self, numeros) -> None:
        """Passage horaire sur `numeros()` (numéros des sets LEGO officiel, sélection d'abord) : boutiques
        d'occasion échues (une lecture par jour au plus), puis BrickLink si ses clés sont posées (sets échus)."""
        def boucle():
            time.sleep(300)
            while True:
                try:
                    nums = numeros()
                    dues = self.boutiques_a_relire()
                    r = self.relever_boutiques(nums, sources=dues) if dues else {}
                    r.update(self.relever(nums))
                    log.info("occasion : %s", r)
                except Exception:
                    log.exception("relevé de l'occasion en échec")
                time.sleep(3600)   # chaque heure, chaque source ne relit que ce qui est échu

        threading.Thread(target=boucle, name="occasion", daemon=True).start()


def _horodatage() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def _age_s(le: str | None, maintenant: float | None = None) -> float:
    try:
        return (maintenant or time.time()) - time.mktime(time.strptime(le, "%Y-%m-%dT%H:%M:%S"))
    except (TypeError, ValueError):   # date absente ou illisible : relevé périmé
        return float("inf")


if __name__ == "__main__":   # essai sur le serveur : python -m app.sources.occasion essai 10294
    logging.basicConfig(level="INFO")
    if len(sys.argv) == 3 and sys.argv[1] == "essai":
        num = sys.argv[2]
        bl, eb = cles_bricklink(), cles_ebay()
        print("BrickLink :", json.dumps(resume_bricklink(guide_bricklink(num, bl, "stock"), guide_bricklink(num, bl, "sold"), num),
                                       ensure_ascii=False) if bl else "clés absentes")
        print("eBay :", json.dumps(resume_ebay(annonces_ebay(num, eb)), ensure_ascii=False)[:2000] if eb else "clés absentes")
    else:
        print("usage : python -m app.sources.occasion essai <numéro du set>")

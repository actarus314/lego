"""Cache local des photos des sets, servi par le service derrière son authentification.

Deux tailles par photo (décision du 23/11/2026) :
- la vignette (400 px de large), téléchargée pour toutes les photos du catalogue et de la sélection
  par le passage horaire de `photos.py` ;
- la grande (1200 px), téléchargée à la première demande (ouverture d'une fiche) et gardée.

La taille se demande au site de la photo par son paramètre ou ses tailles publiées quand il en a
(`VARIANTES` : Shopify `width=`, Rebrickable, Brickset) : aucun recodage dans le service. Un site sans
paramètre donne sa photo d'origine, gardée une fois (vignette, qui sert aussi de grande), sous
`ORIGINE_MAX` octets. Formats gardés : JPEG, PNG, GIF, WebP (jamais SVG ; l'AVIF n'est pas demandé).

Fichiers : `photos/<empreinte>-v.<format>` (vignette) et `photos/<empreinte>-g.<format>` (grande) du
dossier de données ; l'empreinte est le début du SHA-256 de l'adresse d'origine. La date de
modification d'une grande est celle de sa dernière demande : au-delà du plafond (`PHOTOS_QUOTA_MO`,
2048 par défaut), les grandes les moins demandées partent les premières ; si les vignettes seules
dépassent le plafond, plus aucune vignette n'est téléchargée (« plein » dans la vue Synchronisation). Une
photo oubliée par `photos.py` (absente du catalogue depuis 30 jours) perd ses deux fichiers.

Route : `GET /photo?u=<adresse d'origine>&l=<largeur affichée>` ; largeur de 400 ou moins :
vignette, au-delà : grande. Seules les adresses du catalogue et de la sélection sont servies
(le service n'est pas un relais ouvert). Téléchargements à la demande : six à la fois au plus, une demi-
seconde au moins entre deux sur un même site ; un échec n'est pas retenté avant une heure.

Une photo que le cache ne peut pas garder (trop lourde, format non gardé, disque plein) n'est pas
une photo morte : `photos.py` la vérifie alors comme avant (4 premiers Ko) et ne retente le cache
qu'après `NON_GARDABLE_J` jours.
"""
from __future__ import annotations

import hashlib
import logging
import os
import threading
import time
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from . import lien
from .logos import _format
from .reglage import reglage

log = logging.getLogger("cache_photos")
VIGNETTE_PX = 400
GRANDE_PX = 1200
ORIGINE_MAX = 3 * 1024 * 1024      # photo d'un site sans paramètre de taille : au-delà, non gardée
FORMATS = {"jpg": "image/jpeg", "png": "image/png", "gif": "image/gif", "webp": "image/webp"}  # jamais de SVG
ACCEPTE = "image/webp,image/jpeg,image/png,image/gif;q=0.9"
NON_GARDABLE_J = 7                 # photo non gardable : nouvel essai du cache après ce délai
ECHEC_DEMANDE_S = 3600             # téléchargement à la demande en échec : pas de nouvel essai avant ce délai
PAUSE_SITE_S = 0.5                 # entre deux téléchargements à la demande sur un même site
VERROU = threading.Lock()


def _largeur_shopify(url: str, px: int) -> str:
    p = urlsplit(url)
    q = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True) if k not in ("width", "height", "crop")]
    return urlunsplit((p.scheme, p.netloc, p.path, urlencode(q + [("width", str(px))]), ""))


def _taille_rebrickable(url: str, px: int) -> str | None:
    """cdn.rebrickable.com/media/sets/X.jpg : vignettes à tailles fixes (400x400p, 1000x800p relevées le 23/11/2026)."""
    p = urlsplit(url)
    if not p.path.startswith("/media/sets/"):
        return None
    taille = "400x400p" if px <= VIGNETTE_PX else "1000x800p"
    return urlunsplit((p.scheme, p.netloc, "/media/thumbs/sets/" + p.path[len("/media/sets/"):] + f"/{taille}.jpg", "", ""))


def _taille_brickset(url: str, px: int) -> str | None:
    """images.brickset.com/sets/{small,images,large}/X.jpg : 240 px, environ 600 px, pleine taille (23/11/2026)."""
    p = urlsplit(url)
    for dossier in ("/sets/images/", "/sets/large/", "/sets/small/"):
        if p.path.startswith(dossier):
            cible = "/sets/small/" if px <= VIGNETTE_PX else "/sets/images/"
            return urlunsplit((p.scheme, p.netloc, cible + p.path[len(dossier):], "", ""))
    return None


# site de la photo : fonction qui rend l'adresse à la largeur demandée
VARIANTES = {"cdn.shopify.com": _largeur_shopify, "cdn.rebrickable.com": _taille_rebrickable,
             "images.brickset.com": _taille_brickset}


def variante(url: str, px: int) -> tuple[str, bool]:
    """(adresse à télécharger, taille demandée au site) ; sans paramètre connu : l'adresse d'origine."""
    hote = (urlsplit(url).hostname or "").lower()
    for site, f in VARIANTES.items():
        if hote == site or hote.endswith("." + site):
            cible = f(url, px)   # None : chemin sans tailles connues sur ce site
            if cible:
                return cible, True
    return url, False


def empreinte(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()[:32]


def quota_octets() -> int:
    try:
        mo = int(reglage("PHOTOS_QUOTA_MO", "2048"))
    except ValueError:
        mo = 2048
    return max(mo, 1) * 1024 * 1024


class PhotoIllisible(ValueError):
    """Réponse qui n'est pas une photo gardable. `page` : le site a rendu une page à la place."""

    def __init__(self, message: str, page: bool = False):
        super().__init__(message)
        self.public, self.page = message, page


class CacheLocal(Exception):
    """Écriture impossible dans le dossier du cache (disque plein, droits) : défaut du serveur, pas de la photo."""

    def __init__(self, message: str):
        super().__init__(message)
        self.public = message


class CachePhotos:
    _demandes = threading.BoundedSemaphore(6)   # téléchargements à la demande simultanés

    def __init__(self, dossier: Path):
        self.dossier = Path(dossier) / "photos"
        self.plein = False   # vignettes seules au-delà du plafond : plus de téléchargement de vignette
        self.non_gardables: dict[str, float] = {}   # adresse : instant du constat (photo que le cache ne garde pas)
        self._echecs: dict[str, float] = {}          # adresse et taille : instant de l'échec à la demande
        self._dernier_site: dict[str, float] = {}
        self._site = threading.Lock()

    # ----- fichiers -----
    def _fichier(self, url: str, taille: str) -> Path | None:
        h = empreinte(url)
        if not self.dossier.is_dir():
            return None
        for ext in FORMATS:
            p = self.dossier / f"{h}-{taille}.{ext}"
            if p.is_file():
                return p
        return None

    def present(self, url: str, taille: str = "v") -> bool:
        return self._fichier(url, taille) is not None

    def gardable(self, url: str, maintenant: float | None = None) -> bool:
        t = self.non_gardables.get(url)
        return t is None or (maintenant or time.time()) - t >= NON_GARDABLE_J * 86400

    def _garder(self, url: str, taille: str, corps: bytes, type_: str = "") -> Path:
        fmt = _format(corps)
        if fmt not in FORMATS:
            page = type_.split(";")[0].strip().lower().startswith(("text/", "application/json", "application/xhtml"))
            raise PhotoIllisible(f"page à la place de l'image ({type_})" if page and not fmt
                                 else f"format non gardé ({fmt or 'inconnu'})", page=page and not fmt)
        h = empreinte(url)
        cible = self.dossier / f"{h}-{taille}.{fmt}"
        try:
            self.dossier.mkdir(parents=True, exist_ok=True)
            tmp = cible.with_suffix(cible.suffix + ".tmp")
            tmp.write_bytes(corps)
            os.replace(tmp, cible)
            for ext in FORMATS:   # même photo sous un autre format (le site a changé de format) : retirée
                ancien = self.dossier / f"{h}-{taille}.{ext}"
                if ext != fmt and ancien.is_file():
                    ancien.unlink()
        except OSError as e:
            raise CacheLocal(f"écriture du cache impossible ({type(e).__name__})") from e
        return cible

    # ----- téléchargement -----
    def telecharger(self, url: str, taille: str) -> tuple[Path, dict]:
        """Télécharge la vignette (« v ») ou la grande (« g ») de `url` et la garde ; rend le fichier et
        les en-têtes lus (`lien.ENTETES_LUS`). Un site sans paramètre de taille ne donne qu'une photo,
        gardée en vignette. Lève lien.LienRefuse, OSError (réseau), PhotoIllisible ou CacheLocal en cas
        d'échec : rien n'est gardé."""
        cible, native = variante(url, VIGNETTE_PX if taille == "v" else GRANDE_PX)
        if not native:
            taille = "v"
        r = lien.recuperer(cible, accept=ACCEPTE, entetes={"Accept-Encoding": "identity"}, max_octets=ORIGINE_MAX)
        if len(r.corps) >= ORIGINE_MAX:
            raise PhotoIllisible("photo trop lourde")
        with VERROU:
            chemin = self._garder(url, taille, r.corps, r.type or "")
        return chemin, r.entetes or {}

    def _a_la_demande(self, url: str, taille: str) -> Path | None:
        cle = f"{taille}:{url}"
        if time.time() - self._echecs.get(cle, 0) < ECHEC_DEMANDE_S:
            return None
        site = urlsplit(url).hostname or ""
        with CachePhotos._demandes:
            with self._site:   # une demi-seconde au moins entre deux téléchargements sur un même site
                attente = self._dernier_site.get(site, 0) + PAUSE_SITE_S - time.time()
                self._dernier_site[site] = time.time() + max(attente, 0)
            if attente > 0:
                time.sleep(attente)
            try:
                return self.telecharger(url, taille)[0]
            except (lien.LienRefuse, OSError, ValueError, CacheLocal) as e:
                self._echecs[cle] = time.time()
                log.info("photo %s non téléchargée (%s) : %s", taille, getattr(e, "public", type(e).__name__), url)
                return None

    def servir(self, url: str, largeur: int) -> tuple[bytes, str] | None:
        """Corps et type de la photo à afficher à `largeur` px ; télécharge à la demande ce qui manque.
        La grande se replie sur la vignette quand le site ne la donne pas. None : aucune photo."""
        taille = "v" if largeur <= VIGNETTE_PX or not variante(url, GRANDE_PX)[1] else "g"
        chemin = self._fichier(url, taille)
        if chemin is None and not (taille == "v" and self.plein):
            chemin = self._a_la_demande(url, taille)
        if chemin is None and taille == "g":
            chemin = self._fichier(url, "v")
        if chemin is None:
            return None
        try:
            if "-g." in chemin.name:
                os.utime(chemin)   # dernière demande : ordre de purge des grandes
            return chemin.read_bytes(), FORMATS[chemin.suffix[1:]]
        except OSError:   # fichier retiré par l'entretien entre-temps
            return None

    # ----- entretien -----
    def fichiers(self) -> list[os.DirEntry]:
        if not self.dossier.is_dir():
            return []
        return [e for e in os.scandir(self.dossier) if e.is_file() and not e.name.endswith(".tmp")]

    def resume(self) -> dict:
        v = g = octets = 0
        for e in self.fichiers():
            octets += e.stat().st_size
            if "-v." in e.name:
                v += 1
            elif "-g." in e.name:
                g += 1
        return {"vignettes": v, "grandes": g, "octets": octets, "quota_octets": quota_octets(), "plein": self.plein,
                "non_gardables": len(self.non_gardables)}

    def entretenir(self, connues: set[str]) -> dict:
        """Retire les fichiers des photos inconnues (oubliées), puis applique le plafond. Rend
        {retirees, purgees_grandes, octets}."""
        gardees = {empreinte(u) for u in connues}
        retirees = purgees = 0
        with VERROU:
            restants = []
            for e in self.fichiers():
                if e.name.split("-", 1)[0] not in gardees:
                    try:
                        os.unlink(e.path)
                        retirees += 1
                    except OSError:
                        pass
                else:
                    restants.append(e)
            total = sum(e.stat().st_size for e in restants)
            plafond = quota_octets()
            if total > plafond:
                grandes = sorted((e for e in restants if "-g." in e.name), key=lambda e: e.stat().st_mtime)
                for e in grandes:
                    if total <= plafond * 0.9:
                        break
                    taille = e.stat().st_size
                    try:
                        os.unlink(e.path)
                        total -= taille
                        purgees += 1
                    except OSError:
                        pass
            self.plein = total > plafond
        if self.plein:
            log.warning("cache des photos plein : %s octets pour un plafond de %s", total, plafond)
        self.non_gardables = {u: t for u, t in self.non_gardables.items() if u in connues}
        return {"retirees": retirees, "purgees_grandes": purgees, "octets": total}

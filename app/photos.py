"""Vérification des photos des sets, par le service, en continu.

Chaque adresse de photo du catalogue et de la sélection est essayée (4 Ko au plus, sans référent,
comme le navigateur de la page, qui n'en envoie pas). Une photo est écartée, et l'index montre la
suivante du set :
- quand son site en interdit l'affichage ailleurs (Cross-Origin-Resource-Policy) ou quand elle
  n'est pas en https (la page n'accepte que des images https) : dès le premier constat ;
- quand le site la dit absente (404, 410) ou rend une page à la place de l'image : au second
  constat, à un jour d'écart au moins ;
- après des échecs passagers (délai, erreur du site) trois jours différents.
Un refus (401, 403) ne distingue pas un blocage des robots d'un refus au navigateur : la photo est
gardée et comptée « non vérifiable ». Une photo trouvée est revérifiée après 30 jours, une photo
écartée ou non vérifiable après 7 jours. Un site qui refuse ou échoue trois fois de suite, ou qui
répond 429, est laissé jusqu'au passage suivant ; un passage dure 20 minutes au plus. Une adresse
absente du catalogue depuis 30 jours est oubliée.

Le même passage remplit le cache local des photos (`cache_photos.py`) : une photo non écartée dont la
vignette manque est essayée en téléchargeant sa vignette entière, qui vaut vérification ; une photo
oubliée perd ses fichiers du cache, et le plafond du cache s'applique en fin de passage.
"""
from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit

from . import lien
from .cache_photos import CacheLocal, CachePhotos, PhotoIllisible
from .donnees import _ecrire, _lire
from .logos import _format

log = logging.getLogger("photos")
VALIDE_J = 30            # photo trouvée : nouvel essai après ce délai
REESSAI_J = 7            # photo écartée ou non vérifiable : nouvel essai après ce délai
CONFIRMATION_H = 20      # écart minimal entre deux constats d'absence, ou entre deux jours d'échec passager
PASSAGERS_MAX = 3        # jours d'échec passager avant d'écarter la photo
OUBLI_J = 30             # adresse absente du catalogue depuis ce délai : oubliée
PAUSE_S = 0.5            # pause entre deux essais sur un même site (le débit commun du service, lien.py, s'y ajoute)
LOT_MAX = 1200           # essais par passage (un passage par heure) : premier remplissage du cache en 6 h environ
DUREE_MAX_S = 20 * 60    # durée maximale d'un passage
ECHECS_SITE_MAX = 3      # refus ou échecs de suite sur un site avant de le laisser jusqu'au passage suivant
ABSENTE = (404, 410)
REFUS = (401, 403, 451)
PAGES = ("text/", "application/json", "application/xhtml")
VERROU = threading.Lock()


def _instant(texte: str | None) -> float:
    return time.mktime(time.strptime(texte, "%Y-%m-%dT%H:%M:%S")) if texte else 0.0


def _horodatage() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def essayer(url: str, cache: CachePhotos | None = None) -> tuple[str, str]:
    """Rend (résultat, motif). Résultats : « ok » ; « interdite » (écartée dès ce constat) ;
    « absente » (à confirmer) ; « refus » (non vérifiable) ; « passager » (délai, erreur du site) ;
    « limite » (429 : site laissé jusqu'au passage suivant, photo inchangée). Avec `cache`, la
    vignette est téléchargée et gardée (essai complet) ; sans, les 4 premiers Ko seulement."""
    if not url.startswith("https://"):
        return "interdite", "adresse non https, refusée par la page"
    try:
        if cache is not None:
            entetes = cache.telecharger(url, "v")[1]
            r = lien.Reponse(url, 200, "image/*", b"", entetes=entetes)
        else:
            r = lien.recuperer(url, accept="image/avif,image/webp,image/*,*/*;q=0.5",
                               entetes={"Range": "bytes=0-4095", "Accept-Encoding": "identity"},
                               statuts=(200, 206), max_octets=4096)
    except (PhotoIllisible, CacheLocal) as e:
        if isinstance(e, PhotoIllisible) and e.page:
            return "absente", e.public
        # photo que le cache ne garde pas (trop lourde, format non gardé) ou écriture impossible : défaut
        # du cache, pas de la photo, vérifiée alors comme sans cache ; le cache attend NON_GARDABLE_J jours
        cache.non_gardables[url] = time.time()
        log.info("photo non gardée en cache (%s) : %s", e.public, url)
        return essayer(url)
    except lien.LienRefuse as e:
        statut = getattr(e, "statut", None)
        if statut in ABSENTE:
            return "absente", f"le site a répondu {statut}"
        if statut == 429:
            return "limite", "le site a répondu 429"
        if statut in REFUS:
            return "refus", f"le site a répondu {statut}"
        if statut is None and "adresse refusée" in e.public:
            return "interdite", e.public
        return "passager", e.public
    except (OSError, ValueError) as e:  # délai, connexion coupée, réponse illisible
        return "passager", type(e).__name__
    corp = ((r.entetes or {}).get("cross-origin-resource-policy") or "").strip().lower()
    if corp in ("same-origin", "same-site"):
        return "interdite", f"affichage interdit hors du site ({corp})"
    type_ = (r.type or "").split(";")[0].strip().lower()
    if cache is None and type_.startswith(PAGES) and not _format(r.corps):
        return "absente", f"page à la place de l'image ({type_})"
    return "ok", ""


class Photos:
    def __init__(self, dossier: Path):
        self.fichier = Path(dossier) / "photos.json"
        self.cache = CachePhotos(Path(dossier))

    def etat(self) -> dict:
        return _lire(self.fichier, {})

    def ecartees(self) -> set[str]:
        return {u for u, e in self.etat().items() if e.get("etat") == "morte"}

    def douteuses(self) -> set[str]:
        """Photos dites absentes une fois, en attente du second constat : placées après les autres."""
        return {u for u, e in self.etat().items() if e.get("etat") == "doute"}

    def resume(self) -> dict:
        compte: dict[str, int] = {}
        for e in self.etat().values():
            compte[e.get("etat")] = compte.get(e.get("etat"), 0) + 1
        return {"total": sum(compte.values()), "trouvees": compte.get("ok", 0),
                "ecartees": compte.get("morte", 0), "non_verifiables": compte.get("refus", 0),
                "cache": self.cache.resume()}

    def a_cacher(self, url: str, e: dict | None) -> bool:
        """Photo non écartée dont la vignette manque au cache (cache non plein)."""
        return (not self.cache.plein and (e or {}).get("etat") != "morte" and self.cache.gardable(url)
                and not self.cache.present(url))

    @staticmethod
    def _passager_recent(e: dict | None, maintenant: float) -> bool:
        e = e or {}
        return bool(e.get("passager_le")) and maintenant - _instant(e["passager_le"]) < CONFIRMATION_H * 3600

    @staticmethod
    def a_essayer(e: dict | None, maintenant: float) -> bool:
        e = e or {}
        if Photos._passager_recent(e, maintenant):
            return False   # échec passager récent : nouvel essai le lendemain
        if not e.get("essai"):
            return True
        delai_h = {"ok": VALIDE_J * 24, "morte": REESSAI_J * 24, "refus": REESSAI_J * 24,
                   "doute": CONFIRMATION_H}.get(e.get("etat"), 0)
        return maintenant - _instant(e["essai"]) >= delai_h * 3600 - 3600

    @staticmethod
    def suivant(ancien: dict, resultat: str, motif: str, maintenant: float) -> dict:
        """Nouvel état d'une photo après un essai."""
        texte = _horodatage()
        motif = motif[:200]
        if resultat == "limite":
            return dict(ancien)
        if resultat == "ok":
            return {"etat": "ok", "essai": texte}
        if resultat == "interdite":
            return {"etat": "morte", "essai": texte, "motif": motif}
        if resultat == "refus":
            return {"etat": "refus", "essai": texte, "motif": motif}
        if resultat == "absente":
            premier = ancien.get("premier_constat") if ancien.get("etat") in ("doute", "morte") else None
            if premier and maintenant - _instant(premier) >= CONFIRMATION_H * 3600:
                return {"etat": "morte", "essai": texte, "motif": motif, "premier_constat": premier}
            return {"etat": "morte" if ancien.get("etat") == "morte" else "doute", "essai": texte,
                    "motif": motif, "premier_constat": premier or texte}
        # passager : l'état et la date du dernier essai abouti restent ; un jour d'échec de plus
        jours = int(ancien.get("passagers") or 0) + 1
        if jours >= PASSAGERS_MAX:
            return {"etat": "morte", "essai": texte, "motif": motif}
        return {**ancien, "passagers": jours, "passager_le": texte, "motif": motif}

    def actualiser(self, urls: list[str], lot_max: int = LOT_MAX, pause: float = PAUSE_S,
                   duree_max: float = DUREE_MAX_S) -> dict:
        """Essaie les photos jamais essayées ou échues, dans l'ordre donné (premières photos d'abord).
        Rend {essayees, ecartees}."""
        with VERROU:
            lu = self.etat()
            etat = {u: dict(e) for u, e in lu.items()}
            debut = time.time()
            jour = time.strftime("%Y-%m-%d")
            urls = [u for u in dict.fromkeys(urls) if u]
            for u in urls:   # jour du dernier passage où l'adresse est au catalogue
                if u in etat:
                    etat[u]["vu"] = jour
            # photo à essayer selon son état, ou photo trouvée dont la vignette manque au cache
            a_faire = [u for u in urls if self.a_essayer(etat.get(u), debut)
                       or ((etat.get(u) or {}).get("etat") == "ok" and self.a_cacher(u, etat.get(u))
                           and not self._passager_recent(etat.get(u), debut))][:lot_max]
            dernier_par_site: dict[str, float] = {}
            echecs_site: dict[str, int] = {}
            essayees = ecartees = 0
            for url in a_faire:
                if time.time() - debut > duree_max:
                    break
                site = urlsplit(url).hostname or ""
                if echecs_site.get(site, 0) >= ECHECS_SITE_MAX:
                    continue
                attente = dernier_par_site.get(site, 0) + pause - time.time()
                if attente > 0:
                    time.sleep(attente)
                resultat, motif = essayer(url, self.cache if self.a_cacher(url, etat.get(url)) else None)
                dernier_par_site[site] = time.time()
                if resultat == "limite":
                    echecs_site[site] = ECHECS_SITE_MAX
                elif resultat in ("refus", "passager"):
                    echecs_site[site] = echecs_site.get(site, 0) + 1
                else:
                    echecs_site[site] = 0
                ancien = etat.get(url) or {}
                entree = self.suivant(ancien, resultat, motif, time.time())
                if entree:
                    entree["vu"] = jour
                    etat[url] = entree
                if entree.get("etat") == "morte" and ancien.get("etat") != "morte":
                    log.info("photo écartée : %s (%s)", url, entree.get("motif"))
                    ecartees += 1
                essayees += 1
            limite = time.strftime("%Y-%m-%d", time.localtime(debut - OUBLI_J * 86400))
            for u in [u for u, e in etat.items() if (e.get("vu") or jour) < limite]:
                del etat[u]   # absente du catalogue depuis OUBLI_J jours
            if etat != lu:   # sans changement, pas d'écriture : l'index n'est pas reconstruit pour rien
                _ecrire(self.fichier, etat)
        # copie gardée seulement pour une photo non écartée (une photo écartée parce que son site en interdit
        # l'affichage ailleurs n'est pas servie non plus par /photo)
        cache = self.cache.entretenir({u for u in set(etat) | set(urls) if (etat.get(u) or {}).get("etat") != "morte"})
        return {"essayees": essayees, "ecartees": ecartees, **cache}

    def demarrer(self, adresses) -> None:
        """Passage toutes les heures sur `adresses()` (liste ordonnée des photos à vérifier)."""
        def boucle():
            time.sleep(120)
            while True:
                try:
                    r = self.actualiser(adresses())
                    if r["essayees"]:
                        log.info("photos : %s essayées, %s écartées", r["essayees"], r["ecartees"])
                except Exception:
                    log.exception("vérification des photos en échec")
                time.sleep(3600)
        threading.Thread(target=boucle, name="photos", daemon=True).start()


def appliquer(sets: list[dict], ecartees: set[str], douteuses: set[str] = frozenset()) -> None:
    """Retire des sets les photos écartées et place les douteuses après les autres : la première
    photo restante devient la photo du set."""
    if not ecartees and not douteuses:
        return
    for s in sets:
        toutes = list(dict.fromkeys(([s["img"]] if s.get("img") else []) + (s.get("images") or [])))
        if not any(u in ecartees or u in douteuses for u in toutes):
            continue
        restantes = [u for u in toutes if u not in ecartees and u not in douteuses] + \
                    [u for u in toutes if u in douteuses and u not in ecartees]
        s["img"] = restantes[0] if restantes else None
        if len(restantes) > 1:
            s["images"] = restantes
        else:
            s.pop("images", None)


def adresses(sets: list[dict]) -> tuple[list[str], list[str]]:
    """(photos principales, photos des galeries) des sets, avant tout retrait."""
    principales = [s["img"] for s in sets if s.get("img")]
    galeries = [u for s in sets for u in (s.get("images") or [])]
    return principales, galeries

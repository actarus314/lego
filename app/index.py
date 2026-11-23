"""Index du moteur de recherche : offres de chaque source, regroupées en sets.

Chaque source a son fichier `sources/<id>.json` dans le dossier de données (offres du dernier
passage réussi, date de première apparition de chaque produit). Le catalogue éditorial
(`data/catalogue.json` : noms français, tests indépendants, verdicts, sets LEGO officiel relevés
à la main) se superpose par marque et numéro, ou par adresse de la boutique.
"""
from __future__ import annotations

import json
import logging
import re
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit

from . import normalise as n
from .tests_auto import Tests
from .photos import Photos, adresses as adresses_photos, appliquer as appliquer_photos
from .donnees import _ecrire, _lire, dans
from .historique import Historique

TYPES = ("classique", "technic")   # types de briques connus (la page déclare les mêmes, avec libellé et icône)

RACINE = Path(__file__).resolve().parent.parent
log = logging.getLogger("index")
VERROU = threading.RLock()
DISPO_RANG = {"vente": 0, "precommande": 1, "epuise": 2}
# Pour classer seulement : une offre dont le port n'est pas relevé compte ce port (le plus élevé des
# ports relevés), pour ne pas passer devant une offre au port connu ; l'écran affiche « port non relevé ».
PORT_INCONNU = 7.0
# Champs d'offre omis du catalogue quand ils sont vides : prix barré et résumé de l'historique (historique.py).
OPTIONNELS = ("barre", "bas30", "jours_suivis", "avant_remise", "avant_remise_j")
# Ordre de préférence pour le nom affiché d'un set vendu par plusieurs boutiques (anglais avant allemand).
PREFERENCE_NOM = ["editorial", "kbs", "mouldkingcorp", "bricksvalue", "bausteinreich"]


def livraison_revendeurs() -> dict:
    return json.loads((RACINE / "data" / "livraison.json").read_text("utf-8"))["revendeurs"]


def port_revendeur(regle: dict | None, prix: float) -> tuple[float | None, bool]:
    """(port, estimé) d'une offre selon les conditions du revendeur ; (None, False) si inconnu."""
    if not regle:
        return None, False
    if regle.get("gratuit_des") is not None and prix >= regle["gratuit_des"]:
        return 0.0, bool(regle.get("estime"))
    if regle.get("port") is not None:
        return regle["port"], bool(regle.get("estime"))
    return None, False


SERIE_MIN, SERIE_PART = 10, 0.9


def _serie(s: dict) -> tuple[str, str] | None:
    m = re.match(r"[A-Z]*(\d{2})\d{2,}", (s.get("numero") or "").upper())
    return (s["marque"], m.group(1)) if m else None


def types_photos() -> dict[str, str]:
    """Types relevés sur les photos des produits (`data/types_photos.json`) : étalon du tri, appliqué aux
    sets qu'il couvre avant toute règle. Fichier absent ou illisible : aucun type, journalisé."""
    try:
        brut = json.loads((RACINE / "data" / "types_photos.json").read_text("utf-8"))
    except FileNotFoundError:
        return {}
    except ValueError:
        log.exception("data/types_photos.json illisible : types des photos ignorés")
        return {}
    return {k: v for k, v in (brut.get("sets") or {}).items() if isinstance(k, str) and v in ("technic", "classique")}


THEME_MIN, THEME_PART = 3, 0.5


def themes_par_defaut(sets: list[dict]) -> None:
    """Thème estimé des sets dont ni le nom, ni les étiquettes, ni Rebrickable ne donnent de sujet, marqué
    dans `themes_estimes` par sa méthode : thème par défaut de l'univers (« univers ») ; sinon thème le plus
    fréquent de la série de la marque (marque et deux premiers chiffres du numéro), s'il porte au moins la
    moitié de ses sets à thème et trois sets au moins (« série ») ; sinon le plus fréquent de la marque (« marque »)."""
    def compte(groupe: list[dict]) -> list[tuple[str, int]]:
        c: dict[str, int] = {}
        for s in groupe:
            for t in s["themes"]:
                c[t] = c.get(t, 0) + 1
        return sorted(c.items(), key=lambda x: (-x[1], x[0]))
    avec = [s for s in sets if s.get("themes") and not s.get("themes_estimes")]
    par_serie: dict = {}
    par_marque: dict = {}
    for s in avec:
        if _serie(s):
            par_serie.setdefault(_serie(s), []).append(s)
        par_marque.setdefault(s["marque"], []).append(s)
    for s in sets:
        if s.get("themes"):
            continue
        sujet = n.sujet_univers(s.get("univers") or [])
        if sujet:
            s["themes"], s["themes_estimes"] = [sujet], "univers"
            continue
        groupe = par_serie.get(_serie(s), []) if _serie(s) else []
        c = compte(groupe)
        if c and c[0][1] >= THEME_MIN and c[0][1] >= THEME_PART * len(groupe):
            s["themes"], s["themes_estimes"] = [c[0][0]], "série"
            continue
        c = compte(par_marque.get(s["marque"]) or avec)
        if c:
            s["themes"], s["themes_estimes"] = [c[0][0]], "marque"


def types_par_serie(sets: list[dict], surs: set[str] | None = None) -> None:
    """Type de briques d'un set sans type, d'après sa série (marque et deux premiers chiffres du numéro) :
    quand au moins 10 sets de la série ont un type connu et que 90 % d'entre eux ont le même. Mesure du
    20/11/2026, chaque set connu prédit par les autres de sa série : 240 justes, 6 faux (Mould King 15, 16,
    17, 19, 20…, CaDA 61, Reobrix 33 et 66). Calculé à chaque reconstruction, sur les données du moment.
    Avec `surs` (identifiants des sets dont le type est sûr : photos, corrections), la série se compte sur
    eux seuls et l'emporte sur le tri par étiquettes pour les autres sets : mesure du 21/11/2026 contre
    l'étalon des photos, chaque set prédit sans lui-même, série puis étiquettes sûres : 581 justes, 22 faux,
    163 laissés sans type ; étiquettes seules (tri de la v3.13) : 286 justes sur 389 Technic."""
    par_serie: dict[tuple, dict[str, int]] = {}
    for s in sets:
        k = _serie(s)
        if k and s.get("type") and (surs is None or s.get("id") in surs):
            par_serie.setdefault(k, {}).setdefault(s["type"], 0)
            par_serie[k][s["type"]] += 1
    regle = {}
    for k, c in par_serie.items():
        total = sum(c.values())
        t, n = max(c.items(), key=lambda x: x[1])
        if total >= SERIE_MIN and n / total >= SERIE_PART:
            regle[k] = t
    for s in sets:
        a_remplir = not s.get("type") if surs is None else s.get("id") not in surs
        if a_remplir and _serie(s) in regle:
            s["type"], s["type_estime"] = regle[_serie(s)], "série"


def corrections() -> dict:
    """Corrections à la main (`data/corrections.json`), validées : un fichier illisible ou une valeur
    mal formée est ignoré et journalisé, sans priver le catalogue des autres corrections."""
    try:
        brut = json.loads((RACINE / "data" / "corrections.json").read_text("utf-8"))
    except FileNotFoundError:
        return {}
    except ValueError:
        log.exception("data/corrections.json illisible : corrections ignorées")
        return {}
    themes = {t["id"] for t in n.themes_disponibles()}
    valide = {"nom": lambda v: isinstance(v, str) and v.strip(),
              "type": lambda v: v in ("technic", "classique"),
              "themes": lambda v: isinstance(v, list) and all(x in themes for x in v),
              "dims": lambda v: isinstance(v, list) and 0 < len(v) <= 3 and all(isinstance(x, (int, float)) and x > 0 for x in v)}
    sets = {}
    for sid, champs in (brut.get("sets") or {}).items():
        for k, v in (champs or {}).items() if isinstance(champs, dict) else ():
            if k in valide and valide[k](v):
                sets.setdefault(sid, {})[k] = v
            else:
                log.warning("correction ignorée pour %s : %s = %r", sid, k, v)
    listes = lambda x: [c for c in x if isinstance(c, str)] if isinstance(x, list) else []
    return {"regrouper": [listes(g) for g in brut.get("regrouper") or [] if isinstance(g, list)],
            "separer": listes(brut.get("separer")), "sets": sets}


def sources_config() -> list[dict]:
    return json.loads((RACINE / "data" / "sources.json").read_text("utf-8"))["sources"]


def _cle_set(o: dict) -> str:
    base = n.numero_base(o["marque"], o.get("numero"))
    return f"{n.sans_accents(o['marque'])}|{base}" if base else o["cle"]


def _separer(groupe: list[dict]) -> list[list[dict]]:
    """Sépare les offres d'un même numéro dont le nombre de pièces diffère de plus de 10 % (variantes)."""
    paquets: list[list[dict]] = []
    for o in sorted(groupe, key=lambda o: -(o.get("pieces") or 0)):
        p = o.get("pieces")
        for paq in paquets:
            ref = next((x["pieces"] for x in paq if x.get("pieces")), None)
            if p is None or ref is None or abs(p - ref) <= 0.1 * ref:
                paq.append(o)
                break
        else:
            paquets.append([o])
    return paquets


def _slug(cle: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", n.sans_accents(cle)).strip("-")[:60]


class Index:
    def __init__(self, dossier: Path):
        self.dossier = Path(dossier) / "sources"
        self._cache: tuple[float, list] | None = None
        self.tests = Tests(Path(dossier))   # liens de tests indépendants (voir tests_auto.py)
        self.photos = Photos(Path(dossier))  # photos vérifiées (voir photos.py)
        self.photos_brutes: tuple[list[str], list[str]] = ([], [])
        self.historique = Historique(Path(dossier))   # prix de chaque jour (voir historique.py)
        self._classes: dict[tuple, tuple] = {}
        self._ref_lego: tuple = (None, {})

    def fichier(self, source_id: str) -> Path:
        return dans(self.dossier, f"{re.sub(r'[^a-z0-9_-]', '', source_id)}.json")

    def lire(self, source_id: str) -> dict:
        return _lire(self.fichier(source_id), {"offres": [], "vus": {}})

    def enregistrer(self, source_id: str, offres: list[dict]) -> dict:
        """Remplace les offres d'une source ; rend le nombre de nouveaux et de disparus."""
        with VERROU:
            ancien = self.lire(source_id)
            avant = {o["cle"] for o in ancien.get("offres", [])}
            apres = {o["cle"] for o in offres}
            vus = ancien.get("vus", {})
            aujourd_hui = time.strftime("%Y-%m-%d")
            for o in offres:
                o["depuis"] = vus.setdefault(o["cle"], aujourd_hui)
            _ecrire(self.fichier(source_id), {"le": time.strftime("%Y-%m-%dT%H:%M:%S"), "offres": offres, "vus": vus})
            self._noter(offres)
            self._cache = None
            return {"nouveaux": len(apres - avant) if avant else 0, "disparus": len(avant - apres)}

    def maj_fiche(self, source_id: str, prefixe: str, offres: list[dict], etat_fiche: dict) -> None:
        """Remplace les offres d'une fiche (clés commençant par `prefixe`) et note son état de lecture."""
        with VERROU:
            d = self.lire(source_id)
            vus = d.setdefault("vus", {})
            aujourd_hui = time.strftime("%Y-%m-%d")
            maintenant = time.strftime("%Y-%m-%dT%H:%M:%S")
            for o in offres:
                o["depuis"] = vus.setdefault(o["cle"], aujourd_hui)
                o["lu"] = maintenant
                o.setdefault("releve", maintenant)  # date du relevé donnée par la source, sinon celle de la lecture
            d["offres"] = [o for o in d.get("offres", []) if not o["cle"].startswith(prefixe)] + offres
            d.setdefault("fiches", {})[prefixe.rstrip(":").split(":")[-1]] = etat_fiche
            _ecrire(self.fichier(source_id), d)
            self._noter(offres)
            self._cache = None

    def etat_fiche(self, source_id: str, num: str, champs: dict) -> None:
        """Note l'état de lecture d'une fiche sans toucher à ses offres (échec de lecture)."""
        with VERROU:
            d = self.lire(source_id)
            d.setdefault("fiches", {}).setdefault(num, {}).update(champs)
            _ecrire(self.fichier(source_id), d)

    def maj_offre(self, source_id: str, cle: str, champs: dict) -> None:
        """Met à jour une offre relue en direct (prix, disponibilité)."""
        with VERROU:
            d = self.lire(source_id)
            maj = []
            for o in d.get("offres", []):
                if o["cle"] == cle:
                    o.update(champs, releve=time.strftime("%Y-%m-%dT%H:%M:%S"))
                    maj.append(o)
            _ecrire(self.fichier(source_id), d)
            self._noter(maj)
            self._cache = None

    def _noter(self, offres: list[dict]) -> None:
        """Historique des prix : une panne n'empêche jamais d'enregistrer les offres."""
        try:
            self.historique.noter(offres)
        except Exception:
            log.exception("historique des prix non noté")

    def _classer(self, sig: dict, marque: str) -> tuple[str | None, list[str], list[str]]:
        """Type de briques, thèmes et univers d'une offre d'après les signaux bruts de sa boutique ; gardés en
        mémoire par signaux (les règles ne changent qu'avec le code, donc au redémarrage)."""
        cat, etq, titre = sig.get("categorie") or "", [str(x) for x in sig.get("etiquettes") or []], sig.get("titre") or ""
        k = (cat, tuple(etq), titre, marque)
        val = self._classes.get(k)
        if val is None:
            if len(self._classes) > 20000:
                self._classes.clear()
            val = self._classes[k] = (n.type_briques(cat, etq, titre, marque), n.themes(titre, etq, cat),
                                      n.univers(titre, etq, cat))
        return val[0], list(val[1]), list(val[2])

    def _reference_lego(self) -> dict:
        """Référence Rebrickable (`reference_lego.json`, écrite à chaque synchronisation), relue quand elle change."""
        f = self.dossier.parent / "reference_lego.json"
        cle = f.stat().st_mtime_ns if f.exists() else 0
        if self._ref_lego[0] != cle:
            ref = _lire(f, {})
            self._ref_lego = (cle, ref if isinstance(ref, dict) else {})
        return self._ref_lego[1]

    # ----- corrections faites depuis la page -----
    @property
    def fichier_locales(self) -> Path:
        return self.dossier.parent / "corrections_locales.json"

    def corrections_locales(self) -> dict:
        """{id du set: {type, par, le}} : types imposés depuis la fiche par un compte administrateur,
        appliqués après data/corrections.json. Valeur mal formée ignorée."""
        d = _lire(self.fichier_locales, {})
        sets = d.get("sets") if isinstance(d, dict) else None
        return {k: v for k, v in (sets or {}).items() if isinstance(k, str) and isinstance(v, dict)}

    def imposer_type(self, ident: str, type_: str | None, par: str) -> None:
        """Impose (ou retire, avec None) le type de briques d'un set ; le catalogue est reconstruit à la
        lecture suivante."""
        if type_ is not None and type_ not in TYPES:
            raise ValueError("type inconnu")
        with VERROU:
            d = _lire(self.fichier_locales, {})
            sets = d.setdefault("sets", {}) if isinstance(d, dict) else {}
            if type_ is None:
                sets.pop(ident, None)
            else:
                sets[ident] = {"type": type_, "par": par, "le": time.strftime("%Y-%m-%dT%H:%M:%S")}
            _ecrire(self.fichier_locales, {"sets": sets})
            self._cache = None

    # ----- catalogue regroupé -----
    def sets(self, actives: list[str]) -> list[dict]:
        intrants = [self.fichier(s) for s in actives] + [RACINE / "data" / f for f in (
            "corrections.json", "sources.json", "livraison.json", "glossaire.json", "themes.json", "types_photos.json")] + [
            self.dossier.parent / "livraison_lue.json", self.photos.fichier, self.fichier_locales, self.historique.fichier,
            self.dossier.parent / "reference_lego.json"]
        cle_cache = (tuple(sorted(actives)), tuple(p.stat().st_mtime_ns if p.exists() else 0 for p in intrants),
                     self.tests.signature(), time.strftime("%Y-%m-%d"))   # le jour : « plus bas sur 30 jours » exclut le jour même
        if self._cache and self._cache[0] == cle_cache:
            return self._cache[1]
        conf = {s["id"]: s for s in sources_config()}
        revendeurs = livraison_revendeurs()
        from .livraison import ports_lus
        lus = ports_lus(self.dossier.parent)  # port relu sur la page de livraison (ligne « France 4,95 € »)
        ref_lego = self._reference_lego()
        offres = []
        for sid in actives:
            d = self.lire(sid)
            for o in d.get("offres", []):
                o.setdefault("releve", d.get("le"))
                sig = o.get("signaux")
                if isinstance(sig, dict):   # type, thèmes et univers recalculés sur les signaux bruts de la boutique
                    o["type"], o["themes"], o["univers"] = self._classer(sig, o["marque"])
                elif sid == "bricksvalue":   # thèmes et univers recalculés sur le chemin de thèmes Rebrickable
                    chemin = (ref_lego.get(o.get("numero") or "") or {}).get("themes_lego")
                    if chemin:
                        o["themes"], o["univers"] = n.themes(o["nom"], [], "", chemin), n.univers(o["nom"], [], "", chemin)
                try:
                    h = self.historique.resume(o["cle"]) or {}
                except Exception:   # historique illisible : le catalogue reste servi, sans résumé
                    log.exception("historique des prix illisible pour %s", o["cle"])
                    h = {}
                o["bas30"], o["jours_suivis"] = h.get("min30"), h.get("jours")
                o["avant_remise"], o["avant_remise_j"] = h.get("avant_remise"), h.get("avant_remise_j")
                if sid == "bricksvalue":  # place de comparaison : le port dépend du revendeur
                    regle = revendeurs.get(o["boutique"])
                    o["port"], o["port_estime"] = port_revendeur(regle, o["prix"])
                    o["delai"] = (regle or {}).get("delai")
                else:
                    liv = (conf.get(sid) or {}).get("livraison") or {}
                    o["port"], o["delai"], o["port_estime"] = lus.get(sid, liv.get("port")), liv.get("delai"), liv.get("estime", False)
                offres.append(o)
        couverts = {_cle_set(o) for o in offres}
        offres += [o for o in editoriales() if _cle_set(o) not in couverts]
        corr = corrections()
        force = {c: "corr|" + g[0] for g in corr.get("regrouper", []) if g for c in g}
        force.update({c: c for c in corr.get("separer", [])})
        groupes: dict[str, list[dict]] = {}
        for o in offres:
            groupes.setdefault(force.get(o["cle"]) or _cle_set(o), []).append(o)
        edito = {e["cle"]: e for e in editorial()}
        for e in editorial():
            if e.get("cle_numero"):
                edito.setdefault(e["cle_numero"], e)
        # liens de tests rattachés par numéro : à la première variante seulement (la plus riche en pièces)
        out = [_set(cle if i == 0 else f"{cle}-{i}", paq, edito, self.tests if i == 0 else None)
               for cle, g in groupes.items() for i, paq in enumerate(_separer(g))]
        out = [s for s in out if s]
        photos = types_photos()
        locales = self.corrections_locales()
        surs = set(photos) | {i for i, c in corr.get("sets", {}).items() if c.get("type")} \
            | {i for i, c in locales.items() if c.get("type") in TYPES}
        # ordre de preuve du type : choix d'un administrateur, corrections à la main, photos, série, étiquettes
        for s in out:
            if s["id"] in photos:
                s["type"] = photos[s["id"]]
            for k, v in (corr.get("sets", {}).get(s["id"]) or {}).items():
                if k in ("nom", "type", "themes", "dims"):
                    s[k] = v
            if (locales.get(s["id"]) or {}).get("type") in TYPES:  # imposé depuis la fiche par un administrateur
                s["type"] = locales[s["id"]]["type"]
        types_par_serie(out, surs)
        themes_par_defaut(out)
        self.photos_brutes = adresses_photos(out)
        appliquer_photos(out, self.photos.ecartees(), self.photos.douteuses())
        self._cache = (cle_cache, out)
        return out


def _total(o: dict) -> float:
    return o["prix"] + (PORT_INCONNU if o.get("port") is None else o["port"])


def _set(cle: str, offres: list[dict], edito: dict, tests: Tests | None = None) -> dict | None:
    offres.sort(key=lambda o: (DISPO_RANG[o["dispo"]], _total(o)))
    ed = next((edito[o["cle"]] for o in offres if o["cle"] in edito), None)
    if ed is None and offres[0].get("numero"):
        ed = edito.get(f"{n.sans_accents(offres[0]['marque'])}|{n.numero_base(offres[0]['marque'], offres[0]['numero'])}")
    par_pref = sorted(offres, key=lambda o: PREFERENCE_NOM.index(o["source"]) if o["source"] in PREFERENCE_NOM else 99)
    premier = lambda k: next((o.get(k) for o in par_pref if o.get(k)), None)
    meilleure = offres[0]
    if ed:  # thème choisi à la main pour les sets du catalogue éditorial
        themes = n.themes(ed["nom"] + " " + (ed.get("theme") or ""), [ed.get("theme") or ""])
    else:
        themes = sorted({t for o in offres for t in o.get("themes", []) if t in n.ids_connus()[0]})
    # thème ou univers retiré, encore porté par une offre enregistrée avant : ignoré
    univers = sorted({u for o in offres for u in o.get("univers") or [] if u in n.ids_connus()[1]}
                     | set(n.univers(ed["nom"]) if ed else ()))
    actifs = [o["prix"] for o in offres if o["dispo"] != "epuise"]
    nom = (ed or {}).get("nom") or n.nom_court(premier("nom"))
    origine = None
    if not ed and next((o["source"] for o in par_pref if o.get("nom")), None) == "bausteinreich":
        traduit = n.traduire_de(nom)  # nom seulement en allemand : traduction mot à mot (data/glossaire.json)
        if traduit and traduit != nom:
            nom, origine = traduit, nom
    s = {
        "id": _slug(cle), "nom": nom,
        "marque": meilleure["marque"], "numero": premier("numero"),
        "themes": themes, "univers": univers, "type": premier("type"), "pieces": premier("pieces"),
        "dims": (ed or {}).get("dims") or premier("dims"), "img": premier("img"),
        "dispo": meilleure["dispo"], "prix": meilleure["prix"], "port": meilleure.get("port"),
        "depuis": min((o.get("depuis") or "9999") for o in offres),
        "ecart": len(actifs) > 1 and max(actifs) > 1.4 * min(actifs),
        "offres": [{k: o.get(k) for k in ("source", "boutique", "pays", "cle", "url", "prix", "port", "port_estime",
                                           "delai", "dispo", "releve", "releve_par", *OPTIONNELS)
                    if o.get(k) is not None or k not in OPTIONNELS} for o in offres],
    }
    images = []
    for o in par_pref:
        for u in ([o.get("img")] if o.get("img") else []) + (o.get("images") or []):
            if u and u not in images:
                images.append(u)
    if len(images) > 1:
        s["images"] = images
    if origine:
        s["nom_origine"] = origine
    if premier("retrait"):
        s["retrait"] = premier("retrait")
    if ed:
        for k in ("tests", "avis", "tags"):
            if ed.get(k):
                s[k] = ed[k]
    if tests:
        liens = tests.pour(s["marque"], *dict.fromkeys(o.get("numero") for o in offres))
        deja = {t.get("url") for t in s.get("tests", [])}
        liens = [x for x in liens if x["url"] not in deja]
        if liens:   # tests indépendants rattachés par script : liens seulement, aucun verdict
            s["liens_tests"] = liens
            s["nb_tests"] = len(liens)
    return s


# ----- couche éditoriale -----
_EDITO: list | None = None


def editorial() -> list[dict]:
    """Sets du catalogue éditorial, avec la clé qui les rattache aux offres des boutiques."""
    global _EDITO
    if _EDITO is None:
        cat = json.loads((RACINE / "data" / "catalogue.json").read_text("utf-8"))
        _EDITO = []
        for it in cat:
            m = re.search(r"kbs-shop\.com/(?:\w\w/)?products/([^/?#]+)", it["url"])
            cle = f"kbs:{m.group(1)}" if m else f"{n.sans_accents(it['marque'])}|{n.numero(it.get('ref') or '', it.get('ref'))}"
            dims = sorted((float(x) for x in re.findall(r"\d+(?:\.\d+)?", it.get("dim") or "")), reverse=True) or None
            num = n.numero(it.get("ref") or "", it.get("ref"))
            _EDITO.append({**it, "cle": cle, "dims": dims,
                           "cle_numero": f"{n.sans_accents(it['marque'])}|{num}" if num else None})
    return _EDITO


def editoriales() -> list[dict]:
    """Offres du catalogue éditorial pour les sets qu'aucun connecteur ne couvre encore (LEGO officiel)."""
    out = []
    for it in editorial():
        if "lego.com" not in it["url"]:
            continue
        out.append({
            "source": "editorial", "boutique": "LEGO.com", "pays": "France", "cle": it["cle"], "url": it["url"],
            "nom": it["nom"], "marque": it["marque"], "numero": n.numero(it.get("ref") or "", it.get("ref")),
            "prix": it["prix"], "port": port_revendeur(livraison_revendeurs().get("LEGO.com"), it["prix"])[0],
            "delai": livraison_revendeurs()["LEGO.com"]["delai"],
            "dispo": "vente" if it.get("dispo", True) else "epuise",
            "img": it.get("img"), "pieces": it.get("pcs"), "dims": None,
            "type": "technic" if it.get("type") == "Technic" else "classique",
            "themes": n.themes(it["nom"] + " " + (it.get("theme") or ""), [it.get("theme") or ""]),
            "univers": n.univers(it["nom"]), "releve": None, "depuis": "2026-11-19",
        })
    return out


def sets_hors_ligne() -> list[dict]:
    """Sets de la page autonome : le seul catalogue éditorial, avec les prix relevés à la main."""
    offres = editoriales()
    for it in editorial():
        if urlsplit(it["url"]).hostname in ("kbs-shop.com", "www.kbs-shop.com"):
            offres.append({
                "source": "kbs", "boutique": "KBS", "pays": "Allemagne", "cle": it["cle"], "url": it["url"],
                "nom": it["nom"], "marque": it["marque"], "numero": n.numero(it.get("ref") or "", it.get("ref")),
                "prix": it["prix"], "port": 4.95, "delai": "1 à 3 jours",
                "dispo": "precommande" if it.get("precommande") else "vente" if it.get("dispo", True) else "epuise",
                "img": it.get("img"), "pieces": it.get("pcs"), "dims": it.get("dims"),
                "type": "technic" if it.get("type") == "Technic" else "classique",
                "themes": n.themes(it["nom"] + " " + (it.get("theme") or ""), [it.get("theme") or ""]),
                "releve": None, "depuis": "2026-11-19"})
    groupes: dict[str, list[dict]] = {}
    for o in offres:
        groupes.setdefault(_cle_set(o), []).append(o)
    edito = {e["cle"]: e for e in editorial()}
    out = [s for s in (_set(cle, g, edito) for cle, g in groupes.items()) if s]
    themes_par_defaut(out)
    photos, corr = types_photos(), corrections().get("sets", {})
    for s in out:   # même ordre de preuve que le service : les corrections priment sur les photos
        if s and (corr.get(s["id"]) or {}).get("type") or s and s["id"] in photos:
            s["type"] = (corr.get(s["id"]) or {}).get("type") or photos[s["id"]]
    return out

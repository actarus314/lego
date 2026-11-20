"""Tests des logos de marques (app/logos.py) et de l'encodage des adresses (app/lien.py), sans réseau :
`lien.recuperer` est simulé, ainsi que la connexion pour les tests de `lien._get`."""
from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock
from urllib.parse import urlsplit

from app import lien, logos, normalise


def png(taille: int) -> bytes:
    return b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR" + taille.to_bytes(4, "big") * 2 + b"\x08\x06\x00\x00\x00" + b"x" * 20


def ico(*tailles: int) -> bytes:
    tete = b"\x00\x00\x01\x00" + len(tailles).to_bytes(2, "little")
    return tete + b"".join(bytes([t % 256, t % 256]) + b"\x00" * 14 for t in tailles) + b"x" * 20


def gif(taille: int) -> bytes:
    return b"GIF89a" + taille.to_bytes(2, "little") * 2 + b"x" * 10


def jpg(taille: int) -> bytes:
    sof = b"\xff\xc0\x00\x11\x08" + taille.to_bytes(2, "big") + taille.to_bytes(2, "big") + b"\x03" + b"\x00" * 9
    return b"\xff\xd8\xff\xe0\x00\x04ab" + sof + b"\xff\xd9"


def webp(fmt: bytes, taille: int) -> bytes:
    if fmt == b"VP8X":
        corps = b"VP8X" + b"\x0a\x00\x00\x00" + b"\x00" * 4 + (taille - 1).to_bytes(3, "little") * 2
    elif fmt == b"VP8L":
        corps = b"VP8L" + b"\x05\x00\x00\x00" + b"\x2f" + (((taille - 1) | ((taille - 1) << 14)).to_bytes(4, "little"))
    else:
        corps = b"VP8 " + b"\x0a\x00\x00\x00" + b"\x00" * 3 + b"\x9d\x01\x2a" + taille.to_bytes(2, "little") * 2
    return b"RIFF" + (len(corps) + 4).to_bytes(4, "little") + b"WEBP" + corps + b"\x00" * 4


SVG = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><rect width="10" height="10"/></svg>'


def reponse(url: str, corps: bytes = b"", statut: int = 200, type_: str = "") -> lien.Reponse:
    return lien.Reponse(url, statut, type_, corps)


def faux_reseau(pages: dict[str, bytes | Exception]):
    """Remplace lien.recuperer : `pages` associe une adresse à des octets ou à une exception ;
    une adresse absente répond 404. Rend aussi la liste des adresses demandées."""
    demandes: list[str] = []

    def recuperer(url, accept="", entetes=None):
        demandes.append(url)
        r = pages.get(url, pages.get(url + "/"))  # « https://hôte » et « https://hôte/ » sont la même page
        if isinstance(r, Exception):
            raise r
        if r is None:
            e = lien.LienRefuse("le site a répondu 404")
            e.statut = 404
            raise e
        if isinstance(r, tuple):  # (adresse finale après redirection, octets)
            return reponse(*r)
        return reponse(url, r)
    return recuperer, demandes


class Dimensions(unittest.TestCase):
    def test_formats(self):
        self.assertEqual(logos.dimension(png(180), "png"), 180)
        self.assertEqual(logos.dimension(gif(64), "gif"), 64)
        self.assertEqual(logos.dimension(jpg(300), "jpg"), 300)
        self.assertEqual(logos.dimension(webp(b"VP8X", 300), "webp"), 300)
        self.assertEqual(logos.dimension(webp(b"VP8L", 128), "webp"), 128)
        self.assertEqual(logos.dimension(webp(b"VP8 ", 32), "webp"), 32)

    def test_ico_plus_grande_entree(self):
        self.assertEqual(logos.dimension(ico(16, 48, 32), "ico"), 48)
        self.assertEqual(logos.dimension(ico(0), "ico"), 256)  # 0 signifie 256 dans un fichier ICO

    def test_illisible_ou_vectoriel(self):
        self.assertIsNone(logos.dimension(SVG, "svg"))
        self.assertIsNone(logos.dimension(b"\x89PNG", "png"))
        self.assertIsNone(logos.dimension(b"\xff\xd8\xff", "jpg"))
        self.assertIsNone(logos.dimension(b"", "ico"))

    def test_format_reconnu_pour_les_icones_de_site(self):
        self.assertEqual(logos._format(ico(16)), "ico")
        self.assertEqual(logos._format(webp(b"VP8X", 32)), "webp")
        self.assertEqual(logos._format(gif(8)), "gif")
        self.assertEqual(logos._format(jpg(8)), "jpg")
        self.assertIsNone(logos._format(b"<!DOCTYPE html><html>erreur 404</html>"))


class Candidats(unittest.TestCase):
    def candidats(self, page: str, url="https://marque.test/", extra=None):
        # `url` : adresse finale de la page d'accueil (le service demande « https://hôte », éventuellement redirigé)
        pages = {"https://" + urlsplit(url).netloc: (url, page.encode("utf-8")), **(extra or {})}
        rec, _ = faux_reseau(pages)
        with mock.patch.object(logos.lien, "recuperer", rec):
            return logos._candidats(urlsplit(url).netloc)

    def test_apple_touch_icon_avant_les_autres_et_favicon_en_dernier(self):
        page = ('<link rel="icon" href="/p16.png" sizes="16x16">'
                '<link rel="apple-touch-icon" sizes="180x180" href="/apple.png">'
                '<link rel="icon" sizes="32x32" href="/p32.png">')
        self.assertEqual(self.candidats(page), [
            "https://marque.test/apple.png", "https://marque.test/p32.png",
            "https://marque.test/p16.png", "https://marque.test/favicon.ico"])

    def test_adresses_relatives_et_sans_schema(self):
        page = ('<link rel="shortcut icon" href="//cdn.test/i.png">'
                '<link rel="apple-touch-icon" href="img/a.png">')
        self.assertEqual(self.candidats(page, "https://marque.test/fr/"), [
            "https://marque.test/fr/img/a.png", "https://cdn.test/i.png", "https://marque.test/favicon.ico"])

    def test_balise_base_et_attributs_sans_guillemets_ou_en_desordre(self):
        page = ("<base href='https://static.test/'>"
                "<link href=a.png rel=apple-touch-icon>"
                "<link sizes='64x64' HREF='b.png' REL='icon'>")
        self.assertEqual(self.candidats(page)[:2], ["https://static.test/a.png", "https://static.test/b.png"])

    def test_esperluette_html_et_pictogramme_monochrome_ignore(self):
        page = ('<link rel="icon" href="/i.png?a=1&amp;b=2">'
                '<link rel="mask-icon" href="/masque.svg"><link rel="icon" href="data:image/png;base64,AAAA">')
        self.assertEqual(self.candidats(page), ["https://marque.test/i.png?a=1&b=2", "https://marque.test/favicon.ico"])

    def test_svg_compte_comme_tres_grand(self):
        page = '<link rel="icon" sizes="192x192" href="/a.png"><link rel="icon" type="image/svg+xml" href="/a.svg">'
        self.assertEqual(self.candidats(page)[:2], ["https://marque.test/a.svg", "https://marque.test/a.png"])

    def test_miniature_shopify_agrandie(self):
        page = '<link rel="icon" href="//m.test/cdn/shop/files/logo_32x32.png?v=7">'
        self.assertEqual(self.candidats(page)[:2], [
            "https://m.test/cdn/shop/files/logo.png?v=7&width=256", "https://m.test/cdn/shop/files/logo_32x32.png?v=7"])
        self.assertEqual(logos._agrandie("https://m.test/cdn/shop/files/l.png?height=66&crop=center&v=3"),
                         "https://m.test/cdn/shop/files/l.png?v=3&width=256")
        self.assertIsNone(logos._agrandie("https://m.test/cdn/shop/files/l.png?v=3"))
        self.assertIsNone(logos._agrandie("https://m.test/img/l_32x32.png"))

    def test_logo_de_page_sans_icone_declaree(self):
        page = ('<img src="/instagram.png" alt="Instagram"><img src="//m.test/cdn/l.png" itemprop="logo">'
                '<script type="application/ld+json">{"@type":"Organization","logo":"https:\\/\\/m.test\\/ld.png"}</script>')
        self.assertEqual(self.candidats(page), ["https://m.test/cdn/l.png", "https://m.test/ld.png",
                                                "https://marque.test/favicon.ico"])
        self.assertEqual(self.candidats('<img class="header-logo" src="images/logo.jpg">', "https://marque.test/EN/")[0],
                         "https://marque.test/EN/images/logo.jpg")

    def test_redirection_dans_la_page(self):
        refresh = '<html><meta http-equiv="refresh" content="0;url=/EN/Index.aspx"></html>'
        suite = '<link rel="icon" href="/ic.png">'
        self.assertEqual(self.candidats(refresh, extra={"https://marque.test/EN/Index.aspx": suite.encode()})[0],
                         "https://marque.test/ic.png")
        script = '<script>window.onload=function(){window.location.href="/lander"}</script>'
        self.assertEqual(self.candidats(script, extra={"https://marque.test/lander": suite.encode()})[0],
                         "https://marque.test/ic.png")

    def test_page_longue_sans_icone_ne_suit_pas_un_script(self):
        page = "<p>" + "x" * 5000 + "</p><script>location='/ailleurs'</script>"
        rec, demandes = faux_reseau({"https://marque.test/": page.encode()})
        with mock.patch.object(logos.lien, "recuperer", rec):
            logos._candidats("marque.test")
        self.assertEqual(demandes, ["https://marque.test"])

    def test_page_en_echec(self):
        rec, _ = faux_reseau({"https://marque.test/": lien.LienRefuse("le site a répondu 503")})
        with mock.patch.object(logos.lien, "recuperer", rec), self.assertRaises(lien.LienRefuse):
            logos._candidats("marque.test")


class Recuperation(unittest.TestCase):
    def lancer(self, pages, conf=None):
        rec, demandes = faux_reseau(pages)
        with mock.patch.object(logos.lien, "recuperer", rec):
            return logos.recuperer(conf or {"site": "marque.test"}), demandes

    def test_icone_16_px_ne_masque_pas_une_plus_grande(self):
        page = b'<link rel="icon" sizes="16x16" href="/p16.png"><link rel="icon" href="/p48.png">'
        (corps, ext), _ = self.lancer({"https://marque.test/": page, "https://marque.test/p16.png": png(16),
                                       "https://marque.test/p48.png": png(48)})
        self.assertEqual((ext, logos.dimension(corps, ext)), ("png", 48))

    def test_arret_des_qu_une_icone_suffisante_est_lue(self):
        page = b'<link rel="apple-touch-icon" href="/a.png"><link rel="icon" href="/b.png">'
        (corps, ext), demandes = self.lancer({"https://marque.test/": page, "https://marque.test/a.png": png(180),
                                              "https://marque.test/b.png": png(512)})
        self.assertEqual(logos.dimension(corps, ext), 180)
        self.assertEqual(demandes, ["https://marque.test", "https://marque.test/a.png"])

    def test_favicon_ico_si_la_page_ne_declare_rien(self):
        (corps, ext), _ = self.lancer({"https://marque.test/": b"<html></html>", "https://marque.test/favicon.ico": ico(16, 32)})
        self.assertEqual((ext, logos.dimension(corps, ext)), ("ico", 32))

    def test_type_inattendu_et_trop_gros_ecartes(self):
        """Une page d'erreur servie avec le code 200 et une image de plus de TAILLE_MAX ne sont pas gardées."""
        page = b'<link rel="icon" href="/a.png"><link rel="icon" sizes="16x16" href="/b.png">'
        with self.assertRaises(ValueError):
            self.lancer({"https://marque.test/": page, "https://marque.test/a.png": b"<html>erreur</html>",
                         "https://marque.test/b.png": png(16) + b"x" * logos.TAILLE_MAX})
        (corps, ext), _ = self.lancer({"https://marque.test/": page, "https://marque.test/a.png": b"<html>erreur</html>",
                                       "https://marque.test/b.png": png(16)})
        self.assertEqual(logos.dimension(corps, ext), 16)

    def test_svg_prefere_a_un_png(self):
        page = b'<link rel="icon" href="/a.png"><link rel="icon" href="/a.svg">'
        (corps, ext), _ = self.lancer({"https://marque.test/": page, "https://marque.test/a.png": png(64),
                                       "https://marque.test/a.svg": SVG})
        self.assertEqual(ext, "svg")

    def test_adresse_directe_d_abord_puis_site_en_secours(self):
        conf = {"site": "marque.test", "icone": "https://img.test/logo.png"}
        (corps, ext), demandes = self.lancer({"https://img.test/logo.png": png(200)}, conf)
        self.assertEqual(logos.dimension(corps, ext), 200)
        self.assertEqual(demandes, ["https://img.test/logo.png"])
        (corps, ext), _ = self.lancer({"https://marque.test/": b'<link rel="icon" href="/i.png">',
                                       "https://marque.test/i.png": png(128)}, conf)
        self.assertEqual(logos.dimension(corps, ext), 128)

    def test_adresse_directe_seule_quand_la_page_est_refusee(self):
        conf = {"site": "marque.test", "icone": "https://img.test/logo.png"}
        (corps, ext), _ = self.lancer({"https://marque.test/": lien.LienRefuse("le site a répondu 503"),
                                       "https://img.test/logo.png": png(40)}, conf)
        self.assertEqual(logos.dimension(corps, ext), 40)

    def test_echecs(self):
        with self.assertRaises(lien.LienRefuse) as c:  # page refusée, aucune adresse directe : le motif reste lisible
            self.lancer({"https://marque.test/": lien.LienRefuse("le site a répondu 503")})
        self.assertEqual(c.exception.public, "le site a répondu 503")
        with self.assertRaises(ValueError):
            self.lancer({"https://marque.test/": b"<html></html>"})

    def test_erreurs_inattendues_sont_absorbees(self):
        page = b'<link rel="icon" href="/a.png"><link rel="icon" sizes="16x16" href="/b.png">'
        (corps, ext), _ = self.lancer({"https://marque.test/": page, "https://marque.test/a.png": UnicodeEncodeError("ascii", "é", 0, 1, "x"),
                                       "https://marque.test/b.png": png(16)})
        self.assertEqual(logos.dimension(corps, ext), 16)

    def test_nombre_d_icones_essayees_limite(self):
        page = "".join(f'<link rel="icon" sizes="{16 + i}x{16 + i}" href="/{i}.png">' for i in range(20)).encode()
        rec, demandes = faux_reseau({"https://marque.test/": page})
        with mock.patch.object(logos.lien, "recuperer", rec), self.assertRaises(ValueError):
            logos.recuperer({"site": "marque.test"})
        self.assertEqual(len(demandes), 1 + logos.CANDIDATES_MAX)


class Calendrier(unittest.TestCase):
    """Délais de nouvel essai : 1, 3, 7 puis 30 jours après un échec ; 30 jours après un logo réussi."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.logos = logos.Logos(Path(self.tmp.name))
        self.sites = {"Marque A": {"site": "a.test"}}
        for cible in (mock.patch.object(logos, "sites", lambda: self.sites),
                      mock.patch.object(logos, "PAUSE_S", 0)):
            cible.start()
            self.addCleanup(cible.stop)

    def il_y_a(self, jours: float) -> str:
        return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(time.time() - jours * 86400))

    def ecrire_etat(self, etat: dict):
        self.logos.dossier.mkdir(parents=True, exist_ok=True)
        self.logos.fichier.write_text(json.dumps(etat), "utf-8")

    def passage(self, resultat):
        """Un passage de la boucle ; `resultat` : octets de l'image, ou exception. Rend (bilan, appels)."""
        appels = []

        def fausse(conf):
            appels.append(conf["site"])
            if isinstance(resultat, Exception):
                raise resultat
            return resultat, logos._format(resultat)
        with mock.patch.object(logos, "recuperer", fausse):
            return self.logos.actualiser(), appels

    def test_marque_ajoutee_recuperee_au_passage_suivant(self):
        self.assertEqual(self.passage(png(64)), ({"lus": 1, "echecs": 0}, ["a.test"]))
        self.sites["Marque B"] = {"site": "b.test"}  # ajout dans data/marques.json
        bilan, appels = self.passage(png(64))
        self.assertEqual((bilan, appels), ({"lus": 1, "echecs": 0}, ["b.test"]))
        self.assertEqual(set(self.logos.disponibles()), {"marque-a", "marque-b"})
        self.assertEqual(self.logos.etat()["marque-a"]["taille"], 64)

    def test_logo_reussi_relu_apres_30_jours(self):
        self.ecrire_etat({"marque-a": {"marque": "Marque A", "fichier": "marque-a.png", "format": "png",
                                       "le": self.il_y_a(29), "essai": self.il_y_a(29)}})
        self.assertEqual(self.passage(png(64))[1], [])
        self.ecrire_etat({"marque-a": {"marque": "Marque A", "fichier": "marque-a.png", "format": "png",
                                       "le": self.il_y_a(31), "essai": self.il_y_a(31)}})
        self.assertEqual(self.passage(png(64))[1], ["a.test"])

    def test_echelle_des_delais_apres_echec(self):
        erreur = lien.LienRefuse("le site a répondu 503")
        bilan, appels = self.passage(erreur)  # 1er échec
        self.assertEqual((bilan, appels), ({"lus": 0, "echecs": 1}, ["a.test"]))
        self.assertEqual(self.logos.etat()["marque-a"]["motif"], "le site a répondu 503")
        for echecs, delai in ((1, 1), (2, 3), (3, 7), (4, 30), (5, 30), (9, 30)):
            etat = {"marque-a": {"marque": "Marque A", "erreur": True, "echecs": echecs}}
            etat["marque-a"]["essai"] = self.il_y_a(delai - 0.5)
            self.ecrire_etat(etat)
            self.assertEqual(self.passage(erreur)[1], [], f"trop tôt après {echecs} échec(s)")
            etat["marque-a"]["essai"] = self.il_y_a(delai + 0.01)
            self.ecrire_etat(etat)
            self.assertEqual(self.passage(erreur)[1], ["a.test"], f"à retenter après {echecs} échec(s)")
            self.assertEqual(self.logos.etat()["marque-a"]["echecs"], echecs + 1)

    def test_marge_pour_la_boucle_quotidienne(self):
        etat = {"marque-a": {"marque": "Marque A", "erreur": True, "echecs": 1, "essai": self.il_y_a(1 - 600 / 86400)}}
        self.ecrire_etat(etat)  # essai il y a 23 h 50 : la boucle de 24 h ne tombe pas à la seconde près
        self.assertEqual(self.passage(lien.LienRefuse("x"))[1], ["a.test"])

    def test_ancien_etat_d_echec_sans_compteur(self):
        """État écrit avant ce changement : `le` est la date du dernier essai, pas de compteur."""
        self.ecrire_etat({"marque-a": {"marque": "Marque A", "le": self.il_y_a(2), "erreur": True}})
        self.assertEqual(self.passage(png(64))[1], ["a.test"])
        self.assertNotIn("erreur", self.logos.etat()["marque-a"])

    def test_reussite_remet_le_compteur_a_zero(self):
        self.ecrire_etat({"marque-a": {"marque": "Marque A", "erreur": True, "echecs": 3, "essai": self.il_y_a(8)}})
        self.passage(png(64))
        e = self.logos.etat()["marque-a"]
        self.assertEqual((e["fichier"], e["format"], e.get("erreur"), e.get("echecs")), ("marque-a.png", "png", None, None))

    def test_logo_deja_obtenu_reste_servi_apres_un_echec(self):
        self.passage(png(64))
        etat = self.logos.etat()
        etat["marque-a"]["le"] = etat["marque-a"]["essai"] = self.il_y_a(31)
        self.ecrire_etat(etat)
        self.passage(lien.LienRefuse("le site a répondu 503"))
        e = self.logos.etat()["marque-a"]
        self.assertEqual((e["erreur"], e["echecs"], e["fichier"]), (True, 1, "marque-a.png"))
        self.assertEqual(self.logos.chemin("marque-a"), ("marque-a.png", "image/png"))
        self.assertEqual(e["le"][:10], self.il_y_a(31)[:10])  # « le » reste la date du logo

    def test_changement_de_format_supprime_l_ancien_fichier(self):
        self.passage(png(64))
        etat = self.logos.etat()
        etat["marque-a"]["essai"] = etat["marque-a"]["le"] = self.il_y_a(40)
        self.ecrire_etat(etat)
        self.passage(SVG)
        self.assertFalse((self.logos.dossier / "marque-a.png").exists())
        self.assertTrue((self.logos.dossier / "marque-a.svg").exists())

    def test_nom_de_fichier_suspect_jamais_supprime(self):
        (Path(self.tmp.name) / "important.txt").write_text("x")
        self.ecrire_etat({"marque-a": {"marque": "Marque A", "fichier": "../important.txt", "format": "png",
                                       "le": self.il_y_a(40)}})
        self.passage(png(64))
        self.assertTrue((Path(self.tmp.name) / "important.txt").exists())


class MarquesDeclarees(unittest.TestCase):
    def test_toutes_les_marques_reconnues_sont_traitees(self):
        """Une marque de normalise.MARQUES absente de data/marques.json n'aura jamais de logo :
        seules celles sans site officiel trouvé sont tolérées, et listées ici."""
        sans_site = {"TGL", "Xinzhuan"}
        declarees = set(logos.sites())
        manquantes = set(normalise.MARQUES.values()) - declarees - sans_site
        self.assertEqual(manquantes, set())
        self.assertFalse(declarees & sans_site)

    def test_chaque_entree_a_un_site_lisible(self):
        for marque, conf in logos.sites().items():
            self.assertRegex(conf["site"], r"^[a-z0-9.-]+\.[a-z]{2,}$", marque)
            self.assertNotIn("/", conf["site"])
            if conf.get("icone"):
                self.assertTrue(conf["icone"].startswith("https://"), marque)
            self.assertRegex(logos.slug(marque), r"^[a-z0-9-]{1,40}$")

    def test_sites_uniques_ou_justifies(self):
        # (Funwhole redirige vers Lumibricks, mais déclare son propre nom de domaine)
        sites = [c["site"] for c in logos.sites().values()]
        doublons = {s for s in sites if sites.count(s) > 1}
        self.assertEqual(doublons, set())


class Encodage(unittest.TestCase):
    """lien._get : chemin et requête non ASCII encodés, contrôles de sécurité intacts."""

    def faux_http(self, statut=200, corps=b"ok", entetes=None):
        vu = {}

        class Conn:
            def __init__(self, hote, port, timeout=None):
                vu["hote"], vu["port"] = hote, port

            def request(self, methode, chemin, headers=None):
                vu["chemin"], vu["entetes"] = chemin, headers  # http.client lève ici sur un chemin non ASCII
                chemin.encode("ascii")

            def getresponse(self):
                rep = mock.Mock(status=statut)
                rep.getheader.side_effect = lambda k, d=None: (entetes or {}).get(k, d if d is not None else ("" if k == "Content-Encoding" else None))
                rep.read.return_value = corps
                return rep
        sock = mock.Mock()
        return vu, mock.patch.object(lien.http.client, "HTTPConnection", Conn), \
            mock.patch.object(lien.socket, "create_connection", return_value=sock), \
            mock.patch.object(lien, "resoudre", return_value="93.184.216.34"), \
            mock.patch.object(lien, "contexte_tls", return_value=mock.Mock(wrap_socket=lambda s, server_hostname: s))

    def appeler(self, url):
        vu, *patchs = self.faux_http()
        for p in patchs:
            p.start()
            self.addCleanup(p.stop)
        r = lien._get(url, "*/*")
        return vu, r

    def test_chemin_et_requete_non_ascii(self):
        vu, r = self.appeler("https://exemple.test/collections/café noël/é.png?titre=été&x=a b")
        self.assertEqual(vu["chemin"], "/collections/caf%C3%A9%20no%C3%ABl/%C3%A9.png?titre=%C3%A9t%C3%A9&x=a%20b")
        self.assertEqual(r.statut, 200)

    def test_sequences_deja_encodees_et_separateurs_conserves(self):
        vu, _ = self.appeler("https://exemple.test/a%20b/c;d=e,f/@g?q=1%2B2&r=/x?y")
        self.assertEqual(vu["chemin"], "/a%20b/c;d=e,f/@g?q=1%2B2&r=/x?y")

    def test_retour_a_la_ligne_neutralise(self):
        vu, _ = self.appeler("https://exemple.test/a\r\nX-Injecte:%20oui?b=\n1")
        self.assertNotIn("\r", vu["chemin"])
        self.assertNotIn("\n", vu["chemin"])

    def test_nom_de_domaine_accentue(self):
        vu, _ = self.appeler("https://jouets-éléphant.test/é")
        attendu = "jouets-éléphant.test".encode("idna").decode()
        self.assertTrue(attendu.startswith("xn--") and attendu.isascii())
        self.assertEqual(vu["hote"], attendu)
        self.assertEqual(vu["entetes"]["Host"], attendu)

    def test_en_tete_host_avec_port_explicite(self):
        vu, _ = self.appeler("https://exemple.test:443/x")
        self.assertEqual(vu["entetes"]["Host"], "exemple.test:443")

    def test_redirection_vers_un_chemin_non_ascii(self):
        vu, *patchs = self.faux_http(301, b"", {"Location": "/boutique/été/logo.png"})
        for p in patchs:
            p.start()
            self.addCleanup(p.stop)
        r = lien._get("https://exemple.test/a", "*/*")
        self.assertEqual(r.url, "https://exemple.test/boutique/été/logo.png")
        # la requête suivante encode ce chemin
        vu2, r2 = self.appeler(r.url)
        self.assertEqual(vu2["chemin"], "/boutique/%C3%A9t%C3%A9/logo.png")

    def test_controles_de_securite_inchanges(self):
        for url, message in (("ftp://exemple.test/x", "http et https"),
                             ("https://u:p@exemple.test/é", "identifiants"),
                             ("https://exemple.test:8443/é", "ports"),
                             ("http://exemple.test:22/é", "ports"),
                             ("https://exemple.test:0/é", "ports")):
            with self.assertRaisesRegex(lien.LienRefuse, message):
                lien._get(url, "*/*")
        for hote in ("127.0.0.1", "10.0.0.5", "169.254.169.254", "[::1]", "192.168.1.1"):
            with self.assertRaisesRegex(lien.LienRefuse, "refusée"):
                lien._get(f"https://{hote}/é", "*/*")

    def test_connexion_a_l_adresse_verifiee_et_redirection_revérifiée(self):
        """Le nom n'est pas résolu une seconde fois à la connexion ; une redirection vers le réseau local est refusée."""
        with mock.patch.object(lien, "resoudre", return_value="93.184.216.34") as res, \
                mock.patch.object(lien.socket, "create_connection", side_effect=OSError("stop")) as cc:
            with self.assertRaises(OSError):
                lien._get("https://exemple.test/é", "*/*")
        cc.assert_called_once()
        self.assertEqual(cc.call_args.args[0][0], "93.184.216.34")
        res.assert_called_once()
        reel = lien._get
        appels = []

        def faux_get(url, accept, entetes=None):
            appels.append(url)
            if len(appels) == 1:
                return lien.Reponse("http://127.0.0.1/secret", 302, "", b"")
            return reel(url, accept, entetes)
        with mock.patch.object(lien, "_get", faux_get), self.assertRaisesRegex(lien.LienRefuse, "refusée"):
            lien.recuperer("https://exemple.test/é")


if __name__ == "__main__":
    unittest.main()

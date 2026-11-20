"""Liens de tests indépendants : lecture des flux, rattachement par marque et numéro, relève, cache. Sans réseau."""
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from app import index as index_mod, lien, tests_auto
from app.index import Index
from app.tests_auto import Tests, lire_flux, numeros_titre

SOURCES = [
    {"id": "yt", "nom": "Chaîne test", "type": "youtube", "flux": "https://exemple.test/yt.xml", "langue": "de"},
    {"id": "blog", "nom": "Blog test", "type": "rss", "flux": "https://exemple.test/feed/", "langue": "de"},
    {"id": "blog-lego", "nom": "Blog LEGO", "type": "rss", "flux": "https://exemple.test/lego/feed/", "langue": "de",
     "marque_implicite": "LEGO officiel"},
]

ATOM = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns:yt="http://www.youtube.com/xml/schemas/2015" xmlns="http://www.w3.org/2005/Atom">
 <title>Chaine</title><published>2014-06-03T08:56:36+00:00</published>
 <entry><id>yt:video:AAAAAAAAAAA</id><title>Mould King&#174; 24093 Radlader</title>
  <link rel="alternate" href="https://www.youtube.com/watch?v=AAAAAAAAAAA"/>
  <published>2026-11-20T06:38:56+00:00</published></entry>
 <entry><id>yt:video:BBBBBBBBBBB</id><title>Sans lien</title><published>2026-11-01T06:38:56+00:00</published></entry>
</feed>"""

RSS = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:dc="http://purl.org/dc/elements/1.1/"><channel><title>Blog</title>
 <item><title>COBI 2232 Huey im Test &#8211; Hubschrauber</title><link>https://blog.test/cobi-2232/</link>
  <pubDate>Fri, 20 Nov 2026 07:49:26 +0000</pubDate></item>
 <item><title>Piratage</title><link>javascript:alert(1)</link><pubDate>Fri, 20 Nov 2026 07:49:26 +0000</pubDate></item>
</channel></rss>"""


def lien_(source, titre, url, date=None, langue="de"):
    x = {"source": source, "titre": titre, "url": url, "langue": langue}
    if date:
        x["date"] = date
    return x


class Titres(unittest.TestCase):
    def cles(self, titre, implicite=None):
        return [(sorted(c), m) for c, m in numeros_titre(titre, implicite)]

    def test_marque_et_numero(self):
        self.assertEqual(self.cles("Mould King® 24093 Radlader"), [(["24093"], "Mould King")])
        self.assertEqual(self.cles("Reobricks® 66031 Faltbares Set"), [(["66031"], "Reobrix")])
        self.assertEqual(self.cles("LEGO® Star Wars 75342 Republic Fighter Tank"), [(["75342"], "LEGO officiel")])

    def test_prefixe_suffixe_boutique(self):
        (cles, marque), = numeros_titre("Mould King 13197S Bagger")
        self.assertEqual((cles, marque), ({"13197", "13197"}, "Mould King"))
        (cles, _), = numeros_titre("CaDA C66010 Japanese Tea Shop")
        self.assertEqual(cles, {"C66010", "66010"})
        (cles, _), = numeros_titre("Reobrix R55013 Zug")
        self.assertEqual(cles, {"55013"})

    def test_annees_et_unites_ecartees(self):
        self.assertEqual(self.cles("Cobi Neuheiten 2026"), [])
        self.assertEqual(self.cles("Cobi Panzer mit 1500 Teilen"), [])
        self.assertEqual(self.cles("Cobi 3600 pcs Schiff 12,060 Teile"), [])
        self.assertEqual(self.cles("Cobi 1686 Titanic"), [(["1686"], "Cobi")])
        self.assertEqual(self.cles("Cobi 4872 (2026) Graf Spee"), [(["4872"], "Cobi")])

    def test_numero_sans_marque_ecarte(self):
        self.assertEqual(self.cles("Das ist Set 24093"), [])

    def test_lego_cinq_chiffres_si_implicite(self):
        self.assertEqual(self.cles("Neuer Bau 75342", "LEGO officiel"), [(["75342"], "LEGO officiel")])
        self.assertEqual(self.cles("Neuer Bau 7965", "LEGO officiel"), [])
        # LEGO nommé : quatre chiffres acceptés (sets anciens)
        self.assertEqual(self.cles("LEGO 7965 Millennium Falcon"), [(["7965"], "LEGO officiel")])

    def test_comparaison_de_deux_marques(self):
        titre = "Legos® 21325 Schmiede im Vergleich zu Morks® 33004 Bauernhaus"
        self.assertEqual(self.cles(titre), [(["21325"], "LEGO officiel"), (["33004"], "Mork")])

    def test_plusieurs_numeros_une_marque(self):
        self.assertEqual([m for _, m in numeros_titre("LEGO Minecraft 21583 21585 21588")], ["LEGO officiel"] * 3)

    def test_marque_dans_un_mot(self):
        self.assertEqual(self.cles("Legoland Besuch 12345"), [])
        self.assertEqual(self.cles("Pantasy 85075 Weihnachtsuhr"), [(["85075"], "Pantasy")])


class Flux(unittest.TestCase):
    def test_atom_youtube(self):
        liens = lire_flux(ATOM, SOURCES[0])
        self.assertEqual(liens, [{"source": "yt", "titre": "Mould King 24093 Radlader", "langue": "de",
                                  "url": "https://www.youtube.com/watch?v=AAAAAAAAAAA", "date": "2026-11-20"}])

    def test_rss_wordpress_et_lien_refuse(self):
        liens = lire_flux(RSS, SOURCES[1])
        self.assertEqual(len(liens), 1, "adresse javascript: refusée")
        self.assertEqual(liens[0]["titre"], "COBI 2232 Huey im Test – Hubschrauber")
        self.assertEqual(liens[0]["date"], "2026-11-20")

    def test_blog_d_actualites_filtre_les_non_tests(self):
        rss = RSS.replace(b"</channel>", b"""<item><title>COBI 2233 erscheint im Juni</title><link>https://blog.test/x/</link>
            </item><item><title>Black Friday: Cobi 2234 &#8211; Rabatt</title><link>https://blog.test/y/</link></item></channel>""")
        src = {**SOURCES[1], "filtre_tests": True}
        self.assertEqual([x["url"] for x in lire_flux(rss, src)], ["https://blog.test/cobi-2232/"])
        self.assertEqual(len(lire_flux(rss, SOURCES[1])), 3, "sans filtre, tout est gardé")

    def test_flux_illisible(self):
        with self.assertRaises(Exception):
            lire_flux(b"pas du xml", SOURCES[0])


class Rattachement(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dossier = Path(self.tmp.name)
        self.amorce = self.dossier / "amorce.json"
        self.amorce.write_text(json.dumps([
            lien_("yt", "Mould King® 24093 Radlader", "https://y/1"),
            lien_("yt", "Mould King® 24093 Radlader, deuxième avis", "https://y/2", "2026-05-01"),
            lien_("yt", "CaDA C66010 Japanese Tea Shop", "https://y/3"),
            lien_("yt", "Cobi 1686 Titanic", "https://y/4"),
            lien_("yt", "LEGO Star Wars 75342 Tank", "https://y/5", "2025-01-01"),
            lien_("blog-lego", "Gros set 75342 en promotion", "https://b/6", "2026-11-01"),
            lien_("blog-lego", "Vieux set 7965 en promotion", "https://b/7", "2026-11-02"),
            lien_("inconnue", "Mould King 24093 source retirée", "https://z/8"),
            lien_("yt", "Mould King 24093 adresse mauvaise", "ftp://z/9"),
        ]), "utf-8")
        self.t = Tests(self.dossier, amorce=self.amorce, sources=SOURCES)

    def tearDown(self):
        self.tmp.cleanup()

    def test_marque_et_numero_requis(self):
        self.assertEqual([x["url"] for x in self.t.pour("Mould King", "24093")], ["https://y/2", "https://y/1"])
        self.assertEqual(self.t.pour("CaDA", "24093"), [], "autre marque, même numéro")
        self.assertEqual(self.t.pour("Mould King", "24094"), [])
        self.assertEqual(self.t.pour("Mould King", None), [])

    def test_prefixes_et_suffixes(self):
        self.assertEqual(len(self.t.pour("CaDA", "C66010")), 1)
        self.assertEqual(len(self.t.pour("CaDA", "66010")), 1, "numéro de la boutique sans préfixe")
        self.assertEqual(len(self.t.pour("Mould King", "24093S")), 2, "suffixe de variante retiré")

    def test_ordre_recent_dabord_et_champs(self):
        x = self.t.pour("Mould King", "24093")[0]
        self.assertEqual(x, {"source": "Chaîne test", "titre": "Mould King® 24093 Radlader, deuxième avis",
                             "url": "https://y/2", "langue": "de", "type": "video", "date": "2026-05-01"})
        self.assertNotIn("date", self.t.pour("Cobi", "1686")[0])

    def test_lego_officiel(self):
        urls = [x["url"] for x in self.t.pour("LEGO officiel", "75342")]
        self.assertEqual(urls, ["https://b/6", "https://y/5"])
        self.assertEqual([x["type"] for x in self.t.pour("LEGO officiel", "75342")], ["article", "video"])
        self.assertEqual(self.t.pour("LEGO officiel", "7965"), [], "blog LEGO : 5 chiffres au moins")

    def test_annee_jamais_numero(self):
        self.assertEqual(self.t.pour("Cobi", "2026"), [])

    def test_sources_inconnues_ou_adresses_refusees(self):
        urls = {x["url"] for x in self.t.pour("Mould King", "24093")}
        self.assertEqual(urls, {"https://y/1", "https://y/2"})

    def test_tous_les_liens(self):
        self.amorce.write_text(json.dumps([lien_("yt", f"Mould King 24093 avis {i}", f"https://y/{i}", f"2026-01-0{i}")
                                           for i in range(1, 9)]), "utf-8")
        self.t = Tests(self.dossier, amorce=self.amorce, sources=SOURCES)
        r = self.t.pour("Mould King", "24093")
        self.assertEqual(len(r), 8, "aucun plafond : la fiche replie au-delà de trois")
        self.assertEqual(r[0]["date"], "2026-01-08")

    def test_sans_fichiers(self):
        t = Tests(self.dossier / "vide", amorce=self.dossier / "absent.json", sources=SOURCES)
        self.assertEqual(t.pour("Mould King", "24093"), [])


class Releve(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dossier = Path(self.tmp.name)
        self.t = Tests(self.dossier, amorce=self.dossier / "absent.json", sources=SOURCES[:2])

    def tearDown(self):
        self.tmp.cleanup()

    def faux(self, atom=ATOM, rss=RSS, echec=()):
        def recuperer(url, accept="", entetes=None):
            if url in echec:
                raise lien.LienRefuse("le site a répondu 500")
            return lien.Reponse(url, 200, "application/xml", atom if "yt" in url else rss)
        return mock.patch.object(lien, "recuperer", recuperer)

    def test_cumul_sans_doublon_et_signature(self):
        avant = self.t.signature()
        with self.faux():
            r = self.t.relever(pause=0)
            self.assertEqual(r["nouveaux"], 2)
            r = self.t.relever(pause=0)
        self.assertEqual(r["nouveaux"], 0)
        self.assertNotEqual(self.t.signature(), avant, "le cache des sets voit le changement")
        self.assertEqual(len(json.loads(self.t.f_vus.read_text("utf-8"))["liens"]), 2)
        self.assertEqual(len(self.t.pour("Mould King", "24093")), 1)
        self.assertEqual(len(self.t.pour("Cobi", "2232")), 1)

    def test_source_en_echec_n_arrete_pas_les_autres(self):
        with self.faux(echec=("https://exemple.test/yt.xml",)):
            r = self.t.relever(pause=0)
        self.assertEqual((r["yt"], r["nouveaux"]), ("echec", 1))
        self.assertEqual(len(self.t.pour("Cobi", "2232")), 1)

    def test_tout_en_echec_n_ecrit_rien(self):
        with self.faux(echec=("https://exemple.test/yt.xml", "https://exemple.test/feed/")):
            r = self.t.relever(pause=0)
        self.assertTrue(r["tous_en_echec"])
        self.assertFalse(self.t.f_vus.exists())

    def test_flux_illisible_est_un_echec(self):
        with self.faux(atom=b"<html>pas un flux"):
            r = self.t.relever(pause=0)
        self.assertEqual(r["yt"], "echec")

    def test_borne(self):
        with mock.patch.object(tests_auto, "VUS_MAX", 3):
            vus = [lien_("yt", f"Mould King 2409{i} avis", f"https://y/{i}", f"2026-01-0{i}") for i in range(1, 6)]
            self.t.f_vus.write_text(json.dumps({"le": None, "liens": vus}), "utf-8")
            with self.faux():
                self.t.relever(pause=0)
        liens = json.loads(self.t.f_vus.read_text("utf-8"))["liens"]
        self.assertEqual(len(liens), 3)
        self.assertEqual(liens[0]["date"], "2026-11-20", "les plus récents sont gardés")

    def test_fil_quotidien_survit_aux_erreurs(self):
        appels = []

        def relever(pause=1.0):
            appels.append(1)
            raise RuntimeError("panne")
        faux = mock.Mock(derniere_releve=lambda: None, relever=relever)
        # le fil est exécuté en direct : pause de démarrage, puis trois tours en erreur, puis arrêt du test
        with mock.patch.object(tests_auto.time, "sleep", side_effect=[None, None, None, SystemExit]), \
                mock.patch.object(tests_auto.threading, "Thread", lambda target, **k: mock.Mock(start=target)):
            with self.assertRaises(SystemExit):
                tests_auto.demarrer(faux)
        self.assertEqual(len(appels), 3)


class IntegrationIndex(unittest.TestCase):
    OFFRE = {"source": "kbs", "boutique": "KBS", "pays": "Allemagne", "cle": "kbs:bagger", "url": "https://kbs.test/bagger",
             "nom": "Mould King 24093 Radlader", "marque": "Mould King", "numero": "24093", "prix": 99.0,
             "dispo": "vente", "img": None, "pieces": 1200, "dims": None, "type": "technic", "themes": [],
             "depuis": "2026-11-01", "releve": "2026-11-20T00:00:00"}

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dossier = Path(self.tmp.name)
        self.i = Index(self.dossier)
        self.i.tests = Tests(self.dossier, amorce=self.dossier / "amorce.json", sources=SOURCES)
        self.i.enregistrer("kbs", [dict(self.OFFRE)])

    def tearDown(self):
        self.tmp.cleanup()

    def sets(self):
        with mock.patch.object(index_mod, "editorial", return_value=[]), \
                mock.patch.object(index_mod, "editoriales", return_value=[]):
            return self.i.sets(["kbs"])

    def test_champ_absent_sans_lien(self):
        self.assertNotIn("liens_tests", self.sets()[0])

    def test_champ_present_et_cache_invalide(self):
        self.assertNotIn("liens_tests", self.sets()[0])
        time.sleep(0.01)
        (self.dossier / "amorce.json").write_text(json.dumps(
            [lien_("yt", "Mould King® 24093 Radlader", "https://y/1", "2026-11-20")]), "utf-8")
        s = self.sets()[0]
        self.assertEqual(s["liens_tests"], [{"source": "Chaîne test", "titre": "Mould King® 24093 Radlader",
                                              "url": "https://y/1", "langue": "de", "type": "video", "date": "2026-11-20"}])
        # une relève change tests_vus.json : l'index des sets suit sans autre invalidation
        time.sleep(0.01)
        (self.dossier / "tests_vus.json").write_text(json.dumps(
            {"le": None, "liens": [lien_("blog", "Mould King 24093 im Test", "https://b/1", "2026-11-21")]}), "utf-8")
        self.assertEqual([x["url"] for x in self.sets()[0]["liens_tests"]], ["https://b/1", "https://y/1"])

    def test_amorce_du_depot_valide(self):
        amorce = json.loads((index_mod.RACINE / "data" / "tests_amorce.json").read_text("utf-8"))
        ids = {s["id"] for s in tests_auto.sources_tests()}
        for x in amorce:
            self.assertIn(x["source"], ids)
            self.assertTrue(x["url"].startswith("https://") and x["titre"])
        self.assertEqual(len({x["url"] for x in amorce}), len(amorce), "pas de doublon")


if __name__ == "__main__":
    unittest.main()

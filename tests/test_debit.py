"""Débit par site commun à tout le service (app/lien.py) : intervalle entre deux requêtes vers un même
site, pause de tout le service après un 429. Sans réseau : `lien._get` est simulé."""
from __future__ import annotations

import unittest
from unittest import mock

from app import lien


class Debit(unittest.TestCase):
    def setUp(self):
        famille = dict(lien._famille)
        lien._famille.clear()
        lien._famille["cdn.shopify.com"] = lien.SHOPIFY   # état de départ, quels que soient les tests passés avant
        for d in (lien._prochaine, lien._pause, lien._suite_429, lien._dernier_429):
            d.clear()
            self.addCleanup(d.clear)
        self.addCleanup(lambda: (lien._famille.clear(), lien._famille.update(famille)))

    def rep(self, statut=200, attente=None):
        return lien.Reponse("https://kbs-shop.com/a", statut, "text/html", b"x", attente, {})

    def test_intervalle_par_site_tous_modules(self):
        attentes = []
        with mock.patch.object(lien, "_get", return_value=self.rep()), \
                mock.patch.object(lien.time, "sleep", side_effect=attentes.append):
            lien.recuperer("https://kbs-shop.com/a")
            lien.recuperer("https://www.kbs-shop.com/b")    # même site, autre module : attend son tour
            lien.recuperer("https://bausteinreich.de/c")     # autre site : sans attente
        self.assertEqual(len(attentes), 1)
        self.assertAlmostEqual(attentes[0], lien.INTERVALLE_SITE_S, delta=0.1)

    def test_cdn_de_photos_intervalle_court(self):
        self.assertLess(lien.INTERVALLES["cdn.rebrickable.com"], lien.INTERVALLE_SITE_S)

    def test_famille_shopify_file_commune(self):
        """Boutiques Shopify et photos de Shopify : une seule file pour toute la famille."""
        lien.rattacher(["kbs-shop.com", "www.bausteinreich.de"])
        attentes = []
        with mock.patch.object(lien, "_get", return_value=self.rep()), \
                mock.patch.object(lien.time, "sleep", side_effect=attentes.append):
            lien.recuperer("https://kbs-shop.com/a")
            lien.recuperer("https://www.bausteinreich.de/b")
            lien.recuperer("https://cdn.shopify.com/s/files/c.jpg")
            lien.recuperer("https://www.galaxus.fr/d")   # hors famille : sans attente
        self.assertEqual(len(attentes), 2)
        self.assertAlmostEqual(attentes[1], 2 * lien.INTERVALLE_FAMILLE_S, delta=0.2)

    def test_famille_shopify_pause_commune(self):
        lien.rattacher(["kbs-shop.com", "www.bausteinreich.de"])
        with mock.patch.object(lien, "_get", return_value=self.rep(429, "60")) as get, mock.patch.object(lien.time, "sleep"):
            with self.assertRaises(lien.LienRefuse):
                lien.recuperer("https://kbs-shop.com/a")
            for url in ("https://www.bausteinreich.de/b", "https://cdn.shopify.com/c.jpg", "https://x.myshopify.com/d"):
                with self.assertRaises(lien.LienRefuse) as e:
                    lien.recuperer(url)
                self.assertTrue(e.exception.pause)
        self.assertEqual(get.call_count, 1)
        self.assertEqual(lien.en_pause("galaxus.fr"), 0)
        self.assertIn("shopify", lien.pauses())

    def test_hote_shopify_appris_par_sa_reponse(self):
        r = lien.Reponse("https://joygobricks.com/", 200, "text/html", b"x", None, {"powered-by": "Shopify"})
        with mock.patch.object(lien, "_get", return_value=r), mock.patch.object(lien.time, "sleep"):
            lien.recuperer("https://joygobricks.com/")
        self.assertEqual(lien.cle("www.joygobricks.com"), "shopify")

    def test_429_de_suite_pause_doublee_puis_remise_a_zero(self):
        durees = []
        for _ in range(4):
            lien._pause.clear()   # pause écoulée : chaque 429 ouvre un nouvel épisode
            with mock.patch.object(lien, "_get", return_value=self.rep(429, "60")), mock.patch.object(lien.time, "sleep"):
                with self.assertRaises(lien.LienRefuse):
                    lien.recuperer("https://kbs-shop.com/a")
            durees.append(round(lien.en_pause("kbs-shop.com")))
        self.assertEqual(durees, [60, 120, 240, 480])
        lien._pause.clear()
        with mock.patch.object(lien, "_get", return_value=self.rep()), mock.patch.object(lien.time, "sleep"):
            lien.recuperer("https://kbs-shop.com/a")   # réponse acceptée : la suite repart de zéro
        with mock.patch.object(lien, "_get", return_value=self.rep(429, "60")), mock.patch.object(lien.time, "sleep"):
            with self.assertRaises(lien.LienRefuse):
                lien.recuperer("https://kbs-shop.com/a")
        self.assertAlmostEqual(lien.en_pause("kbs-shop.com"), 60, delta=2)
        lien._pause.clear()
        lien._suite_429["kbs-shop.com"] = 40   # plafond : une heure
        lien._noter_429("kbs-shop.com", "60")
        self.assertAlmostEqual(lien.en_pause("kbs-shop.com"), lien.PAUSE_429_MAX_S, delta=2)

    def test_429_met_le_site_en_pause_pour_tout_le_service(self):
        with mock.patch.object(lien, "_get", return_value=self.rep(429, "120")) as get, \
                mock.patch.object(lien.time, "sleep"):
            with self.assertRaises(lien.LienRefuse) as premier:
                lien.recuperer("https://kbs-shop.com/a")
            self.assertTrue(premier.exception.pause)   # le 429 reçu ouvre la pause : même traitement que les suivants
            with self.assertRaises(lien.LienRefuse) as e:
                lien.recuperer("https://www.kbs-shop.com/products.json")   # sans réseau
        self.assertEqual(get.call_count, 1)
        self.assertEqual(e.exception.statut, 429)
        self.assertTrue(e.exception.pause)
        self.assertGreater(lien.en_pause("kbs-shop.com"), 100)
        self.assertEqual(lien.en_pause("bausteinreich.de"), 0)

    def test_429_sans_retry_after_pause_par_defaut(self):
        with mock.patch.object(lien, "_get", return_value=self.rep(429, "Wed, 21 Oct 2026 07:28:00 GMT")), \
                mock.patch.object(lien.time, "sleep"):
            with self.assertRaises(lien.LienRefuse):
                lien.recuperer("https://kbs-shop.com/a")
        self.assertAlmostEqual(lien.en_pause("kbs-shop.com"), lien.PAUSE_429_S, delta=5)

    def test_fin_de_pause_et_bornes(self):
        with mock.patch.object(lien, "_get", return_value=self.rep(429, "1")), mock.patch.object(lien.time, "sleep"):
            with self.assertRaises(lien.LienRefuse):
                lien.recuperer("https://kbs-shop.com/a")
        self.assertAlmostEqual(lien.en_pause("kbs-shop.com"), lien.PAUSE_429_MIN_S, delta=2)
        self.assertEqual(lien.en_pause("kbs-shop.com", maintenant=lien.time.time() + lien.PAUSE_429_MIN_S + 1), 0)
        for valeur, attendu in (("inf", 600), ("1e999", 600), ("nan", 600), ("0", 600), ("-5", 600),
                                ("99999999999", lien.PAUSE_429_MAX_S), ("120", 120)):
            self.assertEqual(lien._attente_s(valeur), attendu, valeur)

    def test_pause_revue_apres_l_attente_de_tour(self):
        """Une requête en file d'attente ne part pas si un 429 arrive pendant qu'elle attend son tour."""
        lien._prochaine["kbs-shop.com"] = lien.time.time() + 5
        def dormir(s):
            lien._noter_429("kbs-shop.com", "600")   # 429 reçu par une autre requête pendant l'attente
        with mock.patch.object(lien, "_get", return_value=self.rep()) as get, mock.patch.object(lien.time, "sleep", side_effect=dormir):
            with self.assertRaises(lien.LienRefuse) as e:
                lien.recuperer("https://kbs-shop.com/a")
        get.assert_not_called()
        self.assertTrue(e.exception.pause)

    def test_adresse_refusee_sans_attendre(self):
        lien._prochaine["exemple.fr"] = lien.time.time() + 30
        with mock.patch.object(lien.time, "sleep") as dormir:
            with self.assertRaises(lien.LienRefuse):
                lien.recuperer("ftp://exemple.fr/a")
        dormir.assert_not_called()

    def test_shopify_n_attend_pas_une_longue_pause(self):
        from app.sources import shopify
        with mock.patch.object(lien, "_get", return_value=self.rep(429)) as get, \
                mock.patch.object(shopify.time, "sleep") as dormir, mock.patch.object(lien.time, "sleep"):
            with self.assertRaises(lien.LienRefuse):
                shopify._page("https://kbs-shop.com/products.json", {}, None)
        self.assertEqual(get.call_count, 1)
        dormir.assert_not_called()   # pause de 600 s : source laissée au passage suivant, sans attente inutile


    def test_rafale_de_429_un_seul_episode(self):
        """Les 429 des requêtes déjà parties, reçus pendant la pause, ne la doublent pas."""
        for _ in range(3):
            lien._noter_429("kbs-shop.com", "60")
        self.assertAlmostEqual(lien.en_pause("kbs-shop.com"), 60, delta=2)

    def test_doublement_depuis_retry_after(self):
        for attendu in (300, 600, 1200):
            lien._pause.clear()
            lien._noter_429("kbs-shop.com", "300")
            self.assertAlmostEqual(lien.en_pause("kbs-shop.com"), attendu, delta=2)

    def test_remise_a_zero_seulement_par_une_boutique_acceptee(self):
        lien.rattacher(["kbs-shop.com"])
        lien._noter_429("kbs-shop.com", "60")
        lien._pause.clear()
        t = lien.time.time() + 1
        for hote, statut in (("cdn.shopify.com", 200), ("kbs-shop.com", 302), ("kbs-shop.com", 403), ("kbs-shop.com", 503)):
            lien._noter_reponse(hote, lien.Reponse(f"https://{hote}/", statut, "", b"", None, {}), t)
            self.assertEqual(lien._suite_429.get("shopify"), 1, (hote, statut))
        lien._noter_reponse("kbs-shop.com", lien.Reponse("https://kbs-shop.com/", 200, "", b"", None, {}), t - 10)
        self.assertEqual(lien._suite_429.get("shopify"), 1)   # partie avant le dernier 429
        lien._noter_reponse("kbs-shop.com", lien.Reponse("https://kbs-shop.com/", 304, "", b"", None, {}), t)
        self.assertNotIn("shopify", lien._suite_429)

    def test_shopify_attend_une_pause_courte(self):
        from app.sources import shopify
        reponses = iter([self.rep(429, "60"), self.rep(200)])
        lien.rattacher(["kbs-shop.com"])
        attentes = []
        def dormir(s):   # la pause s'écoule pendant l'attente
            attentes.append(s)
            lien._pause.clear()
        with mock.patch.object(lien, "_get", side_effect=lambda *a: next(reponses)) as get, \
                mock.patch.object(shopify.time, "sleep", side_effect=dormir):   # même module time que lien.py
            r = shopify._page("https://kbs-shop.com/products.json", {}, None)
        self.assertEqual(r.statut, 200)
        self.assertEqual(get.call_count, 2)
        self.assertEqual(len([s for s in attentes if s > 30]), 1)
        self.assertAlmostEqual(max(attentes), 60, delta=2)   # pause d'une minute : attendue, puis nouvel essai

    def test_hotes_shopify_declares(self):
        from app import boutiques
        hotes = boutiques.hotes_shopify()
        for h in ("kbs-shop.com", "www.bausteinreich.de", "mouldkingcorp.com", "brickplaats.fr"):
            self.assertIn(h, hotes)
        self.assertNotIn("www.galaxus.fr", hotes)
        self.assertEqual(len(hotes), len(set(hotes)))


if __name__ == "__main__":
    unittest.main()

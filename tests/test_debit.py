"""Débit par site commun à tout le service (app/lien.py) : intervalle entre deux requêtes vers un même
site, pause de tout le service après un 429. Sans réseau : `lien._get` est simulé."""
from __future__ import annotations

import unittest
from unittest import mock

from app import lien


class Debit(unittest.TestCase):
    def setUp(self):
        lien._prochaine.clear()
        lien._pause.clear()
        self.addCleanup(lien._prochaine.clear)
        self.addCleanup(lien._pause.clear)

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
        self.assertLess(lien.INTERVALLES["cdn.shopify.com"], lien.INTERVALLE_SITE_S)

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


if __name__ == "__main__":
    unittest.main()

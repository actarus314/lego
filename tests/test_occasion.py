"""Tests des sources d'occasion (app/sources/occasion.py), sans réseau : `_requete` est simulée avec
des réponses de la forme documentée par BrickLink et eBay (aucun appel réel : clés absentes le 23/11/2026)."""
from __future__ import annotations

import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from app.sources import occasion as oc

CLES_BL = {"BRICKLINK_CONSUMER_KEY": "ck", "BRICKLINK_CONSUMER_SECRET": "cs", "BRICKLINK_TOKEN": "tv",
           "BRICKLINK_TOKEN_SECRET": "ts"}


class Signature(unittest.TestCase):
    def test_vecteur_publie_par_x(self):
        # https://docs.x.com/resources/fundamentals/authentication/oauth-1-0a/creating-a-signature
        p = {"include_entities": "true", "status": "Hello Ladies + Gentlemen, a signed OAuth request!",
             "oauth_consumer_key": "xvz1evFS4wEEPTGEFPHBog", "oauth_nonce": "kYjzVBB8Y0ZFabxSWbWovY3uYSQ2pTgmZeNu2VS4cg",
             "oauth_signature_method": "HMAC-SHA1", "oauth_timestamp": "1318622958",
             "oauth_token": "370773112-GmHxMAgYyLbNEtIKZeRNFsMKPR9EyMZeS9weJAEb", "oauth_version": "1.0"}
        self.assertEqual(oc.signature_oauth1("POST", "https://api.twitter.com/1.1/statuses/update.json", p,
                                             "kAcSOqF21Fu85e7zjz7ZN2U4ZRhfV3WpwPAoE3Z7kBw",
                                             "LswwdoUaIvS8ltyTt5jkRh4J50vUPVVHtR2YPi5kE"), "hCtSmYh+iHYCEqBWrE7C7hYmtUk=")

    def test_entete(self):
        h = oc.entete_oauth1("GET", "https://api.bricklink.com/x", {"a": "1"},
                             {"consumer_key": "ck", "consumer_secret": "cs", "token": "tv", "token_secret": "ts"}, "n", 1)
        self.assertTrue(h.startswith('OAuth realm="", oauth_consumer_key="ck", oauth_token="tv"'))
        self.assertIn('oauth_signature="', h)


class Cles(unittest.TestCase):
    def test_sans_cle_sources_eteintes(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual({k: v for k, v in oc.Occasion.actives().items() if k in ("bricklink", "ebay")},
                             {"bricklink": False, "ebay": False})
        with mock.patch.dict(os.environ, {**CLES_BL, "EBAY_APP_ID": "a"}, clear=True):
            self.assertEqual(oc.Occasion.actives()["bricklink"], True)
            self.assertEqual(oc.Occasion.actives()["ebay"], False)


class Formats(unittest.TestCase):
    def test_bricklink(self):
        stock = {"currency_code": "EUR", "min_price": "310.0000", "avg_price": "402.5000", "max_price": "520.0000",
                 "unit_quantity": 14, "total_quantity": 15}
        r = oc.resume_bricklink(stock, {"avg_price": "380.1200", "total_quantity": 42}, "10294")
        self.assertEqual((r["annonces"]["min"], r["annonces"]["lots"], r["ventes_6_mois"]["moyen"]), (310.0, 14, 380.12))
        self.assertIn("S=10294-1", r["url"])

    def test_bricklink_erreur(self):
        with mock.patch.object(oc, "_requete", return_value={"meta": {"code": 401, "message": "BAD_OAUTH_REQUEST"}}):
            with self.assertRaises(ValueError):
                oc.guide_bricklink("10294", {"consumer_key": "a", "consumer_secret": "b", "token": "c", "token_secret": "d"}, "stock")

    def test_titres_ebay(self):
        cas = [("LEGO Icons 10294 Titanic complet avec notice", True), ("Notice LEGO 10294 Titanic", False),
               ("LEGO 102945 lot", False), ("Boîte vide LEGO 10294", False), ("Titanic 10294 compatible", False),
               ("LEGO 10294 notice seule", False), ("LEGO 10294 incomplet", False), ("LEGO 10294 pour pièces", False), ("Stickers LEGO 10294", False), ("LEGO 10294 sans boîte, complet", True),
               ("LEGO Star Wars 75192-1 Millennium Falcon", False), ("lego 75192 Faucon Millenium", False)]
        for titre, attendu in cas:
            with self.subTest(titre):
                self.assertEqual(oc.titre_du_set(titre, "10294"), attendu)

    def test_annonce_ebay(self):
        x = {"title": "LEGO 10294 Titanic", "price": {"value": "450.00", "currency": "EUR"}, "condition": "Occasion",
             "itemWebUrl": "https://www.ebay.fr/itm/1", "seller": {"feedbackScore": 120, "feedbackPercentage": "100.0",
                                                                   "sellerAccountType": "INDIVIDUAL"},
             "shippingOptions": [{"shippingCost": {"value": "19.90"}}, {"shippingCost": {"value": "12.00"}}],
             "itemLocation": {"country": "FR"}}
        a = oc.annonce_ebay(x)
        self.assertEqual((a["prix"], a["port"], a["vendeur"], a["pays"]), (450.0, 12.0, "particulier", "FR"))
        self.assertIsNone(oc.annonce_ebay({"title": "x"}))
        self.assertEqual(oc.resume_ebay([a])["min_port_compris"], 462.0)
        inconnu = {**a, "prix": 300.0, "port": None}
        r = oc.resume_ebay([inconnu, {**a, "prix": 310.0, "port": 0.0}])
        self.assertEqual((r["min_port_compris"], r["annonces"][0]["prix"]), (310.0, 310.0))   # port inconnu jamais compté 0
        self.assertIsNone(oc.resume_ebay([inconnu])["min_port_compris"])
        self.assertEqual(oc.resume_ebay([a] * 12)["nombre"], 12)


class SansEbay(unittest.TestCase):
    """`pour()` lit eBay si ses clés sont dans l'environnement : les tests s'en isolent."""

    def setUp(self):
        env = mock.patch.dict(os.environ, {k: v for k, v in os.environ.items() if not k.startswith(("EBAY_", "BRICKLINK_"))},
                              clear=True)
        env.start()
        self.addCleanup(env.stop)


class Releve(SansEbay):
    def test_hebdomadaire_et_arret_apres_trois_echecs(self):
        o = oc.Occasion(Path(tempfile.mkdtemp()))
        donnee = {"meta": {"code": 200}, "data": {"currency_code": "EUR", "min_price": "1", "avg_price": "2",
                                                  "max_price": "3", "unit_quantity": 1, "total_quantity": 1}}
        with mock.patch.dict(os.environ, CLES_BL, clear=True), mock.patch.object(oc, "_requete", return_value=donnee) as m:
            self.assertEqual(o.relever(["10294", "75192"], pause=0)["bricklink"], 2)
            self.assertEqual(m.call_count, 4)                       # annonces et ventes, par set
            o.relever(["10294"], pause=0)                           # relu il y a moins de 7 jours : rien
            self.assertEqual(m.call_count, 4)
        self.assertEqual(o.pour("10294")["bricklink"]["annonces"]["moyen"], 2.0)
        with mock.patch.dict(os.environ, CLES_BL, clear=True), \
                mock.patch.object(oc, "_requete", side_effect=OSError("refus")) as m:
            o.relever([str(n) for n in range(1000, 1010)], pause=0, maintenant=time.time() + 8 * 86400)
        self.assertEqual(m.call_count, 3)
        self.assertIn("refus", o.etat()["bricklink"]["erreur"])

    def test_sets_inconnus_n_arretent_pas_la_source(self):
        o = oc.Occasion(Path(tempfile.mkdtemp()))
        ok = {"meta": {"code": 200}, "data": {"currency_code": "EUR", "min_price": "1", "avg_price": "2", "unit_quantity": 3}}

        def rep(url, entetes, donnees=None):
            return {"meta": {"code": 404, "message": "NOT_FOUND"}} if "/9000" in url else ok
        with mock.patch.dict(os.environ, CLES_BL, clear=True), mock.patch.object(oc, "_requete", side_effect=rep):
            r = o.relever(["90001", "90002", "90003", "10294", "75192"], pause=0)
        self.assertEqual(r["bricklink"], 5)
        self.assertTrue(o.pour("90001")["bricklink"]["absent"])
        self.assertEqual(o.pour("10294")["bricklink"]["annonces"]["moyen"], 2.0)
        self.assertEqual(o.etat()["bricklink"]["avec_offre"], 2)

    def test_ebay_a_la_demande_garde_6_heures(self):
        o = oc.Occasion(Path(tempfile.mkdtemp()))
        jeton = {"access_token": "j", "expires_in": 7200}
        annonce = {"title": "LEGO 10294 Titanic", "price": {"value": "450.00"}, "itemWebUrl": "https://www.ebay.fr/itm/1"}
        rep = lambda url, entetes, donnees=None: jeton if "oauth2" in url else {"itemSummaries": [annonce]}
        oc.JETON.valeur = None
        with mock.patch.dict(os.environ, {"EBAY_APP_ID": "a", "EBAY_CERT_ID": "c"}, clear=True), \
                mock.patch.object(oc, "_requete", side_effect=rep) as m:
            self.assertEqual(o.pour("10294")["ebay"]["annonces"][0]["prix"], 450.0)
            n = m.call_count
            o.pour("10294")                                         # gardée : aucun appel
            self.assertEqual(m.call_count, n)
            o.pour("10294", maintenant=time.time() + 6 * 3600 + 1)  # plus de 6 h : relue
            self.assertEqual(m.call_count, n + 1)
        self.assertNotIn("10294", o.lire())                          # jamais écrite sur le disque
        oc.JETON.valeur = None

    def test_ebay_en_echec_pas_retente_avant_10_minutes(self):
        o = oc.Occasion(Path(tempfile.mkdtemp()))
        oc.JETON.valeur = None
        with mock.patch.dict(os.environ, {"EBAY_APP_ID": "a", "EBAY_CERT_ID": "c"}, clear=True), \
                mock.patch.object(oc, "_requete", side_effect=OSError("401")) as m:
            for _ in range(5):
                self.assertNotIn("ebay", o.pour("10294"))
            self.assertEqual(m.call_count, 1)
            o.pour("10294", maintenant=time.time() + 601)
            self.assertEqual(m.call_count, 2)


class Boutiques(SansEbay):
    from app.sources import occasion_boutiques as ob

    def test_brickplaats(self):
        p = [{"title": "LEGO® Vespa 125 10298 Building Kit (1,106 Pieces)", "handle": "vespa",
              "options": [{"name": "État", "values": ["D’occasion", "Nouveau"]}],
              "variants": [{"option1": "D’occasion", "price": "49.99", "available": True},
                           {"option1": "Nouveau", "price": "89.99", "available": True}]},
             {"title": "Set 21028 - New York City", "handle": "nyc", "options": [{"name": "Conditie", "values": ["Gebruikt"]}],
              "variants": [{"option1": "Gebruikt", "price": "21.49", "available": False}]},
             {"title": "LEGO 10298 et 21028 en lot", "handle": "lot", "options": [{"name": "État", "values": ["Utilisé"]}],
              "variants": [{"option1": "Utilisé", "price": "60", "available": True}]},
             {"title": "Minifigure 10298", "handle": "fig", "options": [{"name": "Title", "values": ["Default"]}],
              "variants": [{"option1": "Default Title", "price": "3", "available": True}]}]
        r = self.ob.annonces_brickplaats(p, {"10298", "21028"})
        self.assertEqual(sorted(r), ["10298", "21028"])
        self.assertEqual([(a["prix"], a["etat"]) for a in r["10298"]], [(49.99, "D'occasion")])   # neuf écarté
        self.assertFalse(r["21028"][0]["dispo"])

    def test_brickland(self):
        p = [{"name": "LEGO Hogsmeade, réf. 76457", "sku": "76457", "prices": {"price": "36999", "currency_minor_unit": 2,
              "currency_code": "EUR"}, "is_in_stock": True, "permalink": "https://brickland.fr/produit/x/",
              "attributes": [{"name": "état du set", "terms": [{"name": "boîte oui"}, {"name": "notice papier"}]}]}]
        a = self.ob.annonces_brickland(p, {"76457"})["76457"][0]
        self.assertEqual((a["prix"], a["etat"]), (369.99, "reconditionné (boîte oui, notice papier)"))

    def test_annonces_remplacees_et_perimees(self):
        o = oc.Occasion(Path(tempfile.mkdtemp()))
        une = {"prix": 10.0, "etat": "Utilisé", "dispo": True, "vendeur": "professionnel", "titre": "t", "pays": "NL", "url": "u"}
        with mock.patch.dict(self.ob.LECTEURS, {"brickplaats": lambda c, p: {"10298": [une]}, "brickland": lambda c, p: {}}):
            o.relever_boutiques(["10298"], pause=0)
        self.assertEqual(o.pour("10298")["brickplaats"]["nombre"], 1)
        with mock.patch.dict(self.ob.LECTEURS, {"brickplaats": lambda c, p: {}, "brickland": lambda c, p: {}}):
            o.relever_boutiques(["10298"], pause=0)
        self.assertNotIn("brickplaats", o.pour("10298"))           # vendu : retiré
        with mock.patch.dict(self.ob.LECTEURS, {"brickplaats": lambda c, p: {"10298": [une]}, "brickland": lambda c, p: {}}):
            o.relever_boutiques(["10298"], pause=0)
        self.assertNotIn("brickplaats", o.pour("10298", maintenant=time.time() + 3 * 86400))   # relevé de plus de 2 jours
        with mock.patch.dict(self.ob.LECTEURS, {"brickplaats": mock.Mock(side_effect=OSError("x")), "brickland": lambda c, p: {}}):
            o.relever_boutiques(["10298"], pause=0)
        self.assertEqual(o.pour("10298")["brickplaats"]["nombre"], 1)   # source en échec : relevé précédent gardé
        self.assertIn("brickplaats", o.etat())
        # brickplaats en échec au dernier passage : retentée au suivant ; brickland lue (sans set rapproché) : pas avant 20 h
        self.assertEqual(o.boutiques_a_relire(), [])               # brickplaats lue avec succès au passage d'avant
        self.assertEqual(o.boutiques_a_relire(maintenant=time.time() + 21 * 3600), ["brickplaats", "brickland"])
        with mock.patch.dict(self.ob.LECTEURS, {"brickplaats": mock.Mock(side_effect=OSError("x")), "brickland": lambda c, p: {}}):
            o2 = oc.Occasion(Path(tempfile.mkdtemp()))
            o2.relever_boutiques(["10298"], pause=0)
        self.assertEqual(o2.boutiques_a_relire(), ["brickplaats"])
        self.assertNotIn(oc.RELEVES, o2.etat())
        self.assertEqual(o.relever_boutiques([], pause=0), {})        # catalogue de l'outil pas prêt : aucune lecture

    def test_lecture_vide_ou_coupee_est_une_erreur(self):
        page = {"products": [{"title": "LEGO 10298", "handle": "v", "options": [{"name": "État"}],
                              "variants": [{"option1": "Utilisé", "price": "5", "available": True, "id": 7}]}]}
        with mock.patch.object(self.ob, "_json", side_effect=lambda u: {"products": []}):
            with self.assertRaises(self.ob.LectureIncomplete):
                self.ob.LECTEURS["brickplaats"]({"10298"}, 0)
        with mock.patch.object(self.ob, "_json", return_value=page), mock.patch.object(self.ob, "PAGES_MAX", 3):
            with self.assertRaises(self.ob.LectureIncomplete):
                self.ob.LECTEURS["brickplaats"]({"10298"}, 0)
        pages = iter([page, {"products": []}])
        with mock.patch.object(self.ob, "_json", side_effect=lambda u: next(pages)):
            r = self.ob.LECTEURS["brickplaats"]({"10298"}, 0)
        self.assertEqual(r["10298"][0]["url"], "https://brickplaats.fr/products/v?variant=7")
        self.assertEqual((r["10298"][0]["port"], r["10298"][0]["vendeur"]), (None, "professionnel"))
        self.assertIn("non publié", r["10298"][0]["port_note"])

    def test_titres_exclus_et_produits_mal_formes(self):
        def produit(titre, handle="h"):
            return {"title": titre, "handle": handle, "options": [{"name": "État"}],
                    "variants": [{"option1": "D’occasion", "price": "5", "available": True}]}
        p = [produit("Notice LEGO 10298"), produit("LEGO 10298 incomplet"), None, {"title": 5},
             produit("LEGO 10298", handle='a b"c'), produit("LEGO 10298 Vespa")]
        r = self.ob.annonces_brickplaats(p, {"10298"})
        self.assertEqual([a["titre"] for a in r["10298"]], ["LEGO 10298 Vespa"])
        for neuf in ("Unused", "Ongebruikt", "Niet gebruikt", "Jamais utilisé", "Non-utilisé", "Nouveau", "Nieuw"):
            with self.subTest(neuf):
                self.assertEqual(self.ob.annonces_brickplaats([{"title": "LEGO 10298", "handle": "x", "options": [{"name": "État"}],
                                 "variants": [{"option1": neuf, "price": "5"}]}], {"10298"}), {})
        for exclu in ("LEGO 10298 pièce manquante", "LEGO 10298 missing pieces", "LEGO 10298 fehlende Teile"):
            self.assertFalse(oc.titre_du_set(exclu, "10298"), exclu)

    def test_brickland_adresse_et_sku(self):
        base = {"name": "LEGO Hogsmeade, réf. 76457", "sku": "", "prices": {"price": "36999", "currency_code": "EUR"},
                "is_in_stock": True, "attributes": [{"name": "état du set", "terms": [{"x": 1}]}]}
        self.assertEqual(self.ob.annonces_brickland([{**base, "permalink": "javascript:alert(1)"}], {"76457"}), {})
        self.assertEqual(self.ob.annonces_brickland([{**base, "permalink": None}], {"76457"}), {})
        for mauvais in ("https://[::1", "https://evil.com\\@brickland.fr/x", "http://brickland.fr/x"):
            self.assertEqual(self.ob.annonces_brickland([{**base, "permalink": mauvais},
                                                         {**base, "sku": "76457", "permalink": "https://www.brickland.fr/p/"}],
                                                        {"76457"})["76457"][0]["url"], "https://www.brickland.fr/p/")
        r = self.ob.annonces_brickland([{**base, "permalink": "https://brickland.fr/produit/x/"}], {"76457"})
        self.assertEqual(r["76457"][0]["prix"], 369.99)                       # numéro repris du nom sans SKU


if __name__ == "__main__":
    unittest.main()

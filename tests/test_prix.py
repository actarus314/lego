"""v3.15 : historique des prix, prix barré, requêtes conditionnelles, signaux bruts, relecture de la sélection."""
import copy
import json
import tempfile
import unittest
from pathlib import Path

from app import lien
from app.historique import Historique
from app.index import Index
from app.sources import shopify

SOURCE = {"id": "kbs", "nom": "KBS", "type": "shopify", "hote": "kbs-shop.com", "prefixe": "/en",
          "pays_boutique": "Allemagne", "seuil_pieces": 500, "seuil_prix": 50.0}
PRODUIT = {"title": "Mould King 13199 Pirate Ship", "handle": "pirate-13199", "vendor": "Mould King",
           "product_type": "Bausteine", "tags": ["Mould King"], "body_html": "<p>3180 pieces</p>",
           "variants": [{"price": "184.95", "compare_at_price": "219.95", "available": True, "sku": "13199"}],
           "images": [{"src": "https://cdn/x.jpg"}]}


class HistoriquePrix(unittest.TestCase):
    def test_un_point_par_jour_et_plus_bas_sur_30_jours(self):
        with tempfile.TemporaryDirectory() as d:
            h = Historique(Path(d), ecriture_s=0)
            h.noter([{"cle": "kbs:a", "prix": 120.0, "dispo": "vente"}], jour="2026-10-01")   # hors fenêtre de 30 jours
            h.noter([{"cle": "kbs:a", "prix": 100.0, "dispo": "vente"}], jour="2026-11-10")
            h.noter([{"cle": "kbs:a", "prix": 110.0, "barre": 130.0, "dispo": "vente"}], jour="2026-11-20")
            h.noter([{"cle": "kbs:a", "prix": 90.0, "dispo": "vente"}], jour="2026-11-21")
            h.noter([{"cle": "kbs:a", "prix": 95.0, "dispo": "vente"}], jour="2026-11-21")   # même jour : remplace
            h.noter([{"cle": "kbs:b", "prix": None, "dispo": "vente"}, {"prix": 5}], jour="2026-11-21")  # ignorés
            relu = Historique(Path(d))   # relu depuis le fichier
            serie = relu._charger()["kbs:a"]
            self.assertEqual([p[0] for p in serie], ["2026-10-01", "2026-11-10", "2026-11-20", "2026-11-21"])
            self.assertEqual(serie[-1][1], 95.0)
            self.assertEqual(serie[2][2], 130.0, "prix barré gardé")
            self.assertNotIn("kbs:b", relu._charger())
            r = relu.resume("kbs:a", aujourd_hui="2026-11-21")
            self.assertEqual((r["min30"], r["jours"]), (100.0, 11), "jour même exclu, 1er octobre hors fenêtre ; du 10 au 21 novembre")
            self.assertIsNone(relu.resume("kbs:z"))
            self.assertIsNone(relu.resume("kbs:a", aujourd_hui="2026-10-01"), "aucun point avant le jour même")

    def test_ecriture_differee(self):
        with tempfile.TemporaryDirectory() as d:
            h = Historique(Path(d), ecriture_s=0.3)
            h.noter([{"cle": "k", "prix": 1.0}], jour="2026-11-20")   # première écriture : tout de suite
            h.noter([{"cle": "k", "prix": 2.0}], jour="2026-11-21")   # suivante : différée
            self.assertEqual(len(Historique(Path(d))._charger()["k"]), 1)
            import time
            time.sleep(0.6)
            self.assertEqual(len(Historique(Path(d))._charger()["k"]), 2)

    def test_promotion_stable_et_remise_douteuse(self):
        with tempfile.TemporaryDirectory() as d:
            h = Historique(Path(d), ecriture_s=0)
            # remise réelle : 200 avant, 180 barré 200 depuis trois jours
            for j, prix, barre in (("2026-11-15", 200.0, None), ("2026-11-18", 180.0, 200.0), ("2026-11-20", 180.0, 200.0)):
                h.noter([{"cle": "r", "prix": prix, "barre": barre, "dispo": "vente"}], jour=j)
            r = h.resume("r", aujourd_hui="2026-11-21")
            self.assertEqual((r["min30"], r["avant_remise"], r["avant_remise_j"]), (180.0, 200.0, 3))
            # remise douteuse : 150 avant, puis 180 barré 220
            for j, prix, barre in (("2026-11-15", 150.0, None), ("2026-11-19", 180.0, 220.0)):
                h.noter([{"cle": "f", "prix": prix, "barre": barre, "dispo": "vente"}], jour=j)
            self.assertEqual(h.resume("f", aujourd_hui="2026-11-21")["avant_remise"], 150.0)
            # remise dès le premier relevé : aucune référence
            h.noter([{"cle": "n", "prix": 180.0, "barre": 220.0, "dispo": "vente"}], jour="2026-11-20")
            self.assertNotIn("avant_remise", h.resume("n", aujourd_hui="2026-11-21"))
            # jour épuisé au milieu de la remise : ne la coupe pas
            for j, prix, barre, dispo in (("2026-11-10", 200.0, None, "vente"), ("2026-11-12", 180.0, 220.0, "vente"),
                                          ("2026-11-15", 180.0, None, "epuise"), ("2026-11-16", 180.0, 220.0, "vente")):
                h.noter([{"cle": "g", "prix": prix, "barre": barre, "dispo": dispo}], jour=j)
            self.assertEqual(h.resume("g", aujourd_hui="2026-11-21")["avant_remise"], 200.0)
            # jour épuisé : ne compte pas comme prix pratiqué
            h.noter([{"cle": "e", "prix": 10.0, "dispo": "epuise"}], jour="2026-11-19")
            self.assertIsNone(h.resume("e", aujourd_hui="2026-11-21"))

    def test_fichier_illisible(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "historique_prix.json").write_text('{"offres": {"k": [["2026-11-2')
            h = Historique(Path(d), ecriture_s=0)
            self.assertIsNone(h.resume("k"))
            self.assertTrue((Path(d) / "historique_prix.illisible").exists())
            h.noter([{"cle": "k", "prix": 1.0}], jour="2026-11-21")
            self.assertEqual(len(Historique(Path(d))._charger()["k"]), 1)

    def test_points_mal_formes_ignores(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "historique_prix.json").write_text(json.dumps({"offres": {"m": [
                None, ["2026-11-19"], ["2026-11-19", "x", None, None], ["2026-11-20", 5.0, None, "vente"]]}}))
            self.assertEqual(Historique(Path(d)).resume("m", aujourd_hui="2026-11-21"), {"min30": 5.0, "jours": 1})

    def test_points_anciens_retires(self):
        with tempfile.TemporaryDirectory() as d:
            h = Historique(Path(d))
            h.noter([{"cle": "k", "prix": 1.0}], jour="2026-01-01")
            h.noter([{"cle": "partie", "prix": 1.0}], jour="2026-03-01")
            h.noter([{"cle": "k", "prix": 2.0}], jour="2026-11-21")
            self.assertEqual([p[0] for p in h._charger()["k"]], ["2026-11-21"])
            self.assertNotIn("partie", h._charger(), "offre disparue : série retirée")

    def test_alimente_par_l_index(self):
        with tempfile.TemporaryDirectory() as d:
            i = Index(Path(d))
            o = shopify.offre(copy.deepcopy(PRODUIT), SOURCE)
            i.enregistrer("kbs", [o])
            i.maj_offre("kbs", o["cle"], {"prix": 170.0, "dispo": "vente"})
            serie = i.historique.serie(o["cle"])
            self.assertEqual(len(serie), 1, "deux lectures le même jour : un point")
            self.assertEqual(serie[0][1], 170.0)


class PrixBarre(unittest.TestCase):
    def test_compare_at_price(self):
        o = shopify.offre(copy.deepcopy(PRODUIT), SOURCE)
        self.assertEqual((o["prix"], o["barre"]), (184.95, 219.95))
        p = copy.deepcopy(PRODUIT)
        p["variants"][0]["compare_at_price"] = "184.95"   # égal au prix : pas de prix barré
        self.assertIsNone(shopify.offre(p, SOURCE)["barre"])
        p["variants"][0]["compare_at_price"] = None
        self.assertIsNone(shopify.offre(p, SOURCE)["barre"])
        self.assertEqual(shopify._barre({"compare_at_price": 21995}, 184.95, centimes=True), 219.95)

    def test_relecture_directe(self):
        from app import synchro
        vrai = lien.recuperer
        js = {"title": "x", "available": True, "tags": [], "variants": [{"price": 17000, "compare_at_price": 21995, "available": True}]}
        try:
            lien.recuperer = lambda url, **k: lien.Reponse(url, 200, "application/json", json.dumps(js).encode())
            with tempfile.TemporaryDirectory() as d:
                i = Index(Path(d))
                o = shopify.offre(copy.deepcopy(PRODUIT), SOURCE)
                i.enregistrer("kbs", [o])
                r = synchro.offre_directe(i, o["cle"])
                self.assertEqual((r["prix"], r["barre"]), (170.0, 219.95))
        finally:
            lien.recuperer = vrai


class PagesConditionnelles(unittest.TestCase):
    def test_304_reprend_la_page_gardee(self):
        vrai = lien.recuperer
        appels = []
        corps = json.dumps({"products": [PRODUIT]}).encode()

        def faux(url, accept=None, entetes=None, statuts=(200,), **k):
            appels.append((entetes or {}).get("If-None-Match"))
            if (entetes or {}).get("If-None-Match") == 'W/"v1"':
                self.assertIn(304, statuts)
                return lien.Reponse(url, 304, "", b"", entetes={})
            return lien.Reponse(url, 200, "application/json", corps, entetes={"etag": 'W/"v1"'})
        try:
            lien.recuperer = faux
            with tempfile.TemporaryDirectory() as d:
                pages = shopify.Pages(Path(d) / "pages" / "kbs")
                c1, c2 = {}, {}
                a = shopify.lire(SOURCE, pause=0, pages=pages, compte=c1)
                b = shopify.lire(SOURCE, pause=0, pages=pages, compte=c2)
                self.assertEqual(appels, [None, 'W/"v1"'])
                self.assertEqual((c1["inchangees"], c2["inchangees"], c2["octets"]), (0, 1, 0))
                self.assertEqual([o["cle"] for o in a], [o["cle"] for o in b])
                (Path(d) / "pages" / "kbs" / "1.json.gz").write_bytes(b"abime")   # fichier illisible : relue en entier
                shopify.lire(SOURCE, pause=0, pages=pages, compte={})
                self.assertEqual(appels[-1], None)
                import gzip   # page gardée au JSON abîmé, la boutique répond 304 : oubliée, relue sans condition
                (Path(d) / "pages" / "kbs" / "1.json.gz").write_bytes(gzip.compress(json.dumps(
                    {"url": "https://kbs-shop.com/en/products.json?limit=250&page=1", "etag": 'W/"v1"', "corps": "<html>"}).encode()))
                n = len(appels)
                self.assertEqual(len(shopify.lire(SOURCE, pause=0, pages=pages, compte={})), 1)
                self.assertEqual(appels[n:], ['W/"v1"', None])
        finally:
            lien.recuperer = vrai


    def test_corps_illisible_non_garde(self):
        vrai = lien.recuperer
        try:
            lien.recuperer = lambda url, **k: lien.Reponse(url, 200, "text/html", b"<html>maintenance</html>", entetes={"etag": '"x"'})
            with tempfile.TemporaryDirectory() as d:
                pages = shopify.Pages(Path(d))
                with self.assertRaises(ValueError):
                    shopify.lire(SOURCE, pause=0, pages=pages, compte={})
                self.assertFalse((Path(d) / "1.json.gz").exists())
        finally:
            lien.recuperer = vrai


class SignauxBruts(unittest.TestCase):
    def test_type_recalcule_a_la_reconstruction(self):
        from app import normalise
        with tempfile.TemporaryDirectory() as d:
            i = Index(Path(d))
            o = shopify.offre(copy.deepcopy(PRODUIT), SOURCE)
            o["type"], o["themes"] = "technic", ["espace"]   # valeurs calculées par une règle d'avant
            i.enregistrer("kbs", [o])
            s = next(x for x in i.sets(["kbs"]) if x["numero"] == "13199")
            sig = o["signaux"]
            self.assertEqual(s["themes"], normalise.themes(sig["titre"], sig["etiquettes"], sig["categorie"]))
            self.assertNotEqual(s["themes"], ["espace"])


class SelectionHoraire(unittest.TestCase):
    def test_relit_les_offres_de_boutique_des_sets_suivis(self):
        from app import synchro
        vrai_od, vrai_act = synchro.offre_directe, synchro.actives
        relues = []
        try:
            synchro.offre_directe = lambda index, cle: relues.append(cle) or {}
            synchro.actives = lambda: [{"id": "kbs"}]
            with tempfile.TemporaryDirectory() as d:
                i = Index(Path(d))
                o = shopify.offre(copy.deepcopy(PRODUIT), SOURCE)
                autre = shopify.offre({**copy.deepcopy(PRODUIT), "handle": "autre-13199"}, SOURCE)
                i.enregistrer("kbs", [o, autre])
                r = synchro.relire_selection(i, [{"url": o["url"] + "/"}, {"url": o["url"], "statut": "achete"},
                                                 {"url": "https://ailleurs.example/p"}], pause=0)
                self.assertEqual(sorted(relues), sorted([o["cle"], autre["cle"]]), "toutes les offres du set, une fois")
                self.assertEqual((r["offres"], r["lus"], r["echecs"]), (2, 2, 0))
                # exception inattendue sur la première : la suivante est lue ; 429 : boutique laissée
                relues.clear()

                def panne(index, cle):
                    relues.append(cle)
                    raise TypeError("price null")
                synchro.offre_directe = panne
                r = synchro.relire_selection(i, [{"url": o["url"]}], pause=0)
                self.assertEqual((len(relues), r["echecs"]), (2, 2))
                relues.clear()

                def refus(index, cle):
                    relues.append(cle)
                    e = lien.LienRefuse("le site a répondu 429"); e.statut = 429
                    raise e
                synchro.offre_directe = refus
                r = synchro.relire_selection(i, [{"url": o["url"]}], pause=0)
                self.assertEqual((len(relues), r["echecs"]), (1, 2))
        finally:
            synchro.offre_directe, synchro.actives = vrai_od, vrai_act


if __name__ == "__main__":
    unittest.main()

"""Complétude du catalogue par champ (app/completude.py) et sa surveillance."""
import tempfile
import unittest
from pathlib import Path

from app import completude as c


def set_(**k):
    s = {"themes": ["voitures"], "type": "classique", "dims": [40.0], "dispo": "vente",
         "offres": [{"port": 4.95, "delai": "1 à 3 jours ouvrés"}]}
    s.update(k)
    return s


class Compter(unittest.TestCase):
    def test_mesure_estime_manque(self):
        sets = [set_(), set_(themes=[], dims=None, type=None, offres=[{"port": None}]),
                set_(type="technic", type_estime="série", offres=[{"port": 9.95, "port_estime": True}]),
                set_(dispo="epuise", liens_tests=[{"url": "x"}], themes=[])]
        r = c.compter(sets)
        self.assertEqual((r["sets"], r["en_vente"]), (4, 3))
        ch = r["champs"]
        self.assertEqual(ch["theme"]["tous"], {"mesure": 2, "estime": 0, "manque": 2})
        self.assertEqual(ch["theme"]["en_vente"], {"mesure": 2, "estime": 0, "manque": 1}, "l'épuisé ne compte pas en vente")
        self.assertEqual(ch["dimensions"]["tous"], {"mesure": 3, "estime": 0, "manque": 1})
        self.assertEqual(ch["type"]["en_vente"], {"mesure": 1, "estime": 1, "manque": 1}, "type par la série : estimé")
        self.assertEqual(ch["port"]["en_vente"], {"mesure": 1, "estime": 1, "manque": 1})
        self.assertEqual(ch["delai"]["en_vente"]["manque"], 2, "offres sans délai")
        self.assertEqual(ch["avis"]["tous"]["mesure"], 1)
        self.assertTrue(ch["univers"]["facultatif"])
        self.assertEqual(c.compter([])["champs"]["theme"]["tous"], {"mesure": 0, "estime": 0, "manque": 0})

    def test_dimensions_estimees(self):
        r = c.compter([set_(), set_(dims=None, dims_estimees=[52.0], dims_estime="pièces, type et thème"), set_(dims=None)])
        self.assertEqual(r["champs"]["dimensions"]["tous"], {"mesure": 1, "estime": 1, "manque": 1})

    def test_set_sans_offre(self):
        r = c.compter([set_(offres=[])])
        self.assertEqual(r["champs"]["port"]["tous"]["manque"], 1)


def passage(themes_ok, total=100):
    return {"completude": {"champs": {"theme": {"en_vente": {"mesure": themes_ok, "estime": 0, "manque": total - themes_ok}}}}}


class Degradations(unittest.TestCase):
    def test_baisse_signalee(self):
        self.assertEqual(c.degradations([passage(95), passage(96), passage(95), passage(97)]), {})
        d = c.degradations([passage(80), passage(96), passage(95), passage(97)])
        self.assertEqual(list(d), ["completude:theme"])
        self.assertIn("80 sets en vente avec une valeur mesurée sur 100", d["completude:theme"])
        self.assertIn("96 %", d["completude:theme"])

    def test_seuils(self):
        self.assertEqual(c.degradations([passage(80), passage(96)]), {}, "deux passages de référence au moins")
        self.assertEqual(c.degradations([passage(91), passage(96), passage(95), passage(97)]), {}, "moins de 5 points")
        self.assertEqual(c.degradations([passage(8, 10), passage(10, 10), passage(10, 10)]), {}, "trop peu de sets")
        petit = [passage(170, 200), passage(190, 200), passage(190, 200)]
        self.assertEqual(list(c.degradations(petit)), ["completude:theme"])
        self.assertEqual(c.degradations([passage(85, 100)] + [{"sources": []}] + [passage(96), passage(96)]),
                         {"completude:theme": c.degradations([passage(85), passage(96), passage(96)])["completude:theme"]},
                         "passages sans complétude ignorés")
        self.assertEqual(c.degradations([{"completude": {"champs": {}}}, passage(96), passage(96)]), {})

    def test_estimations_ne_masquent_pas_la_baisse(self):
        p = {"completude": {"champs": {"theme": {"en_vente": {"mesure": 50, "estime": 50, "manque": 0}}}}}
        self.assertEqual(list(c.degradations([p, passage(95), passage(95)])), ["completude:theme"])

    def test_cinq_points_exactement(self):
        self.assertEqual(list(c.degradations([passage(180, 200), passage(190, 200), passage(190, 200)])), ["completude:theme"])

    def test_univers_non_surveille(self):
        u = lambda k: {"completude": {"champs": {"univers": {"en_vente": {"mesure": k, "estime": 0, "manque": 100 - k}}}}}
        self.assertEqual(c.degradations([u(10), u(40), u(40)]), {}, "facultatif : suit la composition du catalogue")

    def test_hausse_non_signalee(self):
        self.assertEqual(c.degradations([passage(99), passage(80), passage(80)]), {})

    def test_surveillance_previent(self):
        from app import surveillance as sv, synchro
        from app.index import Index
        with tempfile.TemporaryDirectory() as d:
            envois = []
            j = synchro.Journal(Path(d))
            s = sv.Surveillance(Path(d), j, Index(Path(d)), envoi=lambda sujet, texte: envois.append(texte) or [],
                                relire_livraison=False)
            for n in (96, 96, 70):
                j.enregistrer({"le": "x", "sources": [], **passage(n)})
            vrai = synchro.sante
            synchro.sante = lambda journal, m=None: (True, "ok")
            try:
                s.verifier()
            finally:
                synchro.sante = vrai
            self.assertEqual(len(envois), 1)
            self.assertIn("Thème : 70 sets en vente", envois[0])


if __name__ == "__main__":
    unittest.main()

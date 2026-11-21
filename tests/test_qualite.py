"""Tests du verdict de qualité des briques (app/qualite.py) et du fichier data/qualite.json."""
from __future__ import annotations

import unittest

from app import qualite as q


def c(sens: str, site: str = "a.test", critere: str = "serrage", date: str = "2025-01", rang: str = "test") -> dict:
    return {"critere": critere, "sens": sens, "url": f"https://{site}/x", "date": date, "rang": rang, "resume": "r"}


class Verdict(unittest.TestCase):
    def test_un_site_une_voix(self):
        # un testeur très actif ne pèse qu'une voix, quel que soit son nombre d'articles
        v = q.verdict([c("en_retrait", "a.test")] * 6 + [c("proche", "b.test"), c("proche", "c.test")])
        self.assertEqual((v["verdict"], v["pour"], v["contre"], v["sites"]), ("Partagé", 2, 1, 3))
        v = q.verdict([c("proche", "a.test"), c("comme_lego", "b.test")])
        self.assertEqual((v["verdict"], v["pour"], v["contre"]), ("Favorable", 2, 0))
        self.assertEqual(q.verdict([c("en_retrait", "a.test"), c("en_retrait", "b.test")])["verdict"], "Défavorable")

    def test_majorite_et_egalite_dans_un_site(self):
        v = q.verdict([c("proche", "a.test"), c("proche", "a.test"), c("en_retrait", "a.test"),
                       c("proche", "b.test"), c("en_retrait", "b.test"), c("proche", "d.test")])
        self.assertEqual((v["verdict"], v["pour"], v["contre"], v["sites"]), ("Favorable", 2, 0, 3))

    def test_un_seul_site_et_peu_de_sources(self):
        self.assertEqual(q.verdict([c("comme_lego")] * 5)["verdict"], "Un seul site")
        meme = [c("proche", "www.merlinsbricks.com"), c("proche", "merlinssteine.de")]  # même auteur
        self.assertEqual((q.verdict(meme)["verdict"], q.verdict(meme)["sites"]), ("Un seul site", 1))
        self.assertEqual(q.verdict([c("proche", "a.test"), c("en_retrait", "a.test")])["verdict"], "Peu de sources")
        self.assertEqual(q.verdict([])["verdict"], "Peu de sources")

    def test_defauts_comptes_a_part(self):
        v = q.verdict([c("proche", "a.test"), c("proche", "b.test"), c("probleme", "c.test"), c("probleme", "d.test")])
        self.assertEqual((v["verdict"], v["sites"], v["favorables"], v["defavorables"], v["defauts"]),
                         ("Favorable", 2, 2, 0, 2))

    def test_borne_d_annee_et_sources_liees(self):
        self.assertEqual(q.verdict([c("proche", "a.test", date="2023-01"), c("proche", "b.test", date="2023")])["pour"], 2)
        self.assertEqual(q.verdict([c("proche", "a.test", date="2022-12"), c("proche", "b.test", rang="lie")])["pour"], 0)

    def test_hors_compte(self):
        hors = [c("proche", critere="notice"), c("neutre"), c("proche", date="2021-05"),
                c("comme_lego", rang="marque"), c("proche", date="")]
        self.assertEqual((q.verdict(hors)["favorables"], q.verdict(hors)["verdict"]), (0, "Peu de sources"))


class Fichier(unittest.TestCase):
    def test_donnees_bien_formees(self):
        d = q.lire()
        self.assertTrue(d["releve"])
        for marque, m in d["marques"].items():
            for x in m["constats"]:
                with self.subTest(marque=marque, url=x.get("url")):
                    self.assertIn(x["critere"], q.CRITERES)
                    self.assertIn(x["sens"], q.FAVORABLE | q.DEFAVORABLE | {q.DEFAUT, "neutre"})
                    self.assertTrue(x["url"].startswith("https://"))
                    self.assertLessEqual(len(x["resume"].split()), 30)

    def test_page(self):
        p = q.pour_la_page()
        self.assertEqual(p["_annee_min"], q.ANNEE_MIN)
        m = p["marques"]
        self.assertIn("Mould King", m)
        self.assertTrue(all(v["verdict"] in q.VERDICTS for v in m.values()))
        x = m["Mould King"]["constats"]
        self.assertEqual([c["critere"] for c in x], sorted((c["critere"] for c in x), key=q.CRITERES.index))
        self.assertTrue(all(set(c) <= {"critere", "sens", "resume", "url", "date", "rang", "compte"} for c in x))
        self.assertIs(q.pour_la_page(), p)  # relu seulement si le fichier change

    def test_rangs_et_dates(self):
        import re
        for m in q.lire()["marques"].values():
            for x in m["constats"]:
                self.assertIn(x["rang"], {"test", "forum", "acheteur", "article", "marque", "lie"})
                self.assertRegex(x["date"], r"^\d{4}(-\d{2}(-\d{2})?)?$")


if __name__ == "__main__":
    unittest.main()

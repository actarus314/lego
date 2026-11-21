"""Tests du verdict de qualité des briques (app/qualite.py) et du fichier data/qualite.json."""
from __future__ import annotations

import unittest

from app import qualite as q


def c(sens: str, site: str = "a.test", critere: str = "serrage", date: str = "2025-01", rang: str = "test") -> dict:
    return {"critere": critere, "sens": sens, "url": f"https://{site}/x", "date": date, "rang": rang, "resume": "r"}


class Verdict(unittest.TestCase):
    def test_seuils(self):
        base = [c("proche", "a.test"), c("proche", "b.test")]
        self.assertEqual(q.verdict(base + [c("en_retrait")])["verdict"], "Proche du LEGO officiel")      # 1 sur 3
        self.assertEqual(q.verdict(base + [c("en_retrait"), c("en_retrait")])["verdict"], "Inégale")     # 2 sur 4
        self.assertEqual(q.verdict([c("proche", "b.test")] + [c("en_retrait")] * 2)["verdict"], "En retrait")  # 2 sur 3

    def test_peu_de_sources(self):
        self.assertEqual(q.verdict([c("comme_lego")] * 5)["verdict"], "Peu de sources")          # un seul site
        self.assertEqual(q.verdict([c("comme_lego", "a.test"), c("proche", "b.test")])["verdict"], "Peu de sources")
        # deux adresses d'un même auteur comptent pour un site
        meme = [c("proche", "www.merlinsbricks.com"), c("proche", "merlinssteine.de"), c("proche", "merlinsbricks.com")]
        self.assertEqual(q.verdict(meme)["sites"], 1)

    def test_defauts_comptes_a_part(self):
        v = q.verdict([c("proche", "a.test"), c("proche", "b.test"), c("proche"), c("probleme"), c("probleme")])
        self.assertEqual((v["verdict"], v["favorables"], v["defavorables"], v["defauts"]),
                         ("Proche du LEGO officiel", 3, 0, 2))

    def test_hors_compte(self):
        hors = [c("proche", critere="notice"), c("neutre"), c("proche", date="2021-05"),
                c("comme_lego", rang="marque"), c("proche", date="")]
        self.assertEqual(q.verdict(hors)["favorables"], 0)


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
        self.assertIn("Mould King", p)
        self.assertTrue(all(v["verdict"] in q.VERDICTS for v in p.values()))


if __name__ == "__main__":
    unittest.main()

"""Tests du relevé des boutiques (app/boutiques.py), sans réseau. Les extraits viennent des pages
réelles lues le 23/11/2026 (étalon : délai attendu pour chacune)."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app import boutiques as b, lien

# extraits des politiques de livraison (corps de la politique), avec le délai attendu vers la France
ETALON = [
    ("Mould King officiel", "🇬🇧 Royaume-Uni Expédition standard : Gratuit, livraison en 12-15 jours. 🇩🇪 Allemagne "
     "Expédition standard (TVA incluse) : Gratuit, livré en 18-25 jours par DPD. 🇫🇷 France Expédition standard "
     "(TVA incluse) : Gratuit, livré en 18-25 jours par DPD. Expédition express : 9-12 jours.", "18 à 25 jours"),
    ("Joygobricks", "Processing Time Most orders require approximately 7–10 business days for preparation before "
     "shipment. Estimated Delivery Time: Germany: approximately 8–14 business days Europe, United States, Canada, "
     "Australia: approximately 10–20 business days", "10 à 20 jours ouvrés"),
    ("KBS", "Shipping costs Germany 0.00 € France 4,95 € Delivery time France: 1-3 business days", "1 à 3 jours ouvrés"),
    ("Bausteinreich (bandeau du panier, sans pays)", "Good News! Deine Bestellung kommt in 1-3 Werktagen bei Dir an.", None),
    ("AFOBrick (délai d'un autre service)", "Upload a clear photo of your invoice. Review takes 2–3 business days.", None),
    ("Boutique allemande", "Versand nach Frankreich: 5,90 €, Lieferzeit 3-5 Werktage.", "3 à 5 jours ouvrés"),
]


class Delai(unittest.TestCase):
    def test_etalon(self):
        for nom, texte, attendu in ETALON:
            with self.subTest(nom):
                self.assertEqual(b.delai(texte), attendu)

    def test_page_propre_a_la_france(self):
        self.assertEqual(b.delai("Standard delivery takes 2-5 working days.", page_france=True), "2 à 5 jours ouvrés")
        self.assertIsNone(b.delai("Standard delivery takes 2-5 working days."))

    def test_corps_de_politique_seul(self):
        page = '<div class="panier">1-3 Werktagen France</div><div class="shopify-policy__body">France : 2-4 jours ouvrés</div>'
        self.assertEqual(b.delai(b.corps_politique(page)), "2 à 4 jours ouvrés")


class Avis(unittest.TestCase):
    def test_judgeme(self):
        page = ("<a class='jdgm-all-reviews-rating-wrapper' href='#'><div class='jdgm-all-reviews-rating' "
                "aria-label='4.74 stars' tabindex='0' role='img'></div><div data-number-of-reviews='503'>x</div></a>")
        self.assertEqual(b.avis_affiches(page), {"note": 4.74, "nombre": 503, "verifies": False,
                                                 "plateforme": "Judge.me (avis affichés par la boutique)"})

    def test_badges_produit_ignores(self):   # badges de produits à 0 avis, sans badge « toutes les avis »
        self.assertIsNone(b.avis_affiches("<div data-average-rating='4.78' data-number-of-reviews='12'></div>"))

    def test_json_ld(self):
        ld = {"@type": "Organization", "aggregateRating": {"ratingValue": "4.2", "reviewCount": "88"}}
        page = f'<script type="application/ld+json">{json.dumps(ld)}</script>'
        self.assertEqual(b.avis_affiches(page)["nombre"], 88)

    def test_trustedshops(self):
        rep = {"response": {"data": {"shop": {"qualityIndicators": {"reviewIndicator": {
            "activePeriodInDays": 365, "activeReviewCount": 712, "overallMark": 4.73}}}}}}
        with mock.patch.object(lien, "recuperer", return_value=lien.Reponse("u", 200, "application/json", json.dumps(rep).encode())):
            self.assertEqual(b.lire_trustedshops("X1"), {"note": 4.73, "nombre": 712, "periode_j": 365,
                                                         "plateforme": "Trusted Shops", "verifies": True})


class Regles(unittest.TestCase):
    def test_fiabilite(self):
        ts = lambda note, n: {"note": note, "nombre": n, "verifies": True, "plateforme": "Trusted Shops"}
        self.assertEqual(b.fiabilite(ts(4.73, 712), True)[0], 3)
        self.assertEqual(b.fiabilite(ts(4.2, 60), True)[0], 2)
        self.assertEqual(b.fiabilite(ts(4.9, 20), True)[0], 1)
        self.assertEqual(b.fiabilite({**ts(4.74, 503), "verifies": False}, True)[0], 2)   # plafond des avis affichés
        self.assertEqual(b.fiabilite(None, True)[0], 1)
        self.assertEqual(b.fiabilite(ts(4.9, 900), False)[0], 0)

    def lu(self, **champs):
        return {"le": "2026-11-23T00:00:00", "lus": {c: {"valeur": v, "source": "https://x", "le": "2026-11-23T00:00:00"}
                                                     for c, v in champs.items()}}

    def test_douane_et_delai_estime(self):
        bout = {"id": "x", "nom": "X", "url": "https://x", "hote": "x", "type": "boutique"}
        f = b.fiche(bout, self.lu(pays="DE"))
        self.assertEqual(f["champs"]["douane"]["valeur"], "aucune")
        self.assertEqual((f["champs"]["delai"]["valeur"], f["champs"]["delai"]["origine"]), ("2 à 6 jours ouvrés", "estimé"))
        self.assertEqual(f["champs"]["pays"]["valeur"], "Allemagne")
        f = b.fiche(bout, self.lu(pays="HK", tva_comprise=True, delai="18 à 25 jours"))
        self.assertEqual(f["champs"]["douane"]["valeur"], "TVA payée à la commande")
        self.assertEqual(f["champs"]["delai"]["origine"], "lu")
        f = b.fiche(bout, self.lu(pays="CN"))
        self.assertEqual(f["champs"]["douane"]["valeur"], "TVA et frais possibles à la livraison")

    def test_champ_inconnu_dans_manquants_jamais_vide(self):
        f = b.fiche({"id": "x", "nom": "X", "url": "https://x", "hote": "x", "type": "place_de_marche"}, None)
        self.assertEqual(set(f["manquants"]), {"pays", "devise", "livre_france", "port", "delai", "douane", "avis"})
        self.assertTrue(all(c["valeur"] is not None for c in f["champs"].values()))

    def test_echec_garde_la_valeur_precedente(self):
        d = Path(tempfile.mkdtemp())
        b._ecrire(d / "boutiques_lues.json", {"kbs": self.lu(pays="DE")})
        with mock.patch.object(b, "configuration", return_value=[{"id": "kbs", "nom": "KBS", "url": "https://kbs-shop.com/en",
                                                                 "hote": "kbs-shop.com", "lire": ["meta", "accueil", "livraison"]}]), \
                mock.patch.object(lien, "recuperer", side_effect=lien.LienRefuse("le site a répondu 503")):
            r = b.relever(d, pause=0)
        self.assertEqual(r["kbs"]["lus"]["pays"]["valeur"], "DE")
        self.assertEqual(r["kbs"]["echecs"]["meta"], "le site a répondu 503")

    def test_configuration_sans_valeur_relevee(self):
        for x in b.configuration():
            self.assertLessEqual(set(x), {"id", "nom", "hote", "url", "type", "source", "trustedshops", "livraison_page",
                                          "livraison_france", "lire"}, x["id"])
            self.assertTrue({"nom", "hote", "url"} <= set(x), x["id"])
        brut = json.loads((Path(b.RACINE) / "data" / "boutiques.json").read_text("utf-8"))["boutiques"]
        sources = b._sources()
        for x in brut:   # une seule place : une boutique lue comme source ne répète pas son identité
            if x.get("source"):
                self.assertIn(x["source"], sources)
                self.assertFalse({"nom", "hote", "url"} & set(x), x["id"])

    def test_tva_negations(self):
        for texte, attendu in [("Prices are not including VAT", False), ("Prix hors TVA comprise", False),
                               ("Preise nicht inkl. MwSt", False), ("sans TVA comprise", False), ("no taxes included", False),
                               ("prices without VAT included", False), ("Alle Preise inkl. MwSt.", True),
                               ("prix TTC", True), ("Expédition standard (TVA incluse)", True), ("attcher", False)]:
            with self.subTest(texte):
                self.assertEqual(bool(b._TVA.search(texte)), attendu)

    def test_meta_tous_pays(self):
        rep = lambda pays: lien.Reponse("u", 200, "application/json", json.dumps({"country": "DE", "currency": "EUR",
                                                                                   "ships_to_countries": pays}).encode())
        for pays, attendu in ((["*", "AT"], True), (["BE", "DE", "NL"], False), (["FR"], True)):
            with mock.patch.object(lien, "recuperer", return_value=rep(pays)):
                self.assertEqual(b.lire_meta({"url": "https://x.fr"})["livre_france"], attendu)


if __name__ == "__main__":
    unittest.main()

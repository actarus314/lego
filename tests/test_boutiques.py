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


class HorsShopify(unittest.TestCase):
    """Extraits des pages réelles lues le 23/11/2026 (étalon)."""
    BLUEBRIXX = ("we charge the following shipping costs: Destination Shipping Costs Germany €5.95 free from €99 France "
                 "€9.95 free from €99 Austria, Belgium, Bulgaria, Croatia")
    GALAXUS = ("Livraison gratuite dans toute la France Pour les commandes d’un montant égal ou supérieur à 39 €, tous les "
               "produits sont envoyés gratuitement en France. Nous facturons des frais de port à hauteur de 3,90 € pour les "
               "commandes inférieures à 39 €. Pourquoi? Les petites commandes demandent un effort logistique plus important.")

    def test_port_et_seuil(self):
        self.assertEqual(b.port_et_seuil(self.BLUEBRIXX), (9.95, 99.0))
        self.assertEqual(b.port_et_seuil(self.GALAXUS, page_france=True), (3.9, 39.0))
        self.assertEqual(b.port_et_seuil("Livraison offerte. Retours sous 30 jours."), (None, None))
        lego = ("Here’s how delivery costs work: Orders up to 55 € have a delivery cost of 5.95 €. Orders of 55 € or more "
                "are delivered free. Next-day delivery costs € 15 .")
        self.assertEqual(b.port_et_seuil(lego, page_france=True), (5.95, 55.0))

    def test_mentions_tva(self):
        rep = lambda texte: lien.Reponse("u", 200, "text/html", texte.encode())
        cas = [("Imprint BB Services GmbH Böttgerstr. 14 65439 Flörsheim VAT ID: DE 224 033 430 WEEE-Reg.-Nr.", "DE"),
               ("Numéro d’identification de taxe sur le chiffre d’affaires d’après le § 27a de la loi relative à la taxe "
                "sur le chiffre d’affaires : FR23922143243 Responsabilité Galaxus Deutschland GmbH", "FR")]
        for texte, pays in cas:
            with mock.patch.object(lien, "recuperer", return_value=rep(texte)):
                self.assertEqual(b.lire_mentions("https://x")["pays"], pays)
        with mock.patch.object(lien, "recuperer", return_value=rep("Cookie Settings LEGO System A/S, DK-7190 Billund, Denmark. Must be 18 years or older")):
            self.assertEqual(b.lire_mentions("https://x"), {"pays": "DK", "par": "adresse"})
        with mock.patch.object(lien, "recuperer", return_value=rep("You must be 18 years or older. Prices include VAT for de and fr.")):
            with self.assertRaises(ValueError):
                b.lire_mentions("https://x")
        with mock.patch.object(lien, "recuperer", return_value=rep("Contact : 01 23 45 67 89")):
            with self.assertRaises(ValueError):
                b.lire_mentions("https://x")

    def test_page_anti_robot_200(self):
        alibaba = '<script>var url = window.location.protocol + "//fr.aliexpress.com///_____tmd_____/punish?x5secdata=x"</script>'
        with mock.patch.object(lien, "recuperer", return_value=lien.Reponse("u", 200, "text/html", alibaba.encode())):
            with self.assertRaises(ValueError):
                b.lire_livraison("https://x")

    def test_cause_du_refus(self):
        def refus(entetes):
            e = lien.LienRefuse("le site a répondu 403")
            e.statut, e.entetes = 403, entetes
            return e
        self.assertEqual(b.cause(refus({"server": "cloudflare", "cf-mitigated": "challenge"})),
                         "le site a répondu 403 (Cloudflare, défi anti-robot)")
        self.assertEqual(b.cause(refus({"server": "cloudflare"})), "le site a répondu 403 (Cloudflare)")
        self.assertEqual(b.cause(refus({"server": "AkamaiGHost"})), "le site a répondu 403 (Akamai)")
        self.assertEqual(b.cause(refus({})), "le site a répondu 403")
        self.assertEqual(b.cause(refus({"server": "CloudFront"})), "le site a répondu 403 (CloudFront)")
        autre = lien.LienRefuse("le site a répondu 404")
        autre.statut, autre.entetes = 404, {"server": "cloudflare"}
        self.assertEqual(b.cause(autre), "le site a répondu 404")   # pas un refus de la protection

    def test_faux_positifs_des_motifs(self):
        rep = lambda texte: lien.Reponse("u", 200, "text/html", texte.encode())
        for texte in ("Prix TVA comprise. Service client FR 01 23 45 67 89", "VAT included. Order number DE12345678",
                      "Exempt from VAT. Bank: DE89 3704 0044 0532 0130 00", "Reference DE-2024 Zone B",
                      "Prices include VAT. Customer care: IT 0612345678"):
            with self.subTest(texte), mock.patch.object(lien, "recuperer", return_value=rep(texte)):
                with self.assertRaises(ValueError):
                    b.lire_mentions("https://x")
        for texte, pays in (("BTW-nummer / VAT number: NL123456789B01", "NL"), ("N° TVA intracommunautaire : FR 23 922143243", "FR"),
                            ("Prix TTC (TVA : 20 %). Service client FR 01 23 45 67 89", None),
                            ("VAT: 19% included. IBAN: DE89 3704 0044 0532 0130 00", None),
                            ("TVA intracommunautaire : non applicable. Tél FR 04 90 72 00 00", None)):
            if pays is None:   # faux positifs relevés le 23/11/2026 sur la version large : refusés
                with self.subTest(texte), mock.patch.object(lien, "recuperer", return_value=rep(texte)):
                    with self.assertRaises(ValueError):
                        b.lire_mentions("https://x")
                continue
            with self.subTest(texte), mock.patch.object(lien, "recuperer", return_value=rep(texte)):
                self.assertEqual(b.lire_mentions("https://x")["pays"], pays)
        for texte in ("Livraison gratuite dès 2 jours ouvrés. France 4,90 €", "France : free shipping over 2 kg",
                      "France : gratuit à partir de 18 ans", "France : free returns over 30 days"):
            with self.subTest(texte):
                self.assertIsNone(b.port_et_seuil(texte)[1])
        self.assertEqual(b.port_et_seuil("France €9.95 Austria €12.95 free from €199 Switzerland"), (9.95, None))

    def test_formes_vraies_des_motifs(self):
        rep = lambda texte: lien.Reponse("u", 200, "text/html", texte.encode())
        cas = [("VAT number: DE224033430", "DE"), ("N° TVA intracommunautaire : FR23922143243", "FR"),
               ("USt-IdNr: DE224033430", "DE"), ("Umsatzsteuer-Identifikationsnummer: DE224033430", "DE"),
               ("Siège : FR-75001 Paris, France", "FR"), ("DK-7190 Billund Denmark", "DK")]
        # limite connue de la version stricte (voir _TVA_ID) : non lus
        for texte in ("VAT Reg No: DE224033430", "USt.-IdNr.: DE224033430", "TVA : FR23922143243", "BTW-nummer: NL123456789B01"):
            with self.subTest(texte), mock.patch.object(lien, "recuperer", return_value=rep(texte)):
                with self.assertRaises(ValueError):
                    b.lire_mentions("https://x")
        for texte, pays in cas:
            with self.subTest(texte), mock.patch.object(lien, "recuperer", return_value=rep(texte)):
                self.assertEqual(b.lire_mentions("https://x")["pays"], pays)
        self.assertEqual(b.port_et_seuil("Livraison gratuite dès 39 euros. France 4,90 €")[1], None)   # hors fenêtre France
        self.assertEqual(b.port_et_seuil("France : 4,90 €, gratuite dès 39 euros")[1], 39.0)
        self.assertEqual(b.port_et_seuil("Frankreich: 5,90 €, versandkostenfrei ab 50 Euro")[1], 50.0)

    def test_boutique_retiree_purgee(self):
        d = Path(tempfile.mkdtemp())
        b._ecrire(d / "boutiques_lues.json", {"ancienne": {"le": "2026-11-01T00:00:00", "lus": {}, "echecs": {}}})
        with mock.patch.object(b, "configuration", return_value=[]):
            r = b.relever(d, pause=0)
        self.assertNotIn("ancienne", r)

    def test_releve_hors_shopify(self):
        pages = {"https://bb/": "<html>accueil</html>", "https://bb/livraison": self.BLUEBRIXX,
                 "https://bb/imprint": "VAT ID: DE 224 033 430"}
        conf = [{"id": "bb", "nom": "BB", "url": "https://bb/", "hote": "bb", "type": "boutique",
                 "livraison_page": "https://bb/livraison", "mentions_page": "https://bb/imprint",
                 "lire": ["accueil", "livraison", "mentions"]}]
        d = Path(tempfile.mkdtemp())
        with mock.patch.object(b, "configuration", return_value=conf), \
                mock.patch.object(lien, "recuperer", side_effect=lambda u, **k: lien.Reponse(u, 200, "text/html", pages[u].encode())):
            b.relever(d, pause=0)
        f = b.fiche(conf[0], b._lire(d / "boutiques_lues.json", {})["bb"])
        v = {c: x["valeur"] for c, x in f["champs"].items()}
        self.assertEqual((v["pays"], v["devise"], v["livre_france"], v["port"], v["seuil"], v["douane"]),
                         ("Allemagne", "EUR", True, 9.95, 99.0, "aucune"))
        self.assertEqual(f["champs"]["pays"]["methode"], "pays du numéro de TVA intracommunautaire")
        self.assertEqual(f["manquants"], ["avis"])


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

    def test_ne_livre_pas_la_france(self):
        f = b.fiche({"id": "x", "nom": "X", "url": "https://x", "hote": "x", "type": "boutique"},
                    self.lu(pays="NL", livre_france=False, devise="EUR"))
        self.assertEqual({c: f["champs"][c]["valeur"] for c in ("port", "delai", "douane", "fiabilite")},
                         {"port": "sans objet", "delai": "sans objet", "douane": "sans objet", "fiabilite": 0})

    def test_champ_inconnu_dans_manquants_jamais_vide(self):
        f = b.fiche({"id": "x", "nom": "X", "url": "https://x", "hote": "x", "type": "place_de_marche"}, None)
        self.assertEqual(set(f["manquants"]), {"pays", "devise", "livre_france", "avis"})
        self.assertEqual(f["champs"]["port"]["valeur"], "selon le vendeur")   # place de marché : règle
        self.assertTrue(all(c["valeur"] is not None for c in f["champs"].values()))

    def test_devise_lue_jamais_remplacee(self):
        d = Path(tempfile.mkdtemp())
        b._ecrire(d / "boutiques_lues.json", {"x": self.lu(devise="USD")})
        conf = [{"id": "x", "nom": "X", "url": "https://x.fr", "hote": "x.fr", "livraison_page": "https://x.fr/l",
                 "lire": ["meta", "livraison"]}]
        def rep(u, **k):
            if u.endswith("meta.json"):
                raise lien.LienRefuse("le site a répondu 503")
            return lien.Reponse(u, 200, "text/html", "France 4,90 €".encode())
        with mock.patch.object(b, "configuration", return_value=conf), mock.patch.object(lien, "recuperer", side_effect=rep):
            r = b.relever(d, pause=0)
        self.assertEqual(r["x"]["lus"]["devise"]["valeur"], "USD")

    def test_pause_429_relue_une_heure_apres(self):
        d = Path(tempfile.mkdtemp())
        conf = [{"id": "x", "nom": "X", "url": "https://x.fr", "hote": "x.fr", "lire": ["accueil"]},
                {"id": "y", "nom": "Y", "url": "https://y.fr", "hote": "y.fr", "lire": ["accueil"]}]
        def rep(u, **k):
            if "x.fr" in u:
                e = lien.LienRefuse("site en pause après un refus 429 (encore 600 s)")
                e.statut, e.pause, e.attente = 429, True, "600"
                raise e
            return lien.Reponse(u, 200, "text/html", b"<html></html>")
        with mock.patch.object(b, "configuration", return_value=conf), mock.patch.object(lien, "recuperer", side_effect=rep):
            b.relever(d, pause=0)
            maintenant = b.time.time()
            self.assertEqual(b.a_relire(d, maintenant), [])
            self.assertEqual(b.a_relire(d, maintenant + 3700), ["x"])   # la boutique en pause seule
            self.assertEqual(b.a_relire(d, maintenant + 8 * 86400), ["x", "y"])
            b.relever(d, pause=0, ids=["y"])
        self.assertIn("y", b._lire(d / "boutiques_lues.json", {}))
        self.assertIn("x", b._lire(d / "boutiques_lues.json", {}))   # relevé partiel : les autres restent

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
                                          "livraison_france", "lire", "mentions_page"}, x["id"])
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

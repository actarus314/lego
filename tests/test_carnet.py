import base64
import json
import os
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from app import acces, lien
from app.donnees import Depot, _ecrire
from app.index import Index

RACINE = Path(__file__).resolve().parent.parent


class Acces(unittest.TestCase):
    def test_empreinte(self):
        h = acces.empreinte("un mot de passe", iterations=1000)
        self.assertTrue(acces.verifier("un mot de passe", h))
        self.assertFalse(acces.verifier("autre", h))
        self.assertFalse(acces.verifier("x", "n'importe quoi"))

    def test_comptes(self):
        h = acces.empreinte("abcdefghij", iterations=1000)
        self.assertEqual(acces.lire_comptes(f"a={h}; b=pas-une-empreinte ;"), {"a": h})
        self.assertNotIn("$", h)

    def test_blocage(self):
        g = acces.Gardien({"a": acces.empreinte("bonmotdepasse", iterations=1000)})
        mauvais = "Basic " + base64.b64encode(b"a:faux").decode()
        bon = "Basic " + base64.b64encode(b"a:bonmotdepasse").decode()
        self.assertEqual(g.authentifier(bon), "a")
        for _ in range(acces.ECHECS_MAX):
            self.assertIsNone(g.authentifier(mauvais))
        self.assertIsNone(g.authentifier(bon), "compte bloqué après trop d'échecs")

    def test_memoire_des_connexions(self):
        from unittest import mock
        g = acces.Gardien({"a": acces.empreinte("bonmotdepasse", iterations=1000)})
        bon = "Basic " + base64.b64encode(b"a:bonmotdepasse").decode()
        mauvais = "Basic " + base64.b64encode(b"a:faux").decode()
        self.assertEqual(g.authentifier(bon), "a")
        with mock.patch.object(acces, "verifier", wraps=acces.verifier) as v:
            self.assertEqual(g.authentifier(bon), "a")
            self.assertEqual(v.call_count, 0, "connexion réussie retenue : pas de recalcul")
            self.assertIsNone(g.authentifier(mauvais))
            self.assertIsNone(g.authentifier(mauvais))
            self.assertEqual(v.call_count, 2, "un échec n'est jamais retenu")
        with mock.patch.object(acces.time, "time", return_value=acces.time.time() + acces.MEMOIRE_S + 1), \
                mock.patch.object(acces, "verifier", wraps=acces.verifier) as v:
            self.assertEqual(g.authentifier(bon), "a")
            self.assertEqual(v.call_count, 1, "mémoire expirée : nouveau calcul")
        self.assertTrue(acces.empreinte("x").startswith("pbkdf2_sha256.600000."))


class Lien(unittest.TestCase):
    def test_adresses_refusees(self):
        for ip in ["127.0.0.1", "10.0.0.5", "192.168.1.10", "172.16.3.4", "169.254.169.254",
                   "100.64.0.1", "::1", "fe80::1", "fd00::1", "::ffff:127.0.0.1", "0.0.0.0"]:
            self.assertFalse(lien._ip_publique(ip), ip)
        self.assertTrue(lien._ip_publique("1.1.1.1"))

    def test_localhost_refuse(self):
        with self.assertRaises(lien.LienRefuse):
            lien.recuperer("http://localhost:8080/")
        with self.assertRaises(lien.LienRefuse):
            lien.recuperer("file:///etc/passwd")
        with self.assertRaises(lien.LienRefuse):
            lien.recuperer("http://user:pass@example.com/")

    def test_ports_web_seulement(self):
        for url in ("https://example.com:8443/", "http://example.com:22/", "https://example.com:0/"):
            with self.assertRaises(lien.LienRefuse, msg=url):
                lien.recuperer(url)

    def test_tls_minimum(self):
        import ssl
        ctx = lien.contexte_tls()
        self.assertEqual(ctx.minimum_version, ssl.TLSVersion.TLSv1_2)
        self.assertEqual(ctx.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(ctx.check_hostname)

    def test_pieces(self):
        self.assertEqual(lien.nombre_pieces("Avec 3 887 pièces et"), 3887)
        self.assertEqual(lien.nombre_pieces("With 12,688 pieces"), 12688)
        self.assertEqual(lien.nombre_pieces("1500 Teile"), 1500)
        self.assertIsNone(lien.nombre_pieces("aucun nombre ici"))

    def test_shopify(self):
        d = lien.depuis_shopify({"title": "Big Ben", "price": 64995, "available": True,
                                 "featured_image": "//cdn.shopify.com/x.jpg", "description": "<p>13,825 pieces</p>"})
        self.assertEqual((d["nom"], d["prix"], d["dispo"], d["pcs"]), ("Big Ben", 649.95, True, 13825))
        self.assertEqual(d["img"], "https://cdn.shopify.com/x.jpg")

    def test_html(self):
        page = """<html><head><meta property="og:title" content="Set &amp; Co">
        <meta property="og:image" content="https://ex.com/i.jpg">
        <script type="application/ld+json">{"@type":"Product","name":"Château","description":"Un château de 4000 pièces","offers":{"price":"159,95","availability":"https://schema.org/InStock"}}</script>
        </head><body>Produits similaires : 3218 pièces</body></html>"""
        d = lien.depuis_html(page)
        self.assertEqual((d["nom"], d["prix"], d["dispo"], d["pcs"], d["img"]), ("Château", 159.95, True, 4000, "https://ex.com/i.jpg"))


class Donnees(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Depot(Path(self.tmp.name))

    def tearDown(self):
        self.tmp.cleanup()

    def test_validation(self):
        with self.assertRaises(ValueError):
            self.d.valider({"url": "javascript:alert(1)"})
        v = self.d.valider({"url": "https://ex.com/p", "prix": -3, "pcs": "x", "statut": "bidon", "img": "data:x"})
        self.assertEqual((v["prix"], v["pcs"], v["statut"], v["img"]), (None, None, "idee", ""))

    def test_selection(self):
        self.d.enregistrer("a1", {"url": "https://ex.com/p", "prix": 10, "statut": "retenu"}, "bruno")
        self.d.enregistrer("a1", {"url": "https://ex.com/p", "prix": 12, "statut": "retenu"}, "alice")
        sel = self.d.selection()
        self.assertEqual((len(sel), sel[0]["prix"], sel[0]["par"], sel[0]["modifie_par"]), (1, 12, "bruno", "alice"))
        self.assertTrue(self.d.supprimer("a1"))
        self.assertFalse(self.d.supprimer("a1"))
        with self.assertRaises(ValueError):
            self.d.enregistrer("../x", {"url": "https://ex.com"}, "a")

PRODUIT_KBS = {
    "title": "Pirate Ship – Mould King 13199", "handle": "pirate-ship-mould-king-13199", "vendor": "Mould King",
    "product_type": "Brickbuild-Set", "tags": ["thema-schiffe", "vorbestellung"],
    "body_html": "<p>With 3,180 pieces, about 72 cm long. Size: 72 × 26 × 61 cm</p>",
    "variants": [{"price": "184.95", "available": True, "sku": "MK13199"}],
    "images": [{"src": "https://cdn.shopify.com/p.jpg"}], "published_at": "2026-10-01T10:00:00+02:00"}
SOURCE_KBS = {"id": "kbs", "nom": "KBS", "hote": "kbs-shop.com", "prefixe": "/en", "devise": "EUR", "pays_boutique": "Allemagne"}


class CheminsSurs(unittest.TestCase):
    def test_dans(self):
        from app.donnees import dans
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(dans(Path(d), "a.json"), Path(os.path.realpath(d)) / "a.json")
            for nom in ("../a.json", "/etc/passwd", "x/../../a", "", "."):
                with self.assertRaises(ValueError, msg=nom):
                    dans(Path(d), nom)
            os.symlink("/etc", os.path.join(d, "lien"))
            with self.assertRaises(ValueError):
                dans(Path(d), "lien/passwd")

    def test_fichier_de_source(self):
        with tempfile.TemporaryDirectory() as d:
            i = Index(Path(d))
            self.assertEqual(i.fichier("../../kbs").name, "kbs.json")
            self.assertEqual(i.fichier("../../kbs").parent, Path(os.path.realpath(d)) / "sources")


class Normalisation(unittest.TestCase):
    def test_offre_shopify(self):
        from app.sources import shopify
        o = shopify.offre(PRODUIT_KBS, SOURCE_KBS)
        self.assertEqual((o["marque"], o["numero"], o["prix"], o["dispo"], o["pieces"], o["dims"][0], o["type"]),
                         ("Mould King", "13199", 184.95, "precommande", 3180, 72.0, "classique"))
        self.assertEqual(o["themes"], ["marine"])
        self.assertEqual(o["url"], "https://kbs-shop.com/en/products/pirate-ship-mould-king-13199")

    def test_exclusions(self):
        from app.sources import shopify
        petit = {**PRODUIT_KBS, "body_html": "<p>120 Teile</p>"}
        lot = {**PRODUIT_KBS, "product_type": "Bundle"}
        gratuit = {**PRODUIT_KBS, "variants": [{"price": "0.00", "available": True}]}
        inconnu = {**PRODUIT_KBS, "vendor": "Marque X", "title": "Joli bateau 13199"}
        for p in (petit, lot, gratuit, inconnu):
            self.assertIsNone(shopify.offre(p, SOURCE_KBS))

    def test_pieces_et_dimensions(self):
        from app import normalise as n
        self.assertEqual(n.pieces("Mit 3.180 Teilen"), 3180)
        self.assertEqual(n.pieces("1.234 Klemmbausteinen"), 1234)
        self.assertEqual(n.dimensions("Modell-Maße : 29 cm; 21,6 cm; 4,5 cm"), [29.0, 21.6, 4.5])
        self.assertIsNone(n.dimensions("Modell-Maße : 0 cm; 0 cm;0 cm"))
        self.assertEqual(n.numero("Reobrix 22029 RC", "REO22029"), "22029")

    def test_themes_multilingues(self):
        from app import normalise as n
        self.assertIn("aerospatial", n.themes("CaDA NASA SLS Artemis Rakete"))
        self.assertIn("marine", n.themes("Schlachtschiff Bismarck"))
        self.assertIn("aerospatial", n.themes("Sternenzerstörer", ["thema-film"]) + n.themes("Star Destroyer"))
        self.assertEqual(n.themes("Flugzeugträger Fujian"), ["marine"])


class DimensionsKbs(unittest.TestCase):
    def test_cartes_et_fiche(self):
        from app.sources import shopify
        carte = ('<div class="resource-card" href="/en/products/grue-13107"><p class="kbs-card-info__row" style="x">MK13107</p>'
                 '<p class="kbs-card-info__row" style="x">3218 pieces</p><p class="kbs-card-info__row" style="x">69 × 19 × 110 cm</p></div>')
        fiche = '<div><p>64 x 31 x 41</p></div><div><p>L x W x H in cm</p></div>'
        pages = iter([carte + '<link rel="next" href="?page=2">', carte.replace("grue-13107", "camion-19015")])
        vrai = lien.recuperer
        try:
            lien.recuperer = lambda url, **k: lien.Reponse(url, 200, "text/html", next(pages).encode())
            d = shopify.dimensions_cartes({"hote": "kbs-shop.com", "prefixe": "/en", "cartes": "/collections/all"}, pause=0)
            lien.recuperer = lambda url, **k: lien.Reponse(url, 200, "text/html", fiche.encode())
            f = shopify.dimensions_fiche({"hote": "kbs-shop.com"}, "camion-19015")
        finally:
            lien.recuperer = vrai
        self.assertEqual(d, {"grue-13107": [110.0, 69.0, 19.0], "camion-19015": [110.0, 69.0, 19.0]})
        self.assertEqual(f, [64.0, 41.0, 31.0])


class IndexSets(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        from app.index import Index
        self.i = Index(Path(self.tmp.name))

    def tearDown(self):
        self.tmp.cleanup()

    def test_regroupement_et_meilleur_prix(self):
        from app.sources import shopify
        a = shopify.offre(PRODUIT_KBS, SOURCE_KBS)
        src_mk = {"id": "mouldkingcorp", "nom": "Mould King", "hote": "mouldkingcorp.com", "devise": "EUR", "marque": "Mould King"}
        b = shopify.offre({**PRODUIT_KBS, "title": "Mould King 13199 Pirate Ship Building Set", "handle": "mk-13199",
                           "tags": [], "variants": [{"price": "144.99", "available": True, "sku": "13199"}]}, src_mk)
        self.i.enregistrer("kbs", [a])
        r = self.i.enregistrer("mouldkingcorp", [b])
        self.assertEqual(r, {"nouveaux": 0, "disparus": 0})
        sets = [s for s in self.i.sets(["kbs", "mouldkingcorp"]) if s["numero"] == "13199"]
        self.assertEqual(len(sets), 1)
        s = sets[0]
        self.assertEqual((len(s["offres"]), s["offres"][0]["source"], s["dispo"]), (2, "mouldkingcorp", "vente"))
        self.assertEqual(s["nom"], "Pirate Ship")
        self.assertEqual(self.i.enregistrer("kbs", []), {"nouveaux": 0, "disparus": 1})

    def test_editorial_rattache(self):
        from app.index import editorial, sets_hors_ligne
        self.assertEqual(len(sets_hors_ligne()), len(editorial()))
        self.assertTrue(all(s.get("themes") for s in sets_hors_ligne()), "chaque set éditorial a un thème")


FICHE_BV = """<html><script type="application/ld+json">{"@context":"https://schema.org","@graph":[{"@type":"Product",
 "name":"LEGO Millennium Falcon 75192","category":"Toys > Building toys > LEGO Star Wars","image":["https://cdn.x/75192.png"],
 "additionalProperty":[{"@type":"PropertyValue","name":"Pièces","value":7541},{"@type":"PropertyValue","name":"Âge","value":"16+"},
  {"@type":"PropertyValue","name":"Retrait","value":"Retrait prévu d’ici le 2026-12-31"}],
 "offers":{"@type":"AggregateOffer","priceCurrency":"EUR","offers":[
  {"@type":"Offer","price":"807.49","priceCurrency":"EUR","availability":"https://schema.org/InStock","url":"https://www.amazon.fr/dp/B075NT1KHB","seller":{"name":"Amazon.fr"}},
  {"@type":"Offer","price":"849.99","priceCurrency":"EUR","availability":"https://schema.org/OutOfStock","url":"https://www.lego.com/fr-fr/product/millennium-falcon-75192","seller":{"name":"LEGO.com"}}]}}]}</script></html>"""


class LegoOfficiel(unittest.TestCase):
    def test_fiche(self):
        from app.sources import lego
        vrai = lien.recuperer
        lien.recuperer = lambda url, **k: lien.Reponse(url, 200, "text/html", FICHE_BV.encode())
        try:
            d = lego.lire_fiche("75192", "https://bricksvalue.com/fr/set/75192-millennium-falcon",
                                {"nom": "Millennium Falcon", "pieces": 7541, "themes_lego": ["Star Wars"], "img": "https://r/75192.jpg"})
        finally:
            lien.recuperer = vrai
        self.assertTrue(d["adulte"])
        o = {x["boutique"]: x for x in d["offres"]}
        self.assertEqual((o["Amazon.fr"]["prix"], o["Amazon.fr"]["dispo"], o["LEGO.com"]["dispo"]), (807.49, "vente", "epuise"))
        self.assertEqual((o["LEGO.com"]["numero"], o["LEGO.com"]["img"], o["LEGO.com"]["themes"]), ("75192", "https://r/75192.jpg", ["aerospatial", "films"]))
        self.assertEqual(o["LEGO.com"]["retrait"], "Retrait prévu d’ici le 2026-12-31")

    def test_fiche_donnees_rsc(self):
        """Réponse de données de la fiche : offres, photos et jour du dernier relevé de chaque revendeur."""
        from app.sources import lego
        produit = json.loads(FICHE_BV.split('json">')[1].split("</script>")[0])
        rsc = ('0:["$","script",null,' + json.dumps(produit) + ']\n5f:["$","$L78",null,{"series":{"days":['
               '{"t":1795046400000,"lego":84999,"amazon":null},{"t":1795132800000,"lego":null,"amazon":80749}],'
               '"stores":["lego","amazon"],"stats":{}}}]')
        appels = []
        vrai = lien.recuperer

        def faux(url, **k):
            appels.append((url, k.get("entetes")))
            return lien.Reponse(url, 200, "text/x-component", rsc.encode())
        lien.recuperer = faux
        try:
            d = lego.lire_fiche("75192", "https://bricksvalue.com/fr/set/75192-millennium-falcon", None)
        finally:
            lien.recuperer = vrai
        self.assertEqual(appels, [("https://bricksvalue.com/fr/set/75192-millennium-falcon?_rsc", {"RSC": "1"})])
        o = {x["boutique"]: x for x in d["offres"]}
        self.assertEqual((o["Amazon.fr"]["releve"], o["LEGO.com"]["releve"]), ("2026-11-20", "2026-11-19"))
        self.assertEqual((o["LEGO.com"]["releve_par"], o["LEGO.com"]["images"]), ("BricksValue", ["https://cdn.x/75192.png"]))

    def test_rotation(self):
        import time as t
        from app import synchro
        from app.index import Index
        with tempfile.TemporaryDirectory() as tmp:
            i = Index(Path(tmp))
            from app.donnees import _ecrire
            vieux, recent = "2026-11-17T10:00:00", "2026-11-19T10:00:00"
            _ecrire(i.fichier("bricksvalue"), {"offres": [], "fiches": {
                "1": {"url": "u1", "lu": None}, "2": {"url": "u2", "lu": vieux, "adulte": True},
                "3": {"url": "u3", "lu": recent, "adulte": True}, "4": {"url": "u4", "lu": vieux, "adulte": False}}})
            maintenant = t.mktime(t.strptime("2026-11-20T10:00:00", "%Y-%m-%dT%H:%M:%S"))
            self.assertEqual(synchro.prochaine_fiche(i, set(), maintenant), ("1", synchro.PAS_AMORCE), "une fiche jamais lue passe d'abord")
            d = i.lire("bricksvalue"); d["fiches"]["1"].update(lu=recent, adulte=False); _ecrire(i.fichier("bricksvalue"), d)
            self.assertEqual(synchro.prochaine_fiche(i, set(), maintenant)[0], "2", "la plus ancienne des fiches pour adultes")
            self.assertEqual(synchro.prochaine_fiche(i, {"3"}, maintenant)[0], "3", "la sélection passe devant après 22 h")
            self.assertEqual(synchro.prochaine_fiche(i, set(), maintenant)[1], min(synchro.PAS_MAX, synchro.CIBLE_H * 3600 / 2))


class AlertesSelection(unittest.TestCase):
    def test_changements(self):
        from app import alertes as al
        avant = {"total": 200.0, "dispo": "vente", "boutique": "KBS", "retrait": None, "mieux": None}
        apres = {"total": 180.0, "dispo": "vente", "boutique": "KBS", "retrait": "Retrait prévu d’ici le 2026-12-31",
                 "mieux": ["Galaxus", 150.0, "https://g/x"]}
        l = al.changements("Venator", avant, apres)
        self.assertEqual(len(l), 3)
        self.assertIn("180.00 € chez KBS, au lieu de 200.00 €", l[0])
        self.assertEqual(al.changements("Venator", avant, {**avant, "total": 199.0}), [], "baisse sous le seuil")
        self.assertIn("épuisé", al.changements("V", avant, {**avant, "dispo": "epuise"})[0])
        self.assertIn("de nouveau en vente", al.changements("V", {**avant, "dispo": "epuise"}, avant)[0])

    def test_verification_et_destinataires(self):
        import os
        from app import alertes as al
        from app.index import Index
        from app.sources import shopify
        env = os.environ.get("ALERTES")
        os.environ["ALERTES"] = "julie=courriel:julie@exemple.fr;romain=courriel:romain@exemple.fr,signal:+33600000000"
        try:
            self.assertEqual(al.destinataires()["romain"], [("courriel", "romain@exemple.fr"), ("signal", "+33600000000")])
            with tempfile.TemporaryDirectory() as tmp:
                i, d = Index(Path(tmp)), Depot(Path(tmp))
                o = shopify.offre(PRODUIT_KBS, SOURCE_KBS)
                i.enregistrer("kbs", [o])
                d.enregistrer("a1", {"url": o["url"] + "/", "nom": "Pirate Ship", "prix": 184.95, "statut": "retenu"}, "julie")
                d.enregistrer("a2", {"url": o["url"], "nom": "Déjà acheté", "prix": 184.95, "statut": "achete"}, "julie")
                A = al.Alertes(Path(tmp), i, d, lambda: ["kbs"])
                envois = []
                self.assertEqual(A.verifier(lambda *a: envois.append(a)), {}, "premier passage : référence, sans alerte")
                i.enregistrer("kbs", [{**o, "prix": 150.0}])
                r = A.verifier(lambda *a: envois.append(a))
                self.assertEqual(sorted(r), ["julie", "romain"])
                self.assertEqual(len(envois), 2)
                self.assertIn("Pirate Ship : 154.95 € chez KBS, au lieu de 189.90 €", envois[0][2])
                self.assertNotIn("Déjà acheté", envois[0][2])
                os.environ["ALERTES"] = "julie=signal:group.abc==;romain=signal:group.abc==,courriel:r@exemple.fr"
                vus = []
                al.CANAUX["signal"], vieux = (lambda adr, *_: vus.append(adr)), al.CANAUX["signal"]
                al.CANAUX["courriel"], vieuxc = (lambda adr, *_: vus.append(adr)), al.CANAUX["courriel"]
                try:
                    i.enregistrer("kbs", [{**o, "prix": 120.0}])
                    A.verifier()
                finally:
                    al.CANAUX["signal"], al.CANAUX["courriel"] = vieux, vieuxc
                self.assertEqual(vus, ["group.abc==", "r@exemple.fr"], "groupe commun servi une fois")
        finally:
            if env is None:
                os.environ.pop("ALERTES", None)
            else:
                os.environ["ALERTES"] = env

    def test_reglages_obligatoires(self):
        import os
        from app import alertes as al
        from app.reglage import reglage
        vieux = {k: os.environ.get(k) for k in ("ALERTES", "SMTP_HOTE", "SMTP_UTILISATEUR", "SMTP_EXPEDITEUR",
                                                "SIGNAL_NUMERO", "RELEVE_HEURES")}
        try:
            for k in vieux:
                os.environ.pop(k, None)
            os.environ["RELEVE_HEURES"] = ""
            self.assertEqual(reglage("RELEVE_HEURES", "24"), "24", "ligne vide du .env = valeur par défaut")
            self.assertEqual(al.reglages_manquants(), [], "sans alerte, rien d'obligatoire")
            os.environ["ALERTES"] = "romain=courriel:r@exemple.fr,signal:group.abc,pigeon:x"
            m = al.reglages_manquants()
            self.assertIn("SMTP_HOTE (canal courriel)", m)
            self.assertIn("SIGNAL_NUMERO (canal signal)", m)
            self.assertIn("canal inconnu dans ALERTES : pigeon", m)
            os.environ.update(ALERTES="romain=signal:group.abc", SIGNAL_NUMERO="+33600000000")
            self.assertEqual(al.reglages_manquants(), [])
        finally:
            for k, v in vieux.items():
                os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)

    def test_envoi_signal(self):
        """Requête attendue par signal-cli-rest-api (POST /v2/send) et erreur rendue sur refus."""
        import json as js
        import os
        import threading
        from http.server import BaseHTTPRequestHandler, HTTPServer
        from app import alertes as al
        recu, statut = [], [201]

        class Faux(BaseHTTPRequestHandler):
            def do_POST(self):
                recu.append((self.path, js.loads(self.rfile.read(int(self.headers["Content-Length"])))))
                self.send_response(statut[0])
                self.end_headers()
                self.wfile.write(b'{"error":"User +33600000000 is not registered."}' if statut[0] >= 300 else b"{}")

            def log_message(self, *a):
                pass
        srv = HTTPServer(("127.0.0.1", 0), Faux)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        vieux = {k: os.environ.get(k) for k in ("SIGNAL_URL", "SIGNAL_NUMERO")}
        os.environ.update(SIGNAL_URL=f"http://127.0.0.1:{srv.server_port}/", SIGNAL_NUMERO="+33600000000")
        try:
            al.envoyer_signal("+33600000001", "Sujet", "Texte")
            self.assertEqual(recu[0], ("/v2/send", {"message": "Sujet\n\nTexte", "number": "+33600000000",
                                                    "recipients": ["+33600000001"]}))
            statut[0] = 400
            with self.assertRaisesRegex(RuntimeError, "400.*not registered"):
                al.envoyer_signal("+33600000001", "Sujet", "Texte")
            os.environ.pop("SIGNAL_NUMERO")
            with self.assertRaisesRegex(RuntimeError, "absent"):
                al.envoyer_signal("+33600000001", "Sujet", "Texte")
        finally:
            srv.shutdown()
            for k, v in vieux.items():
                os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)


class Configuration(unittest.TestCase):
    """Une valeur par défaut est écrite à trois endroits (compose, exemple de .env, code) : elle reste la même."""
    INTERNES = {"VERSION_APP", "PORT", "CHEMIN_DONNEES"}   # lues par le code, fixées par l'image
    PILOTAGE = {"COMPOSE_PROFILES"}                        # lues par Compose lui-même

    def lire(self):
        import re
        lignes = [l.split(" #")[0] for l in (RACINE / "compose.yaml").read_text("utf-8").splitlines()
                  if not l.lstrip().startswith("#")]
        compose: dict[str, tuple[str, str]] = {}
        for nom, op, val in re.findall(r"\$\{([A-Z_]+)(?::([-?])([^}]*))?\}", "\n".join(lignes)):
            self.assertIn(op, ("-", "?"), f"{nom} : ${{{nom}}} sans valeur ni exigence")
            self.assertEqual(compose.setdefault(nom, (op, val)), (op, val), f"{nom} : deux valeurs dans le compose")
        exemple = {}
        for l in (RACINE / ".env.example").read_text("utf-8").splitlines():
            m = re.match(r"^(# )?([A-Z_]+)=(.*)$", l)
            if m:
                exemple[m.group(2)] = (bool(m.group(1)), m.group(3))
        code = {}
        for p in (RACINE / "app").rglob("*.py"):
            for nom, val in re.findall(r'reglage\("([A-Z_]+)", "([^"]*)"', p.read_text("utf-8")):
                self.assertEqual(code.setdefault(nom, val), val, f"{nom} : deux valeurs par défaut dans le code")
        return compose, exemple, code

    def test_compose_et_exemple(self):
        compose, exemple, _ = self.lire()
        for nom, (op, val) in compose.items():
            self.assertIn(nom, exemple, f"{nom} absent de .env.example")
            commente, ex = exemple[nom]
            if op == "?":
                self.assertEqual((commente, ex), (False, ""), f"{nom} obligatoire : ligne active et vide")
            else:
                self.assertEqual((commente, ex), (True, val), f"{nom} : .env.example ne montre pas « {val} »")
        self.assertEqual(set(exemple) - set(compose) - self.PILOTAGE, set(), "variables de .env.example hors du compose")

    def test_compose_et_code(self):
        compose, _, code = self.lire()
        for nom, val in code.items():
            if nom in self.INTERNES:
                continue
            self.assertIn(nom, compose, f"{nom} lu par le code mais absent du compose")
            op, defaut = compose[nom]
            if op == "-":
                self.assertEqual(val, defaut, f"{nom} : défaut du code « {val} », du compose « {defaut} »")


class Synchronisation(unittest.TestCase):
    def setUp(self):
        from app import synchro
        from app.index import Index
        self.s = synchro
        self.tmp = tempfile.TemporaryDirectory()
        self.i, self.j = Index(Path(self.tmp.name)), synchro.Journal(Path(self.tmp.name))
        self.vrai = dict(synchro.CONNECTEURS)
        self.env = os.environ.get("SOURCES")
        os.environ["SOURCES"] = "kbs,bausteinreich"

    def tearDown(self):
        self.s.CONNECTEURS.clear(); self.s.CONNECTEURS.update(self.vrai)
        self.s._PROG.update(heures=0.0, fil=None)
        if self.env is None:
            os.environ.pop("SOURCES", None)
        else:
            os.environ["SOURCES"] = self.env
        self.tmp.cleanup()

    def test_source_en_echec_n_arrete_pas_les_autres(self):
        from app.sources import shopify
        def faux(src, pause=0, progres=None):
            if src["id"] == "bausteinreich":
                raise lien.LienRefuse("le site a répondu 503")
            return [shopify.offre(PRODUIT_KBS, SOURCE_KBS)]
        self.s.CONNECTEURS["shopify"] = faux
        import logging
        logging.disable(logging.CRITICAL)
        try:
            j = self.s.synchroniser(self.i, self.j, pause=0)
        finally:
            logging.disable(logging.NOTSET)
        etats = {r["id"]: r["etat"] for r in j["sources"]}
        self.assertEqual(etats, {"kbs": "ok", "bausteinreich": "echec"})
        self.assertEqual(j["echecs"], 1)
        self.assertEqual(self.s.sante(self.j), (True, "ok"))
        self.assertEqual(len([x for x in self.i.sets(["kbs"]) if x["marque"] != "LEGO officiel"]), 1)

    def test_sante_toutes_en_echec(self):
        self.s.CONNECTEURS["shopify"] = lambda src, pause=0, progres=None: (_ for _ in ()).throw(OSError("coupé"))
        import logging
        logging.disable(logging.CRITICAL)
        try:
            self.s.synchroniser(self.i, self.j, pause=0)
        finally:
            logging.disable(logging.NOTSET)
        self.assertFalse(self.s.sante(self.j)[0])
        self.s._PROG.update(heures=24.0, fil=None)
        self.assertEqual(self.s.sante(self.j)[1], "synchronisation programmée arrêtée")


class Serveur(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from app import serveur
        cls.tmp = tempfile.TemporaryDirectory()
        G = serveur.Gestionnaire
        from app import synchro
        from app.index import Index
        G.depot = Depot(Path(cls.tmp.name))
        G.index = Index(Path(cls.tmp.name))
        G.journal = synchro.Journal(Path(cls.tmp.name))
        from app.logos import Logos
        G.logos = Logos(Path(cls.tmp.name))
        G.logos.dossier.mkdir(parents=True)
        (G.logos.dossier / "cobi.svg").write_bytes(b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>')
        (G.logos.dossier / "logos.json").write_text('{"cobi": {"fichier": "cobi.svg", "format": "svg", "le": "2026-11-20T00:00:00"}, '
                                                    '"piege": {"fichier": "../../../../etc/passwd", "format": "svg", "le": "2026-11-20T00:00:00"}}')
        G.gardien = acces.Gardien({"bruno": acces.empreinte("motdepasse-b", iterations=1000),
                                   "alice": acces.empreinte("motdepasse-a", iterations=1000)})
        G.masquer = {"bruno"}
        G.admins = {"alice"}
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), G)
        cls.base = f"http://127.0.0.1:{cls.srv.server_address[1]}"
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.tmp.cleanup()

    def req(self, methode, chemin, qui=None, corps=None):
        h = {"Content-Type": "application/json"}
        if qui:
            h["Authorization"] = "Basic " + base64.b64encode(f"{qui}:motdepasse-{qui[0]}".encode()).decode()
        r = urllib.request.Request(self.base + chemin, method=methode, headers=h,
                                   data=json.dumps(corps).encode() if corps is not None else None)
        try:
            with urllib.request.urlopen(r) as rep:
                return rep.status, rep.read().decode(), dict(rep.headers)
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode(), dict(e.headers)

    def test_sante_sans_compte(self):
        self.assertEqual(self.req("GET", "/api/sante")[0], 200)

    def test_catalogue_et_synchro(self):
        code, corps, _ = self.req("GET", "/api/catalogue", "alice")
        d = json.loads(corps)
        self.assertEqual(code, 200)
        self.assertTrue(d["themes"] and any(s["marque"] == "LEGO officiel" for s in d["sets"]))
        code, corps, _ = self.req("GET", "/api/synchro", "alice")
        self.assertIn("en_cours", json.loads(corps)["etat"])
        self.assertEqual(self.req("POST", "/api/synchro", "alice", {"sources": "kbs"})[0], 400)

    def test_catalogue_compresse(self):
        import gzip
        r = urllib.request.Request(self.base + "/api/catalogue", headers={
            "Accept-Encoding": "gzip", "Authorization": "Basic " + base64.b64encode(b"alice:motdepasse-a").decode()})
        with urllib.request.urlopen(r) as rep:
            self.assertEqual(rep.headers["Content-Encoding"], "gzip")
            self.assertIn("sets", json.loads(gzip.decompress(rep.read())))

    def test_type_impose_par_un_administrateur(self):
        code, corps, _ = self.req("GET", "/api/catalogue", "alice")
        sid = json.loads(corps)["sets"][0]["id"]
        self.assertEqual(self.req("POST", "/api/type", "bruno", {"id": sid, "type": "technic"})[0], 403)
        self.assertEqual(self.req("POST", "/api/type", "alice", {"id": sid, "type": "duplo"})[0], 400)
        self.assertEqual(self.req("POST", "/api/type", "alice", {"id": "inconnu-0", "type": "technic"})[0], 404)
        # requête d'une page tierce : refusée même avec les identifiants du navigateur
        r = urllib.request.Request(self.base + "/api/type", method="POST", data=json.dumps({"id": sid, "type": "technic"}).encode(),
                                   headers={"Content-Type": "text/plain", "Authorization": "Basic " + base64.b64encode(b"alice:motdepasse-a").decode()})
        with self.assertRaises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(r)
        self.assertEqual(e.exception.code, 403)
        r = urllib.request.Request(self.base + "/api/type", method="POST", data=json.dumps({"id": sid, "type": "technic"}).encode(),
                                   headers={"Content-Type": "application/json", "Sec-Fetch-Site": "cross-site",
                                            "Authorization": "Basic " + base64.b64encode(b"alice:motdepasse-a").decode()})
        with self.assertRaises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(r)
        self.assertEqual(e.exception.code, 403)
        self.assertEqual(self.req("POST", "/api/type", "alice", ["liste"])[0], 400)
        self.assertEqual(self.req("POST", "/api/type", "alice", {"id": sid, "type": "technic"})[0], 200)
        d = json.loads(self.req("GET", "/api/catalogue", "alice")[1])
        self.assertEqual(next(x for x in d["sets"] if x["id"] == sid)["type"], "technic")
        self.assertEqual(self.req("POST", "/api/type", "alice", {"id": sid, "type": "classique"})[0], 200)
        d = json.loads(self.req("GET", "/api/catalogue", "alice")[1])
        self.assertEqual(next(x for x in d["sets"] if x["id"] == sid)["type"], "classique")
        self.assertIn('"admin": true', self.req("GET", "/", "alice")[1])
        self.assertIn('"admin": false', self.req("GET", "/", "bruno")[1])
        self.assertEqual(self.req("POST", "/api/type", "alice", {"id": sid, "type": None})[0], 200)
        # fichier local mal formé : ignoré sans priver le catalogue
        (Path(self.tmp.name) / "corrections_locales.json").write_text('{"sets": {"x": "technic", "' + sid + '": {"type": "duplo"}}}')
        self.assertEqual(self.req("GET", "/api/catalogue", "alice")[0], 200)

    def test_logo_isole(self):
        code, corps, h = self.req("GET", "/logos/cobi")
        self.assertEqual((code, h["Content-Type"]), (200, "image/svg+xml"))
        self.assertIn("sandbox", h["Content-Security-Policy"])
        self.assertEqual(self.req("GET", "/logos/inconnu")[0], 404)
        self.assertIn(self.req("GET", "/logos/../logos.json")[0], (401, 404))
        self.assertEqual(self.req("GET", "/logos/piege")[0], 404)
        code, page, _ = self.req("GET", "/", "alice")
        self.assertIn('"logos": {"cobi": "logos/cobi?v=2026-11-20", ', page)

    def test_formats_logo(self):
        from app import logos
        self.assertEqual(logos._format(b"\x89PNG\r\n"), "png")
        self.assertEqual(logos._format(b'<?xml version="1.0"?>\n<svg></svg>'), "svg")
        self.assertIsNone(logos._format(b"<html>pas une image</html>"))
        self.assertEqual(logos._format(b'  <?xml version="1.0"?><!-- a --> <!----><svg viewBox="0 0 1 1"/>'), "svg")
        self.assertIsNone(logos._format(b"<!-- a --><svgx/>"))
        self.assertIsNone(logos._format(b"<!-- sans fin <svg>"))

    def test_format_logo_temps_lineaire(self):
        """Une suite de commentaires sans <svg> se lit d'un seul passage (temps exponentiel avant la v3.8.2)."""
        from app import logos
        debut = time.perf_counter()
        self.assertIsNone(logos._format(b"<!---->" * 285 + b"x"))
        self.assertLess(time.perf_counter() - debut, 0.1)

    def test_page_protegee(self):
        self.assertEqual(self.req("GET", "/")[0], 401)
        code, page, h = self.req("GET", "/", "alice")
        self.assertEqual(code, 200)
        self.assertIn('"serveur": true', page)
        nonce = h["Content-Security-Policy"].split("'nonce-")[1].split("'")[0]
        self.assertIn(f'<script nonce="{nonce}">', page)
        self.assertNotIn("onerror=", page)

    def test_achats_masques(self):
        self.req("PUT", "/api/selection/cadeau1", "alice", {"url": "https://ex.com/a", "statut": "achete"})
        self.req("PUT", "/api/selection/idee1", "bruno", {"url": "https://ex.com/b", "statut": "idee"})
        vu_alice = json.loads(self.req("GET", "/api/selection", "alice")[1])
        vu_bruno = json.loads(self.req("GET", "/api/selection", "bruno")[1])
        self.assertEqual(sorted(s["id"] for s in vu_alice), ["cadeau1", "idee1"])
        self.assertEqual([s["id"] for s in vu_bruno], ["idee1"])
        self.assertEqual(self.req("DELETE", "/api/selection/cadeau1", "bruno")[0], 404)
        self.assertEqual(self.req("PUT", "/api/selection/cadeau1", "bruno", {"url": "https://ex.com/a"})[0], 404)

    def test_lien_local_refuse(self):
        code, corps, _ = self.req("GET", "/api/lien?url=http://127.0.0.1/", "alice")
        self.assertEqual(code, 422)
        self.assertIn("refusée", corps)


class Surveillance(unittest.TestCase):
    def journal(self, lus):
        return {"historique": [{"sources": [{"id": "kbs", "nom": "KBS", "etat": "ok", "lus": n, "dims": n}]} for n in lus]}

    def test_baisse_de_lecture(self):
        from app import surveillance as sv
        self.assertEqual(sv.baisses(self.journal([290, 299, 301, 298])), {})
        b = sv.baisses(self.journal([150, 299, 301, 298]))
        self.assertEqual(set(b), {"kbs:lus", "kbs:dims"})
        self.assertIn("150 sets lus", b["kbs:lus"])
        self.assertEqual(sv.baisses(self.journal([150, 299])), {}, "pas d'alerte sans au moins deux passages de référence")
        self.assertIn("bricksvalue:erreurs", sv.baisses({}, {"lues": 100, "erreurs": 30}))

    def test_messages_et_copie(self):
        from app import surveillance as sv, synchro
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "selection.json").write_text("[]")
            envois = []
            j = synchro.Journal(Path(d))
            s = sv.Surveillance(Path(d), j, Index(Path(d)), envoi=lambda sujet, texte: envois.append(sujet) or [], relire_livraison=False)
            vrai = synchro.sante
            try:
                synchro.sante = lambda journal, m=None: (False, "toutes les sources en échec")
                s.verifier(); s.verifier()
                synchro.sante = lambda journal, m=None: (True, "ok")
                s.verifier()
            finally:
                synchro.sante = vrai
            self.assertEqual(envois, ["Carnet de briques : service dégradé", "Carnet de briques : service rétabli"])
            j.enregistrer({"le": "x", "portee": "toutes", "sources": [{"id": "kbs", "nom": "KBS", "etat": "ok", "lus": 300, "dims": 300}]})
            j.enregistrer({"le": "x", "portee": "toutes", "sources": [{"id": "kbs", "nom": "KBS", "etat": "ok", "lus": 300, "dims": 300}]})
            j.enregistrer({"le": "x", "portee": "toutes", "sources": [{"id": "kbs", "nom": "KBS", "etat": "ok", "lus": 100, "dims": 100}]})
            synchro.sante = lambda journal, m=None: (True, "ok")
            try:
                s.verifier(); s.verifier()
            finally:
                synchro.sante = vrai
            self.assertEqual(envois[2:], ["Carnet de briques : 2 points à vérifier"], "une baisse n'est signalée qu'une fois")
            for jour in range(20):
                s.copier_selection(1795132800 + jour * 86400)
            self.assertEqual(len(list((Path(d) / "sauvegardes").glob("selection-*.json"))), 14)


class Classement(unittest.TestCase):
    def test_type_de_briques(self):
        from app import normalise as n
        self.assertEqual(n.type_briques("Brickbuild-Set", ["Technik Sets"]), "classique", "catégorie de la boutique d'abord")
        self.assertEqual(n.type_briques("Building Toys", ["Construction"], "Mould King 17106 Crawler Crane"), "technic")
        self.assertIsNone(n.type_briques("Building Toys", ["Technic-Vehicles"], "Mould King 10114 Vintage Convertible"),
                          "le mot Technic d'une étiquette ne suffit pas (voitures à picots de Mould King)")
        self.assertIsNone(n.type_briques("Building Toys", ["Motorized Model Building Kit"], "Mould King 12007 BR18 Train"))
        self.assertEqual(n.type_briques("Building Toys", ["Botanicals And Home Decor"], "Mould King 10290 Vine"), "classique")
        self.assertEqual(n.type_briques("", [], "Cobi 2670 Panzer", "Cobi"), "classique")
        self.assertIsNone(n.type_briques("Building Toys", ["Robots and Mecha"], "Mould King 93012 Sentinel", "Mould King"))

    def test_themes_mots_composes_et_etiquettes(self):
        from app import normalise as n
        self.assertIn("militaire", n.themes("Cobi Jagdpanzer IV/70 Wintertarnung"))
        self.assertIn("architecture", n.themes("Wange Blaue Moschee Istanbul"))
        self.assertIn("fleurs", n.themes("Mould King 24100 Amber Bloom Bouquet Flower Building Set"))
        self.assertNotIn("architecture", n.themes("Mould King 24133 Semi Truck Building Set"), "« Building Set » n'est pas un bâtiment")
        self.assertEqual(n.themes("Mould King 12054 Steam Locomotive", ["Architecture And Rail"]), ["trains"],
                         "une étiquette mêlant deux sujets ne classe pas, le nom tranche")
        self.assertNotIn("robots", n.themes("Mould King Forklift", ["Mechanical"]), "étiquette comparée par mot entier")

    def test_dimensions_dans_le_texte(self):
        from app import normalise as n
        self.assertEqual(n.dimensions("At 44 cm long with four-wheel suspension"), [44.0])
        self.assertEqual(n.dimensions("Measuring 43 cm wide and 48 cm tall."), [48.0, 43.0])
        self.assertEqual(n.dimensions('it measures 16.7" (42.5 cm) long'), [42.5])
        self.assertIsNone(n.dimensions("Circular display track included (approx. 71cm loop)"))


class Corrections(unittest.TestCase):
    def test_regrouper_separer_imposer(self):
        from app import index as ix
        offre = lambda cle, num, marque="Mould King": {"source": cle.split(":")[0], "boutique": "B", "pays": "Allemagne", "cle": cle,
                                                     "url": "https://x/" + cle, "nom": f"{marque} {num} Truck", "marque": marque,
                                                     "numero": num, "prix": 100.0, "dispo": "vente", "themes": [], "type": None}
        vrai = ix.corrections
        with tempfile.TemporaryDirectory() as d:
            i = Index(Path(d))
            i.enregistrer("kbs", [offre("kbs:a", "17001"), offre("kbs:b", "17002"), offre("kbs:c", "17003")])
            i.enregistrer("mouldkingcorp", [offre("mouldkingcorp:a", "17001")])
            try:
                ix.corrections = lambda: {"regrouper": [["kbs:b", "kbs:c"]], "separer": ["mouldkingcorp:a"],
                                          "sets": {"mould-king-17001": {"type": "technic", "nom": "Camion"}}}
                i._cache = None
                sets = {s["id"]: s for s in i.sets(["kbs", "mouldkingcorp"])}
            finally:
                ix.corrections = vrai
        groupes = sorted(sorted(o["cle"] for o in s["offres"]) for s in sets.values() if s["offres"][0]["source"] != "editorial")
        self.assertEqual(groupes, [["kbs:a"], ["kbs:b", "kbs:c"], ["mouldkingcorp:a"]])
        self.assertEqual((sets["mould-king-17001"]["type"], sets["mould-king-17001"]["nom"]), ("technic", "Camion"))

    def test_ordre_de_preuve_du_type(self):
        """Administrateur, puis corrections, puis photos, puis série et signaux des boutiques."""
        from app import index as ix
        offre = lambda num, t: {"source": "kbs", "boutique": "B", "pays": "Allemagne", "cle": f"kbs:{num}", "url": f"https://x/{num}",
                                "nom": f"Marque Essai {num}", "marque": "Mould King", "numero": num, "prix": 100.0,
                                "dispo": "vente", "themes": [], "type": t}
        vrais = ix.corrections, ix.types_photos
        with tempfile.TemporaryDirectory() as d:
            i = Index(Path(d))
            i.enregistrer("kbs", [offre("88001", "technic"), offre("88002", "technic"), offre("88003", "technic"), offre("88004", None)])
            try:
                ix.types_photos = lambda: {"mould-king-88001": "classique", "mould-king-88002": "classique", "mould-king-88003": "classique"}
                ix.corrections = lambda: {"sets": {"mould-king-88002": {"type": "technic"}}}
                i.imposer_type("mould-king-88003", "technic", "alice")
                i._cache = None
                t = {s["id"]: s["type"] for s in i.sets(["kbs"])}
            finally:
                ix.corrections, ix.types_photos = vrais
        self.assertEqual([t[f"mould-king-8800{k}"] for k in (1, 2, 3)], ["classique", "technic", "technic"],
                         "photo sur l'étiquette ; correction sur la photo ; administrateur sur tout")
        self.assertIsNone(t["mould-king-88004"], "série trop petite : pas de type inventé")

    def test_etalon_et_corrections_sans_contradiction(self):
        from app.index import types_photos, corrections
        photos = types_photos()
        ecarts = {i: (c["type"], photos[i]) for i, c in corrections().get("sets", {}).items()
                  if c.get("type") and i in photos and photos[i] != c["type"]}
        self.assertEqual(ecarts, {}, "une correction qui contredit l'étalon des photos doit être tranchée dans l'un des deux fichiers")


class Relecture(unittest.TestCase):
    def test_une_lecture_par_fiche(self):
        from app import synchro
        with tempfile.TemporaryDirectory() as d:
            i = Index(Path(d))
            _ecrire(i.fichier("bricksvalue"), {"offres": [], "fiches": {"75192": {"url": "https://bricksvalue.com/fr/set/75192-x", "lu": None}}})
            lus = []
            vrai = synchro.lire_une

            def faux(index, num, url):
                lus.append(num)
                return [{"cle": "bricksvalue:75192:lego-com", "prix": 849.99, "dispo": "vente", "releve": "2026-11-20"}]
            synchro.lire_une = faux
            try:
                r = synchro.relire(i, ["bricksvalue:75192:lego-com", "bricksvalue:75192:amazon-fr", "inconnue:x"])
            finally:
                synchro.lire_une = vrai
        self.assertEqual(lus, ["75192"])
        self.assertEqual(r["bricksvalue:75192:lego-com"]["releve"], "2026-11-20")
        self.assertIn("erreur", r["bricksvalue:75192:amazon-fr"])
        self.assertIn("erreur", r["inconnue:x"])


class Relecture2(unittest.TestCase):
    def test_doublons_bornes_et_pause(self):
        from app import synchro
        appels = []
        vrai = synchro.offre_directe
        synchro.offre_directe = lambda index, cle: appels.append(cle) or {"prix": 10.0, "dispo": "vente", "releve": "x"}
        synchro._RELUES.clear()
        try:
            with tempfile.TemporaryDirectory() as d:
                i = Index(Path(d))
                synchro.relire(i, ["kbs:a"] * 30 + ["kbs:b"])
                synchro.relire(i, ["kbs:a"])
                synchro.relire(i, [f"kbs:p{k}" for k in range(60)])
        finally:
            synchro.offre_directe = vrai
            synchro._RELUES.clear()
        self.assertEqual(appels[:2], ["kbs:a", "kbs:b"], "une clé répétée n'est lue qu'une fois")
        self.assertEqual(len(appels), 2 + synchro.RELIRE_MAX, "relue à l'instant : pas de seconde lecture ; 40 offres au plus")

    def test_poignee_refusee(self):
        from app import synchro
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(synchro.LienRefuse):
                synchro.offre_directe(Index(Path(d)), "kbs:../../admin?x=1")

    def test_revendeur_et_date(self):
        from app.sources import lego
        r = {"lego": "2026-11-20", "amazon": "2026-11-19", "amazonwarehouse": "2026-11-10"}
        self.assertEqual([lego._releve_pour(x, r) for x in ("LEGO.com", "Amazon Warehouse", "Amazon.fr", "Fnac")],
                         ["2026-11-20", "2026-11-10", "2026-11-19", None])


class Livraison(unittest.TestCase):
    def test_port_lu_vraisemblable(self):
        from app import livraison as lv
        self.assertEqual(lv.port_du_pays("Finland 7,95 € 1–3 working days France 4,95 € 1–3 working days", "France"), 4.95)
        self.assertEqual(lv.montants("ab 55 € gratuit, sinon 5,95€ ou €3.90"), {55.0, 5.95, 3.9})
        pages = [{"nom": "KBS", "url": "https://x", "attendus": [4.95], "motif_pays": "France", "source_id": "kbs", "port_ecrit": 4.95}]
        vrai_pages, vrai_rec = lv.pages, lv.lien.recuperer
        try:
            lv.pages = lambda: pages
            for texte, attendu in (("France 59,00 € dès 99 €", None), ("France 5,95 €", 5.95)):
                lv.lien.recuperer = lambda url, **k: lv.lien.Reponse(url, 200, "text/html", texte.encode())
                with tempfile.TemporaryDirectory() as d:
                    lv.relire(Path(d), pause=0)
                    self.assertEqual(lv.ports_lus(Path(d)).get("kbs"), attendu)
                    if attendu is None:
                        self.assertIn("livraison-douteux:KBS", lv.ecarts(Path(d)), "montant invraisemblable : signalé, non appliqué")
        finally:
            lv.pages, lv.lien.recuperer = vrai_pages, vrai_rec


class Robustesse(unittest.TestCase):
    def test_corrections_illisibles_ou_mal_formees(self):
        from app import index as ix
        vrai = ix.RACINE
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "data").mkdir()
            for f in ("themes.json",):
                (Path(d) / "data" / f).write_text((vrai / "data" / f).read_text("utf-8"), "utf-8")
            (Path(d) / "data" / "corrections.json").write_text('{"sets": {"a": {"themes": "trains", "type": "technic"}},}')
            try:
                ix.RACINE = Path(d)
                self.assertEqual(ix.corrections(), {}, "JSON invalide : ignoré")
                (Path(d) / "data" / "corrections.json").write_text('{"sets": {"a": {"themes": "trains", "type": "technic", "nom": 3}}}')
                self.assertEqual(ix.corrections()["sets"], {"a": {"type": "technic"}}, "valeurs mal formées écartées")
            finally:
                ix.RACINE = vrai

    def test_surveillance_reessaie_si_envoi_en_echec(self):
        from app import surveillance as sv, synchro
        with tempfile.TemporaryDirectory() as d:
            envois = []
            s = sv.Surveillance(Path(d), synchro.Journal(Path(d)), Index(Path(d)),
                                envoi=lambda sujet, texte: envois.append(sujet) or ["courriel : TimeoutError"], relire_livraison=False)
            vrai = synchro.sante
            try:
                synchro.sante = lambda journal, m=None: (False, "toutes les sources en échec")
                s.verifier(); s.verifier()
            finally:
                synchro.sante = vrai
        self.assertEqual(len(envois), 2, "message non parti : renvoyé au passage suivant")


class TypeParSerie(unittest.TestCase):
    def test_serie_majoritaire(self):
        from app.index import types_par_serie
        sets = [{"marque": "Mould King", "numero": f"170{k:02d}", "type": "technic"} for k in range(9)]
        sets += [{"marque": "Mould King", "numero": "17099", "type": "classique"},
                 {"marque": "Mould King", "numero": "17100", "type": None},
                 {"marque": "Mould King", "numero": "24001", "type": None},
                 {"marque": "Cobi", "numero": "17101", "type": None}]
        types_par_serie(sets)
        self.assertEqual([s["type"] for s in sets[-3:]], ["technic", None, None],
                         "9 sur 10 dans la série 17 de Mould King : Technic ; rien pour une autre série ou une autre marque")
        sets[9]["type"] = sets[8]["type"] = "classique"
        sets[-3]["type"] = None
        types_par_serie(sets)
        self.assertIsNone(sets[-3]["type"], "8 sur 10 : sous le seuil de 90 %")

    def test_serie_comptee_sur_les_types_surs(self):
        from app.index import types_par_serie
        # 10 sets sûrs (photos) à picots dans la série 10 ; un set de la série classé Technic par une étiquette
        sets = [{"id": f"s{k}", "marque": "Mould King", "numero": f"100{k:02d}", "type": "classique"} for k in range(10)]
        sets += [{"id": "x", "marque": "Mould King", "numero": "10114", "type": "technic"},
                 {"id": "y", "marque": "Mould King", "numero": "10115", "type": "technic"}]
        types_par_serie(sets, surs={f"s{k}" for k in range(10)} | {"y"})
        self.assertEqual((sets[-2]["type"], sets[-1]["type"]), ("classique", "technic"),
                         "la série l'emporte sur l'étiquette, jamais sur un type sûr")

    def test_types_photos_valides(self):
        from app.index import types_photos
        t = types_photos()
        self.assertTrue(t and set(t.values()) <= {"technic", "classique"})


if __name__ == "__main__":
    unittest.main()

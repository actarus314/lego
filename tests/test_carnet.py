import base64
import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from app import acces, lien
from app.donnees import Depot

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
        G.gardien = acces.Gardien({"bruno": acces.empreinte("motdepasse-b", iterations=1000),
                                   "alice": acces.empreinte("motdepasse-a", iterations=1000)})
        G.masquer = {"bruno"}
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
        code, corps, _ = self.req("GET", "/api/lien?url=http://127.0.0.1:22/", "alice")
        self.assertEqual(code, 422)
        self.assertIn("refusée", corps)


if __name__ == "__main__":
    unittest.main()

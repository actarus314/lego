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

    def test_pieces(self):
        self.assertEqual(lien.nombre_pieces("Avec 3 887 pièces et"), 3887)
        self.assertEqual(lien.nombre_pieces("With 12,688 pieces"), 12688)
        self.assertEqual(lien.nombre_pieces("1500 Teile"), 1500)
        self.assertIsNone(lien.nombre_pieces("aucun nombre ici"))

    def test_shopify(self):
        d = lien.depuis_shopify({"title": "Big Ben", "price": 64995, "available": True,
                                 "featured_image": "//cdn.shopify.com/x.jpg", "description": "<p>13,825 pieces</p>"})
        self.assertEqual((d["nom"], d["prix"], d["dispo"], d["pcs"]), ("Big Ben", 649.95, True, 13825))
        self.assertTrue(d["img"].startswith("https://cdn.shopify.com"))

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
        self.d = Depot(Path(self.tmp.name), RACINE / "data" / "catalogue.json")

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

    def test_releve_fusionne(self):
        cat = self.d.catalogue()
        self.d.enregistrer_releve({cat[0]["id"]: {"prix": 1.5, "dispo": False, "le": "2026-11-19T10:00:00"}}, {"le": "x"})
        neuf = self.d.catalogue()[0]
        self.assertEqual((neuf["prix"], neuf["dispo"], neuf["releve"]), (1.5, False, "2026-11-19T10:00:00"))

    def test_catalogue_complet(self):
        for it in self.d.catalogue():
            for k in ("id", "nom", "marque", "theme", "type", "prix", "url", "img"):
                self.assertIn(k, it, f"{it.get('id')} sans {k}")
            self.assertTrue(it["url"].startswith("https://"))


class Serveur(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from app import serveur
        cls.tmp = tempfile.TemporaryDirectory()
        G = serveur.Gestionnaire
        G.depot = Depot(Path(cls.tmp.name), RACINE / "data" / "catalogue.json")
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

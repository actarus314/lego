"""Tests du cache local des photos (app/cache_photos.py) et de son remplissage par app/photos.py,
sans réseau : `lien.recuperer` est simulé."""
from __future__ import annotations

import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from app import cache_photos as cp, lien, photos

JPG = b"\xff\xd8\xff\xe0" + b"j" * 100
PNG = b"\x89PNG\r\n\x1a\n" + b"p" * 40
SHOP = "https://cdn.shopify.com/s/files/1/a.jpg?v=12"
AUTRE = "https://images.exemple.fr/sets/b.jpg"


def rep(corps=JPG, type_="image/jpeg", entetes=None, url=SHOP):
    return lien.Reponse(url, 200, type_, corps, None, entetes or {})


class Variante(unittest.TestCase):
    def test_shopify_largeur_remplacee_version_gardee(self):
        self.assertEqual(cp.variante(SHOP, 400), ("https://cdn.shopify.com/s/files/1/a.jpg?v=12&width=400", True))
        u, _ = cp.variante("https://cdn.shopify.com/a.jpg?width=2048&height=9&v=3", 1200)
        self.assertEqual(u, "https://cdn.shopify.com/a.jpg?v=3&width=1200")

    def test_rebrickable_et_brickset_tailles_publiees(self):
        rb = "https://cdn.rebrickable.com/media/sets/75192-1.jpg"
        self.assertEqual(cp.variante(rb, 400)[0], "https://cdn.rebrickable.com/media/thumbs/sets/75192-1.jpg/400x400p.jpg")
        self.assertEqual(cp.variante(rb, 1200)[0], "https://cdn.rebrickable.com/media/thumbs/sets/75192-1.jpg/1000x800p.jpg")
        bs = "https://images.brickset.com/sets/images/75192-1.jpg"
        self.assertEqual(cp.variante(bs, 400), ("https://images.brickset.com/sets/small/75192-1.jpg", True))
        self.assertEqual(cp.variante(bs, 1200), (bs, True))
        self.assertEqual(cp.variante("https://cdn.rebrickable.com/media/parts/x.png", 400)[1], False)

    def test_site_sans_parametre(self):
        self.assertEqual(cp.variante(AUTRE, 400), (AUTRE, False))


class Cache(unittest.TestCase):
    def setUp(self):
        self.c = cp.CachePhotos(Path(tempfile.mkdtemp()))

    def test_vignette_gardee_avec_son_format(self):
        with mock.patch.object(lien, "recuperer", return_value=rep()) as m:
            chemin, _ = self.c.telecharger(SHOP, "v")
        self.assertTrue(chemin.name.endswith("-v.jpg"))
        self.assertIn("width=400", m.call_args.args[0])
        self.assertTrue(self.c.present(SHOP, "v"))
        self.assertFalse(self.c.present(SHOP, "g"))   # Shopify : la grande se demande à part

    def test_site_sans_parametre_une_photo_pour_deux_tailles(self):
        with mock.patch.object(lien, "recuperer", return_value=rep(PNG, "image/png", url=AUTRE)) as m:
            self.c.telecharger(AUTRE, "g")
            self.assertEqual(self.c.servir(AUTRE, 900), (PNG, "image/png"))   # la vignette sert de grande
        self.assertEqual(m.call_count, 1)
        self.assertTrue(self.c.present(AUTRE, "v"))
        self.assertFalse(self.c.present(AUTRE, "g"))   # gardée une seule fois

    def test_avif_non_demande(self):
        with mock.patch.object(lien, "recuperer", return_value=rep()) as m:
            self.c.telecharger(SHOP, "v")
        self.assertNotIn("avif", m.call_args.kwargs["accept"])

    def test_echec_a_la_demande_pas_retente_avant_une_heure(self):
        with mock.patch.object(lien, "recuperer", side_effect=lien.LienRefuse("le site a répondu 503")) as m:
            self.assertIsNone(self.c.servir(SHOP, 240))
            self.assertIsNone(self.c.servir(SHOP, 240))
        self.assertEqual(m.call_count, 1)

    def test_pause_429_retentee_a_sa_fin(self):
        e = lien.LienRefuse("site en pause après un refus 429 (encore 20 s)")
        e.statut, e.pause, e.attente = 429, True, "20"
        with mock.patch.object(lien, "recuperer", side_effect=e):
            self.assertIsNone(self.c.servir(SHOP, 240))
        with mock.patch.object(lien, "recuperer", return_value=rep()) as m, \
                mock.patch.object(cp.time, "time", return_value=time.time() + 25):
            self.assertEqual(self.c.servir(SHOP, 240), (JPG, "image/jpeg"))   # pas une heure d'attente
        m.assert_called_once()

    def test_ecriture_impossible(self):
        self.c.dossier.parent.mkdir(parents=True, exist_ok=True)
        self.c.dossier.write_text("pas un dossier")   # dossier du cache inutilisable
        with mock.patch.object(lien, "recuperer", return_value=rep()):
            with self.assertRaises(cp.CacheLocal):
                self.c.telecharger(SHOP, "v")

    def test_fichier_retire_entre_temps(self):
        with mock.patch.object(lien, "recuperer", return_value=rep()):
            self.c.telecharger(SHOP, "v")
        with mock.patch.object(Path, "read_bytes", side_effect=FileNotFoundError):
            self.assertIsNone(self.c.servir(SHOP, 240))

    def test_page_svg_ou_trop_lourde_refusees(self):
        cas = [(rep(b"<html>non</html>", "text/html"), True),
               (rep(b"<svg xmlns='http://www.w3.org/2000/svg'/>", "image/svg+xml"), False),
               (rep(b"\xff\xd8" + b"x" * (cp.ORIGINE_MAX - 2), "image/jpeg"), False)]
        for r, page in cas:
            with self.subTest(type=r.type), mock.patch.object(lien, "recuperer", return_value=r):
                with self.assertRaises(cp.PhotoIllisible) as e:
                    self.c.telecharger(SHOP, "v")
                self.assertEqual(e.exception.page, page)
        self.assertFalse(self.c.present(SHOP, "v"))

    def test_servir_vignette_puis_grande_a_la_demande(self):
        with mock.patch.object(lien, "recuperer", return_value=rep()) as m:
            corps, type_ = self.c.servir(SHOP, 240)
            self.assertEqual((corps, type_), (JPG, "image/jpeg"))
            self.c.servir(SHOP, 240)                       # déjà gardée : aucune requête
            self.assertEqual(m.call_count, 1)
            self.c.servir(SHOP, 900)                       # grande : téléchargée à la demande
            self.assertIn("width=1200", m.call_args.args[0])
            self.assertEqual(m.call_count, 2)
        self.assertTrue(self.c.present(SHOP, "g"))

    def test_grande_indisponible_repli_sur_vignette(self):
        with mock.patch.object(lien, "recuperer", return_value=rep()):
            self.c.telecharger(SHOP, "v")
        with mock.patch.object(lien, "recuperer", side_effect=lien.LienRefuse("le site a répondu 503")):
            self.assertEqual(self.c.servir(SHOP, 900), (JPG, "image/jpeg"))
            self.assertIsNone(self.c.servir(AUTRE, 240))

    def test_cache_plein_aucune_vignette_telechargee(self):
        self.c.plein = True
        with mock.patch.object(lien, "recuperer", return_value=rep()) as m:
            self.assertIsNone(self.c.servir(SHOP, 240))
        m.assert_not_called()

    def test_entretien_retire_les_oubliees(self):
        with mock.patch.object(lien, "recuperer", return_value=rep()):
            self.c.telecharger(SHOP, "v")
            self.c.telecharger("https://cdn.shopify.com/c.jpg", "v")
        r = self.c.entretenir({SHOP})
        self.assertEqual(r["retirees"], 1)
        self.assertTrue(self.c.present(SHOP))
        self.assertFalse(self.c.present("https://cdn.shopify.com/c.jpg"))

    def test_plafond_grandes_les_moins_demandees_d_abord(self):
        urls = [f"https://cdn.shopify.com/{i}.jpg" for i in range(3)]
        with mock.patch.object(lien, "recuperer", return_value=rep(b"\xff\xd8" + b"g" * 1000)):
            for u in urls:
                self.c.telecharger(u, "g")
        for i, u in enumerate(urls):   # 0 : la plus ancienne demande
            os.utime(self.c._fichier(u, "g"), (time.time() - 1000 + i, time.time() - 1000 + i))
        with mock.patch.object(cp, "quota_octets", return_value=2100):
            r = self.c.entretenir(set(urls))
        self.assertEqual(r["purgees_grandes"], 2)
        self.assertEqual([self.c.present(u, "g") for u in urls], [False, False, True])
        self.assertFalse(self.c.plein)

    def test_vignettes_seules_au_dela_du_plafond(self):
        with mock.patch.object(lien, "recuperer", return_value=rep()):
            self.c.telecharger(SHOP, "v")
        with mock.patch.object(cp, "quota_octets", return_value=10):
            self.c.entretenir({SHOP})
        self.assertTrue(self.c.plein)
        self.assertTrue(self.c.present(SHOP))   # les vignettes ne sont jamais purgées par le plafond

    def test_quota_reglage(self):
        with mock.patch.dict(os.environ, {"PHOTOS_QUOTA_MO": "3"}):
            self.assertEqual(cp.quota_octets(), 3 * 1024 * 1024)
        with mock.patch.dict(os.environ, {"PHOTOS_QUOTA_MO": "beaucoup"}):
            self.assertEqual(cp.quota_octets(), 2048 * 1024 * 1024)


class Remplissage(unittest.TestCase):
    """Passage horaire de photos.py : la vignette manquante vaut essai complet."""

    def setUp(self):
        self.p = photos.Photos(Path(tempfile.mkdtemp()))

    def test_photo_trouvee_sans_vignette_telechargee(self):
        photos._ecrire(self.p.fichier, {SHOP: {"etat": "ok", "essai": time.strftime("%Y-%m-%dT%H:%M:%S")}})
        with mock.patch.object(lien, "recuperer", return_value=rep()) as m:
            r = self.p.actualiser([SHOP], pause=0)
        self.assertEqual(r["essayees"], 1)
        self.assertIn("width=400", m.call_args.args[0])
        self.assertTrue(self.p.cache.present(SHOP))
        with mock.patch.object(lien, "recuperer", return_value=rep()) as m:
            self.p.actualiser([SHOP], pause=0)   # vignette gardée, photo vérifiée récemment : rien
        m.assert_not_called()

    def test_ecartee_ou_refusee_non_retentee_chaque_heure(self):
        maintenant = time.strftime("%Y-%m-%dT%H:%M:%S")
        photos._ecrire(self.p.fichier, {SHOP: {"etat": "morte", "essai": maintenant},
                                        AUTRE: {"etat": "refus", "essai": maintenant}})
        with mock.patch.object(lien, "recuperer", return_value=rep()) as m:
            self.p.actualiser([SHOP, AUTRE], pause=0)
        m.assert_not_called()

    def test_photo_non_gardable_verifiee_sans_cache_jamais_ecartee(self):
        """Trop lourde, format non gardé, disque plein : défaut du cache, la photo reste « ok »."""
        maintenant = time.strftime("%Y-%m-%dT%H:%M:%S")
        cas = [("trop lourde", rep(b"\xff\xd8" + b"x" * cp.ORIGINE_MAX)), ("avif", rep(b"\x00\x00\x00\x1cftypavif" + b"a" * 40, "image/avif"))]
        for nom, r in cas:
            with self.subTest(nom):
                p = photos.Photos(Path(tempfile.mkdtemp()))
                photos._ecrire(p.fichier, {SHOP: {"etat": "ok", "essai": maintenant}})
                petite = lien.Reponse(SHOP, 206, "image/jpeg", JPG[:50], None, {})
                with mock.patch.object(lien, "recuperer", side_effect=lambda u, **k: petite if "Range" in k.get("entetes", {}) else r):
                    for _ in range(4):
                        p.actualiser([SHOP], pause=0)
                self.assertEqual(p.etat()[SHOP]["etat"], "ok")
                self.assertFalse(p.cache.gardable(SHOP))
                with mock.patch.object(lien, "recuperer") as m:
                    p.actualiser([SHOP], pause=0)   # cache non retenté avant 7 jours
                m.assert_not_called()

    def test_page_a_la_place_de_l_image_comptee_absente(self):
        with mock.patch.object(lien, "recuperer", return_value=rep(b"<html></html>", "text/html")):
            self.p.actualiser([SHOP], pause=0)
        self.assertEqual(self.p.etat()[SHOP]["etat"], "doute")

    def test_interdite_hors_du_site_reste_ecartee(self):
        with mock.patch.object(lien, "recuperer",
                               return_value=rep(entetes={"cross-origin-resource-policy": "same-origin"})):
            self.p.actualiser([SHOP], pause=0)
        self.assertEqual(self.p.etat()[SHOP]["etat"], "morte")

    def test_oubliee_perd_ses_fichiers(self):
        vieux = time.strftime("%Y-%m-%d", time.localtime(time.time() - 31 * 86400))
        with mock.patch.object(lien, "recuperer", return_value=rep()):
            self.p.cache.telecharger(SHOP, "v")
        photos._ecrire(self.p.fichier, {SHOP: {"etat": "ok", "essai": time.strftime("%Y-%m-%dT%H:%M:%S"), "vu": vieux}})
        self.p.actualiser([], pause=0)
        self.assertFalse(self.p.cache.present(SHOP))


if __name__ == "__main__":
    unittest.main()

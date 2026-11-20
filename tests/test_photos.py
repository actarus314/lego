"""Tests de la vérification des photos (app/photos.py), sans réseau : `lien.recuperer` est simulé,
ainsi que la connexion pour la lecture bornée de `lien._get`."""
from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from app import index as index_mod, lien, photos
from tests.test_logos import Encodage

PNG = b"\x89PNG\r\n\x1a\n" + b"x" * 20
U = "https://cdn.exemple.fr/a.png"


def reponse(statut=206, type_="image/png", corps=PNG, entetes=None):
    return lien.Reponse(U, statut, type_, corps, None, entetes or {})


def refus(statut):
    e = lien.LienRefuse(f"le site a répondu {statut}")
    e.statut, e.attente = statut, None
    return e


def horodatage(il_y_a_h: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(time.time() - il_y_a_h * 3600))


class Essayer(unittest.TestCase):
    def cas(self, effet):
        with mock.patch.object(lien, "recuperer", side_effect=[effet]) as r:
            resultat, _ = photos.essayer(U)
        return resultat, r

    def test_image_trouvee_debut_seulement_sans_referent(self):
        resultat, r = self.cas(reponse())
        self.assertEqual(resultat, "ok")
        k = r.call_args.kwargs
        self.assertEqual(k["entetes"]["Range"], "bytes=0-4095")
        self.assertEqual((k["statuts"], k["max_octets"]), ((200, 206), 4096))
        self.assertNotIn("Referer", k["entetes"])   # comme la page : aucun référent

    def test_type_image_ou_type_inconnu_sans_signature(self):
        self.assertEqual(self.cas(reponse(type_="image/avif", corps=b"\x00\x00\x00\x1cftypavif"))[0], "ok")
        self.assertEqual(self.cas(reponse(type_="application/octet-stream", corps=b"????"))[0], "ok")

    def test_absente_a_confirmer(self):
        self.assertEqual(self.cas(refus(404))[0], "absente")
        self.assertEqual(self.cas(refus(410))[0], "absente")
        self.assertEqual(self.cas(reponse(200, "text/html", b"<html>Just a moment</html>"))[0], "absente")

    def test_interdite(self):
        self.assertEqual(self.cas(reponse(entetes={"cross-origin-resource-policy": "same-site"}))[0], "interdite")
        self.assertEqual(self.cas(reponse(entetes={"cross-origin-resource-policy": "cross-origin"}))[0], "ok")
        self.assertEqual(photos.essayer("http://cdn.exemple.fr/a.png")[0], "interdite")   # la page n'accepte que https

    def test_refus_limite_passager(self):
        for s in (401, 403):
            self.assertEqual(self.cas(refus(s))[0], "refus")
        self.assertEqual(self.cas(refus(429))[0], "limite")
        self.assertEqual(self.cas(refus(503))[0], "passager")
        self.assertEqual(self.cas(TimeoutError())[0], "passager")


class LectureBornee(unittest.TestCase):
    """lien.recuperer : statuts acceptés, lecture bornée sans dépassement, en-tête CORP lu."""
    faux_http = Encodage.faux_http   # connexion simulée, sans reprendre les tests d'Encodage

    def demarrer(self, *args):
        vu, *patchs = self.faux_http(*args)
        for p in patchs:
            p.start()
            self.addCleanup(p.stop)

    def test_206_lu_borne_et_corp(self):
        corps = PNG + b"y" * (lien.TAILLE_MAX + 10)   # site qui ignore Range : image entière
        self.demarrer(206, corps, {"Content-Type": "image/png", "Cross-Origin-Resource-Policy": "same-site"})
        r = lien.recuperer(U, statuts=(200, 206), max_octets=4096)
        self.assertEqual(r.statut, 206)
        self.assertEqual(r.entetes, {"cross-origin-resource-policy": "same-site"})

    def test_206_refuse_par_defaut(self):
        self.demarrer(206, PNG)
        with self.assertRaises(lien.LienRefuse) as e:
            lien.recuperer(U)
        self.assertEqual(e.exception.statut, 206)

    def test_3xx_sans_location_refuse_sans_boucler(self):
        self.demarrer(302, b"")
        with self.assertRaises(lien.LienRefuse) as e:
            lien.recuperer(U)
        self.assertEqual(e.exception.statut, 302)


class Suivant(unittest.TestCase):
    s = staticmethod(photos.Photos.suivant)

    def test_absence_confirmee_un_jour_plus_tard(self):
        e = self.s({}, "absente", "404", time.time())
        self.assertEqual(e["etat"], "doute")                       # toujours montrée
        e2 = self.s(e, "absente", "404", time.time())
        self.assertEqual(e2["etat"], "doute")                      # même jour : pas confirmée
        e2["premier_constat"] = horodatage(21)
        self.assertEqual(self.s(e2, "absente", "404", time.time())["etat"], "morte")
        self.assertEqual(self.s(e2, "ok", "", time.time())["etat"], "ok")

    def test_interdite_ecartee_aussitot(self):
        self.assertEqual(self.s({"etat": "ok", "essai": horodatage(1)}, "interdite", "corp", time.time())["etat"], "morte")

    def test_passagers_trois_jours(self):
        e = {"etat": "ok", "essai": horodatage(800)}
        for _ in range(photos.PASSAGERS_MAX - 1):
            e = self.s(e, "passager", "délai", time.time())
            self.assertEqual(e["etat"], "ok")   # photo trouvée gardée pendant un incident
        self.assertEqual(self.s(e, "passager", "délai", time.time())["etat"], "morte")

    def test_limite_ne_change_rien(self):
        e = {"etat": "ok", "essai": horodatage(800)}
        self.assertEqual(self.s(e, "limite", "429", time.time()), e)

    def test_delais(self):
        now, a = time.time(), photos.Photos.a_essayer
        self.assertFalse(a({"etat": "ok", "essai": horodatage(29 * 24)}, now))
        self.assertTrue(a({"etat": "ok", "essai": horodatage(30 * 24)}, now))
        self.assertFalse(a({"etat": "morte", "essai": horodatage(6 * 24)}, now))
        self.assertTrue(a({"etat": "morte", "essai": horodatage(7 * 24)}, now))
        self.assertTrue(a({"etat": "doute", "essai": horodatage(20)}, now))
        self.assertFalse(a({"etat": "ok", "essai": horodatage(800), "passager_le": horodatage(2)}, now))
        self.assertTrue(a({"etat": "ok", "essai": horodatage(800), "passager_le": horodatage(21)}, now))


class Actualiser(unittest.TestCase):
    def setUp(self):
        self.p = photos.Photos(Path(tempfile.mkdtemp()))

    def passe(self, resultats: dict, urls, **k):
        with mock.patch.object(photos, "essayer", side_effect=lambda u: resultats[u]) as m:
            r = self.p.actualiser(urls, pause=0, **k)
        return r, m

    def test_panne_de_quelques_heures_n_ecarte_rien(self):
        u = "https://a/1.jpg"
        for _ in range(5):   # passages horaires : un seul jour d'échec compté
            self.passe({u: ("passager", "503")}, [u])
        self.assertEqual(self.p.ecartees(), set())
        self.assertEqual(self.p.etat()[u]["passagers"], 1)

    def test_site_laisse_apres_trois_echecs_ou_429(self):
        a = [f"https://a/{i}.jpg" for i in range(6)]
        b = ["https://b/1.jpg", "https://b/2.jpg"]
        res = {u: ("refus", "403") for u in a} | {b[0]: ("limite", "429"), b[1]: ("ok", "")}
        _, m = self.passe(res, a + b)
        self.assertEqual([c.args[0] for c in m.call_args_list], a[:3] + b[:1])

    def test_duree_maximale(self):
        _, m = self.passe({"https://a/1.jpg": ("ok", "")}, ["https://a/1.jpg"], duree_max=-1)
        self.assertEqual(m.call_count, 0)

    def test_oubli_apres_30_jours_hors_catalogue_seulement(self):
        vieux = time.strftime("%Y-%m-%d", time.localtime(time.time() - 31 * 86400))
        photos._ecrire(self.p.fichier, {"https://a/1.jpg": {"etat": "morte", "essai": horodatage(1), "vu": vieux},
                                        "https://a/2.jpg": {"etat": "morte", "essai": horodatage(1), "vu": vieux}})
        self.passe({}, ["https://a/2.jpg"])   # liste partielle : seule l'adresse absente depuis 30 jours part
        self.assertEqual(set(self.p.etat()), {"https://a/2.jpg"})
        self.passe({}, [])
        self.assertEqual(self.p.ecartees(), {"https://a/2.jpg"})   # vue aujourd'hui : gardée

    def test_pas_d_ecriture_sans_changement(self):
        self.passe({"https://a/1.jpg": ("ok", "")}, ["https://a/1.jpg"])
        avant = self.p.fichier.stat().st_mtime_ns
        time.sleep(0.01)
        self.passe({}, ["https://a/1.jpg"])
        self.assertEqual(self.p.fichier.stat().st_mtime_ns, avant)

    def test_resume(self):
        urls = ["https://a/1.jpg", "https://b/2.jpg", "https://c/3.jpg"]
        self.passe(dict(zip(urls, [("ok", ""), ("interdite", "corp"), ("refus", "403")])), urls)
        self.assertEqual(self.p.resume(), {"total": 3, "trouvees": 1, "ecartees": 1, "non_verifiables": 1})


class Appliquer(unittest.TestCase):
    def test_photo_suivante_du_set(self):
        sets = [{"img": "https://rb/10318-1.jpg", "images": ["https://rb/10318-1.jpg", "https://bv/10318.png", "https://bv/alt1.png"]},
                {"img": "https://rb/x.jpg"}, {"img": "https://ok/y.jpg"}]
        principales, _ = photos.adresses(sets)
        self.assertEqual(principales[0], "https://rb/10318-1.jpg")
        photos.appliquer(sets, {"https://rb/10318-1.jpg", "https://rb/x.jpg"})
        self.assertEqual(sets[0], {"img": "https://bv/10318.png", "images": ["https://bv/10318.png", "https://bv/alt1.png"]})
        self.assertIsNone(sets[1]["img"])
        self.assertEqual(sets[2], {"img": "https://ok/y.jpg"})

    def test_index_adresses_avant_retrait_et_cache_invalide(self):
        idx = index_mod.Index(Path(tempfile.mkdtemp()))
        idx.enregistrer("kbs", [{"cle": "kbs:a", "source": "kbs", "boutique": "KBS", "pays": "Allemagne",
                                 "url": "https://k/a", "nom": "Avion", "marque": "Mould King", "numero": "10001",
                                 "prix": 100.0, "devise": "EUR", "dispo": "vente", "pieces": 1000,
                                 "img": "https://k/mort.jpg", "images": ["https://k/vivant.jpg"]}])
        trouver = lambda: next(x for x in idx.sets(["kbs"]) if x["numero"] == "10001")
        self.assertEqual(trouver()["img"], "https://k/mort.jpg")
        photos._ecrire(idx.photos.fichier, {"https://k/mort.jpg": {"etat": "morte", "essai": horodatage(1)}})
        self.assertEqual(trouver()["img"], "https://k/vivant.jpg")
        self.assertIn("https://k/mort.jpg", idx.photos_brutes[0])   # toujours vérifiée : pas d'oubli


if __name__ == "__main__":
    unittest.main()

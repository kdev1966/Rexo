"""Tests rapides d'Identité (sans Apple Vision : géométrie, couleurs, fond, planches).

Lancement (depuis apps/identite) : .venv/bin/python -m unittest discover tests
"""

import math
import unittest

import numpy as np

from identite import cadrage, couleurs, fond, planche
from identite.normes import DPI, ECART, FRANCE, MM_PAR_POUCE, PLANCHE, PORTRAIT, px
from identite.visage import Visage

PPMM = DPI / MM_PAR_POUCE


def visage_synthetique(angle=0.0, centre=(500.0, 400.0), oeil_menton=200.0, demi_largeur=150.0):
    """Visage dont les pupilles sont inclinées de `angle` degrés autour de `centre`."""
    t = math.radians(angle)
    rot = np.array([[math.cos(t), -math.sin(t)], [math.sin(t), math.cos(t)]])   # repère redressé -> image
    c = np.array(centre)
    pup = np.array([[-60.0, 0.0], [60.0, 0.0]]) @ rot.T + c
    ang = np.linspace(0, math.pi, 17)
    contour = np.stack([-demi_largeur * np.cos(ang), oeil_menton * np.sin(ang) - 20], axis=1) @ rot.T + c
    oeil = np.array([[-20.0, 0.0], [0.0, -6.0], [20.0, 0.0], [0.0, 6.0]])
    yeux = [oeil + p for p in (np.array([-60.0, 0.0]) @ rot.T + c, np.array([60.0, 0.0]) @ rot.T + c)]
    return Visage(cadre=(0, 0, 1, 1), pupilles=pup, contour=contour, yeux=yeux)


class Geometrie(unittest.TestCase):
    def test_millimetres(self):
        self.assertEqual(px(35), 413)
        self.assertEqual(px(45), 531)

    def test_redressement(self):
        v = visage_synthetique(angle=8.0)
        self.assertAlmostEqual(cadrage.angle_yeux(v.pupilles), 8.0, places=6)

    def test_tete_a_la_norme(self):
        """Le menton, le crâne et le milieu du visage tombent aux positions de la norme."""
        v = visage_synthetique(angle=6.0)
        masque = np.zeros((1000, 1000), np.float32)
        tete = cadrage.mesurer(v, masque)
        self.assertAlmostEqual(tete.menton, 180.0, delta=0.5)
        m, infos = cadrage.placer(tete, FRANCE)
        pt = lambda p: m[:, :2] @ np.asarray(p) + m[:, 2]  # noqa: E731
        c = v.pupilles.mean(axis=0)
        r = cadrage.rotation(tete.angle).T                  # repère redressé -> image
        menton = pt(c + r @ np.array([tete.x, tete.menton]))
        crane = pt(c + r @ np.array([tete.x, tete.crane]))
        self.assertAlmostEqual(menton[1] - crane[1], FRANCE.tete * PPMM, delta=0.5)
        self.assertAlmostEqual(crane[1], FRANCE.marge_haut * PPMM, delta=0.5)
        self.assertAlmostEqual(crane[0], FRANCE.largeur / 2 * PPMM, delta=0.5)
        self.assertAlmostEqual(abs(menton[0] - crane[0]), 0, delta=0.5)   # tête droite
        p0, p1 = pt(v.pupilles[0]), pt(v.pupilles[1])
        self.assertAlmostEqual(p0[1], p1[1], delta=0.01)                   # yeux à l'horizontale
        self.assertTrue(FRANCE.tete_min <= infos['tete_mm'] <= FRANCE.tete_max)

    def test_crane_sous_le_masque(self):
        """Crâne rasé : le haut du masque, plus bas que l'estimation, devient le sommet."""
        v = visage_synthetique()
        masque = np.zeros((1000, 1000), np.float32)
        masque[300:, 350:650] = 1.0               # la tête commence 100 px au-dessus des yeux
        tete = cadrage.mesurer(v, masque)
        self.assertAlmostEqual(tete.cheveux, -100.0, delta=2)
        self.assertAlmostEqual(tete.crane, -100.0, delta=2)

    def test_cheveux_hauts_descendent_la_tete(self):
        v = visage_synthetique()
        masque = np.zeros((1000, 1000), np.float32)
        masque[20:, 350:650] = 1.0                # cheveux très hauts
        tete = cadrage.mesurer(v, masque)
        _, infos = cadrage.placer(tete, FRANCE)
        self.assertGreater(infos['crane_mm'], FRANCE.marge_haut)
        self.assertLessEqual(infos['menton_mm'], FRANCE.hauteur - FRANCE.marge_bas_min + 0.05)

    def test_ouverture_des_yeux(self):
        v = visage_synthetique()
        self.assertAlmostEqual(cadrage.ouverture(v.yeux[0], 0.0), 0.3, places=6)

    def test_rendu_et_couverture(self):
        v = visage_synthetique()
        img = np.full((1000, 1000, 3), 128, np.uint8)
        tete = cadrage.mesurer(v, np.zeros((1000, 1000), np.float32))
        m, _ = cadrage.placer(tete, FRANCE)
        out, couv = cadrage.rendre(img, m, (FRANCE.largeur, FRANCE.hauteur), FRANCE.fond)
        self.assertEqual(out.shape, (px(45), px(35), 3))
        self.assertGreater(couv['bas'], 0.98)


class Couleurs(unittest.TestCase):
    def scene(self, fond_bgr):
        img = np.zeros((200, 200, 3), np.uint8)
        img[:] = fond_bgr
        masque = np.zeros((200, 200), np.float32)
        masque[60:, 70:130] = 1.0
        img[60:, 70:130] = (90, 120, 170)
        return img, masque

    def test_dominante_corrigee(self):
        img, masque = self.scene((200, 192, 185))          # fond gris, lumière froide (BGR)
        gains, raison = couleurs.gains_fond(img, masque)
        self.assertIsNotNone(gains, raison)
        b, v, r = couleurs.appliquer_gains(img, gains)[5, 5].astype(int)
        self.assertLess(r, b)                                # même sens, sans inversion
        self.assertLessEqual(b - r, (200 - 185) / 2)         # dominante au moins divisée par deux

    def test_fond_colore_refuse(self):
        img, masque = self.scene((230, 120, 40))            # fond bleu franc
        gains, raison = couleurs.gains_fond(img, masque)
        self.assertIsNone(gains)
        self.assertIn('coloré', raison)

    def test_fond_trop_petit(self):
        img, masque = self.scene((200, 200, 200))
        masque[:] = 1.0
        gains, raison = couleurs.gains_fond(img, masque)
        self.assertIsNone(gains)

    def test_conversions_lineaires(self):
        x = np.arange(256, dtype=np.uint8).reshape(1, -1, 1).repeat(3, axis=2)
        np.testing.assert_array_equal(couleurs.srgb8(couleurs.lineaire(x)), x)


class Fond(unittest.TestCase):
    def test_remplacement(self):
        img = np.zeros((100, 100, 3), np.uint8)
        img[:] = (0, 0, 255)                                 # ancien fond rouge
        img[30:70, 30:70] = (40, 160, 90)
        masque = np.zeros((100, 100), np.float32)
        masque[30:70, 30:70] = 1.0
        out = fond.remplacer(img, masque, (214, 214, 214))
        np.testing.assert_array_equal(out[2, 2], (214, 214, 214))
        np.testing.assert_array_equal(out[50, 50], (40, 160, 90))


class Planches(unittest.TestCase):
    taille = (FRANCE.largeur, FRANCE.hauteur)

    def dans_la_planche_sans_chevauchement(self, cadres):
        for x, y, w, h in cadres:
            self.assertGreaterEqual(x, 0)
            self.assertGreaterEqual(y, 0)
            self.assertLessEqual(x + w, PLANCHE[0])
            self.assertLessEqual(y + h, PLANCHE[1])
        for i, a in enumerate(cadres):
            for b in cadres[i + 1:]:
                separes = (a[0] + a[2] <= b[0] - ECART + 1e-9 or b[0] + b[2] <= a[0] - ECART + 1e-9 or
                           a[1] + a[3] <= b[1] - ECART + 1e-9 or b[1] + b[3] <= a[1] - ECART + 1e-9)
                self.assertTrue(separes, (a, b))

    def test_planche_8(self):
        cadres = planche.disposition_8(self.taille)
        self.assertEqual(len(cadres), 8)
        self.dans_la_planche_sans_chevauchement(cadres)

    def test_planche_4_portrait(self):
        photos, portrait = planche.disposition_4_portrait(self.taille)
        self.assertEqual(len(photos), 4)
        self.assertEqual(portrait[2:], PORTRAIT)
        self.dans_la_planche_sans_chevauchement(photos + [portrait])

    def test_traits_de_coupe(self):
        cadres = planche.disposition_8(self.taille)
        photo = np.full((px(45), px(35), 3), 200, np.uint8)
        out = planche.composer(cadres, [photo] * 8)
        self.assertEqual(out.shape[:2], (px(PLANCHE[1]), px(PLANCHE[0])))
        x0 = px(cadres[0][0])
        self.assertTrue((out[2, x0] < 255).all())            # trait dans la marge du haut
        self.assertTrue((out[2, x0 + 20] == 255).all())      # papier blanc à côté
        y, x = px(cadres[0][1]) + 50, x0 + 50
        np.testing.assert_array_equal(out[y, x], (200, 200, 200))   # la photo recouvre le trait


if __name__ == '__main__':
    unittest.main()


class Interface(unittest.TestCase):
    """API de l'interface web, sur un dossier de données temporaire (sans Apple Vision)."""

    @classmethod
    def setUpClass(cls):
        import io
        import tempfile
        from unittest import mock

        from identite import interface
        cls.io = io
        cls.tmp = tempfile.TemporaryDirectory()
        from pathlib import Path
        base = Path(cls.tmp.name)
        cls.original, cls.resultats = base / 'original', base / 'resultats'
        cls.original.mkdir()
        cls.resultats.mkdir()
        cls.patches = [mock.patch.object(interface, 'ORIGINAL', cls.original),
                       mock.patch.object(interface, 'RESULTATS', cls.resultats)]
        for p in cls.patches:
            p.start()
        cls.client = interface.app.test_client()

    @classmethod
    def tearDownClass(cls):
        for p in cls.patches:
            p.stop()
        cls.tmp.cleanup()

    def envoyer(self, nom):
        data = {'photo': (self.io.BytesIO(b'\xff\xd8\xff'), nom)}
        return self.client.post('/api/photos', data=data, content_type='multipart/form-data')

    def test_envoi_sans_ecraser(self):
        self.assertEqual(self.envoyer('portrait.jpg').get_json()['name'], 'portrait.jpg')
        # même nom de base, autre extension : renommé, pour que les résultats ne se mélangent pas
        self.assertEqual(self.envoyer('portrait.png').get_json()['name'], 'portrait_2.png')
        self.assertEqual(self.envoyer('virus.exe').status_code, 400)

    def test_chemins_hors_du_dossier(self):
        self.assertEqual(self.client.get('/media/original/..%2F..%2Fsecret.txt').status_code, 404)
        self.assertEqual(self.client.get('/media/autre/x.jpg').status_code, 404)
        self.assertEqual(self.client.get('/api/resultat?photo=../x.jpg').status_code, 404)

    def test_reglages_invalides(self):
        self.envoyer('reglages.jpg')
        for corps in ({'photo': 'reglages.jpg', 'couleurs': 'magie'},
                      {'photo': 'reglages.jpg', 'fond': [300, 0, 0]},
                      {'photo': 'reglages.jpg', 'fond': '214,214,214'}):
            self.assertEqual(self.client.post('/api/fabriquer', json=corps).status_code, 400, corps)
        self.assertEqual(self.client.post('/api/fabriquer', json={'photo': 'absente.jpg'}).status_code, 404)

    def test_pas_de_resultat(self):
        self.envoyer('neuf.jpg')
        self.assertIsNone(self.client.get('/api/resultat?photo=neuf.jpg').get_json())

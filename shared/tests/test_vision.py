"""Tests des mesures communes de shared/vision (sans modèle d'IA).

Lancement, depuis la racine du hub : apps/reveal/.venv/bin/python -m unittest discover -s shared/tests -t .
"""

import unittest

import cv2
import numpy as np

from shared import vision
from shared.vision import qualite


def image_nette(graine=0, l=1200, h=900):
    """Image texturée (bords nets partout), reproductible."""
    rng = np.random.default_rng(graine)
    petite = rng.integers(0, 255, (h // 20, l // 20, 3), dtype=np.uint8)
    return cv2.resize(petite, (l, h), interpolation=cv2.INTER_NEAREST)


class Mesures(unittest.TestCase):
    """Netteté, empreinte (shared/vision/qualite) et ouverture des yeux (shared/vision)."""

    def test_flou_moins_net(self):
        img = image_nette()
        self.assertGreater(qualite.nettete(img), 10 * qualite.nettete(cv2.GaussianBlur(img, (0, 0), 4)))

    def test_fond_flou_sujet_net(self):
        """Un sujet net sur un fond flou n'est pas une photo floue : la zone la plus nette compte."""
        img = cv2.GaussianBlur(image_nette(), (0, 0), 6)
        img[300:600, 450:750] = image_nette(1)[300:600, 450:750]
        self.assertGreater(qualite.nettete(img), 200)      # bien au-dessus d'une photo floue (mesuré : 2 à 160)

    def test_empreinte(self):
        a = image_nette(0)
        self.assertEqual(qualite.distance(qualite.empreinte(a), qualite.empreinte(cv2.GaussianBlur(a, (0, 0), 1))), 0)
        self.assertGreater(qualite.distance(qualite.empreinte(a), qualite.empreinte(image_nette(5))), 16)

    def test_ouverture_des_yeux(self):
        # œil ouvert : ellipse de 40 × 14 ; fermé : 40 × 3 ; incliné de 20° (redressé par ses coins)
        def oeil(h, angle):
            t = np.linspace(0, 2 * np.pi, 16, endpoint=False)
            t = np.roll(t, -8)                         # point 8 : coin opposé au point 0
            p = np.stack([20 * np.cos(t), h / 2 * np.sin(t)], 1)
            a = np.radians(angle)
            r = np.array([[np.cos(a), -np.sin(a)], [np.sin(a), np.cos(a)]])
            return np.column_stack([p @ r.T + 300, np.zeros(16)])
        self.assertAlmostEqual(vision.ouverture_oeil(oeil(14, 20)), 0.35, places=2)
        self.assertLess(vision.ouverture_oeil(oeil(3, 20)), 0.15)              # seuil de Rexo ID et Rexo Dock
        # avec l'angle de la ligne des yeux donné (Rexo ID), même résultat
        self.assertAlmostEqual(vision.ouverture_oeil(oeil(14, 20), 20.0), 0.35, places=2)



def degrade(h=300, w=400):
    g = np.tile(np.linspace(30, 220, w, dtype=np.float32), (h, 1))
    return cv2.cvtColor(g.astype(np.uint8), cv2.COLOR_GRAY2BGR)


class NoirEtBlanc(unittest.TestCase):
    """Un seul critère « noir et blanc » pour tout le hub (shared/vision/qualite)."""

    def test_gris_et_sepia(self):
        self.assertTrue(qualite.est_monochrome(degrade()))
        for teinte in ([0.82, 0.95, 1.08], [0.75, 0.9, 1.0]):            # sépia léger, sépia fort
            sepia = np.clip(degrade().astype(np.float32) * np.array(teinte, np.float32), 0, 255).astype(np.uint8)
            self.assertTrue(qualite.est_monochrome(sepia), teinte)

    def test_couleurs_franches_meme_alignees(self):
        img = degrade()
        img[:, :200] = (40, 60, 200)
        img[:, 200:] = (200, 160, 40)                                  # deux couleurs alignées sur un axe
        self.assertFalse(qualite.est_monochrome(img))

    def test_couleurs_variees(self):
        img = np.random.default_rng(0).integers(0, 255, (120, 90, 3), dtype=np.uint8)
        self.assertFalse(qualite.est_monochrome(img))


if __name__ == '__main__':
    unittest.main()

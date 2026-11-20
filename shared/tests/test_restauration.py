"""Tests des outils de restauration communs (shared/ia/restauration.py).

Lancement, depuis la racine du hub : apps/reveal/.venv/bin/python -m unittest discover -s shared/tests -t .
Les tests qui demandent un modèle sont sautés s'il n'est pas installé.
"""

import unittest

import cv2
import numpy as np


class Rayures(unittest.TestCase):
    """Détecteur de rayures et reconstitution par LaMa."""

    def setUp(self):
        from shared.ia import restauration
        self.r = restauration

    def test_rayure_effacee(self):
        if not self.r.disponible():
            self.skipTest('modèles rayures-anciennes et lama-512 absents')
        g = np.tile(np.linspace(60, 180, 400, dtype=np.float32), (300, 1))
        img = cv2.cvtColor(g.astype(np.uint8), cv2.COLOR_GRAY2BGR)
        abime = img.copy()
        cv2.line(abime, (20, 40), (380, 260), (250, 250, 250), 3)
        # le détecteur répond par un masque 0/1 à la taille de l'image (une ligne synthétique
        # parfaitement nette ne ressemble pas aux rayures réelles : sa détection n'est pas testée)
        m = self.r.rayures(abime)
        self.assertEqual(m.shape, abime.shape[:2])
        self.assertTrue(set(np.unique(m)) <= {0, 1})
        trace = np.zeros(abime.shape[:2], np.uint8)
        cv2.line(trace, (20, 40), (380, 260), 1, 7)
        out = self.r.reconstituer(abime, trace)
        ecart = np.abs(out.astype(int) - img).max(axis=2)
        self.assertLess(ecart[trace > 0].mean(), 20)               # la ligne blanche a disparu
        self.assertEqual(ecart[trace == 0].max(), 0)               # le reste n'est pas touché


class Grain(unittest.TestCase):
    """Grain du film : estimation (sans modèle) ; débruitage SCUNet si le modèle est installé."""

    def setUp(self):
        from shared import ia
        from shared.ia import restauration
        self.r, self.ia = restauration, ia
        g = np.tile(np.linspace(60, 190, 600, dtype=np.float32), (500, 1))
        cv2.circle(g, (300, 250), 120, 220, -1)                     # un sujet aux bords nets
        self.propre = cv2.cvtColor(g.astype(np.uint8), cv2.COLOR_GRAY2BGR)

    def bruit(self, sigma):
        n = np.random.default_rng(1).normal(0, sigma, self.propre.shape[:2])[..., None]
        return np.clip(self.propre + n, 0, 255).astype(np.uint8)

    def test_estimation(self):
        self.assertLess(self.r.grain(self.propre), 0.3)              # les bords du sujet ne comptent pas
        for sigma in (2, 5, 10):
            self.assertAlmostEqual(self.r.grain(self.bruit(sigma)), sigma, delta=sigma * 0.25)

    def test_seuil(self):
        self.assertLess(self.r.grain(self.propre), self.r.SEUIL_GRAIN)
        self.assertGreater(self.r.grain(self.bruit(3)), self.r.SEUIL_GRAIN)

    def test_debruitage_sans_raccord(self):
        if not self.ia.present('scunet-512'):
            self.skipTest('modèle scunet-512 absent')
        abime = self.bruit(8)                                       # 600 × 500 : 2 tuiles qui se chevauchent
        out = self.r.debruiter(abime)
        self.assertEqual(out.shape, abime.shape)
        self.assertLess(self.r.grain(out), self.r.grain(abime) / 2)
        ecart = np.abs(out.astype(int) - self.propre).mean(axis=2)
        self.assertLess(ecart.mean(), np.abs(abime.astype(int) - self.propre).mean() / 2)
        # pas de raccord entre les tuiles : la colonne de jonction ressemble à ses voisines
        col = np.abs(np.diff(out.astype(int), axis=1)).mean(axis=(0, 2))
        self.assertLess(col[440:520].max(), col.mean() * 4)


if __name__ == '__main__':
    unittest.main()

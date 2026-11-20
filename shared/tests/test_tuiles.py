"""Tests du traitement par tuiles commun (shared/ia/tuiles.py), sans modèle.

Lancement, depuis la racine du hub : apps/reveal/.venv/bin/python -m unittest discover -s shared/tests -t .
"""

import unittest

import cv2
import numpy as np

from shared.ia import tuiles


def image(h, w, graine=0):
    return np.random.default_rng(graine).integers(0, 255, (h, w, 3), dtype=np.uint8)


class Tuiles(unittest.TestCase):
    def test_positions(self):
        self.assertEqual(tuiles.positions(400, 512, 64), [0])
        p = tuiles.positions(1300, 512, 64)
        self.assertEqual((p[0], p[-1]), (0, 1300 - 512))
        self.assertTrue(all(b - a <= 512 - 64 for a, b in zip(p, p[1:])))   # recouvrement assuré

    def test_identite_sans_raccord(self):
        """Une fonction qui rend sa tuile telle quelle redonne l'image exacte, dans les deux
        modes, y compris une image plus petite qu'une tuile et des côtés impairs."""
        for h, w in ((300, 200), (777, 1301), (513, 512)):
            img = image(h, w)
            for fixe in (True, False):
                out = tuiles.par_tuiles(img, lambda t: t.astype(np.float32), 256, 32, taille_fixe=fixe)
                self.assertEqual(out.shape, (h, w, 3))
                self.assertLess(np.abs(out - img).max(), 1e-3, (h, w, fixe))

    def test_echelle_et_multiple(self):
        """Échelle 2 et côtés pairs exigés (Real-ESRGAN) : chaque tuile reçue est paire, et
        l'assemblage d'un agrandissement au plus proche voisin redonne l'image agrandie."""
        img = image(301, 457, 3)
        vues = []

        def double(t):
            vues.append(t.shape[:2])
            return cv2.resize(t, None, fx=2, fy=2, interpolation=cv2.INTER_NEAREST).astype(np.float32)

        out = tuiles.par_tuiles(img, double, 192, 32, echelle=2, taille_fixe=False, multiple=2)
        self.assertTrue(all(h % 2 == 0 and w % 2 == 0 for h, w in vues))
        attendu = cv2.resize(img, None, fx=2, fy=2, interpolation=cv2.INTER_NEAREST)
        self.assertEqual(out.shape, attendu.shape)
        self.assertLess(np.abs(out - attendu).max(), 1e-3)

    def test_bord_sans_double_calcul(self):
        """Tuiles de bord réduites : pas plus de pixels calculés que nécessaire (au plus un
        recouvrement par tuile)."""
        surfaces = []
        tuiles.par_tuiles(image(700, 525), lambda t: surfaces.append(t.shape[0] * t.shape[1]) or t.astype(np.float32),
                          192, 32, taille_fixe=False)
        self.assertLess(sum(surfaces), 700 * 525 * (192 / 160) ** 2)


if __name__ == '__main__':
    unittest.main()

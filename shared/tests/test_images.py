"""Tests des JPEG en cache communs (shared/images : ecrire_jpeg, vignette, apercu).

Lancement, depuis la racine du hub : apps/reveal/.venv/bin/python -m unittest discover -s shared/tests -t .
"""

import os
import tempfile
import time
import unittest
from pathlib import Path

import cv2
import numpy as np

from shared import images


class JpegEnCache(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.photo = self.tmp / 'photo.png'
        cv2.imwrite(str(self.photo), np.full((900, 1200, 3), 120, np.uint8))

    def tearDown(self):
        self._tmp.cleanup()

    def test_vignette_reduite_et_refaite_si_la_photo_change(self):
        cache = self.tmp / 'cache'
        v = images.vignette(self.photo, cache, 300)
        self.assertEqual(max(cv2.imread(str(v)).shape[:2]), 300)
        self.assertEqual(images.vignette(self.photo, cache, 300), v)                 # depuis le cache
        self.assertNotEqual(images.chemin_vignette(self.photo, cache, 600), v)      # autre taille
        cv2.imwrite(str(self.photo), np.full((900, 1200, 3), 30, np.uint8))
        os.utime(self.photo, (time.time() + 5, time.time() + 5))
        self.assertNotEqual(images.vignette(self.photo, cache, 300), v)             # photo modifiée
        self.assertFalse(list(cache.rglob('*.partiel.jpg')))                         # rien à moitié écrit

    def test_apercu(self):
        a = images.apercu(self.photo, self.tmp / 'apercus')
        self.assertEqual(a.name, 'photo.png.jpg')
        self.assertEqual(cv2.imread(str(a)).shape[:2], (900, 1200))


if __name__ == '__main__':
    unittest.main()

"""Tests rapides de Reveal (sans PhotoCraft ni modèles IA).

Lancement (depuis apps/reveal) : .venv/bin/python -m unittest discover tests
"""

import os
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

from reveal import analyse
from shared import modeles


def gradient(h=300, w=400):
    """Image grise douce, sans détail ni strie."""
    g = np.tile(np.linspace(60, 200, w, dtype=np.float32), (h, 1))
    g += np.linspace(-20, 20, h, dtype=np.float32)[:, None]
    return cv2.cvtColor(np.clip(g, 0, 255).astype(np.uint8), cv2.COLOR_GRAY2BGR)


def with_streaks(img, n=10, thickness=2, delta=40):
    out = img.astype(np.int16)
    h, w = img.shape[:2]
    for i in range(n):
        y = 40 + i * (h - 80) // n
        out[y:y + thickness, w // 10:w - w // 10] += delta
    return np.clip(out, 0, 255).astype(np.uint8)


class Monochrome(unittest.TestCase):
    def test_gray_photo_is_monochrome(self):
        self.assertTrue(analyse.is_monochrome(gradient()))

    def test_sepia_photo_is_monochrome(self):
        sepia = gradient().astype(np.float32) * np.array([0.82, 0.95, 1.08], np.float32)
        self.assertTrue(analyse.is_monochrome(np.clip(sepia, 0, 255).astype(np.uint8)))

    def test_colour_photo_is_not_monochrome(self):
        img = gradient()
        img[:, :200] = (40, 60, 200)
        img[:, 200:] = (200, 160, 40)
        self.assertFalse(analyse.is_monochrome(img))


class Streaks(unittest.TestCase):
    def test_clean_image_has_no_streak_series(self):
        self.assertLess(analyse.streak_lines(gradient()), 6)

    def test_streaked_image_is_detected(self):
        self.assertGreaterEqual(analyse.streak_lines(with_streaks(gradient())), 6)

    def test_scratch_mask_is_empty_without_series(self):
        self.assertEqual(analyse.scratch_mask(gradient()).max(), 0)

    def test_destreak_reduces_streaks(self):
        clean = gradient()
        streaked = with_streaks(clean)
        fixed, changed = analyse.destreak(streaked)
        before = np.abs(streaked.astype(int) - clean.astype(int)).mean()
        after = np.abs(fixed.astype(int) - clean.astype(int)).mean()
        self.assertGreater(changed, 0)
        self.assertLess(after, before * 0.6)


class Catalogue(unittest.TestCase):
    def test_reveal_models_are_declared(self):
        noms = {m['nom'] for m in modeles.selection('reveal')}
        self.assertTrue({'ddcolor', 'gfpgan_1.4', 'real_esrgan_x2'} <= noms)
        for m in modeles.selection('reveal'):
            self.assertEqual(len(m['sha256']), 64)
            self.assertTrue(m['url'].startswith('https://'))

    def test_models_folder_can_be_overridden(self):
        old = os.environ.get('KDEV_MODELS_DIR')
        os.environ['KDEV_MODELS_DIR'] = '/tmp/ailleurs'
        try:
            self.assertEqual(modeles.chemin('ddcolor'), Path('/tmp/ailleurs/reveal/ddcolor.onnx'))
            self.assertFalse(modeles.present('ddcolor'))
        finally:
            if old is None:
                del os.environ['KDEV_MODELS_DIR']
            else:
                os.environ['KDEV_MODELS_DIR'] = old


class Interface(unittest.TestCase):
    """L'interface ne doit servir que les fichiers de original/ et retouche/."""

    def setUp(self):
        from reveal import interface
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.orig, self.ret = root / 'original', root / 'retouche'
        self.orig.mkdir()
        self.ret.mkdir()
        cv2.imwrite(str(self.orig / 'a.jpg'), gradient())
        (root / 'secret.txt').write_text('privé')
        self._saved = (interface.ORIGINAL, interface.RETOUCHE)
        interface.ORIGINAL, interface.RETOUCHE = self.orig, self.ret
        self.interface = interface
        self.client = interface.app.test_client()

    def tearDown(self):
        self.interface.ORIGINAL, self.interface.RETOUCHE = self._saved
        self.tmp.cleanup()

    def test_lists_photos(self):
        r = self.client.get('/api/photos')
        self.assertEqual([p['name'] for p in r.get_json()], ['a.jpg'])

    def test_refuses_to_leave_the_folder(self):
        self.assertEqual(self.client.get('/media/original/..%2Fsecret.txt').status_code, 404)
        self.assertEqual(self.client.get('/media/autre/a.jpg').status_code, 404)

    def test_upload_never_overwrites(self):
        with open(self.orig / 'a.jpg', 'rb') as f:
            data = f.read()
        import io
        r = self.client.post('/api/photos', data={'photo': (io.BytesIO(data), 'a.jpg')},
                             content_type='multipart/form-data')
        self.assertEqual(r.get_json()['name'], 'a_2.jpg')
        self.assertTrue((self.orig / 'a.jpg').exists())

    def test_rejects_unknown_format(self):
        import io
        r = self.client.post('/api/photos', data={'photo': (io.BytesIO(b'x'), 'a.exe')},
                             content_type='multipart/form-data')
        self.assertEqual(r.status_code, 400)


if __name__ == '__main__':
    unittest.main()

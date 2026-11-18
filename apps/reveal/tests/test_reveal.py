"""Tests rapides de Reveal (sans PhotoCraft ni modèles IA).

Lancement (depuis apps/reveal) : .venv/bin/python -m unittest discover tests
"""

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

from reveal import analyse


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


class Formats(unittest.TestCase):
    """Formats qu'OpenCV ne lit pas : convertis en PNG par Pillow, PhotoCraft ou sips."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.ref = gradient()

    def tearDown(self):
        self.tmp.cleanup()

    def _pillow_save(self, name, fmt, **kw):
        from PIL import Image
        path = self.dir / name
        Image.fromarray(cv2.cvtColor(self.ref, cv2.COLOR_BGR2RGB)).save(path, fmt, **kw)
        return path

    def test_avif_is_converted(self):
        src = self._pillow_save('a.avif', 'AVIF', quality=90)
        self.assertIsNone(cv2.imread(str(src)))                 # OpenCV ne sait pas le lire
        img, outil = analyse.load_any(src, self.dir / 'travail')
        self.assertEqual(outil, 'Pillow')
        self.assertEqual(img.shape, self.ref.shape)
        self.assertLess(np.abs(img.astype(int) - self.ref.astype(int)).mean(), 6)

    def test_transparent_gif_goes_on_white(self):
        from PIL import Image
        # palette : index 0 = noir (déclaré transparent), index 1 = rouge
        im = Image.new('P', (40, 30), 0)
        im.putpalette([0, 0, 0, 255, 0, 0] + [0] * 762)
        im.paste(1, (0, 0, 20, 30))
        src = self.dir / 't.gif'
        im.save(src, transparency=0)
        img, outil = analyse.load_any(src, self.dir / 'travail')
        self.assertIsNotNone(outil)
        self.assertGreater(img[15, 35].min(), 200)              # partie transparente -> blanc

    @unittest.skipUnless(Path('/usr/bin/sips').exists(), 'sips absent')
    def test_heic_is_converted(self):
        jpg = self.dir / 'a.jpg'
        cv2.imwrite(str(jpg), self.ref)
        heic = self.dir / 'a.heic'
        subprocess.run(['sips', '-s', 'format', 'heic', str(jpg), '--out', str(heic)], capture_output=True)
        if not heic.exists():
            self.skipTest('sips ne sait pas écrire le HEIC ici')
        img, outil = analyse.load_any(heic, self.dir / 'travail')
        self.assertIn(outil, ('PhotoCraft', 'sips'))
        self.assertEqual(img.shape, self.ref.shape)

    def test_corrupted_file_is_refused(self):
        from shared.images import ConversionImpossible
        bad = self.dir / 'abime.avif'
        bad.write_bytes(b'ceci n est pas une image')
        with self.assertRaises(ConversionImpossible):
            analyse.load_any(bad, self.dir / 'travail')

    def test_all_accepted_formats_are_lowercase_extensions(self):
        from shared.images import FORMATS
        self.assertTrue(all(f.startswith('.') and f == f.lower() for f in FORMATS))
        self.assertTrue({'.avif', '.heic', '.gif', '.jpg'} <= FORMATS)


def portrait_like():
    """Image de test avec un « visage » clair sur fond sombre (Vision n'y verra pas de personne)."""
    img = gradient()
    cv2.circle(img, (200, 150), 60, (150, 180, 220), -1)
    return img


class Vision(unittest.TestCase):
    """reto-segment (Apple Vision, Core Image) : sauté s'il n'est pas compilé sur la machine."""

    def setUp(self):
        from reveal import vision
        if not vision.disponible():
            self.skipTest('reto-segment non compilé (shared/natif/compiler.sh)')
        self.vision = vision
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.src = self.dir / 'p.png'
        cv2.imwrite(str(self.src), portrait_like())

    def tearDown(self):
        self.tmp.cleanup()

    def test_enhance_and_styles(self):
        res = self.vision.ameliorer(self.src, self.dir / 'e.png')
        self.assertTrue(res['ok'])
        warm = self.dir / 'chaud.png'
        cold = self.dir / 'froid.png'
        self.vision.rendu(self.src, warm, 'chaud')
        self.vision.rendu(self.src, cold, 'froid')
        w, c = cv2.imread(str(warm)).astype(int), cv2.imread(str(cold)).astype(int)
        # BGR : le rendu chaud a plus de rouge et moins de bleu que le froid
        self.assertGreater(w[:, :, 2].mean() - w[:, :, 0].mean(), c[:, :, 2].mean() - c[:, :, 0].mean())

    def test_crop_reports_its_box(self):
        res = self.vision.effet_studio('recadrage', self.src, self.dir / 'c.png', ratio='1:1')
        x, y, w, h = res['box']
        self.assertEqual(w, h)
        self.assertEqual(cv2.imread(str(self.dir / 'c.png')).shape[:2], (h, w))

    def test_unknown_values_are_refused(self):
        with self.assertRaises(self.vision.VisionError):
            self.vision.effet_studio('inconnu', self.src, self.dir / 'x.png')
        with self.assertRaises(self.vision.VisionError):
            self.vision.rendu(self.src, self.dir / 'x.png', 'inconnu')
        with self.assertRaises(self.vision.VisionError):
            self.vision.effet_studio('recadrage', self.src, self.dir / 'x.png', ratio='7:3')


class Effacement(unittest.TestCase):
    """MobileSAM + MI-GAN (embedkit) : sauté si les modèles ne sont pas installés."""

    def test_zones_are_validated(self):
        from reveal import effacer
        ok = effacer.valider([{'cadre': [0.1, 0.1, 0.2, 0.2]}, {'points': [[0.5, 0.5], [0.6, 0.6, 0]]}])
        self.assertEqual(ok[1]['points'][0][2], 1)
        for bad in ([], [{}], [{'cadre': [0.9, 0.1, 0.2, 0.2]}], [{'points': [[1.5, 0.2]]}],
                    [{'cadre': [0.1, 0.1, 0, 0.2]}], [{'cadre': [0, 0, 0.1, 0.1]}] * 21):
            with self.assertRaises(effacer.EffacementError, msg=str(bad)[:60]):
                effacer.valider(bad)

    def test_a_dark_square_disappears(self):
        from reveal import catalogue, effacer
        if not (catalogue.present('mobilesam') and catalogue.present('migan-512')):
            self.skipTest('MobileSAM ou MI-GAN absent')
        img = gradient(360, 480)
        clean = img.copy()
        cv2.rectangle(img, (200, 140), (260, 200), (20, 20, 20), -1)
        result, hole, details = effacer.effacer(img, [{'cadre': [180 / 480, 120 / 360, 100 / 480, 100 / 360]}])
        self.assertGreater(details[0][1], 0)
        zone = (slice(150, 190), slice(210, 250))
        self.assertLess(np.abs(result[zone].astype(int) - clean[zone].astype(int)).mean(), 25)
        self.assertEqual(np.abs(result[:100].astype(int) - img[:100].astype(int)).max(), 0)  # hors zone : intact


class Catalogue(unittest.TestCase):
    """Modèles déclarés pour embedkit (apps/reveal/modeles) et contrôle des licences."""

    def test_reveal_models_are_declared(self):
        from reveal import catalogue
        for mid in ('real-esrgan-x2', 'gfpgan-1.4', 'ddcolor', 'zhang-colorization',
                    'mobilesam', 'migan-512', 'depth-anything-v2-small'):
            m = catalogue.manifeste(mid)
            self.assertEqual(len(m.sha256), 64)

    def test_unverified_licences_are_flagged(self):
        from reveal import catalogue
        self.assertIs(catalogue.manifeste('real-esrgan-x2').license.commercial, True)
        for mid in catalogue.A_VERIFIER:
            self.assertIsNone(catalogue.manifeste(mid).license.commercial)

    def test_unknown_licence_is_refused_without_explicit_permission(self):
        from reveal import catalogue
        from shared.embedkit import licenses
        with self.assertRaises(licenses.LicenseError):
            licenses.check(catalogue.manifeste('gfpgan-1.4'), allow_noncommercial=False)

    def test_models_live_in_the_shared_store(self):
        from reveal import catalogue
        from shared.embedkit import store
        path = store.model_path(catalogue.manifeste('ddcolor'))
        self.assertTrue(str(path).startswith(os.environ['EMBEDKIT_CACHE']))
        self.assertEqual(path.name, 'ddcolor.onnx')


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
        from reveal import config
        self._saved = (interface.ORIGINAL, interface.RETOUCHE, config.APERCUS)
        interface.ORIGINAL, interface.RETOUCHE = self.orig, self.ret
        config.APERCUS = root / '.apercus'
        self.config = config
        self.interface = interface
        self.client = interface.app.test_client()

    def tearDown(self):
        self.interface.ORIGINAL, self.interface.RETOUCHE, self.config.APERCUS = self._saved
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

    def test_avif_gets_a_jpeg_preview(self):
        from PIL import Image
        Image.fromarray(cv2.cvtColor(gradient(), cv2.COLOR_BGR2RGB)).save(self.orig / 'b.avif', 'AVIF')
        self.assertIn('b.avif', [p['name'] for p in self.client.get('/api/photos').get_json()])
        r = self.client.get('/media/original/b.avif')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.mimetype, 'image/jpeg')
        self.assertTrue((self.config.APERCUS / 'b.avif.jpg').exists())
        r.close()

    def test_accepts_avif_upload(self):
        import io
        from PIL import Image
        buf = io.BytesIO()
        Image.fromarray(cv2.cvtColor(gradient(), cv2.COLOR_BGR2RGB)).save(buf, 'AVIF')
        r = self.client.post('/api/photos', data={'photo': (io.BytesIO(buf.getvalue()), 'c.avif')},
                             content_type='multipart/form-data')
        self.assertEqual(r.get_json()['name'], 'c.avif')

    def test_studio_settings_are_validated(self):
        bad = [{'effet': 'inconnu'}, {'effet': 'fond-uni', 'couleur': '300,0,0'},
               {'effet': 'fond-uni', 'couleur': 'rouge'}, {'effet': 'recadrage', 'format': '7:3'}]
        for opts in bad:
            r = self.client.post('/api/traiter', json=dict(photo='a.jpg', filtre='studio', **opts))
            self.assertEqual(r.status_code, 400, opts)

    def test_erase_zones_are_validated(self):
        for zones in (None, [], [{'cadre': [2, 0, 0.1, 0.1]}]):
            r = self.client.post('/api/traiter', json={'photo': 'a.jpg', 'filtre': 'effacer', 'zones': zones})
            self.assertEqual(r.status_code, 400, zones)

    def test_rejects_unknown_format(self):
        import io
        r = self.client.post('/api/photos', data={'photo': (io.BytesIO(b'x'), 'a.exe')},
                             content_type='multipart/form-data')
        self.assertEqual(r.status_code, 400)


if __name__ == '__main__':
    unittest.main()

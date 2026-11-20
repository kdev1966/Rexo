"""Tests des réglages de Rexo Dock (dossier de travail temporaire)."""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from dock import config


class TestConfig(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self._patch = mock.patch.object(config, 'REGLAGES', self.tmp / 'donnees/reglages.json')
        self._patch.start()

    def tearDown(self):
        self._patch.stop()
        self._tmp.cleanup()

    def test_defaut_dans_images(self):
        self.assertEqual(config.dossier_seances(), Path.home() / 'Pictures' / 'Rexo Dock')
        self.assertIsNone(config.dossier_miroir())

    def test_choix_retenus(self):
        s = config.choisir_seances(self.tmp / 'Séances')
        self.assertTrue(s.is_dir())
        config.choisir_miroir(self.tmp / 'Externe')
        self.assertEqual(config.dossier_seances(), s)
        self.assertEqual(config.dossier_miroir(), self.tmp / 'Externe')
        config.choisir_miroir(None)
        self.assertIsNone(config.dossier_miroir())
        self.assertEqual(config.dossier_seances(), s)

    def test_chemin_relatif_refuse(self):
        with self.assertRaises(config.ReglageError):
            config.choisir_seances('relatif')


if __name__ == '__main__':
    unittest.main()

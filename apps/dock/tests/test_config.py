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

    def test_defaut_sur_le_bureau(self):
        with mock.patch.object(config, 'dossier_bureau', return_value=self.tmp / 'Bureau'):
            self.assertEqual(config.dossier_seances(), self.tmp / 'Bureau' / 'Rexo Dock - Séances')
            self.assertFalse((self.tmp / 'Bureau' / 'Rexo Dock - Séances').exists())
            self.assertTrue(config.dossier_seances(creer=True).is_dir())
        self.assertIsNone(config.dossier_miroir())

    def test_bureau_du_mac(self):
        from shared import systeme
        if systeme.MACOS:
            self.assertEqual(systeme.dossier_bureau(), Path.home() / 'Desktop')

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

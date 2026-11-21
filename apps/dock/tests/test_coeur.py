"""Tests du cœur de Rexo Dock (repris des tests d'Import Studio).

Lancement (depuis apps/dock) : python3 -m unittest discover tests
"""

import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from dock import coeur
from dock.coeur import FichierAppareil, Registre

D1 = datetime.fromtimestamp(1_763_570_000, timezone.utc)


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()


class TestCle(unittest.TestCase):
    def test_taille_differente(self):
        a = FichierAppareil('IMG_0001.HEIC', 100, D1)
        b = FichierAppareil('IMG_0001.HEIC', 200, D1)
        self.assertNotEqual(a.cle, b.cle)

    def test_sans_date(self):
        self.assertEqual(FichierAppareil('x', 1).cle, 'x|1|-')

    def test_meme_forme_qu_import_studio(self):
        self.assertEqual(FichierAppareil('IMG_0001.HEIC', 100, D1).cle, 'IMG_0001.HEIC|100|1763570000')


class TestRegistre(Base):
    def test_persistance_et_filtrage(self):
        chemin = self.tmp / 'sous/imported.json'
        a = FichierAppareil('IMG_0001.HEIC', 100, D1)
        b = FichierAppareil('IMG_0001.HEIC', 200, D1)
        c = FichierAppareil('IMG_0002.MOV', 300, D1)
        r = Registre(chemin)
        self.assertEqual(len(r.nouveaux([a, b], 'P1')), 2)
        r.enregistrer(a, 'P1')
        self.assertTrue(Registre(chemin).contient(a, 'P1'))
        self.assertEqual(Registre(chemin).nouveaux([a, b], 'P1'), [b])
        self.assertEqual(Registre(chemin).nouveaux([a], 'P2'), [a])     # séparé par appareil
        r.enregistrer_tous([b, c], 'P1')
        self.assertEqual(Registre(chemin).nouveaux([a, b, c], 'P1'), [])
        self.assertEqual(len(Registre(chemin).entrees['P1']), 3)        # pas de doublon
        self.assertFalse(chemin.with_name('imported.json.partiel').exists())

    def test_registre_illisible(self):
        chemin = self.tmp / 'imported.json'
        chemin.write_text('pas du json')
        self.assertEqual(Registre(chemin).entrees, {})

    def test_lit_le_registre_d_import_studio(self):
        chemin = self.tmp / 'imported.json'
        chemin.write_text('{"P1":["IMG_0001.HEIC|100|1763570000"]}')
        self.assertTrue(Registre(chemin).contient(FichierAppareil('IMG_0001.HEIC', 100, D1), 'P1'))


class TestNoms(Base):
    def test_genres(self):
        self.assertEqual(coeur.genre('IMG_1.HEIC'), coeur.PHOTO)
        self.assertEqual(coeur.genre('IMG_1.mov'), coeur.VIDEO)
        self.assertEqual(coeur.genre('IMG_1.DNG'), coeur.RAW)
        self.assertEqual(coeur.genre('IMG_O1.AAE'), coeur.RETOUCHE)
        self.assertEqual(coeur.genre('IMG_20261121_143005.jpg'), coeur.PHOTO)
        self.assertEqual(coeur.genre('DCIM'), coeur.AUTRE)          # dossier Android vu comme un fichier
        self.assertEqual(coeur.genre('.nomedia'), coeur.AUTRE)
        f = coeur.FichierAppareil('DCIM', 0, None)
        self.assertEqual(coeur.catalogue([f]), [])

    def test_retouches(self):
        self.assertEqual(coeur.noms_retouche('IMG_1234.HEIC'), ['IMG_1234.AAE', 'IMG_O1234.AAE'])
        self.assertEqual(coeur.noms_retouche('img_e1234.heic'), ['IMG_1234.AAE', 'IMG_O1234.AAE'])
        self.assertEqual(coeur.noms_retouche('photo.jpg'), ['PHOTO.AAE'])

    def test_dossier_seance(self):
        jour = datetime(2026, 11, 25, 12)
        self.assertEqual(coeur.nom_dossier_seance(jour), '2026-11-25')
        self.assertEqual(coeur.nom_dossier_seance(jour, '  Mariage Martin '), '2026-11-25 Mariage Martin')
        self.assertEqual(coeur.nom_dossier_seance(jour, 'A/B:C'), '2026-11-25 A-B-C')

    def test_nom_libre(self):
        self.assertEqual(coeur.nom_libre('IMG_1.HEIC', self.tmp), 'IMG_1.HEIC')
        (self.tmp / 'IMG_1.HEIC').write_bytes(b'\1')
        self.assertEqual(coeur.nom_libre('IMG_1.HEIC', self.tmp), 'IMG_1_2.HEIC')
        (self.tmp / 'IMG_1_2.HEIC').write_bytes(b'\1')
        self.assertEqual(coeur.nom_libre('IMG_1.HEIC', self.tmp), 'IMG_1_3.HEIC')


class TestFichiers(Base):
    def test_sha256_et_date(self):
        f = self.tmp / 'abc.txt'
        f.write_bytes(b'abc')
        self.assertEqual(coeur.sha256(f), 'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad')
        coeur.appliquer_date(f, D1)
        self.assertLess(abs(os.stat(f).st_mtime - D1.timestamp()), 1)

    def test_espace_libre(self):
        self.assertGreater(coeur.espace_libre(self.tmp), 0)


class TestMiroir(Base):
    def test_seconde_copie(self):
        src, dst = self.tmp / 'Séances', self.tmp / 'Externe/Séances'
        (src / '2026-11-25').mkdir(parents=True)
        (src / '2026-11-25/VID.MOV').write_bytes(b'\7' * 5_000_000)
        (src / '2026-11-25/IMG.HEIC').write_bytes(b'\1\2\3')
        (src / '.DS_Store').write_bytes(b'x')

        r = coeur.miroir(src, dst)
        self.assertEqual((r.copies, r.echecs), (2, []))
        self.assertEqual(coeur.sha256(dst / '2026-11-25/VID.MOV'), coeur.sha256(src / '2026-11-25/VID.MOV'))
        self.assertFalse((dst / '.DS_Store').exists())

        r = coeur.miroir(src, dst)
        self.assertEqual((r.copies, r.deja_la), (0, 2))

        (dst / '2026-11-25/IMG.HEIC').write_bytes(b'\9\9\9\9')       # différent sur le disque externe
        r = coeur.miroir(src, dst)
        self.assertEqual(r.copies, 1)
        self.assertEqual((dst / '2026-11-25/IMG.HEIC').read_bytes(), b'\9\9\9\9')   # pas écrasé
        self.assertEqual((dst / '2026-11-25/IMG_2.HEIC').read_bytes(), b'\1\2\3')

        r = coeur.miroir(src, dst)                                   # Import Studio recopiait ici
        self.assertEqual((r.copies, r.deja_la), (0, 2))
        self.assertFalse((dst / '2026-11-25/IMG_3.HEIC').exists())

    def test_source_absente(self):
        r = coeur.miroir(self.tmp / 'absent', self.tmp / 'dst')
        self.assertEqual(len(r.echecs), 1)


if __name__ == '__main__':
    unittest.main()

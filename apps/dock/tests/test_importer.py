"""Tests du catalogue et de l'import, avec un faux appareil (sans iPhone).

Lancement (depuis apps/dock) : .venv/bin/python -m unittest discover tests
"""

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dock import coeur
from dock.coeur import FichierAppareil, Registre
from dock.importer import ErreurAppareil, PlaceInsuffisante, importer

T0 = datetime(2026, 11, 20, 10, tzinfo=timezone.utc)


def f(nom, taille=10, minutes=0):
    return FichierAppareil(nom, taille, T0 + timedelta(minutes=minutes))


class FauxAppareil:
    identifiant, nom = 'SERIE1', 'iPhone d\'essai'

    def __init__(self, tronques=(), en_echec=(), debranche_apres=None):
        self.tronques, self.en_echec, self.debranche_apres = set(tronques), set(en_echec), debranche_apres
        self.copies = []

    def copier(self, fichier, dossier, nom):
        if self.debranche_apres is not None and len(self.copies) >= self.debranche_apres:
            raise ErreurAppareil('appareil absent', debranche=True)
        if fichier.nom in self.en_echec:
            raise ErreurAppareil('erreur de lecture')
        self.copies.append(fichier.nom)
        taille = fichier.taille - 1 if fichier.nom in self.tronques else fichier.taille
        chemin = Path(dossier) / nom
        chemin.write_bytes(b'x' * taille)
        return chemin


class TestCatalogue(unittest.TestCase):
    def test_retouches_rattachees_et_ordre(self):
        fichiers = [f('IMG_0001.HEIC', minutes=1), f('IMG_0001.AAE'), f('IMG_E0002.HEIC', minutes=5),
                    f('IMG_O0002.AAE'), f('IMG_0003.MOV', minutes=3)]
        e = coeur.catalogue(fichiers)
        self.assertEqual([x.fichier.nom for x in e], ['IMG_E0002.HEIC', 'IMG_0003.MOV', 'IMG_0001.HEIC'])
        self.assertEqual([r.nom for r in e[2].retouches], ['IMG_0001.AAE'])
        self.assertEqual([r.nom for r in e[0].retouches], ['IMG_O0002.AAE'])
        self.assertEqual(e[1].genre, coeur.VIDEO)

    def test_deja_importe(self):
        with tempfile.TemporaryDirectory() as d:
            r = Registre(Path(d) / 'r.json')
            a = f('IMG_0001.HEIC')
            r.enregistrer(a, 'P1')
            self.assertTrue(coeur.catalogue([a], r, 'P1')[0].importe)
            self.assertFalse(coeur.catalogue([a], r, 'P2')[0].importe)

    def test_rafale_hors_de_la_cle(self):
        self.assertEqual(FichierAppareil('a', 1, T0, rafale='X'), FichierAppareil('a', 1, T0))

    def test_fichiers_a_copier_sans_doublon(self):
        e = coeur.catalogue([f('IMG_0001.HEIC', minutes=2), f('IMG_0001.AAE', minutes=2), f('IMG_0002.JPG')])
        noms = [x.nom for x in coeur.fichiers_a_copier(e + e)]
        self.assertEqual(noms, ['IMG_0002.JPG', 'IMG_0001.HEIC', 'IMG_0001.AAE'])


class TestImport(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.racine = Path(self._tmp.name) / 'Séances'
        self.registre = Registre(Path(self._tmp.name) / 'registre.json')

    def tearDown(self):
        self._tmp.cleanup()

    def test_import_complet(self):
        e = coeur.catalogue([f('IMG_0001.HEIC', 5, 1), f('IMG_0001.AAE', 3, 1), f('IMG_0002.MOV', 7, 2)])
        etapes = []
        r = importer(FauxAppareil(), e, self.racine, self.registre, 'Mariage', date=T0,
                     progression=lambda i, n, nom: etapes.append((i, n)), marge=0)
        self.assertEqual((r.importes, r.total, r.echecs), (3, 3, []))
        self.assertEqual(r.dossier.name, '2026-11-20 Mariage')
        self.assertEqual(etapes[-1], (3, 3))
        self.assertEqual((r.dossier / 'IMG_0002.MOV').stat().st_mtime, (T0 + timedelta(minutes=2)).timestamp())
        self.assertEqual(coeur.catalogue([f('IMG_0001.HEIC', 5, 1)], Registre(self.registre.chemin), 'SERIE1')[0].importe, True)
        self.assertIn('3 fichier(s) importé(s) sur 3', r.rapport.read_text(encoding='utf-8'))

    def test_pas_d_ecrasement(self):
        e = coeur.catalogue([f('IMG_0001.HEIC', 5)])
        importer(FauxAppareil(), e, self.racine, Registre(self.registre.chemin), date=T0, marge=0)
        r = importer(FauxAppareil(), e, self.racine, Registre(Path(self._tmp.name) / 'autre.json'), date=T0, marge=0)
        self.assertTrue((r.dossier / 'IMG_0001_2.HEIC').exists())
        self.assertTrue(r.rapport.name.endswith('_2.txt'))

    def test_taille_fausse_et_erreur(self):
        e = coeur.catalogue([f('A.HEIC', 5, 1), f('B.HEIC', 5, 2), f('C.HEIC', 5, 3)])
        r = importer(FauxAppareil(tronques={'A.HEIC'}, en_echec={'B.HEIC'}), e, self.racine, self.registre,
                     date=T0, marge=0)
        self.assertEqual(r.importes, 1)
        self.assertEqual([n for n, _ in r.echecs], ['A.HEIC', 'B.HEIC'])
        self.assertFalse((r.dossier / 'A.HEIC').exists())          # copie incomplète retirée
        self.assertEqual(coeur.catalogue([f('A.HEIC', 5, 1)], self.registre, 'SERIE1')[0].importe, False)

    def test_debranche(self):
        e = coeur.catalogue([f('A.HEIC', 5, 1), f('B.HEIC', 5, 2), f('C.HEIC', 5, 3)])
        app = FauxAppareil(debranche_apres=1)
        r = importer(app, e, self.racine, self.registre, date=T0, marge=0)
        self.assertEqual(app.copies, ['A.HEIC'])
        self.assertEqual([n for n, _ in r.echecs], ['B.HEIC', 'C.HEIC'])
        self.assertIn('Rien n\'a été supprimé', r.rapport.read_text(encoding='utf-8'))

    def test_place_insuffisante(self):
        e = coeur.catalogue([f('A.HEIC', 5)])
        with self.assertRaises(PlaceInsuffisante):
            importer(FauxAppareil(), e, self.racine, self.registre, marge=10 ** 18)
        self.assertEqual(list(self.racine.iterdir()), [])          # aucun dossier de séance créé


if __name__ == '__main__':
    unittest.main()

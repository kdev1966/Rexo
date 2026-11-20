"""Tests du regroupement par personne (sans modèle : empreintes synthétiques).

Lancement (depuis apps/dock) : .venv/bin/python -m unittest discover tests
"""

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import cv2
import numpy as np

from dock import coeur, personnes, seances


def identite(graine, bruit=0.0, rng=None):
    """Empreinte d'une « personne » (graine), avec une variation (autre photo)."""
    base = np.random.default_rng(graine).normal(size=128)
    if bruit:
        base = base + (rng or np.random.default_rng()).normal(scale=bruit, size=128)
    return (base / np.linalg.norm(base)).astype(np.float32)


class TestRegrouper(unittest.TestCase):
    def test_trois_personnes(self):
        rng = np.random.default_rng(1)
        emb = [identite(1, 0.06, rng) for _ in range(5)] + [identite(2, 0.06, rng) for _ in range(3)] + [identite(3)]
        groupes = personnes.regrouper(np.stack(emb))
        self.assertEqual([sorted(g) for g in groupes], [[0, 1, 2, 3, 4], [5, 6, 7], [8]])

    def test_vide(self):
        self.assertEqual(personnes.regrouper(np.zeros((0, 128))), [])


class TestSeance(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.d = Path(self._tmp.name) / '2026-11-20'
        self.d.mkdir()
        img = np.full((300, 400, 3), 128, np.uint8)
        # A et B : personne 1 ; C : personnes 1 et 2 ; D : personne 2 ; E : personne 3 seule
        self.contenu = {'A.JPG': [1], 'B.JPG': [1], 'C.JPG': [1, 2], 'D.JPG': [2], 'E.JPG': [3]}
        for nom in self.contenu:
            cv2.imwrite(str(self.d / nom), img)
        rng = np.random.default_rng(0)
        faux = lambda chemin: [([10.0, 10.0, 80.0, 80.0], identite(g, 0.05, rng)) for g in self.contenu[Path(chemin).name]]
        self._p = mock.patch.object(personnes, 'visages_photo', side_effect=faux)
        self._p.start()

    def tearDown(self):
        self._p.stop()
        self._tmp.cleanup()

    def test_rien_sans_demande(self):
        self.assertFalse(personnes.actif(self.d))
        self.assertEqual(personnes.calculer(self.d), 0)
        self.assertFalse((self.d / personnes.FICHIER).exists())
        self.assertEqual(personnes.personnes(self.d), [])

    def test_cycle(self):
        personnes.activer(self.d)
        self.assertEqual(personnes.calculer(self.d), 5)
        self.assertEqual(personnes.a_calculer(self.d), [])
        ps = personnes.personnes(self.d)
        self.assertEqual([p['photos'] for p in ps], [['A.JPG', 'B.JPG', 'C.JPG'], ['C.JPG', 'D.JPG']])
        self.assertEqual([p['numero'] for p in ps], [1, 2])            # la personne 3 (une photo) n'apparaît pas

        # Pas de nom ni de copie : seulement des cadres et des empreintes, dans la séance
        d = json.loads((self.d / personnes.FICHIER).read_text())
        self.assertEqual(set(d['photos']['C.JPG']['visages'][0]), {'cadre', 'e'})

        # La seconde copie ne recopie pas les empreintes (fichier caché)
        coeur.miroir(self.d, Path(self._tmp.name) / 'Externe')
        self.assertFalse((Path(self._tmp.name) / 'Externe' / personnes.FICHIER).exists())

        # Photo écartée : son empreinte est purgée au calcul suivant
        seances.ecarter(self.d, ['A.JPG'])
        self.assertEqual(personnes.purger(self.d), 1)
        self.assertNotIn('A.JPG', personnes.lire(self.d)['photos'])

        personnes.effacer(self.d)
        self.assertFalse((self.d / personnes.FICHIER).exists())
        self.assertFalse(personnes.actif(self.d))


if __name__ == '__main__':
    unittest.main()

"""Tests de l'aide au tri et des séances (sans modèle d'IA : les visages sont remplacés).

Lancement (depuis apps/dock) : .venv/bin/python -m unittest discover tests
"""

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

import cv2
import numpy as np

from dock import coeur, seances, tri
from dock.coeur import FichierAppareil

T0 = datetime(2026, 11, 20, 10, tzinfo=timezone.utc)


def image_nette(graine=0, l=1200, h=900):
    """Image texturée (bords nets partout), reproductible."""
    rng = np.random.default_rng(graine)
    petite = rng.integers(0, 255, (h // 20, l // 20, 3), dtype=np.uint8)
    return cv2.resize(petite, (l, h), interpolation=cv2.INTER_NEAREST)


class TestMesures(unittest.TestCase):
    def test_flou_moins_net(self):
        img = image_nette()
        self.assertGreater(tri.nettete(img), 10 * tri.nettete(cv2.GaussianBlur(img, (0, 0), 4)))

    def test_fond_flou_sujet_net(self):
        """Un sujet net sur un fond flou n'est pas une photo floue : la zone la plus nette compte."""
        img = cv2.GaussianBlur(image_nette(), (0, 0), 6)
        img[300:600, 450:750] = image_nette(1)[300:600, 450:750]
        self.assertGreater(tri.nettete(img), tri.FLOU_ABSOLU * 5)

    def test_empreinte(self):
        a = image_nette(0)
        self.assertEqual(tri.distance(tri.empreinte(a), tri.empreinte(cv2.GaussianBlur(a, (0, 0), 1))), 0)
        self.assertGreater(tri.distance(tri.empreinte(a), tri.empreinte(image_nette(5))), 16)

    def test_ouverture_des_yeux(self):
        # œil ouvert : ellipse de 40 × 14 ; fermé : 40 × 3 ; incliné de 20° (redressé par ses coins)
        def oeil(h, angle):
            t = np.linspace(0, 2 * np.pi, 16, endpoint=False)
            t = np.roll(t, -8)                         # point 8 : coin opposé au point 0
            p = np.stack([20 * np.cos(t), h / 2 * np.sin(t)], 1)
            a = np.radians(angle)
            r = np.array([[np.cos(a), -np.sin(a)], [np.sin(a), np.cos(a)]])
            return np.column_stack([p @ r.T + 300, np.zeros(16)])
        idx = list(range(16))
        self.assertAlmostEqual(tri._ouverture(oeil(14, 20), idx), 0.35, places=2)
        self.assertLess(tri._ouverture(oeil(3, 20), idx), tri.OUVERTURE_MIN)


def photo(nom, sec, nettete=500.0, empreinte='0' * 16, rafale=None, yeux_fermes=False):
    return {'nom': nom, 'date': T0.timestamp() + sec, 'nettete': nettete, 'empreinte': empreinte,
            'rafale': rafale, 'yeux_fermes': yeux_fermes}


class TestClasser(unittest.TestCase):
    def test_serie_et_meilleure(self):
        ps = [photo('a', 0, 300), photo('b', 2, 900), photo('c', 4, 600, yeux_fermes=True),
              photo('d', 3600, 500, 'f' * 16)]
        tri.classer(ps)
        a, b, c, d = ps
        self.assertTrue(b['meilleure'])
        self.assertTrue(a['doublon'] and c['doublon'] and a['a_trier'])
        self.assertEqual(a['serie'], b['serie'])
        self.assertIsNone(d['serie'])
        self.assertFalse(d['a_trier'])

    def test_yeux_fermes_jamais_meilleure(self):
        ps = [photo('a', 0, 2000, yeux_fermes=True), photo('b', 1, 400)]
        tri.classer(ps)
        self.assertTrue(ps[1]['meilleure'])

    def test_rafale_de_l_iphone(self):
        ps = [photo('a', 0, 500, '0' * 16, 'R1'), photo('b', 30, 400, 'f' * 16, 'R1')]
        tri.classer(ps)
        self.assertEqual(ps[0]['serie'], ps[1]['serie'])

    def test_identiques_a_dix_minutes(self):
        ps = [photo('a', 0, 500, 'abcdef0123456789'), photo('b', 600, 400, 'abcdef0123456788')]
        tri.classer(ps)
        self.assertTrue(ps[0]['meilleure'] and ps[1]['doublon'])

    def test_differentes_ne_sont_pas_une_serie(self):
        ps = [photo('a', 0, empreinte='0' * 16), photo('b', 2, empreinte='f' * 16)]
        tri.classer(ps)
        self.assertFalse(ps[0]['doublon'] or ps[1]['doublon'])

    def test_flou_absolu_et_relatif(self):
        ps = [photo(str(i), i * 600, 1000, '%016x' % (i * 0x1111111111)) for i in range(6)]
        ps.append(photo('mou', 9000, 150, 'abcdefabcdefabcd'))      # 150 < 0,2 × 1000
        ps.append(photo('flou', 9600, 20, '1234567812345678'))
        tri.classer(ps)
        self.assertTrue(ps[-2]['floue'] and ps[-1]['floue'])
        self.assertFalse(any(p['floue'] for p in ps[:6]))

    def test_pas_de_relatif_sur_une_petite_seance(self):
        ps = [photo('a', 0, 2000, '0' * 16), photo('b', 900, 150, 'f' * 16)]
        tri.classer(ps)
        self.assertFalse(ps[1]['floue'])


class TestDecouperSeances(unittest.TestCase):
    def test_ecarts(self):
        e = coeur.catalogue([FichierAppareil(n, 1, T0 + timedelta(hours=h))
                             for n, h in (('a', 0), ('b', 1), ('c', 5), ('d', 5.5), ('e', 30))])
        e.append(coeur.Entree(FichierAppareil('x', 1), coeur.PHOTO))
        s = coeur.decouper_seances(e)
        self.assertEqual([[x.fichier.nom for x in g] for g in s], [['a', 'b'], ['c', 'd'], ['e', 'x']])


class TestSeances(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.dossier = self.tmp / 'Séances' / '2026-11-20 Mariage'
        self.dossier.mkdir(parents=True)
        self.vignettes = self.tmp / 'vignettes'
        self._yeux = mock.patch.object(tri, 'yeux', return_value=(0, []))
        self._yeux.start()

    def tearDown(self):
        self._yeux.stop()
        self._tmp.cleanup()

    def test_cycle(self):
        nette = image_nette(0)
        cv2.imwrite(str(self.dossier / 'IMG_1.JPG'), nette)
        cv2.imwrite(str(self.dossier / 'IMG_2.JPG'), cv2.GaussianBlur(nette, (0, 0), 1.2))   # même scène
        cv2.imwrite(str(self.dossier / 'IMG_3.JPG'), cv2.GaussianBlur(image_nette(7), (0, 0), 6))
        (self.dossier / 'IMG_4.MOV').write_bytes(b'video')
        (self.dossier / "Rapport d'import.txt").write_text('rapport')
        f1 = FichierAppareil('IMG_1.JPG', 1, T0)
        f2 = FichierAppareil('IMG_2.JPG', 1, T0 + timedelta(seconds=1), rafale='R')
        f3 = FichierAppareil('IMG_3.JPG', 1, T0 + timedelta(hours=1))
        seances.noter_import([(f1, self.dossier / 'IMG_1.JPG'), (f2, self.dossier / 'IMG_2.JPG'),
                              (f3, self.dossier / 'IMG_3.JPG'),
                              (FichierAppareil('IMG_4.MOV', 1, T0), self.dossier / 'IMG_4.MOV')])
        self.assertEqual(len(seances.a_analyser(self.dossier)), 3)
        self.assertEqual(seances.analyser_dossier(self.dossier, self.vignettes), 3)
        self.assertEqual(seances.a_analyser(self.dossier), [])                  # rien à refaire

        ps = {p['nom']: p for p in seances.photos(self.dossier)}
        self.assertEqual(set(ps), {'IMG_1.JPG', 'IMG_2.JPG', 'IMG_3.JPG'})
        self.assertTrue(ps['IMG_1.JPG']['meilleure'] and ps['IMG_2.JPG']['doublon'])
        self.assertTrue(ps['IMG_3.JPG']['floue'] and ps['IMG_3.JPG']['a_trier'])
        self.assertEqual(ps['IMG_2.JPG']['rafale'], 'R')
        self.assertTrue(seances.chemin_vignette(self.dossier / 'IMG_1.JPG', self.vignettes).is_file())
        # rien n'est déplacé ni supprimé dans la séance
        self.assertEqual(len(list(self.dossier.iterdir())), 6)
        donnees = json.loads((self.dossier / seances.FICHIER).read_text(encoding='utf-8'))
        self.assertIn('IMG_3.JPG', donnees['photos'])

        # photo remplacée : analysée de nouveau
        cv2.imwrite(str(self.dossier / 'IMG_3.JPG'), image_nette(9))
        self.assertEqual([p.name for p in seances.a_analyser(self.dossier)], ['IMG_3.JPG'])

    def test_lister(self):
        (self.tmp / 'Séances' / '2026-11-21').mkdir()
        (self.tmp / 'Séances' / '.cache').mkdir()
        self.assertEqual([d.name for d in seances.lister(self.tmp / 'Séances')],
                         ['2026-11-21', '2026-11-20 Mariage'])


if __name__ == '__main__':
    unittest.main()

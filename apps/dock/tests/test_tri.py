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
        from shared.images import chemin_vignette
        self.assertTrue(chemin_vignette(self.dossier / 'IMG_1.JPG', self.vignettes, seances.COTE_VIGNETTE).is_file())
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


class TestActions(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.d = self.tmp / '2026-11-20'
        self.d.mkdir()
        self.corbeille = self.tmp / 'Corbeille'
        self._yeux = mock.patch.object(tri, 'yeux', return_value=(0, []))
        self._yeux.start()
        for i, img in enumerate((image_nette(0), cv2.GaussianBlur(image_nette(3), (0, 0), 8)), 1):
            cv2.imwrite(str(self.d / ('IMG_%d.JPG' % i)), img)
        (self.d / 'IMG_2.AAE').write_text('retouche')
        seances.analyser_dossier(self.d, self.tmp / 'v')

    def tearDown(self):
        self._yeux.stop()
        self._tmp.cleanup()

    def noms(self):
        return {p['nom']: p for p in seances.photos(self.d)}

    def test_garder(self):
        self.assertTrue(self.noms()['IMG_2.JPG']['a_trier'])
        seances.garder(self.d, ['IMG_2.JPG'])
        p = self.noms()['IMG_2.JPG']
        self.assertTrue(p['garde'] and not p['a_trier'])
        seances.garder(self.d, ['IMG_2.JPG'], False)
        self.assertTrue(self.noms()['IMG_2.JPG']['a_trier'])

    def test_ecarter_puis_remettre(self):
        seances.ecarter(self.d, ['IMG_2.JPG'])
        self.assertEqual(set(self.noms()), {'IMG_1.JPG'})
        e = self.d / seances.ECARTEES
        self.assertTrue((e / 'IMG_2.JPG').is_file() and (e / 'IMG_2.AAE').is_file())
        self.assertEqual(seances.ecartees(self.d)[0]['origine'], 'IMG_2.JPG')
        self.assertEqual(seances.a_analyser(self.d), [])            # les écartées ne sont pas analysées
        # un fichier du même nom est apparu entre-temps : rien n'est écrasé
        (self.d / 'IMG_2.JPG').write_bytes(b'autre')
        seances.remettre(self.d, ['IMG_2.JPG'])
        self.assertEqual((self.d / 'IMG_2.JPG').read_bytes(), b'autre')
        self.assertTrue((self.d / 'IMG_2_2.JPG').is_file() and (self.d / 'IMG_2.AAE').is_file())
        self.assertIn('nettete', seances.lire(self.d)['photos']['IMG_2_2.JPG'])   # l'analyse a suivi

    def test_corbeille(self):
        seances.corbeille(self.d, ['IMG_2.JPG'], dossier_corbeille=self.corbeille)
        self.assertFalse((self.d / 'IMG_2.JPG').exists() or (self.d / 'IMG_2.AAE').exists())
        self.assertEqual({p.name for p in self.corbeille.iterdir()}, {'IMG_2.JPG', 'IMG_2.AAE'})
        self.assertNotIn('IMG_2.JPG', seances.lire(self.d)['photos'])

    def test_nom_hors_de_la_seance_refuse(self):
        with self.assertRaises(seances.ActionImpossible):
            seances.ecarter(self.d, ['../2026-11-20/IMG_1.JPG/..'])
        with self.assertRaises(seances.ActionImpossible):
            seances.corbeille(self.d, ['../../etc/hosts'], dossier_corbeille=self.corbeille)


class TestImageDeVideo(unittest.TestCase):
    def test_image_a_une_seconde(self):
        from shared.images import ConversionImpossible, image_de_video
        with tempfile.TemporaryDirectory() as d:
            chemin = Path(d) / 'essai.mp4'
            w = cv2.VideoWriter(str(chemin), cv2.VideoWriter_fourcc(*'mp4v'), 10, (320, 240))
            for i in range(30):                     # 3 s : noir pendant 1 s, puis blanc
                w.write(np.full((240, 320, 3), 0 if i < 10 else 255, np.uint8))
            w.release()
            img = image_de_video(chemin, 160)
            self.assertEqual(img.shape[:2], (120, 160))
            self.assertGreater(img.mean(), 200)
            (Path(d) / 'faux.mov').write_bytes(b'pas une video')
            with self.assertRaises(ConversionImpossible):
                image_de_video(Path(d) / 'faux.mov', 160)

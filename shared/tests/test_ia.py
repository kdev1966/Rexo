"""Tests du catalogue commun des modèles (shared/ia).

Lancement, depuis la racine du hub, avec l'environnement de n'importe quelle application :
    apps/reveal/.venv/bin/python -m unittest discover -s shared/tests -t .
"""

import os
import unittest

from shared import ia


class Catalogue(unittest.TestCase):
    """Un seul catalogue pour toutes les applications : manifestes, licences, magasin partagé."""

    def test_tous_les_modeles_sont_declares(self):
        for mid in ('yunet-2023mar', 'facemesh-v2', 'modnet', 'sface-2021dec',          # visages, détourage
                    'real-esrgan-x2', 'gfpgan-1.4', 'ddcolor', 'ddcolor-tiny', 'zhang-colorization',
                    'rayures-anciennes', 'lama-512', 'scunet-512',                       # restauration
                    'mobilesam', 'migan-512', 'depth-anything-v2-small'):                # livrés avec embedkit
            self.assertEqual(len(ia.manifeste(mid).sha256), 64, mid)

    def test_licences_non_verifiees_signalees(self):
        self.assertIs(ia.manifeste('real-esrgan-x2').license.commercial, True)
        for mid in ia.A_VERIFIER:
            self.assertIsNone(ia.manifeste(mid).license.commercial, mid)

    def test_licence_inconnue_refusee_sans_autorisation(self):
        from shared.embedkit import licenses
        with self.assertRaises(licenses.LicenseError):
            licenses.check(ia.manifeste('gfpgan-1.4'), allow_noncommercial=False)

    def test_magasin_partage(self):
        from shared.embedkit import store
        path = store.model_path(ia.manifeste('ddcolor'))
        self.assertTrue(str(path).startswith(os.environ['EMBEDKIT_CACHE']))
        self.assertEqual(path.name, 'ddcolor.onnx')

    def test_modele_absent(self):
        with self.assertRaises(Exception):
            ia.manifeste('modele-qui-n-existe-pas')


if __name__ == '__main__':
    unittest.main()

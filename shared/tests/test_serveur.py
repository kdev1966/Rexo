"""Tests des outils communs des interfaces (shared/serveur.py).

Lancement, depuis la racine du hub : apps/reveal/.venv/bin/python -m unittest discover -s shared/tests -t .
"""

import tempfile
import unittest
from pathlib import Path

from flask import jsonify
from werkzeug.exceptions import NotFound, UnsupportedMediaType

from shared import serveur


class Outils(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.racine = Path(self._tmp.name)
        self.web = self.racine / 'appli' / 'web'
        self.web.mkdir(parents=True)
        (self.web / 'index.html').write_text('<!doctype html><title>Essai</title>')
        (self.web / 'app.js').write_text('// essai')
        (self.web / 'ar.json').write_text('{"Bonjour": "مرحبا"}', encoding='utf-8')
        self.app = serveur.creer_app('essai.interface', self.racine / 'appli')
        self.dossier = self.racine / 'photos'
        (self.dossier / 'seance').mkdir(parents=True)
        (self.dossier / 'a.jpg').write_bytes(b'x')
        (self.racine / 'secret.txt').write_text('ne pas servir')

    def tearDown(self):
        self._tmp.cleanup()

    def test_pages_communes(self):
        c = self.app.test_client()
        for url in ('/', '/static/app.js', '/langues/ar.js', '/commun/rexo.css', '/commun/rexo.js', '/api/version'):
            r = c.get(url)
            self.assertEqual(r.status_code, 200, url)
        self.assertEqual(c.get('/').headers['Cache-Control'], 'no-cache')
        self.assertEqual(c.get('/static/../../secret.txt').status_code, 404)

    def test_jamais_hors_du_dossier(self):
        with self.app.test_request_context():
            self.assertEqual(serveur.fichier_sur(self.dossier, 'a.jpg').name, 'a.jpg')
            self.assertTrue(serveur.dossier_sur(self.dossier, 'seance').is_dir())
            for nom in ('../secret.txt', '../../secret.txt', 'seance/../../secret.txt', '', None, 'absent.jpg'):
                with self.assertRaises(NotFound, msg=nom):
                    serveur.fichier_sur(self.dossier, nom)
            with self.assertRaises(NotFound):
                serveur.dossier_sur(self.dossier, 'a.jpg')               # un fichier n'est pas un dossier

    def test_erreurs_lisibles_et_corps_json(self):
        @self.app.post('/essai')
        @serveur.erreurs_lisibles(ValueError)
        def essai():
            d = serveur.corps_json()
            if d.get('casser'):
                raise ValueError('Nom manquant.')
            return jsonify(ok=True)
        c = self.app.test_client()
        self.assertEqual(c.post('/essai', json={}).status_code, 200)
        r = c.post('/essai', json={'casser': True})
        self.assertEqual((r.status_code, r.get_json()['error']), (400, 'Nom manquant.'))
        self.assertEqual(c.post('/essai', data='pas du json').status_code, UnsupportedMediaType.code)


if __name__ == '__main__':
    unittest.main()

#!/usr/bin/env python3
"""Interface web locale d'Identité.

Lancement (depuis le dossier apps/identite) :
    .venv/bin/python -m identite.interface
puis ouvrir http://127.0.0.1:8766 dans le navigateur.

Le serveur n'écoute que sur la machine elle-même (127.0.0.1) : aucune photo ne sort.
"""

import json
import subprocess
import threading
from pathlib import Path

from flask import Flask, abort, jsonify, request, send_file, send_from_directory
from werkzeug.utils import secure_filename

from shared.images import FORMATS, ConversionImpossible, convertir
from shared.serveur import ajouter_quitter

from . import couleurs
from .config import DONNEES, ORIGINAL, RESULTATS
from .fabriquer import fabriquer
from .normes import FRANCE, Norme
from .visage import VisageError

WEB = Path(__file__).resolve().parent / 'web'
APERCUS = DONNEES / '.apercus'          # aperçus JPEG des formats que le navigateur n'affiche pas
HOST, PORT = '127.0.0.1', 8766
WEB_NATIF = {'.jpg', '.jpeg', '.png', '.webp', '.gif', '.bmp'}
FICHIERS = ('identite', 'planche_8', 'planche_4_portrait')

app = Flask(__name__, static_folder=None)
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024
ajouter_quitter(app)        # bouton « Quitter » : arrête le serveur
_verrou = threading.Lock()


def _safe(folder, name):
    """Chemin d'un fichier existant dans `folder`, sans possibilité d'en sortir."""
    path = (folder / name).resolve()
    if path.parent != folder.resolve() or not path.is_file():
        abort(404)
    return path


def _photos():
    return sorted((p for p in ORIGINAL.iterdir() if p.suffix.lower() in FORMATS and not p.name.startswith('.')),
                  key=lambda p: p.name.lower())


def _resultat(photo):
    """Rapport et fichiers déjà produits pour `photo` (nom dans original/), ou None."""
    stem = Path(photo).stem
    rapport = RESULTATS / ('%s_rapport.json' % stem)
    if not rapport.is_file():
        return None
    try:
        r = json.loads(rapport.read_text())
    except ValueError:
        return None
    if r.get('photo') != photo:                 # même nom, autre extension : autre photo
        return None
    if not all((RESULTATS / r['fichiers'].get(k, '')).is_file() for k in FICHIERS):
        return None
    r['version'] = int(rapport.stat().st_mtime)
    r['norme'] = {'largeur': FRANCE.largeur, 'hauteur': FRANCE.hauteur,
                  'tete_min': FRANCE.tete_min, 'tete_max': FRANCE.tete_max}
    return r


def _apercu(path):
    cache = APERCUS / (path.name + '.jpg')
    if not cache.exists() or cache.stat().st_mtime < path.stat().st_mtime:
        try:
            convertir(path, cache)
        except ConversionImpossible:
            abort(415)
    return cache


@app.get('/')
def index():
    return send_file(WEB / 'index.html')


@app.get('/static/<path:name>')
def static_files(name):
    return send_from_directory(WEB, name)


@app.get('/media/<zone>/<path:name>')
def media(zone, name):
    folder = {'original': ORIGINAL, 'resultats': RESULTATS}.get(zone)
    if folder is None:
        abort(404)
    path = _safe(folder, name)
    if path.suffix.lower() not in WEB_NATIF:
        path = _apercu(path)
    resp = send_file(path, as_attachment=request.args.get('telecharger') == '1',
                     download_name=path.name)
    resp.headers['Cache-Control'] = 'no-cache'
    return resp


@app.get('/api/photos')
def api_photos():
    return jsonify([{'name': p.name, 'fait': _resultat(p.name) is not None} for p in _photos()])


@app.post('/api/photos')
def api_upload():
    f = request.files.get('photo')
    if not f or not f.filename:
        return jsonify(error='Aucun fichier reçu.'), 400
    name = secure_filename(f.filename) or 'photo.jpg'
    stem, ext = Path(name).stem, Path(name).suffix.lower()
    if ext not in FORMATS:
        return jsonify(error='Format non pris en charge. Formats acceptés : %s.'
                       % ', '.join(sorted(e.lstrip('.') for e in FORMATS))), 400
    existants = {p.stem for p in ORIGINAL.iterdir()}
    target, n = ORIGINAL / (stem + ext), 1
    while target.stem in existants:             # jamais deux originaux au même nom (résultats distincts)
        n += 1
        target = ORIGINAL / ('%s_%d%s' % (stem, n, ext))
    f.save(str(target))
    return jsonify(name=target.name)


@app.get('/api/resultat')
def api_resultat():
    photo = request.args.get('photo', '')
    _safe(ORIGINAL, photo)
    return jsonify(_resultat(photo))


@app.post('/api/fabriquer')
def api_fabriquer():
    data = request.get_json(silent=True) or {}
    photo, mode = data.get('photo', ''), data.get('couleurs', 'auto')
    fond = data.get('fond', list(FRANCE.fond))
    if mode not in couleurs.MODES:
        return jsonify(error='Réglage des couleurs inconnu.'), 400
    if (not isinstance(fond, list) or len(fond) != 3
            or not all(isinstance(c, int) and 0 <= c <= 255 for c in fond)):
        return jsonify(error='Couleur de fond invalide.'), 400
    src = _safe(ORIGINAL, photo)
    if not _verrou.acquire(blocking=False):
        return jsonify(error='Une photo est déjà en cours, patientez.'), 409
    try:
        fabriquer(src, RESULTATS, mode, Norme(fond=tuple(fond)))
    except (VisageError, ConversionImpossible, couleurs.NatifError) as e:
        return jsonify(error=str(e)), 422
    finally:
        _verrou.release()
    return jsonify(_resultat(photo))


@app.post('/api/ouvrir')
def api_ouvrir():
    """Ouvre un résultat dans Aperçu (impression à 100 %)."""
    name = (request.get_json(silent=True) or {}).get('fichier', '')
    path = _safe(RESULTATS, name)
    if path.suffix.lower() != '.jpg':
        abort(400)
    subprocess.Popen(['open', '-a', 'Preview', str(path)])
    return jsonify(ok=True)


if __name__ == '__main__':
    ORIGINAL.mkdir(parents=True, exist_ok=True)
    RESULTATS.mkdir(parents=True, exist_ok=True)
    print('Interface : http://%s:%d  (Ctrl+C pour arrêter)' % (HOST, PORT), flush=True)
    app.run(host=HOST, port=PORT, debug=False, threaded=True)

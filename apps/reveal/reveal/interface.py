#!/usr/bin/env python3
"""Interface web locale de Reveal (PhotoCraft + Python).

Lancement (depuis le dossier apps/reveal) :
    .venv/bin/python -m reveal.interface
puis ouvrir http://127.0.0.1:8765 dans le navigateur.

Le serveur n'écoute que sur la machine elle-même (127.0.0.1) : aucune photo ne sort.
Le traitement est fait par reveal.traiter (PhotoCraft piloté par Python), lancé à part.
"""

import json
import re
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

from flask import Flask, abort, jsonify, request, send_file, send_from_directory
from werkzeug.utils import secure_filename

from shared.images import ConversionImpossible, convertir
from shared.serveur import ajouter_langues, ajouter_quitter, ajouter_version, oublier, suivre

from . import config
from .config import APP, IMAGES, ORIGINAL, RETOUCHE, WEB_NATIF

WEB = Path(__file__).resolve().parent / 'web'
HOST, PORT = '127.0.0.1', 8765

# filtre de l'interface -> (type passé à traiter.py, image affichée comme « après »)
FILTRES = {
    'auto': ('auto', 'jpg'),
    'portrait': ('portrait', 'jpg'),
    'ancienne': ('ancienne', 'jpg'),
    'restauration': ('ancienne', 'restauree'),
    'ameliorer': ('ameliorer', 'jpg'),
    'studio': ('studio', 'jpg'),
    'effacer': ('effacer', 'jpg'),
}
from .effacer import EffacementError, valider as valider_zones  # noqa: E402
from .vision import FORMATS_RECADRAGE, STUDIO, STYLES  # noqa: E402
_COULEUR = re.compile(r'^\d{1,3},\d{1,3},\d{1,3}$')

app = Flask(__name__, static_folder=None)
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024
ajouter_quitter(app)        # bouton « Quitter » : arrête les traitements (modèles en mémoire) et le serveur
ajouter_version(app, 'reveal.interface', Path(__file__).resolve().parent)   # page récente, serveur ancien : redémarrer
ajouter_langues(app, WEB / 'ar.json')   # interface en arabe : catalogue de l'application

_jobs = {}
_lock = threading.Lock()
_current = {'id': None}
_ansi = re.compile(r'\x1b\[[0-9;]*m')


# ---------- utilitaires ----------

def _safe(folder, name):
    """Chemin d'un fichier existant dans `folder`, sans possibilité d'en sortir."""
    path = (folder / name).resolve()
    if path.parent != folder.resolve() or not path.is_file():
        abort(404)
    return path


def _photos():
    return sorted((p for p in ORIGINAL.iterdir() if p.suffix.lower() in IMAGES and not p.name.startswith('.')),
                  key=lambda p: p.name.lower())


def _results():
    """Résultats présents dans retouche/, regroupés par série (NOM_photocraft[_n])."""
    series = {}
    for p in RETOUCHE.glob('*_photocraft*.jpg'):
        m = re.match(r'^(.*_photocraft(?:_\d+)?)(?:_(avant|restauree))?\.jpg$', p.name)
        if not m:
            continue
        base, kind = m.group(1), m.group(2) or 'jpg'
        s = series.setdefault(base, {'base': base, 'date': 0})
        s[kind] = p.name
        s['date'] = max(s['date'], p.stat().st_mtime)
        psd = RETOUCHE / (base + '.psd')
        if psd.exists():
            s['psd'] = psd.name
    out = [s for s in series.values() if 'jpg' in s]
    for s in out:
        s['photo'] = re.sub(r'_photocraft(?:_\d+)?$', '', s['base'])
    return sorted(out, key=lambda s: -s['date'])


# ---------- pages et fichiers ----------

@app.get('/')
def index():
    return send_file(WEB / 'index.html')


@app.get('/static/<path:name>')
def static_files(name):
    return send_from_directory(WEB, name)


@app.get('/media/<zone>/<path:name>')
def media(zone, name):
    folder = {'original': ORIGINAL, 'retouche': RETOUCHE}.get(zone)
    if folder is None:
        abort(404)
    path = _safe(folder, name)
    if path.suffix.lower() not in WEB_NATIF:
        path = _apercu(path)                    # AVIF, HEIC, TIFF… : aperçu JPEG pour le navigateur
    resp = send_file(path)
    resp.headers['Cache-Control'] = 'no-cache'
    return resp


def _apercu(path):
    """Aperçu JPEG (mis en cache) d'une image que le navigateur ne sait pas afficher."""
    cache = config.APERCUS / (path.name + '.jpg')
    if not cache.exists() or cache.stat().st_mtime < path.stat().st_mtime:
        try:
            convertir(path, cache)
        except ConversionImpossible:
            abort(415)
    return cache


# ---------- API ----------

@app.get('/api/photos')
def api_photos():
    return jsonify([{'name': p.name, 'url': '/media/original/' + p.name} for p in _photos()])


@app.post('/api/photos')
def api_upload():
    f = request.files.get('photo')
    if not f or not f.filename:
        return jsonify(error='Aucun fichier reçu.'), 400
    name = secure_filename(f.filename) or 'photo.jpg'
    stem, ext = Path(name).stem, Path(name).suffix.lower()
    if ext not in IMAGES:
        return jsonify(error='Format non pris en charge. Formats acceptés : %s.'
                       % ', '.join(sorted(e.lstrip('.') for e in IMAGES))), 400
    target, n = ORIGINAL / (stem + ext), 1
    while target.exists():                      # ne jamais remplacer un original
        n += 1
        target = ORIGINAL / ('%s_%d%s' % (stem, n, ext))
    f.save(str(target))
    return jsonify(name=target.name, url='/media/original/' + target.name)


@app.get('/api/styles')
def api_styles():
    return jsonify([{'id': k, 'nom': v} for k, v in STYLES.items()])


@app.get('/api/studio')
def api_studio():
    return jsonify({'effets': [{'id': k, 'nom': v[1]} for k, v in STUDIO.items()],
                    'formats': list(FORMATS_RECADRAGE)})


@app.get('/api/resultats')
def api_results():
    return jsonify(_results())


@app.post('/api/traiter')
def api_traiter():
    data = request.get_json(silent=True) or {}
    photo, filtre, style = data.get('photo', ''), data.get('filtre', 'auto'), data.get('style') or None
    opts = {'effet': data.get('effet') or 'fond-flou', 'couleur': data.get('couleur') or '255,255,255',
            'format': data.get('format') or '4:5'}
    if filtre not in FILTRES:
        return jsonify(error='Filtre inconnu.'), 400
    if style and style not in STYLES:
        return jsonify(error='Rendu inconnu.'), 400
    if filtre == 'studio' and (opts['effet'] not in STUDIO or opts['format'] not in FORMATS_RECADRAGE
                               or not _COULEUR.match(opts['couleur'])
                               or any(int(v) > 255 for v in opts['couleur'].split(','))):
        return jsonify(error='Réglage du filtre Studio invalide.'), 400
    if filtre == 'effacer':
        try:
            opts['zones'] = valider_zones(data.get('zones'))
        except (EffacementError, TypeError, ValueError) as e:
            return jsonify(error='Zones à effacer invalides : %s' % e), 400
    src = _safe(ORIGINAL, photo)
    with _lock:
        if _current['id'] and _jobs[_current['id']]['etat'] == 'en cours':
            return jsonify(error='Un traitement est déjà en cours, patientez.'), 409
        job_id = uuid.uuid4().hex[:10]
        _jobs[job_id] = {'id': job_id, 'photo': photo, 'filtre': filtre, 'etat': 'en cours',
                         'journal': [], 'resultat': None, 'debut': time.time()}
        _current['id'] = job_id
    threading.Thread(target=_run, args=(job_id, src, filtre, style, opts), daemon=True).start()
    return jsonify(id=job_id)


@app.get('/api/jobs/<job_id>')
def api_job(job_id):
    job = _jobs.get(job_id)
    if not job:
        abort(404)
    return jsonify(dict(job, ecoule=round(time.time() - job['debut'])))


@app.post('/api/ouvrir')
def api_open():
    name = (request.get_json(silent=True) or {}).get('fichier', '')
    path = _safe(RETOUCHE, name)
    if path.suffix.lower() != '.psd':
        abort(400)
    subprocess.Popen(['open', '-a', 'PhotoCraft', str(path)])
    return jsonify(ok=True)


def _run(job_id, src, filtre, style=None, opts=None):
    job = _jobs[job_id]
    kind, shown = FILTRES[filtre]
    cmd = [sys.executable, '-m', 'reveal.traiter', '--type', kind, str(src)]
    if style and kind == 'ameliorer':
        cmd += ['--style', style]
    if kind == 'studio':
        cmd += ['--effet', opts['effet'], '--couleur', opts['couleur'], '--format', opts['format']]
        if opts['effet'] == 'detourage':
            shown = 'detoure'
    if kind == 'effacer':
        cmd += ['--zones', json.dumps(opts['zones'])]
    try:
        proc = suivre(subprocess.Popen(cmd, cwd=str(APP), stdout=subprocess.PIPE,
                                       stderr=subprocess.STDOUT, text=True, bufsize=1))
        for raw in proc.stdout:
            line = _ansi.sub('', raw).rstrip()
            if line.startswith('RESULTAT '):
                res = json.loads(line[len('RESULTAT '):])
                res['apres'] = res.get(shown) or res.get('jpg')
                job['resultat'] = res
            elif line.strip() and not line.startswith(('libpng', '20')) and 'onnxruntime' not in line:
                job['journal'].append(line.strip())
        proc.wait()
        oublier(proc)
        job['etat'] = 'termine' if job['resultat'] else 'erreur'
        if not job['resultat'] and not any('ERREUR' in l for l in job['journal']):
            job['journal'].append('ERREUR : le traitement n\'a pas produit de résultat.')
    except Exception as e:                       # le serveur ne doit jamais tomber
        job['journal'].append('ERREUR : %s' % e)
        job['etat'] = 'erreur'


if __name__ == '__main__':
    ORIGINAL.mkdir(parents=True, exist_ok=True)
    RETOUCHE.mkdir(parents=True, exist_ok=True)
    print('Interface : http://%s:%d  (Ctrl+C pour arrêter)' % (HOST, PORT), flush=True)
    app.run(host=HOST, port=PORT, debug=False, threaded=True)

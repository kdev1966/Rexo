#!/usr/bin/env python3
"""Interface web locale de Reveal (PhotoCraft + Python).

Lancement (depuis le dossier apps/reveal) :
    .venv/bin/python -m reveal.interface
puis ouvrir http://127.0.0.1:8765 dans le navigateur.

Le serveur n'écoute que sur la machine elle-même (127.0.0.1) : aucune photo ne sort.
Le traitement est fait par reveal.traiter (PhotoCraft piloté par Python), lancé à part.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

from flask import abort, jsonify, request, send_file
from werkzeug.utils import secure_filename

from shared.images import ConversionImpossible
from shared import photocraft
from shared.serveur import a_l_arret, creer_app, envoyer_image, fichier_sur, lancer, oublier, suivre

from . import config
from .config import APP, IMAGES, ORIGINAL, RETOUCHE, TRAVAIL

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

# Application commune au hub : pages, Quitter (arrête aussi les traitements), version, arabe
app = creer_app('reveal.interface', Path(__file__).resolve().parent)
# un traitement arrêté de force (Windows) n'efface pas son dossier de travail : le serveur s'en charge
a_l_arret(lambda: shutil.rmtree(TRAVAIL, ignore_errors=True))

_jobs = {}
_lock = threading.Lock()
_current = {'id': None}
_ansi = re.compile(r'\x1b\[[0-9;]*m')


# ---------- utilitaires ----------

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

@app.get('/media/<zone>/<path:name>')
def media(zone, name):
    folder = {'original': ORIGINAL, 'retouche': RETOUCHE}.get(zone)
    if folder is None:
        abort(404)
    return envoyer_image(fichier_sur(folder, name), config.APERCUS)   # AVIF, HEIC… : aperçu JPEG


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
    return jsonify({'effets': [{'id': k, 'nom': v} for k, v in STUDIO.items()],
                    'formats': list(FORMATS_RECADRAGE)})


@app.get('/api/resultats')
def api_results():
    return jsonify(_results())


@app.post('/api/traiter')
def api_traiter():
    data = request.get_json(silent=True) or {}
    photo, filtre, style = data.get('photo', ''), data.get('filtre', 'auto'), data.get('style') or None
    opts = {'effet': data.get('effet') or 'fond-flou', 'couleur': data.get('couleur') or '255,255,255',
            'format': data.get('format') or '4:5', 'fond_uni': data.get('fond_uni') is True}
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
    src = fichier_sur(ORIGINAL, photo)
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
    path = fichier_sur(RETOUCHE, name)
    if path.suffix.lower() != '.psd':
        abort(400)
    photocraft.ouvrir(path)
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
    if kind == 'ancienne' and opts.get('fond_uni'):
        cmd += ['--fond-uni']
    try:
        # UTF-8 des deux côtés (sous Windows, la console serait en cp1252)
        proc = suivre(subprocess.Popen(
            cmd, cwd=str(APP), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1,
            encoding='utf-8', errors='replace', env=dict(os.environ, PYTHONIOENCODING='utf-8')))
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
    lancer(app, HOST, PORT)

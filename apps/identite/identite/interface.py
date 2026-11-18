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

from . import archive, couleurs
from .base import LIENS, BaseError
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


# ---------- liste de travail : suppression ----------

@app.delete('/api/photos/<path:name>')
def api_retirer(name):
    """Met à la Corbeille un portrait de la liste de travail, ses planches et son rapport."""
    _safe(ORIGINAL, name)
    if not _verrou.acquire(blocking=False):
        return jsonify(error='Une photo est en cours de fabrication, patientez.'), 409
    try:
        retires = archive.retirer_du_travail(name, APERCUS)
    except archive.ArchiveError as e:
        return jsonify(error=str(e)), 404
    finally:
        _verrou.release()
    return jsonify(ok=True, corbeille=len(retires))


# ---------- archive des clients ----------

def _json():
    d = request.get_json(silent=True)
    if not isinstance(d, dict):
        abort(415)
    return d


def _erreurs(f):
    """Erreurs de saisie (BaseError) et d'archive -> 400 avec un message lisible."""
    from functools import wraps

    @wraps(f)
    def g(*a, **k):
        try:
            return f(*a, **k)
        except (BaseError, archive.ArchiveError) as e:
            return jsonify(error=str(e)), 400
    return g


@app.get('/api/archive')
def api_archive():
    return jsonify(dossier=str(archive.dossier_archive()), liens=list(LIENS))


@app.post('/api/archive/choisir')
@_erreurs
def api_archive_choisir():
    """Sélecteur de dossiers du Mac (osascript), puis retient le dossier choisi."""
    depart = archive.dossier_archive()
    script = ('POSIX path of (choose folder with prompt "Dossier de l\'archive des clients" '
              'default location (POSIX file "%s"))' % str(depart if depart.exists() else Path.home())
              .replace('"', ''))
    r = subprocess.run(['osascript', '-e', script], capture_output=True, text=True, timeout=600)
    if r.returncode != 0:                       # annulé
        return jsonify(annule=True, dossier=str(depart))
    return jsonify(dossier=str(archive.choisir_archive(r.stdout.strip())))


@app.post('/api/archive/ouvrir')
@_erreurs
def api_archive_ouvrir():
    """Montre dans le Finder le dossier de l'archive, d'un client ou d'une photo."""
    d = _json()
    b = archive.base()
    if d.get('photo_id'):
        p = b.photo(int(d['photo_id']))
        if not p:
            abort(404)
        cible = Path(p['dossier'])
    else:
        cible = archive.dossier_archive()
        cible.mkdir(parents=True, exist_ok=True)
    subprocess.Popen(['open', str(cible)])
    return jsonify(ok=True)


@app.get('/api/clients')
def api_clients():
    return jsonify(archive.base().chercher(request.args.get('q', '')))


@app.post('/api/clients')
@_erreurs
def api_client_creer():
    d = _json()
    b = archive.base()
    cid = b.creer_client(str(d.get('nom', '')), str(d.get('prenom', '')), str(d.get('telephone', '')))
    return jsonify(b.client(cid))


@app.get('/api/clients/<int:client_id>')
def api_client(client_id):
    fiche = archive.base().client(client_id)
    if fiche is None:
        abort(404)
    for p in fiche['photos']:
        p['present'] = Path(p['dossier']).is_dir()
        p.pop('dossier')                        # le navigateur n'a pas besoin des chemins
    return jsonify(fiche)


@app.put('/api/clients/<int:client_id>')
@_erreurs
def api_client_modifier(client_id):
    d = _json()
    b = archive.base()
    b.modifier_client(client_id, str(d.get('nom', '')), str(d.get('prenom', '')), str(d.get('telephone', '')))
    return jsonify(b.client(client_id))


@app.delete('/api/clients/<int:client_id>')
@_erreurs
def api_client_supprimer(client_id):
    archive.supprimer_client_archive(client_id)
    return jsonify(ok=True)


@app.post('/api/enregistrer')
@_erreurs
def api_enregistrer():
    """Archive la photo d'identité d'un portrait pour un client (existant ou nouveau)."""
    d = _json()
    photo = str(d.get('photo', ''))
    _safe(ORIGINAL, photo)
    if _resultat(photo) is None:                # avant de créer une fiche qui resterait vide
        raise archive.ArchiveError('fabriquer d\'abord les photos de ce portrait')
    b = archive.base()
    if d.get('client_id'):
        client_id = int(d['client_id'])
    else:
        c = d.get('client') or {}
        client_id = b.creer_client(str(c.get('nom', '')), str(c.get('prenom', '')), str(c.get('telephone', '')))
    fiche = b.client(client_id)
    if fiche is None:
        raise BaseError('client inconnu')
    lien = str(d.get('lien', 'lui-même'))
    if lien == 'lui-même':
        nom, prenom = fiche['nom'], fiche['prenom']
    else:
        nom, prenom = str(d.get('nom', '')).strip(), str(d.get('prenom', '')).strip()
        nom = nom or fiche['nom']               # un enfant porte souvent le nom du client
    if not _verrou.acquire(blocking=False):
        return jsonify(error='Une photo est en cours de fabrication, patientez.'), 409
    try:
        photo_id = archive.enregistrer(photo, client_id, nom, prenom, lien)
        retire = bool(d.get('retirer')) and bool(archive.retirer_du_travail(photo, APERCUS))
    finally:
        _verrou.release()
    return jsonify(ok=True, client_id=client_id, photo_id=photo_id, retire=retire)


@app.get('/archive/<int:photo_id>/<nature>')
def archive_fichier(photo_id, nature):
    """Fichier d'une photo archivée, désigné par la base seulement (jamais par un chemin)."""
    p = archive.base().photo(photo_id)
    if p is None or nature not in archive.FICHIERS:
        abort(404)
    f = archive.fichier_archive(p, nature)
    if not f.is_file():
        abort(404)
    resp = send_file(f, as_attachment=request.args.get('telecharger') == '1',
                     download_name='%s.jpg' % nature)
    resp.headers['Cache-Control'] = 'no-cache'
    return resp


@app.delete('/api/archive/photos/<int:photo_id>')
@_erreurs
def api_archive_photo_supprimer(photo_id):
    archive.supprimer_photo_archive(photo_id)
    return jsonify(ok=True)


if __name__ == '__main__':
    ORIGINAL.mkdir(parents=True, exist_ok=True)
    RESULTATS.mkdir(parents=True, exist_ok=True)
    print('Interface : http://%s:%d  (Ctrl+C pour arrêter)' % (HOST, PORT), flush=True)
    app.run(host=HOST, port=PORT, debug=False, threaded=True)

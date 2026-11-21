#!/usr/bin/env python3
"""Interface web locale de Rexo ID.

Lancement (depuis le dossier apps/identite) :
    .venv/bin/python -m identite.interface
puis ouvrir http://127.0.0.1:8766 dans le navigateur.

Le serveur n'écoute que sur la machine elle-même (127.0.0.1) : aucune photo ne sort.
"""

import json
import threading
from pathlib import Path

from flask import abort, jsonify, request, send_file
from werkzeug.utils import secure_filename

from shared import systeme
from shared.images import ConversionImpossible, FORMATS
from shared.serveur import corps_json, creer_app, envoyer_image, erreurs_lisibles, fichier_sur, lancer

from . import archive, couleurs
from .base import LIENS, BaseError, formater_tel
from .config import DONNEES, ORIGINAL, RESULTATS
from .fabriquer import fabriquer
from .normes import FRANCE, Norme
from .visage import VisageError

APERCUS = DONNEES / '.apercus'          # aperçus JPEG des formats que le navigateur n'affiche pas
HOST, PORT = '127.0.0.1', 8766
FICHIERS = ('identite', 'planche_8', 'planche_4_portrait')

# Application commune au hub : pages, Quitter, version, arabe (shared/serveur)
app = creer_app('identite.interface', Path(__file__).resolve().parent)
_verrou = threading.Lock()


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


@app.get('/media/<zone>/<path:name>')
def media(zone, name):
    folder = {'original': ORIGINAL, 'resultats': RESULTATS}.get(zone)
    if folder is None:
        abort(404)
    return envoyer_image(fichier_sur(folder, name), APERCUS, telecharger=request.args.get('telecharger') == '1')


@app.get('/api/photos')
def api_photos():
    fiches = archive.base().travaux()
    return jsonify([{'name': p.name, 'fait': _resultat(p.name) is not None, 'fiche': fiches.get(p.name)}
                    for p in _photos()])


def _lire_fiche(d):
    """Vérifie les données client d'un portrait, sans rien créer : renvoie un plan
    (client_id ou nouveau client, personne photographiée). Lève BaseError."""
    if not isinstance(d, dict):
        raise BaseError('données du client manquantes')
    b = archive.base()
    lien = str(d.get('lien', 'lui-même'))
    if lien not in LIENS:
        raise BaseError('personne photographiée : lien inconnu')
    if d.get('client_id'):
        client = b.client(int(d['client_id']))
        if client is None:
            raise BaseError('client inconnu')
        nouveau = None
    else:
        c = d.get('client') if isinstance(d.get('client'), dict) else {}
        nouveau = {k: ' '.join(str(c.get(k, '')).split()) for k in ('nom', 'prenom', 'telephone')}
        manque = [lib for k, lib in (('nom', 'le nom'), ('prenom', 'le prénom'), ('telephone', 'le téléphone'))
                  if not nouveau[k]]
        if manque:
            raise BaseError('nouveau client : saisir %s' % ', '.join(manque))
        nouveau['telephone'] = formater_tel(nouveau['telephone'])     # refusé ici s'il est invalide
        client = nouveau
    if lien == 'lui-même':
        nom, prenom = client['nom'], client['prenom']
    else:
        prenom = ' '.join(str(d.get('prenom', '')).split())
        nom = ' '.join(str(d.get('nom', '')).split()) or client['nom']   # un enfant porte souvent ce nom
        if not prenom:
            raise BaseError('prénom de la personne photographiée obligatoire')
    return {'client_id': None if nouveau else client['id'], 'nouveau': nouveau,
            'nom': nom, 'prenom': prenom, 'lien': lien}


def _appliquer_fiche(plan, fichier):
    b = archive.base()
    client_id = plan['client_id']
    if plan['nouveau']:
        n = plan['nouveau']
        client_id = b.creer_client(n['nom'], n['prenom'], n['telephone'])
    b.lier_travail(fichier, client_id, plan['nom'], plan['prenom'], plan['lien'])
    return b.travail(fichier)


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
    try:                                        # client obligatoire, vérifié avant tout enregistrement
        plan = _lire_fiche(json.loads(request.form.get('fiche') or 'null'))
    except ValueError as e:                     # BaseError en est une
        return jsonify(error=str(e) if isinstance(e, BaseError) else 'données du client illisibles'), 400
    existants = {p.stem for p in ORIGINAL.iterdir()}
    target, n = ORIGINAL / (stem + ext), 1
    while target.stem in existants:             # jamais deux originaux au même nom (résultats distincts)
        n += 1
        target = ORIGINAL / ('%s_%d%s' % (stem, n, ext))
    f.save(str(target))
    try:
        fiche = _appliquer_fiche(plan, target.name)
    except Exception as e:
        target.unlink()                         # pas de portrait sans client
        if isinstance(e, BaseError):
            return jsonify(error=str(e)), 400
        raise
    return jsonify(name=target.name, fiche=fiche)


@app.put('/api/travail/<path:name>')
def api_travail(name):
    """Renseigne ou modifie le client d'un portrait de la liste de travail."""
    fichier_sur(ORIGINAL, name)
    try:
        plan = _lire_fiche(request.get_json(silent=True))
        return jsonify(fiche=_appliquer_fiche(plan, name))
    except ValueError as e:                     # BaseError en est une
        return jsonify(error=str(e) if isinstance(e, BaseError) else 'données du client illisibles'), 400


@app.get('/api/resultat')
def api_resultat():
    photo = request.args.get('photo', '')
    fichier_sur(ORIGINAL, photo)
    return jsonify(_resultat(photo))


@app.post('/api/fabriquer')
def api_fabriquer():
    data = request.get_json(silent=True) or {}
    photo, mode = data.get('photo', ''), data.get('couleurs', 'auto')
    fond = data.get('fond', list(FRANCE.fond))
    mode = couleurs.ALIAS.get(mode, mode)
    if mode not in couleurs.MODES:
        return jsonify(error='Réglage des couleurs inconnu.'), 400
    if (not isinstance(fond, list) or len(fond) != 3
            or not all(isinstance(c, int) and 0 <= c <= 255 for c in fond)):
        return jsonify(error='Couleur de fond invalide.'), 400
    src = fichier_sur(ORIGINAL, photo)
    if archive.base().travail(photo) is None:
        return jsonify(error='Renseigner d\'abord le client de ce portrait.'), 409
    if not _verrou.acquire(blocking=False):
        return jsonify(error='Une photo est déjà en cours, patientez.'), 409
    try:
        fabriquer(src, RESULTATS, mode, Norme(fond=tuple(fond)))
    except (VisageError, ConversionImpossible) as e:
        return jsonify(error=str(e)), 422
    finally:
        _verrou.release()
    return jsonify(_resultat(photo))


@app.post('/api/ouvrir')
def api_ouvrir():
    """Ouvre un résultat dans Aperçu (macOS) ou la visionneuse de Windows."""
    name = (request.get_json(silent=True) or {}).get('fichier', '')
    path = fichier_sur(RESULTATS, name)
    if path.suffix.lower() != '.jpg':
        abort(400)
    systeme.ouvrir(path, appli='Preview')
    return jsonify(ok=True)


# ---------- liste de travail : suppression ----------

@app.delete('/api/photos/<path:name>')
def api_retirer(name):
    """Met à la Corbeille un portrait de la liste de travail, ses planches et son rapport."""
    fichier_sur(ORIGINAL, name)
    if not _verrou.acquire(blocking=False):
        return jsonify(error='Une photo est en cours de fabrication, patientez.'), 409
    try:
        retires = archive.retirer_du_travail(name, APERCUS)
        archive.base().delier_travail(name)
    except archive.ArchiveError as e:
        return jsonify(error=str(e)), 404
    finally:
        _verrou.release()
    return jsonify(ok=True, corbeille=len(retires))


# ---------- archive des clients ----------

# Erreurs de saisie (BaseError) et d'archive : 400 avec un message lisible
_erreurs = erreurs_lisibles(BaseError, archive.ArchiveError)


@app.get('/api/archive')
def api_archive():
    return jsonify(dossier=str(archive.dossier_archive()), liens=list(LIENS))


@app.post('/api/archive/choisir')
@_erreurs
def api_archive_choisir():
    """Fenêtre de choix d'un dossier du système, puis retient le dossier choisi."""
    depart = archive.dossier_archive()
    choisi = systeme.choisir_dossier("Dossier de l'archive des clients", depart)
    if choisi is None:                          # annulé
        return jsonify(annule=True, dossier=str(depart))
    return jsonify(dossier=str(archive.choisir_archive(choisi)))


@app.post('/api/archive/ouvrir')
@_erreurs
def api_archive_ouvrir():
    """Montre dans le Finder ou l'Explorateur le dossier de l'archive, d'un client ou d'une photo."""
    d = corps_json()
    b = archive.base()
    if d.get('photo_id'):
        p = b.photo(int(d['photo_id']))
        if not p:
            abort(404)
        cible = Path(p['dossier'])
    else:
        cible = archive.dossier_archive()
        cible.mkdir(parents=True, exist_ok=True)
    systeme.montrer(cible)
    return jsonify(ok=True)


@app.get('/api/clients')
def api_clients():
    return jsonify(archive.base().chercher(request.args.get('q', '')))


@app.post('/api/clients')
@_erreurs
def api_client_creer():
    d = corps_json()
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
    d = corps_json()
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
    """Archive la photo d'identité d'un portrait pour le client saisi au dépôt."""
    d = corps_json()
    photo = str(d.get('photo', ''))
    fichier_sur(ORIGINAL, photo)
    fiche = archive.base().travail(photo)
    if fiche is None:
        raise BaseError('renseigner d\'abord le client de ce portrait')
    if _resultat(photo) is None:
        raise archive.ArchiveError('fabriquer d\'abord les photos de ce portrait')
    if not _verrou.acquire(blocking=False):
        return jsonify(error='Une photo est en cours de fabrication, patientez.'), 409
    try:
        photo_id = archive.enregistrer(photo, fiche['client_id'], fiche['nom'], fiche['prenom'], fiche['lien'])
        retire = bool(d.get('retirer')) and bool(archive.retirer_du_travail(photo, APERCUS))
        if retire:
            archive.base().delier_travail(photo)
    finally:
        _verrou.release()
    return jsonify(ok=True, client_id=fiche['client_id'], photo_id=photo_id, retire=retire)


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
    lancer(app, HOST, PORT)

#!/usr/bin/env python3
"""Interface web locale de Rexo Dock.

Lancement (depuis le dossier apps/dock) :
    .venv/bin/python -m dock.interface
puis ouvrir http://127.0.0.1:8767 dans le navigateur.

Le serveur n'écoute que sur la machine elle-même (127.0.0.1) : aucune photo ne sort.
Le fil principal fait tourner l'accès à l'appareil (ImageCaptureCore sous macOS) ; le serveur
web tourne dans un autre fil, et l'import dans un troisième, pour que la page suive la
progression. Rien n'est jamais supprimé de l'appareil.
"""

import threading
import time
from pathlib import Path

from flask import Flask, Response, abort, jsonify, request, send_from_directory

from shared import systeme
from shared.serveur import ajouter_langues, ajouter_quitter, ajouter_version, lancer

from . import coeur, config
from .importer import ErreurAppareil, PlaceInsuffisante, importer

WEB = Path(__file__).resolve().parent / 'web'
HOST, PORT = '127.0.0.1', 8767
MAX_VIGNETTES = 20000            # vignettes gardées en mémoire (environ 10 Ko chacune)

app = Flask(__name__, static_folder=None)
ajouter_quitter(app)
ajouter_version(app, 'dock.interface', Path(__file__).resolve().parent)
ajouter_langues(app, WEB / 'ar.json')

pilote = None                    # AppareilsMac sous macOS ; None si le système n'est pas encore pris en charge
registre = coeur.Registre(config.REGISTRE)
_verrou = threading.Lock()       # registre et état de l'import
_vignettes = {}
_import = {'en_cours': False, 'fait': 0, 'total': 0, 'courant': '', 'etape': '',
           'resultat': None, 'erreur': None, 'numero': 0}


def _erreurs(fn):
    from functools import wraps

    @wraps(fn)
    def enveloppe(*a, **k):
        try:
            return fn(*a, **k)
        except (ErreurAppareil, PlaceInsuffisante, config.ReglageError, OSError) as e:
            return jsonify(error=str(e)), 400
    return enveloppe


def _etat_appareil():
    if pilote is None:
        return {'etat': 'indisponible', 'nom': '', 'identifiant': ''}
    return pilote.etat()


def _entrees():
    """Catalogue de l'appareil branché, avec l'état « déjà importé » du registre."""
    if pilote is None:
        return []
    with _verrou:
        return coeur.catalogue(pilote.fichiers(), registre, pilote.identifiant)


def _miroir_present(m):
    """Le disque de seconde copie est-il branché ? (son dossier ou, à défaut, son parent)"""
    return m is not None and (m.exists() or m.parent.exists())


# ---------- pages ----------

@app.get('/')
def index():
    r = send_from_directory(WEB, 'index.html')
    r.headers['Cache-Control'] = 'no-cache'
    return r


@app.get('/static/<path:nom>')
def statique(nom):
    r = send_from_directory(WEB, nom)
    r.headers['Cache-Control'] = 'no-cache'
    return r


# ---------- état et catalogue ----------

@app.get('/api/etat')
def api_etat():
    appareil = _etat_appareil()
    nb = len(pilote.fichiers()) if pilote is not None else 0
    with _verrou:
        imp = dict(_import)
        importes = len(registre.entrees.get(appareil['identifiant'], ()))
    m = config.dossier_miroir()
    return jsonify(appareil={'etat': appareil['etat'], 'nom': appareil['nom']},
                   signature='%s|%s|%d|%d' % (appareil['etat'], appareil['identifiant'], nb, importes),
                   import_=imp,
                   seances=str(config.dossier_seances()),
                   miroir=str(m) if m else None,
                   miroir_present=_miroir_present(m))


@app.get('/api/catalogue')
def api_catalogue():
    sortie = []
    for e in _entrees():
        f = e.fichier
        sortie.append({'cle': e.cle, 'nom': f.nom, 'genre': e.genre, 'taille': f.taille,
                       'date': f.date.isoformat() if f.date else None,
                       'duree': f.duree, 'rafale': f.rafale, 'importe': e.importe,
                       'retouches': len(e.retouches)})
    return jsonify(sortie)


@app.get('/vignette')
def vignette():
    cle = request.args.get('cle', '')
    donnees = _vignettes.get(cle)
    if donnees is None:
        if pilote is None:
            abort(404)
        f = next((x for x in pilote.fichiers() if x.cle == cle), None)
        if f is None:
            abort(404)
        try:
            donnees = pilote.vignette(f)
        except ErreurAppareil:
            abort(404)
        if len(_vignettes) < MAX_VIGNETTES:
            _vignettes[cle] = donnees
    r = Response(donnees, mimetype='image/jpeg')
    r.headers['Cache-Control'] = 'private, max-age=86400'
    return r


@app.post('/api/actualiser')
@_erreurs
def api_actualiser():
    if pilote is not None:
        pilote.actualiser()
    return jsonify(ok=True)


# ---------- import ----------

def _choix(cles):
    voulues = set(cles or ())
    return [e for e in _entrees() if e.cle in voulues]


def _travail(entrees, nom_seance):
    def progression(fait, total, nom):
        with _verrou:
            _import.update(fait=fait, total=total, courant=nom)

    resultat, erreur = None, None
    try:
        r = importer(pilote, entrees, config.dossier_seances(creer=True), registre, nom_seance,
                     progression=progression)
        resultat = {'dossier': str(r.dossier), 'nom_dossier': r.dossier.name, 'importes': r.importes,
                    'total': r.total, 'echecs': [{'nom': n, 'raison': x} for n, x in r.echecs],
                    'miroir': None}
        m = config.dossier_miroir()
        if r.importes and m is not None:
            with _verrou:
                _import.update(etape='miroir', courant='')
            if _miroir_present(m):
                mr = coeur.miroir(config.dossier_seances(), m,
                                  progression=lambda rel: _import.update(courant=rel))
                resultat['miroir'] = {'copies': mr.copies, 'deja_la': mr.deja_la, 'echecs': mr.echecs}
            else:
                resultat['miroir'] = {'absent': True}
    except (PlaceInsuffisante, ErreurAppareil, OSError) as e:
        erreur = str(e)
    with _verrou:
        _import.update(en_cours=False, etape='', courant='', resultat=resultat, erreur=erreur)


@app.post('/api/importer')
@_erreurs
def api_importer():
    d = request.get_json(force=True, silent=True) or {}
    if _etat_appareil()['etat'] != 'pret':
        return jsonify(error='Aucun appareil prêt.'), 409
    entrees = _choix(d.get('cles'))
    if not entrees:
        return jsonify(error='Aucune photo choisie.'), 400
    with _verrou:
        if _import['en_cours']:
            return jsonify(error='Un import est déjà en cours.'), 409
        _import.update(en_cours=True, fait=0, total=len(coeur.fichiers_a_copier(entrees)), courant='',
                       etape='copie', resultat=None, erreur=None, numero=_import['numero'] + 1)
    threading.Thread(target=_travail, args=(entrees, str(d.get('seance') or '')), daemon=True).start()
    return jsonify(ok=True)


@app.post('/api/marquer')
@_erreurs
def api_marquer():
    """Marque la sélection comme déjà importée, sans la copier (copiée auparavant autrement)."""
    d = request.get_json(force=True, silent=True) or {}
    entrees = _choix(d.get('cles'))
    if not entrees:
        return jsonify(error='Aucune photo choisie.'), 400
    with _verrou:
        registre.enregistrer_tous(coeur.fichiers_a_copier(entrees), pilote.identifiant)
    return jsonify(ok=True, marques=len(entrees))


# ---------- dossiers ----------

@app.post('/api/seances/choisir')
@_erreurs
def api_seances_choisir():
    p = systeme.choisir_dossier('Dossier où ranger les séances', config.dossier_seances())
    if p is None:
        return jsonify(ok=False)
    return jsonify(ok=True, seances=str(config.choisir_seances(p)))


@app.post('/api/miroir/choisir')
@_erreurs
def api_miroir_choisir():
    m = config.dossier_miroir()
    p = systeme.choisir_dossier('Dossier de seconde copie (disque externe)', m or Path('/Volumes'))
    if p is None:
        return jsonify(ok=False)
    return jsonify(ok=True, miroir=str(config.choisir_miroir(p)))


@app.post('/api/miroir/retirer')
@_erreurs
def api_miroir_retirer():
    config.choisir_miroir(None)
    return jsonify(ok=True)


@app.post('/api/montrer')
@_erreurs
def api_montrer():
    """Ouvre dans le Finder (ou l'Explorateur) le dossier d'une séance, ou celui des séances."""
    d = request.get_json(force=True, silent=True) or {}
    racine = config.dossier_seances(creer=True).resolve()
    cible = racine
    if d.get('seance'):
        cible = (racine / str(d['seance'])).resolve()
        if cible.parent != racine or not cible.is_dir():
            return jsonify(error='Dossier introuvable.'), 404
    systeme.montrer(cible)
    return jsonify(ok=True)


# ---------- démarrage ----------

def principal():
    global pilote
    config.dossier_seances(creer=True)          # visible sur le Bureau dès le lancement
    if systeme.MACOS:
        from .appareil_mac import AppareilsMac
        pilote = AppareilsMac().demarrer()
    threading.Thread(target=lancer, args=(app, HOST, PORT), daemon=True).start()
    try:
        if pilote is not None:
            pilote.tourner()                    # fil principal : rappels d'ImageCaptureCore
        else:
            while True:
                time.sleep(3600)
    except KeyboardInterrupt:
        pass
    finally:
        if pilote is not None:
            pilote.arreter()


if __name__ == '__main__':
    principal()

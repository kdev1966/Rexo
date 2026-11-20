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

import queue
import threading
import time
from pathlib import Path

from flask import Flask, Response, abort, jsonify, request, send_file, send_from_directory

from shared import systeme
from shared.serveur import ajouter_langues, ajouter_quitter, ajouter_version, lancer

from . import coeur, config, seances
from .importer import ErreurAppareil, PlaceInsuffisante, importer

WEB = Path(__file__).resolve().parent / 'web'
HOST, PORT = '127.0.0.1', 8767
MAX_VIGNETTES = 20000            # vignettes gardées en mémoire (environ 10 Ko chacune)
COTE_NETTE = 400                 # vignettes nettes du téléphone, tirées de l'original

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
VIGNETTES = config.DONNEES / 'vignettes'      # vignettes des séances (jamais dans le dossier du photographe)
VIGNETTES_TEL = config.DONNEES / 'vignettes-telephone'   # vignettes nettes des photos du téléphone
_verrou_nettes = threading.Lock()             # une lecture d'original à la fois (câble USB)
_a_trier = queue.Queue()                      # dossiers de séance à analyser, un à la fois
_tri = {'en_cours': False, 'seance': '', 'fait': 0, 'total': 0, 'version': 0}


def _erreurs(fn):
    from functools import wraps

    @wraps(fn)
    def enveloppe(*a, **k):
        try:
            return fn(*a, **k)
        except (ErreurAppareil, PlaceInsuffisante, config.ReglageError, seances.ActionImpossible, OSError) as e:
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
    with _verrou:
        tri_etat = dict(_tri)
    return jsonify(appareil={'etat': appareil['etat'], 'nom': appareil['nom']},
                   tri=tri_etat,
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


def _vignette_nette(f):
    """Vignette nette d'une photo ou d'une vidéo du téléphone : l'iPhone ne fournit que des
    vignettes de 120 × 160 pixels. On lit l'original dans un dossier temporaire, on le réduit
    (vidéo : image à 1 s du début), on garde la vignette en cache et on efface la copie. Le
    téléphone n'est que lu. None si impossible."""
    import hashlib
    import tempfile

    import cv2

    from shared.images import image_de_video, reduire
    cle = hashlib.sha1(('%s|%s' % (pilote.identifiant, f.cle)).encode()).hexdigest()
    chemin = VIGNETTES_TEL / cle[:2] / (cle + '.jpg')
    if chemin.is_file():
        return chemin
    with _verrou_nettes:
        if chemin.is_file():
            return chemin
        with _verrou:
            if _import['en_cours']:
                return None                     # l'import passe d'abord
        with tempfile.TemporaryDirectory(prefix='rexo-dock-') as d:
            try:
                video = coeur.genre(f.nom) == coeur.VIDEO
                copie = pilote.copier(f, d, 'original' + Path(f.nom).suffix.lower(), delai=900 if video else 120)
                img = image_de_video(copie, COTE_NETTE) if video else reduire(copie, COTE_NETTE)
            except Exception:
                return None
            chemin.parent.mkdir(parents=True, exist_ok=True)
            provisoire = chemin.with_name(chemin.name + '.partiel.jpg')
            cv2.imwrite(str(provisoire), img, [cv2.IMWRITE_JPEG_QUALITY, 85])
            provisoire.replace(chemin)
    return chemin


@app.get('/vignette')
def vignette():
    """Vignette d'un fichier du téléphone ; nette=1 : vignette nette tirée de l'original
    (photos, RAW et vidéos), 503 si elle n'est pas disponible maintenant (import en cours)."""
    cle = request.args.get('cle', '')
    if pilote is None:
        abort(404)
    if request.args.get('nette') == '1':
        f = next((x for x in pilote.fichiers() if x.cle == cle), None)
        if f is None or coeur.genre(f.nom) not in (coeur.PHOTO, coeur.RAW, coeur.VIDEO):
            abort(404)
        chemin = _vignette_nette(f)
        if chemin is None:
            abort(503)
        r = send_file(chemin, mimetype='image/jpeg')
        r.headers['Cache-Control'] = 'private, max-age=604800'
        return r
    donnees = _vignettes.get(cle)
    if donnees is None:
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


def _travail(groupes):
    """Importe chaque séance proposée (nom, entrées) dans son dossier, puis la seconde copie,
    puis met les séances en file pour l'aide au tri."""
    total = sum(len(coeur.fichiers_a_copier(e)) for _, e in groupes)
    fait_avant = [0]

    def progression(fait, _total, nom):
        with _verrou:
            _import.update(fait=fait_avant[0] + fait, total=total, courant=nom)

    resultats, erreur, dossiers = [], None, []
    try:
        racine = config.dossier_seances(creer=True)
        for nom_seance, entrees in groupes:
            r = importer(pilote, entrees, racine, registre, nom_seance, progression=progression)
            fait_avant[0] += r.total
            resultats.append({'dossier': str(r.dossier), 'nom_dossier': r.dossier.name, 'importes': r.importes,
                              'total': r.total, 'echecs': [{'nom': n, 'raison': x} for n, x in r.echecs]})
            dossiers += seances.noter_import(r.copies)
            if r.dossier not in dossiers:
                dossiers.append(r.dossier)
        miroir = None
        m = config.dossier_miroir()
        if any(x['importes'] for x in resultats) and m is not None:
            with _verrou:
                _import.update(etape='miroir', courant='')
            if _miroir_present(m):
                mr = coeur.miroir(racine, m, progression=lambda rel: _import.update(courant=rel))
                miroir = {'copies': mr.copies, 'deja_la': mr.deja_la, 'echecs': mr.echecs}
            else:
                miroir = {'absent': True}
        resultat = {'seances': resultats, 'miroir': miroir,
                    'importes': sum(x['importes'] for x in resultats), 'total': total}
    except (PlaceInsuffisante, ErreurAppareil, OSError) as e:
        erreur, resultat = str(e), None
    with _verrou:
        _import.update(en_cours=False, etape='', courant='', resultat=resultat, erreur=erreur)
    for d in dossiers:
        _a_trier.put(Path(d))


@app.post('/api/importer')
@_erreurs
def api_importer():
    """Corps : {seances: [{nom, cles}]} (séances proposées, validées par le photographe),
    ou {cles, seance} (une seule séance)."""
    d = request.get_json(force=True, silent=True) or {}
    if _etat_appareil()['etat'] != 'pret':
        return jsonify(error='Aucun appareil prêt.'), 409
    demandes = d.get('seances') or [{'nom': d.get('seance') or '', 'cles': d.get('cles')}]
    groupes = [(str(s.get('nom') or ''), _choix(s.get('cles'))) for s in demandes]
    groupes = [(n, e) for n, e in groupes if e]
    if not groupes:
        return jsonify(error='Aucune photo choisie.'), 400
    with _verrou:
        if _import['en_cours']:
            return jsonify(error='Un import est déjà en cours.'), 409
        _import.update(en_cours=True, fait=0, total=sum(len(coeur.fichiers_a_copier(e)) for _, e in groupes),
                       courant='', etape='copie', resultat=None, erreur=None, numero=_import['numero'] + 1)
    threading.Thread(target=_travail, args=(groupes,), daemon=True).start()
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


# ---------- aide au tri : séances importées ----------

def _dossier(nom):
    """Dossier de séance désigné par son nom, sans possibilité de sortir du dossier des séances."""
    racine = config.dossier_seances().resolve()
    d = (racine / str(nom or '')).resolve()
    if d.parent != racine or not d.is_dir():
        abort(404)
    return d


def _trieur():
    """Fil de l'aide au tri : analyse les séances mises en file, une à la fois."""
    while True:
        dossier = _a_trier.get()
        if not dossier.is_dir():
            continue
        with _verrou:
            _tri.update(en_cours=True, seance=dossier.name, fait=0, total=0)

        def progression(fait, total, nom):
            with _verrou:
                _tri.update(fait=fait, total=total)
        try:
            seances.analyser_dossier(dossier, VIGNETTES, progression=progression)
        except Exception as e:                       # une séance en échec n'arrête pas les autres
            print('Aide au tri : %s : %s' % (dossier.name, e), flush=True)
        with _verrou:
            _tri.update(en_cours=_a_trier.qsize() > 0, seance='', fait=0, total=0, version=_tri['version'] + 1)


@app.get('/api/seances')
def api_seances():
    sortie = []
    for d in seances.lister(config.dossier_seances()):
        ps = seances.photos(d)
        sortie.append({'nom': d.name, 'photos': len(ps), 'analysees': sum(p['analysee'] for p in ps),
                       'a_trier': sum(p['a_trier'] for p in ps)})
    return jsonify(sortie)


@app.get('/api/seances/photos')
def api_seance_photos():
    d = _dossier(request.args.get('seance'))
    return jsonify(photos=[{k: p.get(k) for k in ('nom', 'date', 'analysee', 'nettete', 'visages', 'yeux_fermes',
                                                   'floue', 'doublon', 'meilleure', 'serie', 'a_trier', 'garde',
                                                   'erreur')}
                           for p in seances.photos(d)],
                   ecartees=seances.ecartees(d))


def _photo_seance():
    d = _dossier(request.args.get('seance'))
    base = d / seances.ECARTEES if request.args.get('ecartee') == '1' else d
    p = (base / str(request.args.get('nom', ''))).resolve()
    if p.parent != base.resolve() or not seances.est_photo(p):
        abort(404)
    return p


@app.get('/seance/vignette')
def seance_vignette():
    """Vignette ; avec grand=1, grande image pour la comparaison."""
    p = _photo_seance()
    try:
        v = seances.apercu(p, VIGNETTES) if request.args.get('grand') == '1' else seances.vignette(p, VIGNETTES)
    except Exception:
        abort(404)
    r = send_file(v, mimetype='image/jpeg')
    r.headers['Cache-Control'] = 'private, max-age=86400'
    return r


@app.post('/api/seances/action')
@_erreurs
def api_seance_action():
    """Actions du photographe sur des photos de séance : garder, ne_plus_garder, ecarter,
    remettre (depuis « Écartées »), corbeille (ecartees: true pour une photo écartée)."""
    corps = request.get_json(force=True, silent=True) or {}
    d = _dossier(corps.get('seance'))
    noms = [str(n) for n in corps.get('noms') or []]
    if not noms:
        return jsonify(error='Aucune photo choisie.'), 400
    action = corps.get('action')
    if action == 'garder':
        n = seances.garder(d, noms)
    elif action == 'ne_plus_garder':
        n = seances.garder(d, noms, False)
    elif action == 'ecarter':
        n = seances.ecarter(d, noms)
    elif action == 'remettre':
        n = seances.remettre(d, noms)
    elif action == 'corbeille':
        n = seances.corbeille(d, noms, ecartees=bool(corps.get('ecartees')))
    else:
        return jsonify(error='Action inconnue.'), 400
    return jsonify(ok=True, n=n)


@app.post('/api/seances/analyser')
@_erreurs
def api_seance_analyser():
    d = _dossier((request.get_json(force=True, silent=True) or {}).get('seance'))
    _a_trier.put(d)
    with _verrou:
        _tri.update(en_cours=True)
    return jsonify(ok=True)


@app.post('/api/seances/ouvrir')
@_erreurs
def api_seance_ouvrir():
    """Ouvre une photo de séance dans l'application du système (Aperçu, Photos de Windows)."""
    corps = request.get_json(force=True, silent=True) or {}
    d = _dossier(corps.get('seance'))
    base = d / seances.ECARTEES if corps.get('ecartee') else d
    p = (base / str(corps.get('nom', ''))).resolve()
    if p.parent != base.resolve() or not p.is_file():
        return jsonify(error='Photo introuvable.'), 404
    systeme.ouvrir(p)
    return jsonify(ok=True)


# ---------- démarrage ----------

def principal():
    global pilote
    racine = config.dossier_seances(creer=True)  # visible sur le Bureau dès le lancement
    threading.Thread(target=_trieur, daemon=True).start()
    for d in seances.lister(racine):            # séances pas encore (entièrement) analysées
        if seances.a_analyser(d):
            _a_trier.put(d)
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

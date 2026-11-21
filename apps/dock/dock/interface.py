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

from flask import Response, abort, jsonify, request, send_file

from shared import systeme
from shared.images import vignette
from shared.serveur import corps_json, creer_app, dossier_sur, erreurs_lisibles, fichier_sur, lancer

from . import coeur, config, personnes, seances
from .importer import ErreurAppareil, PlaceInsuffisante, importer

HOST, PORT = '127.0.0.1', 8767
MAX_VIGNETTES = 20000            # vignettes gardées en mémoire (environ 10 Ko chacune)
COTE_NETTE = 400                 # vignettes nettes du téléphone, tirées de l'original

# Application commune au hub : pages, Quitter, version, arabe (shared/serveur)
app = creer_app('dock.interface', Path(__file__).resolve().parent)

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
_tri = {'en_cours': False, 'seance': '', 'etape': '', 'fait': 0, 'total': 0, 'version': 0}


# Erreurs prévues (appareil, place, réglage, action) : 400 avec un message lisible
_erreurs = erreurs_lisibles(ErreurAppareil, PlaceInsuffisante, config.ReglageError, seances.ActionImpossible, OSError)


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
    return jsonify(appareil={'etat': appareil['etat'], 'nom': appareil['nom'],
                             'marque': appareil.get('marque', '')},
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

    from shared.images import ecrire_jpeg, image_de_video, reduire
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
            ecrire_jpeg(img, chemin)
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
    d = corps_json()
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
    d = corps_json()
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
    d = corps_json()
    racine = config.dossier_seances(creer=True)
    systeme.montrer(dossier_sur(racine, d['seance']) if d.get('seance') else racine)
    return jsonify(ok=True)


# ---------- aide au tri : séances importées ----------

def _dossier(nom):
    """Dossier de séance désigné par son nom, sans possibilité de sortir du dossier des séances."""
    return dossier_sur(config.dossier_seances(), nom)


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
            if personnes.actif(dossier):            # seulement si le photographe l'a demandé
                with _verrou:
                    _tri.update(etape='personnes', fait=0, total=0)
                personnes.calculer(dossier, progression=progression)
        except Exception as e:                       # une séance en échec n'arrête pas les autres
            print('Aide au tri : %s : %s' % (dossier.name, e), flush=True)
        with _verrou:
            _tri.update(en_cours=_a_trier.qsize() > 0, seance='', etape='', fait=0, total=0, version=_tri['version'] + 1)


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
    p = fichier_sur(base, request.args.get('nom'))
    if not seances.est_photo(p):
        abort(404)
    return p


@app.get('/seance/vignette')
def seance_vignette():
    """Vignette ; avec grand=1, grande image pour la comparaison."""
    p = _photo_seance()
    try:
        v = vignette(p, VIGNETTES, 1600, 88) if request.args.get('grand') == '1' else vignette(p, VIGNETTES, seances.COTE_VIGNETTE)
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
    corps = corps_json()
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


# ---------- regroupement par personne (données biométriques : voir dock/personnes.py) ----------

@app.get('/api/seances/personnes')
def api_seance_personnes():
    d = _dossier(request.args.get('seance'))
    if not personnes.actif(d):
        return jsonify(actif=False, a_calculer=0, personnes=[])
    return jsonify(actif=True, a_calculer=len(personnes.a_calculer(d)),
                   personnes=[{'numero': x['numero'], 'photos': x['photos']} for x in personnes.personnes(d)])


@app.get('/seance/visage')
def seance_visage():
    """Vignette du visage le plus représentatif d'une personne (calculée à la demande, gardée
    seulement par le navigateur)."""
    d = _dossier(request.args.get('seance'))
    try:
        numero = int(request.args.get('personne', ''))
    except ValueError:
        abort(404)
    x = next((p for p in personnes.personnes(d) if p['numero'] == numero), None)
    if x is None:
        abort(404)
    try:
        jpeg = personnes.visage_vignette(d, x['visage']['nom'], x['visage']['cadre'])
    except Exception:
        abort(404)
    r = Response(jpeg, mimetype='image/jpeg')
    r.headers['Cache-Control'] = 'private, no-store'
    return r


@app.post('/api/seances/personnes/activer')
@_erreurs
def api_seance_personnes_activer():
    d = _dossier(corps_json().get('seance'))
    personnes.activer(d)
    _a_trier.put(d)
    with _verrou:
        _tri.update(en_cours=True)
    return jsonify(ok=True)


@app.post('/api/seances/personnes/effacer')
@_erreurs
def api_seance_personnes_effacer():
    d = _dossier(corps_json().get('seance'))
    personnes.effacer(d)
    with _verrou:
        _tri.update(version=_tri['version'] + 1)
    return jsonify(ok=True)


@app.post('/api/seances/analyser')
@_erreurs
def api_seance_analyser():
    d = _dossier(corps_json().get('seance'))
    _a_trier.put(d)
    with _verrou:
        _tri.update(en_cours=True)
    return jsonify(ok=True)


@app.post('/api/seances/ouvrir')
@_erreurs
def api_seance_ouvrir():
    """Ouvre une photo de séance dans l'application du système (Aperçu, Photos de Windows)."""
    corps = corps_json()
    d = _dossier(corps.get('seance'))
    base = d / seances.ECARTEES if corps.get('ecartee') else d
    systeme.ouvrir(fichier_sur(base, corps.get('nom')))
    return jsonify(ok=True)


# ---------- démarrage ----------

def principal():
    global pilote
    racine = config.dossier_seances(creer=True)  # visible sur le Bureau dès le lancement
    threading.Thread(target=_trieur, daemon=True).start()
    for d in seances.lister(racine):            # séances pas encore (entièrement) analysées
        if seances.a_analyser(d) or personnes.a_calculer(d):
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

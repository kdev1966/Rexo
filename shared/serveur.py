"""Arrêt d'un serveur web local du hub depuis son interface (bouton « Quitter »).

POST /api/quitter (JSON seulement : un autre site ouvert dans le navigateur ne peut pas
l'appeler sans une requête préalable CORS, que le serveur refuse) : arrête les traitements
en cours (processus enfants enregistrés par `suivre`), ce qui libère la mémoire des modèles
d'IA, puis arrête le serveur. L'application du Dock (shared/lanceur) le voit et se ferme.

GET /api/version et POST /api/redemarrer : le code Python est lu une fois, au démarrage,
alors que la page est relue sur le disque à chaque ouverture. Après une mise à jour, la
page récente parlerait à un serveur ancien (routes absentes, 404). /api/version compare
l'empreinte du code au démarrage et maintenant ; la page propose alors de redémarrer, et
/api/redemarrer relance le serveur sur place (même processus, os.execv) : l'application
du Dock ne voit qu'une courte absence.
"""

import hashlib
import os
import sys
import threading
import time
from pathlib import Path

from flask import jsonify, request

_enfants = set()
_verrou = threading.Lock()


def suivre(proc):
    """Enregistre un processus enfant (traitement) à arrêter si l'on quitte."""
    with _verrou:
        _enfants.add(proc)
    return proc


def oublier(proc):
    with _verrou:
        _enfants.discard(proc)


def arreter_enfants(delai=3.0):
    with _verrou:
        enfants = [p for p in _enfants if p.poll() is None]
    for p in enfants:
        p.terminate()
    fin = time.time() + delai
    for p in enfants:
        try:
            p.wait(timeout=max(0.1, fin - time.time()))
        except Exception:
            p.kill()
    return len(enfants)


def ajouter_quitter(app):
    """Ajoute POST /api/quitter à l'application Flask `app`."""

    @app.post('/api/quitter')
    def api_quitter():
        if not request.is_json:
            return jsonify(error='Requête JSON attendue.'), 415
        arretes = arreter_enfants()

        def sortir():
            time.sleep(0.3)             # laisse partir la réponse
            os._exit(0)

        threading.Thread(target=sortir, daemon=True).start()
        return jsonify(ok=True, traitements_arretes=arretes)


HUB = Path(__file__).resolve().parent.parent


def empreinte(dossiers):
    """Empreinte du code Python (chemins, dates et tailles des .py) des dossiers donnés."""
    h = hashlib.sha1()
    for d in dossiers:
        for f in sorted(Path(d).rglob('*.py')):
            if '.venv' in f.parts or '__pycache__' in f.parts:
                continue
            st = f.stat()
            h.update(('%s|%d|%d\n' % (f.relative_to(HUB), st.st_mtime_ns, st.st_size)).encode())
    return h.hexdigest()[:12]


def ajouter_version(app, module, dossier_app):
    """Ajoute GET /api/version et POST /api/redemarrer. `module` : module lancé par
    « python -m » (ex. identite.interface) ; `dossier_app` : dossier du code de l'application."""
    dossiers = [Path(dossier_app), HUB / 'shared']
    au_demarrage = empreinte(dossiers)

    @app.get('/api/version')
    def api_version():
        actuel = empreinte(dossiers)
        return jsonify(demarrage=au_demarrage, actuel=actuel, a_jour=actuel == au_demarrage)

    @app.post('/api/redemarrer')
    def api_redemarrer():
        if not request.is_json:
            return jsonify(error='Requête JSON attendue.'), 415
        arreter_enfants()

        def relancer():
            time.sleep(0.3)             # laisse partir la réponse
            sys.stdout.flush()
            sys.stderr.flush()
            # Werkzeug rend son port transmissible à l'exec (pour son propre rechargement) et
            # note son numéro dans WERKZEUG_SERVER_FD : fermé ici, sinon le nouveau processus
            # en hérite et ne peut pas rouvrir le port (« Address already in use »).
            fd = os.environ.pop('WERKZEUG_SERVER_FD', None)
            if fd and fd.isdigit():
                try:
                    os.close(int(fd))
                except OSError:
                    pass
            os.execv(sys.executable, [sys.executable, '-m', module])

        threading.Thread(target=relancer, daemon=True).start()
        return jsonify(ok=True)


def ajouter_langues(app, catalogue_ar):
    """Langue arabe pour l'application Flask `app` : catalogue `catalogue_ar` (JSON, voir
    shared/langues.py). Ajoute /commun/<fichier> (scripts communs de shared/web),
    /langues/ar.js (le catalogue pour la page) et la traduction des messages du serveur
    quand la page envoie « X-Langue: ar »."""
    import json

    from flask import Response, send_from_directory

    from shared.langues import Catalogue

    catalogue = Catalogue(catalogue_ar)
    commun = HUB / 'shared' / 'web'

    @app.get('/commun/<path:nom>')
    def fichiers_communs(nom):
        return send_from_directory(commun, nom)

    @app.get('/langues/ar.js')
    def catalogue_js():
        texte = Path(catalogue_ar).read_text(encoding='utf-8')
        json.loads(texte)                         # catalogue invalide : erreur ici, pas dans la page
        r = Response('window.CATALOGUE_AR = %s;\n' % texte, mimetype='application/javascript')
        r.headers['Cache-Control'] = 'no-cache'
        return r

    @app.after_request
    def traduire_reponse(r):
        if request.headers.get('X-Langue') == 'ar' and r.is_json:
            donnees = r.get_json(silent=True)
            if donnees is not None:
                r.set_data(json.dumps(catalogue.traduire_json(donnees), ensure_ascii=False))
        return r

    return catalogue

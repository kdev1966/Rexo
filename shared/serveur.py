"""Arrêt d'un serveur web local du hub depuis son interface (bouton « Quitter »).

POST /api/quitter (JSON seulement : un autre site ouvert dans le navigateur ne peut pas
l'appeler sans une requête préalable CORS, que le serveur refuse) : arrête les traitements
en cours (processus enfants enregistrés par `suivre`), ce qui libère la mémoire des modèles
d'IA, puis arrête le serveur. L'application du Dock (shared/lanceur) le voit et se ferme.
"""

import os
import threading
import time

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

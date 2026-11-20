"""Modèles d'IA du hub : un seul catalogue et un seul chargeur pour toutes les applications Rexo.

Les applications ne déclarent ni ne chargent de modèle elles-mêmes : elles appellent les outils
de `shared/` (shared/vision : visages, repères, détourage, reconnaissance ; shared/ia.photo :
agrandissement, visages restaurés, colorisation ; shared/ia.restauration : rayures,
reconstitution, grain), qui passent tous par ce module.

    present(id)        le modèle est installé et intact
    chemin(id)         fichier du modèle, après contrôle de sa licence
    annexe(id, nom)    fichier annexe d'un modèle (ex. « prototxt »)
    session(id)        session ONNX (processeur), ouverte une fois par processus
    executer(id, x)    session(id) appliquée à l'entrée x
    registre()         registre embedkit (pour Segmenter, Inpainter… d'embedkit)

Manifestes : shared/ia/modeles/*.yaml, plus ceux livrés avec embedkit (MobileSAM, MI-GAN,
Depth Anything V2 Small, OCR arabe). Fichiers dans le magasin partagé
~/.local/share/kdev-models/embedkit (KDEV_MODELS_DIR pour un autre dossier). Installer :

    python -m shared.embedkit.cli --models-path shared/ia/modeles models pull \\
        --allow-noncommercial <id> …

Licences : embedkit refuse un modèle dont l'usage commercial n'est pas établi. Ceux de
A_VERIFIER sont autorisés en attendant la vérification de leur licence (un avertissement,
une fois par modèle).
"""

import os
import threading
import warnings
from pathlib import Path

os.environ.setdefault('EMBEDKIT_CACHE', str(
    Path(os.environ.get('KDEV_MODELS_DIR', '~/.local/share/kdev-models')).expanduser() / 'embedkit'))

from shared.embedkit import licenses, store  # noqa: E402
from shared.embedkit.registry import Registry  # noqa: E402

MANIFESTES = Path(__file__).resolve().parent / 'modeles'
# Usage commercial non établi : poids entraînés sur des bases réservées à la recherche, ou
# licence du dépôt d'origine à vérifier.
A_VERIFIER = {'yunet-2023mar', 'sface-2021dec', 'gfpgan-1.4', 'ddcolor', 'zhang-colorization'}


class ModeleAbsent(RuntimeError):
    pass


_verrou = threading.RLock()
_registre = None
_licences_vues = set()
_sessions = {}


def registre():
    global _registre
    with _verrou:
        if _registre is None:
            _registre = Registry(extra_dirs=[MANIFESTES])
        return _registre


def manifeste(model_id):
    return registre().get(model_id)


def present(model_id):
    try:
        return store.is_installed(manifeste(model_id))
    except Exception:
        return False


def _licence(m):
    with _verrou:
        if m.id in _licences_vues:
            return
        if m.id in A_VERIFIER:
            with warnings.catch_warnings():
                warnings.simplefilter('ignore')
                licenses.check(m, allow_noncommercial=True)
        else:
            licenses.check(m)
        _licences_vues.add(m.id)


def chemin(model_id):
    """Fichier principal du modèle, après contrôle de sa licence."""
    m = manifeste(model_id)
    _licence(m)
    p = store.model_path(m)
    if not p.exists():
        raise ModeleAbsent('modèle %s absent : voir shared/ia/__init__.py pour l\'installer' % model_id)
    return p


def annexe(model_id, nom):
    """Fichier annexe d'un modèle, après contrôle de sa licence."""
    m = manifeste(model_id)
    _licence(m)
    return store.extra_path(m, nom)


def session(model_id):
    """Session ONNX Runtime sur le processeur, partagée par tout le processus."""
    with _verrou:
        if model_id not in _sessions:
            import onnxruntime as ort
            opts = ort.SessionOptions()
            opts.log_severity_level = 3
            _sessions[model_id] = ort.InferenceSession(str(chemin(model_id)), opts,
                                                       providers=['CPUExecutionProvider'])
        return _sessions[model_id]


def executer(model_id, x):
    s = session(model_id)
    return s.run(None, {s.get_inputs()[0].name: x})[0]

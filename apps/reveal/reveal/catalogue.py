"""Modèles IA de Reveal, gérés par embedkit (shared/embedkit).

Manifestes : apps/reveal/modeles/*.yaml (modèles propres à Reveal) et ceux livrés avec
embedkit (MobileSAM, MI-GAN, Depth Anything V2 Small). Fichiers dans le magasin partagé
~/.local/share/kdev-models/embedkit (KDEV_MODELS_DIR pour un autre dossier), partagé avec
Rexo Studio.

Licences : embedkit refuse par défaut un modèle dont l'usage commercial n'est pas établi.
Les modèles listés dans A_VERIFIER sont autorisés explicitement pour Reveal, avec un
avertissement, en attendant la vérification de leur licence.
"""

import os
from pathlib import Path

from .config import APP

os.environ.setdefault('EMBEDKIT_CACHE', str(
    Path(os.environ.get('KDEV_MODELS_DIR', '~/.local/share/kdev-models')).expanduser() / 'embedkit'))

from shared.embedkit import licenses, store  # noqa: E402
from shared.embedkit.registry import Registry  # noqa: E402

MANIFESTES = APP / 'modeles'
A_VERIFIER = {'gfpgan-1.4', 'ddcolor', 'zhang-colorization'}
_registre = None
_licences_vues = set()


def registre():
    global _registre
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
    if m.id not in _licences_vues:
        licenses.check(m, allow_noncommercial=m.id in A_VERIFIER)
        _licences_vues.add(m.id)


def chemin(model_id):
    """Fichier principal du modèle, après contrôle de sa licence."""
    m = manifeste(model_id)
    _licence(m)
    return store.model_path(m)


def annexe(model_id, nom):
    """Fichier annexe d'un modèle (ex. « prototxt »), après contrôle de sa licence."""
    m = manifeste(model_id)
    _licence(m)
    return store.extra_path(m, nom)

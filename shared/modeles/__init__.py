"""Catalogue des modèles IA de RetoHub : emplacement, présence, vérification, installation.

Les fichiers sont rangés une fois par machine dans ~/.local/share/kdev-models
(ou le dossier donné par la variable KDEV_MODELS_DIR), et partagés par les applications.
Bibliothèque standard seulement : utilisable avant toute installation.
"""

import hashlib
import json
import os
import shutil
import urllib.request
from pathlib import Path

CATALOGUE = Path(__file__).resolve().parent / 'catalogue.json'


def dossier():
    return Path(os.environ.get('KDEV_MODELS_DIR', '~/.local/share/kdev-models')).expanduser()


def catalogue():
    return json.loads(CATALOGUE.read_text(encoding='utf-8'))['modeles']


def _entree(nom):
    for m in catalogue():
        if m['nom'] == nom:
            return m
    raise KeyError('Modèle inconnu du catalogue : %s' % nom)


def selection(nom_ou_groupe=None):
    """Modèles d'un groupe (ex. « reveal »), un modèle par son nom, ou tous."""
    tous = catalogue()
    if not nom_ou_groupe:
        return tous
    return [m for m in tous if m['nom'] == nom_ou_groupe or nom_ou_groupe in m.get('groupes', [])]


def chemin(nom):
    """Chemin du fichier d'un modèle (qu'il soit présent ou non)."""
    return dossier() / _entree(nom)['fichier']


def present(nom):
    """Vrai si le fichier est là et a la bonne taille (vérification rapide)."""
    m = _entree(nom)
    p = dossier() / m['fichier']
    return p.is_file() and p.stat().st_size == m['taille']


def _sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for bloc in iter(lambda: f.read(1 << 20), b''):
            h.update(bloc)
    return h.hexdigest()


def verifier(nom):
    """Vrai si le fichier est là et que son empreinte SHA-256 est la bonne (vérification complète)."""
    m = _entree(nom)
    p = dossier() / m['fichier']
    return p.is_file() and p.stat().st_size == m['taille'] and _sha256(p) == m['sha256']


def installer(nom, journal=print):
    """Télécharge un modèle s'il manque, vérifie son empreinte, puis le range. Relançable."""
    m = _entree(nom)
    cible = dossier() / m['fichier']
    if present(nom) and verifier(nom):
        journal('  %s : déjà installé et vérifié' % nom)
        return cible
    cible.parent.mkdir(parents=True, exist_ok=True)
    partiel = cible.with_name(cible.name + '.part')
    journal('  %s : téléchargement (%.0f Mo)…' % (nom, m['taille'] / 1e6))
    with urllib.request.urlopen(m['url']) as rep, open(partiel, 'wb') as out:
        shutil.copyfileobj(rep, out, 1 << 20)
    empreinte = _sha256(partiel)
    if empreinte != m['sha256']:
        partiel.unlink()
        raise ValueError('%s : empreinte inattendue (%s), fichier rejeté' % (nom, empreinte))
    partiel.replace(cible)
    journal('  %s : installé et vérifié' % nom)
    return cible

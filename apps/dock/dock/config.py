"""Emplacements et réglages de Rexo Dock, calculés sur la machine où l'application tourne.

Rien n'est écrit en dur pour une machine : par défaut, les séances vont dans un dossier
« Rexo Dock » créé sur le Bureau de la machine où l'application tourne, pour que le
photographe le trouve tout de suite (Bureau donné par le système : sous Windows, il peut être
redirigé vers OneDrive). Un autre dossier et le disque de seconde copie se choisissent dans
l'application ; ces choix sont retenus dans donnees/reglages.json, propre à chaque machine.
"""

import json
import os
from pathlib import Path

from shared.systeme import dossier_bureau

APP = Path(__file__).resolve().parent.parent          # apps/dock
DONNEES = Path(os.environ.get('DOCK_DATA', str(APP / 'donnees'))).expanduser()
REGLAGES = DONNEES / 'reglages.json'
REGISTRE = DONNEES / 'registre.json'                  # fichiers déjà importés, par appareil
NOM_DOSSIER = 'Rexo Dock'


class ReglageError(ValueError):
    pass


def lire_reglages():
    try:
        return json.loads(REGLAGES.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}


def _ecrire(cle, valeur):
    r = lire_reglages()
    r[cle] = valeur
    REGLAGES.parent.mkdir(parents=True, exist_ok=True)
    REGLAGES.write_text(json.dumps(r, ensure_ascii=False, indent=2), encoding='utf-8')


def dossier_seances_defaut():
    return dossier_bureau() / NOM_DOSSIER


def dossier_seances(creer=False):
    """Dossier où sont créés les dossiers de séance ; `creer` le crée s'il manque (au démarrage,
    pour qu'il soit visible sur le Bureau avant le premier import)."""
    p = Path(lire_reglages().get('seances') or dossier_seances_defaut()).expanduser()
    if creer:
        p.mkdir(parents=True, exist_ok=True)
    return p


def choisir_seances(chemin):
    p = Path(chemin).expanduser()
    if not p.is_absolute():
        raise ReglageError('chemin absolu attendu')
    p.mkdir(parents=True, exist_ok=True)
    _ecrire('seances', str(p))
    return p


def dossier_miroir():
    """Dossier de seconde copie (disque externe), ou None s'il n'est pas choisi."""
    m = lire_reglages().get('miroir')
    return Path(m).expanduser() if m else None


def choisir_miroir(chemin):
    """Retient le dossier de seconde copie ; None l'abandonne. Le disque peut être débranché :
    la seconde copie attend simplement qu'il revienne."""
    if chemin is None:
        _ecrire('miroir', None)
        return None
    p = Path(chemin).expanduser()
    if not p.is_absolute():
        raise ReglageError('chemin absolu attendu')
    _ecrire('miroir', str(p))
    return p

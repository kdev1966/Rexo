"""Emplacements et réglages de Rexo Dock, calculés sur la machine où l'application tourne.

Rien n'est écrit en dur pour une machine : par défaut, les séances vont dans le dossier
« Images » de l'utilisateur (~/Pictures/Rexo Dock sur Mac, C:\\Users\\<nom>\\Pictures\\Rexo Dock
sous Windows) ; le photographe choisit un autre dossier, et le disque de seconde copie, dans
l'application. Ces choix sont retenus dans donnees/reglages.json, propre à chaque machine.
"""

import json
import os
from pathlib import Path

APP = Path(__file__).resolve().parent.parent          # apps/dock
DONNEES = Path(os.environ.get('DOCK_DATA', str(APP / 'donnees'))).expanduser()
REGLAGES = DONNEES / 'reglages.json'
REGISTRE = DONNEES / 'registre.json'                  # fichiers déjà importés, par appareil
SEANCES_DEFAUT = Path.home() / 'Pictures' / 'Rexo Dock'


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


def dossier_seances():
    """Dossier où sont créés les dossiers de séance."""
    return Path(lire_reglages().get('seances') or SEANCES_DEFAUT).expanduser()


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

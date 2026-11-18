"""Emplacements des données de l'application Identité."""

import os
from pathlib import Path

APP = Path(__file__).resolve().parent.parent          # apps/identite
DONNEES = Path(os.environ.get('IDENTITE_DATA', str(APP / 'donnees'))).expanduser()
ORIGINAL = DONNEES / 'original'        # portraits à traiter (jamais modifiés)
RESULTATS = DONNEES / 'resultats'      # photos d'identité, planches et rapports

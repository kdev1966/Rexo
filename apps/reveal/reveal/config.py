"""Emplacements des données de Reveal."""

import os
from pathlib import Path

APP = Path(__file__).resolve().parent.parent          # apps/reveal
DONNEES = Path(os.environ.get('REVEAL_DATA', str(APP / 'donnees'))).expanduser()
ORIGINAL = DONNEES / 'original'        # photos à traiter (jamais modifiées)
RETOUCHE = DONNEES / 'retouche'        # résultats : PSD, JPEG, avant, restaurée
TRAVAIL = DONNEES / '.travail'         # fichiers intermédiaires, effacés après chaque passage
REGLAGES = DONNEES / 'reglages.json'   # réglages par photo (visages exclus de l'IA, retouches ciblées)
IMAGES = {'.jpg', '.jpeg', '.png', '.tif', '.tiff', '.webp'}

"""Emplacements des données de Reveal."""

import os
from pathlib import Path

APP = Path(__file__).resolve().parent.parent          # apps/reveal
DONNEES = Path(os.environ.get('REVEAL_DATA', str(APP / 'donnees'))).expanduser()
ORIGINAL = DONNEES / 'original'        # photos à traiter (jamais modifiées)
RETOUCHE = DONNEES / 'retouche'        # résultats : PSD, JPEG, avant, restaurée
TRAVAIL = DONNEES / '.travail'         # fichiers intermédiaires, effacés après chaque passage
REGLAGES = DONNEES / 'reglages.json'   # réglages par photo (visages exclus de l'IA, retouches ciblées)
APERCUS = DONNEES / '.apercus'        # aperçus JPEG des formats que le navigateur n'affiche pas

from shared.images import FORMATS as IMAGES  # noqa: E402  formats acceptés (convertis si besoin)

# Formats affichés tels quels par les navigateurs (Safari 15 sous macOS 12 compris)

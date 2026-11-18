"""Reveal : retouche de portraits et restauration / colorisation de photos anciennes,
avec PhotoCraft piloté par Python et des modèles IA locaux (aucune photo ne quitte la machine)."""

import sys
from pathlib import Path

# Rend le code partagé de Rexo (dossier shared/ à la racine du dépôt) importable.
_HUB = Path(__file__).resolve().parents[3]
if str(_HUB) not in sys.path:
    sys.path.insert(0, str(_HUB))

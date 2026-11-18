"""Identité : photos d'identité aux normes françaises (35 × 45 mm) et planches 10 × 15 cm,
avec Apple Vision (visage, détourage) et des réglages de couleur locaux (aucune photo ne sort)."""

import sys
from pathlib import Path

# Rend le code partagé de Rexo (dossier shared/ à la racine du dépôt) importable.
_HUB = Path(__file__).resolve().parents[3]
if str(_HUB) not in sys.path:
    sys.path.insert(0, str(_HUB))

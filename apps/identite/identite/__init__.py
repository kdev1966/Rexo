"""Identité : photos d'identité aux normes françaises (35 × 45 mm) et planches 10 × 15 cm,
avec des modèles d'IA locaux (visage, détourage : shared.vision) et des réglages de couleur (aucune photo ne sort)."""

import sys
from pathlib import Path

# Rend le code partagé de Rexo (dossier shared/ à la racine du dépôt) importable.
_HUB = Path(__file__).resolve().parents[3]
if str(_HUB) not in sys.path:
    sys.path.insert(0, str(_HUB))

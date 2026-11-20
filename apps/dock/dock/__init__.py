"""Rexo Dock : copier les photos d'un iPhone, vérifiées, puis aider au tri (ADR 0005)."""

import sys
from pathlib import Path

# Racine du hub (Rexo/), pour importer `shared`
_HUB = Path(__file__).resolve().parents[3]
if str(_HUB) not in sys.path:
    sys.path.insert(0, str(_HUB))

#!/bin/bash
# ---------------------------------------------------------------------------
# Compile reto-segment (Swift, Apple Vision et Core Image) dans shared/natif/bin/ :
# détourage des personnes, fond flou / noir et blanc / uni, recadrage centré sur les
# personnes, amélioration automatique, rendus de couleur, redressement EXIF.
# Nécessite les outils en ligne de commande d'Apple (xcode-select --install) et
# macOS 12 ou plus (VNGeneratePersonSegmentationRequest). Relançable : ne recompile
# que si la source a changé.
# ---------------------------------------------------------------------------
set -euo pipefail
cd "$(dirname "$0")"
SRC="segment.swift"
OUT="bin/reto-segment"
command -v swiftc >/dev/null 2>&1 || { echo "swiftc introuvable : xcode-select --install" >&2; exit 1; }
mkdir -p bin
if [ -x "$OUT" ] && [ "$OUT" -nt "$SRC" ]; then
  echo "$OUT est à jour."
else
  swiftc -O "$SRC" -o "$OUT.tmp"
  mv "$OUT.tmp" "$OUT"
  echo "$OUT compilé."
fi

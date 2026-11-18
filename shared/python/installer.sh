#!/bin/bash
# ---------------------------------------------------------------------------
# Installe le Python 3.11 autonome partagé par les applications de RetoHub dans
# <hub>/.outils/python (python-build-standalone, empreinte SHA-256 épinglée).
# Chaque application crée ensuite son propre environnement à partir de lui.
# Relançable : ne retélécharge rien si la bonne version est déjà là.
# ---------------------------------------------------------------------------
set -euo pipefail
cd "$(dirname "$0")/../.."
DEST="$PWD/.outils/python"
PY_RELEASE="20261021"
PY_VERSION="3.11.17"
PY_URL="https://github.com/astral-sh/python-build-standalone/releases/download/${PY_RELEASE}/cpython-${PY_VERSION}%2B${PY_RELEASE}-x86_64-apple-darwin-install_only.tar.gz"
PY_SHA="c647c272312c03301e399f0e0fdb2b876fed213ee6985cd2d232d588a316483f"

[ "$(uname -s)" = "Darwin" ] || { echo "macOS seulement." >&2; exit 1; }
[ "$(uname -m)" = "x86_64" ] || { echo "Version figée pour Mac Intel (x86_64)." >&2; exit 1; }

if [ -x "$DEST/bin/python3" ] && \
   [ "$("$DEST/bin/python3" -c 'import platform; print(platform.python_version())')" = "$PY_VERSION" ]; then
  echo "Python $PY_VERSION déjà installé ($DEST)."
  exit 0
fi
mkdir -p .outils
TMP=".outils/python-$PY_VERSION.tar.gz.part"
echo "Téléchargement de Python $PY_VERSION…"
curl -fL --retry 3 -o "$TMP" "$PY_URL"
echo "$PY_SHA  $TMP" | shasum -a 256 -c - >/dev/null || { rm -f "$TMP"; echo "Empreinte SHA-256 incorrecte : refusé." >&2; exit 1; }
rm -rf .outils/python.new && mkdir -p .outils/python.new
tar xzf "$TMP" -C .outils/python.new
rm -rf "$DEST" && mv .outils/python.new/python "$DEST" && rmdir .outils/python.new && rm -f "$TMP"
echo "Python $("$DEST/bin/python3" -c 'import platform; print(platform.python_version())') installé ($DEST)."

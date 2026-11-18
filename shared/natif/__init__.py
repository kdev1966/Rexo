"""Appel de reto-segment (Swift, Apple Vision et Core Image), commun aux applications du hub.

L'outil se compile avec shared/natif/compiler.sh (macOS 12 ou plus). Il lit les formats que
macOS connaît (pas l'AVIF sous macOS 12) : lui passer des PNG ou des JPEG de travail.
Chaque appel répond par une ligne JSON {"ok": true, ...} ou {"ok": false, "error": ...}.
"""

import json
import subprocess
from pathlib import Path

SEGMENT = Path(__file__).resolve().parent / 'bin' / 'reto-segment'


class NatifError(RuntimeError):
    pass


def disponible():
    return SEGMENT.exists()


def executer(*args, timeout=300):
    """Lance reto-segment avec `args` ; renvoie sa réponse JSON, ou lève NatifError."""
    if not disponible():
        raise NatifError('reto-segment absent : lancer shared/natif/compiler.sh')
    try:
        r = subprocess.run([str(SEGMENT)] + [str(a) for a in args], capture_output=True, text=True,
                           timeout=timeout)
    except subprocess.TimeoutExpired:
        raise NatifError('reto-segment : délai dépassé')
    lines = [l for l in r.stdout.splitlines() if l.strip().startswith('{')]
    try:
        res = json.loads(lines[-1]) if lines else {}
    except ValueError:
        res = {}
    if not res.get('ok'):
        raise NatifError('reto-segment %s : %s' % (args[0], res.get('error') or r.stderr.strip()[:200]))
    return res

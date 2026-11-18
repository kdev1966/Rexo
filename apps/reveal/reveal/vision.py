"""Effets natifs d'Apple (Vision, Core Image) par l'outil partagé reto-segment.

L'outil se compile avec shared/natif/compiler.sh (macOS 12 ou plus). Il lit les formats que
macOS connaît (pas l'AVIF sous macOS 12) : Reveal lui passe toujours ses PNG de travail.
Chaque appel répond par une ligne JSON {"ok": true, ...} ou {"ok": false, "error": ...}.
"""

import json
import subprocess
from pathlib import Path

import cv2
import numpy as np

SEGMENT = Path(__file__).resolve().parents[3] / 'shared' / 'natif' / 'bin' / 'reto-segment'

# Rendus de couleur proposés par reto-segment (option --name de « style »)
STYLES = {
    'chaud': 'Chaud',
    'froid': 'Froid',
    'vintage-chaud': 'Vintage chaud',
    'noir-et-blanc': 'Noir et blanc',
    'lumineux': 'Lumineux',
    'contraste': 'Contrasté',
    'doux': 'Doux',
}


class VisionError(RuntimeError):
    pass


def disponible():
    return SEGMENT.exists()


def _run(*args, timeout=300):
    if not disponible():
        raise VisionError('reto-segment absent : lancer shared/natif/compiler.sh')
    try:
        r = subprocess.run([str(SEGMENT)] + [str(a) for a in args], capture_output=True, text=True,
                           timeout=timeout)
    except subprocess.TimeoutExpired:
        raise VisionError('reto-segment : délai dépassé')
    lines = [l for l in r.stdout.splitlines() if l.strip().startswith('{')]
    try:
        res = json.loads(lines[-1]) if lines else {}
    except ValueError:
        res = {}
    if not res.get('ok'):
        raise VisionError('reto-segment %s : %s' % (args[0], res.get('error') or r.stderr.strip()[:200]))
    return res


def masque_personnes(src, dst):
    """Masque des personnes (Apple Vision, qualité maximale) : tableau 0..1 et part de l'image."""
    res = _run('mask', src, dst, '--quality', 'accurate')
    m = cv2.imread(str(dst), cv2.IMREAD_GRAYSCALE)
    if m is None:
        raise VisionError('masque illisible : %s' % dst)
    return m.astype(np.float32) / 255.0, float(res.get('coverage', m.mean() / 255.0))


# Effets de studio (détourage des personnes par Apple Vision) : nom Reveal -> (effet reto-segment, libellé)
STUDIO = {
    'fond-flou': ('blur', 'Fond flou'),
    'fond-noir-blanc': ('bw', 'Couleur sur fond noir et blanc'),
    'fond-uni': ('uni', 'Fond uni'),
    'detourage': ('cutout', 'Détourage'),
    'recadrage': ('crop', 'Recadrage'),
}
FORMATS_RECADRAGE = ('4:5', '1:1', '9:16', '16:9', '3:4', '2:3')


def effet_studio(nom, src, dst, couleur='255,255,255', ratio='4:5'):
    """Applique un effet de STUDIO ; renvoie la réponse de reto-segment (avec « box » pour le recadrage)."""
    if nom not in STUDIO:
        raise VisionError('effet de studio inconnu : %s' % nom)
    tool = STUDIO[nom][0]
    opts = []
    if tool == 'uni':
        opts = ['--color', couleur]
    elif tool == 'crop':
        if ratio not in FORMATS_RECADRAGE:
            raise VisionError('format de recadrage inconnu : %s' % ratio)
        opts = ['--ratio', ratio]
    return _run(tool, src, dst, *opts)


def ameliorer(src, dst):
    """Amélioration automatique d'Apple : lumière, couleurs, balance des blancs, relief."""
    return _run('enhance', src, dst)


def rendu(src, dst, nom):
    """Rendu de couleur sur toute l'image (voir STYLES)."""
    if nom not in STYLES:
        raise VisionError('rendu inconnu : %s' % nom)
    return _run('style', src, dst, '--name', nom)

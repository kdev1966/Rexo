"""Masque des personnes, effets de studio, amélioration et rendus de couleur de Reveal.

Calculés en Python (shared.vision : MODNet et MobileSAM ; shared.vision.effets : numpy et
OpenCV), pour un résultat identique sous macOS et Windows. Ils remplacent Apple Vision et
Core Image (rexo-segment), dont ils reprennent les réglages.

Les fonctions lisent un fichier image et en écrivent un autre : PNG si le nom finit par
.png (transparence gardée), JPEG (qualité 92) sinon.
"""

import cv2
import numpy as np

from shared import vision as _vision
from shared.images import ConversionImpossible, lire
from shared.vision import effets as _effets


class VisionError(RuntimeError):
    pass


# Rendus de couleur : nom Reveal -> libellé
STYLES = {
    'chaud': 'Chaud',
    'froid': 'Froid',
    'vintage-chaud': 'Vintage chaud',
    'noir-et-blanc': 'Noir et blanc',
    'lumineux': 'Lumineux',
    'contraste': 'Contrasté',
    'doux': 'Doux',
}

# Effets de studio (personnes détourées) : nom Reveal -> libellé
STUDIO = {
    'fond-flou': 'Fond flou',
    'fond-noir-blanc': 'Couleur sur fond noir et blanc',
    'fond-uni': 'Fond uni',
    'detourage': 'Détourage',
    'recadrage': 'Recadrage',
}
FORMATS_RECADRAGE = ('4:5', '1:1', '9:16', '16:9', '3:4', '2:3')


def disponible():
    """Vrai si les modèles du masque des personnes sont installés."""
    try:
        _vision._chemin('modnet')
        _vision._chemin('yunet-2023mar')
        return True
    except Exception:
        return False


def _lire(src, alpha=False):
    try:
        return lire(src, alpha=alpha)[0]                  # lecture commune au hub
    except ConversionImpossible as e:
        raise VisionError(str(e)) from None


def _ecrire(img, dst):
    dst = str(dst)
    ok = cv2.imwrite(dst, img) if dst.lower().endswith('.png') else \
        cv2.imwrite(dst, img, [cv2.IMWRITE_JPEG_QUALITY, 92])
    if not ok:
        raise VisionError('écriture impossible : %s' % dst)


def _personnes(img):
    try:
        return _vision.personnes(img)
    except _vision.VisionError as e:
        raise VisionError(str(e))


def masque_personnes(src, dst):
    """Masque des personnes : tableau 0..1, part de l'image ; le masque est aussi écrit dans `dst`."""
    m, _ = _personnes(_lire(src))
    _ecrire((np.clip(m, 0, 1) * 255).astype(np.uint8), dst)
    return m, float(m.mean())


def effet_studio(nom, src, dst, couleur='255,255,255', ratio='4:5'):
    """Applique un effet de STUDIO ; renvoie {coverage, methode} (et « box » pour le recadrage)."""
    if nom not in STUDIO:
        raise VisionError('effet de studio inconnu : %s' % nom)
    img = _lire(src)
    m, methode = _personnes(img)
    res = {'coverage': float(m.mean()), 'methode': methode}
    if nom == 'fond-flou':
        out = _effets.flou(img, m)
    elif nom == 'fond-noir-blanc':
        out = _effets.noir_blanc(img, m)
    elif nom == 'fond-uni':
        try:
            rvb = tuple(int(v) for v in couleur.split(','))
            assert len(rvb) == 3 and all(0 <= v <= 255 for v in rvb)
        except (ValueError, AssertionError):
            raise VisionError('couleur invalide (r,g,b) : %s' % couleur)
        out = _effets.uni(img, m, rvb)
    elif nom == 'detourage':
        out = _effets.detourage(img, m)
    else:
        if ratio not in FORMATS_RECADRAGE:
            raise VisionError('format de recadrage inconnu : %s' % ratio)
        out, res['box'] = _effets.recadrage(img, m, ratio)
    _ecrire(out, dst)
    return res


def ameliorer(src, dst):
    """Amélioration automatique : lumière, couleurs, balance des blancs, relief."""
    out, faits, gains = _effets.ameliorer(_lire(src))
    _ecrire(out, dst)
    return {'enhance': faits, 'white_balance': gains}


def rendu(src, dst, nom):
    """Rendu de couleur sur toute l'image (voir STYLES)."""
    if nom not in STYLES:
        raise VisionError('rendu inconnu : %s' % nom)
    _ecrire(_effets.rendu(_lire(src, alpha=True), nom), dst)
    return {}

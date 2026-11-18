"""Planches 10 × 15 cm (à l'italienne) avec traits de coupe.

Les traits prolongent chaque bord de photo sur toute la planche ; les photos sont posées
par-dessus, si bien qu'ils ne restent visibles que dans les marges et entre les photos :
on coupe d'un bord de la planche à l'autre, au massicot ou au cutter.
"""

import cv2
import numpy as np

from .normes import DPI, ECART, MM_PAR_POUCE, PLANCHE, PORTRAIT, TRAIT


def disposition_8(photo_mm, planche=PLANCHE, ecart=ECART):
    """8 photos : 4 colonnes × 2 rangées, centrées. Renvoie [(x, y, l, h)] en mm."""
    pw, ph = photo_mm
    bw, bh = 4 * pw + 3 * ecart, 2 * ph + ecart
    x0, y0 = (planche[0] - bw) / 2, (planche[1] - bh) / 2
    if x0 < 0 or y0 < 0:
        raise ValueError('8 photos de %g × %g mm ne tiennent pas sur la planche' % photo_mm)
    return [(x0 + c * (pw + ecart), y0 + r * (ph + ecart), pw, ph) for r in range(2) for c in range(4)]


def disposition_4_portrait(photo_mm, portrait_mm=PORTRAIT, planche=PLANCHE, ecart=ECART):
    """4 photos (2 × 2) à gauche, le portrait à droite ; le tout centré.
    Renvoie (cadres des 4 photos, cadre du portrait) en mm."""
    pw, ph = photo_mm
    qw, qh = portrait_mm
    bw = 2 * pw + ecart + 2 * ecart + qw       # écart double entre le bloc et le portrait
    bh = max(2 * ph + ecart, qh)
    x0, y0 = (planche[0] - bw) / 2, (planche[1] - bh) / 2
    if x0 < 0 or y0 < 0:
        raise ValueError('4 photos et un portrait ne tiennent pas sur la planche')
    yb = y0 + (bh - (2 * ph + ecart)) / 2
    photos = [(x0 + c * (pw + ecart), yb + r * (ph + ecart), pw, ph) for r in range(2) for c in range(2)]
    portrait = (x0 + 2 * pw + 3 * ecart, y0 + (bh - qh) / 2, qw, qh)
    return photos, portrait


def _px(v, dpi):
    return int(round(v * dpi / MM_PAR_POUCE))


def composer(cadres, images, planche=PLANCHE, dpi=DPI, trait=TRAIT):
    """Planche blanche, traits de coupe, puis chaque image (BGR) dans son cadre (mm)."""
    W, H = _px(planche[0], dpi), _px(planche[1], dpi)
    out = np.full((H, W, 3), 255, np.uint8)
    couleur = tuple(int(c) for c in trait[::-1])
    epaisseur = max(1, int(round(dpi / 300)))
    boites = []
    for (x, y, w, h), img in zip(cadres, images):
        x0, y0 = _px(x, dpi), _px(y, dpi)
        x1, y1 = x0 + img.shape[1], y0 + img.shape[0]
        boites.append((x0, y0, x1, y1, img))
        for xx in (x0, x1 - 1):
            cv2.line(out, (xx, 0), (xx, H - 1), couleur, epaisseur)
        for yy in (y0, y1 - 1):
            cv2.line(out, (0, yy), (W - 1, yy), couleur, epaisseur)
    for x0, y0, x1, y1, img in boites:
        out[y0:y1, x0:x1] = img
    return out

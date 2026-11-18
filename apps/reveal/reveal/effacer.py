"""D. Effacer des objets ou des personnes indésirables : MobileSAM détoure ce qu'on désigne,
MI-GAN reconstitue le décor à sa place (modèles d'embedkit, licences commerciales).

Une zone, en fractions de l'image (0..1, telle qu'affichée : orientation EXIF appliquée) :
    {"cadre": [x, y, largeur, hauteur]}                  ce qui est dans le cadre
    {"points": [[x, y], [x, y, 0], ...]}                 clics : 1 (défaut) = « ça », 0 = « pas ça »
    {"cadre": [...], "points": [...]}                    les deux à la fois
Plusieurs zones sont réunies en un seul masque, élargi pour emporter les bords et les ombres
douces de l'objet, puis reconstitué en une seule fois.
"""

import os

import cv2
import numpy as np

from . import catalogue

MAX_ZONES = 20
MAX_PART_ZONE = 0.6      # au-delà, MobileSAM a pris le fond : on prend sa proposition suivante


class EffacementError(RuntimeError):
    pass


def valider(zones):
    """Vérifie la forme des zones (fractions entre 0 et 1) ; renvoie la liste nettoyée."""
    if not isinstance(zones, list) or not 1 <= len(zones) <= MAX_ZONES:
        raise EffacementError('entre 1 et %d zones attendues' % MAX_ZONES)
    propres = []
    for z in zones:
        if not isinstance(z, dict) or not ('cadre' in z or 'points' in z):
            raise EffacementError('zone sans cadre ni clic')
        out = {}
        if 'cadre' in z:
            c = [float(v) for v in z['cadre']]
            if len(c) != 4 or min(c) < 0 or c[0] + c[2] > 1.0001 or c[1] + c[3] > 1.0001 or c[2] <= 0 or c[3] <= 0:
                raise EffacementError('cadre invalide : %s' % z['cadre'])
            out['cadre'] = c
        if 'points' in z:
            pts = []
            for p in z['points']:
                p = [float(v) for v in p]
                if len(p) not in (2, 3) or not (0 <= p[0] <= 1 and 0 <= p[1] <= 1):
                    raise EffacementError('clic invalide : %s' % p)
                pts.append([p[0], p[1], int(p[2]) if len(p) == 3 else 1])
            if pts:
                out['points'] = pts
        if not out:
            raise EffacementError('zone vide')
        propres.append(out)
    return propres


def _elargir(mask, grow):
    """Zone à effacer : tout pixel à moins de `grow` px de l'objet (transformée de distance
    limitée à la zone de l'objet : rapide même sur une grande photo)."""
    h, w = mask.shape
    ys, xs = np.nonzero(mask)
    x0, y0 = max(0, xs.min() - grow - 1), max(0, ys.min() - grow - 1)
    x1, y1 = min(w, xs.max() + grow + 2), min(h, ys.max() + grow + 2)
    dist = cv2.distanceTransform((mask[y0:y1, x0:x1] == 0).astype(np.uint8), cv2.DIST_L2, 5)
    hole = np.zeros_like(mask)
    hole[y0:y1, x0:x1] = (dist <= grow).astype(np.uint8)
    return hole


def effacer(image, zones):
    """Renvoie (image reconstituée, masque effacé 0/1, détails par zone [(n°, part, score)])."""
    zones = valider(zones)
    os.environ.setdefault('EMBEDKIT_OFFLINE', '1')        # jamais de réseau pendant un traitement
    from shared.embedkit.tasks.inpaint import Inpainter
    from shared.embedkit.tasks.segment import Segmenter

    h, w = image.shape[:2]
    total = np.zeros((h, w), np.uint8)
    details = []
    with Segmenter.load(model='mobilesam', registry=catalogue.registre()) as seg:
        if seg.tier == 0:
            raise EffacementError('modèle MobileSAM absent')
        emb = seg.embed(image)
        for n, z in enumerate(zones, 1):
            box = None
            inside = None
            if 'cadre' in z:
                fx, fy, fw, fh = z['cadre']
                box = (fx * w, fy * h, (fx + fw) * w, (fy + fh) * h)
                inside = np.zeros((h, w), np.uint8)
                inside[int(box[1]):int(np.ceil(box[3])), int(box[0]):int(np.ceil(box[2]))] = 1
            pts = [(p[0] * w, p[1] * h, p[2]) for p in z.get('points', [])]
            masks, scores = seg.segment(emb, points=pts or None, box=box)
            chosen = None
            for k in np.argsort(-scores):
                m = masks[k].astype(np.uint8)
                if inside is not None:
                    m &= inside                                   # ce qui déborde du cadre n'est pas l'objet
                part = float(m.mean())
                if 0 < part < MAX_PART_ZONE:
                    chosen = (m, float(scores[k]), part)
                    break
            if chosen is None:
                details.append((n, 0.0, 0.0))
                continue
            total |= chosen[0]
            details.append((n, chosen[2], chosen[1]))
    if not total.any():
        raise EffacementError('rien trouvé à effacer dans les zones désignées')
    hole = _elargir(total, max(7, int(round(max(w, h) * 0.006))))
    with Inpainter.load(model='migan-512', registry=catalogue.registre()) as inp:
        if inp.tier == 0:
            raise EffacementError('modèle MI-GAN absent')
        result = inp(image, hole)
    return result, hole, details

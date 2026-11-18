"""Visage et masque des personnes par Apple Vision (reto-segment face)."""

from dataclasses import dataclass, field

import cv2
import numpy as np

from shared.natif import NatifError, executer


class VisageError(RuntimeError):
    pass


@dataclass
class Visage:
    cadre: tuple                     # x, y, l, h (pixels, origine en haut à gauche)
    pupilles: np.ndarray             # 2 × 2, triées de gauche à droite dans l'image
    contour: np.ndarray              # mâchoire, d'une oreille à l'autre
    yeux: list                       # deux tableaux de points (gauche, droite de l'image)
    lacet: float = 0.0               # degrés, tête tournée
    autres: int = 0                  # autres visages nets sur la photo
    confiance: float = 0.0
    extra: dict = field(default_factory=dict)


def analyser(src_png, masque_png):
    """Renvoie (visage principal, masque des personnes 0..1 à la taille de l'image)."""
    try:
        res = executer('face', src_png, masque_png, '--quality', 'accurate')
    except NatifError as e:
        raise VisageError(str(e))
    faces = [f for f in res.get('faces', []) if len(f.get('pupils', [])) == 2 and f.get('contour')]
    if not faces:
        raise VisageError('aucun visage trouvé')
    faces.sort(key=lambda f: f['box'][2], reverse=True)
    f = faces[0]
    autres = sum(1 for g in faces[1:] if g['box'][2] > 0.4 * f['box'][2])
    pupilles = np.array(sorted(f['pupils']), dtype=np.float64)
    yeux = sorted((np.array(f['left_eye'], np.float64), np.array(f['right_eye'], np.float64)),
                  key=lambda e: e[:, 0].mean() if len(e) else 0)
    masque = cv2.imread(str(masque_png), cv2.IMREAD_GRAYSCALE)
    if masque is None:
        raise VisageError('masque illisible')
    return Visage(cadre=tuple(f['box']), pupilles=pupilles, contour=np.array(f['contour'], np.float64),
                  yeux=yeux, lacet=float(f.get('yaw') or 0.0), autres=autres,
                  confiance=float(f.get('confidence', 0))), masque.astype(np.float32) / 255.0

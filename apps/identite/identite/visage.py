"""Visage et masque des personnes (shared.vision : YuNet, Face Mesh, MODNet), sous macOS
comme sous Windows."""

from dataclasses import dataclass, field

import numpy as np

from shared import vision


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


def analyser(img):
    """Visage principal et masque des personnes (0..1, à la taille de l'image BGR `img`)."""
    try:
        v, masque = vision.analyser_visage(img)
    except vision.VisionError as e:
        raise VisageError(str(e))
    return Visage(cadre=tuple(v['cadre']), pupilles=v['pupilles'], contour=v['contour'],
                  yeux=v['yeux'], lacet=float(v['lacet']), autres=v['autres'],
                  confiance=float(v['confiance'])), masque

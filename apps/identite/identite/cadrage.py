"""Géométrie de la photo d'identité : redressement, mesure de la tête, mise à l'échelle.

Tout est calculé dans le repère « redressé » : origine au milieu des pupilles, axe x le long
de la ligne des yeux, y vers le bas. Le menton est le point le plus bas du contour de la
mâchoire (Face Mesh). Le sommet du crâne (hors chevelure) n'est pas visible : il est
estimé par les proportions de la tête (yeux à mi-hauteur environ, l'œil -> menton valant
0,52 de la hauteur menton -> sommet), sans monter plus haut que le haut du masque des
personnes (crâne rasé, cheveux plaqués). Le haut des cheveux est lu sur le masque.
"""

import math
from dataclasses import dataclass

import cv2
import numpy as np

from .normes import DPI, MM_PAR_POUCE, px

OEIL_MENTON = 0.52          # (œil -> menton) / (sommet -> menton)


def angle_yeux(pupilles):
    """Inclinaison de la ligne des yeux, en degrés (positif : œil droit de l'image plus bas)."""
    (x0, y0), (x1, y1) = pupilles
    return math.degrees(math.atan2(y1 - y0, x1 - x0))


def rotation(angle):
    """Matrice qui ramène la ligne des yeux à l'horizontale (repère image, y vers le bas)."""
    t = math.radians(angle)
    return np.array([[math.cos(t), math.sin(t)], [-math.sin(t), math.cos(t)]])


@dataclass
class Tete:
    centre: np.ndarray      # milieu des pupilles (image)
    angle: float            # degrés
    x: float                # milieu du visage (repère redressé)
    crane: float            # sommet du crâne (repère redressé, négatif)
    cheveux: float          # haut des cheveux
    menton: float

    @property
    def hauteur(self):
        return self.menton - self.crane


def haut_du_masque(masque, centre, angle, largeur_visage, x_visage):
    """Haut des cheveux (repère redressé) : première ligne où le masque couvre 30 % de la
    bande centrale du visage ; None si le masque ne monte pas au-dessus des yeux."""
    m = cv2.warpAffine(masque, matrice(centre, angle, 1.0, (masque.shape[1] / 2, masque.shape[0] / 2)),
                       (masque.shape[1], masque.shape[0]), flags=cv2.INTER_LINEAR, borderValue=0)
    ox, oy = masque.shape[1] / 2, masque.shape[0] / 2
    x0 = int(max(0, ox + x_visage - largeur_visage / 4))
    x1 = int(min(m.shape[1], ox + x_visage + largeur_visage / 4))
    if x1 <= x0:
        return None
    bande = (m[: int(oy), x0:x1] > 0.5).mean(axis=1)
    lignes = np.nonzero(bande >= 0.3)[0]
    return float(lignes[0] - oy) if len(lignes) else None


def mesurer(visage, masque):
    centre = visage.pupilles.mean(axis=0)
    angle = angle_yeux(visage.pupilles)
    r = rotation(angle)
    contour = (visage.contour - centre) @ r.T
    menton = float(contour[:, 1].max())
    x = float((contour[:, 0].min() + contour[:, 0].max()) / 2)
    crane = -menton * (1 / OEIL_MENTON - 1)
    cheveux = haut_du_masque(masque, centre, angle, np.ptp(contour[:, 0]), x)
    if cheveux is None:
        cheveux = crane
    crane = max(crane, cheveux)         # le crâne n'est jamais au-dessus du masque
    return Tete(centre=centre, angle=angle, x=x, crane=crane, cheveux=cheveux, menton=menton)


def matrice(centre, angle, echelle, cible):
    """Transformation affine (2 × 3) : centre -> cible, ligne des yeux horizontale, échelle."""
    r = rotation(angle) * echelle
    t = np.asarray(cible, np.float64) - r @ np.asarray(centre, np.float64)
    return np.hstack([r, t.reshape(2, 1)])


def placer(tete, norme, dpi=DPI):
    """Transformation de la photo vers la photo d'identité, et la position de la tête (mm)."""
    ppmm = dpi / MM_PAR_POUCE
    echelle = norme.tete * ppmm / tete.hauteur
    haut = norme.marge_haut * ppmm
    # Cheveux trop près du bord haut : on descend la tête, sans coller le menton en bas
    cheveux = haut + echelle * (tete.cheveux - tete.crane)
    descente = max(0.0, norme.marge_cheveux * ppmm - cheveux)
    menton = haut + echelle * tete.hauteur
    descente = min(descente, max(0.0, (norme.hauteur - norme.marge_bas_min) * ppmm - menton))
    haut += descente
    cible = (norme.largeur * ppmm / 2 - echelle * tete.x, haut - echelle * tete.crane)
    m = matrice(tete.centre, tete.angle, echelle, cible)
    infos = {
        'tete_mm': round(norme.tete, 1),
        'crane_mm': round(haut / ppmm, 1),
        'cheveux_mm': round((haut + echelle * (tete.cheveux - tete.crane)) / ppmm, 1),
        'menton_mm': round((haut + echelle * tete.hauteur) / ppmm, 1),
        'echelle': round(echelle, 3),
        'redressement': round(tete.angle, 1),
    }
    return m, infos


def placer_portrait(tete, taille_mm, dpi=DPI, part_tete=0.42, marge_haut=0.10):
    """Portrait (planche « 4 + portrait ») : tête plus petite, plus d'épaules."""
    ppmm = dpi / MM_PAR_POUCE
    lw, lh = taille_mm[0] * ppmm, taille_mm[1] * ppmm
    echelle = part_tete * lh / tete.hauteur
    haut = marge_haut * lh - echelle * (tete.cheveux - tete.crane)
    cible = (lw / 2 - echelle * tete.x, haut - echelle * tete.crane)
    return matrice(tete.centre, tete.angle, echelle, cible)


def placer_portrait_couvert(tete, img_shape, taille_mm, dpi=DPI, part_tete=0.42, part_max=0.65):
    """Comme placer_portrait, en rapprochant le portrait (tête plus grande, jusqu'à part_max)
    tant que la photo d'origine n'atteint pas le bas du portrait : pas de corps coupé net."""
    un = np.ones(img_shape[:2], np.uint8)
    w, h = px(taille_mm[0], dpi), px(taille_mm[1], dpi)
    part = part_tete
    while True:
        m = placer_portrait(tete, taille_mm, dpi, part)
        bas = cv2.warpAffine(un, m, (w, h), flags=cv2.INTER_NEAREST, borderValue=0)[-1].mean()
        if bas >= 0.98 or part >= part_max:
            return m, part
        part = min(part_max, part + 0.02)


def rendre(img, m, taille_mm, fond, dpi=DPI):
    """Applique `m` ; ce qui sort de la photo est rempli du fond. Renvoie (image, couverture),
    couverture = part de chaque bord (haut, bas, gauche, droite) réellement couverte par la photo."""
    w, h = px(taille_mm[0], dpi), px(taille_mm[1], dpi)
    fond_bgr = tuple(int(c) for c in fond[::-1])
    # Forte réduction : warpAffine ne lisse pas avant d'échantillonner (crénelage, grain
    # scintillant sur la peau). On réduit d'abord par moyenne des pixels (INTER_AREA),
    # puis la transformation travaille à l'échelle 1.
    echelle = math.sqrt(abs(np.linalg.det(m[:, :2])))
    if echelle < 0.9:
        sw = max(1, int(round(img.shape[1] * echelle)))
        sh = max(1, int(round(img.shape[0] * echelle)))
        kx, ky = sw / img.shape[1], sh / img.shape[0]
        img = cv2.resize(img, (sw, sh), interpolation=cv2.INTER_AREA)
        m = m.copy()
        m[:, 0] /= kx
        m[:, 1] /= ky
    out = cv2.warpAffine(img, m, (w, h), flags=cv2.INTER_LANCZOS4, borderMode=cv2.BORDER_CONSTANT,
                         borderValue=fond_bgr)
    un = cv2.warpAffine(np.ones(img.shape[:2], np.uint8), m, (w, h), flags=cv2.INTER_NEAREST, borderValue=0)
    couverture = {'haut': float(un[0].mean()), 'bas': float(un[-1].mean()),
                  'gauche': float(un[:, 0].mean()), 'droite': float(un[:, -1].mean())}
    return out, couverture


def ouverture(oeil, angle):
    """Hauteur / largeur d'un œil (repère redressé) : petit = œil fermé ou plissé."""
    if len(oeil) < 3:
        return None
    p = oeil @ rotation(angle).T
    largeur = np.ptp(p[:, 0])
    return float(np.ptp(p[:, 1]) / largeur) if largeur > 0 else None

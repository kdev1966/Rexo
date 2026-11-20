"""Traitement d'une grande image par tuiles qui se chevauchent, commun aux outils du hub
(agrandissement, débruitage, reconstitution) : un modèle qui attend une taille fixe, ou qui
coûterait trop de mémoire sur l'image entière, voit l'image morceau par morceau, sans raccord.

    positions(n, tuile, recouvrement)   débuts des tuiles le long d'un côté de n pixels ; la
                                        dernière tuile finit au bord (toutes ont la même taille)
    fenetre(tuile, recouvrement)        poids de fondu : 1 au centre, rampe sur `recouvrement`
                                        pixels vers chaque bord
    par_tuiles(img, fn, tuile, recouvrement, echelle, taille_fixe, multiple)
                                        applique fn à chaque tuile et assemble les résultats en
                                        les fondant. taille_fixe (modèle à entrée fixe : SCUNet,
                                        LaMa) : toutes les tuiles font `tuile`, l'image est
                                        complétée par réflexion si elle est plus petite ; sinon
                                        (modèle qui accepte toute taille : Real-ESRGAN) les tuiles
                                        du bord sont plus petites, ce qui évite de calculer deux
                                        fois le bord (mesuré : 30 % plus rapide), complétées au
                                        multiple de `multiple` pixels demandé par le modèle
"""

import cv2
import numpy as np


def positions(n, tuile, recouvrement):
    if n <= tuile:
        return [0]
    return list(range(0, n - tuile, tuile - recouvrement)) + [n - tuile]


def _rampe(n, recouvrement):
    r = np.minimum(np.arange(n) + 1, n - np.arange(n)).astype(np.float32)
    return np.minimum(r / recouvrement, 1.0)


def fenetre(tuile, recouvrement, largeur=None):
    """Poids de fondu d'une tuile de `tuile` × `largeur` (carrée si largeur est None)."""
    hy = _rampe(tuile, recouvrement)
    hx = hy if largeur is None or largeur == tuile else _rampe(largeur, recouvrement)
    return (hy[:, None] * hx[None, :])[..., None]


def par_tuiles(img, fn, tuile, recouvrement, echelle=1, taille_fixe=True, multiple=1):
    """Applique `fn` à chaque tuile de `img` (même type que `img`) et assemble ses résultats
    (float32, 3 canaux, taille de la tuile × `echelle`) en les fondant sur le recouvrement.
    Renvoie un float32 de (h * echelle, w * echelle, 3)."""
    h, w = img.shape[:2]
    e = echelle
    if taille_fixe:
        H, W = max(h, tuile), max(w, tuile)
        src = cv2.copyMakeBorder(img, 0, H - h, 0, W - w, cv2.BORDER_REFLECT)
        cases = [(y, x, tuile, tuile) for y in positions(H, tuile, recouvrement)
                 for x in positions(W, tuile, recouvrement)]
    else:
        H, W, src = h, w, img
        pas = tuile - recouvrement
        ys = list(range(0, max(h - recouvrement, 1), pas))
        xs = list(range(0, max(w - recouvrement, 1), pas))
        cases = [(y, x, min(tuile, h - y), min(tuile, w - x)) for y in ys for x in xs]
    acc = np.zeros((H * e, W * e, 3), np.float32)
    poids = np.zeros((H * e, W * e, 1), np.float32)
    fenetres = {}
    for y, x, th, tw in cases:
        morceau = src[y:y + th, x:x + tw]
        ph, pw = -th % multiple, -tw % multiple
        if ph or pw:                               # le modèle veut des côtés multiples de `multiple`
            morceau = cv2.copyMakeBorder(morceau, 0, ph, 0, pw, cv2.BORDER_REFLECT)
        r = fn(morceau)[:th * e, :tw * e]
        if (th, tw) not in fenetres:
            fenetres[(th, tw)] = fenetre(th * e, recouvrement * e, tw * e)
        f = fenetres[(th, tw)]
        acc[y * e:(y + th) * e, x * e:(x + tw) * e] += r * f
        poids[y * e:(y + th) * e, x * e:(x + tw) * e] += f
    return (acc / np.maximum(poids, 1e-6))[:h * e, :w * e]

"""Remplacement du fond par une couleur unie, bords des cheveux nettoyés.

Sur le pourtour des personnes, un pixel à demi transparent mélange la personne et l'ancien
fond. Sa couleur est remplacée par la couleur moyenne de la personne autour de lui
(flou(image × masque) / flou(masque)), puis posée sur le nouveau fond : pas de liseré de
l'ancien fond autour des cheveux. Au cœur de la personne (masque > 0,9), l'image est intacte.
"""

import cv2
import numpy as np


def remplacer(img_bgr, masque, couleur_rvb):
    h, w = masque.shape
    a = np.clip(masque, 0, 1).astype(np.float32)[..., None]
    img = img_bgr.astype(np.float32)
    rayon = max(4.0, max(h, w) / 400.0)
    flou = lambda x: cv2.GaussianBlur(x, (0, 0), rayon)  # noqa: E731
    personne = flou(img * a) / np.maximum(flou(a[..., 0])[..., None], 1e-4)
    coeur = np.clip((a - 0.9) * 10, 0, 1)
    premier_plan = coeur * img + (1 - coeur) * personne
    fond = np.array(couleur_rvb[::-1], np.float32).reshape(1, 1, 3)
    return np.clip(a * premier_plan + (1 - a) * fond + 0.5, 0, 255).astype(np.uint8)

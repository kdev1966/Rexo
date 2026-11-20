"""Mesures de qualité d'une photo, sans modèle (OpenCV), communes aux applications du hub.

    nettete(img)        variance du laplacien sur ZONES × ZONES zones de l'image réduite à
                        COTE_NETTETE pixels ; la zone la plus nette compte (un fond flou derrière
                        un sujet net n'est pas un défaut). Mesuré : photos nettes 71 à 2 900,
                        floutées (mise au point ratée) 2 à 160.
    empreinte(img)      empreinte de différence (dHash, 64 bits, 16 caractères hexadécimaux)
    distance(a, b)      nombre de bits différents entre deux empreintes : 0 pour deux photos
                        identiques à l'œil, 21 et plus pour deux photos différentes (mesuré)
"""

import cv2

COTE_NETTETE = 1024            # côté long pour la netteté (mesure comparable d'une photo à l'autre)
ZONES = 4


def nettete(img):
    h, w = img.shape[:2]
    f = COTE_NETTETE / max(h, w)
    if f < 1:
        img = cv2.resize(img, (round(w * f), round(h * f)), interpolation=cv2.INTER_AREA)
    lap = cv2.Laplacian(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), cv2.CV_64F)
    H, W = lap.shape
    return float(max(lap[i * H // ZONES:(i + 1) * H // ZONES, j * W // ZONES:(j + 1) * W // ZONES].var()
                     for i in range(ZONES) for j in range(ZONES)))


def empreinte(img):
    g = cv2.resize(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), (9, 8), interpolation=cv2.INTER_AREA)
    bits = (g[:, 1:] > g[:, :-1]).flatten()
    return '%016x' % int(''.join('1' if b else '0' for b in bits), 2)


def distance(a, b):
    return bin(int(a, 16) ^ int(b, 16)).count('1')

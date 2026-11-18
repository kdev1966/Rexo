"""Balance des blancs et couleurs, sans modèle d'IA.

Deux méthodes, choisies dans cet ordre en mode « auto » :

1. Le fond d'origine comme charte de gris : en studio il est presque toujours neutre
   (blanc, gris). Sa dominante mesurée (en lumière linéaire, loin des personnes) donne
   les gains rouge, vert et bleu qui le ramènent au neutre ; la même correction vaut pour
   la peau, éclairée par la même lumière. Le fond est mesuré avant d'être remplacé.
2. Sinon (fond coloré, trop petit ou surexposé), la balance d'Apple sur la peau des
   visages (CIFaceBalance), par reto-segment.

Puis, dans les deux cas, l'exposition automatique d'Apple (courbe de tons, ombres et hautes
lumières), sans relief ni vivacité : les couleurs restent naturelles.
"""

import cv2
import numpy as np

from shared.natif import NatifError, executer  # noqa: F401

MODES = ('auto', 'fond', 'apple', 'aucune')
TONS = 'CIToneCurve,CIHighlightShadowAdjust'

FOND_PART_MIN = 0.03        # part de l'image occupée par le fond utilisable
FOND_CHROMA_MAX = 0.30      # au-delà (en linéaire), le fond est coloré, pas une dominante
GAIN_MIN, GAIN_MAX = 0.75, 1.33
# Force de la correction : entière pour une légère dominante (écart <= 0,10), réduite à
# moitié à l'approche de FOND_CHROMA_MAX : un fond franchement teinté peut être un choix
# du studio (fond beige), pas une lumière à corriger ; corriger tout refroidit la peau.
FORCE_ECART = (0.10, FOND_CHROMA_MAX)
FORCE_MIN = 0.5


def lineaire(img8):
    x = img8.astype(np.float32) / 255.0
    return np.where(x <= 0.04045, x / 12.92, ((x + 0.055) / 1.055) ** 2.4)


def srgb8(lin):
    lin = np.clip(lin, 0.0, 1.0)
    x = np.where(lin <= 0.0031308, lin * 12.92, 1.055 * np.power(lin, 1 / 2.4) - 0.055)
    return np.clip(x * 255.0 + 0.5, 0, 255).astype(np.uint8)


def gains_fond(img_bgr, masque):
    """Gains (B, V, R) qui rendent le fond neutre, ou (None, raison) si le fond ne s'y prête pas.

    masque : personnes de 0 à 1 (Apple Vision). Le fond retenu est loin des personnes et ni
    bouché ni brûlé.
    """
    h, w = masque.shape
    marge = max(3, int(max(h, w) * 0.02))
    personne = cv2.dilate((masque > 0.05).astype(np.uint8), np.ones((2 * marge + 1,) * 2, np.uint8))
    gris = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    fond = (personne == 0) & (gris > 30) & (img_bgr.max(axis=2) < 250)
    part = fond.mean()
    if part < FOND_PART_MIN:
        return None, 'fond trop petit (%.1f %% de la photo)' % (part * 100)
    moy = lineaire(img_bgr[fond]).mean(axis=0)
    chroma = float((moy.max() - moy.min()) / max(moy.max(), 1e-6))
    if chroma > FOND_CHROMA_MAX:
        return None, 'fond coloré (écart %.2f)' % chroma
    a, b = FORCE_ECART
    force = 1.0 - (1.0 - FORCE_MIN) * float(np.clip((chroma - a) / (b - a), 0, 1))
    g = np.clip(moy.mean() / np.maximum(moy, 1e-6), GAIN_MIN, GAIN_MAX) ** force
    return g.astype(np.float32), 'fond neutre (%.1f %% de la photo, écart %.2f, correction à %d %%)' % (
        part * 100, chroma, round(force * 100))


def appliquer_gains(img_bgr, gains):
    return srgb8(lineaire(img_bgr) * gains.reshape(1, 1, 3))


def corriger(src_png, masque, travail, mode='auto'):
    """Corrige les couleurs de `src_png` ; renvoie (image BGR, rapport)."""
    if mode not in MODES:
        raise ValueError('mode de couleurs inconnu : %s' % mode)
    img = cv2.imread(str(src_png), cv2.IMREAD_COLOR)
    rapport = {'mode': mode}
    if mode == 'aucune':
        rapport['methode'] = 'aucune'
        return img, rapport
    gains, raison = (None, 'non demandé') if mode == 'apple' else gains_fond(img, masque)
    rapport['fond'] = raison
    if gains is not None:
        img = appliquer_gains(img, gains)
        rapport['methode'] = 'fond neutre'
        rapport['gains_rvb'] = [round(float(x), 3) for x in gains[::-1]]
        garder = TONS
    elif mode == 'fond':
        rapport['methode'] = 'aucune (%s)' % raison
        garder = TONS
    else:
        rapport['methode'] = 'balance d\'Apple sur la peau'
        garder = 'CIFaceBalance,' + TONS
    entree, sortie = travail / 'couleurs_entree.png', travail / 'couleurs.png'
    cv2.imwrite(str(entree), img)
    res = executer('balance', entree, sortie, '--keep', garder)
    rapport['apple'] = res.get('applied', [])
    if 'face_balance' in res:
        rapport['balance_peau'] = res['face_balance']
    return cv2.imread(str(sortie), cv2.IMREAD_COLOR), rapport

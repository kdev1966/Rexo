"""Balance des blancs et couleurs, sans modèle d'IA.

Principe : ne corriger que ce qui est manifestement faux. Une photo de studio est souvent
déjà bien réglée, et toute correction devinée l'abîme.

1. Le fond d'origine comme charte de gris. Sa dominante est mesurée en lumière linéaire,
   loin des personnes, avant que le fond soit remplacé.
   - écart < 0,10 : fond presque neutre, la teinte vient de la toile, pas de la lumière :
     aucune correction (une vraie erreur de balance, une lampe chaude par exemple, donne
     un écart bien plus fort) ;
   - de 0,10 à 0,15 : correction croissante, entière à 0,15 ;
   - de 0,15 à 0,30 : correction décroissante, jusqu'à la moitié : un fond franchement
     teinté peut être un choix du studio (fond beige) ;
   - au-delà de 0,30 : fond coloré, il ne sert pas de référence.
2. Sinon, la peau. Dans l'espace YIQ, l'axe I suit la teinte de la peau humaine : une peau
   bien rendue a une composante Q (vert - / magenta +) proche de 0, quelle que soit la
   carnation. Mesuré sur des photos justes : Q de +0,01 à +0,04. Si Q est hors de
   PEAU_Q, la balance d'Apple sur la peau (CIFaceBalance) corrige ; sinon rien. On n'appelle
   pas CIFaceBalance par défaut : sur des peaux justes, elle ajoute du rose (Q +0,035 à +0,05).

Puis l'exposition automatique d'Apple (courbe de tons, ombres et hautes lumières), sans
relief ni vivacité.
"""

import cv2
import numpy as np

from shared.natif import NatifError, executer  # noqa: F401

MODES = ('auto', 'fond', 'apple', 'aucune')
TONS = 'CIToneCurve,CIHighlightShadowAdjust'

FOND_PART_MIN = 0.03        # part de l'image occupée par le fond utilisable
FOND_NEUTRE = 0.10          # écart (linéaire) sous lequel le fond est jugé neutre
FOND_PLEIN = 0.15           # correction entière à partir de cet écart
FOND_CHROMA_MAX = 0.30      # au-delà, le fond est coloré, pas une dominante
FORCE_MIN = 0.5             # correction à FOND_CHROMA_MAX
GAIN_MIN, GAIN_MAX = 0.75, 1.33
PEAU_Q = (-0.005, 0.06)     # teinte de peau plausible (Q / Y), hors de quoi on corrige


def lineaire(img8):
    x = img8.astype(np.float32) / 255.0
    return np.where(x <= 0.04045, x / 12.92, ((x + 0.055) / 1.055) ** 2.4)


def srgb8(lin):
    lin = np.clip(lin, 0.0, 1.0)
    x = np.where(lin <= 0.0031308, lin * 12.92, 1.055 * np.power(lin, 1 / 2.4) - 0.055)
    return np.clip(x * 255.0 + 0.5, 0, 255).astype(np.uint8)


def force_fond(chroma):
    """Part de la correction appliquée selon l'écart du fond (voir l'en-tête)."""
    if chroma < FOND_NEUTRE or chroma > FOND_CHROMA_MAX:
        return 0.0
    if chroma < FOND_PLEIN:
        return (chroma - FOND_NEUTRE) / (FOND_PLEIN - FOND_NEUTRE)
    return 1.0 - (1.0 - FORCE_MIN) * (chroma - FOND_PLEIN) / (FOND_CHROMA_MAX - FOND_PLEIN)


def gains_fond(img_bgr, masque):
    """Gains (B, V, R) qui rendent le fond neutre, avec l'état du fond.

    Renvoie (gains ou None, raison, état) ; état : 'dominante' (gains à appliquer),
    'neutre' (rien à corriger), 'colore' ou 'petit' (le fond ne sert pas de référence).
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
        return None, 'fond trop petit (%.1f %% de la photo)' % (part * 100), 'petit'
    moy = lineaire(img_bgr[fond]).mean(axis=0)
    chroma = float((moy.max() - moy.min()) / max(moy.max(), 1e-6))
    if chroma > FOND_CHROMA_MAX:
        return None, 'fond coloré (écart %.2f)' % chroma, 'colore'
    if chroma < FOND_NEUTRE:
        return None, 'fond presque neutre (écart %.2f) : rien à corriger' % chroma, 'neutre'
    force = force_fond(chroma)
    g = np.clip(moy.mean() / np.maximum(moy, 1e-6), GAIN_MIN, GAIN_MAX) ** force
    return g.astype(np.float32), 'dominante du fond (écart %.2f), correction à %d %%' % (
        chroma, round(force * 100)), 'dominante'


def teinte_peau(img_bgr, pupilles):
    """Teinte de la peau des joues (I / Y, Q / Y en YIQ), sans ombres ni reflets ; None si
    la zone est vide. pupilles : 2 × 2 (x, y), de gauche à droite."""
    (xl, yl), (xr, yr) = pupilles
    d = xr - xl
    y0, y1 = int(max(yl, yr) + 0.25 * d), int(max(yl, yr) + 0.75 * d)
    x0, x1 = int(xl - 0.25 * d), int(xr + 0.25 * d)
    h, w = img_bgr.shape[:2]
    z = img_bgr[max(0, y0):min(h, y1), max(0, x0):min(w, x1)].reshape(-1, 3).astype(np.float64)[:, ::-1] / 255
    if len(z) < 50:
        return None
    lum = z @ np.array([0.299, 0.587, 0.114])
    z = z[(lum >= np.percentile(lum, 20)) & (lum <= np.percentile(lum, 95))]
    if len(z) == 0:
        return None
    r, v, b = z.mean(axis=0)
    y = 0.299 * r + 0.587 * v + 0.114 * b
    if y <= 0:
        return None
    return (0.596 * r - 0.274 * v - 0.322 * b) / y, (0.211 * r - 0.523 * v + 0.312 * b) / y


def appliquer_gains(img_bgr, gains):
    return srgb8(lineaire(img_bgr) * gains.reshape(1, 1, 3))


def corriger(src_png, masque, travail, mode='auto', pupilles=None):
    """Corrige les couleurs de `src_png` ; renvoie (image BGR, rapport).

    Modes : auto (fond, sinon peau si elle est hors teinte, sinon rien), fond (fond
    seulement), apple (balance d'Apple sur la peau, toujours), aucune (ni balance ni
    exposition)."""
    if mode not in MODES:
        raise ValueError('mode de couleurs inconnu : %s' % mode)
    img = cv2.imread(str(src_png), cv2.IMREAD_COLOR)
    rapport = {'mode': mode}
    peau = teinte_peau(img, pupilles) if pupilles is not None else None
    if peau:
        rapport['peau_avant'] = {'I': round(peau[0], 3), 'Q': round(peau[1], 4)}
    if mode == 'aucune':
        rapport['methode'] = 'aucune'
        return img, rapport
    garder = TONS
    if mode == 'apple':
        rapport['methode'] = 'balance d\'Apple sur la peau'
        garder = 'CIFaceBalance,' + TONS
    else:
        gains, raison, etat = gains_fond(img, masque)
        rapport['fond'] = raison
        if gains is not None:
            img = appliquer_gains(img, gains)
            rapport['methode'] = 'dominante du fond corrigée'
            rapport['gains_rvb'] = [round(float(x), 3) for x in gains[::-1]]
        elif mode == 'fond' or etat == 'neutre':
            rapport['methode'] = 'aucune balance (%s)' % raison
        elif peau is not None and PEAU_Q[0] <= peau[1] <= PEAU_Q[1]:
            rapport['methode'] = 'aucune balance (peau de teinte naturelle)'
        else:
            rapport['methode'] = 'balance d\'Apple sur la peau (peau hors teinte)'
            garder = 'CIFaceBalance,' + TONS
    entree, sortie = travail / 'couleurs_entree.png', travail / 'couleurs.png'
    cv2.imwrite(str(entree), img)
    res = executer('balance', entree, sortie, '--keep', garder)
    rapport['apple'] = res.get('applied', [])
    if 'face_balance' in res:
        rapport['balance_peau'] = res['face_balance']
    out = cv2.imread(str(sortie), cv2.IMREAD_COLOR)
    apres = teinte_peau(out, pupilles) if pupilles is not None else None
    if apres:
        rapport['peau_apres'] = {'I': round(apres[0], 3), 'Q': round(apres[1], 4)}
    return out, rapport

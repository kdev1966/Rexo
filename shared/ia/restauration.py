"""Restauration d'image par IA, commune aux applications du hub (ONNX, processeur seul).

    rayures(img)      masque des rayures, fissures et déchirures : détecteur de « Bringing Old
                      Photos Back to Life » (Microsoft, MIT)
    reconstituer(img, masque)   LaMa (Samsung, Apache-2.0) : par tuiles de 512 à la
                      résolution de l'image (lignes fines), ou sur l'image réduite à 512 pour
                      les grands trous (tout le contexte)
    grain(img)        grain du film : écart type du bruit sur les zones unies (Immerkær), sans modèle
    debruiter(img)    SCUNet (Apache-2.0), par tuiles de 512 qui se chevauchent (lent : environ
                      16 s par tuile sur le MacBook)
    disponible()      détecteur de rayures et LaMa installés

Modèles : rayures-anciennes, lama-512, scunet-512 (catalogue commun shared/ia). Images BGR uint8.
"""

import cv2
import numpy as np

from . import present, session

COTE_DETECTION = 256          # le détecteur voit l'image au côté court de 256 (comme Microsoft)
SEUIL_RAYURES = 0.4           # probabilité au-dessus de laquelle un pixel est une rayure
TUILE = 512                   # entrée fixe de LaMa
RECOUVREMENT = 96


def disponible():
    return present('rayures-anciennes') and present('lama-512')


# ---------- rayures, fissures, déchirures ----------

def rayures(img):
    """Masque 0/1 des rayures et fissures, légèrement élargi (bord des fissures)."""
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    f = COTE_DETECTION / min(g.shape)
    h, w = (max(16, int(round(v * f / 16)) * 16) for v in g.shape)
    x = cv2.resize(g, (w, h), interpolation=cv2.INTER_AREA).astype(np.float32) / 255
    s = session('rayures-anciennes')
    p = s.run(None, {s.get_inputs()[0].name: ((x - 0.5) / 0.5)[None, None]})[0][0, 0]
    p = cv2.resize(p, (g.shape[1], g.shape[0]), interpolation=cv2.INTER_LINEAR)
    m = (p >= SEUIL_RAYURES).astype(np.uint8)
    k = max(3, int(round(5 * max(g.shape) / 640))) | 1
    return cv2.dilate(m, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))


# ---------- reconstitution (LaMa) ----------

def _lama_512(img, m):
    """Une passe de LaMa sur une image et un masque de 512 × 512."""
    s = session('lama-512')
    x = cv2.cvtColor(img, cv2.COLOR_BGR2RGB).astype(np.float32).transpose(2, 0, 1)[None] / 255
    mk = m.astype(np.float32)[None, None]
    y = s.run(None, {'image': x * (1 - mk), 'mask': mk})[0][0]       # le trou est vidé, comme dans LaMa
    if y.max() > 2:
        y = y / 255
    return cv2.cvtColor((np.clip(y.transpose(1, 2, 0), 0, 1) * 255).round().astype(np.uint8), cv2.COLOR_RGB2BGR)


def _positions(n):
    if n <= TUILE:
        return [0]
    return list(range(0, n - TUILE, TUILE - RECOUVREMENT)) + [n - TUILE]


def _reduite(img, m):
    """LaMa sur l'image réduite (ou complétée) à 512 × 512 ; résultat à la taille d'origine."""
    h, w = m.shape
    f = TUILE / max(h, w)
    sw, sh = max(1, round(w * f)), max(1, round(h * f))
    a = cv2.resize(img, (sw, sh), interpolation=cv2.INTER_AREA if f < 1 else cv2.INTER_CUBIC)
    b = (cv2.resize(m.astype(np.float32), (sw, sh), interpolation=cv2.INTER_LINEAR) > 0.1).astype(np.uint8)
    a = cv2.copyMakeBorder(a, 0, TUILE - sh, 0, TUILE - sw, cv2.BORDER_REFLECT)
    b = cv2.copyMakeBorder(b, 0, TUILE - sh, 0, TUILE - sw, cv2.BORDER_CONSTANT, value=0)
    return cv2.resize(_lama_512(a, b)[:sh, :sw], (w, h), interpolation=cv2.INTER_CUBIC)


def reconstituer(img, m, grand=False):
    """Reconstitue les pixels de `m` (0/1). grand : grands trous, sur l'image réduite à 512
    (LaMa voit tout le contexte) ; sinon par tuiles de 512 à la résolution de l'image (les
    lignes fines restent nettes). Une image d'à peine plus de 512 px est traitée d'un bloc."""
    if not m.any():
        return img
    h, w = m.shape
    if grand or max(h, w) <= TUILE * 1.25:
        r = _reduite(img, m)
        out = img.copy()
        out[m > 0] = r[m > 0]
        return out
    H, W = max(h, TUILE), max(w, TUILE)
    out = cv2.copyMakeBorder(img, 0, H - h, 0, W - w, cv2.BORDER_REFLECT)
    mk = cv2.copyMakeBorder(m, 0, H - h, 0, W - w, cv2.BORDER_CONSTANT, value=0)
    for y in _positions(H):
        for x in _positions(W):
            t = mk[y:y + TUILE, x:x + TUILE]
            if t.any():
                r = _lama_512(out[y:y + TUILE, x:x + TUILE], t)
                sel = t > 0
                out[y:y + TUILE, x:x + TUILE][sel] = r[sel]
    return out[:h, :w]


# ---------- grain du film ----------

SEUIL_GRAIN = 1.2             # écart type du bruit (sur 255) au-dessus duquel on débruite
# Mesuré : tirages argentiques scannés 2 et plus ; photos JPEG déjà lissées 0,2 à 0,9
GARDE_ORIGINAL = 0.15         # part de l'original remise dans le résultat (pas d'aspect lissé)
RECOUVREMENT_GRAIN = 64


def grain(img):
    """Écart type du bruit (sur 255), par le filtre de Laplace sur les zones les plus unies
    (estimateur d'Immerkær) : les détails n'y sont pas comptés comme du grain."""
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).astype(np.float32)
    k = np.array([[1, -2, 1], [-2, 4, -2], [1, -2, 1]], np.float32)
    r = cv2.filter2D(g, -1, k)
    grad = cv2.magnitude(cv2.Sobel(g, cv2.CV_32F, 1, 0), cv2.Sobel(g, cv2.CV_32F, 0, 1))
    uni = grad <= np.percentile(grad, 40)          # <= : un fond parfaitement uni a un gradient nul
    if not uni.any():
        return 0.0
    return float(np.sqrt(np.pi / 2) * np.abs(r[uni]).mean() / 6)


def debruiter(img):
    """SCUNet par tuiles de 512 qui se chevauchent, fondues entre elles (pas de raccord),
    puis une part de l'original remise."""
    s = session('scunet-512')
    nom = s.get_inputs()[0].name
    h, w = img.shape[:2]
    H, W = max(h, TUILE), max(w, TUILE)
    src = cv2.copyMakeBorder(img, 0, H - h, 0, W - w, cv2.BORDER_REFLECT)
    acc = np.zeros((H, W, 3), np.float32)
    poids = np.zeros((H, W, 1), np.float32)
    rampe = np.minimum(np.arange(TUILE) + 1, TUILE - np.arange(TUILE)).astype(np.float32)
    fen = np.minimum(rampe / RECOUVREMENT_GRAIN, 1.0)
    fen = (fen[:, None] * fen[None, :])[..., None]
    pas = TUILE - RECOUVREMENT_GRAIN
    ys = [0] if H <= TUILE else list(range(0, H - TUILE, pas)) + [H - TUILE]
    xs = [0] if W <= TUILE else list(range(0, W - TUILE, pas)) + [W - TUILE]
    for y in ys:
        for x in xs:
            t = cv2.cvtColor(src[y:y + TUILE, x:x + TUILE], cv2.COLOR_BGR2RGB).astype(np.float32)
            r = s.run(None, {nom: (t.transpose(2, 0, 1)[None] / 255)})[0][0].transpose(1, 2, 0)
            acc[y:y + TUILE, x:x + TUILE] += cv2.cvtColor(np.clip(r, 0, 1), cv2.COLOR_RGB2BGR) * 255 * fen
            poids[y:y + TUILE, x:x + TUILE] += fen
    out = (acc / np.maximum(poids, 1e-6))[:h, :w]
    out = out * (1 - GARDE_ORIGINAL) + img.astype(np.float32) * GARDE_ORIGINAL
    return np.clip(out, 0, 255).round().astype(np.uint8)

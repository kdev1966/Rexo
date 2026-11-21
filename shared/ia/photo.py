"""Outils d'image par IA, communs aux applications du hub (ONNX, processeur seul) :
agrandissement, visages restaurés, colorisation.

Modèles du projet libre FaceFusion (github.com/facefusion/facefusion-assets, models-3.0.0),
déclarés dans le catalogue commun shared/ia/modeles/ :
    real-esrgan-x2  agrandissement x2 (Real-ESRGAN)
    gfpgan-1.4      restauration des visages (GFPGAN 1.4)
    ddcolor         colorisation (DDColor, grand modèle : secours)
et, depuis Hugging Face (shared/ia/modeles/) :
    ddcolor-tiny    colorisation (DDColor tiny, 7 fois plus léger ; préféré)
Les pré/post-traitements reprennent ceux de FaceFusion et des auteurs de DDColor.
"""

import cv2
import numpy as np

from . import executer as _run, present as available, session as _session  # noqa: F401
from .tuiles import par_tuiles


# ---------- agrandissement ----------

def upscale_x2(img, tile=192, overlap=16):
    """Real-ESRGAN x2 par tuiles de `tile` pixels qui se chevauchent de 2 × `overlap` (mémoire
    limitée), fondues entre elles (shared/ia/tuiles). img : BGR uint8."""
    rgb = img[:, :, ::-1].astype(np.float32) / 255.0

    def agrandir(t):                     # côtés pairs : le modèle replie l'image par blocs 2 × 2
        return _run('real-esrgan-x2', np.ascontiguousarray(t.transpose(2, 0, 1)[None]))[0].transpose(1, 2, 0)

    out = par_tuiles(rgb, agrandir, tile, overlap * 2, echelle=2, taille_fixe=False, multiple=2)
    return (np.clip(out, 0, 1) * 255).round().astype(np.uint8)[:, :, ::-1].copy()


# ---------- visages ----------

# Gabarit FFHQ 512 (FaceFusion) : œil gauche, œil droit, nez, coin gauche, coin droit de la bouche
_FFHQ_512 = np.array([[0.37691676, 0.46864664], [0.62285697, 0.46912813], [0.50123859, 0.61331904],
                      [0.39308822, 0.72541100], [0.61150205, 0.72490465]], np.float32) * 512


def _face_points(face):
    """Cinq repères (œil gauche et droit de l'image, nez, coins gauche et droit de la bouche)
    d'un visage de shared.vision.visages (dict) ou d'un objet qui les porte (eye_l…)."""
    if isinstance(face, dict):
        p = np.asarray(face['points'], np.float32).copy()
        if p[3, 0] > p[4, 0]:
            p[[3, 4]] = p[[4, 3]]
        return p
    return np.array([face.eye_l, face.eye_r, face.nose, face.mouth_l, face.mouth_r], np.float32)


def _box_mask(size, blur=0.3, padding=0.05):
    m = np.ones((size, size), np.float32)
    b = int(size * blur * 0.5)
    p = int(size * padding)
    m[:max(b, p), :] = 0
    m[-max(b, p):, :] = 0
    m[:, :max(b, p)] = 0
    m[:, -max(b, p):] = 0
    if b > 0:
        m = cv2.GaussianBlur(m, (0, 0), b * 0.25)
    return m


def restore_faces(img, faces, blend=0.8):
    """GFPGAN 1.4 sur chaque visage, recollé avec un masque doux. `faces` : visages de
    shared.vision.visages, ou objets portant les repères eye_l, eye_r, nose, mouth_l, mouth_r."""
    out = img.astype(np.float32)
    for f in faces:
        M, _ = cv2.estimateAffinePartial2D(_face_points(f), _FFHQ_512, method=cv2.LMEDS)
        if M is None:
            continue
        crop = cv2.warpAffine(img, M, (512, 512), borderMode=cv2.BORDER_REPLICATE, flags=cv2.INTER_AREA)
        x = (crop[:, :, ::-1].astype(np.float32) / 255.0 - 0.5) / 0.5
        y = _run('gfpgan-1.4', np.ascontiguousarray(x.transpose(2, 0, 1)[None]))[0]
        y = ((np.clip(y, -1, 1) + 1) / 2).transpose(1, 2, 0)[:, :, ::-1] * 255.0
        inv = cv2.invertAffineTransform(M)
        h, w = img.shape[:2]
        back = cv2.warpAffine(y, inv, (w, h), borderMode=cv2.BORDER_REPLICATE)
        mask = cv2.warpAffine(_box_mask(512), inv, (w, h))[:, :, None] * blend
        out = out * (1 - mask) + back * mask
    return np.clip(out, 0, 255).round().astype(np.uint8)


# ---------- colorisation ----------

DOMINANTE_RETIREE = 0.7      # part de la dominante globale retirée (DDColor tire tout vers le rouge)
CHROMA_MAX_TINY = 48.0


def colorize(img, fond=None):
    """Colorisation : DDColor tiny si installé (préféré), sinon le grand DDColor. fond :
    masque (0..1) d'un fond de studio repeint, qui reçoit une seule teinte sobre."""
    out = colorize_tiny(img) if available('ddcolor-tiny') else colorize_ddcolor(img)
    if fond is not None and fond.shape == img.shape[:2]:
        out = _fond_sobre(img, out, fond)
    return out


TEINTE_FOND = 0.45           # part de la teinte proposée par le modèle gardée pour un fond repeint


def _fond_sobre(gris, couleur, fond):
    """Fond de studio repeint : face à une surface lisse, sans repère, le modèle invente des
    dégradés de couleurs ; le fond reçoit une seule teinte, sa médiane atténuée."""
    lab = cv2.cvtColor(couleur, cv2.COLOR_BGR2LAB).astype(np.float32)
    sur = fond > 0.9
    if sur.mean() < 0.05:
        return couleur
    a0 = 128 + (np.median(lab[..., 1][sur]) - 128) * TEINTE_FOND
    b0 = 128 + (np.median(lab[..., 2][sur]) - 128) * TEINTE_FOND
    L = cv2.cvtColor(gris, cv2.COLOR_BGR2LAB)[..., 0].astype(np.float32)
    uni = cv2.cvtColor(np.dstack([L, np.full_like(L, a0), np.full_like(L, b0)]).astype(np.uint8), cv2.COLOR_LAB2BGR)
    f = fond.astype(np.float32)[..., None]
    return np.clip(couleur * (1 - f) + uni * f, 0, 255).astype(np.uint8)


def _ab_ddcolor(name, img):
    """Canaux a/b prédits par DDColor (`name`) à 512 px, à la taille de l'image, et la
    luminance L d'origine (Lab float d'OpenCV, comme à l'entraînement de DDColor)."""
    gray = cv2.cvtColor(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), cv2.COLOR_GRAY2RGB).astype(np.float32) / 255.0
    L = cv2.cvtColor(gray, cv2.COLOR_RGB2LAB)[:, :, :1]
    lab0 = np.concatenate([L, np.zeros_like(L), np.zeros_like(L)], axis=-1)
    x = cv2.resize(cv2.cvtColor(lab0, cv2.COLOR_LAB2RGB), (512, 512), interpolation=cv2.INTER_AREA)
    ab = _run(name, np.ascontiguousarray(x.transpose(2, 0, 1)[None].astype(np.float32)))[0]
    ab = cv2.resize(ab.transpose(1, 2, 0), (img.shape[1], img.shape[0]), interpolation=cv2.INTER_CUBIC)
    return L, ab.astype(np.float32)


def _lab_vers_bgr(L, ab):
    out = cv2.cvtColor(np.concatenate([L, ab], axis=-1).astype(np.float32), cv2.COLOR_LAB2BGR)
    return (np.clip(out, 0, 1) * 255).round().astype(np.uint8)


def colorize_tiny(img):
    """DDColor tiny. Couleurs lissées, atténuées dans les noirs et les blancs profonds. La dominante globale (médiane de a/b sur les zones les moins colorées :
    fonds, murs, vêtements neutres) est retirée à DOMINANTE_RETIREE : le modèle plonge souvent
    toute l'image dans le rouge-orangé ; les couleurs propres à chaque objet restent."""
    L, ab = _ab_ddcolor('ddcolor-tiny', img)
    # couleurs lissées (plaques isolées), puis presque rien dans les noirs et les blancs
    # profonds : des cheveux noirs ne sont ni rouges ni bleus (L de 0 à 100)
    sigma = max(1.0, max(img.shape[:2]) / 250.0)
    ab = cv2.GaussianBlur(ab, (0, 0), sigma)
    l = L[:, :, 0]
    ab = ab * (np.clip((l - 8.0) / 32.0, 0.1, 1.0) * np.clip((99.0 - l) / 14.0, 0.2, 1.0))[..., None]
    chroma = np.sqrt((ab ** 2).sum(axis=2))
    neutres = chroma < np.percentile(chroma, 60)
    ab = ab - DOMINANTE_RETIREE * np.median(ab[neutres], axis=0)
    chroma = np.sqrt((ab ** 2).sum(axis=2, keepdims=True))
    ab = ab * np.minimum(1.0, CHROMA_MAX_TINY / np.maximum(chroma, 1e-6))
    return _lab_vers_bgr(L, ab)


def colorize_ddcolor(img, max_chroma=34.0):
    """Grand DDColor (secours) : prédit a/b à 512 px, recombinés avec la luminance d'origine."""
    L, ab = _ab_ddcolor('ddcolor', img)
    # DDColor tire les cheveux et vêtements sombres vers le rouge : correction dans les tons sombres
    from .analyse import correct_casts
    ab = correct_casts(L[:, :, 0], ab, max(img.shape[:2]), max_l=55.0)
    chroma = np.sqrt((ab ** 2).sum(axis=2, keepdims=True))
    ab = ab * np.minimum(1.0, max_chroma / np.maximum(chroma, 1e-6))
    return _lab_vers_bgr(L, ab)

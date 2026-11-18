"""Modèles d'image IA locaux (ONNX, processeur seul) : agrandissement, visages, colorisation.

Modèles du projet libre FaceFusion (github.com/facefusion/facefusion-assets, models-3.0.0),
déclarés dans le catalogue partagé (shared/modeles/catalogue.json) :
    real_esrgan_x2  agrandissement x2 (Real-ESRGAN)
    gfpgan_1.4      restauration des visages (GFPGAN 1.4)
    ddcolor         colorisation (DDColor)
Les pré/post-traitements reprennent ceux de FaceFusion.
"""

import cv2
import numpy as np

from shared import modeles as catalogue

_sessions = {}


def available(name):
    return catalogue.present(name)


def _session(name):
    if name not in _sessions:
        import onnxruntime as ort
        opts = ort.SessionOptions()
        opts.log_severity_level = 3
        _sessions[name] = ort.InferenceSession(str(catalogue.chemin(name)), opts,
                                               providers=['CPUExecutionProvider'])
    return _sessions[name]


def _run(name, x):
    s = _session(name)
    return s.run(None, {s.get_inputs()[0].name: x})[0]


# ---------- agrandissement ----------

def upscale_x2(img, tile=192, overlap=16):
    """Real-ESRGAN x2 par tuiles (mémoire limitée). img : BGR uint8."""
    h, w = img.shape[:2]
    rgb = img[:, :, ::-1].astype(np.float32) / 255.0
    out = np.zeros((h * 2, w * 2, 3), np.float32)
    weight = np.zeros((h * 2, w * 2, 1), np.float32)
    step = tile - overlap * 2
    for y in range(0, h, step):
        for x in range(0, w, step):
            y0, x0 = max(0, y - overlap), max(0, x - overlap)
            y1, x1 = min(h, y + step + overlap), min(w, x + step + overlap)
            patch = rgb[y0:y1, x0:x1]
            ph, pw = patch.shape[:2]
            # le modèle replie l'image par blocs 2x2 : dimensions paires obligatoires
            patch = np.pad(patch, ((0, ph % 2), (0, pw % 2), (0, 0)), mode='reflect')
            res = _run('real_esrgan_x2', np.ascontiguousarray(patch.transpose(2, 0, 1)[None]))[0]
            res = res.transpose(1, 2, 0)[:ph * 2, :pw * 2]
            # on ne garde que le centre de la tuile, avec un fondu sur la marge
            wy = np.ones((res.shape[0], 1), np.float32)
            wx = np.ones((1, res.shape[1]), np.float32)
            ramp = overlap * 2
            if y0 > 0:
                wy[:ramp, 0] = np.linspace(0, 1, ramp)
            if y1 < h:
                wy[-ramp:, 0] = np.linspace(1, 0, ramp)
            if x0 > 0:
                wx[0, :ramp] = np.linspace(0, 1, ramp)
            if x1 < w:
                wx[0, -ramp:] = np.linspace(1, 0, ramp)
            wgt = (wy * wx)[:, :, None]
            out[y0 * 2:y1 * 2, x0 * 2:x1 * 2] += res * wgt
            weight[y0 * 2:y1 * 2, x0 * 2:x1 * 2] += wgt
    out = out / np.maximum(weight, 1e-6)
    return (np.clip(out, 0, 1) * 255).round().astype(np.uint8)[:, :, ::-1].copy()


# ---------- visages ----------

# Gabarit FFHQ 512 (FaceFusion) : œil gauche, œil droit, nez, coin gauche, coin droit de la bouche
_FFHQ_512 = np.array([[0.37691676, 0.46864664], [0.62285697, 0.46912813], [0.50123859, 0.61331904],
                      [0.39308822, 0.72541100], [0.61150205, 0.72490465]], np.float32) * 512


def _face_points(face):
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
    """GFPGAN 1.4 sur chaque visage (repères PhotoCraft), recollé avec un masque doux."""
    out = img.astype(np.float32)
    for f in faces:
        M, _ = cv2.estimateAffinePartial2D(_face_points(f), _FFHQ_512, method=cv2.LMEDS)
        if M is None:
            continue
        crop = cv2.warpAffine(img, M, (512, 512), borderMode=cv2.BORDER_REPLICATE, flags=cv2.INTER_AREA)
        x = (crop[:, :, ::-1].astype(np.float32) / 255.0 - 0.5) / 0.5
        y = _run('gfpgan_1.4', np.ascontiguousarray(x.transpose(2, 0, 1)[None]))[0]
        y = ((np.clip(y, -1, 1) + 1) / 2).transpose(1, 2, 0)[:, :, ::-1] * 255.0
        inv = cv2.invertAffineTransform(M)
        h, w = img.shape[:2]
        back = cv2.warpAffine(y, inv, (w, h), borderMode=cv2.BORDER_REPLICATE)
        mask = cv2.warpAffine(_box_mask(512), inv, (w, h))[:, :, None] * blend
        out = out * (1 - mask) + back * mask
    return np.clip(out, 0, 255).round().astype(np.uint8)


# ---------- colorisation ----------

def colorize_ddcolor(img, max_chroma=34.0):
    """DDColor : prédit les canaux a/b à 512 px, recombinés avec la luminance d'origine."""
    s = _session('ddcolor')
    size = s.get_inputs()[0].shape[2] if isinstance(s.get_inputs()[0].shape[2], int) else 512
    gray = cv2.cvtColor(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), cv2.COLOR_GRAY2RGB).astype(np.float32) / 255.0
    L = cv2.cvtColor(gray, cv2.COLOR_RGB2LAB)[:, :, :1]
    lab0 = np.concatenate([L, np.zeros_like(L), np.zeros_like(L)], axis=-1)
    x = cv2.resize(cv2.cvtColor(lab0, cv2.COLOR_LAB2RGB), (size, size))
    ab = _run('ddcolor', np.ascontiguousarray(x.transpose(2, 0, 1)[None].astype(np.float32)))[0]
    ab = cv2.resize(ab.transpose(1, 2, 0), (img.shape[1], img.shape[0]), interpolation=cv2.INTER_CUBIC)
    # DDColor tire les cheveux et vêtements sombres vers le rouge : correction dans les tons sombres
    from .analyse import correct_casts
    ab = correct_casts(L[:, :, 0], ab.astype(np.float32), max(img.shape[:2]), max_l=55.0)
    chroma = np.sqrt((ab ** 2).sum(axis=2, keepdims=True))
    ab = ab * np.minimum(1.0, max_chroma / np.maximum(chroma, 1e-6))
    out = cv2.cvtColor(np.concatenate([L, ab], axis=-1).astype(np.float32), cv2.COLOR_LAB2BGR)
    return (np.clip(out, 0, 1) * 255).round().astype(np.uint8)

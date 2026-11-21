"""Analyse d'image en Python (OpenCV) : masques de peau et de maquillage, rayures, colorisation."""

import math

import cv2
import numpy as np



# ---------- utilitaires ----------

def save_mask(mask, path):
    """Enregistre un masque 0..1 en PNG RVB (lisible comme sélection par PhotoCraft)."""
    m8 = (np.clip(mask, 0, 1) * 255).astype(np.uint8)
    cv2.imwrite(str(path), cv2.cvtColor(m8, cv2.COLOR_GRAY2BGR))


def coverage(mask):
    return float(np.clip(mask, 0, 1).mean())


def _soft(mask, sigma):
    sigma = max(0.5, sigma)
    k = int(sigma * 3) * 2 + 1
    return cv2.GaussianBlur(mask, (k, k), sigma)


def _ellipse(shape, center, axes, angle_deg, value=1.0):
    m = np.zeros(shape[:2], np.float32)
    cv2.ellipse(m, (int(round(center[0])), int(round(center[1]))),
                (max(1, int(round(axes[0]))), max(1, int(round(axes[1])))),
                angle_deg, 0, 360, value, -1)
    return m


class Face:
    """Visage détecté par le détecteur commun du hub (shared/vision.visages : YuNet), avec la
    géométrie dont Reveal a besoin (peau, maquillage). Mesuré : mêmes visages que
    image.detectFaces de PhotoCraft sur les photos de test, repères à 0-9 % de l'écart des yeux."""

    def __init__(self, v):
        pts = np.asarray(v['points'], np.float32)
        self.rect = tuple(v['cadre'])                        # (x, y, largeur, hauteur)
        self.score = float(v['score'])
        self.eye_l, self.eye_r = pts[0], pts[1]              # gauche, droite de l'image
        a, b = pts[3], pts[4]
        self.mouth_l, self.mouth_r = (a, b) if a[0] <= b[0] else (b, a)
        self.nose = pts[2]
        v = self.eye_r - self.eye_l
        self.eye_dist = float(np.linalg.norm(v))
        self.angle = math.degrees(math.atan2(v[1], v[0]))
        t = math.radians(self.angle)
        self.up = np.array([math.sin(t), -math.cos(t)], np.float32)   # vers le front
        self.mouth_c = (self.mouth_l + self.mouth_r) / 2
        self.mouth_w = float(np.linalg.norm(self.mouth_r - self.mouth_l))


LONGUEUR_VISAGES = 1280       # photos de groupe : petits visages (à 640, un visage sur 7 manquait)


def visages(img, min_score=0.8):
    """Visages de l'image (BGR), du plus grand au plus petit, par le détecteur commun."""
    from shared import vision
    return [Face(v) for v in vision.visages(img, seuil=min_score, longueur=LONGUEUR_VISAGES)]


# ---------- peau ----------

def _features_mask(shape, f):
    """Yeux, sourcils et bouche : zones à garder nettes (1 = à exclure)."""
    d, up = f.eye_dist, f.up
    m = np.zeros(shape[:2], np.float32)
    for eye in (f.eye_l, f.eye_r):
        m = np.maximum(m, _ellipse(shape, eye, (d * 0.30, d * 0.17), f.angle))
        m = np.maximum(m, _ellipse(shape, eye + up * d * 0.36, (d * 0.36, d * 0.12), f.angle))
    m = np.maximum(m, _ellipse(shape, f.mouth_c + (-up) * f.mouth_w * 0.05,
                               (f.mouth_w * 0.62, f.mouth_w * 0.33), f.angle))
    return m


def skin_mask(img, faces):
    """Masque doux de la peau (visage, cou, décolleté) à partir de la couleur mesurée sur les joues."""
    h, w = img.shape[:2]
    ycc = cv2.cvtColor(img, cv2.COLOR_BGR2YCrCb).astype(np.float32)
    total = np.zeros((h, w), np.float32)
    for f in faces:
        d = f.eye_dist
        r = max(2, int(d * 0.12))
        samples = []
        for eye, corner in ((f.eye_l, f.mouth_l), (f.eye_r, f.mouth_r)):
            c = eye * 0.45 + corner * 0.55
            x, y = int(c[0]), int(c[1])
            samples.append(ycc[max(0, y - r):y + r, max(0, x - r):x + r].reshape(-1, 3))
        fc = f.eye_l * 0.5 + f.eye_r * 0.5 + f.up * d * 0.75          # front
        x, y = int(fc[0]), int(fc[1])
        samples.append(ycc[max(0, y - r):y + r, max(0, x - r):x + r].reshape(-1, 3))
        s = np.concatenate([p for p in samples if p.size])
        mu = s[:, 1:].mean(0)
        cov = np.cov(s[:, 1:].T) + np.eye(2) * 6.0
        inv = np.linalg.inv(cov)
        y_ref = float(s[:, 0].mean())

        x0, y0, fw, fh = f.rect
        X0, X1 = max(0, int(x0 - 0.35 * fw)), min(w, int(x0 + 1.35 * fw))
        Y0, Y1 = max(0, int(y0 - 0.20 * fh)), min(h, int(y0 + 2.2 * fh))
        roi = ycc[Y0:Y1, X0:X1]
        diff = roi[:, :, 1:] - mu
        dist = np.sqrt(np.einsum('...i,ij,...j->...', diff, inv, diff))
        p = np.clip((3.5 - dist) / 1.5, 0, 1)                       # proche de la couleur des joues
        p *= np.clip((roi[:, :, 0] - 0.35 * y_ref) / (0.2 * y_ref), 0, 1)   # pas les ombres profondes
        m = np.zeros((h, w), np.float32)
        m[Y0:Y1, X0:X1] = p

        # Nettoyage : on garde la zone reliée au visage
        k = max(3, int(d * 0.06)) | 1
        b = (m > 0.5).astype(np.uint8)
        b = cv2.morphologyEx(b, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
        b = cv2.morphologyEx(b, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k * 3, k * 3)))
        n, labels = cv2.connectedComponents(b)
        seeds = [f.nose, (f.eye_l + f.mouth_l) / 2, (f.eye_r + f.mouth_r) / 2]
        keep = np.zeros_like(b)
        for sd in seeds:
            sx, sy = int(np.clip(sd[0], 0, w - 1)), int(np.clip(sd[1], 0, h - 1))
            lab = labels[sy, sx]
            if lab:
                keep |= (labels == lab).astype(np.uint8)
        if keep.any():
            keep = cv2.dilate(keep, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k * 2, k * 2)))
            m *= keep.astype(np.float32)
        # Remplir les petits trous (grains de beauté, reflets) puis exclure yeux, sourcils, bouche
        m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k * 2, k * 2)))
        m *= 1 - _soft(_features_mask(img.shape, f), d * 0.05)
        total = np.maximum(total, _soft(m, d * 0.03))
    return np.clip(total, 0, 1)


# ---------- maquillage ----------

def lips_mask(img, f):
    up, mw = f.up, f.mouth_w
    region = _ellipse(img.shape, f.mouth_c + (-up) * mw * 0.06, (mw * 0.60, mw * 0.30), f.angle)
    lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB).astype(np.float32)
    a = lab[:, :, 1]
    inside = region > 0.5
    vals = a[inside]
    if vals.size > 50:
        # Les lèvres sont plus rouges que la peau autour : seuil d'Otsu sur a* dans l'ellipse
        lo, hi = float(np.percentile(vals, 5)), float(np.percentile(vals, 95))
        if hi - lo > 4:
            v8 = np.clip((vals - lo) / (hi - lo) * 255, 0, 255).astype(np.uint8)
            t, _ = cv2.threshold(v8, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            thr = lo + t / 255.0 * (hi - lo)
            m = np.clip((a - thr) / max(2.0, (hi - lo) * 0.15) + 0.5, 0, 1) * region
            k = max(3, int(mw * 0.06)) | 1
            m = cv2.morphologyEx(m, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
            if m.mean() > region.mean() * 0.15:
                return _soft(m, mw * 0.03)
    return _soft(region * 0.8, mw * 0.06)


def blush_mask(img, f, skin):
    d = f.eye_dist
    m = np.zeros(img.shape[:2], np.float32)
    for eye, corner, side in ((f.eye_l, f.mouth_l, -1), (f.eye_r, f.mouth_r, 1)):
        c = eye + (corner - eye) * 0.42
        c = c + np.array([math.cos(math.radians(f.angle)), math.sin(math.radians(f.angle))]) * side * d * 0.18
        m = np.maximum(m, _ellipse(img.shape, c, (d * 0.36, d * 0.22), f.angle - side * 18))
    return _soft(m, d * 0.14) * np.clip(skin * 1.5, 0, 1)


def eyeshadow_mask(img, f):
    d = f.eye_dist
    m = np.zeros(img.shape[:2], np.float32)
    for eye in (f.eye_l, f.eye_r):
        lid = _ellipse(img.shape, eye + f.up * d * 0.13, (d * 0.30, d * 0.13), f.angle)
        opening = _ellipse(img.shape, eye + f.up * d * 0.01, (d * 0.21, d * 0.075), f.angle)
        m = np.maximum(m, np.clip(lid - opening, 0, 1))
    return _soft(m, d * 0.035)


# ---------- photos anciennes ----------

def streak_lines(img):
    """Nombre de stries claires horizontales longues (signature d'un défaut de tirage)."""
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    h, w = g.shape
    t = max(3, int(round(max(h, w) / 120))) | 1
    length = max(20, int(w / 12))
    th = cv2.morphologyEx(g, cv2.MORPH_TOPHAT, cv2.getStructuringElement(cv2.MORPH_RECT, (1, t * 2 + 1)))
    b = (th > 8).astype(np.uint8) * 255
    b = cv2.morphologyEx(b, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (length, 1)))
    n, _, stats, _ = cv2.connectedComponentsWithStats(b)
    return sum(1 for i in range(1, n)
               if stats[i][2] >= length and stats[i][3] <= t * 2 and stats[i][2] / max(1, stats[i][3]) >= 8)


def scratch_mask(img, min_lines=6):
    """Stries claires horizontales (défaut de tirage ou de numérisation).

    Renvoie un masque vide s'il y a moins de `min_lines` stries : une ligne claire isolée
    est presque toujours un vrai détail (guidon, cadre, bord de table), pas un défaut.
    """
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    h, w = g.shape
    t = max(3, int(round(max(h, w) / 120))) | 1        # épaisseur max d'une strie
    length = max(20, int(w / 12))                       # longueur minimale
    th = cv2.morphologyEx(g, cv2.MORPH_TOPHAT, cv2.getStructuringElement(cv2.MORPH_RECT, (1, t * 2 + 1)))
    b = (th > 8).astype(np.uint8) * 255
    b = cv2.morphologyEx(b, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (length, 1)))
    n, labels, stats, _ = cv2.connectedComponentsWithStats(b)
    keep = np.zeros_like(b)
    lines = 0
    for i in range(1, n):
        x, y, bw, bh, area = stats[i]
        if bw >= length and bh <= t * 2 and bw / max(1, bh) >= 8:
            keep[labels == i] = 255
            lines += 1
    if lines < min_lines:
        return np.zeros((h, w), np.float32)
    keep = cv2.dilate(keep, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3)))
    return keep.astype(np.float32) / 255.0


def print_quad(img):
    """Coins du tirage photographié (bord de papier clair autour), ou None s'il n'y en a pas.

    Renvoie [haut-gauche, haut-droit, bas-droit, bas-gauche] en pixels.
    """
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    h, w = g.shape
    # Le papier est clair et uni ; la photo est plus sombre et texturée
    blur = cv2.GaussianBlur(g, (0, 0), max(1.0, max(h, w) / 300))
    paper = float(np.percentile(blur, 97))
    dark = (blur < paper - 18).astype(np.uint8) * 255
    k = max(3, int(max(h, w) / 60)) | 1
    dark = cv2.morphologyEx(dark, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (k, k)))
    dark = cv2.morphologyEx(dark, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (k, k)))
    contours, _ = cv2.findContours(dark, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None
    c = max(contours, key=cv2.contourArea)
    area = cv2.contourArea(c) / float(h * w)
    if area < 0.40 or area > 0.93:          # pas de bord net : on ne recadre pas
        return None
    rect = cv2.minAreaRect(c)
    box = cv2.boxPoints(rect)
    # Rogne légèrement vers l'intérieur pour éliminer le liseré
    center = box.mean(axis=0)
    box = center + (box - center) * 0.97
    s_ = box.sum(axis=1)
    d_ = np.diff(box, axis=1).ravel()
    quad = [box[np.argmin(s_)], box[np.argmin(d_)], box[np.argmax(s_)], box[np.argmax(d_)]]
    quad = [[float(np.clip(x, 0, w - 1)), float(np.clip(y, 0, h - 1))] for x, y in quad]
    return quad


def _vmedian(g, k):
    """Médiane verticale (colonne par colonne) sur k pixels."""
    pad = k // 2
    gp = np.pad(g, ((pad, pad), (0, 0)), mode='reflect')
    return np.median(np.stack([gp[i:i + g.shape[0]] for i in range(k)], 0), 0)


def destreak(img, iterations=3):
    """Atténue les stries horizontales (claires ou sombres), y compris serrées et courtes.

    Pour chaque pixel : écart à la médiane verticale de ses voisins ; cet écart, moyenné
    le long de la ligne, donne la surbrillance propre à la strie, qu'on retire. Les détails
    du visage (courts horizontalement) s'annulent dans la moyenne et restent intacts.
    La correction est limitée à la zone striée, avec un fondu.
    Renvoie (image corrigée en gris BGR, part de l'image corrigée).
    """
    g0 = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    h, w = g0.shape
    t = max(3, int(round(max(h, w) / 120))) | 1
    # zone striée : lignes longues détectées, largement élargies
    th = cv2.morphologyEx(g0, cv2.MORPH_TOPHAT, cv2.getStructuringElement(cv2.MORPH_RECT, (1, t * 2 + 1)))
    b = (th > 6).astype(np.uint8) * 255
    b = cv2.morphologyEx(b, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (max(20, w // 14), 1)))
    region = cv2.dilate(b, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (max(3, w // 6), max(3, w // 10))))
    region = cv2.GaussianBlur(region.astype(np.float32) / 255, (0, 0), max(1.0, w / 40))
    k = (t * 3) | 1
    L = max(15, w // 30)
    g = g0.astype(np.float32)
    for _ in range(iterations):
        resid = g - _vmedian(g, k)
        offset = np.clip(cv2.blur(resid, (L, 1)), -40, 40)
        g = g - offset * region
    out = np.clip(g, 0, 255).astype(np.uint8)
    changed = float((np.abs(out.astype(np.int16) - g0) > 2).mean())
    return cv2.cvtColor(out, cv2.COLOR_GRAY2BGR), changed


_net = None


def _colorizer():
    global _net
    if _net is None:
        from shared import ia
        net = cv2.dnn.readNetFromCaffe(str(ia.annexe('zhang-colorization', 'prototxt')),
                                       str(ia.chemin('zhang-colorization')))
        pts = np.load(str(ia.annexe('zhang-colorization', 'points'))).transpose().reshape(2, 313, 1, 1).astype(np.float32)
        net.getLayer(net.getLayerId('class8_ab')).blobs = [pts]
        net.getLayer(net.getLayerId('conv8_313_rh')).blobs = [np.full([1, 313], 2.606, np.float32)]
        _net = net
    return _net


def correct_casts(L, ab, longest, max_l=None):
    """Corrige les dominantes roses du modèle de colorisation.

    - teintes rose, rouge rosé et magenta (angle Lab de -80 à 50 degrés, mesuré à 20-40 sur la
      photo 3) ramenées vers la teinte chair / brun naturelle (55 degrés) et désaturées ;
      le bleu du ciel (vers -110 degrés), le jaune et le vert (au-delà de 60 degrés) ne bougent pas ;
    - couleur atténuée dans les ombres (cheveux sombres colorés en rouge par le modèle) ;
    - léger lissage des couleurs pour supprimer les taches isolées.
    max_l : si donné, la correction des roses ne touche que les zones de luminance < max_l.
    """
    sigma = max(1.0, longest / 300.0)
    k = int(sigma * 3) * 2 + 1
    ab = cv2.GaussianBlur(ab, (k, k), sigma)
    a, b = ab[:, :, 0], ab[:, :, 1]
    hue = np.degrees(np.arctan2(b, a))
    chroma = np.sqrt(a * a + b * b)
    rose = np.clip((50.0 - hue) / 20.0, 0, 1) * (hue > -80)
    if max_l is not None:                                    # seulement les tons sombres et moyens
        rose = rose * np.clip((max_l - L) / 10.0, 0, 1)
    hue = hue + (55.0 - hue) * rose
    chroma = chroma * (1 - 0.45 * rose)
    chroma = chroma * np.clip((L - 15.0) / 45.0, 0.2, 1.0)   # L de 0 à 100 : ombres moins colorées
    t = np.radians(hue)
    return np.dstack([chroma * np.cos(t), chroma * np.sin(t)]).astype(np.float32)


def colorize(img, saturation=1.0, max_chroma=30.0):
    """Colorisation automatique (modèle de Zhang et al. 2016) ; garde la luminance de l'image."""
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    base = cv2.cvtColor(g, cv2.COLOR_GRAY2BGR).astype(np.float32) / 255
    L = cv2.cvtColor(base, cv2.COLOR_BGR2LAB)[:, :, 0]
    small = cv2.resize(base, (224, 224), interpolation=cv2.INTER_AREA)
    Ls = cv2.cvtColor(small, cv2.COLOR_BGR2LAB)[:, :, 0] - 50
    net = _colorizer()
    net.setInput(cv2.dnn.blobFromImage(Ls))
    ab = net.forward()[0].transpose(1, 2, 0)
    ab = cv2.resize(ab, (img.shape[1], img.shape[0]), interpolation=cv2.INTER_CUBIC) * saturation
    ab = correct_casts(L, ab, max(img.shape[:2]))
    # Plafonne la chroma : évite les couleurs criardes du modèle
    chroma = np.sqrt((ab ** 2).sum(axis=2, keepdims=True))
    ab = ab * np.minimum(1.0, max_chroma / np.maximum(chroma, 1e-6))
    out = cv2.cvtColor(np.dstack([L, ab]).astype(np.float32), cv2.COLOR_LAB2BGR)
    return (np.clip(out, 0, 1) * 255).astype(np.uint8)

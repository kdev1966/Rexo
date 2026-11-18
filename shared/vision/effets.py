"""Effets photo en numpy et OpenCV, identiques sous macOS et Windows.

Reprennent ceux de rexo-segment (Core Image et Apple Vision), sur le masque des personnes de
MODNet (shared.vision.detourer). Images BGR uint8, masques float32 de 0 à 1.

    flou(img, m)               personnes nettes, fond flou
    noir_blanc(img, m)         personnes en couleur, fond en noir et blanc
    uni(img, m, (r, v, b))     personnes sur une couleur unie
    detourage(img, m)          BGRA : personnes sur fond transparent, bords nettoyés
    recadrage(img, m, '4:5')   (image, cadre x, y, l, h) centré sur les personnes
    ameliorer(img)             (image, réglages) : lumière, couleurs, balance des blancs, relief
    rendu(img, nom)            rendu de couleur (STYLES)
    courbe_tons(img)           courbe de tons automatique douce (aussi pour Rexo ID)
"""

import cv2
import numpy as np

STYLES = ('chaud', 'froid', 'vintage-chaud', 'noir-et-blanc', 'lumineux', 'contraste', 'doux')
TONS_MAX = 14                  # déplacement maximal de la courbe de tons (niveaux sur 255)
LUMA = np.array([0.0722, 0.7152, 0.2126], np.float32)       # BGR, Rec. 709 (Core Image)


class EffetError(RuntimeError):
    pass


def _f(img):
    return img.astype(np.float32) / 255.0


def _u8(x):
    return np.clip(x * 255.0 + 0.5, 0, 255).astype(np.uint8)


def _lineaire(x):
    return np.where(x <= 0.04045, x / 12.92, ((x + 0.055) / 1.055) ** 2.4)


def _srgb(lin):
    lin = np.clip(lin, 0, 1)
    return np.where(lin <= 0.0031308, lin * 12.92, 1.055 * np.power(lin, 1 / 2.4) - 0.055)


def _melanger(avant, fond, m):
    a = np.clip(m, 0, 1)[..., None]
    return avant * a + fond * (1 - a)


def _flou(x, sigma):
    return cv2.GaussianBlur(x, (0, 0), sigmaX=float(sigma), borderType=cv2.BORDER_REPLICATE)


def _gris(x):
    return x @ LUMA


# ---------- courbe de tons ----------

def courbe_tons(img):
    """Table de 256 niveaux : noirs un peu plus profonds, tons moyens éclaircis de quelques
    niveaux, blancs rapprochés du blanc ; jamais plus de TONS_MAX niveaux de déplacement.
    Réglée sur ce que faisait CIToneCurve (réglages automatiques d'Apple) sur nos portraits."""
    gris = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    bas, milieu, haut = (float(v) for v in np.percentile(gris, (0.5, 50, 99.5)))
    px = np.array([0.0, bas, milieu, haut, 255.0])
    py = np.array([0.0, bas * 0.75, milieu + float(np.clip((165 - milieu) * 0.5, -6, 10)),
                   haut + (255 - haut) * 0.4, 255.0])
    garde = np.concatenate([[True], np.diff(px) > 1])
    px, py = px[garde], np.maximum.accumulate(py[garde])
    # interpolation monotone (Fritsch-Carlson) : pas de dépassement entre les points
    pentes = np.diff(py) / np.diff(px)
    m = np.concatenate([[pentes[0]], (pentes[:-1] + pentes[1:]) / 2, [pentes[-1]]])
    for k, p in enumerate(pentes):
        if p == 0:
            m[k] = m[k + 1] = 0
        else:
            a, b = m[k] / p, m[k + 1] / p
            n = a * a + b * b
            if n > 9:
                t = 3 / np.sqrt(n)
                m[k], m[k + 1] = t * a * p, t * b * p
    x = np.arange(256, dtype=np.float64)
    k = np.clip(np.searchsorted(px, x, side='right') - 1, 0, len(px) - 2)
    h = px[k + 1] - px[k]
    t = (x - px[k]) / h
    y = ((2 * t ** 3 - 3 * t ** 2 + 1) * py[k] + (t ** 3 - 2 * t ** 2 + t) * h * m[k]
         + (-2 * t ** 3 + 3 * t ** 2) * py[k + 1] + (t ** 3 - t ** 2) * h * m[k + 1])
    y = np.clip(y, x - TONS_MAX, x + TONS_MAX)
    return np.clip(np.round(y), 0, 255).astype(np.uint8)


# ---------- réglages de base (équivalents de Core Image) ----------

def couleurs(x, saturation=1.0, luminosite=0.0, contraste=1.0):
    """CIColorControls : saturation autour de la luminance, puis luminosité, puis contraste."""
    g = _gris(x)[..., None]
    x = g + (x - g) * saturation
    x = x + luminosite
    return np.clip((x - 0.5) * contraste + 0.5, 0, 1)


def _blanc(kelvin):
    """Couleur (B, V, R, linéaire) d'un corps noir à `kelvin` (approximation de T. Helland)."""
    t = kelvin / 100.0
    r = 255.0 if t <= 66 else 329.698727446 * (t - 60) ** -0.1332047592
    v = 99.4708025861 * np.log(t) - 161.1195681661 if t <= 66 else 288.1221695283 * (t - 60) ** -0.0755148492
    b = 255.0 if t >= 66 else (0.0 if t <= 19 else 138.5177312231 * np.log(t - 10) - 305.0447927307)
    return _lineaire(np.clip(np.array([b, v, r], np.float32), 0, 255) / 255.0)


def temperature(x, kelvin, cible=6500):
    """CITemperatureAndTint : la lumière de la photo est déclarée à `kelvin` et ramenée à
    `cible` (kelvin > cible réchauffe)."""
    g = _blanc(kelvin) / _blanc(cible)
    g = g / (g @ LUMA)
    return _srgb(_lineaire(x) / g)


def ombres_lumieres(x, ombres=0.0, lumieres=1.0):
    """CIHighlightShadowAdjust (approché) : débouche les ombres (0 à 1) et atténue les hautes
    lumières (1 = rien) d'après la luminance locale, sur la luminance seule (la saturation est
    gardée) et sans relever les noirs profonds."""
    lum = _gris(x)
    base = _flou(lum, max(2.0, max(x.shape[:2]) / 100))
    nouv = lum.copy()
    if ombres:
        noirs = np.clip((lum - 0.02) / 0.10, 0, 1)                 # noirs profonds épargnés
        nouv = nouv + ombres * 0.45 * (1 - base) ** 2 * (1 - lum) * noirs * np.clip(1 - lum * 1.6, 0, 1)
    if lumieres < 1:
        nouv = nouv - (1 - lumieres) * 0.5 * base ** 2 * lum
    return np.clip(x * (nouv / np.maximum(lum, 1e-4))[..., None], 0, 1)


def exposition_auto(x):
    """Niveaux automatiques : blancs (0,5 % les plus clairs) étirés jusqu'à 0,97, noirs gardés,
    puis une photo sombre est éclaircie (luminance moyenne rapprochée à moitié de 0,5 ; jamais
    assombrie). Gain et gamma bornés."""
    lum = _gris(x)
    bas, haut = (float(v) for v in np.percentile(lum, (0.5, 99.5)))
    if haut - bas > 0.05:
        gain = min(1.35, 0.97 / max(haut, 1e-3))
        if gain > 1:
            x = np.clip(x * gain, 0, 1)
    moy = float(_gris(x).mean())
    if 0.02 < moy < 0.5:
        cible = moy + 0.5 * (0.5 - moy)
        gamma = float(np.clip(np.log(cible) / np.log(moy), 0.7, 1.0))
        lum = _gris(x)
        x = np.clip(x * (np.power(np.maximum(lum, 1e-4), gamma) / np.maximum(lum, 1e-4))[..., None], 0, 1)
    return x


def vivacite(x, force):
    """CIVibrance : augmente la saturation des couleurs peu saturées d'abord."""
    sat = np.max(x, axis=2) - np.min(x, axis=2)
    g = _gris(x)[..., None]
    return np.clip(g + (x - g) * (1 + force * (1 - sat))[..., None], 0, 1)


def nettete(x, rayon, intensite):
    """CIUnsharpMask : x + intensité × (x - flou(x))."""
    return np.clip(x + intensite * (x - _flou(x, rayon)), 0, 1)


def vignette(x, intensite=0.7, rayon=1.6):
    h, w = x.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    d = np.hypot((xx - w / 2) / (w / 2), (yy - h / 2) / (h / 2)) / np.sqrt(2)     # 0 au centre, 1 au coin
    debut = max(0.0, 1 - rayon / 2.0)
    f = 1 - intensite * 0.6 * np.clip((d - debut) / (1 - debut + 1e-6), 0, 1) ** 2
    return x * f[..., None]


def eclat(x, rayon, intensite):
    """CIBloom (approché) : halo lumineux, flou des parties claires en écran."""
    clair = _flou(np.clip((x - 0.5) * 2, 0, 1), rayon)
    return 1 - (1 - x) * (1 - intensite * clair)


def mono(x):
    """CIPhotoEffectMono : noir et blanc, léger contraste."""
    g = _gris(x)
    g = np.clip((g - 0.5) * 1.05 + 0.5, 0, 1)
    return np.repeat(g[..., None], 3, axis=2)


def transfert(x):
    """CIPhotoEffectTransfer (approché) : tirage ancien, tons jaunes, noirs à peine relevés,
    contraste un peu plus fort."""
    x = np.clip((x - 0.5) * 1.1 + 0.5, 0, 1)
    x = 0.03 + 0.94 * x
    return np.clip(x * np.array([0.84, 1.0, 1.04], np.float32), 0, 1)


# ---------- effets de studio ----------

def flou(img, m):
    x = _f(img)
    return _u8(_melanger(x, _flou(x, max(img.shape[:2]) / 120), m))


def noir_blanc(img, m):
    x = _f(img)
    return _u8(_melanger(x, mono(x), m))


def uni(img, m, rvb=(255, 255, 255)):
    x = _f(img)
    fond = np.empty_like(x)
    fond[:] = np.array(rvb[::-1], np.float32) / 255.0
    return _u8(_melanger(x, fond, m))


def decontaminer(img, m):
    """Couleurs du bord nettoyées : au pourtour, un pixel à demi transparent mêle la personne
    et l'ancien fond ; il prend la couleur moyenne de la personne autour de lui
    (flou(image × masque) / flou(masque)). Au cœur (masque > 0,9), l'image reste intacte."""
    x = _f(img)
    r = max(4.0, max(img.shape[:2]) / 400.0)
    a = np.clip(m, 0, 1)[..., None]
    premier = _flou(x * a, r) / np.maximum(_flou(a[..., 0], r)[..., None], 1e-4)
    coeur = np.clip(m * 10 - 9, 0, 1)
    return _u8(_melanger(x, np.clip(premier, 0, 1), coeur))


def detourage(img, m):
    """BGRA : personnes aux bords nettoyés, transparence = masque."""
    return np.dstack([decontaminer(img, m), _u8(np.clip(m, 0, 1))])


def cadre_personnes(m, seuil=0.5):
    """Cadre (x, y, l, h) des personnes, en pixels ; None sans personne."""
    lignes, colonnes = np.where((m > seuil).any(axis=1))[0], np.where((m > seuil).any(axis=0))[0]
    if not len(lignes):
        return None
    return int(colonnes[0]), int(lignes[0]), int(colonnes[-1] - colonnes[0] + 1), int(lignes[-1] - lignes[0] + 1)


def recadrage(img, m, ratio='4:5'):
    """Le plus grand cadre au format L:H, centré sur les personnes en largeur et sur les
    visages (haut des personnes) en hauteur ; renvoie (image recadrée, (x, y, l, h))."""
    try:
        rl, rh = (float(v) for v in ratio.split(':'))
        r = rl / rh
    except ValueError:
        raise EffetError('format invalide (L:H) : %s' % ratio)
    H, W = img.shape[:2]
    cw = min(W, H * r)
    ch = cw / r
    cx, cy = W / 2, H / 2
    boite = cadre_personnes(m)
    if boite:
        bx, by, bw, bh = boite
        cx = bx + bw / 2
        cy = by + min(bh, ch) * 0.45
    x = round(min(max(0, cx - cw / 2), W - cw))
    y = round(min(max(0, cy - ch / 2), H - ch))
    l, h = int(cw), int(ch)
    return img[y:y + h, x:x + l].copy(), (x, y, l, h)


# ---------- amélioration et rendus ----------

def ameliorer(img):
    """Lumière et couleurs (exposition, ombres débouchées, vivacité), balance des blancs sur
    les zones blanches, relief. Réglé sur l'amélioration automatique d'Apple (mesurée sur nos
    photos : une photo sombre est nettement éclaircie, les noirs restent profonds, la
    saturation monte d'environ un tiers). Renvoie (image, liste des réglages, gains R, V, B)."""
    faits = []
    x = exposition_auto(_f(img))
    faits.append('Exposition')
    x = ombres_lumieres(x, ombres=0.3)
    faits.append('Ombres')
    x = vivacite(x, 0.12)
    faits.append('Vivacité')
    # Balance des blancs : zones très claires et peu colorées (robe, chemise), ramenées vers
    # le neutre à moitié, de 15 % au plus par couleur (garde la chaleur des soirées).
    petite = cv2.resize(x, None, fx=256 / max(x.shape[:2]), fy=256 / max(x.shape[:2]), interpolation=cv2.INTER_AREA) * 255
    lum = _gris(petite / 255) * 255
    seuil = np.percentile(lum, 97)
    hi, lo = petite.max(axis=2), petite.min(axis=2)
    choix = (lum >= seuil) & (hi < 250) & (hi > 120) & ((hi - lo) / np.maximum(hi, 1) < 0.25)
    gains = np.ones(3, np.float32)
    if choix.sum() >= max(20, lum.size // 500):
        somme = petite[choix].sum(axis=0)
        gains = np.clip(1 + (somme.mean() / somme - 1) * 0.5, 0.85, 1.15).astype(np.float32)
        x = np.clip(x * gains, 0, 1)
        faits.append('Balance des blancs')
    x = nettete(x, max(img.shape[:2]) / 150.0, 0.25)
    faits.append('Relief')
    return _u8(x), faits, [round(float(v), 3) for v in gains[::-1]]


def rendu(img, nom):
    """Rendu de couleur sur toute l'image ; une 4e couche (transparence) est gardée."""
    if nom not in STYLES:
        raise EffetError('rendu inconnu : %s' % nom)
    alpha = img[..., 3:] if img.ndim == 3 and img.shape[2] == 4 else None
    x = _f(img[..., :3])
    cote = max(img.shape[:2])
    if nom == 'chaud':
        x = couleurs(temperature(x, 7000), saturation=1.06, contraste=1.03)
    elif nom == 'froid':
        x = couleurs(temperature(x, 6000), saturation=0.95)
    elif nom == 'vintage-chaud':
        x = vignette(couleurs(transfert(temperature(x, 7400)), saturation=0.8, contraste=0.92,
                              luminosite=0.02), 0.7, 1.6)
    elif nom == 'noir-et-blanc':
        x = mono(x)
    elif nom == 'lumineux':
        x = couleurs(ombres_lumieres(x, ombres=0.45, lumieres=0.95), luminosite=0.06)
    elif nom == 'contraste':
        x = couleurs(x, contraste=1.15, saturation=1.08)
    elif nom == 'doux':
        x = eclat(couleurs(x, contraste=0.9, saturation=0.92, luminosite=0.02), cote / 300.0, 0.35)
    out = _u8(x)
    return np.dstack([out, alpha]) if alpha is not None else out

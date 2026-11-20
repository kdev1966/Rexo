"""Réparation d'une photo ancienne avant toute autre retouche : parties arrachées, taches,
rayures, fissures et déchirures. Tout est calculé en Python (ONNX), avant l'agrandissement :
l'image est plus petite, et Real-ESRGAN affine ensuite une image propre.

    manques(img)      parties arrachées : couleur du fond du scan, reliées au bord, dans le
                      rectangle du tirage (un tirage est rectangulaire)
    taches(img)       taches d'eau ou de moisissure d'un tirage monochrome : intérieur éclairci,
                      auréoles effacées (sauf visages), teinte rendue unique
    ton_d_origine     rend au tirage restauré sa teinte d'origine (sépia)
    rayures(img)      masque des rayures, fissures et déchirures : détecteur de « Bringing Old
                      Photos Back to Life » (Microsoft, MIT)
    grain(img), debruiter(img)  grain du film : estimé (Immerkær), atténué par SCUNet (Apache-2.0)
                      seulement s'il dépasse SEUIL_GRAIN (lent : 15 s par tuile de 512 sur le Mac)
    reconstituer(img, masque)   LaMa (Samsung, Apache-2.0) : par tuiles de 512 à la
                      résolution de l'image (lignes fines), ou sur l'image réduite à 512 pour
                      les grands trous (tout le contexte)
    reparer(img)      les quatre à la suite ; renvoie (image, lignes de journal)

Modèles : rayures-anciennes, lama-512, scunet-512 (apps/reveal/modeles). Images BGR uint8.
"""

import cv2
import numpy as np

from . import ia

COTE_DETECTION = 256          # le détecteur voit l'image au côté court de 256 (comme Microsoft)
SEUIL_RAYURES = 0.4           # probabilité au-dessus de laquelle un pixel est une rayure
TUILE = 512                   # entrée fixe de LaMa
RECOUVREMENT = 96
ECART_TACHES = 2.0            # excès de jaune (Lab, sur 255) à partir duquel une zone est tachée


def disponible():
    return ia.available('rayures-anciennes') and ia.available('lama-512')


# ---------- rayures, fissures, déchirures ----------

def rayures(img):
    """Masque 0/1 des rayures et fissures, légèrement élargi (bord des fissures)."""
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    f = COTE_DETECTION / min(g.shape)
    h, w = (max(16, int(round(v * f / 16)) * 16) for v in g.shape)
    x = cv2.resize(g, (w, h), interpolation=cv2.INTER_AREA).astype(np.float32) / 255
    s = ia._session('rayures-anciennes')
    p = s.run(None, {s.get_inputs()[0].name: ((x - 0.5) / 0.5)[None, None]})[0][0, 0]
    p = cv2.resize(p, (g.shape[1], g.shape[0]), interpolation=cv2.INTER_LINEAR)
    m = (p >= SEUIL_RAYURES).astype(np.uint8)
    k = max(3, int(round(5 * max(g.shape) / 640))) | 1
    return cv2.dilate(m, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))


# ---------- reconstitution (LaMa) ----------

def _lama_512(img, m):
    """Une passe de LaMa sur une image et un masque de 512 × 512."""
    s = ia._session('lama-512')
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


# ---------- parties arrachées ----------

def manques(img):
    """Parties arrachées du tirage : (masque 0/1, part de l'image), ou (None, 0) si le scan n'a
    pas de fond autour du tirage (photo déjà recadrée : rien à chercher)."""
    lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB).astype(np.float32)
    h, w = lab.shape[:2]
    e = max(2, min(h, w) // 200)
    bord = np.concatenate([lab[:e].reshape(-1, 3), lab[-e:].reshape(-1, 3),
                           lab[:, :e].reshape(-1, 3), lab[:, -e:].reshape(-1, 3)])
    ref = np.median(bord, axis=0)
    proche = (np.sqrt(((lab - ref) ** 2).sum(2)) < 18).astype(np.uint8)
    proche = cv2.morphologyEx(proche, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    _, labs = cv2.connectedComponents(proche, connectivity=4)
    pourtour = np.concatenate([labs[0], labs[-1], labs[:, 0], labs[:, -1]])
    if (pourtour > 0).mean() < 0.5:                       # pas de fond tout autour : photo recadrée
        return None, 0.0
    fond = np.isin(labs, list(set(np.unique(pourtour)) - {0})).astype(np.uint8)
    papier = 1 - fond
    cols, lignes = np.where(papier.mean(0) > 0.5)[0], np.where(papier.mean(1) > 0.5)[0]
    if len(cols) < w * 0.3 or len(lignes) < h * 0.3:
        return None, 0.0
    rect = np.zeros_like(fond)
    rect[lignes[0]:lignes[-1] + 1, cols[0]:cols[-1] + 1] = 1
    m = fond & rect
    # un liseré le long du bord du rectangle n'est pas un manque (marge irrégulière du scan)
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * e + 1,) * 2))
    part = float(m.mean())
    if part < 0.002:
        return None, 0.0
    k = max(5, int(max(h, w) / 50)) | 1                   # fibres blanches du bord déchiré
    return cv2.dilate(m, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))), part


# ---------- taches ----------

def taches(img):
    """Tirage monochrome : (image à teinte unique, taches corrigées ; part tachée ; teinte a, b
    du tirage en Lab 8 bits). Une tache d'eau a trois parties :
    1. l'intérieur, plus jaune et plus sombre : éclairci jusqu'au niveau du voisinage propre, à
       une échelle moyenne (les plis et détails fins restent) ;
    2. les auréoles et points sombres (traits sombres fins dans la zone tachée) : effacés par
       LaMa, sauf dans les visages (sourcils, yeux, lèvres sont aussi des traits sombres fins) ;
    3. la couleur : teinte unique du tirage (rendue ensuite par ton_d_origine)."""
    lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB).astype(np.float32)
    L, a, b = lab[..., 0], lab[..., 1], lab[..., 2]
    h, w = L.shape
    d = max(h, w)
    a0, b0 = float(np.median(a)), float(np.median(b))
    jaune = cv2.GaussianBlur(np.clip((b - b0) + 0.5 * (a - a0), 0, None), (0, 0), d / 300)
    s = np.clip((jaune - ECART_TACHES) / ECART_TACHES, 0, 1)
    s = cv2.GaussianBlur(s, (0, 0), d / 200)
    # 1. intérieur
    moyen = cv2.GaussianBlur(L, (0, 0), d / 90)
    poids = cv2.GaussianBlur(1 - s, (0, 0), d / 30)
    propre = cv2.GaussianBlur(L * (1 - s), (0, 0), d / 30) / np.maximum(poids, 1e-3)
    L2 = np.clip(L + np.clip(propre - moyen, 0, 70) * s, 0, 255)
    out = cv2.cvtColor(np.dstack([L2, np.full_like(a, a0), np.full_like(b, b0)]).astype(np.uint8),
                       cv2.COLOR_LAB2BGR)
    # 2. auréoles et points sombres
    zone = cv2.dilate((s > 0.1).astype(np.uint8),
                      cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (int(d / 40) | 1,) * 2))
    k = max(5, int(d / 70)) | 1
    noir = cv2.morphologyEx(L2, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))) - L2
    traits = cv2.morphologyEx(((noir > 9) & (zone > 0)).astype(np.uint8), cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
    try:
        from shared import vision
        for v in vision.visages(img, seuil=0.6):
            x, y, l, hv = v['cadre']
            cv2.ellipse(traits, (int(x + l / 2), int(y + hv / 2)), (int(l * 0.6), int(hv * 0.65)),
                        0, 0, 360, 0, -1)
    except Exception:
        pass
    if traits.any():
        out = reconstituer(out, cv2.dilate(traits, np.ones((3, 3), np.uint8)))
    return out, float((s > 0.3).mean()), (a0, b0)


def ton_d_origine(gris, teinte):
    """Rend au tirage restauré (gris) sa teinte d'origine (sépia) : pleine dans les tons
    moyens, discrète dans les noirs et les blancs, comme sur un tirage viré."""
    a0, b0 = teinte
    L = cv2.cvtColor(gris, cv2.COLOR_BGR2GRAY).astype(np.float32)
    l = L / 255.0
    f = np.clip(4.8 * l * (1 - l), 0.3, 1.0)
    lab = np.dstack([L, 128 + (a0 - 128) * f, 128 + (b0 - 128) * f]).astype(np.uint8)
    return cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)


def teinte_marquee(teinte):
    """Vrai si le tirage d'origine a une teinte (sépia, brun) et n'est pas simplement gris."""
    return teinte is not None and abs(teinte[0] - 128) + abs(teinte[1] - 128) > 3


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
    s = ia._session('scunet-512')
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


# ---------- fond de studio uni (option) ----------

FOND_PART = (0.1, 0.9)        # part du fond pour laquelle l'option a un sens


def fond_uni(img):
    """Option « fond de studio uni » : le fond derrière les personnes devient un dégradé
    lisse tiré de ses propres tons (éclairage d'origine gardé ; taches, auréoles et texture
    abîmée disparus), avec un grain léger. Renvoie (image, part du fond, masque du fond 0..1),
    ou (img, 0, None) si les personnes ne sont pas séparées du fond de façon sûre. Les
    personnes coupées par le bas de la photo (jupe, bras) le restent : le bas n'est repeint
    que là où le fond y est déjà sûr. C'est une retouche qui change la
    photo : désactivée par défaut."""
    from shared import vision
    # MODNet seul : un fond de studio va avec un portrait posé, son domaine ; l'arbitrage avec
    # MobileSAM (vision.personnes) prend toute l'image sur un portrait serré
    m = vision.detourer(img)
    fond = 1.0 - np.clip(m, 0, 1)
    part = float((fond > 0.5).mean())
    if not FOND_PART[0] <= part <= FOND_PART[1]:
        return img, 0.0, None
    h, w = m.shape
    d = max(h, w)
    sur = cv2.erode((fond > 0.9).astype(np.float32), np.ones((5, 5), np.uint8))   # fond sûr
    lisse = np.empty_like(img, dtype=np.float32)
    for c in range(3):
        x = img[..., c].astype(np.float32)
        lisse[..., c] = cv2.GaussianBlur(x * sur, (0, 0), d / 10) / np.maximum(cv2.GaussianBlur(sur, (0, 0), d / 10), 1e-3)
    grain = np.random.default_rng(7).normal(0, 1.2, (h, w)).astype(np.float32)[..., None]
    lisse = lisse + grain
    a = np.clip((fond - 0.05) / 0.9, 0, 1)
    # bas de la photo : MODNet y hésite (personnes coupées par le bord) ; on n'y repeint que le
    # fond sûr, avec une transition sur le dernier dixième de la hauteur
    bas = np.clip((np.arange(h, dtype=np.float32) - 0.9 * h) / (0.1 * h), 0, 1)[:, None]
    a = a * (1 - bas) + a * sur * bas
    a = cv2.GaussianBlur(a, (0, 0), max(1.0, d / 800))
    out = img.astype(np.float32) * (1 - a[..., None]) + lisse * a[..., None]
    return np.clip(out, 0, 255).round().astype(np.uint8), part, a


# ---------- tout ensemble ----------

AXE2_MAX = 2.5                # dispersion des couleurs hors de leur axe principal (Lab) d'un tirage


def tirage_monochrome(img):
    """Vrai pour un tirage noir et blanc ou sépia, même jauni ou taché : ses couleurs ne
    varient que le long d'un seul axe (du gris au brun). Mesuré : tirages anciens 1,0 à 1,9 ;
    portraits en couleur 3,0 et plus. Une encre ou une tache isolée ne change presque rien."""
    lab = cv2.cvtColor(cv2.resize(img, (256, 256), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2LAB)
    ab = lab[..., 1:].reshape(-1, 2).astype(np.float64)
    ab -= ab.mean(axis=0)
    return float(np.sqrt(max(0.0, np.linalg.eigvalsh(np.cov(ab.T))[0]))) < AXE2_MAX


def reparer(img, monochrome=None):
    """Répare `img` (BGR) ; renvoie (image, lignes de journal, teinte du tirage ou None).
    monochrome : None pour le déterminer (tirage_monochrome) ; les taches et la teinte ne
    sont traitées que sur un tirage monochrome."""
    if monochrome is None:
        monochrome = tirage_monochrome(img)
    journal = []
    teinte = None
    m, part = manques(img)
    if m is not None:
        img = reconstituer(img, m, grand=True)
        journal.append('parties arrachées reconstituées (LaMa) : %.1f %% de l\'image' % (part * 100))
    if monochrome:
        img, part, teinte = taches(img)
        if part > 0.001:
            journal.append('taches atténuées, teinte du tirage unifiée : %.1f %% de l\'image' % (part * 100))
    m = rayures(img)
    if m.mean() > 0.0005:
        img = reconstituer(img, m)
        journal.append('rayures, fissures et déchirures effacées (LaMa) : %.1f %% de l\'image' % (m.mean() * 100))
    else:
        journal.append('aucune rayure ni fissure trouvée')
    if ia.available('scunet-512'):
        bruit = grain(img)
        if bruit > SEUIL_GRAIN:
            import time
            t = time.time()
            img = debruiter(img)
            journal.append('grain atténué (SCUNet) : bruit %.1f -> %.1f, %.0f s' % (bruit, grain(img), time.time() - t))
        else:
            journal.append('grain faible (%.1f) : débruitage inutile' % bruit)
    return img, journal, teinte

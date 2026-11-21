"""Vision locale des applications du hub, identique sous macOS et Windows (ONNX, processeur).

Remplace Apple Vision (rexo-segment) :
    visages(img)        YuNet : cadres et 5 repères de chaque visage, du plus grand au plus petit
    reperes(img, v)     MediaPipe Face Mesh V2 : 478 points du visage `v` (iris compris)
    ouverture_oeil(oeil, angle)   hauteur / largeur de l'œil (repères Face Mesh) : petit = fermé
                        ou plissé ; commune à Rexo ID et Rexo Dock
    rotation(angle)     matrice qui ramène la ligne des yeux à l'horizontale
    empreinte_visage(img, v)   SFace : empreinte d'identité du visage `v` (128 valeurs, norme 1) ;
                        deux visages de la même personne : cosinus >= MEME_PERSONNE
    detourer(img)       MODNet : masque des personnes de 0 à 1, cheveux compris (portraits)
    personnes(img)      masque des personnes sur toute photo : MODNet, vérifié et au besoin
                        remplacé par MobileSAM guidé par les visages (groupes, scènes chargées)
    analyser_visage(img)   les trois à la suite : visage principal (dict) et masque

Modèles chargés par le catalogue commun du hub (shared/ia : manifestes, licences, sessions) :
    python -m shared.embedkit.cli --models-path shared/ia/modeles models pull \\
        --allow-noncommercial yunet-2023mar facemesh-v2 modnet
(empreinte_visage() utilise sface-2021dec : données biométriques, voir l'ADR 0005.)
(personnes() utilise aussi mobilesam, manifeste livré avec embedkit.)
Images en BGR uint8 (OpenCV), coordonnées en pixels, origine en haut à gauche.
"""

import math
import os
import threading

import cv2
import numpy as np

from shared import ia as _ia  # noqa: E402

# Indices MediaPipe Face Mesh (478 points). « Gauche » et « droite » : côtés de l'image.
MACHOIRE = [454, 323, 361, 288, 397, 365, 379, 378, 400, 377, 152,
            148, 176, 149, 150, 136, 172, 58, 132, 93, 234]          # d'une oreille à l'autre
OEIL_IMAGE_GAUCHE = [33, 7, 163, 144, 145, 153, 154, 155, 133, 173, 157, 158, 159, 160, 161, 246]
OEIL_IMAGE_DROITE = [263, 249, 390, 373, 374, 380, 381, 382, 362, 398, 384, 385, 386, 387, 388, 466]
IRIS_IMAGE_GAUCHE, IRIS_IMAGE_DROITE = 468, 473
JOUE_GAUCHE, JOUE_DROITE, MENTON, NEZ = 234, 454, 152, 1


class VisionError(RuntimeError):
    pass


def rotation(angle):
    """Matrice qui ramène la ligne des yeux à l'horizontale (angle en degrés, repère image, y
    vers le bas)."""
    t = math.radians(angle)
    return np.array([[math.cos(t), math.sin(t)], [-math.sin(t), math.cos(t)]])


def ouverture_oeil(oeil, angle=None):
    """Hauteur / largeur d'un œil (ses repères Face Mesh, en pixels), dans le repère redressé :
    petit = œil fermé ou plissé (Rexo ID et Rexo Dock : sous 0,15). `angle` : inclinaison de la
    ligne des yeux en degrés ; sans angle, redressé par les coins de l'œil (points 0 et 8 des
    listes OEIL_IMAGE_*). None si l'œil n'a pas de largeur."""
    oeil = np.asarray(oeil, np.float64)[:, :2]
    if len(oeil) < 3:
        return None
    if angle is None:
        (x0, y0), (x1, y1) = oeil[0], oeil[8]
        angle = math.degrees(math.atan2(y1 - y0, x1 - x0))
    p = oeil @ rotation(angle).T
    largeur = np.ptp(p[:, 0])
    return float(np.ptp(p[:, 1]) / largeur) if largeur > 0 else None


_verrou = threading.Lock()


def _chemin(model_id):
    """Fichier du modèle, par le catalogue commun (shared/ia)."""
    try:
        return _ia.chemin(model_id)
    except _ia.ModeleAbsent as e:
        raise VisionError(str(e)) from None


def _session(model_id):
    try:
        return _ia.session(model_id)
    except _ia.ModeleAbsent as e:
        raise VisionError(str(e)) from None


# ---------- visages (YuNet) ----------

_LONGUEUR_DETECTION = 640      # YuNet travaille sur une copie réduite (côté long 640)


def visages(img, seuil=0.8, longueur=None):
    """Liste de dicts {cadre (x, y, l, h), points (5 × 2 : œil gauche et droit de l'image, nez,
    coins de la bouche), score}, du plus grand visage au plus petit. `longueur` : côté long de
    la copie où l'on cherche (640 par défaut, rapide pour un portrait) ; plus grand pour une
    photo de groupe aux petits visages (mesuré : 6 visages sur 7 trouvés à 640, 7 à 1280)."""
    h, w = img.shape[:2]
    f = min(1.0, (longueur or _LONGUEUR_DETECTION) / max(h, w))
    petite = cv2.resize(img, (round(w * f), round(h * f)), interpolation=cv2.INTER_AREA) if f < 1 else img
    with _verrou:
        det = cv2.FaceDetectorYN.create(str(_chemin('yunet-2023mar')), '',
                                        (petite.shape[1], petite.shape[0]), seuil, 0.3, 50)
        _, res = det.detect(petite)
    out = []
    for r in (res if res is not None else []):
        pts = r[4:14].reshape(5, 2) / f
        if pts[0, 0] > pts[1, 0]:                      # œil de gauche dans l'image d'abord
            pts[[0, 1]] = pts[[1, 0]]
        out.append({'cadre': tuple(float(v) / f for v in r[:4]), 'points': pts, 'score': float(r[14])})
    out.sort(key=lambda v: v['cadre'][2], reverse=True)
    return out


# ---------- reconnaissance (SFace) ----------

MEME_PERSONNE = 0.363          # seuil de cosinus d'OpenCV pour SFace (même identité au-dessus)
_reconnaisseur = None


def empreinte_visage(img, visage):
    """Empreinte d'identité (128 valeurs float32, norme 1) du visage détecté `visage` :
    visage aligné sur 112 × 112 par ses 5 repères (YuNet), puis SFace. Donnée biométrique :
    à ne calculer qu'avec l'accord du photographe, et à garder au plus près de la photo."""
    global _reconnaisseur
    x, y, l, h = visage['cadre']
    ligne = np.array([x, y, l, h, *np.asarray(visage['points'], np.float32).ravel(), visage['score']],
                     np.float32).reshape(1, 15)
    with _verrou:
        if _reconnaisseur is None:
            _reconnaisseur = cv2.FaceRecognizerSF.create(str(_chemin('sface-2021dec')), '')
        aligne = _reconnaisseur.alignCrop(img, ligne)
        e = _reconnaisseur.feature(aligne).ravel().astype(np.float32)
    n = float(np.linalg.norm(e))
    return e / n if n > 0 else e


# ---------- repères denses (Face Mesh V2) ----------

_MAILLE = 256
_ECHELLE_DEPART = 1.6          # premier recadrage : autour du cadre de YuNet
_ECHELLE_REPERES = 1.5         # recadrages suivants : autour des points trouvés (MediaPipe)
_PASSES = 3


def _maille(img, cx, cy, cote, angle):
    """Face Mesh sur le carré de côté `cote` centré en (cx, cy), tourné de `angle` (radians) :
    478 points (x, y, z) dans l'image, et la présence d'un visage (0 à 1)."""
    e = _MAILLE / cote
    c, s = math.cos(-angle) * e, math.sin(-angle) * e
    vers = np.array([[c, -s, _MAILLE / 2 - (c * cx - s * cy)],
                     [s, c, _MAILLE / 2 - (s * cx + c * cy)]], np.float64)
    interp = cv2.INTER_AREA if e < 1 else cv2.INTER_LINEAR
    rec = cv2.warpAffine(img, vers, (_MAILLE, _MAILLE), flags=interp, borderMode=cv2.BORDER_REPLICATE)
    entree = cv2.cvtColor(rec, cv2.COLOR_BGR2RGB).astype(np.float32)[None] / 255.0
    sess = _session('facemesh-v2')
    sorties = sess.run(None, {sess.get_inputs()[0].name: entree})
    pts = sorties[0].reshape(-1, 3).astype(np.float64)
    presence = 1 / (1 + math.exp(-float(np.ravel(sorties[1])[0])))
    inverse = cv2.invertAffineTransform(vers)
    xy = pts[:, :2] @ inverse[:, :2].T + inverse[:, 2]
    return np.column_stack([xy, pts[:, 2] / e]), presence


def reperes(img, visage):
    """478 points (x, y, z) dans l'image pour le visage détecté `visage`, et la présence.

    Face Mesh dépend beaucoup du recadrage qu'on lui donne (le menton bouge de 100 pixels
    entre 1,2 et 2 fois le cadre de YuNet). Comme MediaPipe, on recadre ensuite autour des
    points trouvés, redressés par les coins des yeux : en trois passes, le résultat ne dépend
    plus du premier cadre."""
    x, y, l, h = visage['cadre']
    yg, yd = visage['points'][0], visage['points'][1]
    angle = math.atan2(yd[1] - yg[1], yd[0] - yg[0])
    cx, cy, cote = x + l / 2, y + h / 2, max(l, h) * _ECHELLE_DEPART
    for i in range(_PASSES):
        pts, presence = _maille(img, cx, cy, cote, angle)
        if i == _PASSES - 1 or presence < 0.5:
            break
        a, b = pts[33, :2], pts[263, :2]                     # coins extérieurs des yeux
        angle = math.atan2(b[1] - a[1], b[0] - a[0])
        r = np.array([[math.cos(angle), math.sin(angle)], [-math.sin(angle), math.cos(angle)]])
        q = pts[:468, :2] @ r.T                               # repère redressé
        bas, haut = q.min(axis=0), q.max(axis=0)
        cx, cy = ((bas + haut) / 2) @ r
        cote = float(max(haut - bas)) * _ECHELLE_REPERES
    return pts, presence


def lacet(points):
    """Rotation gauche-droite de la tête, en degrés (0 de face), par la profondeur des joues."""
    a, b = points[JOUE_GAUCHE], points[JOUE_DROITE]
    return math.degrees(math.atan2(b[2] - a[2], math.hypot(b[0] - a[0], b[1] - a[1])))


# ---------- détourage (MODNet) ----------

_COTE_DETOURAGE = 512


def detourer(img):
    """Masque des personnes, float32 de 0 à 1, à la taille de l'image."""
    h, w = img.shape[:2]
    f = _COTE_DETOURAGE / min(h, w)
    nh, nw = (max(32, round(h * f / 32) * 32), max(32, round(w * f / 32) * 32))
    petite = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_AREA if f < 1 else cv2.INTER_CUBIC)
    x = (cv2.cvtColor(petite, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0 - 0.5) / 0.5
    sess = _session('modnet')
    alpha = sess.run(None, {sess.get_inputs()[0].name: x.transpose(2, 0, 1)[None]})[0][0, 0]
    return np.clip(cv2.resize(alpha, (w, h), interpolation=cv2.INTER_LINEAR), 0, 1).astype(np.float32)


# ---------- personnes sur toute photo (MODNet + MobileSAM) ----------

COUVERTURE_MIN = 0.8           # part du masque de SAM couverte par MODNet pour garder MODNet


def _iou(a, b):
    return float((a & b).sum()) / max(1, int((a | b).sum()))


def personnes(img):
    """Masque des personnes (0 à 1) et la méthode retenue.

    MODNet a appris sur des portraits : sur une scène chargée (cycliste devant une haie) ou
    une photo de groupe, il perd des personnes. MobileSAM, guidé par chaque visage (YuNet :
    un point sur le visage, un cadre du visage jusqu'en bas de la photo), les retrouve, avec
    des bords plus grossiers, et parfois seulement le visage. Si MODNet couvre presque tout ce
    que SAM a trouvé (≥ COUVERTURE_MIN), il n'a perdu personne : il est gardé tel quel. Sinon
    SAM décide, et MODNet n'affine que le voisinage de son masque (ce qu'il voit ailleurs est
    écarté)."""
    m = detourer(img)
    trouves = visages(img, seuil=0.6)
    if not trouves:
        return m, 'MODNet (aucun visage pour vérifier)'
    try:
        sam = _sam_visages(img, trouves)
    except Exception as e:                                  # modèle absent, etc.
        return m, 'MODNet (MobileSAM indisponible : %s)' % str(e)[:80]
    if not sam.any():
        return m, 'MODNet (MobileSAM n\'a rien retenu)'
    couvert = float(((m > 0.5) & (sam > 0)).sum()) / max(1, int(sam.sum()))
    if couvert >= COUVERTURE_MIN:
        return m, 'MODNet (couvre %.0f %% de MobileSAM)' % (couvert * 100)
    h, w = m.shape
    k = max(3, int(max(h, w) / 100)) | 1
    voisinage = cv2.dilate(sam, np.ones((k, k), np.uint8)).astype(np.float32)
    doux = cv2.GaussianBlur(sam.astype(np.float32), (k, k), 0)
    return np.maximum(doux, m * voisinage), 'MobileSAM guidé par %d visage(s), affiné par MODNet (qui n\'en couvrait que %.0f %%)' % (
        len(trouves), couvert * 100)


def _sam_visages(img, trouves):
    os.environ.setdefault('EMBEDKIT_OFFLINE', '1')        # jamais de réseau pendant un traitement
    from shared.embedkit.tasks.segment import Segmenter
    h, w = img.shape[:2]
    total = np.zeros((h, w), np.uint8)
    with Segmenter.load(model='mobilesam', registry=_ia.registre()) as seg:
        if seg.tier == 0:
            raise VisionError('modèle MobileSAM absent')
        emb = seg.embed(img)
        for v in trouves:
            x, y, l, hv = v['cadre']
            cx = x + l / 2
            cadre = (max(0, cx - 2.2 * l), max(0, y - 0.5 * hv), min(w, cx + 2.2 * l), h)
            masques, scores = seg.segment(emb, points=[(cx, y + hv / 2, 1)], box=cadre)
            # Une proposition n'est retenue que si elle couvre le visage désigné : sur un
            # portrait, le cadre prend presque toute la photo et la mieux notée peut être le fond.
            ix0, iy0 = int(max(0, x + 0.25 * l)), int(max(0, y + 0.25 * hv))
            ix1, iy1 = int(min(w, x + 0.75 * l)), int(min(h, y + 0.75 * hv))
            for k in np.argsort(-np.asarray(scores)):
                mk = masques[k].astype(np.uint8)
                if ix1 > ix0 and iy1 > iy0 and mk[iy0:iy1, ix0:ix1].mean() > 0.8:
                    total |= mk
                    break
    return total


# ---------- tout ensemble ----------

def analyser_visage(img):
    """Visage principal et masque : ({cadre, pupilles (2 × 2, de gauche à droite), contour
    (mâchoire), yeux (deux contours, de gauche à droite), lacet, autres, confiance, points},
    masque). Lève VisionError sans visage."""
    trouves = visages(img)
    if not trouves:
        raise VisionError('aucun visage trouvé')
    v = trouves[0]
    pts, presence = reperes(img, v)
    if presence < 0.5:
        raise VisionError('visage trop incertain')
    autres = sum(1 for g in trouves[1:] if g['cadre'][2] > 0.4 * v['cadre'][2])
    pupilles = np.array(sorted([pts[IRIS_IMAGE_GAUCHE, :2], pts[IRIS_IMAGE_DROITE, :2]],
                               key=lambda p: p[0]), np.float64)
    yeux = sorted((pts[OEIL_IMAGE_GAUCHE, :2], pts[OEIL_IMAGE_DROITE, :2]), key=lambda e: e[:, 0].mean())
    visage = {'cadre': v['cadre'], 'pupilles': pupilles, 'contour': pts[MACHOIRE, :2],
              'yeux': list(yeux), 'lacet': lacet(pts), 'autres': autres,
              'confiance': v['score'], 'points': pts}
    return visage, detourer(img)

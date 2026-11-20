"""Conversion d'une image de n'importe quel format pris en charge vers PNG ou JPEG.

Chaque outil couvre des formats différents (mesuré sur macOS 12, Intel) :

    format        Pillow 11.3   PhotoCraft 0.23   sips (macOS)
    AVIF          oui           non (écriture)    non
    HEIC / HEIF   non           oui               oui
    GIF, TGA      oui           oui               oui
    JPEG 2000     selon build   non               oui
    PSD           aplati        oui               oui

On essaie donc Pillow, puis PhotoCraft (photocraft-cli convert), puis sips ; le premier qui
réussit gagne. `lire` lit une image de n'importe lequel de ces formats en pleine taille,
comme OpenCV la lirait (orientation EXIF appliquée), pour toutes les applications. `reduire` lit une image de n'importe lequel de ces formats en version réduite
(analyse, vignettes), sans écrire de copie en pleine taille. `image_de_video` tire une image
réduite d'une vidéo (H.264 et HEVC de l'iPhone, rotation appliquée), par OpenCV : identique
sous macOS et Windows. Les pixels transparents sont posés sur du blanc. Pour un GIF animé ou un fichier
à plusieurs images, seule la première image est gardée.
"""

import subprocess
import sys
from pathlib import Path


# Formats acceptés par les applications (en plus de ceux qu'OpenCV lit directement)
FORMATS = {
    '.jpg', '.jpeg', '.jpe', '.png', '.tif', '.tiff', '.webp', '.bmp',
    '.gif', '.tga', '.avif', '.heic', '.heif', '.jp2', '.psd', '.exr', '.hdr', '.qoi', '.ico',
}


class ConversionImpossible(RuntimeError):
    pass


def _pillow(src, dst):
    try:
        from PIL import Image
    except ImportError:
        return False
    try:
        with Image.open(src) as im:
            im.seek(0)
            if im.mode in ('RGBA', 'LA', 'P', 'PA'):
                rgba = im.convert('RGBA')
                fond = Image.new('RGB', rgba.size, 'white')
                fond.paste(rgba, mask=rgba.split()[3])
                im = fond
            elif im.mode not in ('RGB', 'L'):
                im = im.convert('RGB')
            if dst.suffix.lower() in ('.jpg', '.jpeg'):
                im.convert('RGB').save(dst, 'JPEG', quality=90)
            else:
                im.save(dst, 'PNG')
        return dst.is_file() and dst.stat().st_size > 0
    except Exception:
        return False


def _photocraft(src, dst):
    from shared.photocraft import trouver_cli
    cli = trouver_cli()
    if cli is None:
        return False
    try:
        r = subprocess.run([str(cli), 'convert', str(src), str(dst)],
                           capture_output=True, timeout=300)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return r.returncode == 0 and dst.is_file() and dst.stat().st_size > 0


def _sips(src, dst):
    if sys.platform != 'darwin':                 # outil de macOS
        return False
    fmt = 'jpeg' if dst.suffix.lower() in ('.jpg', '.jpeg') else 'png'
    try:
        r = subprocess.run(['sips', '-s', 'format', fmt, str(src), '--out', str(dst)],
                           capture_output=True, timeout=300)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return r.returncode == 0 and dst.is_file() and dst.stat().st_size > 0


OUTILS = (('Pillow', _pillow), ('PhotoCraft', _photocraft), ('sips', _sips))


def convertir(src, dst):
    """Convertit `src` en `dst` (PNG ou JPEG selon l'extension). Renvoie le nom de l'outil utilisé."""
    src, dst = Path(src), Path(dst)
    if dst.suffix.lower() not in ('.png', '.jpg', '.jpeg'):
        raise ValueError('Destination PNG ou JPEG attendue : %s' % dst.name)
    dst.parent.mkdir(parents=True, exist_ok=True)
    for nom, outil in OUTILS:
        if dst.exists():
            dst.unlink()
        if outil(src, dst):
            return nom
    raise ConversionImpossible('Aucun outil ne sait lire %s (essayés : Pillow, PhotoCraft, sips)' % src.name)


def lire(src, travail=None, alpha=False):
    """(image BGR uint8, outil de conversion ou None si OpenCV l'a lue directement). OpenCV
    d'abord ; sinon conversion sans perte en PNG (Pillow, PhotoCraft ou sips) dans `travail`
    (un dossier temporaire effacé ensuite s'il n'est pas donné). `alpha` : garder la
    transparence (BGRA ; une image en niveaux de gris devient BGR). Lève ConversionImpossible."""
    import tempfile

    import cv2
    drapeau = cv2.IMREAD_UNCHANGED if alpha else cv2.IMREAD_COLOR

    def ouvrir(chemin):
        img = cv2.imread(str(chemin), drapeau)
        if img is not None and alpha and img.ndim == 2:
            img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
        return img

    src = Path(src)
    img = ouvrir(src)
    if img is not None:
        return img, None
    with tempfile.TemporaryDirectory(prefix='rexo-lire-') as tmp:
        dossier = Path(travail) if travail is not None else Path(tmp)
        dossier.mkdir(parents=True, exist_ok=True)
        png = dossier / 'converti.png'
        outil = convertir(src, png)
        img = ouvrir(png)
    if img is None:
        raise ConversionImpossible('Image illisible : %s' % src.name)
    return img, outil


def reduire(src, cote):
    """Image BGR (OpenCV) réduite à `cote` pixels de côté long, orientation EXIF appliquée ;
    jamais agrandie. HEIC sous macOS : sips réduit directement (rapide) ; sinon conversion."""
    import tempfile

    import cv2
    src = Path(src)
    img = None
    if src.suffix.lower() not in ('.heic', '.heif', '.avif'):
        img = cv2.imread(str(src), cv2.IMREAD_COLOR)            # applique l'orientation EXIF
    if img is None:
        with tempfile.TemporaryDirectory() as d:
            dst = Path(d) / 'reduite.jpg'
            ok = False
            if sys.platform == 'darwin':
                try:
                    r = subprocess.run(['sips', '-s', 'format', 'jpeg', '-Z', str(int(cote)), str(src),
                                        '--out', str(dst)], capture_output=True, timeout=120)
                    ok = r.returncode == 0 and dst.is_file()
                except (OSError, subprocess.TimeoutExpired):
                    ok = False
            if not ok:
                convertir(src, dst)
            img = cv2.imread(str(dst), cv2.IMREAD_COLOR)
    if img is None:
        raise ConversionImpossible('Image illisible : %s' % src.name)
    h, w = img.shape[:2]
    f = cote / max(h, w)
    if f < 1:
        img = cv2.resize(img, (round(w * f), round(h * f)), interpolation=cv2.INTER_AREA)
    return img


def image_de_video(src, cote, seconde=1.0):
    """Image BGR réduite à `cote` pixels de côté long, prise à `seconde` du début (une vidéo
    commence souvent par une image noire), ou la première si la vidéo est plus courte."""
    import cv2
    cap = cv2.VideoCapture(str(src))
    try:
        if not cap.isOpened():
            raise ConversionImpossible('Vidéo illisible : %s' % Path(src).name)
        fps = cap.get(cv2.CAP_PROP_FPS) or 0
        n = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0
        if fps > 0 and n > fps * seconde:
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(fps * seconde))
        ok, img = cap.read()
        if not ok:
            cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            ok, img = cap.read()
        if not ok or img is None:
            raise ConversionImpossible('Aucune image lisible dans %s' % Path(src).name)
    finally:
        cap.release()
    h, w = img.shape[:2]
    f = cote / max(h, w)
    if f < 1:
        img = cv2.resize(img, (round(w * f), round(h * f)), interpolation=cv2.INTER_AREA)
    return img

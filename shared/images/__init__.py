"""Conversion d'une image de n'importe quel format pris en charge vers PNG ou JPEG.

Chaque outil couvre des formats différents (mesuré sur macOS 12, Intel) :

    format        Pillow 11.3   PhotoCraft 0.23   sips (macOS)
    AVIF          oui           non (écriture)    non
    HEIC / HEIF   non           oui               oui
    GIF, TGA      oui           oui               oui
    JPEG 2000     selon build   non               oui
    PSD           aplati        oui               oui

On essaie donc Pillow, puis PhotoCraft (photocraft-cli convert), puis sips ; le premier qui
réussit gagne. `reduire` lit une image de n'importe lequel de ces formats en version réduite
(analyse, vignettes), sans écrire de copie en pleine taille. Les pixels transparents sont posés sur du blanc. Pour un GIF animé ou un fichier
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

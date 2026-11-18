"""Dessine l'icône d'une application du hub (PNG 1024 × 1024), avec Pillow.

    python icone.py identite|reveal <sortie.png>
    python icone.py identite|reveal <sortie.ico>      (Windows : 16 à 256 pixels)

Carré arrondi sombre, pictogramme ambré : une photo d'identité (visage dans un cadre)
pour Rexo ID, un diaphragme pour Rexo Reveal.
"""

import math
import sys

from PIL import Image, ImageDraw, ImageFilter

N = 1024
AMBRE = (232, 180, 106)
CUIVRE = (217, 140, 95)


def fond():
    img = Image.new('RGBA', (N, N), (0, 0, 0, 0))
    ombre = Image.new('RGBA', (N, N), (0, 0, 0, 0))
    ImageDraw.Draw(ombre).rounded_rectangle((100, 120, 924, 944), 190, fill=(0, 0, 0, 140))
    img.alpha_composite(ombre.filter(ImageFilter.GaussianBlur(24)))
    # dégradé vertical, masqué par le carré arrondi
    degrade = Image.new('RGBA', (N, N))
    d = ImageDraw.Draw(degrade)
    for y in range(N):
        t = y / N
        d.line([(0, y), (N, y)], fill=(int(40 - 16 * t), int(38 - 15 * t), int(44 - 16 * t), 255))
    masque = Image.new('L', (N, N), 0)
    ImageDraw.Draw(masque).rounded_rectangle((100, 100, 924, 924), 190, fill=255)
    img.paste(degrade, (0, 0), masque)
    ImageDraw.Draw(img).rounded_rectangle((100, 100, 924, 924), 190, outline=(70, 68, 76, 255), width=6)
    return img


def identite(img):
    d = ImageDraw.Draw(img)
    # la photo (35 × 45) : cadre ambré, fond gris clair, silhouette sombre
    x0, y0, x1, y1 = 322, 202, 702, 690
    d.rounded_rectangle((x0 - 18, y0 - 18, x1 + 18, y1 + 18), 34, fill=AMBRE)
    w, h = x1 - x0, y1 - y0
    photo = Image.new('RGBA', (w, h), (214, 214, 214, 255))
    p = ImageDraw.Draw(photo)
    cx = w // 2
    p.ellipse((cx - 92, 96, cx + 92, 306), fill=(58, 56, 64))                 # tête
    p.chord((cx - 175, 340, cx + 175, 700), 180, 360, fill=(58, 56, 64))     # épaules
    img.paste(photo, (x0, y0))
    # traits de coupe sous la photo
    for x in (x0 - 18, x1 + 18):
        d.line([(x, 750), (x, 830)], fill=CUIVRE, width=10)
    d.line([(x0 - 90, 790), (x1 + 90, 790)], fill=CUIVRE, width=10)
    return img


def reveal(img):
    d = ImageDraw.Draw(img)
    c, r = N // 2, 270
    d.ellipse((c - r, c - r, c + r, c + r), outline=AMBRE, width=44)
    for k in range(6):
        a = math.radians(60 * k + 15)
        b = math.radians(60 * k + 75)
        p1 = (c + 0.92 * r * math.cos(a), c + 0.92 * r * math.sin(a))
        p2 = (c + 0.36 * r * math.cos(b), c + 0.36 * r * math.sin(b))
        d.line([p1, p2], fill=CUIVRE, width=30)
    d.ellipse((c - 70, c - 70, c + 70, c + 70), fill=AMBRE)
    return img


def main():
    nom, sortie = sys.argv[1], sys.argv[2]
    dessins = {'identite': identite, 'reveal': reveal}
    if nom not in dessins:
        sys.exit('application inconnue : %s' % nom)
    img = dessins[nom](fond())
    if sortie.lower().endswith('.ico'):
        img.save(sortie, sizes=[(t, t) for t in (16, 24, 32, 48, 64, 128, 256)])
    else:
        img.save(sortie)


if __name__ == '__main__':
    main()

#!/usr/bin/env python3
"""Retouche automatique avec PhotoCraft piloté par Python.

Portraits (photos couleur)   : visages par IA (GFPGAN, calque à 50 %), lissage de la peau
                               + maquillage
                               (lèvres, blush, paupières) placés grâce aux repères du visage
                               (PhotoCraft image.detectFaces).
Photos anciennes (N&B/sépia) : agrandissement x2 si petite (Real-ESRGAN), puis
                               restauration complète (recadrage du tirage, gris neutre,
                               stries, rayures, bruit, voile, contraste, netteté ; fichier
                               visages par IA (GFPGAN) ; fichier NOM_photocraft_restauree.jpg),
                               puis colorisation (DDColor) en calque séparé au-dessus.
Les modèles IA (embedkit, manifestes dans apps/reveal/modeles) tournent sur le processeur, sans connexion.

Résultat : retouche/NOM_photocraft.psd (calques modifiables), NOM_photocraft.jpg, et
NOM_photocraft_avant.jpg (l'original à la même géométrie, pour comparer avant / après).
Les fichiers de original/ ne sont jamais modifiés.

Utilisation (depuis le dossier apps/reveal) :
    .venv/bin/python -m reveal.traiter                         # toutes les photos de donnees/original/
    .venv/bin/python -m reveal.traiter donnees/original/1.jpg  # une photo
    .venv/bin/python -m reveal.traiter --type ancienne donnees/original/x.jpg   # forcer le type
"""

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

import numpy as np

from shared.images import ConversionImpossible
from shared.photocraft import PhotoCraft, PhotoCraftError

from . import analyse, ia, vision
from .config import DONNEES, IMAGES, ORIGINAL, REGLAGES, RETOUCHE
from .config import TRAVAIL as WORK


def reglages(photo):
    """Réglages propres à une photo dans reglages.json (ex. visages exclus de GFPGAN)."""
    try:
        return json.loads(REGLAGES.read_text(encoding='utf-8')).get(photo.name, {})
    except (OSError, ValueError):
        return {}


def faces_for_ai(job, faces):
    """Liste les visages (centre en % de l'image) et retire ceux exclus dans reglages.json."""
    excl = reglages(job.src).get('visages_exclus_ia', [])
    kept = []
    for i, f in enumerate(faces, 1):
        cx = float((f.eye_l[0] + f.eye_r[0] + f.mouth_c[0]) / 3) / job.width
        cy = float((f.eye_l[1] + f.eye_r[1] + f.mouth_c[1]) / 3) / job.height
        out = any(abs(cx - ex) < 0.05 and abs(cy - ey) < 0.05 for ex, ey in excl)
        log('    visage %d : centre (%.2f, %.2f), score %.2f%s'
            % (i, cx, cy, f.score, '  -> exclu de GFPGAN' if out else ''))
        if not out:
            kept.append(f)
    return kept

# Maquillage : (nom, couleur, mode, opacité)
MAKEUP = {
    'levres': ('Rouge à lèvres', '#a8253f', 'Color', 0.55),
    'blush': ('Blush', '#e0707c', 'Soft Light', 0.30),
    'fard': ('Fard à paupières', '#7a4a6e', 'Multiply', 0.30),
}


def deselect(pc):
    """Désélectionne s'il y a une sélection (certaines commandes la consomment déjà)."""
    if pc.call('doc.inspect').get('hasSelection'):
        pc.cmd('select.deselect')


def log(msg):
    print(msg, flush=True)


class Job:
    """Une photo ouverte dans PhotoCraft (document 0) et son dossier de travail."""

    def __init__(self, pc, src, image=None):
        """image : version préparée en Python (ex. agrandie) à ouvrir à la place de l'original."""
        self.pc = pc
        self.src = src
        self.work = WORK / src.stem
        self.work.mkdir(parents=True, exist_ok=True)
        path = src
        if image is not None:
            path = self.work / 'depart.png'
            analyse.cv2.imwrite(str(path), image)
        info = pc.call('doc.open', path=str(path))
        self.index = info['index']
        self.width, self.height = info['width'], info['height']
        self.img = analyse.load(path)
        self.extras = []          # images complémentaires enregistrées avec le résultat (suffixe, image)
        self.extra_files = []     # fichiers complémentaires copiés tels quels (suffixe, chemin)

    def select_from_mask(self, mask, name):
        """Charge un masque calculé en Python comme sélection dans le document de la photo."""
        path = self.work / (name + '.png')
        analyse.save_mask(mask, path)
        other = self.pc.call('doc.open', path=str(path))['index']
        self.pc.call('doc.select', index=self.index)
        self.pc.cmd('select.loadSelection', document=other, channel='red')
        self.pc.call('doc.close', index=other)
        self.pc.call('doc.select', index=self.index)

    def output_paths(self):
        base = self.src.stem + '_photocraft'
        name, n = base, 1
        while (RETOUCHE / (name + '.psd')).exists() or (RETOUCHE / (name + '.jpg')).exists():
            n += 1
            name = '%s_%d' % (base, n)
        return RETOUCHE / (name + '.psd'), RETOUCHE / (name + '.jpg')

    def save(self):
        psd, jpg = self.output_paths()
        self.pc.call('doc.save', path=str(psd))
        self.pc.call('doc.save', path=str(jpg), quality=92)
        self.pc.call('doc.close', index=self.index)
        self.outputs = {'psd': psd.name, 'jpg': jpg.name}
        for suffix, image in getattr(self, 'extras', []):
            path = jpg.with_name(jpg.stem + suffix + '.jpg')
            analyse.cv2.imwrite(str(path), image, [analyse.cv2.IMWRITE_JPEG_QUALITY, 92])
            self.outputs[suffix.strip('_')] = path.name
        for suffix, src in getattr(self, 'extra_files', []):
            path = jpg.with_name(jpg.stem + suffix + Path(src).suffix)
            shutil.copyfile(src, path)
            self.outputs[suffix.strip('_')] = path.name
        return psd, jpg


# ---------- portraits ----------

def portrait(job):
    pc = job.pc
    job.extras.append(('_avant', export_current(job, 'avant')))
    faces = analyse.faces_from(pc.cmd('image.detectFaces', minScore=0.5), min_score=0.8)
    if not faces:
        log('  aucun visage net détecté : portrait ignoré')
        return False
    log('  %d visage(s) détecté(s)' % len(faces))
    d = max(f.eye_dist for f in faces)

    # Visages par IA (GFPGAN), calque séparé à 50 % pour garder le grain et la ressemblance
    if ia.available('gfpgan-1.4'):
        t = time.time()
        try:
            restored = ia.restore_faces(job.img, faces, blend=1.0)
            path = job.work / 'visages.png'
            analyse.cv2.imwrite(str(path), restored)
            pc.call('doc.place', path=str(path))
            pc.cmd('layer.setProps', name='Visages (IA)', opacity=0.5)
            log('  visages restaurés (GFPGAN) : %.1f s' % (time.time() - t))
        except Exception as e:
            log('  restauration des visages impossible : %s' % str(e)[:120])
    base = export_current(job, 'base_portrait')        # image vue à ce stade (fond + visages)

    # Lissage : flou de surface (garde les contours) sur une copie de l'image vue, limité à la peau
    path = job.work / 'lissage.png'
    analyse.cv2.imwrite(str(path), base)
    pc.call('doc.place', path=str(path))
    pc.cmd('layer.rasterize.smartObject')
    pc.cmd('layer.setProps', name='Lissage peau')
    pc.cmd('filter.blur.surfaceBlur', radius=max(3, round(d / 10)), threshold=16)
    pc.cmd('filter.noise.addNoise', amount=1.5, distribution='gaussian', monochromatic=True, seed=7)
    skin = analyse.skin_mask(base, faces)
    # A. La peau seulement sur les personnes (Apple Vision) : le fond couleur chair n'est plus lissé
    if vision.disponible():
        try:
            people, part = vision.masque_personnes(job.work / 'base_portrait.png', job.work / 'personnes.png')
            k = max(3, int(d * 0.15)) | 1
            people = analyse.cv2.GaussianBlur(analyse.cv2.dilate(people, np.ones((k, k), np.uint8)), (k, k), 0)
            before = analyse.coverage(skin)
            skin = skin * people
            log('  personnes (Apple Vision) : %.0f %% de l\'image ; peau limitée aux personnes : %.0f %% -> %.0f %%'
                % (part * 100, before * 100, analyse.coverage(skin) * 100))
        except vision.VisionError as e:
            log('  masque des personnes indisponible : %s' % str(e)[:120])
    log('  peau : %.0f %% de l\'image' % (analyse.coverage(skin) * 100))
    job.select_from_mask(skin, 'peau')
    pc.cmd('layer.layerMask.revealSelection')
    deselect(pc)
    pc.cmd('layer.setProps', opacity=0.5)

    # Maquillage : un calque de couleur par zone, masqué par la zone calculée
    pc.cmd('layer.new.group', name='Maquillage')
    masks = {'fard': sum_masks([analyse.eyeshadow_mask(base, f) for f in faces]),
             'blush': sum_masks([analyse.blush_mask(base, f, skin) for f in faces]),
             'levres': sum_masks([analyse.lips_mask(base, f) for f in faces])}
    for key in ('fard', 'blush', 'levres'):
        label, color, mode, opacity = MAKEUP[key]
        job.select_from_mask(masks[key], key)
        pc.cmd('layer.newFillLayer.solidColor', color=color)
        pc.cmd('layer.setProps', name=label, blend=mode, opacity=opacity)
        deselect(pc)
    return True


def ameliorer(job, style=None):
    """C. Amélioration automatique d'Apple (lumière, couleurs, balance des blancs, relief),
    puis rendu de couleur facultatif. Chaque étape est un calque du PSD."""
    pc = job.pc
    start = job.work / 'avant.png'
    job.extras.append(('_avant', export_current(job, 'avant')))
    out = job.work / 'ameliore.png'
    res = vision.ameliorer(start, out)
    pc.call('doc.place', path=str(out))
    pc.cmd('layer.setProps', name='Amélioration (Apple)')
    log('  amélioration : %s' % ', '.join(n.replace('CI', '') for n in res.get('enhance', [])))
    if style:
        styled = job.work / 'rendu.png'
        vision.rendu(out, styled, style)
        pc.call('doc.place', path=str(styled))
        pc.cmd('layer.setProps', name='Rendu : %s' % vision.STYLES[style])
        log('  rendu de couleur : %s' % vision.STYLES[style])
    return True


def studio(job, effet, couleur='255,255,255', ratio='4:5'):
    """B. Effets de studio sur les personnes détourées par Apple Vision."""
    pc = job.pc
    avant = export_current(job, 'avant')
    out = job.work / 'studio.png'
    res = vision.effet_studio(effet, job.work / 'avant.png', out, couleur=couleur, ratio=ratio)
    label = vision.STUDIO[effet][1]
    log('  personnes (Apple Vision) : %.0f %% de l\'image' % (res.get('coverage', 0) * 100))
    if effet == 'recadrage':
        x, y, w, h = res['box']
        pc.cmd('image.crop', x=x, y=y, width=w, height=h)
        job.width, job.height = w, h
        avant = avant[y:y + h, x:x + w]
        log('  recadrage %s : %dx%d (cadre %d, %d)' % (ratio, w, h, x, y))
    else:
        pc.call('doc.place', path=str(out))
        pc.cmd('layer.setProps', name=label if effet != 'fond-uni' else '%s (%s)' % (label, couleur))
        if effet == 'detourage':
            for layer in pc.cmd('layer.list')['layers']:
                if layer['name'] == 'Background':
                    pc.cmd('layer.setProps', layer=layer['id'], visible=False)
            job.extra_files.append(('_detoure', out))          # PNG transparent, livré tel quel
        log('  effet : %s' % label)
    job.extras.append(('_avant', avant))
    return True


def sum_masks(masks):
    out = masks[0]
    for m in masks[1:]:
        out = (out + m).clip(0, 1)
    return out


# ---------- photos anciennes ----------

def place_python_result(job, image, name):
    """Pose une image calculée en Python comme calque, puis la fusionne dans le calque de travail."""
    path = job.work / (name + '.png')
    analyse.cv2.imwrite(str(path), image)
    job.pc.call('doc.place', path=str(path))
    job.pc.cmd('layer.mergeDown')


def export_current(job, name):
    path = job.work / (name + '.png')
    job.pc.call('doc.save', path=str(path))
    return analyse.load(path)


def ancienne(job):
    pc = job.pc

    # 1. Recadrage / redressement du tirage (bord de papier)
    quad = analyse.print_quad(job.img)
    if quad:
        r = pc.cmd('image.perspectiveCrop', corners=quad)
        job.width, job.height = r['width'], r['height']
        log('  tirage recadré et redressé : %dx%d' % (job.width, job.height))
    longest = max(job.width, job.height)
    job.extras.append(('_avant', export_current(job, 'avant')))      # même géométrie que le résultat

    # 2. Gris neutre sur un calque de travail
    pc.cmd('layer.duplicate', name='Restauration')
    pc.cmd('image.adjustments.desaturate')

    # 3. Stries : atténuation (Python) puis rayures franches comblées (PhotoCraft)
    cur = export_current(job, 'avant_stries')
    lines = analyse.streak_lines(cur)
    fixed, changed = analyse.destreak(cur) if lines >= 6 else (cur, 0.0)
    if lines < 6:
        log('  pas de série de stries (%d ligne(s)) : correction des stries sautée' % lines)
    if changed > 0.002:
        place_python_result(job, fixed, 'stries')
        log('  stries atténuées : %.1f %% de l\'image' % (changed * 100))
        cur = fixed
    scratches = analyse.scratch_mask(cur)
    if analyse.coverage(scratches) > 0.0005:
        job.select_from_mask(scratches, 'rayures')
        pc.cmd('select.modify.expand', radius=1)
        pc.cmd('edit.contentAwareFill', sampling='auto', output='current', colorAdaptation='default')
        deselect(pc)
        log('  rayures franches comblées : %.1f %%' % (analyse.coverage(scratches) * 100))

    # 4. Bruit, poussières, artefacts JPEG
    pc.cmd('filter.noise.reduceNoise', strength=6, preserveDetails=55, reduceColorNoise=0,
           sharpenDetails=15, removeJpegArtifact=True)
    pc.cmd('filter.noise.dustAndScratches', radius=max(1, round(longest / 600)), threshold=8)

    # 5. Voile, contraste, ombres et hautes lumières (Camera Raw de PhotoCraft)
    pc.cmd('filter.cameraRaw', dehaze=25, clarity=18, texture=8, contrast=10,
           highlights=-35, shadows=30, whites=12, blacks=-18)
    pc.cmd('image.autoContrast')
    pc.cmd('filter.sharpen.unsharpMask', amount=70, radius=max(0.6, round(longest / 900, 1)), threshold=3)

    # 5 bis. Retouches ciblées de reglages.json (correcteur localisé de PhotoCraft le long d'un tracé)
    for r in reglages(job.src).get('correcteur', []):
        pts = [[x * job.width, y * job.height] for x, y in r['points']]
        size = max(3, round(r.get('taille', 0.008) * max(job.width, job.height)))
        pc.cmd('paint.spotHealing', points=pts, size=size, hardness=60, type='contentAware')
        log('  correcteur localisé : %s (%d px)' % (r.get('nom', 'tracé'), size))

    # 6. Visages restaurés par IA (GFPGAN), sur un calque séparé réglable
    if ia.available('gfpgan-1.4'):
        faces = [f for f in analyse.faces_from(pc.cmd('image.detectFaces', minScore=0.5), min_score=0.6)
                 if f.eye_dist >= 8]
        faces = faces_for_ai(job, faces)
        if faces:
            t = time.time()
            cur = export_current(job, 'avant_visages')
            try:
                fixed = ia.restore_faces(cur, faces)
            except Exception as e:
                log('  restauration des visages impossible : %s' % str(e)[:120])
                fixed = cur
            fixed = analyse.cv2.cvtColor(analyse.cv2.cvtColor(fixed, analyse.cv2.COLOR_BGR2GRAY),
                                         analyse.cv2.COLOR_GRAY2BGR)
            path = job.work / 'visages.png'
            analyse.cv2.imwrite(str(path), fixed)
            pc.call('doc.place', path=str(path))
            pc.cmd('layer.setProps', name='Visages (IA)', opacity=0.75)
            log('  %d visage(s) restauré(s) : %.1f s' % (len(faces), time.time() - t))

    # 7. Version restaurée seule (noir et blanc), pour juger la restauration
    restored = export_current(job, 'restauree')
    job.extras.append(('_restauree', restored))

    # 8. Colorisation de l'image restaurée (DDColor, sinon modèle OpenCV)
    t = time.time()
    try:
        color = ia.colorize_ddcolor(restored) if ia.available('ddcolor') else analyse.colorize(restored)
    except Exception as e:
        log('  DDColor impossible, modèle OpenCV utilisé : %s' % str(e)[:120])
        color = analyse.colorize(restored)
    colored = job.work / 'couleur.png'
    analyse.cv2.imwrite(str(colored), color)
    log('  colorisation : %.1f s' % (time.time() - t))
    pc.call('doc.place', path=str(colored))
    # Mode Normal : le calque contient déjà la luminance restaurée (le mode Couleur sursature)
    pc.cmd('layer.setProps', name='Colorisation (IA)', blend='Normal', opacity=1.0)
    return True


# ---------- principal ----------

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('photos', nargs='*', type=Path, help='photos à traiter (défaut : tout original/)')
    ap.add_argument('--type', choices=['auto', 'portrait', 'ancienne', 'ameliorer', 'studio'], default='auto')
    ap.add_argument('--effet', choices=sorted(vision.STUDIO), default='fond-flou', help='effet (avec --type studio)')
    ap.add_argument('--couleur', default='255,255,255', help='fond uni : couleur R,V,B (0-255)')
    ap.add_argument('--format', dest='ratio', choices=vision.FORMATS_RECADRAGE, default='4:5', help='recadrage')
    ap.add_argument('--style', choices=sorted(vision.STYLES), help='rendu de couleur (avec --type ameliorer)')
    args = ap.parse_args()

    photos = [p.resolve() for p in args.photos] or sorted(
        p for p in ORIGINAL.iterdir() if p.suffix.lower() in IMAGES)
    RETOUCHE.mkdir(parents=True, exist_ok=True)
    WORK.mkdir(parents=True, exist_ok=True)
    ok = 0
    try:
        with PhotoCraft(read_roots=[ORIGINAL, WORK] + sorted({p.parent for p in photos}),
                        write_root=DONNEES) as pc:
            for src in photos:
                log('== %s' % src.name)
                t = time.time()
                try:
                    img, outil = analyse.load_any(src, WORK / src.stem)
                    if outil:
                        log('  format %s converti par %s' % (src.suffix.lower().lstrip('.').upper(), outil))
                    kind = args.type
                    if kind == 'auto':
                        kind = 'ancienne' if analyse.is_monochrome(img) else 'portrait'
                    log('  type : %s' % kind)
                    start = img if outil else None          # photo convertie : PhotoCraft ouvre le PNG
                    if kind == 'ancienne' and max(img.shape[:2]) < 1600 and ia.available('real-esrgan-x2'):
                        t2 = time.time()
                        try:
                            start = ia.upscale_x2(img)
                            log('  agrandie x2 (Real-ESRGAN) : %dx%d, %.0f s'
                                % (start.shape[1], start.shape[0], time.time() - t2))
                        except Exception as e:
                            start = img if outil else None
                            log('  agrandissement impossible, taille d\'origine gardée : %s' % str(e)[:120])
                    job = Job(pc, src, start)
                    if kind == 'portrait':
                        done = portrait(job)
                    elif kind == 'ameliorer':
                        done = ameliorer(job, args.style)
                    elif kind == 'studio':
                        done = studio(job, args.effet, args.couleur, args.ratio)
                    else:
                        done = ancienne(job)
                    if done:
                        psd, jpg = job.save()
                        log('  -> %s, %s (%.0f s)' % (psd.name, jpg.name, time.time() - t))
                        log('RESULTAT ' + json.dumps(dict(job.outputs, photo=src.name, type=kind,
                                                          duree=round(time.time() - t))))
                        ok += 1
                    else:
                        pc.call('doc.close', index=job.index)
                except (PhotoCraftError, ValueError, ConversionImpossible) as e:
                    log('  ERREUR : %s' % e)
                    try:
                        for _ in range(5):
                            pc.call('doc.close', index=0)
                    except PhotoCraftError:
                        pass
    finally:
        shutil.rmtree(WORK, ignore_errors=True)
    log('%d/%d photo(s) traitée(s).' % (ok, len(photos)))
    return 0 if ok == len(photos) else 1


if __name__ == '__main__':
    sys.exit(main())

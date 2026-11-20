#!/usr/bin/env python3
"""Photo d'identité aux normes françaises et planches 10 × 15 cm, depuis un portrait.

Lancement (depuis apps/identite) :
    .venv/bin/python -m identite.fabriquer donnees/original/photo.jpg
    .venv/bin/python -m identite.fabriquer                      # toutes les photos de donnees/original/

Pour chaque photo, dans donnees/resultats/ (JPEG à 300 points par pouce) :
    NOM_identite.jpg            la photo seule, 35 × 45 mm
    NOM_planche_8.jpg           8 photos d'identité sur 10 × 15 cm, traits de coupe
    NOM_planche_4_portrait.jpg  4 photos d'identité et un portrait sur 10 × 15 cm
    NOM_rapport.json            mesures, couleurs et avertissements

Étapes : couleurs (balance des blancs, exposition), fond remplacé par un gris clair, tête
redressée et mise à l'échelle (32 à 36 mm du menton au sommet du crâne), contrôles.
Tout reste sur la machine.
"""

import argparse
import json
import sys
from pathlib import Path

import cv2
from PIL import Image

from shared.images import FORMATS, ConversionImpossible, lire

from . import cadrage, couleurs, fond, planche
from .config import ORIGINAL, RESULTATS
from .normes import (DPI, FRANCE, LACET_MAX, OUVERTURE_YEUX_MIN, PORTRAIT, ROULIS_MAX, MM_PAR_POUCE,
                     Norme)
from .visage import VisageError, analyser


def enregistrer(img_bgr, chemin, dpi=DPI):
    rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
    Image.fromarray(rgb).save(chemin, 'JPEG', quality=95, subsampling=0, dpi=(dpi, dpi))


def controler(visage, tete, masque, infos, couverture, norme, dpi=DPI):
    """Avertissements (la photo est produite quand même) : au photographe de juger."""
    avis = []
    if visage.autres:
        avis.append('%d autre(s) visage(s) sur la photo : le plus grand est retenu' % visage.autres)
    if abs(visage.lacet) > LACET_MAX:
        avis.append('tête tournée (%.0f°) : le visage doit être de face' % visage.lacet)
    if abs(tete.angle) > ROULIS_MAX:
        avis.append('tête très penchée (%.0f°), redressée : vérifier le résultat' % tete.angle)
    ouvertures = [cadrage.ouverture(o, tete.angle) for o in visage.yeux]
    ouvertures = [o for o in ouvertures if o is not None]
    if ouvertures and min(ouvertures) < OUVERTURE_YEUX_MIN:
        avis.append('yeux peut-être fermés ou plissés (ouverture %.2f)' % min(ouvertures))
    besoin = norme.tete * dpi / MM_PAR_POUCE
    if tete.hauteur < 0.75 * besoin:
        avis.append('définition faible : tête de %d pixels, agrandie %.1f fois (flou possible à '
                    "l'impression)" % (tete.hauteur, besoin / tete.hauteur))
    if infos['cheveux_mm'] < 0:
        avis.append('cheveux coupés par le bord haut de la photo d\'identité')
    x0, x1 = int(tete.centre[0] - 0.15 * masque.shape[1]), int(tete.centre[0] + 0.15 * masque.shape[1])
    if (masque[0, max(0, x0):max(1, x1)] > 0.5).mean() > 0.3:
        avis.append('haut de la tête coupé sur la photo d\'origine')
    if couverture['bas'] < 0.98:
        avis.append('photo d\'origine trop serrée : le bas (épaules) est complété en gris')
    return avis


def fabriquer(src, dest=RESULTATS, mode_couleurs='auto', norme=FRANCE, dpi=DPI):
    src = Path(src)
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    nom = src.stem
    img, _ = lire(src)                     # lecture commune au hub (orientation EXIF appliquée)
    visage, masque = analyser(img)
    corrigee, rapport_couleurs = couleurs.corriger(img, masque, mode_couleurs, visage.pupilles)
    detouree = fond.remplacer(corrigee, masque, norme.fond)
    tete = cadrage.mesurer(visage, masque)
    m, infos = cadrage.placer(tete, norme, dpi)
    photo, couverture = cadrage.rendre(detouree, m, (norme.largeur, norme.hauteur), norme.fond, dpi)
    mp, part_portrait = cadrage.placer_portrait_couvert(tete, detouree.shape, PORTRAIT, dpi)
    infos['portrait_part_tete'] = round(part_portrait, 2)
    portrait, _ = cadrage.rendre(detouree, mp, PORTRAIT, norme.fond, dpi)

    taille = (norme.largeur, norme.hauteur)
    p8 = planche.composer(planche.disposition_8(taille), [photo] * 8, dpi=dpi)
    cadres, cadre_portrait = planche.disposition_4_portrait(taille)
    p4 = planche.composer(cadres + [cadre_portrait], [photo] * 4 + [portrait], dpi=dpi)

    fichiers = {
        'identite': dest / ('%s_identite.jpg' % nom),
        'planche_8': dest / ('%s_planche_8.jpg' % nom),
        'planche_4_portrait': dest / ('%s_planche_4_portrait.jpg' % nom),
    }
    enregistrer(photo, fichiers['identite'], dpi)
    enregistrer(p8, fichiers['planche_8'], dpi)
    enregistrer(p4, fichiers['planche_4_portrait'], dpi)
    rapport = {
        'photo': src.name,
        'avertissements': controler(visage, tete, masque, infos, couverture, norme, dpi),
        'cadrage': infos,
        'couleurs': rapport_couleurs,
        'lacet': visage.lacet,
        'fichiers': {k: v.name for k, v in fichiers.items()},
    }
    (dest / ('%s_rapport.json' % nom)).write_text(json.dumps(rapport, ensure_ascii=False, indent=2))
    return rapport


def main(argv=None):
    ap = argparse.ArgumentParser(description="Photos d'identité (normes françaises) et planches 10 × 15 cm")
    ap.add_argument('photos', nargs='*', help='photos (par défaut : toutes celles de donnees/original/)')
    ap.add_argument('--couleurs', choices=couleurs.MODES, default='auto',
                    help='balance des blancs : auto (dominante nette du fond ou de la peau), fond, peau, aucune')
    ap.add_argument('--fond', default=None, help='couleur du fond r,v,b (gris clair par défaut)')
    ap.add_argument('--sortie', default=str(RESULTATS), help='dossier des résultats')
    a = ap.parse_args(argv)
    norme = FRANCE
    if a.fond:
        parts = [int(x) for x in a.fond.split(',') if x.strip().isdigit()]
        if len(parts) != 3 or len(a.fond.split(',')) != 3 or not all(0 <= x <= 255 for x in parts):
            ap.error('--fond : trois valeurs de 0 à 255, par exemple 214,214,214')
        norme = Norme(fond=tuple(parts))
    photos = [Path(p) for p in a.photos] or sorted(
        p for p in ORIGINAL.iterdir() if p.suffix.lower() in FORMATS and not p.name.startswith('.'))
    erreurs = 0
    for p in photos:
        try:
            r = fabriquer(p, a.sortie, a.couleurs, norme)
        except (VisageError, ConversionImpossible, couleurs.NatifError) as e:
            print('%s : ÉCHEC, %s' % (p.name, e))
            erreurs += 1
            continue
        c = r['cadrage']
        print('%s : tête %s mm (crâne à %s mm du haut, menton à %s mm), redressée de %s°, couleurs : %s'
              % (p.name, c['tete_mm'], c['crane_mm'], c['menton_mm'], c['redressement'],
                 r['couleurs']['methode']))
        for avis in r['avertissements']:
            print('  ! %s' % avis)
    return 1 if erreurs else 0


if __name__ == '__main__':
    sys.exit(main())

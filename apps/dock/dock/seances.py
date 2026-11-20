"""Dossiers de séance et résultats de l'aide au tri.

Chaque dossier de séance garde ses résultats dans un fichier caché `.rexo-tri.json`, qui suit
le dossier (déplacé, renommé ou recopié sur le disque de seconde copie, il reste valable) :

    {"version": 1, "photos": {"IMG_0001.HEIC": {"date": 1763570000.0, "rafale": "…",
        "taille": 123, "mtime": …, "nettete": …, "empreinte": "…", "visages": 1,
        "ouvertures": [0.31], "yeux_fermes": false, "erreur": null}}}

Les vignettes de la vue « Séances » sont rangées à part, dans les données de l'application
(jamais dans le dossier du photographe). Rien n'est déplacé ni supprimé dans une séance.
"""

import hashlib
import json
import os
import threading
from pathlib import Path

import cv2

from . import coeur, tri

FICHIER = '.rexo-tri.json'
VERSION = 1
PHOTOS = {'.jpg', '.jpeg', '.heic', '.heif', '.png', '.dng', '.tif', '.tiff', '.webp', '.avif'}
COTE_VIGNETTE = 360
_verrou = threading.Lock()


def est_photo(p):
    return p.suffix.lower() in PHOTOS and not p.name.startswith('.') and p.is_file()


def lister(racine):
    """Dossiers de séance sous `racine`, les plus récents d'abord (nom AAAA-MM-JJ…)."""
    racine = Path(racine)
    if not racine.is_dir():
        return []
    dossiers = [d for d in racine.iterdir() if d.is_dir() and not d.name.startswith('.')]
    return sorted(dossiers, key=lambda d: d.name, reverse=True)


def lire(dossier):
    try:
        d = json.loads((Path(dossier) / FICHIER).read_text(encoding='utf-8'))
        if d.get('version') == VERSION and isinstance(d.get('photos'), dict):
            return d
    except (OSError, ValueError):
        pass
    return {'version': VERSION, 'photos': {}}


def ecrire(dossier, donnees):
    chemin = Path(dossier) / FICHIER
    provisoire = chemin.with_name(FICHIER + '.partiel')
    provisoire.write_text(json.dumps(donnees, ensure_ascii=False, indent=1), encoding='utf-8')
    os.replace(provisoire, chemin)


def noter_import(copies):
    """Après un import : date de prise de vue et rafale de l'iPhone pour chaque fichier copié
    (`copies` : (FichierAppareil, Path)), que le fichier seul ne dit pas toujours."""
    par_dossier = {}
    for f, chemin in copies:
        par_dossier.setdefault(Path(chemin).parent, []).append((f, Path(chemin)))
    with _verrou:
        for dossier, liste in par_dossier.items():
            d = lire(dossier)
            for f, chemin in liste:
                if coeur.genre(chemin.name) not in (coeur.PHOTO, coeur.RAW):
                    continue
                p = d['photos'].setdefault(chemin.name, {})
                p.update(date=f.date.timestamp() if f.date else None, rafale=f.rafale)
            ecrire(dossier, d)
    return list(par_dossier)


def a_analyser(dossier):
    """Photos du dossier sans analyse à jour (nouvelles ou modifiées depuis)."""
    d = lire(dossier)
    restent = []
    for p in sorted(Path(dossier).iterdir()):
        if not est_photo(p):
            continue
        st = p.stat()
        info = d['photos'].get(p.name, {})
        if 'nettete' not in info or info.get('taille') != st.st_size or info.get('mtime') != st.st_mtime:
            restent.append(p)
    return restent


def analyser_dossier(dossier, vignettes, progression=None, arreter=None):
    """Analyse les photos du dossier qui ne le sont pas encore ; enregistre après chaque photo
    (une coupure ne fait perdre que la photo en cours). Renvoie le nombre de photos analysées."""
    restent = a_analyser(dossier)
    for i, p in enumerate(restent):
        if arreter is not None and arreter():
            break
        if progression:
            progression(i, len(restent), p.name)
        a = tri.analyser(p)
        st = p.stat()
        with _verrou:
            d = lire(dossier)
            info = d['photos'].setdefault(p.name, {})
            if info.get('date') is None:
                info['date'] = st.st_mtime          # date de prise de vue remise par l'import
            info.update(taille=st.st_size, mtime=st.st_mtime, nettete=a.nettete, empreinte=a.empreinte,
                        visages=a.visages, ouvertures=a.ouvertures, yeux_fermes=a.yeux_fermes, erreur=a.erreur)
            ecrire(dossier, d)
        try:
            vignette(p, vignettes)
        except Exception:
            pass
    return len(restent)


def photos(dossier):
    """Photos du dossier avec leurs indications de tri (classer), dans l'ordre de prise de vue."""
    d = lire(dossier)
    liste = []
    for p in Path(dossier).iterdir():
        if not est_photo(p):
            continue
        info = dict(d['photos'].get(p.name, {}))
        st = p.stat()
        info['nom'] = p.name
        info['analysee'] = 'nettete' in info and info.get('taille') == st.st_size and info.get('mtime') == st.st_mtime
        info.setdefault('date', st.st_mtime)
        liste.append(info)
    analysees = [x for x in liste if x['analysee']]
    tri.classer(analysees)
    for x in liste:
        if not x['analysee']:
            x.update(floue=False, doublon=False, meilleure=False, serie=None, a_trier=False)
    liste.sort(key=lambda x: (x.get('date') or 0, x['nom']))
    return liste


def chemin_vignette(photo, vignettes):
    st = photo.stat()
    cle = hashlib.sha1(('%s|%d|%s' % (photo.resolve(), st.st_size, st.st_mtime)).encode()).hexdigest()
    return Path(vignettes) / cle[:2] / (cle + '.jpg')


def vignette(photo, vignettes):
    """Vignette JPEG d'une photo de séance (créée au besoin), chemin renvoyé."""
    photo = Path(photo)
    v = chemin_vignette(photo, vignettes)
    if not v.is_file():
        from shared.images import reduire
        img = reduire(photo, COTE_VIGNETTE)
        v.parent.mkdir(parents=True, exist_ok=True)
        provisoire = v.with_name(v.name + '.partiel.jpg')
        cv2.imwrite(str(provisoire), img, [cv2.IMWRITE_JPEG_QUALITY, 85])
        os.replace(provisoire, v)
    return v

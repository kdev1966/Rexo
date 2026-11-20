"""Dossiers de séance et résultats de l'aide au tri.

Chaque dossier de séance garde ses résultats dans un fichier caché `.rexo-tri.json`, qui suit
le dossier (déplacé, renommé ou recopié sur le disque de seconde copie, il reste valable) :

    {"version": 1, "photos": {"IMG_0001.HEIC": {"date": 1763570000.0, "rafale": "…",
        "taille": 123, "mtime": …, "nettete": …, "empreinte": "…", "visages": 1,
        "ouvertures": [0.31], "yeux_fermes": false, "erreur": null}}}

Les vignettes de la vue « Séances » sont rangées à part, dans les données de l'application
(jamais dans le dossier du photographe). L'analyse ne déplace ni ne supprime rien ; seules les
actions du photographe le font :

    garder(dossier, noms)      la photo est bonne malgré le signalement : elle sort de « à trier »
    ecarter(dossier, noms)     déplacée dans le sous-dossier « Écartées » de la séance (avec son
                               fichier de retouche .AAE) ; remettre() la ramène
    corbeille(dossier, noms)   dans la Corbeille du système (récupérable tant qu'elle n'est pas vidée)
"""

import json
import os
import threading
from pathlib import Path


from shared.images import vignette  # vignettes en cache, communes au hub

from . import coeur, tri

FICHIER = '.rexo-tri.json'
ECARTEES = 'Écartées'
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
            d.setdefault('ecartees', {})
            return d
    except (OSError, ValueError):
        pass
    return {'version': VERSION, 'photos': {}, 'ecartees': {}}


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
            vignette(p, vignettes, COTE_VIGNETTE)          # prête pour la vue Séances
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
        x['garde'] = bool(x.get('garde'))
        if x['garde']:
            x['a_trier'] = False                # jugée bonne par le photographe
    liste.sort(key=lambda x: (x.get('date') or 0, x['nom']))
    return liste


# ---------- actions du photographe ----------

class ActionImpossible(RuntimeError):
    pass


def _photo(dossier, nom, sous=None):
    base = (Path(dossier) / sous) if sous else Path(dossier)
    p = (base / str(nom)).resolve()
    if p.parent != base.resolve() or not p.is_file():
        raise ActionImpossible('Photo introuvable : %s' % nom)
    return p


def _retouches(photo):
    """Fichiers de retouche (.AAE) de l'iPhone posés à côté de la photo."""
    noms = {n.upper() for n in coeur.noms_retouche(photo.name)}
    return [f for f in photo.parent.iterdir() if f.is_file() and f.name.upper() in noms]


def garder(dossier, noms, valeur=True):
    with _verrou:
        d = lire(dossier)
        for nom in noms:
            _photo(dossier, nom)
            d['photos'].setdefault(nom, {})['garde'] = bool(valeur)
        ecrire(dossier, d)
    return len(noms)


def ecarter(dossier, noms):
    """Déplace les photos (et leurs .AAE) dans « Écartées » ; leur analyse les suit."""
    dossier = Path(dossier)
    cible = dossier / ECARTEES
    with _verrou:
        d = lire(dossier)
        try:
            for nom in noms:
                p = _photo(dossier, nom)
                cible.mkdir(exist_ok=True)
                nouveau = coeur.nom_libre(p.name, cible)
                for r in _retouches(p):
                    os.replace(r, cible / coeur.nom_libre(r.name, cible))
                os.replace(p, cible / nouveau)
                info = d['photos'].pop(p.name, {})
                info['origine'] = p.name
                d['ecartees'][nouveau] = info
        finally:
            ecrire(dossier, d)
    return len(noms)


def remettre(dossier, noms):
    dossier = Path(dossier)
    with _verrou:
        d = lire(dossier)
        try:
            for nom in noms:
                p = _photo(dossier, nom, ECARTEES)
                info = d['ecartees'].pop(p.name, {})
                nouveau = coeur.nom_libre(info.pop('origine', p.name), dossier)
                for r in _retouches(p):
                    os.replace(r, dossier / coeur.nom_libre(r.name, dossier))
                os.replace(p, dossier / nouveau)
                d['photos'][nouveau] = info
        finally:
            ecrire(dossier, d)
    return len(noms)


def corbeille(dossier, noms, ecartees=False, dossier_corbeille=None):
    """Met les photos (et leurs .AAE) dans la Corbeille du système. `dossier_corbeille` : tests."""
    from shared import systeme
    sous = ECARTEES if ecartees else None
    with _verrou:
        d = lire(dossier)
        try:
            for nom in noms:
                p = _photo(dossier, nom, sous)
                for r in _retouches(p):
                    systeme.corbeille(r, dossier_mac=dossier_corbeille)
                systeme.corbeille(p, dossier_mac=dossier_corbeille)
                (d['ecartees'] if ecartees else d['photos']).pop(p.name, None)
        finally:
            ecrire(dossier, d)
    return len(noms)


def ecartees(dossier):
    """Photos écartées de la séance, avec leur nom d'origine."""
    d = lire(dossier)
    base = Path(dossier) / ECARTEES
    if not base.is_dir():
        return []
    sortie = []
    for p in sorted(base.iterdir()):
        if est_photo(p):
            info = d['ecartees'].get(p.name, {})
            sortie.append({'nom': p.name, 'origine': info.get('origine', p.name), 'date': info.get('date')})
    return sortie

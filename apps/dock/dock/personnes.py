"""Regroupement des photos d'une séance par personne (reconnaissance faciale).

Données biométriques : décision du photographe, cadre légal vérifié (ADR 0005). Garde-fous :
- rien n'est calculé tant que le photographe ne l'a pas demandé pour cette séance ;
- les empreintes restent dans la séance, dans le fichier caché `.rexo-visages.json` : aucune
  base commune aux séances, aucune comparaison d'une séance à l'autre, aucun nom de personne ;
- la seconde copie ne recopie pas les fichiers cachés : les empreintes ne quittent pas la
  machine ; effacer() les supprime, et elles disparaissent avec le dossier de la séance.

Méthode : visages par YuNet (assez grands seulement), empreinte d'identité par SFace
(shared/vision), regroupement hiérarchique à liaison moyenne : deux groupes sont réunis tant
que la ressemblance moyenne de leurs visages dépasse MEME_PERSONNE (seuil d'OpenCV pour SFace).
Une personne présente sur une seule photo ne forme pas de groupe.
"""

import base64
import json
import os
import threading
from pathlib import Path

import numpy as np

from shared.images import reduire

from . import seances

FICHIER = '.rexo-visages.json'
VERSION = 1
MODELE = 'sface-2021dec'
COTE = 1600
VISAGE_MIN = 48               # pixels de large sur l'image réduite : en dessous, empreinte peu fiable
PHOTOS_MIN = 2                # une personne vue sur une seule photo ne forme pas de groupe
_verrou = threading.Lock()


def _chemin(dossier):
    return Path(dossier) / FICHIER


def actif(dossier):
    """Le photographe a-t-il demandé le regroupement pour cette séance ?"""
    return _chemin(dossier).is_file()


def lire(dossier):
    try:
        d = json.loads(_chemin(dossier).read_text(encoding='utf-8'))
        if d.get('version') == VERSION and d.get('modele') == MODELE:
            return d
    except (OSError, ValueError):
        pass
    return {'version': VERSION, 'modele': MODELE, 'photos': {}}


def _ecrire(dossier, d):
    chemin = _chemin(dossier)
    provisoire = chemin.with_name(FICHIER + '.partiel')
    provisoire.write_text(json.dumps(d), encoding='utf-8')
    os.replace(provisoire, chemin)


def activer(dossier):
    """Demande du photographe : le fichier vide marque la séance comme à regrouper."""
    with _verrou:
        if not actif(dossier):
            _ecrire(dossier, lire(dossier))


def effacer(dossier):
    """Supprime les empreintes de la séance (effacement réel : ce sont des données biométriques,
    pas des photos ; elles se recalculent si le photographe le redemande)."""
    with _verrou:
        _chemin(dossier).unlink(missing_ok=True)
        _chemin(dossier).with_name(FICHIER + '.partiel').unlink(missing_ok=True)


def _code(e):
    return base64.b64encode(np.asarray(e, np.float16).tobytes()).decode('ascii')


def _decode(s):
    return np.frombuffer(base64.b64decode(s), np.float16).astype(np.float32)


def purger(dossier):
    """Retire les empreintes des photos qui ne sont plus dans la séance (écartées, mises à la
    Corbeille, renommées) : pas d'empreinte biométrique sans sa photo."""
    if not actif(dossier):
        return 0
    presentes = {p.name for p in Path(dossier).iterdir() if seances.est_photo(p)}
    with _verrou:
        d = lire(dossier)
        orphelines = [n for n in d['photos'] if n not in presentes]
        for n in orphelines:
            del d['photos'][n]
        if orphelines:
            _ecrire(dossier, d)
    return len(orphelines)


def a_calculer(dossier):
    if not actif(dossier):
        return []
    d = lire(dossier)
    restent = []
    for p in sorted(Path(dossier).iterdir()):
        if not seances.est_photo(p):
            continue
        st = p.stat()
        info = d['photos'].get(p.name)
        if not info or info.get('taille') != st.st_size or info.get('mtime') != st.st_mtime:
            restent.append(p)
    return restent


def visages_photo(chemin):
    """[(cadre, empreinte)] des visages assez grands d'une photo."""
    from shared import vision
    img = reduire(chemin, COTE)
    sortie = []
    for v in vision.visages(img):
        if v['cadre'][2] < VISAGE_MIN:
            continue
        sortie.append(([round(float(x), 1) for x in v['cadre']], vision.empreinte_visage(img, v)))
    return sortie


def calculer(dossier, progression=None):
    """Empreintes des photos de la séance qui n'en ont pas encore ; enregistre après chaque
    photo. Ne fait rien si le photographe ne l'a pas demandé. Renvoie le nombre de photos."""
    purger(dossier)
    restent = a_calculer(dossier)
    for i, p in enumerate(restent):
        if progression:
            progression(i, len(restent), p.name)
        try:
            trouves = visages_photo(p)
            erreur = None
        except Exception as e:
            trouves, erreur = [], str(e) or e.__class__.__name__
        st = p.stat()
        with _verrou:
            if not actif(dossier):          # effacé entre-temps : on s'arrête
                return i
            d = lire(dossier)
            d['photos'][p.name] = {'taille': st.st_size, 'mtime': st.st_mtime, 'erreur': erreur,
                                   'visages': [{'cadre': c, 'e': _code(e)} for c, e in trouves]}
            _ecrire(dossier, d)
    return len(restent)


def regrouper(empreintes, seuil=None):
    """Liaison moyenne sur la ressemblance (cosinus). `empreintes` : matrice (n, 128), normes 1.
    Renvoie une liste de groupes d'indices, les plus grands d'abord."""
    from shared.vision import MEME_PERSONNE
    seuil = MEME_PERSONNE if seuil is None else seuil
    n = len(empreintes)
    if n == 0:
        return []
    groupes = [[i] for i in range(n)]
    sim = np.asarray(empreintes, np.float64) @ np.asarray(empreintes, np.float64).T
    # ressemblance moyenne entre groupes, mise à jour à chaque fusion (Lance-Williams)
    moy = sim.copy()
    np.fill_diagonal(moy, -np.inf)
    vivants = list(range(n))
    while len(vivants) > 1:
        sous = moy[np.ix_(vivants, vivants)]
        k = int(np.argmax(sous))
        a, b = vivants[k // len(vivants)], vivants[k % len(vivants)]
        if moy[a, b] < seuil:
            break
        na, nb = len(groupes[a]), len(groupes[b])
        moy[a, :] = (na * moy[a, :] + nb * moy[b, :]) / (na + nb)
        moy[:, a] = moy[a, :]
        moy[a, a] = -np.inf
        groupes[a] += groupes[b]
        groupes[b] = []
        vivants.remove(b)
    return sorted((g for g in groupes if g), key=len, reverse=True)


def personnes(dossier):
    """Personnes de la séance : [{numero, photos: [noms], visage: {nom, cadre}}], la plus
    présente d'abord. `visage` : le visage le plus représentatif, pour la vignette."""
    d = lire(dossier)
    presentes = {p.name for p in Path(dossier).iterdir() if seances.est_photo(p)}
    noms, cadres, emb = [], [], []
    for nom, info in d['photos'].items():
        if nom not in presentes:
            continue                     # photo écartée ou mise à la Corbeille depuis
        for v in info.get('visages', []):
            noms.append(nom)
            cadres.append(v['cadre'])
            emb.append(_decode(v['e']))
    if not emb:
        return []
    emb = np.stack(emb)
    emb /= np.maximum(np.linalg.norm(emb, axis=1, keepdims=True), 1e-9)
    sortie = []
    for g in regrouper(emb):
        photos = sorted({noms[i] for i in g})
        if len(photos) < PHOTOS_MIN:
            continue
        centre = emb[g].mean(axis=0)
        rep = max(g, key=lambda i: float(emb[i] @ centre) + 0.001 * cadres[i][2])
        sortie.append({'photos': photos, 'visage': {'nom': noms[rep], 'cadre': cadres[rep]}})
    sortie.sort(key=lambda x: len(x['photos']), reverse=True)
    for i, x in enumerate(sortie, 1):
        x['numero'] = i
    return sortie


def visage_vignette(dossier, nom, cadre, cote=160):
    """Vignette carrée du visage (JPEG en mémoire), pour la liste des personnes."""
    import cv2
    img = reduire(Path(dossier) / nom, COTE)
    x, y, l, h = cadre
    c = max(l, h) * 1.4
    cx, cy = x + l / 2, y + h / 2
    x0, y0 = int(max(0, cx - c / 2)), int(max(0, cy - c / 2))
    x1, y1 = int(min(img.shape[1], cx + c / 2)), int(min(img.shape[0], cy + c / 2))
    rec = cv2.resize(img[y0:y1, x0:x1], (cote, cote), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode('.jpg', rec, [cv2.IMWRITE_JPEG_QUALITY, 85])
    return buf.tobytes()

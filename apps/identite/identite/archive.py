"""Archive des photos d'identité des clients, et suppression vers la Corbeille.

Rangement :  <archive>/<NOM Prénom - téléphone>/<AAAA-MM-JJ Prénom Nom>/
                 identite.jpg, planche_8.jpg, planche_4_portrait.jpg, original.<ext>, rapport.json
Une seule base pour tous les clients : donnees/clients.sqlite (base.py). Le dossier de
l'archive choisi est retenu dans donnees/reglages.json (par défaut : ~/Pictures/Identité,
« Images » dans le Finder) ; en changer ne change pas de base.

Rien n'est effacé définitivement : les fichiers supprimés vont dans la Corbeille de
l'utilisateur, d'où on peut les récupérer.
"""

import json
import re
import shutil
import time
from pathlib import Path

from .base import Base, BaseError, LIENS
from .config import DONNEES, ORIGINAL, RESULTATS

REGLAGES = DONNEES / 'reglages.json'
BASE = DONNEES / 'clients.sqlite'
ARCHIVE_DEFAUT = Path.home() / 'Pictures' / 'Identité'
CORBEILLE = Path.home() / '.Trash'
FICHIERS = ('identite', 'planche_8', 'planche_4_portrait')


class ArchiveError(RuntimeError):
    pass


# ---------- réglages ----------

def lire_reglages():
    try:
        return json.loads(REGLAGES.read_text())
    except (OSError, ValueError):
        return {}


def dossier_archive():
    return Path(lire_reglages().get('archive') or ARCHIVE_DEFAUT).expanduser()


def choisir_archive(chemin):
    """Retient `chemin` comme dossier de l'archive (créé au besoin) pour les prochaines photos."""
    p = Path(chemin).expanduser()
    if not p.is_absolute():
        raise ArchiveError('chemin absolu attendu')
    p.mkdir(parents=True, exist_ok=True)
    r = lire_reglages()
    r['archive'] = str(p)
    DONNEES.mkdir(parents=True, exist_ok=True)
    REGLAGES.write_text(json.dumps(r, ensure_ascii=False, indent=2))
    return p


def base():
    return Base(BASE)


# ---------- noms de dossiers ----------

def _nom_dossier(texte):
    t = re.sub(r'[/:\\\x00-\x1f]', '-', ' '.join(texte.split())).strip(' .')
    return t[:90] or 'sans nom'


def _unique(chemin):
    if not chemin.exists():
        return chemin
    n = 2
    while (chemin.parent / ('%s (%d)' % (chemin.name, n))).exists():
        n += 1
    return chemin.parent / ('%s (%d)' % (chemin.name, n))


def dossier_client(fiche):
    nom = ' '.join(x for x in (fiche['nom'].upper(), fiche['prenom']) if x)
    if fiche['telephone']:
        nom += ' - ' + fiche['telephone']
    return dossier_archive() / _nom_dossier(nom)


# ---------- enregistrement ----------

def enregistrer(photo, client_id, nom, prenom, lien='lui-même'):
    """Copie la photo d'identité de `photo` (nom dans original/), ses planches, son rapport
    et l'original dans l'archive du client ; ajoute la photo à la base. Renvoie son id."""
    if lien not in LIENS:
        raise BaseError('lien inconnu : %s' % lien)
    src = ORIGINAL / photo
    rapport_f = RESULTATS / ('%s_rapport.json' % Path(photo).stem)
    try:
        rapport = json.loads(rapport_f.read_text())
    except (OSError, ValueError):
        raise ArchiveError('photos pas encore fabriquées pour %s' % photo)
    if rapport.get('photo') != photo or not src.is_file():
        raise ArchiveError('photos pas encore fabriquées pour %s' % photo)
    fichiers = {k: RESULTATS / rapport['fichiers'][k] for k in FICHIERS}
    if not all(f.is_file() for f in fichiers.values()):
        raise ArchiveError('fichiers manquants : refaire « Fabriquer les photos »')
    b = base()
    fiche = b.client(client_id)
    if fiche is None:
        raise BaseError('client inconnu')
    personne = ' '.join(x for x in (prenom, nom) if x) or 'photo'
    dossier = _unique(dossier_client(fiche) / _nom_dossier('%s %s' % (time.strftime('%Y-%m-%d'), personne)))
    dossier.mkdir(parents=True)
    try:
        for k, f in fichiers.items():
            shutil.copy2(f, dossier / ('%s.jpg' % k))
        shutil.copy2(src, dossier / ('original%s' % src.suffix.lower()))
        shutil.copy2(rapport_f, dossier / 'rapport.json')
        return b.ajouter_photo(client_id, nom, prenom, lien, dossier)
    except Exception:
        shutil.rmtree(dossier, ignore_errors=True)       # pas de dossier orphelin
        raise


def fichier_archive(photo_fiche, nature):
    """Chemin d'un fichier d'une photo archivée ; nature : identite, planche_8, planche_4_portrait."""
    if nature not in FICHIERS:
        raise ArchiveError('fichier inconnu')
    return Path(photo_fiche['dossier']) / ('%s.jpg' % nature)


# ---------- suppression (Corbeille) ----------

def corbeille(chemin):
    """Déplace un fichier ou un dossier dans la Corbeille (nom rendu unique au besoin)."""
    p = Path(chemin)
    if not p.exists():
        return None
    CORBEILLE.mkdir(exist_ok=True)
    cible = CORBEILLE / p.name
    if cible.exists():
        cible = CORBEILLE / ('%s %s%s' % (p.stem, time.strftime('%H-%M-%S'), p.suffix))
    n = 2
    while cible.exists():
        cible = CORBEILLE / ('%s %d%s' % (p.stem, n, p.suffix))
        n += 1
    shutil.move(str(p), str(cible))
    return cible


def retirer_du_travail(photo, apercus=None):
    """Met à la Corbeille un portrait de la liste de travail, ses planches et son rapport."""
    src = ORIGINAL / photo
    if src.parent.resolve() != ORIGINAL.resolve() or not src.is_file():
        raise ArchiveError('photo inconnue')
    stem = src.stem
    retires = [corbeille(src)]
    rapport_f = RESULTATS / ('%s_rapport.json' % stem)
    try:
        rapport = json.loads(rapport_f.read_text())
    except (OSError, ValueError):
        rapport = None
    if rapport and rapport.get('photo') == photo:          # pas les résultats d'une homonyme
        for k in FICHIERS:
            retires.append(corbeille(RESULTATS / rapport['fichiers'].get(k, '')) if rapport['fichiers'].get(k)
                           else None)
        retires.append(corbeille(rapport_f))
    if apercus is not None:
        a = Path(apercus) / (photo + '.jpg')
        if a.exists():
            a.unlink()                                      # simple cache, recalculable
    return [str(r) for r in retires if r]


def supprimer_photo_archive(photo_id):
    dossier = base().supprimer_photo(photo_id)
    corbeille(dossier)
    _retirer_si_vide(Path(dossier).parent)


def supprimer_client_archive(client_id):
    b = base()
    if b.client(client_id) is None:
        raise BaseError('client inconnu')
    dossiers = b.supprimer_client(client_id)
    for d in dossiers:
        corbeille(d)
    for parent in {Path(d).parent for d in dossiers}:
        _retirer_si_vide(parent)


def _retirer_si_vide(dossier):
    """Retire un dossier de client resté vide (jamais l'archive elle-même)."""
    try:
        d = Path(dossier)
        if d.resolve() in (dossier_archive().resolve(), Path.home().resolve()):
            return
        if d.is_dir() and not any(p for p in d.iterdir() if p.name != '.DS_Store'):
            shutil.rmtree(d)
    except OSError:
        pass

"""Cœur de Rexo Dock, sans dépendance au système ni à l'interface.

Repris de `Core.swift` (prototype Import Studio) :

    FichierAppareil           fichier vu sur l'appareil (nom, taille, date de prise de vue) et sa clé
    Registre                  fichiers déjà importés et vérifiés, par appareil (JSON, même format
                              que le registre d'Import Studio)
    nom_dossier_seance()      « AAAA-MM-JJ » ou « AAAA-MM-JJ Nom de la séance »
    nom_libre()               IMG_1.HEIC, sinon IMG_1_2.HEIC, IMG_1_3.HEIC… (jamais d'écrasement)
    genre(), noms_retouche()  photo, RAW, vidéo ou fichier de retouche (.AAE) de l'iPhone
    sha256(), appliquer_date(), espace_libre()
    miroir()                  seconde copie vérifiée d'un dossier sur un disque externe

Rien n'est jamais supprimé, ni sur l'appareil ni dans les copies.
"""

import hashlib
import json
import os
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

BLOC = 4 * 1024 * 1024        # lecture par blocs de 4 Mo : les vidéos font plusieurs Go

PHOTO, RAW, VIDEO, RETOUCHE = 'photo', 'raw', 'video', 'retouche'
_VIDEOS = {'.mov', '.mp4', '.m4v', '.avi', '.3gp'}
_RAWS = {'.dng', '.raw', '.cr2', '.cr3', '.nef', '.arw'}

# Caractères interdits dans un nom de dossier (macOS, Windows, disque exFAT)
_INTERDITS = set('/:\\?%*|"<>')


@dataclass(frozen=True)
class FichierAppareil:
    nom: str
    taille: int
    date: datetime | None = None      # date de prise de vue (avec fuseau, ou heure locale)

    @property
    def cle(self):
        """Clé stable : nom + taille + date (secondes depuis 1970). Reconnaît un fichier déjà
        importé même si le dossier de destination a changé. Même forme que dans Import Studio."""
        stamp = str(int(self.date.timestamp())) if self.date else '-'
        return '%s|%d|%s' % (self.nom, self.taille, stamp)


class Registre:
    """Fichiers déjà importés et vérifiés, par appareil. Écrit sur disque à chaque ajout,
    pour qu'un import coupé reprenne là où il s'est arrêté."""

    def __init__(self, chemin):
        self.chemin = Path(chemin)
        self.entrees = {}
        try:
            donnees = json.loads(self.chemin.read_text(encoding='utf-8'))
            self.entrees = {appareil: set(cles) for appareil, cles in donnees.items()}
        except (OSError, ValueError, AttributeError):
            pass                       # registre absent ou illisible : tout est nouveau

    def contient(self, fichier, appareil):
        return fichier.cle in self.entrees.get(appareil, ())

    def nouveaux(self, fichiers, appareil):
        return [f for f in fichiers if not self.contient(f, appareil)]

    def enregistrer(self, fichier, appareil):
        self.entrees.setdefault(appareil, set()).add(fichier.cle)
        self.sauver()

    def enregistrer_tous(self, fichiers, appareil):
        """Marque des fichiers comme déjà importés (copiés auparavant par un autre moyen)."""
        self.entrees.setdefault(appareil, set()).update(f.cle for f in fichiers)
        self.sauver()

    def sauver(self):
        self.chemin.parent.mkdir(parents=True, exist_ok=True)
        texte = json.dumps({a: sorted(c) for a, c in self.entrees.items()}, ensure_ascii=False)
        provisoire = self.chemin.with_name(self.chemin.name + '.partiel')
        provisoire.write_text(texte, encoding='utf-8')
        os.replace(provisoire, self.chemin)          # écriture atomique


def nom_dossier_seance(date, nom=''):
    """« AAAA-MM-JJ » ou « AAAA-MM-JJ Nom de la séance », caractères interdits remplacés par « - »."""
    jour = date.strftime('%Y-%m-%d')
    propre = ''.join('-' if c in _INTERDITS else c for c in nom).strip()
    return '%s %s' % (jour, propre) if propre else jour


def nom_libre(nom, dossier):
    """`nom` s'il est libre dans `dossier`, sinon « base_2.ext », « base_3.ext »…"""
    dossier = Path(dossier)
    if not (dossier / nom).exists():
        return nom
    base, ext = os.path.splitext(nom)
    i = 2
    while (dossier / ('%s_%d%s' % (base, i, ext))).exists():
        i += 1
    return '%s_%d%s' % (base, i, ext)


def genre(nom):
    ext = os.path.splitext(nom)[1].lower()
    if ext == '.aae':
        return RETOUCHE
    if ext in _VIDEOS:
        return VIDEO
    if ext in _RAWS:
        return RAW
    return PHOTO


def noms_retouche(nom):
    """Fichiers de retouche (.AAE) liés à une photo de l'iPhone :
    IMG_1234.HEIC et IMG_E1234.HEIC (version retouchée) → IMG_1234.AAE, IMG_O1234.AAE."""
    base = os.path.splitext(nom)[0].upper()
    if base.startswith('IMG_E'):
        numero = base[5:]
    elif base.startswith('IMG_'):
        numero = base[4:]
    else:
        return ['%s.AAE' % base]
    return ['IMG_%s.AAE' % numero, 'IMG_O%s.AAE' % numero]


def sha256(chemin):
    h = hashlib.sha256()
    with open(chemin, 'rb') as f:
        while bloc := f.read(BLOC):
            h.update(bloc)
    return h.hexdigest()


def appliquer_date(chemin, date):
    """Remet la date de prise de vue comme date de modification du fichier importé."""
    if date is not None:
        t = date.timestamp()
        os.utime(chemin, (t, t))


def espace_libre(chemin):
    return shutil.disk_usage(chemin).free


@dataclass
class ResultatMiroir:
    copies: int = 0
    deja_la: int = 0
    echecs: list = None

    def __post_init__(self):
        if self.echecs is None:
            self.echecs = []


def _deja_copie(fichier, cible, taille):
    """Vrai si `cible`, ou une copie « base_N.ext » posée à côté d'elle par un passage précédent,
    a la taille de `fichier` et le même contenu."""
    base, ext = os.path.splitext(cible.name)
    candidats = [cible] + sorted(cible.parent.glob('%s_*%s' % (base, ext)))
    for c in candidats:
        try:
            if c.is_file() and c.stat().st_size == taille and (c == cible or sha256(c) == sha256(fichier)):
                return True
        except OSError:
            continue
    return False


def miroir(source, destination, progression=None):
    """Recopie `source` dans `destination` fichier par fichier, chaque copie vérifiée par son
    empreinte. Un fichier déjà présent avec la même taille est laissé ; un fichier de même nom
    mais différent n'est jamais écrasé : la copie est posée à côté (IMG_2.HEIC)."""
    source, destination = Path(source).resolve(), Path(destination)
    resultat = ResultatMiroir()
    if not source.is_dir():
        resultat.echecs.append(str(source))
        return resultat
    for racine, dossiers, fichiers in os.walk(source):
        dossiers[:] = sorted(d for d in dossiers if not d.startswith('.'))
        for nom in sorted(fichiers):
            if nom.startswith('.'):
                continue
            fichier = Path(racine) / nom
            relatif = fichier.relative_to(source).as_posix()
            cible = destination / relatif
            try:
                taille = fichier.stat().st_size
                if _deja_copie(fichier, cible, taille):
                    resultat.deja_la += 1
                    continue
                if progression:
                    progression(relatif)
                cible.parent.mkdir(parents=True, exist_ok=True)
                partiel = cible.with_name(cible.name + '.partiel')
                shutil.copyfile(fichier, partiel)
                if sha256(fichier) != sha256(partiel):
                    partiel.unlink(missing_ok=True)
                    resultat.echecs.append(relatif)
                    continue
                shutil.copystat(fichier, partiel)
                os.replace(partiel, cible.parent / nom_libre(cible.name, cible.parent))
                resultat.copies += 1
            except OSError:
                resultat.echecs.append(relatif)
    return resultat

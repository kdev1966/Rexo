"""Import d'une sélection depuis un appareil, quel que soit le système.

L'appareil (macOS : `appareil_mac`, Windows : à venir) fournit seulement :

    appareil.identifiant          identifiant stable de l'appareil (clé du registre)
    appareil.nom                  nom affiché (« iPhone de … »)
    appareil.copier(fichier, dossier, nom) -> Path
                                  copie l'original dans `dossier` sous `nom` et renvoie le chemin
                                  réellement écrit ; lève ErreurAppareil en cas d'échec

Ici : place disponible, dossier de séance, noms sans écrasement, vérification de la taille,
date d'origine, registre écrit après chaque fichier (reprise après coupure), rapport.
Rien n'est jamais supprimé de l'appareil.
"""

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from . import coeur

MARGE = 2_000_000_000          # place laissée libre sur le disque, en plus de l'import
NOM_RAPPORT = 'Rapport d\'import.txt'


class ErreurAppareil(RuntimeError):
    """Copie impossible. `debranche` : l'appareil n'est plus là, inutile d'essayer la suite."""

    def __init__(self, message, debranche=False):
        super().__init__(message)
        self.debranche = debranche


class PlaceInsuffisante(RuntimeError):
    def __init__(self, besoin, libre):
        super().__init__('Pas assez de place : il faut %s et il reste %s.' % (taille_lisible(besoin), taille_lisible(libre)))
        self.besoin, self.libre = besoin, libre


@dataclass
class ResultatImport:
    dossier: Path
    total: int = 0
    importes: int = 0
    echecs: list = field(default_factory=list)       # (nom, raison)
    rapport: Path | None = None


def taille_lisible(octets):
    for unite in ('octets', 'Ko', 'Mo', 'Go'):
        if octets < 1000 or unite == 'Go':
            return ('%d %s' if unite == 'octets' else '%.1f %s') % (octets, unite)
        octets /= 1000


def importer(appareil, entrees, racine, registre, nom_seance='', date=None, progression=None, marge=MARGE):
    """Copie les entrées choisies (et leurs fichiers de retouche) dans un dossier de séance
    sous `racine`. `progression(fait, total, nom)` est appelée avant chaque fichier."""
    fichiers = coeur.fichiers_a_copier(entrees)
    racine = Path(racine)
    racine.mkdir(parents=True, exist_ok=True)
    besoin = sum(f.taille for f in fichiers)
    libre = coeur.espace_libre(racine)
    if libre < besoin + marge:
        raise PlaceInsuffisante(besoin, libre)

    debut = date or datetime.now()
    dossier = racine / coeur.nom_dossier_seance(debut, nom_seance)
    dossier.mkdir(exist_ok=True)
    resultat = ResultatImport(dossier, total=len(fichiers))

    for i, f in enumerate(fichiers):
        if progression:
            progression(i, len(fichiers), f.nom)
        try:
            chemin = Path(appareil.copier(f, dossier, coeur.nom_libre(f.nom, dossier)))
        except ErreurAppareil as e:
            resultat.echecs.append((f.nom, str(e)))
            if e.debranche:
                resultat.echecs.extend((g.nom, 'appareil débranché') for g in fichiers[i + 1:])
                break
            continue
        taille = chemin.stat().st_size if chemin.is_file() else -1
        if taille != f.taille:
            chemin.unlink(missing_ok=True)         # copie incomplète, à nous : jamais l'original
            resultat.echecs.append((f.nom, 'taille %d au lieu de %d' % (taille, f.taille)))
            continue
        coeur.appliquer_date(chemin, f.date)
        try:
            registre.enregistrer(f, appareil.identifiant)
        except OSError as e:
            resultat.echecs.append((f.nom, 'registre non enregistré : %s' % e))
            continue
        resultat.importes += 1

    if progression:
        progression(len(fichiers), len(fichiers), '')
    resultat.rapport = ecrire_rapport(resultat, appareil.nom, debut)
    return resultat


def ecrire_rapport(resultat, nom_appareil, date):
    lignes = ['Import du %s depuis « %s »' % (date.strftime('%d/%m/%Y à %H:%M'), nom_appareil),
              '%d fichier(s) importé(s) sur %d, chacun vérifié.' % (resultat.importes, resultat.total)]
    if resultat.echecs:
        lignes += ['', 'En échec (restés sur l\'appareil, à refaire) :']
        lignes += ['  %s : %s' % e for e in resultat.echecs]
    lignes += ['', 'Rien n\'a été supprimé de l\'appareil.']
    chemin = resultat.dossier / coeur.nom_libre(NOM_RAPPORT, resultat.dossier)
    chemin.write_text('\n'.join(lignes) + '\n', encoding='utf-8')
    return chemin

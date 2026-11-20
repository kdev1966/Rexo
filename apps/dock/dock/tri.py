"""Aide au tri de Rexo Dock (ADR 0005), sur les photos déjà importées : rien n'est déplacé,
rien n'est supprimé ; chaque photo reçoit seulement des indications.

    analyser(chemin)       netteté, yeux, empreinte d'une photo (sur une copie réduite)
    classer(photos)        rafales et quasi-doublons (meilleure photo proposée), photos floues
                           par rapport à leur séance, « à trier »

Méthodes, locales et sur le processeur :
- netteté : variance du laplacien sur 4 × 4 zones de l'image réduite à 1024 pixels ; la zone la
  plus nette compte (un fond flou derrière un sujet net n'est pas un défaut). Mesuré sur les
  photos de test : nettes de 71 à 2 900 ; floutées (mise au point ratée) de 2 à 160. Une photo
  est « floue » sous FLOU_ABSOLU, ou sous FLOU_RELATIF fois la netteté médiane de sa séance
  (même téléphone, même lumière). Limite : un bougé dans une seule direction est mal repéré.
- yeux : visages par YuNet, 478 repères par Face Mesh (shared/vision), ouverture = hauteur /
  largeur de l'œil comme dans Rexo ID (sous 0,15 : fermé ou plissé). Seuls les visages assez
  grands comptent (VISAGE_MIN pixels de large sur l'image réduite) : sur un petit visage,
  l'ouverture n'est pas fiable.
- quasi-doublons : empreinte de différence (dHash, 64 bits) ; deux photos se suivent dans
  une même série si l'iPhone les a marquées comme rafale, si elles sont prises à quelques
  secondes d'écart et presque identiques, ou si elles se suivent dans la séance et sont
  identiques à l'œil (même photo reprise ou enregistrée deux fois). Mesuré : photos identiques
  à distance 0, photos différentes à 21 et plus. Meilleure photo d'une série : la plus nette parmi
  celles où personne n'a les yeux fermés.
"""

import statistics
from dataclasses import asdict, dataclass, field

import cv2
import numpy as np

from shared.images import reduire

COTE_ANALYSE = 1600            # côté long de la copie réduite (visages)
COTE_NETTETE = 1024            # côté long pour la netteté (mesure comparable d'une photo à l'autre)
ZONES = 4
FLOU_ABSOLU = 40.0
FLOU_RELATIF = 0.2
SEANCE_MIN_RELATIF = 5         # en dessous, pas de comparaison à la séance
OUVERTURE_MIN = 0.15           # comme Rexo ID (normes.OUVERTURE_YEUX_MIN)
VISAGE_MIN = 90                # pixels de large sur la copie réduite à COTE_ANALYSE
VISAGES_MAX = 6                # au-delà, seuls les plus grands sont examinés (temps)
SERIE_SECONDES, SERIE_DISTANCE = 10, 14        # prises rapprochées et assez semblables
PROCHE_SECONDES, PROCHE_DISTANCE = 120, 6      # ou presque identiques à deux minutes près
IDENTIQUE_DISTANCE = 4                         # ou identiques à l'œil, à n'importe quel écart

# Indices Face Mesh des yeux (côtés de l'image), comme shared/vision
from shared.vision import OEIL_IMAGE_DROITE, OEIL_IMAGE_GAUCHE  # noqa: E402


@dataclass
class Analyse:
    nom: str
    nettete: float | None = None
    visages: int = 0
    ouvertures: list = field(default_factory=list)      # une par visage examiné : min des deux yeux
    yeux_fermes: bool = False
    empreinte: str | None = None                        # dHash, 16 caractères hexadécimaux
    erreur: str | None = None

    def vers_dict(self):
        return asdict(self)


def nettete(img):
    h, w = img.shape[:2]
    f = COTE_NETTETE / max(h, w)
    if f < 1:
        img = cv2.resize(img, (round(w * f), round(h * f)), interpolation=cv2.INTER_AREA)
    lap = cv2.Laplacian(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), cv2.CV_64F)
    H, W = lap.shape
    return float(max(lap[i * H // ZONES:(i + 1) * H // ZONES, j * W // ZONES:(j + 1) * W // ZONES].var()
                     for i in range(ZONES) for j in range(ZONES)))


def empreinte(img):
    g = cv2.resize(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), (9, 8), interpolation=cv2.INTER_AREA)
    bits = (g[:, 1:] > g[:, :-1]).flatten()
    return '%016x' % int(''.join('1' if b else '0' for b in bits), 2)


def distance(a, b):
    return bin(int(a, 16) ^ int(b, 16)).count('1')


def _ouverture(points, indices):
    """Hauteur / largeur de l'œil, dans le repère de l'œil (redressé par ses coins)."""
    p = points[indices, :2]
    a, b = p[0], p[8]                                    # coins de l'œil (33/133, 263/362)
    angle = np.arctan2(b[1] - a[1], b[0] - a[0])
    r = np.array([[np.cos(angle), np.sin(angle)], [-np.sin(angle), np.cos(angle)]])
    q = p @ r.T
    largeur = np.ptp(q[:, 0])
    return float(np.ptp(q[:, 1]) / largeur) if largeur > 0 else None


def yeux(img):
    """(nombre de visages, ouvertures des visages assez grands)."""
    from shared import vision
    trouves = vision.visages(img)
    grands = [v for v in trouves if v['cadre'][2] >= VISAGE_MIN][:VISAGES_MAX]
    ouvertures = []
    for v in grands:
        points, presence = vision.reperes(img, v)
        if presence < 0.5:
            continue
        o = [_ouverture(points, OEIL_IMAGE_GAUCHE), _ouverture(points, OEIL_IMAGE_DROITE)]
        o = [x for x in o if x is not None]
        if o:
            ouvertures.append(round(min(o), 3))
    return len(trouves), ouvertures


def analyser(chemin, avec_yeux=True):
    a = Analyse(nom=chemin.name if hasattr(chemin, 'name') else str(chemin))
    try:
        img = reduire(chemin, COTE_ANALYSE)
        a.nettete = round(nettete(img), 1)
        a.empreinte = empreinte(img)
        if avec_yeux:
            a.visages, a.ouvertures = yeux(img)
            a.yeux_fermes = any(o < OUVERTURE_MIN for o in a.ouvertures)
    except Exception as e:                      # une photo illisible ne bloque pas les autres
        a.erreur = str(e) or e.__class__.__name__
    return a


def classer(photos):
    """`photos` : dicts {nom, date (secondes), rafale, nettete, empreinte, yeux_fermes, erreur}.
    Ajoute à chacune : serie (numéro ou None), meilleure, doublon, floue, a_trier."""
    ordre = sorted(photos, key=lambda p: (p.get('date') or 0, p['nom']))
    nettes = [p['nettete'] for p in ordre if p.get('nettete') is not None]
    mediane = statistics.median(nettes) if len(nettes) >= SEANCE_MIN_RELATIF else None
    for p in ordre:
        n = p.get('nettete')
        p['floue'] = n is not None and (n < FLOU_ABSOLU or (mediane is not None and n < FLOU_RELATIF * mediane))
        p.update(serie=None, meilleure=False, doublon=False)

    series, courante, precedente = [], [], None
    for p in ordre:
        if precedente is not None and _meme_serie(precedente, p):
            courante.append(p)
        else:
            if len(courante) > 1:
                series.append(courante)
            courante = [p]
        precedente = p
    if len(courante) > 1:
        series.append(courante)

    for i, s in enumerate(series, 1):
        candidates = [p for p in s if not p.get('erreur')]
        if not candidates:
            continue
        meilleure = max(candidates, key=lambda p: (not p.get('yeux_fermes'), p.get('nettete') or 0))
        for p in s:
            p['serie'] = i
            p['meilleure'] = p is meilleure
            p['doublon'] = p is not meilleure
    for p in ordre:
        p['a_trier'] = bool(p['floue'] or p.get('yeux_fermes') or p['doublon'])
    return photos


def _meme_serie(a, b):
    if a.get('rafale') and a.get('rafale') == b.get('rafale'):
        return True
    if not (a.get('empreinte') and b.get('empreinte')):
        return False
    ecart = abs((b.get('date') or 0) - (a.get('date') or 0))
    d = distance(a['empreinte'], b['empreinte'])
    return ((ecart <= SERIE_SECONDES and d <= SERIE_DISTANCE) or (ecart <= PROCHE_SECONDES and d <= PROCHE_DISTANCE)
            or d <= IDENTIQUE_DISTANCE)

"""Normes de la photo d'identité française et formats d'impression.

Photo : 35 × 45 mm ; visage de 32 à 36 mm du bas du menton au sommet du crâne (hors
chevelure) ; tête droite et centrée ; fond uni et clair, le blanc étant refusé (gris clair ici).
Les longueurs sont en millimètres ; les images sont produites à DPI points par pouce.
"""

from dataclasses import dataclass

DPI = 300
MM_PAR_POUCE = 25.4


def px(mm, dpi=DPI):
    """Millimètres -> pixels (arrondi)."""
    return int(round(mm * dpi / MM_PAR_POUCE))


@dataclass(frozen=True)
class Norme:
    largeur: float = 35.0
    hauteur: float = 45.0
    tete_min: float = 32.0          # menton -> sommet du crâne
    tete_max: float = 36.0
    tete: float = 34.0              # visée : milieu de la plage, la marge absorbe l'estimation du crâne
    marge_haut: float = 5.0         # bord haut -> sommet du crâne
    marge_cheveux: float = 1.0      # les cheveux restent au moins à cette distance du bord haut
    marge_bas_min: float = 4.0      # le menton reste au moins à cette distance du bord bas
    fond: tuple = (214, 214, 214)   # gris clair (RVB)


FRANCE = Norme()

# Contrôles (avertissements, la photo est produite quand même)
LACET_MAX = 10.0        # degrés : tête tournée
ROULIS_MAX = 15.0       # degrés : tête penchée (redressée jusqu'à cette valeur)
OUVERTURE_YEUX_MIN = 0.15   # hauteur / largeur de l'œil : en dessous, yeux fermés ou plissés

# Planche 10 × 15 cm, à l'italienne
PLANCHE = (150.0, 100.0)
ECART = 2.0             # mm entre deux photos (deux traits de coupe)
PORTRAIT = (66.0, 88.0) # portrait de la planche « 4 + portrait » (3:4)
TRAIT = (110, 110, 110) # couleur des traits de coupe (RVB)

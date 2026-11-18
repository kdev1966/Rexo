# Identité

Photos d'identité **aux normes françaises** et planches à imprimer sur papier 10 × 15 cm,
depuis un portrait pris en studio. **100 % locale** : Apple Vision et Core Image, sans modèle
d'IA à télécharger. Aucune photo ne quitte la machine.

## Ce que fait Identité

| Étape | Méthode |
|---|---|
| **Balance des blancs** | Ne corrige que ce qui est manifestement faux : une photo de studio déjà réglée est laissée telle quelle. Le fond d'origine sert de charte de gris. Sous un écart de 0,10, il est jugé neutre (sa teinte vient de la toile) et rien n'est corrigé. De 0,10 à 0,15, la correction monte jusqu'à être entière. De 0,15 à 0,30, elle redescend jusqu'à la moitié, car un fond franchement teinté peut être un choix du studio. Si le fond ne sert pas de référence, c'est la peau qui décide : dans l'espace YIQ, une peau bien rendue a une composante Q proche de 0 (mesuré de +0,01 à +0,04). La balance d'Apple (`CIFaceBalance`) n'intervient que si la peau sort de cette plage |
| **Exposition** | Réglages automatiques d'Apple (courbe de tons, ombres et hautes lumières), sans relief ni vivacité |
| **Fond** | Personne détourée par Apple Vision, fond remplacé par un gris clair uni (le blanc est refusé). Les bords des cheveux sont nettoyés de la couleur de l'ancien fond |
| **Cadrage** | Photo réduite par moyenne des pixels (sans crénelage), ligne des yeux remise à l'horizontale. Tête de 34 mm du bas du menton au sommet du crâne (norme : 32 à 36 mm), centrée, crâne à 5 mm du bord haut. Photo de 35 × 45 mm à 300 points par pouce |
| **Contrôles** | Avertissements, la photo est produite quand même : plusieurs visages, tête tournée ou très penchée, yeux fermés ou plissés, définition faible, cheveux ou haut de la tête coupés, photo d'origine trop serrée |
| **Planches** | 10 × 15 cm à l'italienne : « 8 photos d'identité » (4 × 2) et « 4 photos d'identité + 1 portrait » (portrait de 66 × 88 mm). Traits de coupe d'un bord à l'autre de la planche, visibles dans les marges et entre les photos |

Le menton vient du contour de la mâchoire trouvé par Vision. Le sommet du crâne, caché par
les cheveux, est estimé par les proportions de la tête (de l'œil au menton : 0,52 de la tête),
sans jamais monter au-dessus du haut du masque des personnes. Viser 34 mm laisse 2 mm de
marge de chaque côté pour cette estimation.

## Installation

Prérequis : Mac Intel, macOS 12 ou plus, outils en ligne de commande d'Apple.

```bash
shared/python/installer.sh          # Python 3.11.17 autonome (depuis la racine du hub)
shared/natif/compiler.sh            # reto-segment (Apple Vision, Core Image)
cd apps/identite
../../.outils/python/bin/python3 -m venv .venv
.venv/bin/pip install --require-hashes --only-binary :all: -r requirements.txt
```

## Application à ouvrir d'un double-clic

```bash
shared/lanceur/creer_app.sh identite --bureau     # depuis la racine du hub
```

Crée `~/Applications/Identité.app` et un raccourci sur le Bureau. Un double-clic démarre le
serveur local et ouvre la page dans le navigateur ; quitter l'application (Cmd+Q) arrête le
serveur. Le bouton **Quitter** de la page fait de même : il arrête le serveur, et l'application se
ferme d'elle-même. Journal : `~/Library/Logs/RetoHub/identite.log`. Sans `--bureau`, pas de raccourci.

## Utilisation

### Interface web

```bash
cd apps/identite
.venv/bin/python -m identite.interface        # puis ouvrir http://127.0.0.1:8766
```

Choisir ou déposer un portrait, choisir le réglage des couleurs et le gris du fond, puis
« Fabriquer les photos ». La photo d'identité s'affiche avec les repères de la norme (sommet
du crâne, zone de 32 à 36 mm où doit tomber le menton, axe du visage). On passe ensuite aux
deux planches et à l'original, avec les avertissements et les mesures. « Ouvrir dans Aperçu »
sert à imprimer. Le serveur n'écoute que sur la machine (127.0.0.1). L'adresse garde la photo
et la vue affichées (`#photo=…&vue=…`).

### Ligne de commande

```bash
cd apps/identite
.venv/bin/python -m identite.fabriquer                              # toutes les photos de donnees/original/
.venv/bin/python -m identite.fabriquer donnees/original/photo.jpg   # une photo
.venv/bin/python -m identite.fabriquer --couleurs apple photo.jpg   # balance sur la peau seulement
.venv/bin/python -m identite.fabriquer --fond 220,220,220 photo.jpg # autre gris
```

`--couleurs` : `auto` (dominante nette du fond, sinon de la peau), `fond`, `apple` (toujours la balance d'Apple) ou `aucune`. Le rapport donne la teinte de la peau avant et après.

Résultats dans `donnees/resultats/`, en JPEG à 300 points par pouce : `NOM_identite.jpg`
(35 × 45 mm), `NOM_planche_8.jpg`, `NOM_planche_4_portrait.jpg` (150 × 100 mm), et
`NOM_rapport.json` (mesures, couleurs, avertissements). Les formats acceptés sont ceux de
`shared/images` (HEIC et AVIF compris).

Imprimer les planches **à 100 %**, sans « ajuster à la page », pour garder 35 × 45 mm.

## Tests

```bash
.venv/bin/python -m unittest discover tests
```

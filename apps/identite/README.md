# Rexo ID

Photos d'identité **aux normes françaises** et planches à imprimer sur papier 10 × 15 cm,
depuis un portrait pris en studio, **sous macOS et sous Windows**. **100 % locale** : trois petits
modèles d'IA ouverts (31 Mo) tournent sur le processeur, et donnent le même résultat sur les
deux systèmes. Aucune photo ne quitte la machine.

## Ce que fait Rexo ID

| Étape | Méthode |
|---|---|
| **Balance des blancs** | Ne corrige que ce qui est manifestement faux : une photo de studio déjà réglée est laissée telle quelle. Le fond d'origine sert de charte de gris. Sous un écart de 0,10, il est jugé neutre (sa teinte vient de la toile) et rien n'est corrigé. De 0,10 à 0,15, la correction monte jusqu'à être entière. De 0,15 à 0,30, elle redescend jusqu'à la moitié, car un fond franchement teinté peut être un choix du studio. Si le fond ne sert pas de référence, c'est la peau qui décide : dans l'espace YIQ, une peau bien rendue a une composante Q proche de 0 (mesuré de +0,01 à +0,04). La balance sur la peau n'intervient que si la peau sort de cette plage : elle ramène Q au bord le plus proche de la plage des peaux justes, sans changer la luminosité ; le mode « Par la peau » l'applique toujours, mais ne touche pas une peau déjà juste |
| **Exposition** | Courbe de tons automatique et douce, réglée sur ce que faisaient les réglages automatiques d'Apple : noirs un peu plus profonds, tons moyens éclaircis de quelques niveaux, blancs rapprochés du blanc (jamais plus de 14 niveaux) |
| **Fond** | Personne détourée par MODNet, fond remplacé par un gris clair uni (le blanc est refusé). Les bords des cheveux sont nettoyés de la couleur de l'ancien fond |
| **Cadrage** | Photo réduite par moyenne des pixels (sans crénelage), ligne des yeux remise à l'horizontale. Tête de 34 mm du bas du menton au sommet du crâne (norme : 32 à 36 mm), centrée, crâne à 5 mm du bord haut. Photo de 35 × 45 mm à 300 points par pouce |
| **Contrôles** | Avertissements, la photo est produite quand même : plusieurs visages, tête tournée ou très penchée, yeux fermés ou plissés, définition faible, cheveux ou haut de la tête coupés, photo d'origine trop serrée |
| **Planches** | 10 × 15 cm à l'italienne : « 8 photos d'identité » (4 × 2) et « 4 photos d'identité + 1 portrait » (portrait de 66 × 88 mm). Traits de coupe d'un bord à l'autre de la planche, visibles dans les marges et entre les photos |

Le menton vient du contour de la mâchoire trouvé par Face Mesh. Le sommet du crâne, caché par
les cheveux, est estimé par les proportions de la tête (de l'œil au menton : 0,52 de la tête),
sans jamais monter au-dessus du haut du masque des personnes. Viser 34 mm laisse 2 mm de
marge de chaque côté pour cette estimation.

## Clients et archive

- **Client obligatoire au dépôt** : déposer un portrait ouvre d'abord la fenêtre du client.
  On choisit un client existant (recherche par nom, prénom ou téléphone) ou on en crée un
  (nom, prénom et téléphone obligatoires), et la personne photographiée : le client lui-même,
  ou un enfant, un conjoint, un parent… Sans ces données, le portrait n'est pas déposé. Un
  portrait déposé sans client (avant cette règle) ne peut pas être fabriqué tant que son
  client n'est pas renseigné (« Renseigner le client »).
- **Un client, plusieurs photos** : chaque photo d'identité appartient à un seul client ; un
  client en a autant que nécessaire (une mère et ses enfants : une fiche, toutes leurs photos).
- **Enregistrer** : sous les résultats, la carte « Archive du client » reprend le client
  saisi au dépôt (modifiable) et archive la photo d'un clic.
- **Archive** : les fichiers sont copiés dans
  `<archive>/NOM Prénom - téléphone/AAAA-MM-JJ Prénom Nom/` (photo, deux planches, original,
  rapport). Le dossier de l'archive est par défaut « Rexo ID » dans le dossier « Images »
  (`~/Pictures/Rexo ID` sur Mac, `C:\Users\<nom>\Pictures\Rexo ID` sous Windows) ; on le change dans l'onglet Clients (« Changer… »).
- **Base** : une seule base SQLite pour tous les clients, `donnees/clients.sqlite`. Elle reste
  la même si l'on change de dossier d'archive. Les noms et téléphones ne quittent pas la
  machine et n'entrent jamais dans le dépôt git (`donnees/` est ignoré).
- **Recherche** (onglet Clients) : par nom ou prénom du client ou des personnes photographiées,
  sans tenir compte des accents ni des majuscules, ou par téléphone, quelle que soit son
  écriture (`20123456`, `+216 20 123 456`, `00216…`, ou une partie : `123 456`).
- **Téléphones** au format tunisien : 8 chiffres, enregistrés sous la forme `20 123 456`
  (+216 et 00216 retirés). Un numéro étranger est accepté avec son indicatif (`+33 6…`). Depuis la fiche : réimprimer une planche, ouvrir le
  dossier, modifier le client, supprimer une photo ou le client.
- **Suppression** : le bouton corbeille de chaque vignette (ou « Retirer de la liste » au-dessus
  du portrait ouvert) met à la Corbeille le portrait, ses
  planches et son rapport ; on peut aussi les retirer automatiquement après l'enregistrement.
  Les suppressions dans l'archive vont aussi à la Corbeille. Rien n'est effacé définitivement,
  et chaque suppression demande un second clic.
- **Sauvegarde** : copier le dossier de l'archive et `donnees/clients.sqlite`.

## Langue arabe

Le bouton **العربية** de la barre du haut passe toute l'interface en arabe, de droite à
gauche ; **Français** la ramène (`?langue=ar` dans l'adresse aussi). Le choix est retenu par le navigateur. Vocabulaire tunisien :
« حريف / حرفاء » (client), « الاسم » (prénom), « اللقب » (nom). Les chiffres restent
occidentaux ; numéros de téléphone, chemins et noms de fichiers restent de gauche à droite.

Les textes sont dans `identite/web/ar.json` : chaque clé est le texte français affiché, `{}`
marquant une partie variable ; la valeur est sa traduction (`{1}`, `{2}`… pour changer
l'ordre). Un texte absent reste en français. Le moteur est commun au hub : `shared/langues.py`
(messages du serveur) et `shared/web/langues.js` (page).

## Modèles d'IA

| Rôle | Modèle | Taille | Licence |
|---|---|---|---|
| Visages | YuNet (OpenCV Zoo) | 0,2 Mo | MIT ; entraîné sur WIDER Face, base réservée à la recherche : **usage commercial à vérifier** |
| Repères du visage (478 points, iris compris) | MediaPipe Face Mesh V2, en ONNX | 4,9 Mo | Apache-2.0 |
| Détourage (cheveux compris) | MODNet | 25,9 Mo | Apache-2.0 |

Moteur commun au hub : `shared/vision`, modèles chargés par le catalogue commun `shared/ia` (manifestes dans `shared/ia/modeles/`). Les fichiers
vont dans le magasin partagé `~/.local/share/kdev-models/embedkit` (sous Windows :
`%USERPROFILE%\.local\share\kdev-models\embedkit`), ou `$KDEV_MODELS_DIR/embedkit`.

## Installation sur Mac

Prérequis : Mac Intel, macOS 12 ou plus. Depuis la racine du hub :

```bash
shared/python/installer.sh          # Python 3.11.17 autonome
.outils/python/bin/python3 -m venv apps/identite/.venv
apps/identite/.venv/bin/pip install --require-hashes --only-binary :all: -r apps/identite/requirements.txt
export EMBEDKIT_CACHE=~/.local/share/kdev-models/embedkit
apps/identite/.venv/bin/python -m shared.embedkit.cli --models-path shared/ia/modeles \
    models pull --allow-noncommercial yunet-2023mar facemesh-v2 modnet
```

## Installation sous Windows

Prérequis : Windows 10 ou 11, 64 bits. Dans PowerShell, depuis la racine du hub :

```powershell
powershell -ExecutionPolicy Bypass -File shared\python\installer.ps1     # Python 3.11.17 autonome
.outils\python\python.exe -m venv apps\identite\.venv
apps\identite\.venv\Scripts\pip install --require-hashes --only-binary :all: -r apps\identite\requirements.txt
$env:EMBEDKIT_CACHE = "$env:USERPROFILE\.local\share\kdev-models\embedkit"
apps\identite\.venv\Scripts\python -m shared.embedkit.cli --models-path shared\ia\modeles `
    models pull --allow-noncommercial yunet-2023mar facemesh-v2 modnet
powershell -ExecutionPolicy Bypass -File shared\lanceur\creer_raccourci.ps1 identite
```

La dernière ligne crée le raccourci **Rexo ID** sur le Bureau : un double-clic démarre le serveur
local (sans fenêtre noire) et ouvre la page dans le navigateur ; le bouton **Quitter** de la page
l'arrête. Journal : `%LOCALAPPDATA%\Rexo\Journaux\identite.log`. Les fichiers supprimés vont dans
la Corbeille de Windows.

## Application à ouvrir d'un double-clic (Mac)

```bash
shared/lanceur/creer_app.sh identite --bureau     # depuis la racine du hub
```

Crée `~/Applications/Rexo ID.app` et un raccourci sur le Bureau. Un double-clic démarre le
serveur local et ouvre la page dans le navigateur ; quitter l'application (Cmd+Q) arrête le
serveur. Le bouton **Quitter** de la page fait de même : il arrête le serveur, et l'application se
ferme d'elle-même. Journal : `~/Library/Logs/Rexo/identite.log`. Sans `--bureau`, pas de raccourci.

## Utilisation

### Interface web

```bash
cd apps/identite
.venv/bin/python -m identite.interface        # puis ouvrir http://127.0.0.1:8766
```

Choisir ou déposer un portrait, choisir le réglage des couleurs et le gris du fond, puis
« Fabriquer les photos ». La photo d'identité s'affiche avec les repères de la norme (sommet
du crâne, zone de 32 à 36 mm où doit tomber le menton, axe du visage). On passe ensuite aux
deux planches et à l'original, avec les avertissements et les mesures. « Imprimer » imprime
la planche ; « Ouvrir l'image » l'ouvre dans Aperçu (Mac) ou la visionneuse de Windows. Le serveur n'écoute que sur la machine (127.0.0.1). L'adresse garde la photo
et la vue affichées (`#photo=…&vue=…`).

### Ligne de commande

```bash
cd apps/identite
.venv/bin/python -m identite.fabriquer                              # toutes les photos de donnees/original/
.venv/bin/python -m identite.fabriquer donnees/original/photo.jpg   # une photo
.venv/bin/python -m identite.fabriquer --couleurs peau photo.jpg    # balance sur la peau seulement
.venv/bin/python -m identite.fabriquer --fond 220,220,220 photo.jpg # autre gris
```

`--couleurs` : `auto` (dominante nette du fond, sinon de la peau), `fond`, `peau` (toujours la balance sur la peau ; `apple` reste accepté) ou `aucune`. Le rapport donne la teinte de la peau avant et après.

Résultats dans `donnees/resultats/`, en JPEG à 300 points par pouce : `NOM_identite.jpg`
(35 × 45 mm), `NOM_planche_8.jpg`, `NOM_planche_4_portrait.jpg` (150 × 100 mm), et
`NOM_rapport.json` (mesures, couleurs, avertissements). Les formats acceptés sont ceux de
`shared/images` (HEIC et AVIF compris).

Imprimer les planches **à 100 %**, sans « ajuster à la page », pour garder 35 × 45 mm.

## Tests

```bash
.venv/bin/python -m unittest discover tests
```

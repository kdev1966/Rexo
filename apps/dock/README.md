# Rexo Dock

Import des photos et vidéos d'un iPhone pour un studio, puis **aide au tri par IA**,
**100 % local** : aucune photo ne quitte la machine, et **rien n'est jamais supprimé du
téléphone**. Fonctionne aujourd'hui **sous macOS** ; la version Windows est prévue (voir
« Windows »). Choix techniques : [ADR 0005](../../docs/adr/0005-rexo-dock.md).

| Étape | Ce que fait Rexo Dock |
|---|---|
| **Voir le téléphone** | Grille de vignettes par jour, filtres « Nouveaux / Tous » : un fichier déjà importé n'est plus proposé comme nouveau, même si le dossier de destination a changé. Badges vidéo (durée), RAW, rafale |
| **Choisir** | Clic sur une photo, Maj + clic pour une plage, « Choisir ce jour », « Tout sélectionner » |
| **Séances** | La sélection est découpée en séances : nouvelle séance après plus de 3 h sans photo. Chacune a son nom (facultatif) et son dossier `AAAA-MM-JJ Nom`, daté du jour de la prise de vue ; « Tout mettre dans une seule séance » les regroupe |
| **Importer** | Originaux copiés tels quels (HEIC, JPEG, RAW, MOV), avec leurs fichiers de retouche `.AAE` ; taille de chaque copie vérifiée, date de prise de vue remise sur le fichier ; place libre contrôlée avant de commencer ; jamais d'écrasement (`IMG_0001_2.HEIC`) ; rapport d'import dans chaque dossier |
| **Seconde copie** | Après l'import, le dossier des séances est recopié sur un disque externe, chaque fichier vérifié par son empreinte SHA-256 ; rien n'y est écrasé ni supprimé |
| **Trier** | Après l'import, en arrière-plan : photos floues, yeux fermés ou plissés, séries de photos presque identiques avec la meilleure proposée. Le photographe garde, écarte, met à la Corbeille ou compare (voir « Aide au tri ») |

Une copie ne compte comme faite qu'après vérification, et chaque fichier est noté dès qu'il
est vérifié : un import coupé (câble débranché, téléphone verrouillé) reprend là où il s'est
arrêté, sans doublon.

## Où vont les photos

Par défaut dans **`Rexo Dock - Séances`**, sur le **Bureau** de la machine où Rexo Dock est
installé, pour que le photographe le trouve tout de suite. Le dossier est créé au lancement.
« Changer… » (panneau de gauche) en choisit un autre ; « Seconde copie » choisit le dossier du
disque externe. Ces choix sont propres à chaque machine (`donnees/reglages.json`).

```
Bureau/Rexo Dock - Séances/
    2026-11-20 Mariage/
        IMG_0001.HEIC  IMG_0001.AAE  IMG_0002.MOV  …
        Rapport d'import.txt
        Écartées/              photos écartées pendant le tri (récupérables)
        .rexo-tri.json         résultats de l'aide au tri (fichier caché)
```

## Aide au tri

Onglet **Séances**. L'analyse tourne sur les photos **déjà importées** (pleine qualité, même
téléphone débranché), une séance à la fois, et reprend au lancement si elle a été coupée.

| Signalement | Méthode | Mesuré |
|---|---|---|
| **Floue** | Variance du laplacien sur 4 × 4 zones de l'image réduite ; la zone la plus nette compte (un fond flou derrière un sujet net n'est pas un défaut). Floue si très faible, ou bien moins nette que la moyenne de sa séance (même téléphone, même lumière) | Photos nettes de test : 71 à 2 900 ; les mêmes floutées : 2 à 160 |
| **Yeux fermés ou plissés** | Visages par YuNet, 478 repères par Face Mesh ; ouverture de l'œil (hauteur / largeur) sous 0,15, comme dans Rexo ID. Seuls les visages assez grands comptent | Yeux ouverts : 0,19 à 0,34 ; un cas signalé vérifié à l'œil : yeux plissés au soleil |
| **Série** et **★ Meilleure** | Empreinte de l'image (dHash 64 bits). Même série : rafale marquée par l'iPhone, photos prises à quelques secondes d'écart et semblables, ou photos qui se suivent et sont identiques à l'œil. Meilleure : la plus nette sans yeux fermés | Photos identiques : distance 0 ; photos différentes : 21 et plus |

Filtres : **Toutes**, **À trier** (floues, yeux fermés ou plissés, doublons d'une série),
**Meilleures**, **Écartées**. L'analyse ne déplace ni ne supprime rien ; ce sont les actions
du photographe qui le font. Cliquer sur des photos pour les choisir, puis :

- **Garder** : la photo est bonne malgré le signalement (un flou voulu, par exemple) ; elle
  sort de « À trier ». « Ne plus garder » annule.
- **Écarter** : la photo va dans le sous-dossier `Écartées` de la séance, avec son `.AAE`.
  Le filtre « Écartées » la retrouve ; **Remettre** la ramène (sans écraser un fichier du même
  nom apparu entre-temps).
- **Corbeille** : dans la Corbeille du système, récupérable tant qu'elle n'est pas vidée.
  Second clic pour confirmer.
- **⤢** (coin d'une photo) : la série entière en grand, côte à côte, la meilleure encadrée,
  avec les mêmes actions sous chaque photo et « Ouvrir dans Aperçu ». Échap ferme.

Durée sur le MacBook : 0,1 à 0,9 s par photo (HEIC le plus lent).

## Regroupement par personne

Section **Personnes** de l'onglet Séances : « Regrouper par personne » lit les visages de la
séance (reconnaissance faciale) et affiche une vignette par personne présente sur au moins deux
photos, avec leur nombre ; un clic sur un visage ne montre que ses photos.

Ce sont des **données biométriques** (décision et garde-fous : ADR 0005) :
- rien n'est calculé tant que le photographe ne l'a pas demandé, séance par séance ;
- les empreintes restent dans la séance (`.rexo-visages.json`, fichier caché), jamais dans une
  base commune ni comparées d'une séance à l'autre ; aucun nom de personne ;
- la seconde copie ne les recopie pas ; « Effacer les empreintes de cette séance » les supprime,
  et l'empreinte d'une photo écartée ou mise à la Corbeille est retirée.

Méthode : visages par YuNet (48 pixels de large au moins), empreinte par SFace, regroupement à
liaison moyenne au seuil d'OpenCV (cosinus 0,363). Mesuré : même photo 0,99 ; même personne
entre un portrait de studio et un selfie 0,39 à 0,64 ; personnes différentes 0,27 au plus.

## Vignettes du téléphone

L'iPhone ne fournit que des vignettes de 120 × 160 pixels, quelle que soit la taille demandée :
floues à l'écran. Rexo Dock affiche d'abord celles-ci, puis les remplace par des vignettes
nettes, pour les éléments **visibles** seulement, un à la fois : l'original est lu dans un
dossier temporaire, réduit (pour une vidéo : l'image à 1 seconde du début), gardé en cache, et
la copie est effacée. Mesuré : 0,8 s par photo HEIC, de 0,4 à 5,5 s par vidéo (6 à 128 Mo), puis
instantané depuis le cache. Ce travail s'arrête pendant un import.

## Langue arabe

Le bouton **العربية** de la barre du haut passe toute l'interface en arabe, de droite à
gauche ; **Français** la ramène (`?langue=ar` dans l'adresse aussi). Les textes sont dans
`dock/web/ar.json` (clé : le texte français affiché, `{}` pour une partie variable). Moteur
commun au hub : `shared/langues.py` et `shared/web/langues.js`. L'apparence suit la charte
commune des applications Rexo, `shared/web/rexo.css`.

## Modèles d'IA

Pour l'aide au tri et le regroupement par personne seulement ; l'import n'en utilise aucun.

| Rôle | Modèle | Taille | Licence |
|---|---|---|---|
| Visages | YuNet (OpenCV Zoo) | 0,2 Mo | MIT ; entraîné sur WIDER Face, base réservée à la recherche : **usage commercial à vérifier** |
| Repères du visage (yeux) | MediaPipe Face Mesh V2, en ONNX | 4,9 Mo | Apache-2.0 |
| Reconnaissance faciale (regroupement par personne) | SFace (OpenCV Zoo) | 36,9 Mo | Apache-2.0 ; entraîné sur des bases de visages issues de la recherche : **usage commercial à vérifier** |

Les mêmes que Rexo ID, par le moteur commun `shared/vision`, dans le magasin partagé
`~/.local/share/kdev-models/embedkit`. Netteté et séries n'utilisent aucun modèle (OpenCV).

## Installation sur Mac

Prérequis : Mac Intel, macOS 12 ou plus (le Python autonome du hub est figé pour Intel). Depuis
la racine du hub :

```bash
shared/python/installer.sh          # Python 3.11.17 autonome
.outils/python/bin/python3 -m venv apps/dock/.venv
apps/dock/.venv/bin/pip install --require-hashes --only-binary :all: -r apps/dock/requirements.txt
export EMBEDKIT_CACHE=~/.local/share/kdev-models/embedkit
apps/dock/.venv/bin/python -m shared.embedkit.cli --models-path shared/ia/modeles \
    models pull --allow-noncommercial yunet-2023mar facemesh-v2 sface-2021dec
```

Les paquets sont figés par empreinte. L'accès au téléphone passe par ImageCaptureCore, l'API
d'Apple, depuis Python avec pyobjc 13.0 (licence MIT).

## Application à ouvrir d'un double-clic (Mac)

```bash
shared/lanceur/creer_app.sh dock --bureau     # depuis la racine du hub
```

Crée `~/Applications/Rexo Dock.app` et le raccourci **Rexo Dock** sur le Bureau. Un double-clic
démarre le serveur local et ouvre la page dans le navigateur ; Cmd+Q ou le bouton **Quitter**
de la page l'arrête. Journal : `~/Library/Logs/Rexo/dock.log`.

## Utilisation

### Interface web

```bash
cd apps/dock
.venv/bin/python -m dock.interface        # puis ouvrir http://127.0.0.1:8767
```

1. Brancher l'iPhone en USB, le **déverrouiller**, et toucher « Se fier » si la question
   s'affiche. La barre du haut indique l'état du téléphone.
2. Onglet **Téléphone** : choisir les photos (filtre « Nouveaux » par défaut), nommer les
   séances proposées, puis **Importer**. « Marquer comme déjà importées » sert aux photos
   copiées auparavant par un autre moyen : elles ne sont plus proposées, sans être copiées.
3. Onglet **Séances** : trier avec l'aide de l'IA (voir « Aide au tri »).

Le serveur n'écoute que sur la machine (127.0.0.1). L'adresse `#vue=seances` ouvre l'onglet
Séances. Si le téléphone ne signale pas une photo prise entre-temps, « Actualiser » relit sa
liste.

### Essai en ligne de commande

```bash
cd apps/dock
.venv/bin/python -m dock.appareil_mac                          # lit le téléphone, sans rien copier
.venv/bin/python -m dock.appareil_mac --copier 5 --vers /tmp/essai   # copie les 5 plus récents
```

Affiche l'état, le nombre de fichiers par genre et par extension, les rafales, le temps d'une
vignette ; avec `--copier`, la vitesse d'import (registre d'essai à part, le vrai registre
n'est pas touché).

## Données

| Emplacement | Contenu |
|---|---|
| `donnees/registre.json` | fichiers déjà importés, par téléphone (clé : nom, taille, date de prise de vue ; même format que le prototype Import Studio, pour reprendre son historique) |
| `donnees/reglages.json` | dossier des séances, dossier de seconde copie |
| `donnees/vignettes/`, `donnees/vignettes-telephone/` | vignettes en cache (effaçables : elles sont refaites) |
| `<séance>/.rexo-tri.json` | résultats de l'aide au tri ; suit le dossier s'il est déplacé ou recopié |
| `<séance>/.rexo-visages.json` | empreintes des visages, seulement si le photographe l'a demandé ; jamais recopié sur le disque externe |

`donnees/` n'entre jamais dans le dépôt git. `DOCK_DATA=<dossier>` en utilise un autre (essais).

## Windows

Pas encore disponible. Tout ce qui ne dépend pas du système est déjà commun (`coeur.py`,
`importer.py`, `tri.py`, `seances.py`, interface, extraction d'image des vidéos par OpenCV).
Restent à faire et à essayer sur un PC : l'accès au téléphone par Windows Portable Devices
(`comtypes`), la lecture des HEIC (sous macOS, `sips` s'en charge) et le raccourci du Bureau.

## Limites connues

- Un **bougé** dans une seule direction est mal repéré par la mesure de netteté.
- **Yeux** : sur de petits visages (photo de groupe de loin), l'ouverture n'est pas mesurée.
- **Séances** : l'écart de 3 h convient à une journée de prises de vue ; deux séances le même
  après-midi peuvent être réunies (les renommer ou importer en deux fois).
- Un seul téléphone à la fois.

## Tests

```bash
.venv/bin/python -m unittest discover tests
```

Sans téléphone ni modèle d'IA (faux appareil, visages remplacés).

## Code

| Fichier | Rôle |
|---|---|
| `dock/coeur.py` | sans dépendance au système : registre des imports, noms de séance et de fichier, catalogue (retouches `.AAE`), séances proposées, SHA-256, seconde copie vérifiée |
| `dock/importer.py` | import d'une sélection depuis n'importe quel appareil : place, dossier de séance, vérification, date, registre, rapport |
| `dock/appareil_mac.py` | accès au téléphone sous macOS (ImageCaptureCore par pyobjc) : état, liste, vignettes, copie des originaux ; essai en ligne de commande |
| `dock/tri.py` | aide au tri : netteté, yeux, empreintes, séries et meilleure photo |
| `dock/personnes.py` | regroupement par personne (à la demande) : empreintes SFace dans la séance, liaison moyenne, effacement et purge |
| `dock/seances.py` | dossiers de séance : analyse, résultats (`.rexo-tri.json`), vignettes, actions Garder / Écarter / Remettre / Corbeille |
| `dock/config.py` | emplacements et réglages, calculés sur la machine (Bureau donné par `shared/systeme`) |
| `dock/interface.py`, `dock/web/` | interface web locale (Flask, 127.0.0.1 seulement) ; le fil principal fait tourner l'accès au téléphone |

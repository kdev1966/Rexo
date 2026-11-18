# Reveal

Retouche de photos pour un studio, **100 % locale** : PhotoCraft piloté par Python, avec des
modèles IA open source qui tournent sur le processeur. Aucune photo ne quitte la machine.

| Type de photo | Ce que fait Reveal, sans retouche à la main |
|---|---|
| **Portrait** (couleur) | Visages restaurés par IA (GFPGAN), lissage de la peau limité à la peau détectée, maquillage (lèvres, blush, paupières) placé grâce aux repères du visage |
| **Photo ancienne** (noir et blanc, sépia) | Agrandissement x2 si elle est petite (Real-ESRGAN), recadrage du tirage, gris neutre, stries et rayures atténuées, bruit, voile, contraste, netteté, visages restaurés, puis colorisation (DDColor) |
| **Studio** | Personnes détourées par Apple Vision : fond flou, fond uni, couleur sur fond noir et blanc, détourage (PNG transparent), recadrage 4:5, 1:1, 9:16, 16:9, 3:4, 2:3 centré sur les personnes |
| **Effacer** | Objets ou personnes indésirables : on trace un cadre serré autour, ou on clique dessus (Alt-clic exclut une partie) ; plusieurs zones par photo. MobileSAM détoure, MI-GAN reconstitue le décor ; calque « Effacement (IA) » masqué à la seule zone reconstituée |
| **Améliorer** | Amélioration automatique d'Apple (lumière, couleurs, balance des blancs, relief), puis rendu de couleur au choix : chaud, froid, vintage chaud, noir et blanc, lumineux, contrasté, doux |

Pour les portraits, le lissage est limité à la peau **des personnes** détectées par Apple Vision :
un fond couleur chair n'est plus lissé.

Le type est choisi automatiquement : une photo sans couleur est traitée comme ancienne.
Chaque résultat est un **PSD à calques** (chaque étape réglable dans PhotoCraft) et un JPEG.

## Installation

Prérequis : Mac Intel, macOS 12 ou plus, outils en ligne de commande d'Apple, PhotoCraft ≥ 0.23
dans `/Applications`.

```bash
shared/python/installer.sh          # Python 3.11.17 autonome (depuis la racine du hub)
shared/natif/compiler.sh            # reto-segment (Apple Vision)
cd apps/reveal
../../.outils/python/bin/python3 -m venv .venv
.venv/bin/pip install --require-hashes --only-binary :all: -r requirements.txt
.venv/bin/python -m shared.embedkit.cli models pull --models-path modeles --all --allow-noncommercial
```

Licences : GFPGAN, DDColor et la colorisation de Zhang ont un usage commercial **non vérifié**
(`commercial: unknown` dans `modeles/*.yaml`). Reveal les autorise explicitement
(`reveal/catalogue.py`, `A_VERIFIER`) et affiche un avertissement à chaque chargement.

## Application à ouvrir d'un double-clic

```bash
shared/lanceur/creer_app.sh reveal --bureau     # depuis la racine du hub
```

Crée `~/Applications/Reveal.app` et un raccourci sur le Bureau. Un double-clic démarre le
serveur local et ouvre la page dans le navigateur ; quitter l'application (Cmd+Q) arrête le
serveur. Le bouton **Quitter** de la page fait de même : il arrête le serveur, et l'application se
ferme d'elle-même. Un traitement en cours est arrêté (les modèles d'IA quittent la mémoire), PhotoCraft compris. Journal : `~/Library/Logs/RetoHub/reveal.log`. Sans `--bureau`, pas de raccourci.

## Utilisation

### Interface web

```bash
cd apps/reveal
.venv/bin/python -m reveal.interface        # puis ouvrir http://127.0.0.1:8765
```

Choisir ou déposer une photo, choisir un filtre (Automatique, Portrait, Photo ancienne,
Restauration seule), appliquer, puis comparer avec le curseur avant / après, côte à côte, ou
l'une des deux vues seule. Le PSD s'ouvre dans PhotoCraft d'un clic.

### Ligne de commande

```bash
.venv/bin/python -m reveal.traiter                          # toutes les photos de donnees/original/
.venv/bin/python -m reveal.traiter donnees/original/1.jpg   # une photo
.venv/bin/python -m reveal.traiter --type ancienne donnees/original/x.jpg
```

## Formats acceptés

JPEG, PNG, TIFF, WebP, BMP, GIF, TGA, **AVIF**, **HEIC / HEIF** (iPhone), JPEG 2000, PSD, EXR, HDR,
QOI, ICO. Ce qu'OpenCV ne lit pas est converti sans perte en PNG par `shared/images`, avec le
premier outil qui réussit : Pillow (AVIF, GIF, TGA…), puis PhotoCraft (HEIC, PSD…), puis `sips`
(outil d'images de macOS). Les pixels transparents sont posés sur du blanc ; d'un GIF animé, seule
la première image est gardée. Dans l'interface, les formats que le navigateur n'affiche pas reçoivent
un aperçu JPEG, mis en cache dans `donnees/.apercus/`.

## Données

Tout est rangé dans `donnees/` (ou le dossier donné par `REVEAL_DATA`), jamais versionné :

| Chemin | Contenu |
|---|---|
| `original/` | photos à traiter, jamais modifiées |
| `retouche/NOM_photocraft.psd` | résultat à calques |
| `retouche/NOM_photocraft.jpg` | résultat final |
| `retouche/NOM_photocraft_avant.jpg` | l'original à la même géométrie, pour comparer |
| `retouche/NOM_photocraft_restauree.jpg` | photos anciennes : la restauration en noir et blanc |
| `reglages.json` | réglages par photo (voir ci-dessous) |

Un fichier existant n'est jamais remplacé : les résultats suivants prennent `_2`, `_3`…

### Réglages par photo

```json
{
  "3.jpeg": {
    "visages_exclus_ia": [[0.37, 0.28]],
    "correcteur": [{"nom": "strie", "points": [[0.31, 0.26], [0.43, 0.25]], "taille": 0.01}]
  }
}
```

- `visages_exclus_ia` : centres (en fraction de l'image traitée) des visages que GFPGAN ne doit
  pas toucher ; le traitement affiche la liste des visages détectés avec leur centre.
- `correcteur` : tracés passés au correcteur localisé de PhotoCraft avant la restauration des visages.

## Tests

```bash
.venv/bin/python -m unittest discover tests
```

## Code

| Fichier | Rôle |
|---|---|
| `reveal/traiter.py` | chaîne de traitement, pilote PhotoCraft (`shared.photocraft`) |
| `reveal/analyse.py` | vision en Python (OpenCV) : peau, maquillage, stries, colorisation de secours |
| `reveal/ia.py` | modèles ONNX : Real-ESRGAN, GFPGAN, DDColor |
| `reveal/effacer.py` | effacement : zones (cadres, clics), MobileSAM, MI-GAN (embedkit) |
| `reveal/vision.py` | Apple Vision et Core Image par `reto-segment` : masque des personnes, studio, amélioration, rendus |
| `reveal/catalogue.py` | modèles par embedkit, contrôle des licences |
| `modeles/*.yaml` | manifestes embedkit des modèles propres à Reveal |
| `reveal/interface.py`, `reveal/web/` | interface web locale (Flask, 127.0.0.1 seulement) |
| `reveal/config.py` | emplacements des données, formats acceptés |

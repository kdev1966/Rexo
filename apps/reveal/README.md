# Rexo Reveal

Retouche de photos pour un studio, **sous macOS et sous Windows**, **100 % locale** : PhotoCraft
piloté par Python, avec des modèles IA open source qui tournent sur le processeur. Aucune photo
ne quitte la machine.

| Type de photo | Ce que fait Reveal, sans retouche à la main |
|---|---|
| **Portrait** (couleur) | Visages restaurés par IA (GFPGAN), lissage de la peau limité à la peau détectée, maquillage (lèvres, blush, paupières) placé grâce aux repères du visage |
| **Photo ancienne** (noir et blanc, sépia) | D'abord la réparation, sur l'image d'origine : parties arrachées reconstituées, taches atténuées (tirage monochrome), rayures, fissures et déchirures détectées (modèle de Microsoft) puis effacées (LaMa), grain du film atténué (SCUNet) s'il est marqué. Ensuite agrandissement x2 si elle est petite (Real-ESRGAN), recadrage du tirage, gris neutre, stries, bruit, voile, contraste, netteté, visages restaurés, puis colorisation (DDColor tiny) |
| **Studio** | Personnes détourées (MODNet, vérifié par MobileSAM guidé par les visages) : fond flou, fond uni, couleur sur fond noir et blanc, détourage (PNG transparent), recadrage 4:5, 1:1, 9:16, 16:9, 3:4, 2:3 centré sur les personnes |
| **Effacer** | Objets ou personnes indésirables : on trace un cadre serré autour, ou on clique dessus (Alt-clic exclut une partie) ; plusieurs zones par photo. MobileSAM détoure, MI-GAN reconstitue le décor ; calque « Effacement (IA) » masqué à la seule zone reconstituée |
| **Améliorer** | Amélioration automatique (exposition, ombres, vivacité, balance des blancs sur les blancs, relief, réglée sur celle d'Apple), puis rendu de couleur au choix : chaud, froid, vintage chaud, noir et blanc, lumineux, contrasté, doux |

Les visages sont trouvés par le détecteur commun du hub (YuNet, `shared/vision`), le même que
pour Rexo ID et Rexo Dock : mesuré sur les photos de test, il trouve les mêmes visages que
PhotoCraft (7 sur 7 sur une photo de groupe ancienne), avec des repères à quelques pourcents
près, et 2 à 7 fois plus vite.

Pour les portraits, le lissage est limité à la peau **des personnes** détectées :
un fond couleur chair n'est plus lissé.

Le type est choisi automatiquement : une photo sans couleur est traitée comme ancienne.
Chaque résultat est un **PSD à calques** (chaque étape réglable dans PhotoCraft) et un JPEG.

**Grain du film** (photos anciennes) : Reveal mesure d'abord le bruit sur les zones unies de
l'image (estimateur d'Immerkær), et ne débruite que s'il dépasse 1,2 (écart type sur 255).
Mesuré : tirages argentiques scannés de 1,4 à 2,3 ; photos numériques de 0,05 à 1,0, laissées
telles quelles. Le débruitage (SCUNet, Apache-2.0) travaille par tuiles de 512 pixels qui se
chevauchent et se fondent (pas de raccord), puis remet 15 % de l'original pour ne pas donner
un aspect lissé. Il est lent : environ 16 s par tuile sur le MacBook, soit de 16 s pour une petite
photo à 2 min 30 pour un scan de 1000 × 1300 pixels ; le rapport indique le grain avant et après,
et le temps.

## Installation sur Mac

Prérequis : Mac Intel, macOS 12 ou plus, PhotoCraft ≥ 0.23 dans `/Applications`.

Toutes les commandes se lancent **depuis la racine du hub** :

```bash
shared/python/installer.sh          # Python 3.11.17 autonome
.outils/python/bin/python3 -m venv apps/reveal/.venv
apps/reveal/.venv/bin/pip install --require-hashes --only-binary :all: -r apps/reveal/requirements.txt

# Modèles d'IA (environ 1,6 Go), dans le magasin partagé par les applications Rexo
export EMBEDKIT_CACHE=~/.local/share/kdev-models/embedkit
apps/reveal/.venv/bin/python -m shared.embedkit.cli --models-path shared/ia/modeles \
    models pull --allow-noncommercial gfpgan-1.4 ddcolor zhang-colorization real-esrgan-x2 mobilesam migan-512 \
    rayures-anciennes lama-512 scunet-512 ddcolor-tiny
apps/reveal/.venv/bin/python -m shared.embedkit.cli --models-path shared/ia/modeles \
    models pull --allow-noncommercial yunet-2023mar modnet
apps/reveal/.venv/bin/python -m shared.embedkit.cli --models-path shared/ia/modeles models verify
```

## Installation sous Windows

Prérequis : Windows 10 ou 11, 64 bits ; PhotoCraft ≥ 0.23 installé par le lanceur ArtCraft
(`C:\Program Files\ArtCraft\PhotoCraft`, trouvé tout seul ; sinon, indiquer le chemin de
`photocraft-cli.exe` dans la variable `PHOTOCRAFT_CLI`). Dans PowerShell, depuis la racine du hub :

```powershell
powershell -ExecutionPolicy Bypass -File shared\python\installer.ps1     # Python 3.11.17 autonome
.outils\python\python.exe -m venv apps\reveal\.venv
apps\reveal\.venv\Scripts\pip install --require-hashes --only-binary :all: -r apps\reveal\requirements.txt
$env:EMBEDKIT_CACHE = "$env:USERPROFILE\.local\share\kdev-models\embedkit"
apps\reveal\.venv\Scripts\python -m shared.embedkit.cli --models-path shared\ia\modeles `
    models pull --allow-noncommercial gfpgan-1.4 ddcolor zhang-colorization real-esrgan-x2 mobilesam migan-512 `
    rayures-anciennes lama-512 scunet-512 ddcolor-tiny
apps\reveal\.venv\Scripts\python -m shared.embedkit.cli --models-path shared\ia\modeles `
    models pull --allow-noncommercial yunet-2023mar modnet
powershell -ExecutionPolicy Bypass -File shared\lanceur\creer_raccourci.ps1 reveal
```

La dernière ligne crée le raccourci **Rexo Reveal** sur le Bureau (serveur sans fenêtre noire,
page dans le navigateur, bouton **Quitter**). Journal : `%LOCALAPPDATA%\Rexo\Journaux\reveal.log`.
Les formats HEIC et PSD sont convertis par PhotoCraft (`sips` n'existe que sur Mac).

Trois points comptent dans cette commande :
- **la racine du hub** : c'est là que Python trouve le code partagé (`shared`) ;
- **`EMBEDKIT_CACHE`** : sans elle, l'outil range les modèles dans son dossier par défaut,
  où Rexo Reveal ne les cherche pas (il les cherche dans `~/.local/share/kdev-models/embedkit`,
  ou dans `$KDEV_MODELS_DIR/embedkit` si cette variable est définie) ;
- **`--models-path` avant `models`** : c'est une option générale de l'outil.

Les modèles déjà présents et intacts ne sont pas retéléchargés ; `models verify` contrôle
leur empreinte SHA-256, et `models list` indique ce qui est installé.

Licences : GFPGAN, DDColor et la colorisation de Zhang ont un usage commercial **non vérifié**
(`commercial: unknown` dans `shared/ia/modeles/*.yaml`). Le catalogue commun des modèles les
autorise explicitement en attendant (`shared/ia`, `A_VERIFIER`).

## Application à ouvrir d'un double-clic (Mac)

```bash
shared/lanceur/creer_app.sh reveal --bureau     # depuis la racine du hub
```

Crée `~/Applications/Rexo Reveal.app` et un raccourci sur le Bureau. Un double-clic démarre le
serveur local et ouvre la page dans le navigateur ; quitter l'application (Cmd+Q) arrête le
serveur. Le bouton **Quitter** de la page fait de même : il arrête le serveur, et l'application se
ferme d'elle-même. Un traitement en cours est arrêté (les modèles d'IA quittent la mémoire), PhotoCraft compris. Journal : `~/Library/Logs/Rexo/reveal.log`. Sans `--bureau`, pas de raccourci.

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

## Langue arabe

Le bouton **العربية** de la barre du haut passe l'interface en arabe, de droite à gauche
(**Français** la ramène ; `?langue=ar` dans l'adresse aussi). Le journal de traitement et les
messages du serveur sont traduits ; la zone d'image (curseur avant / après, zones à effacer)
reste de gauche à droite. Textes dans `reveal/web/ar.json` (clé = texte français, `{}` pour
une partie variable), moteur commun au hub : `shared/langues.py`, `shared/web/langues.js`.

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
| `reveal/restauration.py` | réparation des photos anciennes : manques, taches, teinte d'origine, enchaînement des étapes ; les outils d'IA (rayures, LaMa, grain SCUNet) sont communs : `shared/ia/restauration.py` |
| `shared/ia/photo.py` (commun) | agrandissement Real-ESRGAN, visages GFPGAN, colorisation DDColor (tiny, préféré ; grand en secours) |
| `reveal/effacer.py` | effacement : zones (cadres, clics), MobileSAM, MI-GAN (embedkit) |
| `reveal/vision.py` | masque des personnes, studio, amélioration, rendus : `shared/vision` (MODNet, MobileSAM, effets en numpy), identiques sous macOS et Windows |
| `modeles/*.yaml` | manifestes embedkit des modèles propres à Reveal |
| `reveal/interface.py`, `reveal/web/` | interface web locale (Flask, 127.0.0.1 seulement) |
| `reveal/config.py` | emplacements des données, formats acceptés |

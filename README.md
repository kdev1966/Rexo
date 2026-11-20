# Rexo

**Rexo** est une famille d'outils pour studio photo : **Rexo Studio**, **Rexo Reveal**,
**Rexo ID**, **Rexo Dock**. Ce dépôt est le hub de la famille : un dépôt unique (monorepo) pour une suite de
petits outils de retouche photo et vidéo,
pensés pour un studio photo, qui tournent **entièrement en local**, **sous macOS et sous
Windows**, avec le même résultat sur les deux : aucune photo ne quitte la machine.

Chaque outil est une application indépendante dans `apps/`. Ce qui sert à plusieurs
applications (pilote PhotoCraft, catalogue des modèles IA) est dans `shared/`.

## Applications

| Application | Rôle | Dossier |
|---|---|---|
| **Rexo Reveal** | Retouche de portraits (visages, peau, maquillage) et restauration puis colorisation de photos anciennes, avec PhotoCraft et des modèles IA locaux | [`apps/reveal`](apps/reveal) |
| **Rexo ID** | Photos d'identité aux normes françaises (35 × 45 mm, fond gris clair, balance des blancs) et planches 10 × 15 cm avec traits de coupe | [`apps/identite`](apps/identite) |
| **Rexo Dock** | Import vérifié des photos et vidéos d'un iPhone (rien n'est supprimé du téléphone), séances proposées, seconde copie sur disque externe, puis aide au tri par IA : photos floues, yeux fermés ou plissés, séries avec la meilleure photo. macOS pour l'instant | [`apps/dock`](apps/dock) |

## Organisation

```
apps/<application>/   une application : son code, ses tests, son interface
shared/photocraft/    pilote de PhotoCraft (photocraft-cli serve)
shared/embedkit/      couche d'IA locale (repris de Rexo Studio) : registre de modèles, téléchargement
                      épinglé et vérifié (SHA-256), audit des licences, ONNX, détourage, effacement, profondeur
shared/vision/        vision locale commune, identique sous macOS et Windows (ONNX) : visages (YuNet),
                      repères du visage (Face Mesh), détourage des personnes (MODNet, MobileSAM) ;
                      effets.py : fonds, recadrage, amélioration, rendus de couleur (numpy, OpenCV)
shared/systeme.py     ce qui dépend du système : Corbeille, ouvrir un fichier ou un dossier, choisir un dossier
shared/python/        Python 3.11 autonome partagé (python-build-standalone, SHA-256 épinglé) :
                      installer.sh (Mac), installer.ps1 (Windows)
shared/lanceur/       ouvrir d'un double-clic (serveur local + navigateur) : creer_app.sh (application
                      macOS), creer_raccourci.ps1 et lancer.py (raccourci du Bureau Windows)
shared/natif/         rexo-segment (Swift, Apple Vision) : n'est plus utilisé par les applications du
                      hub depuis le passage à Windows (ADR 0004) ; gardé pour référence
shared/langues.py     traduction des interfaces (arabe) : catalogue JSON par application, messages du serveur
shared/web/           scripts communs des pages (langues.js : traduction, sens de droite à gauche)
shared/images/        conversion de tous les formats d'image en PNG ou JPEG (Pillow, PhotoCraft, sips sur Mac)
docs/adr/             décisions d'architecture
```

## Modèles IA

Les modèles ne sont **pas** dans le dépôt. embedkit les range une seule fois par machine dans
`~/.local/share/kdev-models/embedkit` (sous Windows : `%USERPROFILE%\.local\share\kdev-models\embedkit` ;
`KDEV_MODELS_DIR` pour un autre dossier), partagé par toutes les applications Rexo : un modèle
servant à deux applications n'est stocké qu'une fois. Chaque modèle a un manifeste YAML
(adresse, empreinte SHA-256, licence) : ceux d'embedkit dans `shared/embedkit/models/`, ceux de
la vision commune dans `shared/vision/modeles/`, ceux d'une application dans `apps/<app>/modeles/`.
Un modèle dont l'usage commercial n'est pas établi est refusé par défaut, sauf autorisation
explicite de l'application.

## Déploiement

Le développement se fait sur une machine de développement ; une machine d'exploitation
reçoit les versions par `git push` sur une branche d'arrivée, puis une fusion en avance rapide,
suivie de l'installation propre à chaque application (voir le README de l'application).

## Prérequis

- Mac Intel (x86_64), macOS 12 ou plus, **ou** Windows 10 ou 11 (64 bits)
- Python 3.11 autonome : `shared/python/installer.sh` (Mac) ou `shared\python\installer.ps1` (Windows)
- PhotoCraft ≥ 0.23 pour les applications qui le pilotent (`/Applications` sur Mac ;
  `C:\Program Files\ArtCraft\PhotoCraft` sous Windows)

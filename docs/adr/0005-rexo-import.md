# ADR 0005 — Rexo Import : copier les photos d'un iPhone, puis aider au tri

Date : 20/11/2026. Statut : proposé (en attente du prototype Windows, voir « Risques »).

## Contexte

Un studio a perdu une nuit à récupérer les photos d'un iPhone : sans procédure d'import, il
est passé par une sauvegarde complète du téléphone, une extraction, puis une restauration qui
a failli effacer l'appareil. Un prototype macOS, Import Studio (Swift, ImageCaptureCore), a
été écrit en urgence et tourne sur l'iMac : grille de vignettes, import des seuls fichiers
nouveaux, vérification de chaque copie, seconde copie sur disque externe, rien n'est jamais
supprimé du téléphone. Il ne fonctionne que sous macOS et sort de la pile du hub (ADR 0004).

L'import est la première étape du travail d'un studio ; il doit suivre les mêmes principes
que Rexo Reveal et Rexo ID : local, macOS et Windows, interface web locale, langue arabe.

## Décision

**Rexo Import** devient une application du hub, dans `apps/import`, qui reprend le prototype
dans la pile Rexo.

- **Un cœur commun en Python** (`import/coeur.py`, sans dépendance au système) : registre des
  fichiers déjà importés (clé nom + taille + date de prise de vue, par appareil), nom du
  dossier de séance (`AAAA-MM-JJ [nom]`), noms de fichiers sans écrasement, vérification de
  la taille puis de l'empreinte SHA-256, date d'origine remise sur le fichier, seconde copie
  vérifiée sur un disque externe, rapport d'import. C'est la logique de `Core.swift`, avec
  ses tests.
- **L'interface habituelle du hub** : Flask sur 127.0.0.1, grille de vignettes, filtres
  « Nouveaux / Tous », sélection, import de la sélection, « déjà importé », traduction arabe
  par `shared/langues`, lanceur de `shared/lanceur`.
- **L'accès à l'appareil est la seule partie propre à chaque système**, derrière une même
  interface (`lister`, `vignette`, `copier`) :
  - **macOS** : ImageCaptureCore depuis Python (pyobjc, licence MIT), la même API que le
    prototype, qui donne les originaux (HEIC, RAW, MOV) sans dépendre du réglage de l'iPhone ;
  - **Windows** : l'iPhone est vu comme un appareil photo par le système. Accès par l'API
    Windows Portable Devices (WPD), depuis Python par `comtypes` (licence MIT).
- **Écarté** : `pymobiledevice3` (même code sur les deux systèmes, mais sous licence GPL, à
  vérifier, incompatible avec un dépôt public destiné à un usage commercial) et la copie
  par la sauvegarde complète du téléphone (lourde, et c'est elle qui a causé l'incident).
- **Rien n'est jamais supprimé de l'appareil.** Une copie ne compte comme faite qu'après
  vérification ; une coupure reprend là où elle s'est arrêtée.

## Aide au tri (décisions du 20/11/2026)

Après l'import, en arrière-plan, sur des images réduites (les machines des studios sont
lentes : iMac de 2015 à disque dur) :

| Fonction | Méthode | Version |
|---|---|---|
| Photos floues | mesure de netteté OpenCV, sans modèle | v1 |
| Yeux fermés | Face Mesh, déjà dans `shared/vision` | v1 |
| Rafales et quasi-doublons | regroupement des photos presque identiques, meilleure photo de chaque série proposée | v1 |
| Séances automatiques | découpage selon les écarts de temps, nom de dossier proposé | v1 |
| Recherche par contenu | modèle de type CLIP en ONNX, après vérification de la licence et de la vitesse | v2 |
| Regroupement par personne | **non décidé** : données biométriques de clients ; cadre légal (loi tunisienne, RGPD) à étudier avant toute décision | — |

Les photos signalées reçoivent **seulement un badge** et un filtre « À trier » : rien n'est
déplacé ni supprimé sans l'action du photographe.

## Risques

- **Windows** : l'accès WPD à un iPhone n'est pas encore prouvé (pilote Apple requis,
  originaux HEIC ou JPEG convertis, vitesse). Un prototype sur le PC Windows passe avant tout
  autre développement ; s'il échoue, cette ADR est revue.
- pyobjc doit fournir des roues pour macOS 12 Intel, figées par empreinte comme les autres
  paquets du hub.

## Conséquences

- Import Studio reste en service sur l'iMac jusqu'à ce que Rexo Import y soit testé.
- Aucun nom de studio ni de photographe dans le dépôt (public).
- Une fonction ne compte comme faite qu'après un essai sur le Mac **et** sur le PC Windows.

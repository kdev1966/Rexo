# Rexo

**Rexo** est une famille d'outils pour studio photo : **Rexo Studio**, **Rexo Reveal**,
**Rexo ID**. Ce dépôt est le hub de la famille : un dépôt unique (monorepo) pour une suite de
petits outils de retouche photo et vidéo,
pensés pour un studio photo, qui tournent **entièrement en local** sur des Mac Intel
(macOS 12 ou plus) : aucune photo ne quitte la machine.

Chaque outil est une application indépendante dans `apps/`. Ce qui sert à plusieurs
applications (pilote PhotoCraft, catalogue des modèles IA) est dans `shared/`.

## Applications

| Application | Rôle | Dossier |
|---|---|---|
| **Rexo Reveal** | Retouche de portraits (visages, peau, maquillage) et restauration puis colorisation de photos anciennes, avec PhotoCraft et des modèles IA locaux | [`apps/reveal`](apps/reveal) |
| **Rexo ID** | Photos d'identité aux normes françaises (35 × 45 mm, fond gris clair, balance des blancs) et planches 10 × 15 cm avec traits de coupe | [`apps/identite`](apps/identite) |

## Organisation

```
apps/<application>/   une application : son code, ses tests, son interface
shared/photocraft/    pilote de PhotoCraft (photocraft-cli serve)
shared/embedkit/      couche d'IA locale (repris de Rexo Studio) : registre de modèles, téléchargement
                      épinglé et vérifié (SHA-256), audit des licences, ONNX, détourage, effacement, profondeur
shared/natif/         rexo-segment (Swift, Apple Vision et Core Image) : détourage des personnes, fonds,
                      recadrage, amélioration, rendus de couleur, repères du visage, balance des blancs ;
                      compiler.sh le compile sur la machine, __init__.py l'appelle depuis Python
shared/python/        installer.sh : Python 3.11 autonome partagé (python-build-standalone, SHA-256 épinglé)
shared/lanceur/       creer_app.sh : application macOS à ouvrir d'un double-clic (serveur local + navigateur)
shared/langues.py     traduction des interfaces (arabe) : catalogue JSON par application, messages du serveur
shared/web/           scripts communs des pages (langues.js : traduction, sens de droite à gauche)
shared/images/        conversion de tous les formats d'image en PNG ou JPEG (Pillow, PhotoCraft, sips)
docs/adr/             décisions d'architecture
```

## Modèles IA

Les modèles ne sont **pas** dans le dépôt. embedkit les range une seule fois par machine dans
`~/.local/share/kdev-models/embedkit` (`KDEV_MODELS_DIR` pour un autre dossier), partagé avec
Rexo Studio. Chaque modèle a un manifeste YAML (adresse, empreinte SHA-256, licence) : ceux
d'embedkit dans `shared/embedkit/models/`, ceux d'une application dans `apps/<app>/modeles/`.
Un modèle dont l'usage commercial n'est pas établi est refusé par défaut, sauf autorisation
explicite de l'application.

## Déploiement

Le développement se fait sur une machine de développement ; une machine d'exploitation
reçoit les versions par `git push` sur une branche d'arrivée, puis une fusion en avance rapide,
suivie de l'installation propre à chaque application (voir le README de l'application).

## Prérequis

- Mac Intel (x86_64), macOS 12 ou plus ; Python 3.11 autonome installé par `shared/python/installer.sh`
- Outils en ligne de commande d'Apple (`xcode-select --install`) pour compiler `rexo-segment`
- PhotoCraft ≥ 0.23 dans `/Applications` pour les applications qui le pilotent

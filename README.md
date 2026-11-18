# RetoHub

Un dépôt unique (monorepo) pour une suite de petits outils de retouche photo et vidéo,
pensés pour un studio photo, qui tournent **entièrement en local** sur des Mac Intel
(macOS 12 ou plus) : aucune photo ne quitte la machine.

Chaque outil est une application indépendante dans `apps/`. Ce qui sert à plusieurs
applications (pilote PhotoCraft, catalogue des modèles IA) est dans `shared/`.

## Applications

| Application | Rôle | Dossier |
|---|---|---|
| **Reveal** | Retouche de portraits (visages, peau, maquillage) et restauration puis colorisation de photos anciennes, avec PhotoCraft et des modèles IA locaux | [`apps/reveal`](apps/reveal) |

## Organisation

```
apps/<application>/   une application : son code, ses tests, son interface
shared/photocraft/    pilote de PhotoCraft (photocraft-cli serve)
shared/modeles/       catalogue des modèles IA : adresse, empreinte SHA-256, installation vérifiée
docs/adr/             décisions d'architecture
```

## Modèles IA

Les modèles ne sont **pas** dans le dépôt. Ils sont rangés une seule fois par machine dans
`~/.local/share/kdev-models` (ou le dossier donné par `KDEV_MODELS_DIR`) et partagés par toutes
les applications. Le catalogue `shared/modeles/catalogue.json` donne pour chacun son adresse
de téléchargement et son empreinte SHA-256.

```bash
python3 -m shared.modeles liste              # état des modèles sur cette machine
python3 -m shared.modeles installer reveal   # télécharge et vérifie les modèles de Reveal
```

## Déploiement

Le développement se fait sur une machine de développement ; une machine d'exploitation
reçoit les versions par `git push` sur une branche d'arrivée, puis une fusion en avance rapide,
suivie de l'installation propre à chaque application (voir le README de l'application).

## Prérequis

- Mac Intel (x86_64), macOS 12 ou plus, Python 3.9 du système
- PhotoCraft ≥ 0.23 dans `/Applications` pour les applications qui le pilotent

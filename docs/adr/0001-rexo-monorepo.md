# ADR 0001 — Rexo, un monorepo pour une suite de petits outils

- **Statut** : accepté
- **Date** : 18 novembre 2026
- **Décideur** : porteur du projet

## Contexte

Le porteur du projet veut développer, au fil des besoins, une série de petits outils et
d'applications de retouche pour un studio photo, qui tournent en local sur des Mac Intel.
Plusieurs de ces outils utilisent les mêmes ressources lourdes : modèles IA open source
(plusieurs centaines de mégaoctets chacun), pilote de PhotoCraft, versions figées des
bibliothèques de calcul (onnxruntime, OpenCV, numpy) qui sont les dernières compilées pour
macOS 12 sur Intel.

## Décision

Un seul dépôt git, **Rexo**, public :

- `apps/<application>/` : une application par dossier, avec son code, ses tests, son interface
  et son propre environnement Python ;
- `shared/` : le code commun (pilote PhotoCraft, catalogue des modèles) ;
- les **modèles ne sont pas versionnés** : le dépôt contient seulement leur catalogue
  (adresse, taille, SHA-256) ; ils sont rangés une fois par machine dans
  `~/.local/share/kdev-models` et partagés par toutes les applications ;
- les **photos des clients ne sont jamais versionnées** (`apps/*/donnees/` est ignoré).

## Conséquences

- Une nouvelle application démarre avec le pilote PhotoCraft et les modèles déjà disponibles.
- Une modification de `shared/` peut toucher plusieurs applications : chaque application garde
  ses tests, à relancer quand `shared/` change.
- Le dépôt étant public, aucune information privée (adresses de machines, comptes, noms de
  studio ou de photographe, photos) ne doit y entrer.

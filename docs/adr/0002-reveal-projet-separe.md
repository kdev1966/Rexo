# ADR 0002 — Reveal reste séparé de Rexo Studio

- **Statut** : accepté
- **Date** : 18 novembre 2026
- **Décideur** : porteur du projet

## Contexte

Reveal (retouche de portraits, restauration et colorisation de photos anciennes) est né de
tests sur la machine d'exploitation. Rexo Studio, projet existant dans son propre dépôt, fait
du dérushage et de la post-production vidéo d'événements. Les deux partagent le même public,
la même machine et une partie de la pile technique : PhotoCraft piloté par `photocraft-cli`,
onnxruntime 1.19.2, OpenCV 4.10, modèles dans `~/.local/share/kdev-models`.

Trois scénarios ont été étudiés :

- **A.** Reveal devient un module de Rexo Studio.
- **B.** Reveal vit seul dans Rexo ; Rexo Studio reste un dépôt à part ; on partage d'abord
  les modèles, puis le code commun.
- **C.** B, puis Rexo Studio rejoint Rexo (`git subtree`, historique conservé).

## Décision

**Scénario B.**

Arguments retenus :

- la vision du projet est une suite de **petits outils indépendants** ; greffer Reveal sur
  Rexo Studio alourdirait chaque version et couplerait leurs calendriers ;
- le cœur de Rexo Studio n'utilise que la bibliothèque standard de Python 3.9 ; Reveal dépend
  de numpy, OpenCV, onnxruntime et Flask ;
- les deux domaines (retouche photo, montage vidéo) évoluent à des rythmes différents.

Contre-arguments acceptés :

- le pilote PhotoCraft existe en double (`montagia/photocraft.py` dans Rexo Studio,
  `shared/photocraft` ici) tant que Rexo Studio n'utilise pas `shared/` ;
- le studio aura deux applications au lieu d'une.

## Conséquences

- Les modèles sont déjà partagés : même dossier `~/.local/share/kdev-models`.
- Le scénario C reste ouvert, une fois Rexo rodé.

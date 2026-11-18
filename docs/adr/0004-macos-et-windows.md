# ADR 0004 — macOS et Windows, un seul moteur de vision

Date : 18/11/2026. Statut : accepté.

## Contexte

Les applications du hub ne tournaient que sur Mac : le détourage, les repères du visage, la
balance des blancs et les rendus de couleur passaient par Apple Vision et Core Image
(`rexo-segment`, en Swift), le lanceur était une application AppleScript, et plusieurs
fonctions appelaient `open`, `osascript`, `sips` ou la Corbeille du Finder. Or la plupart des
photographes à qui Rexo s'adresse travaillent sous Windows.

## Décision

Chaque application Rexo fonctionne sous macOS **et** sous Windows. Le MacBook sert au
développement, l'iMac au déploiement macOS, un PC Windows au déploiement Windows.

- **Un seul moteur de vision, le même sur les deux systèmes** (`shared/vision`), plutôt
  qu'Apple Vision sur Mac et autre chose sous Windows : une même photo donne le même résultat
  sur les trois machines (écart mesuré entre Mac et Windows : 0,7 niveau sur 255 en moyenne,
  la compression JPEG). Modèles ONNX sur le processeur : YuNet (visages), MediaPipe Face
  Mesh V2 (478 repères, iris compris), MODNet (détourage), MobileSAM guidé par les visages
  quand MODNet perd des personnes. Effets de Core Image refaits en numpy et OpenCV, réglés par
  mesure sur les résultats d'Apple.
- **Ce qui dépend du système est isolé** dans `shared/systeme.py` (Corbeille, ouvrir, choisir
  un dossier), `shared/photocraft` (emplacement de PhotoCraft) et `shared/lanceur`
  (application macOS, raccourci Windows).
- **Installation identique** : même Python autonome (python-build-standalone), mêmes
  paquets figés, avec les empreintes des roues Mac et Windows dans le même fichier.

## Conséquences

- Comparé à Apple Vision sur nos photos de test : pupilles mieux placées, menton plus bas
  d'environ 0,5 mm, masques identiques à 94–99 % sur les portraits ; meilleur que Vision sur
  une photo de groupe ancienne. Analyse plus rapide (3 s contre 4,5 s).
- Trois modèles de plus (31 Mo). YuNet est sous licence MIT mais entraîné sur WIDER Face, base
  réservée à la recherche : son usage commercial reste à vérifier avant toute vente.
- `rexo-segment` n'est plus utilisé par les applications du hub.
- Une fonction ne compte comme faite qu'après un essai sur le PC Windows.

# ADR 0003 — Une seule marque : Rexo

Date : 18/11/2026. Statut : accepté.

## Contexte

La suite portait quatre noms sans lien : **Rexo Studio** (première application, dépôt à
part), **RetoHub** (le hub), **Reveal** (retouche) et **Identité** (photos d'identité).
*Rexo* et *Reto* ne diffèrent que d'une lettre : on croit à une faute de frappe. Les noms
mêlaient trois langues (anglais, français, et l'arabe de l'interface), et rien ne rattachait
les applications au hub ni à Rexo Studio.

## Décision

Une seule racine, celle de la première application :

| Avant | Après |
|---|---|
| RetoHub (hub, dépôt) | **Rexo** |
| Rexo Studio | **Rexo Studio** (inchangé) |
| Reveal | **Rexo Reveal** |
| Identité | **Rexo ID** |

« ID » se comprend en français, en anglais et en arabe ; dans l'interface arabe, les noms de
marque restent en lettres latines. L'outil natif `reto-segment` devient `rexo-segment`.

Les noms techniques internes (`apps/reveal`, `apps/identite`, paquets Python `reveal` et
`identite`) ne changent pas : personne ne les voit, et les garder évite de casser les
chemins, les données et les tests.

## Conséquences

- Dépôt GitHub renommé (GitHub redirige l'ancienne adresse), dossier local renommé,
  environnements Python recréés.
- Applications macOS : `Rexo ID.app`, `Rexo Reveal.app` ; journaux dans
  `~/Library/Logs/Rexo` ; archive des clients par défaut dans `~/Pictures/Rexo ID`.
- Toute nouvelle application du hub s'appelle « Rexo <nom> ».

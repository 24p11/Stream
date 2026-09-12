# Session du 12 septembre 2026 (fin) — lot R3 : smoke de chaîne, librairie de fiches

À lire après `2026-09-12-lot-r2-retrait-ancien-monde.md`.

## Environnement (point 1)

- fictomed **0.1.0**, éditable depuis `~/Documents/fictomed`
  (`FICTOMED_SRC`), branche `prompt-work`, commit **`83ebca9`**
  (2026-08-05, « python 3.12 requis et plus 3.13 ») — à jour avec
  `origin/prompt-work`, aucun commit en attente côté Brest sur cette
  branche.

## Découverte bloquante — puis débloquée : la librairie de fiches a changé de format

La librairie `data/aphp/referentials/cards_library*` a été **resynchronisée**
(chapitres datés du 9 sept., dépôt local le 12) : chapitre V complet,
nouveaux codes (D50.8, Z37.x… en fiches exactes), index enrichi
(`type_mco`, `statut_mco`, `classe_generation`…) — mais l'index s'appelle
désormais **`_index.csv`**, alors que fictomed (toutes branches, `83ebca9`
compris) construit son registre depuis **`index.csv`** : premier smoke =
**zéro fiche servie** (55 codes « aucune fiche retrouvée »), pire que
l'épisode 05/06.

**Shim local appliqué** (réversible, dans le dossier de données non
versionné) : copie `_index.csv` → `index.csv` dans `cards_library/` et
`cards_library_categories/` — les colonnes utiles (`code`, `filepath`)
sont compatibles. **À refaire après chaque resync de la librairie**, tant
que fictomed ne lit pas `_index.csv` → point ajouté au message à Brest
(avec le wheel 0.1.2 cassé).

## Smoke de chaîne (point 2) — VERT après le shim

Répertoire scratch, aucun appel payant, profiles remplacé puis restauré
(mécanique `finally` standard). 6 candidats forcés couvrant les six codes
de l'épisode 05/06, chaîne `bench.scenarios` complète (config, génération
fictomed, `seed_user_prompts`) :

- 6 scénarios seedés, **56/56 codes avec fiche** dans les
  `user_generation.txt`, `ecrire_entrees_juge` : **0 `fiche: null`** ;
- les six codes de l'épisode servis en fiches **EXACTES** (plus aucun
  repli de catégorie nécessaire) : D508→D50.8, F101→F10.1, F1725→F17.25,
  F17202→F17.202, Z370→Z37.0, Z3711→Z37.11.

## Inventaire de la librairie (point 2 bis) — avant / après

| | avant (épisode 05/06) | après resync |
|---|---|---|
| fiches exactes à l'index | 16 058 annoncées / **14 874 présentes** | **15 282 / 15 282** (100 % cohérent) |
| chapitre V | **0/1060** | **1291/1291** |
| D50.8 | à l'index, fichier absent | à l'index, présent |
| catégories | présentes (index ancien) | 2054/2054 |

1 709 `.md` de plus sur disque hors index (16 991 au total) — filtrage
volontaire du nouvel index (`statut_mco`/`classe_generation`).

## Note de traçabilité (point 3)

**Les tests 01-06 ont été seedés sous des versions fictomed variables**
(PyPI 0.1.2 sans repli de fiches pour 05/06 au moins, ancienne librairie) —
`test.json` fait foi par test. Les fiches des tests figés ne sont pas
régénérées ; à partir du test 07, la chaîne consolidée (éditable vérifié
par l'assertion bootstrap + librairie resynchronisée + shim index) sert
toutes les fiches en exact.

## Prochaines étapes

1. Message à Brest (Rémi) : wheel PyPI 0.1.2 cassé (`regles_atih.yml`
   absent), **fictomed doit lire `_index.csv`** (nouveau format de la
   librairie de fiches), promotion du package enrichissement, doctrine
   E669x→E660x.
2. Test 07 sur la chaîne consolidée (fiches exactes attendues pour les
   codes tabac/alcool et Z37).
3. Relecture CRH 06 vs 05 et décisions en attente (statut alcool
   « occasionnel », puce CRO « Rappel clinique »).

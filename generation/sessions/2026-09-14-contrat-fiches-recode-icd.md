# Session du 14 septembre 2026 — conformité au contrat d'interface des fiches recode-icd

Suite de l'incident du 09/09 (`index.csv` → `_index.csv` non annoncé,
fiches cassées en silence, shim local du 12/09). Un CONTRAT d'interface
existe désormais côté producteur — source canonique, qui fait foi :
`docs/livraison/CONTRAT.md` sur `main` de 24p11/recode-icd (exemplaire
épinglé à la racine de chaque bibliothèque livrée ; ne pas le copier ici).

## Livraison consommée

`recode-icd_fiches_generation_33d89c0_atih-2025.tar.gz` (commit `33d89c0`,
kit `atih-2025`, `format_version` **1**), déployée dans
`data/aphp/referentials/cards_library*` : index canonique `index.csv`
(noyau `code`/`fichier`/`statut_mco`/`format_version`), `_index.csv`
déprécié encore présent (transition), `CONTRAT.md` embarqué.
15 282 fiches génération (15 071 émissibles, 211 `tronc_composition`),
2 097 catégories (+43 fiches de bloc/chapitre). Les six codes de
l'épisode 05/06 sont tous couverts.

## Shim retiré

Le shim du 12/09 (copie `_index.csv` → `index.csv`) a de fait disparu :
la livraison a remplacé les copies par de vrais `index.csv` au schéma
contrat. Aucun chemin de repli n'existait dans le code du dépôt, aucun
test du shim n'existait. **La consigne « refaire le shim après chaque
resync » (journal du 12/09) est RÉVOQUÉE** — l'index canonique est livré.

## Mise en conformité du dépôt (consommateur)

- **`bench/fiches.py`** : point d'accès UNIQUE aux bibliothèques —
  `charger_index` (index.csv seul, jamais `_index.csv`, noyau vérifié,
  refus bruyant si `format_version` > `FORMAT_VERSION_CONNUE` = 1, ou non
  constant), `codes_emissibles` (`classe_generation == "emissible"`,
  troncs exclus — composition via `recode-icd resoudre`),
  `codes_sans_fiche` (liste à journaliser, appariement pointé/compact,
  jamais de parcours du répertoire : l'index fait foi).
- **Notebook** : cellule « contrôle du contrat » après l'enrichissement —
  d'abord la **sonde du LECTEUR** (registre chargé par le code fictomed
  lui-même sur les chemins du servers.yaml courant, cohérence avec
  l'index à 10 % près : vérification de bout en bout, « le lecteur la
  lit ») avec message d'échec pointant le patch fichier/filepath
  (`4386ad5`) — validée dans les deux sens (verte sur le lecteur patché,
  RuntimeError sur le lecteur d'avant-patch) ; puis codes du pool sans
  fiche journalisés et codes ajoutés par l'enrichissement vérifiés
  émissibles. Sur le pool courant : 46 codes, 0 sans fiche, 5 ajoutés
  tous émissibles.
- **README** : section « Dépendance fiches recode-icd » (lien vers le
  contrat, version consommée, règle « mise à jour = décision explicite »).
- **Tests** (`test_bench_fiches.py`, 11) : chargement + noyau, refus sans
  `index.csv` (pas de repli sur `_index.csv`), noyau incomplet,
  `format_version` inconnu ou non constant, filtre émissible, `.md` hors
  index inexistant. 141 verts au total (+ l'échec préexistant de
  `test_pipelines`).

## fictomed (l'autre consommateur) — patch local à promouvoir

fictomed `83ebca9` lit bien `index.csv` mais joint sur `filepath`
(historique) : face au schéma contrat (`fichier`), **registre vide, zéro
fiche** — vérifié. Patch minimal dans le clone éditable
`~/Documents/fictomed` : `row.get("fichier") or row.get("filepath")`,
commit **`4386ad5`** sur `prompt-work`, complété du merge de
`origin/two_stages_generation` (2-gen, `e7e2e75`, sans conflit). Poussé
sur le fork `24p11/fictomed` (créé pour l'occasion) et proposé à Brest :
**PR CHU-Brest/fictomed#13**. Registre restauré : 15 111 exactes /
2 054 catégories, chaîne notebook rejouée verte jusqu'au contrôle du
contrat.

## Prochaines étapes

1. Message à Brest, enrichi : wheel PyPI sans `regles_atih.yml` ; **patch
   `4386ad5` à intégrer** (colonne `fichier` du contrat) ; promotion du
   package enrichissement ; doctrine E669x→E660x.
2. Test 07 sur la chaîne consolidée et conforme.
3. Décisions en attente (statut alcool « occasionnel », puce CRO
   « Rappel clinique »).

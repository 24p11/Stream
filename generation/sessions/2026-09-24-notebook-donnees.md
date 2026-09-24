# Session du 24 septembre 2026 (fin) — notebook d'inventaire des données

`generation/notebook_donnees.ipynb` : la carte d'identité exécutable de
chaque fichier de données important de la chaîne — documentation,
vérification à la demande, exploration libre. Aucune modification de
`bench/` ni des contrats : le notebook APPELLE l'existant
(`verifier_source`, `charger_index` / `codes_emissibles`, `deriver_agean`,
la `Politique` d'enrichissement, `charger_reference` du script de
substitution, le loader fictomed), il ne redéclare aucun schéma ni contrôle
(vérifié par grep : `SCHEMA_SOURCE =`, `Exigence(`, `COLONNES_REF =`,
`_PROFILE_RENAME`, `index.csv`… absents ; seule lecture directe, celle du
journal CSV).

## Structure

Intro (rôle, règle « ce qui fait foi reste les contrats et
`SCHEMA_SOURCE` — ce notebook les exécute »), cellule d'imports avec un
helper `present(chemin, comment_obtenir)` (tolérance : présent → taille,
absent → comment l'obtenir, jamais d'exception), puis huit fiches sur le
même gabarit : markdown (rôle / producteur et évolution / emplacement / ce
qui fait foi / consommation), cellule de chargement et statistiques,
cellule « Exploration » vide. 26 cellules dont 17 de code.

| Fiche | Fichier (chemin constaté) | Appelle |
|---|---|---|
| 1 | `data/aphp/scenarios_C1.parquet` et `_dp` | `verifier_source`, effectifs branche / typologie, taux de DP substitués par niveau, part enrichissable (`deriver_agean` + `Politique`) |
| 2 | `data/aphp/ref_substitution_imprecis.parquet` | `charger_reference` du script ; catégories, part d'imprécis, `nb`, `niveau`, dernier rapport |
| 3 | `data/aphp/referentials/dictionnaire_spe_racine.parquet` | loader fictomed (`specialty`) ; clé, sommes de ratios, couverture des racines de C1 |
| 4 | `mapping_type_unite.yaml` (**pas encore produit**) | valeurs `type_unite` de C1 par branche ; message d'obtention |
| 5 | librairie de fiches + `DEPLOIEMENT.txt` | `charger_index` ×2, `codes_emissibles`, classes, chapitres ; sonde du lecteur en commentaire (elle vit dans `verifier_environnement`) |
| 6 | référentiels fictomed annexes (`chu`, spécialités…) | `load_referentials` : état des 36 clés, aperçu `hospitals` / `specialty` |
| 7 | `generation/usage_log.csv` | existence, période, nb de runs — renvoi à `notebook_bilan_api.ipynb` |
| 8 | `generation/runs/06/0000` (test le plus récent) | fichiers du test et du scénario décrits, renvoi spec §2 / §3 / §7 |

## Constats du premier passage (ce poste)

- Tout présent sauf `mapping_type_unite.yaml` (la fiche liste les valeurs
  de C1 à couvrir : `null` sur toute la branche courte, `HC`, `GERIATRIE`,
  `NEONAT`, `SC`, `SC-NEONAT`, `HP` sur la longue).
- Part enrichissable de C1 (âge dérivé ≥ 18, hors préfixes O / Z94 / T86) :
  81,6 %.
- Référence de substitution : 1 273 catégories, 7 364 codes dont 1 510
  imprécis (20,5 %), **94 catégories sans aucun code précis** (les DP y
  sont conservés — 42 touchées dans C1).
- Dictionnaire des spécialités : 864 lignes, 624 racines, 55 spécialités,
  clé (racine, age, spécialité) unique, ratios sommant à 1 par (racine,
  age). Couverture de C1 : 707 191 / 715 417 racines non nulles ; la
  branche courte a `racine` nulle partout (372 108 lignes) — fictomed n'y
  trouvera pas de spécialité par cette jointure, alors que `ghm2[:5]` en
  couvrirait 367 044. Point à porter côté producteur ou loader.
- Librairie : livraison `33d89c0`, 15 282 fiches (15 071 émissibles,
  211 troncs), 2 097 catégories, `CONTRAT.md` épinglé.
- `usage_log.csv` : 14 lignes, un seul run (test 06, 6 septembre).

## Vérifications

- Rejeu jupyter_client complet sans clé : 0 erreur, fiches pleines.
- Tolérance : rejeu de toutes les fiches avec `DATA_APHP`, `REFERENTIALS`,
  `USAGE_LOG`, `TESTS_DIR` redirigés vers un dossier vide → 0 exception,
  un message d'obtention par fichier ; dossier de référentiels présent
  mais incomplet → le refus du loader fictomed est affiché, pas levé
  (il vérifie les CSV dès la construction).

## Prochaines étapes

1. Produire `mapping_type_unite.yaml` (statuts proposition / valide) —
   la fiche 4 le lira tel quel.
2. Décision sur la spécialité des séjours de la branche courte (racine
   nulle) avant le seeding d'une campagne.
3. Toujours en attente : âge exact de la branche courte, patch fictomed
   `age` / `cage`, test 07, message à Brest.

# Session du 24 septembre 2026 (suite) — dérivation d'`agean` depuis la classe d'âge

Complément du chantier « substitution des DP » : la chaîne n'attend plus
`agean` du producteur. L'âge exact est agrégé en classes (`cage`) dès
l'extraction (protection assumée) ; le contrat historique (utils.R v7,
l. 236/275) fabriquait `agean` en aval, reproduit ici côté Python.

## Livré

- **`bench/scenarios.py`** : `bornes_cage` (« [a-b[ » → a..b-1 ; « [0-1[ » →
  0 ; classe ouverte « [a-[ » → a..a+9, choix documenté par
  `LARGEUR_CLASSE_OUVERTE` ; libellé inattendu → `ValueError` explicite),
  `graine_ligne(cle, domaine="agean")` (sha256 tronqué, préfixe de domaine
  pour séparer les tirages DP / âge d'une même ligne, jamais `hash()`),
  `deriver_agean(df)` → `(df, DerivationAgean)` : tirage entier uniforme
  dans la classe (sha256 modulo largeur, biais < 2⁻⁵⁷), déterministe
  (deux passes, ordre mélangé, deux processus à `PYTHONHASHSEED` différents),
  même clé → même âge (variantes d'un scénario), `agean` numérique existant
  jamais écrasé, pivot `age` = `ge_18` / `lt_18` qui resserre l'intervalle
  d'une classe à cheval sur 18 ans (contradiction ignorée et comptée, autre
  valeur signalée sans effet), classes chevauchant 18 sans pivot consignées,
  classe nulle → `agean` nul compté. 1 087 525 lignes en ~2 s.
- **`bench/banc.py`** : `preparer_pool` appelle `deriver_agean` en PREMIER
  geste après `verifier_source` (la typologie et l'enrichisseur lisent l'âge
  final — même principe d'ordre que la substitution des DP) et imprime son
  rapport ; le récap final dit « agean dérivé de cage[, pivot age] » ou
  « lu du fichier ». `SCHEMA_SOURCE` : `agean` → statut `derivee`
  (numérique si présente, dérivée sinon, variable dérivée jamais confondue
  avec une donnée observée) ; `cage` (motif « [a-b[ », nuls interdits) et
  `id_scenario` (nuls interdits) → statut `derivation` : requises quand
  `agean` est absente, facultatives sinon — l'ancien format avec `agean`
  reste conforme (lecture retenue : Rémi demandait « obligatoires » et,
  dans le même souffle, la conservation d'un `agean` fourni ; rendre `cage`
  obligatoire même avec `agean` aurait mis `scenarios_bn_all` au rouge).
  `verifier_source` dérive `agean` à la volée pour calculer les types du
  rapport quand la typologie n'est pas fournie.
- **`enrichissement/integration_stream.py`** : renommage sans collision —
  un corpus de campagne porte déjà `cage` ; `age` (pivot) est garé sous un
  nom neutre le temps de l'enrichissement puis restauré (sinon
  `DuplicateError` polars, ou l'âge numérique masqué). Fichier hors
  livrable fictomed.
- Tests : 30 nouveaux (bornes, dérivation, déterminisme en deux processus,
  non-écrasement, pivot, chevauchement consigné, schéma, récap du pool,
  collision `cage`) — suite complète 244 verts + l'échec préexistant.

## Vérification finale

- `verifier_source(scenarios_C1.parquet)` : **conforme** (signalement
  « agean absente : DÉRIVÉE de cage »), idem `scenarios_C1_dp.parquet` ;
  `scenarios_bn_all_20260128.pq` toujours conforme.
- `preparer_pool("scenarios_C1.parquet", "couverture", 42)` : 3,2 s ;
  « agean : dérivé de cage, pivot age — 1087525/1087525 lignes », typologie
  fournie conservée, filtre DP en 8 → 128 057, 16 modalités, 16 séjours,
  enrichissement 8/16 (4 exclus O, 4 mineurs — donc le pivot joue son rôle
  dans la Politique), 74 codes, 2 sans fiche journalisés (`NA`, `X3100`),
  codes ajoutés émissibles, récap « agean dérivé de cage, pivot age ».

## Constats C1 (à connaître)

- **Branche courte : `age` est l'âge exact en chaîne** (372 108 lignes,
  0 à 95), cohérent avec `cage` sauf dans « [80-[ » (âges réels jusqu'à 95,
  la dérivation plafonne à 89). Aujourd'hui sans effet (signalé « pivot
  hors ge_18 / lt_18 ») : la dérivation tire dans la classe partout, comme
  spécifié. Si cet âge exact est fiable, l'utiliser tel quel sur la branche
  courte serait plus fidèle qu'un tirage — décision à prendre, pas prise.
- Branche longue : pivot `ge_18` / `lt_18` parfaitement cohérent avec
  `cage` ; aucune classe de C1 ne chevauche 18 ans (« [15-18[ » puis
  « [18-30[ ») — le resserrement ne joue pas sur C1, il est prêt pour
  d'autres grilles.
- `cage` est unique par `id_scenario` : même âge pour toutes les variantes
  d'un scénario, cohérent avec la décision « un scénario = un cas clinique ».
- **Pour le seeding sur C1 (hors périmètre ici)** : le loader fictomed
  renomme `age` → `cage` sans test de collision (`_safe_rename`) ; avec la
  colonne `cage` du corpus, polars lèvera une erreur de doublon. Patch
  fictomed à prévoir avant le premier `seeder` sur une campagne (à ajouter
  au message à Brest, comme `4386ad5`).

## Question consignée (aucune action)

Si la revue des CRH trouve les âges uniformes peu crédibles dans certaines
classes (pédiatrie fine, très grand âge : « [80-[ » plafonné à 89 alors que
la branche courte montre des 95 ans), une référence exportable de
distribution d'âge intra-classe pourrait être ajoutée côté producteur —
décision ultérieure, l'uniforme d'abord.

## Prochaines étapes

1. Décision sur l'âge exact de la branche courte (tirer ou lire).
2. Patch fictomed `age` / `cage` avant le seeding d'une campagne ; test 07.
3. Message à Brest (wheel 0.1.2, `4386ad5`, collision `age`/`cage`,
   promotion enrichissement, doctrine E669x→E660x).

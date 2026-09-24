# Session du 24 septembre 2026 — substitution des DP imprécis (étape fichier → fichier)

Chantier amont du banc : `scripts/substituer_dp_imprecis.py` remplace les
DP « sans précision » d'un corpus de campagne (projet amont
scenarios_bn_pmsi) par un code précis de la même catégorie, tiré au sort
pondéré par les effectifs réels de la référence
`ref_substitution_imprecis.parquet`, sauf séjours UHCD ; DAS intouchés.
Aucun appel payant, `bench/` inchangé hors `SCHEMA_SOURCE`.

## Architecture

- Script autonome, `corpus.parquet --ref ref.parquet [--out corpus_dp.parquet]`
  (défaut `<corpus>_dp.parquet`, rapport `<out sans extension>.rapport.txt`).
  Le notebook n'a rien à savoir : `SOURCE_PROFILES_PATH` pointe le fichier
  de sortie, `verifier_source` le contrôle comme toute source. La
  substitution précède TOUT (typologie, filtres, enrichissement) : par
  construction, l'enrichisseur voit le DP substitué (E11 → corpulence
  diabétique, exclusions Z94/T86/O, E66 → contrainte IMC).
- Règle : DP hors liste des imprécis → rien ; `type_unite == "UHCD"` →
  conservé et compté ; sinon tirage pondéré par `nb` parmi les codes précis
  de la même `cat`, strate (cage, sexe), repli (cat, sexe) puis (cat) ; sans
  candidat précis → conservé et compté. `niveau` (CMA) non utilisé, les
  effectifs sont sommés dessus.
- Déterminisme : graine par ligne = sha256 de `str(id_scenario)` tronqué
  (jamais `hash()` natif, salé par processus) ; `numpy.random.Generator`
  pour le tirage. Vérifié : ordre des lignes mélangé → sorties égales ;
  deux processus avec `PYTHONHASHSEED` différents → parquets bit à bit
  identiques.
- Traçabilité : colonnes d'entrée inchangées sauf `diag2` ; ajoutées
  `dp_origine`, `dp_substitue`, `repli_substitution` (0/1/2, nul sinon).
  Rapport par branche (lignes, imprécis rencontrés, substitués par niveau,
  conservés UHCD, conservés faute de candidat), constats, note de
  cohérence DP/GHM (le `ghm2` a été groupé sur le DP d'origine — compromis
  écrit, même doctrine que les codes ajoutés par l'enrichissement). Aucun
  contrôle de fiches ici : les codes substitués sont observés du PMSI réel,
  le contrat recode-icd s'applique en aval dans `preparer_pool`.
- `SCHEMA_SOURCE` : `id_scenario`, `branche`, `cage`, `type_unite`,
  `dp_origine`, `dp_substitue` (booléen), `repli_substitution` reconnues
  comme facultatives documentées ; `agean` reste obligatoire (`cage` est
  une classe d'âge, pas l'âge numérique).

## Constats sur le vrai corpus (`scenarios_C1.parquet`, 1 087 525 lignes)

- **La référence n'est pas sur ce poste** : pas de rapport réel de
  substitution. Smoke du script sur le corpus avec une référence vide :
  2,2 s, constats réels ci-dessous, sortie 38 colonnes.
- **`type_unite` est nulle sur toute la branche « court »** (372 108
  lignes) : règle par défaut, on substitue — un court programmé n'est pas
  une UHCD. Sur « long » (715 417 lignes), valeurs `GERIATRIE`, `HC`, `HP`,
  `NEONAT`, `SC`, `SC-NEONAT` : **aucune valeur `UHCD` dans tout le
  corpus**, l'exemption est sans objet sur C1 tel que livré. À poser au
  producteur : les séjours UHCD sont-ils dans « court » (type nul) ?
- **`id_scenario` n'est pas unique par ligne** : 474 077 valeurs pour
  1 087 525 lignes (jusqu'à 77 lignes par identifiant). Les lignes qui le
  partagent ne diffèrent que par `duree`, `mode_entree`, `mode_sortie`,
  `mdp` (variantes de contexte de séjour d'un même scénario : DP, DAS,
  cage, sexe identiques). Choix : graine sur `id_scenario` tel que demandé
  → même substitution pour toutes les variantes d'un scénario (cohérent :
  un scénario, un DP final ; déterministe). Alternative si l'on voulait
  diversifier le DP entre variantes : clé composite
  (`id_scenario`, `duree`, `mode_entree`, `mode_sortie`, `mdp`), toutes
  les lignes étant distinctes sur l'ensemble des colonnes. À trancher.
- `cage` du corpus : tranches `[0-1[` … `[80-[` ; la référence devra
  utiliser le même encodage (le rapport avertit si aucune substitution
  n'atteint le niveau 0).
- Rappel : C1 reste non conforme à `verifier_source` (pas d'`agean`), à
  corriger côté producteur — hors périmètre.

## Tests (21, tous verts ; suite complète 214 + l'échec préexistant de `test_pipelines`)

Proportions du tirage sous graine (2 000 patients, 75 % / 25 % à ±4),
exemption UHCD (insensible à la casse), repli à chaque niveau tracé,
conservation faute de candidat, DP précis intouché, court sans
`type_unite` substitué, DAS et colonnes d'entrée intouchés, jamais de code
hors référence, déterminisme (ordre mélangé, deux processus, mêmes
identifiants → même substitution), effectif nul ignoré, CLI (sortie et
rapport par défaut, erreurs), `verifier_source` (nouvelles colonnes
reconnues, fichier sans elles conforme, type inattendu détecté).

## Questions consignées (aucune action en v1)

1. `niveau` (sévérité CMA) comme critère « à sévérité comparable » : v2
   possible, à valider cliniquement.
2. DAS imprécis : hors périmètre par décision ; la même référence servirait.
3. Probabilité de conservation aux urgences hors UHCD (entrée urgences,
   hospitalisation classique) : 0 en v1 ; réglable si la revue clinique
   des CRH le demande.

## Décisions Rémi (24 septembre, consignées)

- **C1 ne contient aucun séjour UHCD.** Ils arriveront en campagne 2, avec
  `type_unite` renseigné sur la branche courte. Sur C1 la substitution
  s'applique donc uniformément : le compteur « conservés UHCD » du rapport
  doit valoir **0**, toute autre valeur serait une anomalie.
- **Clé de graine = `id_scenario`, voulu** : un scénario = un cas
  clinique ; ses variantes de contexte (durée, modes) partagent le DP
  final, par construction de la graine. L'alternative « clé composite »
  n'est pas retenue.

Les deux décisions sont inscrites dans la docstring du script.

## Prochaines étapes

1. Déposer `ref_substitution_imprecis.parquet` sur le poste, lancer le
   script sur C1, lire le rapport (niveaux de repli, codes conservés,
   « conservés UHCD » attendu à 0).
2. Puis, toujours en attente : `agean` pour C1, test 07, message à Brest.

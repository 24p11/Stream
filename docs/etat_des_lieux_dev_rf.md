# État des lieux du projet Stream — branche `dev_rf`

*Rédigé le 2026-08-12, à partir de la branche `notion` (commit `339b2b4`).*

Stream génère des comptes rendus d'hospitalisation (CRH) synthétiques à partir de
statistiques PMSI et de LLM. Deux modes d'utilisation coexistent :

1. **Le pipeline CLI** (`stream <pipeline> --client ...`) : orchestration
   `cli.py` → `runner.py` → `pipelines/{brest,aphp}` avec les scénarios produits
   par `fictomed`.
2. **Le banc d'essai notebook** (`work_modif_prompts/`) : workflow expérimental
   AP-HP pour comparer la génération en 1 étape (CR direct) et en 2 étapes
   (résumé clinique puis CR), avec édition manuelle des prompts entre les étapes.

---

## 1. Arborescence et rôle des modules

```
Stream/
├── cli.py                  # Point d'entrée CLI (argparse) → runner.run()
├── runner.py               # Orchestration : config YAML → fictomed.generate() → pipeline.get_report()
├── core/
│   ├── config.py           # load_config() : lecture YAML (11 lignes)
│   ├── logger.py           # get_logger() : logger console
│   └── clients.py          # Clients LLM normalisés sur une interface chat() commune :
│                           #   AnthropicClient, MistralClient (+ batch_chat), OllamaClient,
│                           #   get_client() (fabrique à partir de servers.yaml)
├── pipelines/
│   ├── pipeline.py         # BasePipeline (ABC) : check_data/load_data/get_fictive/
│   │                       #   get_scenario/get_report + flush_batch() + REPORT_SCHEMA
│   ├── fictive.py          # generate_fictive_stays() : wrapper générique de tirage
│   ├── scenario.py         # format_scenarios() : wrapper générique de mise en forme
│   ├── report.py           # generate_reports() : boucle LLM commune + flush Parquet par lots
│   ├── brest/              # Pipeline Brest : tirage pondéré DP/CCAM/DAS/DMS dans Stream
│   └── aphp/               # Pipeline AP-HP : coquille mince — la génération de scénarios
│                           #   est déléguée à fictomed ; get_report() propose un mode
│                           #   "direct" (tous clients) et "mistral_batch" (historique AP-HP)
├── config/
│   ├── prompts.yaml        # System prompts par pipeline
│   └── servers.example.yaml# Modèle de configuration (à copier en servers.yaml)
├── scripts/notion/
│   └── export_reports_to_notion.py   # Export des CR générés vers Notion pour évaluation
├── tests/
│   └── test_pipelines.py   # Seul fichier de tests (voir §4)
└── work_modif_prompts/     # Banc d'essai AP-HP 1 gen / 2 gen (hors package)
    ├── aphp_generation_utils.py                       # 1 652 lignes, ~30 fonctions
    ├── notebook_generation_aphp_1gen_2gen_refactored.ipynb
    ├── template_one_unique_gen/    # System prompts « 1 génération » (1 .txt par template_name)
    ├── template_first_gen/         # System prompts « étape 1 : résumé clinique »
    └── template_second_gen/        # System prompts « étape 2 : CR à partir du résumé »
```

Points notables sur l'organisation :

- `work_modif_prompts/` est **hors du package** : le notebook charge
  `aphp_generation_utils.py` par manipulation de `sys.path` + `importlib.reload`,
  pas via une installation. Le module est volontairement sans configuration
  (tout est paramétré depuis le notebook), mais il duplique une partie de la
  logique de `core/clients.py` (voir §3.6).
- `pipelines/aphp/` côté CLI et `work_modif_prompts/` côté notebook constituent
  **deux chemins de génération AP-HP parallèles** qui ne partagent que
  `core.clients.MistralClient` (et encore, le notebook contourne son API, §3.6).
- Le dossier `data/` attendu par le notebook (`data/aphp/…`) **n'est pas versionné
  et absent de ce poste** : `find_stream_root()` exige `data/aphp` pour
  reconnaître la racine du projet, donc le notebook ne démarre pas sans ces
  données (voir §3.5).

---

## 2. Workflow du notebook `generation_aphp_1gen_2gen_refactored`

### 2.1 Chaîne des cellules et dépendances

Le notebook est strictement séquentiel : chaque cellule de code consomme des
variables globales définies par les précédentes.

| Cellule | Rôle | Produit (variables globales) | Dépend de |
|---|---|---|---|
| 2 | Bootstrap : `sys.path`, import + reload de `utils`, détection racine | `utils`, `PROJECT_ROOT`, `NOTEBOOK_DIR`, `DEPENDENCIES_DIR`, `FICTOMED_*` | — |
| 4 | Installation fictomed (clone git + pip editable) et vérification | `FICTOMED_INSTALLATION` | 2 |
| 6 | Configuration du run + création de l'arborescence | `RUN_DIR`, `PATHS`, `SOURCE_PROFILES_PATH`, `TARGET_N`, `CANDIDATE_POOL_SIZE`, dossiers de templates | 2 |
| 8 | Définition des filtres | `SOURCE_FILTERS`, `SCENARIO_FILTERS` | — |
| 10 | Lecture/filtrage/échantillonnage des profils source | `candidate_source` (+ `source_df`, `source_filtered`) | 6, 8 |
| 12 | Écriture du `servers.yaml` de fictomed | `FICTOMED_CONFIG_PATHS` | 6 |
| 14 | Génération fictomed + sélection finale | `selected_scenarios` (+ parquet `scenarios_fictomed_selected.parquet`) | 4, 10, 12 |
| 16 | Création des fichiers de prompts + manifest | `manifest` (+ parquet `manifest.parquet`, fichiers `.txt`) | 14 |
| 18 | Prévisualisation des prompts | — | 16 |
| — | *(édition manuelle éventuelle des `.txt` sur disque)* | | |
| 20 | Configuration Mistral (mode, modèle, tarifs, clé) | `GENERATION_MODE`, `MODEL`, `MAX_TOKENS_*`, `MISTRAL_API_KEY`, préfixes et encarts résumé | — |
| 22 | Exécution Mistral + bilan tokens/coûts | `GENERATION_RESULTS` | 6, 16 (via disque), 20 |
| 24 | Visualisation d'un scénario et de ses sorties | — | 22 (via disque) |

Deux remarques structurelles :

- À partir de la cellule 22, l'état passe **par le disque** et non par les
  variables : `run_generation_workflow()` recharge
  `scenarios_fictomed_selected.parquet` et `manifest.parquet` via `load_state()`.
  On peut donc redémarrer le kernel et relancer directement 2 → 6 → 20 → 22 sur
  un run existant — c'est le mécanisme qui permet l'édition manuelle des prompts.
- La cellule 6 recrée l'arborescence (`create_run_tree`) à chaque exécution ;
  c'est elle qui garantit l'existence de `sorties/` pour la cellule 22 (voir §3.4).

### 2.2 Fonctions de `aphp_generation_utils.py` utilisées, par étape

**Bootstrap et installation** (cellules 2 et 4)
- `find_stream_root()` / `looks_like_stream_root()` — détection de la racine.
- `install_or_update_fictomed()` — clone/pull de la branche `prompt-work` de
  fictomed puis `python -m pip install --editable`, purge de `sys.modules`.
- `verify_fictomed_installation()` — vérifie branche git et chemin d'import.
- `run_command()` — sous-jacent aux deux précédentes (subprocess + trace).

**Préparation des données** (cellules 6 à 14)
- `create_run_tree()` — crée les 10 dossiers du run et renvoie le dict `PATHS`.
- `prepare_source_candidates()` — `resolve_parquet_path()` + lecture Parquet,
  ajout de `source_row_id`/`source_scenario_id`, `apply_filters()`
  (via `build_filter_expr()`, 14 opérateurs), échantillonnage.
- `write_fictomed_config()` — écrit le `servers.yaml` consommé par fictomed.
- `generate_and_select_fictomed_scenarios()` — sauvegarde le `profiles` actif,
  le remplace par `candidate_source`, appelle `fictomed.generate()`, restaure
  dans un `finally`, filtre (`apply_filters`) et sélectionne `TARGET_N` scénarios.

**Prompts** (cellules 16 et 18)
- `create_prompt_files()` — écrit les 6 familles de `.txt`
  (system/user × une_gen/première/deuxième) avec `write_text()`/`safe_stem()`,
  copie les templates, écrit `manifest.parquet`.
- `preview_prompt_files()` — relit le manifest et affiche les 6 prompts d'une ligne.

**Exécution Mistral** (cellule 22) — orchestrée par `run_generation_workflow()` :
- `load_state()` — recharge scénarios + manifest depuis le disque.
- `load_stage_prompts()` — relit les `.txt` (éventuellement édités), gère le
  préfixe assistant (`original`/`first`/`empty`) et l'injection du résumé de
  l'étape 1 dans le user prompt de l'étape 2 (encarts header/footer).
- `run_mistral_batch()` — construit le JSONL, upload, création et polling du
  batch job, téléchargement/parsing des sorties
  (`_parse_batch_jsonl`, `_message_content_to_text`, `_error_to_text`,
  `_normalise_batch_status`, `_read_downloaded_file`, `_object_get`),
  jointure des réponses sur `generation_id`.
- `reports_to_map()` — transforme les résumés de l'étape 1 en mapping
  `generation_id → texte` pour l'étape 2.
- `validate_reports()` — exhaustivité des IDs, sorties vides, erreurs batch.
- `save_individual_outputs()` — un `.txt` par CR/résumé dans `sorties/`.
- `calculate_and_print_usage()` / `combine_and_print_usage()` /
  `format_token_count()` — bilans tokens et coûts, écrits dans
  `sorties/mistral_token_usage_and_cost.json`.

**Visualisation** (cellule 24)
- `visualize_run_outputs()` — affiche scénario + CR 1gen + résumé + CR 2gen.

Le mode `two` enchaîne : `load_stage_prompts(first)` → batch résumés →
`validate` → `load_stage_prompts(second, summaries=reports_to_map(résumés))` →
batch CR → `validate`. Le mode `both` ajoute la branche `one` et un total global.

---

## 3. Points de fragilité identifiés

### 3.1 `install_or_update_fictomed` — pip et conflit d'installations ⚠️ critique

[aphp_generation_utils.py:172-181](work_modif_prompts/aphp_generation_utils.py#L172-L181)
exécute `{sys.executable} -m pip install --editable <clone>`. Deux problèmes,
**vérifiés sur ce poste** :

1. **pip est absent des venv créés par uv.** Le `.venv` du projet ne contient
   pas de module pip (`.venv/bin/python -m pip` → `No module named pip`). Si le
   kernel Jupyter tourne sur ce venv — cas nominal avec le groupe dev
   `ipykernel` fraîchement ajouté à `pyproject.toml` — la cellule 4 échoue
   systématiquement.
2. **Triple installation de fictomed en conflit.** Coexistent actuellement :
   - la dépendance `fictomed>=0.1.1` de `pyproject.toml`, verrouillée en
     **0.1.2 PyPI** dans `uv.lock` ;
   - une installation **editable déjà présente** dans le venv pointant vers
     `/Users/remi/Documents/fictomed` (checkout local indépendant, installé via
     `__editable__.fictomed-0.1.2.pth`) ;
   - le clone que le notebook veut installer en editable :
     `work_modif_prompts/_dependencies/fictomed_prompt_work` (branche `prompt-work`).

   Chaque `uv sync` réinstallera la version PyPI par-dessus l'editable ; chaque
   exécution de la cellule 4 fera l'inverse. `verify_fictomed_installation()`
   détecte le problème a posteriori (bon point), mais la boucle
   installation/écrasement reste non résolue. La purge de `sys.modules`
   (lignes 190-192) ne suffit d'ailleurs pas toujours : les objets déjà créés
   par l'ancien module restent vivants, seul un redémarrage du kernel est sûr.

### 3.2 `load_stage_prompts` — pertes silencieuses avant l'appel API ⚠️ critique

Trois défauts dans [aphp_generation_utils.py:773-851](work_modif_prompts/aphp_generation_utils.py#L773-L851) :

- **Join inner silencieux** (ligne 843) :
  `scenarios.join(prompt_df, on="generation_id", how="inner")`. Si le manifest
  et `scenarios_fictomed_selected.parquet` divergent (run partiellement
  régénéré, manifest recréé après une nouvelle sélection, fichier édité à la
  main), les scénarios sans correspondance **disparaissent sans erreur ni
  message** — le batch part avec moins de lignes que prévu.
  `validate_reports()` rattrape le coup *après* le batch (IDs manquants), mais
  l'anomalie devrait être détectée *avant* de payer l'appel API, et le
  message d'erreur actuel ne pointe pas la cause.
- **`summaries.get(generation_id, "")`** (ligne 804) : à l'étape 2, un résumé
  absent est remplacé par une chaîne vide. Le CR de deuxième génération est
  alors produit avec un encart « RÉSUMÉ CLINIQUE » **vide entre header et
  footer**, sans aucune alerte — dégradation de qualité indétectable en aval.
  (En pratique `validate_reports` sur l'étape 1 réduit le risque, mais la
  fonction reste permissive si elle est réutilisée hors de ce chemin.)
- **`read_text(encoding="utf-8")` sans gestion d'erreur** (lignes 796-801) : un
  `.txt` édité à la main et sauvegardé en Latin-1/CP-1252 (éditeur Windows,
  copier-coller) lève un `UnicodeDecodeError` brut, sans indiquer **quel
  fichier** est en cause parmi les centaines du run.

### 3.3 Manifest — chemins non portables (séparateurs Windows) ⚠️

[create_prompt_files](work_modif_prompts/aphp_generation_utils.py#L705-L710)
stocke `str(path.relative_to(run_dir))` dans le manifest. `str()` d'un `Path`
utilise le séparateur de l'OS : un manifest écrit sous Windows contient
`prompts\une_gen\system_prompt\0000__....txt`. Relu sous macOS/Linux
(`run_dir / str(item[system_key])` dans `load_stage_prompts`,
`preview_prompt_files`), le backslash est traité comme un caractère ordinaire
du nom de fichier → `FileNotFoundError` sur tout run transféré entre OS.
Le correctif standard est `path.relative_to(run_dir).as_posix()` à l'écriture
(et, en lecture, tolérer les manifests existants en remplaçant `\` par `/`).

### 3.4 Écritures dans `run_dir/sorties/` sans `mkdir` préalable ⚠️

`run_generation_workflow()` écrit directement :
- [reports_1gen.parquet](work_modif_prompts/aphp_generation_utils.py#L1452)
- [resumes_2gen.parquet](work_modif_prompts/aphp_generation_utils.py#L1496)
- [reports_2gen.parquet](work_modif_prompts/aphp_generation_utils.py#L1540)
- [mistral_token_usage_and_cost.json](work_modif_prompts/aphp_generation_utils.py#L1567)

sans jamais créer `run_dir/sorties/`. Cela fonctionne aujourd'hui **uniquement
parce que** la cellule 6 appelle `create_run_tree()` dans la même session (qui
crée `sorties/CR_1gen` et `sorties/resume_CR_2gen`, donc `sorties/` par effet
de bord). Toute réutilisation de `run_generation_workflow()` hors notebook, ou
un `run_dir` pointé vers un run dont `sorties/` a été nettoyé, échoue en
`FileNotFoundError` **après** que le batch Mistral a été payé — le pire moment.
À noter : `save_individual_outputs()` et `run_mistral_batch()` font, eux,
correctement leur `mkdir(parents=True, exist_ok=True)`.

### 3.5 Autres fragilités relevées

- **Détection de racine couplée aux données** : `looks_like_stream_root()`
  exige `data/aphp`, dossier non versionné (absent sur ce poste). Un clone
  frais du dépôt n'est pas reconnu comme racine ; le message d'erreur oriente
  vers `PROJECT_ROOT_OVERRIDE` mais la vraie cause (données manquantes) n'est
  pas explicitée.
- **Clé API dans le notebook** : cellule 20, `MISTRAL_API_KEY = "xxx"` à
  compléter en dur, alors que la note de bas de page du notebook demande
  explicitement de passer par la variable d'environnement. Risque de commit de
  clé ; le message d'erreur de `run_generation_workflow` (« définissez-la dans
  la cellule précédente ») encourage la mauvaise pratique.
- **Mutation temporaire du `profiles` partagé**
  ([generate_and_select_fictomed_scenarios](work_modif_prompts/aphp_generation_utils.py#L531-L547)) :
  le fichier `profiles` de `data/aphp` est remplacé puis restauré dans un
  `finally` — correct en nominal, mais un crash kernel/machine entre les deux
  laisse les données sources corrompues (le backup existe dans `_backups`, la
  restauration est alors manuelle). Un vrai répertoire d'entrée par run éviterait
  toute écriture dans les données partagées.
- **`run_mistral_batch` contourne l'abstraction** : accès direct à
  `client._client` (attribut privé de `MistralClient`,
  [ligne 1119](work_modif_prompts/aphp_generation_utils.py#L1119)) et
  réimplémentation quasi complète de `MistralClient.batch_chat()` (polling,
  parsing JSONL, gestion des erreurs) avec des différences subtiles
  (`_read_downloaded_file` vs itération sur `output_file.stream`). Deux parseurs
  de batch JSONL à maintenir en parallèle.
- **Polling sans timeout** : les boucles de polling
  ([utils :1139](work_modif_prompts/aphp_generation_utils.py#L1139),
  [core/clients.py:162](core/clients.py#L162)) tournent indéfiniment si un job
  reste `QUEUED` ; aucun mécanisme d'annulation du job en cas d'interruption.
- **`custom_id` positionnel** : le batch utilise l'index de ligne comme
  `custom_id` puis rejoint sur `generation_id` — correct tant que l'ordre de
  `prompt_df` ne change pas entre construction et parsing, mais fragile ;
  utiliser `generation_id` comme `custom_id` supprimerait la classe d'erreur.
- **`pipelines/aphp/pipeline.py` : `system_prompt=""`**
  ([ligne 110](pipelines/aphp/pipeline.py#L110)) passé à `generate_reports` en
  mode direct — à vérifier : si les scénarios fictomed portent leur propre
  system prompt c'est voulu, mais rien ne le documente.
- **`tests/__init__.py` présent** avec `pytest.ini` configuré en
  `python_files = tests/*.py` : configuration inhabituelle qui fait de `tests`
  un package importable ; le Makefile ajoute `--doctest-modules` alors que les
  modules n'ont pas de doctests — source de lenteur/bruit.

---

## 4. État des tests

**Un seul fichier de tests : [tests/test_pipelines.py](tests/test_pipelines.py) (106 lignes, 5 tests).**

Couvert (superficiellement — essentiellement des smoke tests d'instanciation) :
- Instanciation de `BrestPipeline` et `APHPPipeline` (`name` correct).
- `BrestPipeline.check_data()` avec des CSV minimaux (conversion CSV → Parquet).
- `APHPPipeline.check_data()` crée le dossier de sortie.
- Enregistrement des deux pipelines dans `runner.PIPELINES`.

Non couvert :
- **`work_modif_prompts/aphp_generation_utils.py` : 0 test** pour 1 652 lignes,
  alors que c'est le code le plus complexe et le plus utilisé du moment. Sont
  pourtant très testables sans réseau ni fictomed : `build_filter_expr` /
  `apply_filters` (14 opérateurs, `exclude`, `fill_null`), `safe_stem`,
  `create_run_tree`, `create_prompt_files` + manifest (dont la portabilité des
  chemins, §3.3), `load_stage_prompts` (join, résumés, préfixes),
  `_parse_batch_jsonl`, `_message_content_to_text`, `validate_reports`,
  `calculate_and_print_usage` / `combine_and_print_usage`, `load_state`.
- **`core/clients.py` : 0 test** — normalisation des messages Anthropic
  (extraction du system), parsing de `batch_chat`, `get_client`.
- **`core/config.py`, `runner.py`, `cli.py`** : 0 test (le parsing argparse et
  le mapping des arguments seraient triviaux à couvrir).
- Les chemins de génération eux-mêmes (`get_report`, `generate_reports`,
  modes `direct` vs `mistral_batch`) — nécessiteraient des clients mockés,
  aucun mock n'existe.
- Aucune mesure de couverture, pas de CI visible dans le dépôt.

---

## 5. Propositions d'optimisation priorisées

### Quick wins (faible effort, gain immédiat)

1. **Portabilité du manifest** : `as_posix()` à l'écriture dans
   `create_prompt_files`, normalisation `\` → `/` à la lecture dans
   `load_stage_prompts`/`preview_prompt_files`. ~5 lignes, supprime le §3.3.
2. **`mkdir` des sorties dans `run_generation_workflow`** : un
   `(run_dir / "sorties").mkdir(parents=True, exist_ok=True)` en tête de
   fonction. 1 ligne, supprime le §3.4.
3. **Join contrôlé dans `load_stage_prompts`** : vérifier avant jointure que
   les `generation_id` du manifest et des scénarios coïncident, et lever une
   erreur listant les IDs orphelins ; passer `summaries.get(...)` en accès
   strict (erreur si résumé manquant, ou au minimum warning explicite + liste
   des IDs concernés). Évite de payer un batch faussé.
4. **`read_text` enveloppé** : petit helper `read_prompt_file(path)` qui
   attrape `UnicodeDecodeError`/`OSError` et relance avec le chemin du fichier
   fautif dans le message.
5. **Remplacer pip par `uv pip`** dans `install_or_update_fictomed` : détecter
   `shutil.which("uv")` et utiliser `uv pip install --python {sys.executable} -e ...`,
   avec repli sur `python -m pip` s'il existe. Corrige la moitié du §3.1.
6. **Clé API** : supprimer l'affectation en dur de la cellule 20 au profit de
   `os.getenv("MISTRAL_API_KEY")` (le message d'erreur de
   `run_generation_workflow` est déjà presque bon).
7. **`custom_id = generation_id`** dans `run_mistral_batch` au lieu de l'index
   positionnel.
8. **Timeout de polling** (paramètre `max_wait_seconds`) dans les deux boucles
   de batch.

### Refactorings (effort moyen, à planifier)

9. **Clarifier la stratégie fictomed** (l'autre moitié du §3.1) : choisir une
   source unique — soit la dépendance `pyproject.toml` (éventuellement en
   `[tool.uv.sources] fictomed = { git = ..., branch = "prompt-work" }`), soit
   l'editable local — et faire de la cellule 4 une simple *vérification*
   (version/branche attendue) plutôt qu'une installation. Supprime le conflit
   uv sync ↔ pip install et le besoin de purger `sys.modules`.
10. **Réunifier la couche batch Mistral** : faire porter le format « avec
    usage » par `MistralClient.batch_chat()` (tokens, finish_reason, fichiers
    d'erreurs, sauvegarde des JSONL) et faire consommer cette API par
    `run_mistral_batch`, qui ne garderait que la construction du DataFrame.
    Un seul parseur JSONL à maintenir, plus d'accès à `client._client`.
11. **Extraire `aphp_generation_utils.py` en package testable** : le fichier
    mélange installation (git/pip), données (filtres), fichiers (prompts,
    manifest), API (batch) et affichage (IPython). Le scinder en modules purs
    (ex. `stream.bench.filters`, `.manifest`, `.batch`, `.usage`) importables
    depuis le projet, le notebook ne gardant que l'orchestration et l'affichage.
    C'est le prérequis pour le point 12.
12. **Suite de tests sur la logique pure** (cf. §4) : filtres, manifest
    aller-retour (y compris cas Windows), `load_stage_prompts` avec run
    fabriqué en `tmp_path`, `_parse_batch_jsonl` sur des JSONL de référence
    (succès, erreur, usage manquant), `validate_reports`. Aucun réseau
    nécessaire ; viser d'abord les fonctions listées comme fragiles.
13. **Isoler les entrées fictomed par run** : générer dans un dossier d'entrée
    temporaire propre au run plutôt que de remplacer/restaurer le `profiles`
    partagé de `data/aphp` (si fictomed le permet via sa config — le
    `servers.yaml` par run existe déjà, il ne manque que l'input).
14. **Hygiène mineure** : nettoyer `pytest.ini` (`testpaths` plutôt que
    `python_files`), retirer `--doctest-modules` du Makefile ou ajouter de
    vrais doctests, documenter le `system_prompt=""` de
    `pipelines/aphp/pipeline.py`, ajouter une CI minimale (pytest sur push).

Ordre suggéré : 1-8 en une seule passe courte (aucun changement de
comportement nominal, uniquement des garde-fous), puis 9 et 10 qui se
renforcent mutuellement, puis 11 + 12 ensemble, 13 et 14 au fil de l'eau.

*Rien n'a été implémenté : ce document est un constat, la base de travail de la
branche `dev_rf`.*

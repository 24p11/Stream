# Spécification — Banc d'essai de génération AP-HP (`bench`)

Branche cible : `dev_rf` · Statut : **v3.7** — transport Mistral `sync` (défaut) ou `batch`

v3.6 → v3.7 (septembre 2026, demande Rémi) : **transport des appels Mistral**.
Le batch Mistral reste en file (`QUEUED`) sans jamais démarrer ; `generate`
reçoit un paramètre `transport` — `"sync"` (défaut : un `chat.complete` par
scénario, `max_workers` appels en parallèle, trois tentatives par requête,
`timeout_seconds` borne chaque requête) ou `"batch"` (inchangé, à réactiver
quand Mistral l'aura rétabli). Même requête (système, user, prefix assistant,
`max_tokens`), même forme de réponse archivée (JSONL `sync_input_*` /
`sync_output_*` sous `batches/<stem de out>/`), validation et journal
communs ; l'entrée `usage.json` note le `transport`, car les tarifs diffèrent
(sync = deux fois le batch). `Pricing` garde ses noms de champs.

v3.5 → v3.6 (demande Rémi) : **renommage des positions** — `first` évoquait
la génération en deux étapes ; la génération directe (seule en service)
s'appelle désormais `one_gen` (`system/one_gen/`, figé
`prompt_system_one_gen.txt`). Si le 2-gen renaît, ses positions seront
`first_gen`/`second_gen`. Transition : le test 01 (archive) a été monté sous
`first` ; la bascule se fait au montage du test 02 (`copytree`
01/system/first → 02/system/one_gen).

Changements v3.2 → v3.3 : le test contient son **jeu de templates système**
dans `system/<position>/` (copié des sources, édité là — unité d'édition par
famille), puis `copy_system_prompts` le **fige par scénario** en
`prompt_system_<position>.txt`. Les positions (`first`, `second`, `third`...)
sont **relatives au test** : Test1 (directe) monte `first` depuis les templates
one-gen ; Test2 (deux temps) monte `first` et `second` depuis first/second-gen.
Vérifications actées : les trois fichiers user de l'ancien `create_prompt_files`
sont identiques → **un seul fichier user par dossier** ; le 2-step n'existe pas
dans fictomed (couche notebook uniquement) → le lot 5 devient le chemin de
**promotion** vers fictomed. Ajout : mécanisme `prompt_local.py` (§3.7).

v3.4 → v3.5 (demande Rémi) : **les jeux de templates système vivent dans les
tests, pas à la racine** — ils sont l'objet testé. Le jeu du test N+1 est monté
par copie du jeu du test N puis édité ; la chaîne des tests est la chaîne des
versions des jeux (01 = v1, 02 = évolution, 03 = figement, ...). Les dossiers
`work_prompts/template_*` disparaissent : l'amorçage du premier test se fait
directement depuis `work_modif_prompts/template_*` (import unique).
**Tout `work_prompts/` est versionné et partagé** (décision Rémi) : jeux,
scénarios, prompts figés, CRH — les tests complets sont l'objet de la
collaboration. « Figer » un jeu = commiter son test.

v3.3 → v3.4 (demande Rémi) : **`work_modif_prompts/` n'est plus touché** —
l'ancien monde y reste intact (notebook, utilitaires, anciens runs, sources de
templates), en lecture seule de fait. Tout le nouveau vit dans un répertoire
neuf **`work_prompts/`** : le notebook, les copies des sources de templates
(faites une fois depuis l'ancien répertoire), et `tests/`. Le code réutilisé de
l'ancien monde (`aphp_generation_utils.py` pour la chaîne amont fictomed,
`run_mistral_batch` pour la logique batch) est **importé ou copié**, jamais
modifié en place.

## 1. Modèle d'usage

Le workflow d'un test :

1. **Graine** : DataFrame polars de scénarios — soit lu d'un parquet de
   `data/`, soit produit par la chaîne fictomed existante
   (`write_fictomed_config` + `generate_and_select_fictomed_scenarios`,
   réutilisées telles quelles) — puis **filtré à la main** dans le notebook.
   La frontière est nette : fictomed produit la graine, `bench` commence après.
2. **Création des prompts** :
   - `seed_user_prompts` matérialise les dossiers scénario (user prompt,
     `template.txt`, `prefix.txt`) ;
   - montage du jeu de templates du test : copie du jeu du **test
     précédent** dans `system/<position>/` (ou de `work_modif_prompts/
     template_*` pour l'amorçage du tout premier test) ;
   - **édition manuelle dans `system/<position>/`** — c'est l'unité d'édition,
     un fichier par famille clinique ;
   - `copy_system_prompts` **fige** le jeu par scénario
     (`prompt_system_<position>.txt`, résolu via `template.txt`).
     Après cela, chaque dossier scénario est **autonome** : il archive
     exactement ce qui partira au modèle.
3. **Générations** : appels successifs de `generate`, chacun prenant en
   argument des **noms de fichiers** lus dans le dossier de chaque scénario.
   Étapes conditionnées = plusieurs appels, le `reports` de l'un nourrissant
   le `context` du suivant. Aucun paramètre `generation_mode`.

Positions : chaînes libres, nommées d'après la topologie pour lever toute
ambiguïté. Amorçage depuis l'ancien monde (premier test de chaque topologie
uniquement — ensuite, la chaîne) :

- Génération directe (seule en service) : `system/one_gen/` ←
  `template_one_gen`
- Deux temps (non utilisé actuellement) : `system/first_gen/` ←
  `template_first_gen`, `system/second_gen/` ← `template_second_gen`
- Autres topologies : positions libres (`verif`, ...).

Itération : éditer `system/<position>/` puis re-figer sous un autre nom
(`dest="prompt_system_one_gen_v2.txt"` → `out="crh_v2.txt"`, les variantes
coexistent) ; ou copier un dossier scénario (il emporte tous ses prompts).
Jamais de nettoyage de prompts existants (`clean_existing_prompts` disparaît) :
pour repartir, créer `tests/02`.

Le disque fait foi : aucune fonction ne maintient de registre. La référence
d'un jeu est le jeu commité du test précédent — la chaîne des tests est la
chaîne des versions.

Hors périmètre : la réunification de la couche batch dans `MistralClient`
(chantier séparé), la promotion des prompts validés vers fictomed (§6).

## 2. Arborescence d'un test

```
work_modif_prompts/                        # ANCIEN MONDE — non modifié
└── ... (ancien notebook, utils, runs, template_*)

scripts/
└── check_crh.py                           # vérificateur mécanique des CRH

work_prompts/                              # NOUVEAU MONDE
├── notebook_generation_bench.ipynb        # le notebook
└── tests/                                 # versionné intégralement (cf. §9)
    └── 02/                                # ex. un test « génération directe »
        ├── system/                        # JEU DU TEST (objet testé) : copié
        │   └── one_gen/                   # du jeu du test précédent, édité
        │       │                          # ICI (un .txt par famille,
        │       │                          # + regles_atih.yml, hors périmètre)
        │       ├── medical_outpatient.txt
        │       └── surgery_inpatient.txt
        ├── prompt_local.py                # optionnel : user_fn locale (§3.7)
        ├── test.json                      # provenance (facultatif, §2.2)
        ├── usage.json                     # journal des coûts (§7)
        ├── .fictomed/                     # optionnel : fichiers de travail de
        │                                  # la chaîne amont (ignoré, caché)
        ├── 0000/                          # un dossier AUTONOME par scénario
        │   ├── template.txt               # famille (stem), seeding, éditable
        │   ├── prompt_system_one_gen.txt  # FIGÉ par copy_system_prompts
        │   ├── prompt_system_verif.txt    # via write_prompts (texte partagé)
        │   ├── user_generation.txt        # matérialisé depuis la graine
        │   ├── prefix.txt                 # prefill (si graine en a un)
        │   ├── crh_generation.txt         # écrits par generate()
        │   └── verdict.txt
        ├── 0001/                          # autre famille : son
        │   └── ...                        # prompt_system_one_gen.txt diffère
        ├── 0001_bis/                      # copie manuelle — légitime
        └── batches/                       # JSONL Mistral (technique), un
            └── crh_final/                 # sous-dossier par fichier de sortie
```

Conventions :

- **Identité d'un scénario = nom de son dossier** (seeding : `0000`, ... ;
  copies manuelles : nom libre). Sert de `custom_id` batch, de clé de
  jointure du contexte et de valeur pour `only`.
- **Découverte disque** : sous-dossiers directs de `test_dir`, hors
  `system/`, `batches/` et dossiers cachés, triés alphabétiquement. Les
  fichiers à la racine (`prompt_local.py`, `test.json`, ...) sont ignorés.
- **Nommage** : `prompt_system_<position>.txt` (défaut de
  `copy_system_prompts`) — donc `prompt_system_one_gen.txt` pour la
  génération directe ; les noms restent des arguments libres. **Un seul fichier
  user** par dossier et par contenu distinct (vérifié : l'ancien système
  dupliquait le même texte en trois exemplaires).
- Les fonctions de création de prompts n'écrasent **jamais** un fichier
  existant, de façon **atomique** (si un dossier est déjà servi, rien n'est
  écrit nulle part). Les sorties (`out`) sont écrasées à chaque re-run.

### 2.2 `test.json` (provenance, facultatif)

Écrit par `seed_user_prompts` uniquement, jamais relu par le code :

```json
{
  "created_at": "2026-08-13T10:00:00",
  "seed_path": "data/aphp/scenarios_20260810.parquet",
  "generation_ids": {"0000": "4426ab10-...", "0001": "..."},
  "templates": {"0000": "medical_outpatient", "0001": "surgery_inpatient"},
  "fictomed_version": "0.1.2",
  "fictomed_commit": "abc1234",
  "notes": ""
}
```

`seed_path` relatif à la racine du repo, `as_posix()` (seul point d'écriture
de chemin — portabilité par construction). `fictomed_version`/
`fictomed_commit` obtenus si possible (importlib.metadata + `direct_url.json`,
ou `git rev-parse` en repli), sinon `null` + avertissement.

## 3. API (`bench/`)

Une seule exception, `BenchError`, toujours à message actionnable (chemin
complet, liste des scénarios, id du run Mistral — batch ou sync — le cas
échéant). Politique
générale : **échec dur** — un banc d'essai comparatif n'a pas de mode dégradé.

### 3.1 `scenario_dirs`

```python
def scenario_dirs(test_dir: Path) -> list[str]
```

Découverte (§2). Retourne les noms triés.

### 3.2 `seed_user_prompts` — la graine, une fois

```python
def seed_user_prompts(
    test_dir: Path,
    seed: pl.DataFrame,
    *,
    filename: str = "user_generation.txt",
    user_fn: Callable[[dict], str] | None = None,   # défaut : user_from_column()
    seed_path: Path | None = None,                  # provenance pour test.json
) -> list[str]                                      # dossiers créés
```

1. Refuse si `test_dir` contient déjà des dossiers scénario (`BenchError`) —
   une graine par test.
2. Valide `seed` : `generation_id` présent, non nul, unique (provenance) ;
   `template_name` présent, non nul. **Plusieurs familles admises.** Le
   DataFrame arrive **déjà filtré** par le notebook.
3. Crée un dossier par ligne (`0000`, ... dans l'ordre du DataFrame) et y
   écrit : `filename` via `user_fn` ; `template.txt` =
   `Path(template_name).stem` (nettoyé) ; `prefix.txt` si la graine a une
   colonne `prefix` non vide.
4. Écrit `test.json` (§2.2).

```python
def user_from_column(column: str = "user_prompt") -> Callable[[dict], str]
    # colonne absente ou valeur nulle → BenchError
```

### 3.3 `copy_system_prompts` — figer le jeu du test par scénario

```python
def copy_system_prompts(
    test_dir: Path,
    position: str,                          # "one_gen", "verif", ...
    *,
    dest: str | None = None,                # défaut : f"prompt_system_{position}.txt"
) -> list[str]                              # scénarios servis
```

Source : **le jeu du test**, `test_dir / "system" / position /`. Pour chaque
dossier découvert : lit `template.txt` (strip) et copie
`system/<position>/<template>.txt` sous `<scenario>/<dest>`. C'est ici — et
seulement ici — que la famille clinique choisit le prompt système. Échecs
durs (`BenchError` nommant scénario et chemin attendu) : `system/<position>/`
absent, `template.txt` absent, fichier de famille absent du jeu, `dest` déjà
présent dans un dossier (atomique : liste des dossiers, rien n'est écrit).

Le montage du jeu (`system/<position>/` ← source) est un geste notebook :
`shutil.copytree(SRC, TD / "system" / "one_gen")` — refuse nativement si la
destination existe.

### 3.4 `write_prompts` — texte constant dans chaque dossier

```python
def write_prompts(test_dir: Path, filename: str, text: str) -> list[str]
```

Écrit `text` sous `filename` dans **chaque dossier découvert** — user prompts
additionnels (vérificateur) comme prompts système partagés
(`prompt_system_verif.txt`), même mécanique. Refus d'écraser atomique.

### 3.5 `generate` — le cycle de génération

```python
def generate(
    test_dir: Path,
    *,
    system: str,                     # fichier dans chaque dossier scénario
    user: str,                       # fichier dans chaque dossier scénario
    out: str,                        # fichier écrit dans chaque dossier scénario
    client: MistralClient,
    model: str,
    max_tokens: int,
    pricing: Pricing,
    prefix_file: str | None = None,  # ex. "prefix.txt" (lu par scénario)
    prefix_text: str = "",           # exclusif de prefix_file (BenchError si les deux)
    context: pl.DataFrame | None = None,   # colonnes scenario, report
    context_header: str = "",
    context_footer: str = "",
    only: list[str] | None = None,
    dry_run: bool = False,
    transport: Literal["sync", "batch"] = "sync",
    max_workers: int = 3,            # sync : appels en parallèle
    poll_interval_seconds: float = 1.0,   # batch : cadence du polling
    timeout_seconds: float = 3600.0,      # sync : par requête ; batch : polling
) -> GenResult
```

`transport` inconnu → `BenchError` avant tout travail (dry-run compris).
`pricing` est le tarif du transport choisi (le notebook les tient côte à
côte).

`system`, `user`, `out`, `prefix_file` : tous des noms de fichiers **relatifs
au dossier de chaque scénario** — parfaitement symétriques. Aucune résolution
dans `generate` : elle a eu lieu à l'installation (§3.3).

```python
@dataclass(frozen=True)
class Pricing:                       # tarif du transport utilisé (noms hérités
    batch_input_usd_per_million: float    # du batch, conservés)
    batch_output_usd_per_million: float

@dataclass(frozen=True)
class Usage:
    n_requests: int
    input_tokens: int
    output_tokens: int
    total_tokens: int
    input_cost_usd: float
    output_cost_usd: float
    total_cost_usd: float

@dataclass
class GenResult:
    out: str                     # nom du fichier de sortie (sert d'étiquette)
    reports: pl.DataFrame        # scenario, template, system_prompt,
                                 # user_prompt, prefix, report, model,
                                 # timestamp, tokens in/out
    usage: Usage
    partial: bool                # True si `only` a restreint le run
    dry_run: bool                # True si aucun appel API n'a eu lieu
```

(`template` = contenu de `template.txt` si présent, sinon null — informatif,
pour ventiler les analyses par famille.)

Déroulement :

1. **Découverte + filtre.** `scenario_dirs(test_dir)`, puis `only` ; nom
   inconnu → `BenchError` listant les dossiers existants.
2. **Assemblage.** Pour chaque scénario retenu, lecture dans **son** dossier :
   `system`, `user`, prefix selon `prefix_file`/`prefix_text`, contexte
   injecté le cas échéant (§4). Fichier manquant ou illisible → `BenchError`
   nommant chemin et scénario. **Jamais de perte silencieuse** : un dossier
   auquel il manque un fichier fait échouer le run, il n'est pas sauté. La
   cellule `dry_run=True` du notebook sert ainsi de **test de complétude**
   avant tout appel API.
3. **Point d'arrêt `dry_run`.** Retourne le `GenResult` (prompts assemblés,
   `report` vide, usage nul). **Aucun appel API, aucune écriture.**
4. **Appels Mistral selon `transport`.** Requête commune : messages système,
   user, prefix assistant (`prefix: true`) le cas échéant, `max_tokens` ;
   `custom_id` = nom du scénario ; JSONL d'entrée et de sortie sous
   `batches/<stem de out>/`, au même format quel que soit le transport.
   - `sync` : un `chat.complete` par scénario, `max_workers` en parallèle,
     trois tentatives par requête (pauses 5 s puis 15 s) ; une erreur
     persistante est archivée comme une erreur batch et tombe en validation.
     Fichiers `sync_input_<ts>.jsonl` / `sync_output_<ts>.jsonl`, id de run
     `sync_<ts>`.
   - `batch` : upload, job, polling borné par `timeout_seconds` →
     `BenchError` mentionnant l'id du batch Mistral pour récupération
     manuelle. Fichiers `batch_input/output/errors_<ts>.jsonl`.
5. **Validation** — précède toute écriture : scénarios retournés == attendus ;
   réponses non vides/non blanches ; **aucune erreur Mistral**
   (`mistral_batch_error`, alimentée par les deux transports). Chaque écart →
   `BenchError` nommant le run et listant les scénarios.
6. **Sauvegarde.** `out` écrit dans chaque dossier traité (écrasement = geste
   normal) ; entrée ajoutée au journal `usage.json` (§7), étiquetée par `out`.
7. Retour du `GenResult`.

### 3.6 `load_reports` — reprise de session

```python
def load_reports(test_dir: Path, filename: str,
                 *, strict: bool = True) -> pl.DataFrame   # scenario, report
```

Relit `filename` dans les dossiers découverts. `strict=True` → `BenchError`
listant les scénarios sans fichier ; `strict=False` → retourne les présents.

### 3.7 `prompt_local.py` — logique de prompt locale au test

La graine porte les champs bruts (`icd_primary_code`, `ghm2`,
`admission_type`, `template_name`, ...) en plus du `user_prompt` construit par
fictomed. Pour tester une **construction** de user prompt différente sans
toucher au package, l'utilisateur pose un `prompt_local.py` à la racine du
test (c'est un fichier : la découverte l'ignore) :

```python
# tests/02/prompt_local.py
def build_user(row: dict) -> str:
    return f"...{row['icd_primary_code']}...{row['ghm2']}..."
```

et le charge dans le notebook (`importlib.util.spec_from_file_location`) pour
le passer en `user_fn=` à `seed_user_prompts`. Le fichier vit avec le test —
un test, c'est ses prompts, y compris leur logique de construction. Point de
départ possible : `inspect.getsource` sur la fonction fictomed correspondante,
copiée puis modifiée. Hiérarchie des leviers de modification : (1) éditer les
`.txt` du test ; (2) `prompt_local.py` ; (3) monkeypatch fictomed dans le
notebook (fragile, à noter dans `test.json["notes"]`) ; (4) modifier le clone
fictomed editable — réservé à ce qui doit être promu.

## 4. Injection de contexte

`context` contient `scenario` et `report` ; pour chaque scénario retenu, le
`report` de **son** dossier est concaténé en fin de user prompt. Scénario
absent du contexte ou `report` vide/blanc → `BenchError` (remplace le
`summaries.get(id, "")` silencieux actuel). Format :

```
<user_prompt.rstrip()>

<context_header.strip()>

<report.strip()>

<context_footer.strip()>
```

Pas de placeholder : l'injection est toujours terminale. Un positionnement
intra-prompt serait une évolution de spec (placeholder explicite
`{{context}}`), pas un comportement implicite.

## 5. Workflows de référence (documentation notebook)

```python
# ---------- Test 1 : génération directe (amorçage depuis l'ancien monde) ----------
# (historique : le test 01 utilisait la position "first" ; convention
#  actuelle : "one_gen")
TD = Path("work_prompts/tests/01")
seed_user_prompts(TD, seed_df, seed_path=SEED_PATH)
shutil.copytree("work_modif_prompts/template_one_gen", TD / "system" / "one_gen")
# [édition manuelle de TD/system/one_gen/*.txt]
copy_system_prompts(TD, "one_gen")
cr = generate(TD, system="prompt_system_one_gen.txt", user="user_generation.txt",
              out="crh_generation.txt", prefix_file="prefix.txt", ...)

# ---------- Test suivant : évolution du jeu (chaîne de versions) ----------
TD = Path("work_prompts/tests/02")
seed_user_prompts(TD, seed_df, seed_path=SEED_PATH)
shutil.copytree("work_prompts/tests/01/system/first",   # 01 : ancienne position
                TD / "system" / "one_gen")              # 02+ : convention one_gen
# [édition du jeu de 02 — c'est LA modification testée]

# ---------- Test deux générations (non utilisé — amorçage le jour venu) ----------
# shutil.copytree("work_modif_prompts/template_first_gen",  TD / "system" / "first_gen")
# shutil.copytree("work_modif_prompts/template_second_gen", TD / "system" / "second_gen")
copy_system_prompts(TD, "one_gen")
copy_system_prompts(TD, "second_gen")  # si 2-gen
res = generate(TD, system="prompt_system_one_gen.txt", user="user_generation.txt",
               out="crh_resume.txt", prefix_text=FIRST_GEN_PREFIX, ...)
cr = generate(TD, system="prompt_system_second_gen.txt", user="user_generation.txt",
              out="crh_final.txt", context=res.reports,
              context_header=SUMMARY_HEADER, context_footer=SUMMARY_FOOTER, ...)

# ---------- Test 3 : génération + vérificateur ----------
cr = generate(TD, system="prompt_system_one_gen.txt", user="user_generation.txt",
              out="crh_generation.txt", prefix_file="prefix.txt", ...)
write_prompts(TD, "prompt_system_verif.txt", VERIF_SYSTEM)   # une fois
write_prompts(TD, "user_verification.txt", VERIF_USER)       # une fois
verdicts = generate(TD, system="prompt_system_verif.txt",
                    user="user_verification.txt", out="verdict.txt",
                    context=cr.reports, context_header=VERIF_HEADER, ...)

# ---------- Itération sur un jeu système ----------
# [éditer TD/system/one_gen/*.txt]
copy_system_prompts(TD, "first", dest="prompt_system_one_gen_v2.txt")
cr_v2 = generate(TD, system="prompt_system_one_gen_v2.txt",
                 user="user_generation.txt", out="crh_v2.txt", ...)

# ---------- Reprise de session ----------
cr = load_reports(TD, "crh_generation.txt", strict=False)
verdicts = generate(TD, system="prompt_system_verif.txt",
                    user="user_verification.txt", out="verdict.txt",
                    context=cr, only=cr["scenario"].to_list(), ...)
```

Chaque appel réel est précédé d'une cellule `dry_run=True` affichant le
premier prompt assemblé — contrôle à sec et test de complétude en un geste.
La graine peut venir de la chaîne fictomed existante (cellules
`write_fictomed_config` / `generate_and_select_fictomed_scenarios`,
inchangées, fichiers de travail dirigés vers `TD/.fictomed/` ou un dossier
temporaire) ou d'un parquet de `data/`.

## 6. Promotion vers fictomed (second temps)

Constat vérifié : la génération en deux temps n'existe pas dans fictomed —
`template_first_gen`/`template_second_gen` sont des créations locales du banc,
et l'enchaînement (résumé → CR) vivait dans la couche notebook. Le « lot 5 »
n'est donc pas une simple exposition de ressources : c'est le **chemin de
promotion** des jeux de templates validés par le banc vers le package —
chantier de contenu autant que de code, à mener avec le CHU de Brest. Le jour
venu : fictomed expose ses jeux en ressources (`importlib.resources`), et un
helper `install_fictomed_system_set(test_dir, set_name, position)` remplace le
`shutil.copytree` depuis les dossiers locaux. Hors périmètre de la v1.

## 7. Coûts

- `usage.json` : **journal append-only** ; chaque run réel (non dry-run)
  ajoute une entrée étiquetée par `out` — y compris les re-runs. L'argent
  dépensé reste tracé même quand les sorties sont écrasées.

```json
{"runs": [
  {"out": "crh_generation.txt", "at": "2026-08-13T15:02:11", "partial": false,
   "n_requests": 20, "model": "mistral-large-latest",
   "input_tokens": 41000, "output_tokens": 38000,
   "input_cost_usd": 0.082, "output_cost_usd": 0.228, "total_cost_usd": 0.31}
]}
```

- `summarize_costs(test_dir) -> pl.DataFrame` : total engagé par `out` et
  global, plus coût de l'état courant par `out` (entrées depuis le dernier
  run complet, celui-ci inclus).

## 8. Emplacement du code

**Package `bench/` à la racine** (même convention que `core/` et
`pipelines/`) :

```
bench/
├── __init__.py     # scenario_dirs, seed_user_prompts, user_from_column,
│                   # copy_system_prompts, write_prompts, generate,
│                   # load_reports, summarize_costs, Pricing, Usage,
│                   # GenResult, BenchError
├── seeding.py      # scenario_dirs, seed_user_prompts, copy_system_prompts,
│                   # write_prompts
├── generate.py     # generate, load_reports (+ transports Mistral privés : sync, batch)
├── costs.py
└── errors.py
```

Le transport sync est nouveau (`_run_mistral_sync`, `chat.complete` du SDK).
La logique batch reprend `run_mistral_batch` de l'ancien
`work_modif_prompts/aphp_generation_utils.py` — **copiée/adaptée dans
`bench/generate.py`, sans modifier le fichier d'origine**. L'accès
`client._client` est conservé provisoirement (résorbé par le chantier
`MistralClient` séparé). Le notebook vit dans `work_prompts/` ; sa cellule
bootstrap `sys.path` pointe la **racine du repo** pour que `import bench` (et
l'import de la chaîne amont depuis `work_modif_prompts/`) fonctionnent.

## 9. Git

**Tout `work_prompts/` est versionné et partagé** — jeux de templates,
scénarios, prompts figés, CRH générés, `test.json`, `usage.json` : les tests
complets sont l'objet de la collaboration (prompts et résultats côte à
côte). Seule exception admise, au choix : ignorer
`work_prompts/tests/*/batches/` (JSONL techniques, redondants avec le
contenu des dossiers scénario). « Figer » un jeu = commiter son test.
`work_modif_prompts/` n'est pas modifié par ce chantier.

Point d'attention (décision hors spec, à l'appréciation du DIM) : le dépôt
étant public, vérifier que la publication de scénarios dérivés de profils
PMSI réels est conforme aux règles applicables, ou cibler une visibilité
restreinte.

## 10. Tests attendus

Tous sans réseau (client Mistral mocké), sur `tmp_path` :

1. `seed_user_prompts` : dossiers numérotés dans l'ordre de la graine, avec
   `filename`, `template.txt` (stem) et `prefix.txt` (si colonne) ;
   **plusieurs familles admises** ; refus si dossiers scénario déjà
   présents ; refus si `generation_id` dupliqués/nuls ou `template_name`
   nul ; `test.json` conforme (`seed_path` en `as_posix`, blocs
   `generation_ids` et `templates`).
2. `scenario_dirs` : exclut `system/`, `batches/` et cachés, ignore les
   fichiers à la racine (dont `prompt_local.py`), tri alphabétique ; **un
   dossier copié manuellement apparaît**.
3. `copy_system_prompts` : deux scénarios de familles différentes reçoivent
   des contenus différents sous le même `dest` (depuis
   `system/<position>/`) ; `system/<position>/` absent → `BenchError` ;
   `template.txt` absent → `BenchError` ; famille absente du jeu →
   `BenchError` nommant le chemin attendu ; `dest` déjà présent →
   `BenchError` listant les dossiers, **rien n'est écrit** (y compris dans
   les dossiers indemnes) ; `dest` par défaut =
   `prompt_system_<position>.txt`.
4. `write_prompts` : écrit dans chaque dossier découvert (y compris copié) ;
   refus d'écraser atomique.
5. `generate` dry-run : prompts assemblés corrects (system et user lus dans
   le dossier de chaque scénario, contexte au format §4, prefix
   file/text/aucun, colonne `template` renseignée) ; aucune écriture, aucune
   entrée dans `usage.json`.
6. Complétude : `system` ou `user` manquant dans un dossier → `BenchError`
   nommant fichier et scénario.
7. Contexte : scénario absent ou report vide → `BenchError`.
8. `only` : filtrage correct ; nom inconnu → `BenchError` ; run partiel
   n'écrit `out` que dans les dossiers traités (les autres intacts),
   `partial=True`.
9. Prefix : `prefix_file` absent du dossier → `BenchError` ; `prefix_file`
   et `prefix_text` fournis ensemble → `BenchError`.
10. Validation (sync et batch) : réponse manquante, vide, ou en erreur
    Mistral → `BenchError` avant toute écriture (ni `out`, ni journal).
    Sync : reprise après erreur transitoire ; erreur persistante après trois
    tentatives → `BenchError` ; `transport` inconnu → `BenchError` sans
    appel.
11. Usage : journal append-only (re-run = nouvelle entrée, l'ancienne
    subsiste) ; `summarize_costs` distingue total engagé et état courant.
12. `user_from_column` : colonne absente ou valeur nulle → `BenchError`.
13. `load_reports` : reconstruction fidèle (scénarios, tri) ; fichier
    manquant → `BenchError` en strict, ignoré en non-strict.
14. Portabilité : `seed_path` écrit avec `/` ; `test.json` relisible tel
    quel sous les deux OS.

## 11. Migration

- `run_generation_workflow`, `load_stage_prompts`, `load_state`, le dict
  `paths`, `create_prompt_files` (et son flag `clean_existing_prompts`) et
  l'arborescence `prompts/une_gen|deux_gen` sont remplacés — pas de couche de
  compatibilité, l'ancien notebook reste dans l'historique git.
- La chaîne amont fictomed (`write_fictomed_config`,
  `generate_and_select_fictomed_scenarios`) est **réutilisée telle quelle** ;
  seul son `run_dir` de travail change de destination.
- `run_mistral_batch`, `validate_reports`, `save_individual_outputs`,
  `calculate_and_print_usage` sont absorbés/adaptés dans `bench/`.
- `work_modif_prompts/` (notebook, utilitaires, runs, templates d'origine)
  n'est **pas modifié** ; sa suppression éventuelle est une décision séparée,
  ultérieure.

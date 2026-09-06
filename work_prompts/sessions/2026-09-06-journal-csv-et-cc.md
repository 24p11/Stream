# Session du 6 septembre 2026 — journal CSV global des appels ; chantier CC (tabac/alcool)

Document de session, complété étape par étape (Rémi change de poste bientôt :
chaque étape est commitée et poussée sur `origin/dev_rf` = 24p11/Stream).
À lire après `2026-09-05-transport-sync.md`.

## Étape 1 — journal CSV global des appels (spec §7) — FAIT, commité

- `bench/costs.py` : `append_usage_csv(path, rows)` + `USAGE_CSV_COLUMNS`
  (`timestamp_utc, test, out, scenario, template, model, input_tokens,
  output_tokens, cost_usd, batch_id, partial`). Création avec en-tête si absent,
  sinon append pur ; `cost_usd` arrondi à 6 décimales ; échec → `BenchError`.
  `append_usage(..., at=)` : instant partagé avec le CSV.
- `bench/generate.py` : paramètre `usage_csv` (défaut `...` →
  `<racine des tests>.parent/usage_log.csv` = `work_prompts/usage_log.csv` ;
  `None` désactive). Écrit après validation, après `out` et `usage.json` :
  une ligne par scénario traité, `batch_id` = id du run (batch ou `sync_<ts>`).
  Même instant que `usage.json` : local sans fuseau dans le JSON (format
  inchangé), UTC suffixe Z dans le CSV.
- Tests : `TestJournalCsv` (8 cas). 91 verts + l'échec préexistant de
  `test_pipelines`.
- Notebook §4 : cellule de stats (par test/out, par template du test courant),
  skip si le CSV n'existe pas ; polars force `test`, `scenario`, `batch_id`
  en chaînes.
- Le CSV naîtra au prochain run réel (pas de rétro-journalisation des runs
  du 5 septembre) ; `scripts/recover_batch.py` ne l'alimente pas.

## Étape 2 — chantier CC : étiquettes tabac/alcool = données, template les reformule — FAIT, commité

Origine : relecture des CRH de tests/05 — le modèle recopiait « Non-fumeur /
Pas de mésusage » tel quel dans l'encadré patient (surtout les CRO de chirurgie
ambulatoire, qui n'avaient aucun bloc H).

- `work_prompts/enrichissement/intoxications.py` : `Tabac.as_ligne` /
  `Alcool.as_ligne` (source des colonnes `tabac`/`alcool` et donc du
  `bloc_contexte`) produisent des formes courtes et factuelles, un statut →
  une forme (table dans `README_fictomed.md`) : tabac « non » / « actif, 15
  cigarettes/jour, 20 PA » / « sevré depuis 4 ans (22 PA) » ; alcool « non » /
  « environ n verres/jour » (+ « , symptômes physiques de sevrage ») /
  « n verres par épisode, k épisodes/semaine » / « sevré depuis … ». Le mot
  « mésusage » n'apparaît plus dans le bloc. `as_texte` (`contexte_texte`)
  inchangé, hors prompt. **Pas de forme « occasionnel »** : aucune catégorie
  du module n'y correspond (la « consommation modérée » est régulière, 2-4
  verres/jour, contexte poly sans code) — à créer comme statut si voulu.
- Tests : `test_bloc_contexte_contenu_et_style` durci (regex, pas de
  « mésusage »), `test_etiquettes_tabac_alcool_par_statut` (les 6+3 statuts),
  `test_etiquettes_du_bloc_sur_toute_la_table`. 93 verts.
- `README_fictomed.md` : note pour fictomed (étiquettes = données, le template
  doit les faire reformuler, bloc H de référence) + table des formes.
- **tests/06 monté** (`system/one_gen` copié de 05, comme la cellule de
  montage) et bloc H amendé dans les 13 templates : après « … avec les
  valeurs exactes. », la consigne « Les lignes Tabac et Alcool du scénario
  sont des DONNÉES, pas des phrases … pas dans l'encadré d'identification. ».
  Les deux CRO (`surgery_outpatient`, `_onco`) n'avaient pas de bloc H ni de
  section Mode de vie : puce complète ajoutée avant « - Langue », données à
  restituer dans le **Rappel clinique** (interprétation à valider par Rémi).
  tests/05 non modifié ; effet au seeding de 06.
- Notebook inchangé : pour passer à 06, cellule « Paramétrage des chemins » →
  `TEST_NUM = "06"`, `PREV_TEST = "05"` ; la cellule de montage SKIP (déjà
  monté), puis tirage + seeding (enrichissement avec les nouvelles
  étiquettes) + figement, contrôle à sec, run réel (sync).

## Étape 3 — test 06 seedé et figé (sans appel API) — FAIT, commité

- Notebook basculé : `TEST_NUM = "06"`, `PREV_TEST = "05"`.
- Cellules jouées hors interface (pilote `jupyter_client` sur un noyau du venv,
  cwd `work_prompts/`) : sections 1, 2 (préparation, filtre DP en 8, tirage
  stratifié seed 42, enrichissement seed 42), 3.1 (montage SKIP — déjà monté —,
  génération fictomed, seeding, figement, prompts vérificateur), contrôle à sec
  3.2. Tout OK, 4 s pour fictomed.
- Résultat : 14 dossiers `0000`-`0013`, `test.json` du 6 sept. 12h37.
  **Mêmes 14 séjours que tests/05** (DP, âge, sexe identiques deux à deux) mais
  fictomed régénère l'habillage synthétique (nom, dates, hôpital, signataire,
  `generation_id`) et la numérotation change (ex. 05/0000 N328 → 06/0006). Une
  césarienne : 05 `delivery_inpatient_hospit` → 06 `delivery_inpatient_csection_hospit`
  pour le même séjour O628 (choix de template fictomed).
- Prompts utilisateur : nouvelles étiquettes (« Tabac : non », « sevré depuis
  4 ans (22 PA) », « actif, 12 cigarettes/jour, 10 PA », « Alcool : environ 5
  verres/jour »…), 11 lignes enrichies sur 14 (3 exclues par la politique),
  zéro « mésusage ». Prompts système figés : consigne bloc H présente dans les
  14 (variante « Rappel clinique » pour le CRO de chirurgie ambulatoire).
- Reste à faire : run réel 3.2 (14 scénarios, sync, ~0,09 USD — feu vert de
  Rémi requis), aperçus .md, bilan §4, check_crh, commit.

## Étape 4 — run réel tests/06, aperçus .md, bilan — FAIT, commité

- Run réel (feu vert Rémi) joué dans le noyau VS Code (seul détenteur de la
  clé) via le pilote : 14/14 réponses `stop`, 0 erreur, 116 s, 100 625 tokens
  in / 23 338 out, **0,085 USD** (`usage.json`, transport sync). Aperçus `.md`
  écrits (cellule « Lecture des CR »). Section 4 jouée.
- **Objectif CC atteint** : dans les 14 CRH de 06, 0 étiquette recopiée
  (« Tabac : », « Alcool : »), 0 « mésusage », 0 « Non-fumeur » — contre 4
  étiquettes recopiées, 6 CRH « mésusage », 6 CRH « Non-fumeur » dans tests/05.
- `check_crh` (mécanique, hors modèle) : 06 = 94 ECHEC / 19 AVERT (70
  formulations fantômes, 14 IPP absent, 9 gras interdit, 1 taille de scénario)
  contre 05 = 74 / 17 (53, 14, 7). Hausse des formulations fantômes à
  surveiller (variance d'un run, ou effet de la consigne ?) — hors périmètre CC.
- **Journal CSV** : le noyau VS Code (démarré le 5 au soir) avait l'ancien
  module `bench` en mémoire → `generate` sans `usage_csv`, `usage_log.csv` non
  créé par le run. Reconstruit après coup depuis l'archive validée
  `sync_output_20260906_124117_973760.jsonl` + `usage.json` (mêmes données,
  sommes vérifiées), 14 lignes. Leçon : après modification de `bench`,
  redémarrer le noyau avant tout run.
- Commit : 14 CRH + 14 .md + `usage.json` de 06, `usage_log.csv`.

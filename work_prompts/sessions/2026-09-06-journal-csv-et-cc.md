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

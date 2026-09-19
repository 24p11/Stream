# Session du 12 septembre 2026 — chaîne de vérification-régénération ; lot R1

Reprise sur le poste d'origine (pull `e3b5663`, env resynchronisé). Piège
constaté en plus de ceux du journal : **`uv run` re-synchronise aussi**
l'environnement et écrase le fictomed éditable par le PyPI 0.1.2 — utiliser
`.venv/bin/python` directement, ou `uv run --no-sync`.

## Retouches scripts (commit `c2edc64`)

- `scripts/reancre_crh.py` déposé (fourni par Rémi) : tri exactes /
  réancrées / orphelines par fuzzy matching, lecture seule. Sur tests/06 :
  les 70 « formulations fantômes » du check = 37 réancrables + 26 vraies
  orphelines (seuil 0,75) — éclairage pour la question variance vs consigne.
- `check_crh.py` : contrôle n°4 (IPP/Nom/Prénom/naissance) rétrogradé en
  AVERT (l'IPP viendra de l'enrichissement) ; tests/06 : 94/19 → 80/33.

## Chaîne de vérification-régénération (commit `ab52706`)

Les maillons Python autour du futur juge d'équivalence (encodeur externe,
seul son contrat est construit ici) :

- `check_crh.py` : complétude du codage (codes du bloc « Codage CIM10 » ↔
  clés du dictionnaire diagnostics, habillages variés, extension PMSI
  « +n » tronquée — relevée sur 06/0005 `C254+8`) ; rapport `--json` par
  scénario, types stables documentés en tête de fichier.
- `nettoie_dictionnaire.py` : export propre par scénario sous
  `export_dict/` (réservé) — exactes gardées, réancrées remplacées par
  l'extrait exact, orphelines supprimées et tracées. Lecture seule.
- `juge_io.py` : contrat d'E/S du juge (docstring = référence pour
  l'équipe encodeur) — entrées JSONL par code (libellé, fiche, passages
  propres), verdicts validés strictement (BenchError).
- `prepare_regeneration.py` : bloc CORRECTION REQUISE prescriptif (jamais
  de citation fautive), formulation imposée tirée seedée des entités de la
  fiche, `user_regeneration.txt` dans les seuls dossiers rejetés (refus
  d'écraser atomique), `regeneration_<seed>.json` pour le re-check.
- Factorisation : `reancre_crh` expose `trier_formulations` et réutilise
  le chargeur JSON réparateur de `check_crh` (0001/0005 de 06 désormais
  lisibles ; nettoyage 14/14). 23 tests (`test_scripts_verification.py`).
- Chaîne validée bout à bout sur copie scratch de 06 : 48 entrées juge,
  1 rejeté mécanique (0011, taille absente). tests/06 inchangé : 80/33.

## Enquête fiches manquantes (6 codes sans fiche sur 48)

D508 (DP de 0010 !), F101, F1725, F17202, Z370, Z3711. Causes :
la librairie exacte locale est incomplète vs son index (**chapitre V
entier absent : 0/1060**, chapitre III partiel dont D50.8 ; Z37.x n'existe
qu'en catégorie) ET le repli « fiche de catégorie » n'a pas joué aux
seedings 05/06 — rejoué aujourd'hui avec l'éditable, il fonctionne
(D50 + F10 en catégorie) : les seedings ont très probablement tourné sur
le fictomed PyPI 0.1.2 (piège `uv sync`/`uv run`). D'où le lot R3.

## Lot R1 — consolidation (commit `adac8f2`)

`bench/scenarios.py` : chaîne amont extraite de l'ancien
`aphp_generation_utils.py` à l'identique — 3 fonctions appelées par le
notebook (`resolve_parquet_path`, `write_fictomed_config`,
`generate_and_select_fictomed_scenarios`) + `build_filter_expr`,
`apply_filters`, `prepare_source_candidates` (au plan de tests, bien que
le tirage stratifié s'y substitue). Ni `create_run_tree` (arborescence
obsolète) ni `safe_stem`/`write_text`. Notebook : `from bench import
scenarios as aphp_utils` (diff minimal), markdown 2.1 à jour ;
`bench/generate.py` : provenance reformulée « historique, dans git ».
14 tests (`test_bench_scenarios.py`). Critère vérifié : notebook rejoué
sans clé jusqu'au dry-run 3.2 inclus (pilote, SKIP attendus sur 06).

## Prochaines étapes

1. **Lot R2** (retrait de `work_modif_prompts/`) : R1 est commité, la voie
   est libre — le commit de retrait doit rester seul.
2. **Lot R3** : Rémi met à jour le clone fictomed (`git pull` sur
   `prompt-work`), puis réinstallation éditable, smoke de chaîne scratch
   (fiches D508/F17x/Z37x attendues), message à Brest (wheel 0.1.2 cassé,
   promotion enrichissement, doctrine E669x→E660x).
3. Relecture CRH 06 vs 05 et décisions en attente (statut alcool
   « occasionnel », puce CRO « Rappel clinique ») — inchangées.

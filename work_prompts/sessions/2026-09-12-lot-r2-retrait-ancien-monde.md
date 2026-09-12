# Session du 12 septembre 2026 (suite) — lot R2 : retrait de l'ancien monde

À lire après `2026-09-12-verif-regen-et-lot-r1.md`. Deux commits : la
relocalisation et les docs d'abord, puis le `git rm -r work_modif_prompts/`
SEUL (trivialement réversible — tout l'historique reste dans git).

## Clone fictomed relocalisé (AVANT le retrait)

- Convention : le clone canonique est **`~/Documents/fictomed`** (frère du
  repo, hors dépôt, remote CHU-Brest, branche `prompt-work`) — chemin
  porté par `FICTOMED_SRC`, défini une fois dans la cellule bootstrap du
  notebook et propre à chaque poste.
- Bascule vérifiée : fetch + checkout `prompt-work`, tête `83ebca9` de
  chaque côté (aucun commit local à rapatrier), éditable réinstallé
  (`uv pip install -e ~/Documents/fictomed`), `fictomed.__file__` pointe
  le nouveau clone. L'ancien clone interne
  (`work_modif_prompts/_dependencies/`) part avec le répertoire.
- **Nouvelle assertion bootstrap** : le notebook vérifie au démarrage que
  fictomed est bien l'éditable de `FICTOMED_SRC`, avec message de
  réparation (le garde-fou qui a manqué aux seedings 05/06, cf. l'enquête
  fiches du journal précédent). CLAUDE.md documente la convention.

## Notebook et docs

- Amorçage `PREV_TEST=None` : plus de chemin vers l'ancien monde — erreur
  claire « premier test d'une topologie : fournir un jeu initial dans
  TD/system/one_gen à la main (jeux historiques dans git : tests/01) ».
- Annexe 2-gen : `template_first_gen` / `template_second_gen` supprimés
  avec le répertoire (décision Rémi) — dernier commit les contenant :
  **`339b2b4`** (noté dans l'annexe, avec le geste de restauration).
- Encadré Prérequis : `FICTOMED_SRC`, convention du clone frère, rappel
  du piège `uv sync`/`uv run`.
- `docs/spec_testrun_run_stage.md` : mentions vivantes de l'ancien monde
  remplacées par des notes « retiré, historique dans git » (arborescence,
  amorçage/positions, §5, §8, §9, §11) ; les entrées de changelog
  (v3.3→v3.5) restent telles quelles. `.gitignore` : ligne
  `work_modif_prompts/tests/` retirée.
- `docs/etat_des_lieux_dev_rf.md` : document d'état des lieux daté, non
  touché (ses liens vers l'ancien monde sont historiques).
- `scripts/notion/` : CONSERVÉ (export des CRH vers Notion pour relecture
  DIM) — vérifié : aucune référence à `work_modif_prompts/`, rien à
  adapter ; son branchement sur les tests du banc reste un chantier futur.

## Grep préalable (rattachement complet)

Aucune dépendance de code imprévue. `bench/scenarios.py` (docstring de
provenance) et un output archivé du notebook restent comme mentions
historiques, avec les notes des docs.

## Vérifications

- pytest : mêmes résultats qu'au lot R1 (130 verts + l'échec préexistant
  de `test_pipelines`).
- Notebook rejoué sans clé jusqu'au dry-run 3.2 inclus (pilote
  `jupyter_client`), clone au nouvel emplacement : assertion bootstrap
  passée, SKIP attendus sur le test 06, prompt 0000 assemblé.

## Prochaines étapes

1. **Lot R3** : Rémi met à jour `~/Documents/fictomed` (git pull sur
   `prompt-work` ou la branche recommandée par Brest) → réinstallation
   éditable, smoke de chaîne scratch (fiches D508/F17x/Z37x attendues),
   journal, commit. Message à Brest (wheel 0.1.2, promotion
   enrichissement, doctrine E669x→E660x) — indépendant.
2. Relecture CRH 06 vs 05 et décisions en attente (statut alcool
   « occasionnel », puce CRO « Rappel clinique ») — inchangées.

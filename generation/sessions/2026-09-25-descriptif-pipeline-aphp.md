# Session du 25 septembre 2026 — descriptif du pipeline de données AP-HP

Dépôt de `docs/pipeline_donnees_aphp.md` (texte fourni par Rémi), après
confrontation au code, avec renvois et institution de la convention
« un pipeline = un descriptif ». Aucun code modifié, aucun appel payant.

## Vérification d'exactitude

Corrections de forme apportées au document :

- `verifier_source` et `SCHEMA_SOURCE` vivent dans `bench/banc.py`, pas
  dans `bench/scenarios.py` (les fonctions de données y restent) ;
  signature `verifier_source(source_path)`.
- `ref_substitution_imprecis.parquet` vit dans `data/aphp/`, à côté du
  corpus (chemin passé en `--ref`), pas dans `referentials/`.
- Variables de contexte : `duree`, `mode_entree`, `mode_sortie`, `mdp`
  distinguent les variantes d'un cas ; `mode_hospit` est constant au sein
  d'un cas (ligne séparée).
- Repli de spécialité : ~8 % des lignes de C1 (82 360), non ~1 %.
- Récap de `preparer_pool` : paires (type de séjour, spécialité) ; les
  paires (famille de template, spécialité) se lisent au tableau de
  contrôle du seeding.
- Contrainte d'IMC : E660x/E669x, E43 ou E44.0 (doctrine d'`anthropometrie.py`).
- Typologie : fournie par C1 et conservée, sinon calculée (`with_typologie`).
- Mapping : mention de `hors_vocabulaire: true` (décision du 25/09).
- Section 3 : date de naissance ajoutée au bloc patient (présente dans
  les prompts) ; titre en H1.

Écarts de fond signalés à Rémi, NON corrigés (voir le résumé de session) :
la flèche « TPEC/DPEC → famille de template » (la famille est attribuée
par fictomed au seeding, la typologie ne sert qu'aux strates du tirage) ;
trois mécanismes de l'étape B absents du texte (identifiants de
traçabilité, filtre DP « en 8 » actif par défaut, exclusion des séjours
incomplets pour fictomed avant le tirage) ; à l'étape C, le retrait de
`cage` du profil transmis ; la règle « tous les référentiels vivent dans
`referentials/` » non honorée par la référence de substitution.

État coché au 25/09 : patch fictomed fait (`60f210b`, `4795635` sur
`prompt-work`, fork ; PR Brest à ouvrir) ; référence déposée et
substitution réelle faite (24/09, 152 492 DP). Cascade `agean` (âge exact
de la branche courte) : ouverte, décision à prendre.

## Renvois

- Cellule markdown finale de `notebook_generation_bench.ipynb` → le
  descriptif (lien relatif, aucune copie).
- README : section « Pipelines de données » (machinerie générique,
  descriptif par instanciation, convention, lien).
- CLAUDE.md : section « Documentation » (spec + descriptif, convention).
- `docs/` n'a pas d'index et la spec n'a pas de section « documents
  liés » : rien ajouté là.

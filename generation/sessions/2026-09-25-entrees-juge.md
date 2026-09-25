# Session du 25 septembre 2026 (suite) — cellule « Préparer les entrées juge »

Section 4 du notebook de génération, après le bilan : une cellule
optionnelle qui, pour le test courant, (1) lance le nettoyage d'export
(`scripts/nettoie_dictionnaire.py`, sortie `export_dict/` du test),
(2) appelle `juge_io.ecrire_entrees_juge` vers
`generation/runs/<NN>/entrees_juge.jsonl`, (3) affiche le compte
d'entrées et les cinq premières lignes (scénario, code, nombre de
passages, fiche présente, libellé). Markdown au-dessus : à quoi servent
ces entrées (verdicts manuels aujourd'hui, encodeur demain, verdicts →
`prepare_regeneration`), contrat dans la docstring de `scripts/juge_io.py`.

- **`bench/banc.py`** : `preparer_entrees_juge(td, *, out_file, seuil,
  out_jsonl, apercu)` — sorties du script capturées et réimprimées
  (`_lancer_script`, comme `bilan`) ; sans CR nettoyable, message et liste
  vide, jamais d'exception. Le notebook n'est qu'un appel.
- **Découverte alignée** : `bench.seeding.scenario_dirs` ignore désormais
  `export_dict/` (comme `RESERVED_DIRS` des scripts) — sans quoi `generate`
  aurait pris le dossier d'export pour un scénario après un nettoyage.
  Spec §2 et §10 mises à jour ; test de découverte des noms réservés.
- Tests : 3 nouveaux (nettoyage puis JSONL et aperçu sur arbre jouet,
  sans CR → message, noms réservés) — 275 verts + l'échec préexistant.
- Rejeu sur `runs/07` (cellules paramètres, bootstrap, dossiers, entrées
  juge) : 15 scénarios nettoyés, `export_dict/` de 15 fichiers,
  `entrees_juge.jsonl` de 88 entrées.

Incident : l'insertion des cellules a écrit un `\\n` littéral après le
JSON du notebook (fichier invalide quelques minutes) — réparé par relecture
`raw_decode` et réécriture ; à fermer sans enregistrer puis rouvrir dans
VS Code.

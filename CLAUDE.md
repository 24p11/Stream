# CLAUDE.md

Stream — génération de comptes rendus d'hospitalisation (CRH) synthétiques à partir de
statistiques PMSI nationales et de LLM. Voir `README.md` pour l'architecture complète
(pipelines Brest et AP-HP, `cli.py`, `runner.py`, `core/`, `pipelines/`).

## Reprise de session

En début de session, lire le fichier le plus récent de `generation/sessions/` : c'est
le journal de travail versionné (une entrée courte par session — décisions, état,
prochaines étapes). En fin de session significative, y déposer une nouvelle entrée datée.

## Zone de travail courante (branche `dev_rf`)

- `generation/notebook_generation_bench.ipynb` : banc d'essai de génération AP-HP —
  suite courte d'appels (paramètres courants / avancés, puis environnement, pool,
  montage, seeding/figement, dry-run, run réel, vérificateur, bilan). Les fonctions
  de données sont dans `bench/scenarios.py`, l'orchestration (gardes, idempotence,
  messages) dans `bench/banc.py` ; `generation/notebook_annexes.ipynb` porte les
  annexes (2-gen, `prompt_local.py`, itération par copie, ajout de DAS).
- `enrichissement/` (racine) : package d'enrichissement des séjours, livrable destiné à fictomed.
- `generation/runs/0X/` : générations figées (ex-tests/0X), un dossier par scénario. On n'édite pas
  un jeu figé ; on itère par copie de dossier scénario (annexe C du notebook).

## Environnement

- fictomed s'installe en **éditable** depuis le clone local `FICTOMED_SRC`
  (convention : clone frère du repo, `~/Documents/fictomed`, remote CHU-Brest,
  branche `prompt-work` — chemin propre à chaque poste) :
  `uv pip install -e ~/Documents/fictomed`. Attention : `uv sync` **et**
  `uv run` réinstallent le paquet PyPI fictomed (wheel sans `regles_atih.yml`,
  quelle que soit sa version : seul le chemin, site-packages ou clone, fait
  foi) — refaire l'éditable après chaque sync, puis redémarrer le noyau ; la
  cellule bootstrap du notebook vérifie l'installation.

## Documentation

- `docs/spec_testrun_run_stage.md` : la spec du banc (API, arborescence d'un test,
  coûts) — mise à jour à chaque chantier qui change le banc.
- `docs/pipeline_donnees_aphp.md` : le descriptif du pipeline de données AP-HP
  (fichiers d'entrée et producteurs, transformations dans l'ordre, contenu du
  scénario final). Convention : un pipeline = un descriptif dans `docs/`, sur ce
  gabarit ; un chantier qui change le pipeline met à jour son descriptif — même
  règle que pour la spec.

## Conventions

- Langue de travail : français (code, commits, documents).
- Messages de commit courts et descriptifs, préfixés par la zone touchée
  (ex. « tests/05 : … », « enrichissement : … », « Notebook : … »).
- Branche de travail `dev_rf`, poussée sur le remote `fork` (24p11/Stream) ;
  `origin` est CHU-Brest/Stream.
- Jamais de clé API en dur (le notebook la lit depuis l'environnement).
- Ne pas lancer de runs LLM payants sans confirmation explicite.

# CLAUDE.md

Stream — génération de comptes rendus d'hospitalisation (CRH) synthétiques à partir de
statistiques PMSI nationales et de LLM. Voir `README.md` pour l'architecture complète
(pipelines Brest et AP-HP, `cli.py`, `runner.py`, `core/`, `pipelines/`).

## Reprise de session

En début de session, lire le fichier le plus récent de `work_prompts/sessions/` : c'est
le journal de travail versionné (une entrée courte par session — décisions, état,
prochaines étapes). En fin de session significative, y déposer une nouvelle entrée datée.

## Zone de travail courante (branche `dev_rf`)

- `work_prompts/notebook_generation_bench.ipynb` : banc d'essai de génération AP-HP
  (préparation des données, tirage des scénarios, figement des prompts, runs, bilan).
- `work_prompts/enrichissement/` : modules d'enrichissement des séjours (fictomed).
- `work_prompts/tests/0X/` : jeux de test figés, un dossier par scénario. On n'édite pas
  un jeu figé ; on itère par copie de dossier scénario (annexe C du notebook).

## Environnement

- fictomed s'installe en **éditable** depuis le clone local `FICTOMED_SRC`
  (convention : clone frère du repo, `~/Documents/fictomed`, remote CHU-Brest,
  branche `prompt-work` — chemin propre à chaque poste) :
  `uv pip install -e ~/Documents/fictomed`. Attention : `uv sync` **et**
  `uv run` réinstallent le fictomed PyPI 0.1.2 (cassé) — refaire l'éditable
  après chaque sync, puis redémarrer le noyau ; la cellule bootstrap du
  notebook vérifie l'installation.

## Conventions

- Langue de travail : français (code, commits, documents).
- Messages de commit courts et descriptifs, préfixés par la zone touchée
  (ex. « tests/05 : … », « enrichissement : … », « Notebook : … »).
- Branche de travail `dev_rf`, poussée sur le remote `fork` (24p11/Stream) ;
  `origin` est CHU-Brest/Stream.
- Jamais de clé API en dur (le notebook la lit depuis l'environnement).
- Ne pas lancer de runs LLM payants sans confirmation explicite.

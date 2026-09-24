# Session du 24 septembre 2026 (soir) — spécialité (service d'hospitalisation) des scénarios

Objectif : la spécialité devient une donnée du scénario, observée ou
dérivée, restituée telle quelle, vérifiée. Aucun appel payant.

## Prémisse corrigée — la ligne « - Service : » existait déjà

Tous les prompts des runs 01 à 06 (80/80) portent une ligne « - Service : »
: fictomed, quand le profil n'a pas de colonne `specialty`, joint lui-même
la **première** spécialité du dictionnaire par racine (`fictive.py`,
`group_by("drg_parent_code").agg(first())`) — sans groupe d'âge ni ratio.
Exemple run 06/0002 : `medical_outpatient`, 25 ans, racine 23M20 →
« PEDIATRIE NEUROLOGIE » (la ligne `lt_18` passait en premier). C'est la
source des « grosses erreurs » : non pas une invention du modèle, mais
une attribution aveugle en amont. Fournir `specialty` dans le pool
désactive cette jointure (colonne présente) ; une ligne en repli
(`specialty` nulle) n'a plus de ligne Service et le modèle choisit — le
« statu quo » visé par le chantier, différent du statu quo réel.

## Livré

- **`bench/scenarios.py`** : `reparer_racine` (racine = ghm2[:5] si nulle
  ou absente, trace `racine_reparee`, divergence observée ≠ ghm2[:5]
  signalée sans modification, sans racine ni ghm2 → erreur) ;
  `charger_mapping_type_unite` (seules les entrées `valide` hors `DERIVER`,
  refus d'une spécialité valide hors des 55 libellés) ;
  `deriver_specialite(df, dico, mapping)` en trois étages par ligne —
  observée (mapping), unique / tirée (dictionnaire brut `racine`, `age`,
  `lib_spe_uma`, `ratio_spe_racine`, ratios vérifiés sommant à 1 par
  (racine, age), groupe ge_18 / lt_18 dérivé d'`agean`, graine composite
  sha256 de `specialite ‖ id_scenario ‖ duree ‖ mode_entree ‖ mode_sortie ‖
  mdp`), repli compté. Colonnes `specialty` (traverse fictomed) et
  `specialite_source`.
- **`bench/banc.py`** : ordre `verifier_source → deriver_agean →
  reparer_racine → typologie → … tirage → deriver_specialite →
  enrichissement → contrôle contrat` ; récap : compteur de réparations,
  répartition des sources, table (TPEC, DPEC, spécialité, source) ; le
  tableau de contrôle du seeding affiche `department` et
  `specialite_source` (paires famille de template / spécialité).
  `SCHEMA_SOURCE` : `racine` statut `reparable` (nuls réparés, absente
  réparée si `ghm2`, ni l'une ni l'autre → non conforme). `specialite=False`
  rend l'ancien comportement.
- **`data/aphp/referentials/mapping_type_unite.yaml`** : construit,
  pré-rempli de 7 propositions (HC → DERIVER, GERIATRIE → MEDECINE INTERNE,
  NEONAT → NEONATOLOGIE, SC → DERIVER, SC-NEONAT → NEONATOLOGIE, HP →
  DERIVER, UHCD → DERIVER), effectifs et candidats en commentaire, règle
  d'usage en tête. Versionné en force (`git add -f`, `data/` est ignoré) :
  c'est une décision, pas une donnée. Toutes en `proposition` : rien n'est
  appliqué tant que Rémi n'a pas passé des entrées en `valide`.
- **`scripts/check_crh.py`** : `fidelite_service` — la ligne « - Service :
  X » du user prompt doit se retrouver dans le CR (casse, espaces, accents
  indifférents ; ponctuation conservée : restitution tel quel) ; pas de
  ligne → pas de contrôle.
- **Jeu 07** : `generation/runs/07/system/one_gen` monté par la chaîne
  depuis 06 (01–06 intacts), les 13 templates amendés sous « En entête :
  nom du service… » : « Le service d'hospitalisation fourni dans le
  scénario (ligne Service) est restitué TEL QUEL dans l'en-tête du compte
  rendu — ne le remplacez pas, ne le reformulez pas. En son absence,
  choisissez un service cliniquement cohérent avec la prise en charge. »
- **Notebook de données** : fiche 4 (YAML avec statuts, valeurs non
  couvertes, entrées appliquées), fiche 3 (répartition attendue des
  sources sur C1, consommateur `deriver_specialite`).
- Tests : 27 nouveaux (271 verts + l'échec préexistant) — les quatre de
  `reparer_racine`, mapping valide / proposition / hors vocabulaire,
  jointure unique, pondérée (0,6 / 0,3 / 0,1 à ±3 % sur 3 000 lignes),
  frontière 17 / 18 ans, graine composite (même `id_scenario`, contextes
  différents → deux candidates sortent ; lignes identiques → même résultat),
  ordre mélangé et deux processus, repli tracé, ratios ≠ 1 → échec,
  schéma brut, `preparer_pool` (récap, racine réparée, dictionnaire absent
  → refus explicite / `specialite=False`), `check_crh` (fourni présent,
  fourni absent → ECHEC, non fourni → rien, normalisation).

## Résultats sur C1

- Passe `preparer_pool("couverture")` : racine réparée sur 372 108 lignes
  (toute la branche courte), spécialité **unique 15, tiree 0, repli 1**
  (racine 22M02 « Brûlés » absente du dictionnaire) sur 16. Paires à
  regarder : « Bébé normal » et « Bébé néonat med » → OBSTETRIQUE (le
  dictionnaire rattache le nouveau-né à l'unité de la mère) ; « Médecine
  adultes > 3 nuits » sur la racine 14Z06 → OBSTETRIQUE ; « Médecine
  adultes < 3 nuits » sur 09M03 → CH.ORTHO.ET TRAUMATO.
- Sur tout C1 (3,4 s) : **unique 882 845 (81 %), tirée 113 083 (10 %),
  repli 91 597 (8 %)** — racines sans entrée en tête : 23M20 (24 844),
  23M06, 28Z17, 08M19, 19M02. Top spécialités : CH.ORTHO.ET TRAUMATO,
  MEDECINE INTERNE, CARDIOLOGIE, HEPATO-GASTRO-ENTERO, NEUROLOGIE,
  OBSTETRIQUE.
- **Traversée fictomed** (seeding scratch, hors `generation/runs/`) :
  `department` = `specialty` du pool sur 15/15 scénarios, la ligne
  « - Service : » porte la valeur dérivée, la ligne en repli n'a pas de
  ligne Service. Pour ce test : `cage` retirée du pool (collision
  `age`→`cage` du loader fictomed) et une ligne à `duree`/mode nuls écartée
  (fictomed élimine les profils incomplets — `age2`, `los`,
  `admission_mode`, `discharge_disposition`).
- `check_crh` sur run 06 : 3 ECHEC `fidelite_service` sur 14 (CANCERO
  ADULTE, CH.ORTHO.ET TRAUMATO, PED.HEPATO-GASTRO. — libellés abrégés
  développés par le modèle, sans instruction « tel quel » dans le jeu 06),
  11 restitués ; runs 01–05 : 1 à 2 par run. Ce ne sont pas des faux
  positifs du mécanisme : la prémisse « aucune ligne Service dans 06 »
  était fausse.

## Prérequis au seeding réel sur C1 (hors périmètre, à rappeler)

1. Patch fictomed de la collision `age` / `cage` (`_safe_rename`) — session
   fictomed séparée.
2. fictomed élimine les lignes sans `duree` / `mode_entree` /
   `mode_sortie` (97 034 lignes de la branche longue de C1) : à écarter
   avant le tirage, sinon `target_n` n'est pas atteint.
3. `_PMSI_PATTERNS["profiles"] = ("scenarios_*.parquet", "scenarios_*")` :
   fictomed prend le fichier `scenarios_*` le plus récent de `data/aphp/` —
   ici `scenarios_C1_dp.rapport.txt` a été pris comme profils actif
   (écrasé puis restauré par le `finally`). Écrire les rapports ailleurs,
   ou resserrer le motif côté fictomed.

## Questions consignées (aucune action)

- `id_ligne` unique par ligne à demander au producteur : la graine
  composite (`id_scenario` ‖ contexte) est le palliatif.
- Correction de `racine` côté producteur : le compteur de réparations doit
  tomber à 0 à la prochaine campagne.
- Les libellés validés du YAML doivent rester dans le vocabulaire des 55
  spécialités du dictionnaire (le lecteur le refuse sinon).
- Le dictionnaire ne couvre pas 91 597 lignes de C1 (racines 23M20,
  23M06, 28Z17…) : à compléter côté référentiel, ou accepter le repli.

## Prochaines étapes

1. Rémi : statuts du YAML (valide / proposition), relecture des paires
   surprenantes.
2. Prérequis fictomed ci-dessus, puis test 07 (`TEST_NUM = "07"`,
   `PREV_TEST = "06"`, source C1).

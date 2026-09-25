# Le pipeline de données AP-HP, de la campagne au prompt

*Descriptif de l'instanciation AP-HP de la chaîne : les données,
référentiels et règles métier propres au site. La machinerie en dessous
(bench/, fictomed, le format des tests) est générique et partagée — un
autre site (Brest…) brancherait ses propres fichiers et doctrines aux
mêmes étapes. Ce qui fait foi reste le code (`bench/scenarios.py`,
`bench/banc.py`), les contrats (`SCHEMA_SOURCE`, CONTRAT.md recode-icd) et
la spec. État au 25/09/2026.*

---

### 1) Les fichiers d'entrée

#### Le corpus de scénarios — `data/aphp/scenarios_C1.parquet` (~1 087 525 lignes)

Produit par le projet amont (tirage depuis la base nationale PMSI
fictive). Une **ligne = une variante de séjour** ; un **`id_scenario` = un
cas clinique** (jusqu'à 77 variantes de contexte par cas).

| Variable | Contenu | Particularités (C1) |
|---|---|---|
| `id_scenario` | identifiant du cas clinique | non unique par ligne (474 077 valeurs) |
| `branche` | `long` / `court` | |
| `diag2` | le DP | contient des codes « sans précision » |
| `diagnostic_associes` | les DAS | |
| `racine` / `ghm2` | racine de GHM / GHM complet | `racine` nulle sur toute la branche courte (erreur, correction amont prévue) |
| `cage` | classe d'âge `[a-b[` | |
| `age` | pivot `ge_18`/`lt_18` (longs) **ou** âge exact en chaîne (courts) | double nature selon la branche |
| `sexe` | encodage PMSI 1/2 | |
| `type_unite` | GERIATRIE, HC, HP, NEONAT, SC, SC-NEONAT | nulle sur les courts ; UHCD attendu campagne 2 |
| `duree`, `mode_entree`, `mode_sortie`, `mdp` | contexte de séjour | distinguent les variantes d'un cas |
| `mode_hospit` | HC / HP | constant au sein d'un cas |

**`agean` (âge numérique) est absent par construction** : l'âge exact est
agrégé en classes dès l'extraction (protection) — la chaîne le dérive
(§2).

#### Les référentiels — `data/aphp/referentials/`

| Fichier | Rôle | Producteur |
|---|---|---|
| `ref_substitution_imprecis.parquet` (dans `data/aphp/`, à côté du corpus ; chemin passé en `--ref`) | candidats de remplacement des DP imprécis, pondérés (`nb`) par strate (cat, cage, sexe) | plateforme nationale (export seuillé) |
| `dictionnaire_spe_racine.parquet` | (racine, `ge_18`/`lt_18`) → spécialités avec `ratio` (somme = 1) | Rémi — 864 lignes, 624 racines, 55 spécialités |
| `mapping_type_unite.yaml` | type_unite → spécialité (libellé du dictionnaire, ou hors vocabulaire assumé par `hors_vocabulaire: true`) ou `DERIVER` ; seules les entrées `statut: valide` s'appliquent | Rémi |
| Librairie de fiches (livraison recode-icd) | fiches descriptives des codes, sous contrat (`index.csv` fait foi, `DEPLOIEMENT.txt` = version installée) | recode-icd |
| Référentiels fictomed (`chu`, spécialités UMA, CIM…) | identité fictive, libellés | AP-HP |

*Règle générale : tous les référentiels vivent dans
`data/aphp/referentials/` ; le code n'embarque jamais de données.*

---

### 2) Les transformations, dans l'ordre d'exécution

#### Étape A — hors notebook, fichier → fichier (une fois par campagne)

**Substitution des DP imprécis** — `scripts/substituer_dp_imprecis.py` :
`scenarios_C1.parquet` → `scenarios_C1_dp.parquet` + rapport. Tout DP
« sans précision » est remplacé par un code précis de la même catégorie,
tiré au sort **pondéré par les effectifs réels** (`nb`) dans la strate
(cage, sexe), avec repli hiérarchique ; conservé si aucun candidat précis
n'existe. Exemption UHCD (sans objet en C1 — compteur attendu à 0). Graine
sha256 par `id_scenario` → toutes les variantes d'un cas gardent le même
DP. DAS intouchés. Trace : `dp_origine`, `dp_substitue`,
`repli_substitution`.

#### Étape B — dans `preparer_pool()` (`bench/banc.py`), à chaque préparation de test

Ordre impératif — les fonctions de données vivent dans
`bench/scenarios.py` ; `verifier_source` et `SCHEMA_SOURCE` dans
`bench/banc.py` :

1. **`verifier_source(source_path)`** — conformité au contrat
   `SCHEMA_SOURCE` (colonnes, types, encodages ; échec explicite sinon).
2. **`deriver_agean(df)`** — l'âge numérique : un `agean` fourni est lu
   tel quel ; sinon tirage entier uniforme dans les bornes de `cage`,
   graine sha256 par `id_scenario` (domaine `agean`), resserré pour
   respecter le pivot `ge_18`/`lt_18`.
3. **`reparer_racine(df)`** — garde-fou : `racine = ghm2[:5]` quand
   `racine` est nulle ; trace `racine_reparee` ; compteur destiné à 0
   après la correction amont.
4. **Typologie + tirage** — type de prise en charge TPEC/DPEC (fournie
   par C1 et conservée telle quelle, sinon calculée par
   `with_typologie` ; → **famille de template**), puis
   `tirage_stratifie` selon `QUOTAS` (dict, `"couverture"` = 1 par
   type, ou None).
5. **`deriver_specialite(df, dico, mapping)`** — trois étages, **par
   ligne** (la spécialité est une propriété du séjour, pas du cas) :
   - étage 1 : entrée `valide` du YAML pour `type_unite` → source
     `observee` ;
   - étage 2 : dictionnaire sur (racine réparée, groupe d'âge dérivé
     d'`agean`) — candidate unique (`unique`) ou tirage pondéré par
     `ratio`, graine composite `id_scenario` + contexte (`tiree`) ;
   - étage 3 : rien au dictionnaire → pas de spécialité, le modèle
     proposera (`repli`, ~8 % des lignes de C1 ; 1 à 2 sur un pool
     « couverture » de 15).
6. **Enrichissement** (package `enrichissement/`) — ordre interne
   load-bearing intoxications → anthropométrie ; Politique : exclusions
   (mineurs, O00-O99, Z94, T86), tabac/alcool (codes F17/F10 en DAS +
   étiquettes factuelles), corpulence (IMC contraint par un E660x/E669x,
   E43 ou E44.0 présent, sinon tiré Esteban/DNID — toute classe ≥ 25
   codée E660x en DAS). Colonnes : `taille_cm`, `poids_kg`, `imc`,
   `tabac`, `alcool`, `codes_ajoutes`, `enrichi`.
7. **Contrôle du contrat fiches** (`bench/fiches`) — chaque code du pool
   a sa fiche (absences journalisées), codes d'enrichissement émissibles.

Le récap affiche : tirage par type, réparations racine, répartition
`specialite_source`, paires (type de séjour, spécialité), lignes
enrichies/exclues ; les paires (famille de template, spécialité) se
lisent au tableau de contrôle du seeding.

#### Étape C — au seeding (`seeder()` puis fictomed)

La chaîne fictomed (`generate_and_select_fictomed_scenarios`) transforme
chaque ligne du pool en **séjour fictif** : identité inventée (patient,
médecin, dates cohérentes avec `duree`), hôpital tiré au sort (référentiel
CHU), `specialty` → ligne « - Service : », texte de contexte
d'hospitalisation (depuis `mdp` et les modes), reconstruction des lignes
DAS avec **libellés officiels et fiches descriptives**. Puis côté Stream :
`user_fn_enrichi` insère le bloc Taille/Poids/IMC/Tabac/Alcool, le prefix
du jeu remplace celui de fictomed, `seed_user_prompts` écrit les fichiers,
le figement copie le prompt système de la famille.

---

### 3) Le scénario final — le contenu du prompt utilisateur

Le bloc « SCÉNARIO DE DÉPART » d'un `user_generation.txt` porte :

- **Âge** (`agean`) · **Sexe** · **Patient** (nom, prénom, date de
  naissance) et **médecin** (fictifs) · **Dates** d'entrée/sortie ·
  **Modes** · **Contexte de l'hospitalisation** ;
- **Taille, Poids (IMC), Tabac, Alcool** (enrichissement — données à
  reformuler, valeurs exactes) ;
- **Service** (spécialité observée ou dérivée ; absente si `repli`) ·
  **Hôpital** ;
- **Codage CIM-10** : DP (substitué le cas échéant) et DAS (y compris les
  codes ajoutés F17/F10/E660x), chaque code avec son libellé officiel ;
- **Acte CCAM** (racines chirurgicales/interventionnelles) ;
- puis les **fiches descriptives** de chaque code (librairie recode-icd).

Le prompt **système** (le jeu de la famille, versionné dans
`generation/runs/NN/system/one_gen/`) porte les règles de rédaction — dont
la restitution fidèle des données fournies, qui rend le tout vérifiable
par `scripts/check_crh.py`.

---

### État — à cocher quand c'est fait

- [ ] Cascade `agean` : lire l'`age` exact de la branche courte au lieu
      de tirer (retouche demandée — décision à prendre, non livrée au
      25/09/2026)
- [x] Patch fictomed collision `age`/`cage` au loader (prérequis du
      seeding sur C1) — fait le 25/09/2026 : commits `60f210b`
      (`_safe_rename`) et `4795635` (motifs de profils avec extension)
      sur `prompt-work`, poussés sur `fork/prompt-work` ; à intégrer côté
      CHU-Brest (PR à ouvrir)
- [x] Dépôt de `ref_substitution_imprecis.parquet` + substitution réelle
      (prérequis du fichier `_dp`) — fait le 24/09/2026 : 152 492 DP
      substitués sur 1 087 525 lignes, 0 conservé UHCD, 27 741 conservés
      faute de candidat

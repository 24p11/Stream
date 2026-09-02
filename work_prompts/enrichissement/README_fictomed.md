# Enrichissement de scénarios AP-HP — package pour fictomed

Trois modules qui enrichissent un scénario CIM-10 (DP, DAS, âge, sexe) avec
des **codes DAS** (F17/F10 tabac-alcool, E660x obésité) et des **variables
descriptives** (taille, poids, IMC, statuts tabac/alcool, contexte) tirées de
lois calibrées sur les données françaises (Esteban 2014-2016, Obépi 2020/2012,
répartition réelle des codes d'intoxication). Auteur de la doctrine : RF.

## Modules

- `intoxications.py` — statuts tabac/alcool cohérents avec les codes du
  scénario ; tirage pondéré d'un code F17/F10 sinon ; contexte de
  polyaddiction (F11/F12/F14/F16) qui biaise vers les usages actifs.
- `anthropometrie.py` — taille/poids/IMC par sexe et âge (Esteban croisé) ;
  contraints par un code présent (E660x, série E669x « sans précision » —
  bornes des libellés ATIH, E6693 = surpoids [25,30[ —, E43, E440) ;
  corpulence DNID si E11* ; jamais de dénutrition ni d'obésité grade IV
  en tirage libre.
- `enrichissement.py` — l'orchestration : `Politique`, `enrichir_scenarios`,
  `bloc_contexte`. **L'ordre est load-bearing** : intoxications puis
  anthropométrie, chaque étape lisant le scénario complet (DP + DAS déjà
  enrichis). Les codes ajoutés le sont toujours en DAS, jamais en DP.

`integration_stream.py` est la colle avec le banc d'essai Stream — **ne pas
le copier** dans fictomed.

## Entrées / sorties

`enrichir_scenarios(df, seed, politique=Politique()) -> DataFrame` (polars) :

- lit `icd_primary_code`, `icd_secondary_code` (liste ou chaîne
  espace-séparée — type préservé en sortie), `age` (repli `age2`), `sexe`
  (PMSI 1/2) ; codes **compacts** sans point (`E1120`) — les conventions
  internes de fictomed (relevées sur `sites/aphp` : loader, scenario, prompt) ;
- ajoute `taille_cm`, `poids_kg`, `imc`, `classe_imc`, `tabac`, `alcool`,
  `contexte_texte`, `codes_ajoutes` (chaîne espace-séparée), `enrichi` (bool),
  et étend le DAS ;
- **déterministe à `seed` et ordre des lignes fixés** (les lignes exclues ne
  consomment aucun tirage).

`bloc_contexte(ligne) -> str` : lignes patient prêtes pour le prompt user,
dans le style des lignes existantes (`- Taille : 176 cm`, `- Poids : 81 kg
(IMC 26,1)`, `- Tabac : ex-fumeur, sevré depuis 8 ans (18 paquets-années)`,
`- Alcool : pas de mésusage`) ; chaîne vide si `enrichi=False`.

## Politique (les décisions, ajustables)

`Politique(age_min=18, prefixes_exclusion=("O", "Z94", "T86"),
p_tabac=0.30, p_alcool=0.10, p_tabac_poly=0.90, p_alcool_poly=0.70,
feuilles_seulement=True)`

- moins de `age_min` ans, grossesse (O00-O99) ou transplanté (Z94/T86) :
  ligne passée **intacte** (`enrichi=False`) ;
- **règle de codage anthropométrique (doctrine révisée RF)** : un code E66*
  (E660x, E669x) ou de dénutrition (E43, E440) déjà présent est conservé tel
  quel — il contraint l'IMC et rien n'est ajouté ; sinon le codage est
  **systématique** dès IMC >= 25 : E6603 [25,30[ (« Surpoids dû à un excès
  calorique »), E6604 [30,35[, E6605 [35,40[, E6606 [40,50[, E6607 [50,60[
  (le grade IV est tirable, poids 0.01, puisque toujours codé).

## Brancher dans fictomed

1. Copier ce dossier dans fictomed (sans `integration_stream.py`).
2. Appeler `enrichir_scenarios` sur le DataFrame de profils **avant
   `build_scenario`** : fictomed génère alors lui-même les lignes
   « Diagnostics associés » (libellés officiels du référentiel) et les
   **fiches descriptives** des codes ajoutés — vérifié de bout en bout côté
   Stream. (Après `build_scenario`, il faudrait étendre soi-même
   `text_secondary_icd_official` : à éviter.)
3. Appeler `bloc_contexte(scenario)` depuis le template du prompt user, à la
   suite des lignes d'identité (`- Sexe du patient : ...`).
4. Régler la `Politique` si besoin ; passer une `seed` pour la
   reproductibilité.

## Note E669x (profils sources)

Les profils AP-HP portent des codes « sans précision » E669x : ils seront
convertis en E660x **en amont par RF** (préparation des données). Les
contraintes E669x du module restent en place **en défense** : un E669x qui
passerait quand même contraint l'IMC selon les bornes de son libellé ATIH
(E6693 = surpoids [25,30[) et n'entraîne aucun ajout.

## Note PMSI

Un E660x/F17/F10 ajouté en DAS ne modifie pas le GHM stocké du séjour source
(pas de regroupage) — accepté pour un corpus d'entraînement : le lien
texte↔codes du document reste exact, c'est lui qui compte.

## Validation

- Auto-contrôles épidémiologiques : `python -m <package>.intoxications` et
  `.anthropometrie` reproduisent les marges Esteban/Obépi et les fréquences
  de codes attendues ; `.enrichissement` montre une table complète.
- Suite de tests côté Stream : déterminisme, codes en DAS uniquement,
  politique (mineurs, grossesse, transplantés), corpulence DNID, contraintes
  E660x/E669x/E43/E440, codage systématique par classe d'IMC, format des
  blocs.

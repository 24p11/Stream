# Session du 25 septembre 2026 (fin) — quatre arbitrages sur le descriptif du pipeline

Suite du commit `41ab943` (dépôt de `docs/pipeline_donnees_aphp.md`) :
Rémi a tranché les écarts de fond signalés.

1. **Typologie = strates du tirage** ; la famille de template est choisie
   par fictomed au seeding — reformulé dans le document (étape B.4).
2. **Étape 4 bis ajoutée** : `ensure_source_ids`, le **filtre DP**
   (`filtre_dp_suffixe="8"` par défaut : seuls les DP en 8 sont tirés,
   choix de campagne ; `filtre_dp_suffixe=None` / `FILTRE_DP_SUFFIXE = None`
   pour tirer sur tout le corpus), l'exclusion des séjours incomplets pour
   fictomed ; récap complété.
3. **Retrait de `cage` dans `seeder` SUPPRIMÉ** (`bench/banc.py`) : le
   patch fictomed `60f210b` le rend obsolète, et le garder masquerait une
   régression du loader. Test inversé (le profil est transmis tel quel,
   `cage` comprise). Traversée fictomed revalidée : `seeder` réel sur une
   copie scratch du jeu 07 avec le pool « couverture » de
   `scenarios_C1_dp.parquet`, `cage` transmise → 15 scénarios, `cage`
   présente dans le scénario fictomed, `department` = `specialty`, 15/15
   prompts avec la ligne Service attendue. Le document n'en dit rien.
4. **`ref_substitution_imprecis.parquet` déplacée dans
   `data/aphp/referentials/`** — fiche 2 du notebook de données, exemple
   `--ref` de la docstring et aide du script, document : la règle « tous
   les référentiels vivent dans `referentials/` » est sans exception.
5. Au passage : la ligne `ONLY = None` de la cellule du run réel du
   notebook est supprimée (doublon qui écrasait le paramètre courant ; le
   paramétrage vit une seule fois, en tête).

Vérifications : 275 verts + l'échec préexistant ; notebook de génération
rejoué sans clé sur `runs/07` jusqu'au dry-run, bilan et entrées juge (0
erreur, mêmes SKIP) ; notebook de données rejoué (0 erreur, fiche 2 sur le
nouveau chemin). À rappeler à Brest : sans le patch `60f210b`, le seeding
d'une campagne échoue de nouveau (`DuplicateError` sur `cage`) — c'est
voulu, la chaîne ne masque plus le loader.

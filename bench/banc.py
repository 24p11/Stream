"""Orchestration du banc d'essai — les étapes du notebook de génération.

Chaque fonction reprend TEL QUEL le code d'une (ou plusieurs) cellule(s)
du notebook ``generation/notebook_generation_bench.ipynb`` d'avant
l'amincissement (septembre 2026) : mêmes gardes, mêmes messages, même
idempotence. Le notebook n'est plus qu'une suite courte d'appels ; les
paramètres qui vivaient en cellules sont les arguments de ces fonctions,
avec les mêmes défauts.

Correspondance cellule d'origine → fonction :

- bootstrap (assertion fictomed) + contrôle du contrat fiches + sonde du
  lecteur → :func:`verifier_environnement` ;
- NOUVEAU : contrôle des prérequis du fichier de scénarios →
  :func:`verifier_source` (:data:`SCHEMA_SOURCE`) ;
- import des données, typologie, identifiants, filtre DP, tirage
  stratifié, enrichissement, contrôle du contrat côté pool →
  :func:`preparer_pool` ;
- paramétrage des chemins → :func:`dossiers_test` ; état du test →
  :func:`etat_test` ; montage du jeu → :func:`monter_jeu` ;
- génération fictomed + graine + prefix du jeu + figement →
  :func:`seeder` ; prompts partagés du vérificateur →
  :func:`prompts_verificateur` ;
- client Mistral → :func:`mistral_client` ; affichage du dry-run →
  :func:`show_first_prompt` ; lecture des CR → :func:`afficher_crh`,
  :func:`ecrire_apercus_md` ; contexte du vérificateur →
  :func:`contexte_verificateur` ;
- bilan (coûts, journal CSV, check_crh, reancre_crh) → :func:`bilan`.

``generate`` (bench.generate) reste appelé directement par le notebook.
Les fonctions qui appellent fictomed (:func:`verifier_environnement`,
:func:`seeder`) ne sont pas couvertes par les tests unitaires : le rejeu
du notebook en tient lieu.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from types import EllipsisType
from typing import Any

import polars as pl

from bench.costs import summarize_costs
from bench.errors import BenchError
from bench.fiches import charger_index, codes_emissibles, codes_sans_fiche
from bench.generate import GenResult, load_reports
from bench.scenarios import (
    COLONNES_TYPOLOGIE,
    DPEC_TO_TPEC,
    charger_mapping_type_unite,
    deriver_agean,
    deriver_specialite,
    ensure_source_ids,
    generate_and_select_fictomed_scenarios,
    reparer_racine,
    resolve_parquet_path,
    tirage_stratifie,
    with_typologie,
    write_fictomed_config,
)
from bench.seeding import (
    copy_system_prompts,
    scenario_dirs,
    seed_user_prompts,
    write_prompts,
)

# ---------------------------------------------------------------------------
# Chemins du dépôt (le notebook vit dans generation/, les runs sous
# generation/runs/, les données non versionnées sous data/aphp/)
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[1]
WORK_DIR = REPO_ROOT / "generation"
TESTS_DIR = WORK_DIR / "runs"  # versionné et partagé (§9)
USAGE_LOG = WORK_DIR / "usage_log.csv"
DATA_APHP = REPO_ROOT / "data" / "aphp"
REFERENTIALS = DATA_APHP / "referentials"
SCRIPTS_DIR = REPO_ROOT / "scripts"

# Clone fictomed éditable — FICTOMED_SRC est propre à chaque poste
# (convention : clone frère du repo, remote CHU-Brest, branche prompt-work).
FICTOMED_SRC = Path.home() / "Documents" / "fictomed"

# Colonnes du tableau de contrôle du tirage (récap avant écriture) —
# retenues après inspection du schéma fictomed (55 colonnes) :
# identifiant, famille, mode de prise en charge (code), âge, sexe (1/2,
# codage PMSI), diagnostic principal (libellé + code), nb de DAS.
RECAP_TIRAGE_COLUMNS = [
    "generation_id",
    "template_name",
    "case_management_type",  # code du mode de prise en charge (libellé souvent vide)
    "age",
    "sexe",
    "icd_primary_description",
    "icd_primary_code",
    "nb_associated",
]

_COLONNES_CONTROLE = ("TPEC", "DPEC", *RECAP_TIRAGE_COLUMNS,
                      "department", "specialite_source",  # spécialité (service) — paires (famille, spécialité)
                      "taille_cm", "poids_kg", "imc", "tabac", "alcool",
                      "codes_ajoutes")

# Colonnes du profil que fictomed exige non nulles (fictive.py, required_cols :
# age2, los, admission_mode, discharge_disposition — noms Stream ci-dessous) ;
# les lignes incomplètes sont écartées avant le tirage.
COLONNES_REQUISES_FICTOMED = ("agean", "duree", "mode_entree", "mode_sortie")

# Référentiels de la spécialité (service d'hospitalisation) — voir
# bench.scenarios.deriver_specialite : le dictionnaire fait foi pour l'étage 2,
# le mapping type_unite (statuts valide / proposition) pour l'étage 1.
DICO_SPECIALITE = "dictionnaire_spe_racine.parquet"
MAPPING_TYPE_UNITE = "mapping_type_unite.yaml"


def _chemin(p: Path | str) -> Path:
    """Chemin absolu : un chemin relatif s'entend depuis la racine du dépôt."""
    p = Path(p).expanduser()
    return p if p.is_absolute() else REPO_ROOT / p


def _afficher(obj: Any) -> None:
    """``display`` IPython quand il est disponible (rendu tableau dans le
    notebook), ``print`` sinon (tests, scripts)."""
    try:
        from IPython.display import display
    except ImportError:  # pragma: no cover - IPython est une dépendance du notebook
        print(obj)
        return
    display(obj)


# ---------------------------------------------------------------------------
# Environnement — assertion fictomed, contrat fiches, sonde du lecteur
# ---------------------------------------------------------------------------

def verifier_environnement(
    *,
    fictomed_src: Path = FICTOMED_SRC,
    referentials: Path = REFERENTIALS,
) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Les trois gardes de l'environnement, dans l'ordre : fictomed est
    l'éditable attendu (clone ``fictomed_src``), les deux bibliothèques de
    fiches respectent le contrat recode-icd (``bench.fiches`` — l'index
    fait foi), et le LECTEUR fictomed les lit (registre chargé par le code
    fictomed lui-même, cohérent avec l'index à 10 % près).

    Retourne les deux index chargés (fiches, catégories). Échec bruyant
    (``RuntimeError`` / :class:`BenchError`) au premier écart.
    """
    import importlib.util as _ilu

    _spec_fictomed = _ilu.find_spec("fictomed")
    _fictomed_file = (
        Path(_spec_fictomed.origin).resolve()
        if _spec_fictomed and _spec_fictomed.origin else None
    )
    if _fictomed_file is None or not _fictomed_file.is_relative_to(
            Path(fictomed_src).expanduser().resolve()):
        raise RuntimeError(
            "fictomed n'est pas l'éditable attendu — trouvé : "
            f"{_fictomed_file}. Réparation : uv pip install -e {fictomed_src} "
            "(cloner CHU-Brest/fictomed, branche prompt-work, si absent). "
            "Rappel : uv sync / uv run réinstallent le paquet PyPI (wheel sans "
            "regles_atih.yml, quelle que soit sa version : seul le chemin, "
            "site-packages ou clone, fait foi) — refaire l'éditable après chaque "
            "sync, puis redémarrer le noyau."
        )

    print("Racine repo  :", REPO_ROOT)
    print("bench        :", Path(__file__).resolve().parent)
    print("fictomed     :", _fictomed_file)

    # Contrôle du contrat fiches recode-icd (bench.fiches — l'index fait foi,
    # CONTRAT.md du producteur), puis sonde du LECTEUR : vérification de bout
    # en bout — non pas « la librairie est conforme » mais « le lecteur la lit ».
    _referentials = Path(referentials)
    _index_fiches = charger_index(_referentials / "cards_library")
    _index_categories = charger_index(_referentials / "cards_library_categories")

    # Sonde du registre fictomed — chargé par le code fictomed lui-même, sur
    # les chemins que write_fictomed_config met dans le servers.yaml courant
    # (<referentials>/cards_library*). Le registre normalise et déduplique :
    # cohérence attendue avec l'index à 10 % près, jamais vide.
    from fictomed.sites.aphp.code_cards import CodeCardsRegistry

    _reg = CodeCardsRegistry.from_dirs(
        exact_dir=_referentials / "cards_library",
        category_dir=_referentials / "cards_library_categories",
    )
    _n_exactes, _n_categories = len(_reg.exact_index), len(_reg.category_index)
    if not (_n_exactes >= 0.9 * _index_fiches.height
            and _n_categories >= 0.9 * _index_categories.height):
        raise RuntimeError(
            "fictomed ne lit pas la librairie déployée (schéma ? version du "
            f"clone ?) — registre : {_n_exactes} exacte(s) pour "
            f"{_index_fiches.height} à l'index, {_n_categories} catégorie(s) "
            f"pour {_index_categories.height} — vérifier le patch de "
            "compatibilité fichier/filepath (commit 4386ad5)."
        )
    print(f"Registre fictomed : {_n_exactes} fiches exactes, {_n_categories} "
          f"catégories (index : {_index_fiches.height} / "
          f"{_index_categories.height}) — le lecteur lit la librairie.")
    return _index_fiches, _index_categories


# ---------------------------------------------------------------------------
# Fichier de scénarios — prérequis (NOUVEAU)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Exigence:
    """Exigence sur une colonne du fichier de scénarios (:data:`SCHEMA_SOURCE`).

    ``statut`` : ``"obligatoire"`` (la chaîne la lit toujours),
    ``"typologie"`` (requise seulement quand le fichier ne fournit pas déjà
    ``TPEC``/``DPEC`` — c'est ``with_typologie`` qui la lit),
    ``"derivee"`` (``agean`` : lue si présente, sinon DÉRIVÉE de ``cage`` par
    ``deriver_agean`` — variable dérivée, jamais une donnée observée),
    ``"derivation"`` (requise seulement quand ``agean`` est absente : ce sont
    les entrées de la dérivation), ``"reparable"`` (``racine`` : réparée
    depuis ``ghm2[:5]`` quand elle est nulle ou absente — sans ``racine`` ni
    ``ghm2`` le fichier est non conforme), ou ``"facultative"`` (lue si
    présente).
    ``type`` : ``"chaine"``,
    ``"numerique"``, ``"entier"``, ``"booleen"`` ou ``"chaine_ou_entier"``.
    ``valeurs`` :
    ensemble fermé des valeurs admises (contrôle d'encodage, sur la forme
    texte). ``motif`` : expression régulière que chaque valeur non vide doit
    respecter (contrôle de forme). ``nuls`` : nuls tolérés. ``role`` : qui
    la consomme, et pour quoi (documentation).
    """

    statut: str
    type: str
    role: str
    valeurs: tuple[str, ...] | None = None
    motif: str | None = None
    nuls: bool = True


# Forme constatée d'un code CIM-10 compact : lettre, deux chiffres, extension
# alphanumérique, extension ATIH « +n » admise (« F03+02 », « R53+1 »).
_CODE_CIM = r"[A-Z][0-9]{2}[A-Z0-9]*(\+[0-9A-Z]+)?"
# Un DAS est une suite de codes séparés par des espaces ; le jeton « NA »
# (valeur manquante d'origine) est toléré : fictomed et l'enrichisseur
# l'ignorent (_parse_secondary_codes, _lire_das).
_DAS = rf"({_CODE_CIM}|NA)"

# Schéma attendu du fichier de scénarios — établi sur ce que la chaîne
# consomme RÉELLEMENT (septembre 2026) :
# - bench.scenarios.with_typologie : ghm2, racine, diag2, duree, mode_hospit,
#   agean (COLONNES_TYPOLOGIE) ;
# - preparer_pool : filtre sur diag2 ; quotas sur DPEC/TPEC ;
# - enrichissement (enrichissement/integration_stream.py → enrichissement.py) :
#   diag2 → icd_primary_code, diagnostic_associes → icd_secondary_code (chaîne
#   de codes séparés par des espaces), agean → age2 (nul = ligne exclue), sexe
#   (PMSI 1/2 : `int(sexe) == 2`), nbda mis à jour ;
# - fictomed (sites/aphp/loader.py `_PROFILE_RENAME`, scenario.py) : sexe
#   (`int(profile["sexe"])`, prénoms), diag2, diagnostic_associes, agean → age2
#   (sinon age → cage, classe d'âge tirée au sort), duree → los, mode_hospit →
#   admission_type (HP = ambulatoire), mode_entree → admission_mode,
#   mode_sortie → discharge_disposition, racine → drg_parent_code, mdp →
#   case_management_type, n → nb, nbda → nb_associated ;
# - contrôle du contrat fiches : diag2, diagnostic_associes (codes du pool).
# Colonnes des campagnes récentes (scenarios_bn_pmsi) et de l'étape amont de
# substitution des DP imprécis (scripts/substituer_dp_imprecis.py) : reconnues
# et documentées. Les campagnes ne livrent pas l'âge exact (agrégé en classes
# `cage` dès l'extraction, protection assumée) : `agean` y est DÉRIVÉE de
# `cage` (deriver_agean, graine par id_scenario) — d'où `cage` et
# `id_scenario` requises quand `agean` est absente.
SCHEMA_SOURCE: dict[str, Exigence] = {
    "diag2": Exigence(
        "obligatoire", "chaine",
        "DP CIM-10 compact (sans point, extension ATIH « +n » admise) — typologie (séances), filtre DP, "
        "enrichissement (icd_primary_code), fictomed, contrôle des fiches",
        motif=rf"^{_CODE_CIM}$", nuls=False),
    "diagnostic_associes": Exigence(
        "obligatoire", "chaine",
        "DAS : codes compacts séparés par des espaces (« NA » toléré), chaîne vide admise — "
        "enrichissement (icd_secondary_code), fictomed, contrôle des fiches",
        motif=rf"^{_DAS}( {_DAS})*$"),
    "sexe": Exigence(
        "obligatoire", "chaine_ou_entier",
        "sexe PMSI 1/2 — enrichissement (probabilités, textes), fictomed "
        "(int(sexe), prénoms)",
        valeurs=("1", "2"), nuls=False),
    "agean": Exigence(
        "derivee", "numerique",
        "âge en années — typologie (adulte), enrichissement (age2 : nul = "
        "ligne exclue), fictomed (age2). Lue telle quelle si le fichier la "
        "fournit (ancien format) ; sinon DÉRIVÉE de cage (tirage entier "
        "uniforme, déterministe par id_scenario) : variable dérivée que le "
        "CRH utilise, jamais une donnée observée"),
    "age": Exigence(
        "facultative", "chaine",
        "pivot ge_18 / lt_18 (branche longue des campagnes) : borne le tirage "
        "d'agean à la frontière des 18 ans ; ancien format : classe d'âge, "
        "repli fictomed (cage) quand agean est nul ; âge numérique en chaîne "
        "(branche courte de C1) : sans effet, signalé"),
    "ghm2": Exigence(
        "typologie", "chaine",
        "GHM (CMD, type, sévérité) — typologie"),
    "racine": Exigence(
        "reparable", "chaine",
        "racine de GHM — typologie ; fictomed (drg_parent_code) ; spécialité "
        "(dictionnaire par racine). RÉPARABLE depuis ghm2[:5] quand nulle ou "
        "absente (reparer_racine, compteur au récap — doit valoir 0 après la "
        "correction amont) ; une racine observée divergente est signalée, "
        "jamais modifiée"),
    "duree": Exigence(
        "obligatoire", "numerique",
        "durée de séjour — typologie (borne 3 nuits), fictomed (los)"),
    "mode_hospit": Exigence(
        "obligatoire", "chaine",
        "HC / HP — typologie (HDJ), fictomed (admission_type)",
        valeurs=("HC", "HP"), nuls=False),
    "mode_entree": Exigence(
        "facultative", "chaine", "fictomed (admission_mode, dates de séjour)"),
    "mode_sortie": Exigence(
        "facultative", "chaine", "fictomed (discharge_disposition)"),
    "mdp": Exigence(
        "facultative", "chaine",
        "mode de prise en charge — fictomed (case_management_type), récap"),
    "n": Exigence("facultative", "entier", "effectif du profil — fictomed (nb)"),
    "nbda": Exigence(
        "facultative", "entier",
        "nombre de DAS — mis à jour par l'enrichissement, fictomed "
        "(nb_associated)"),
    "TPEC": Exigence(
        "facultative", "chaine",
        "typologie fournie par le fichier (sinon calculée par with_typologie)"),
    "DPEC": Exigence(
        "facultative", "chaine",
        "typologie fournie par le fichier (sinon calculée) — clés des quotas"),
    # --- campagnes récentes (scenarios_bn_pmsi) ---
    "id_scenario": Exigence(
        "derivation", "chaine",
        "identifiant du scénario amont — clé des graines (substitution des DP, "
        "dérivation d'agean) ; obligatoire quand agean est absente ; non "
        "unique par ligne (variantes de contexte de séjour d'un même scénario)",
        nuls=False),
    "branche": Exigence(
        "facultative", "chaine",
        "long / court — axe du rapport de substitution ; non lue par la chaîne"),
    "cage": Exigence(
        "derivation", "chaine",
        "classe d'âge « [a-b[ » (« [a-[ » pour la classe ouverte) — source de "
        "la dérivation d'agean, obligatoire quand agean est absente ; strates "
        "de la substitution des DP ; ne remplace pas l'âge numérique",
        motif=r"^\[\d+-\d*\[$", nuls=False),
    "type_unite": Exigence(
        "facultative", "chaine",
        "type d'unité (UHCD = exemption de substitution) — non lue par la chaîne"),
    # --- traçabilité de scripts/substituer_dp_imprecis.py ---
    "dp_origine": Exigence(
        "facultative", "chaine", "DP d'entrée avant substitution (traçabilité)"),
    "dp_substitue": Exigence(
        "facultative", "booleen", "DP substitué ? (traçabilité)"),
    "repli_substitution": Exigence(
        "facultative", "entier",
        "niveau de repli de la substitution 0/1/2, nul sinon (traçabilité)"),
}


@dataclass
class RapportSource:
    """Résultat de :func:`verifier_source` — lisible par :meth:`texte`."""

    fichier: Path
    n_lignes: int
    colonnes: list[str]
    typologie_fournie: bool
    types: dict[str, int] = field(default_factory=dict)  # DPEC -> effectif
    ecarts: list[str] = field(default_factory=list)       # bloquants
    signalements: list[str] = field(default_factory=list)  # non bloquants

    @property
    def conforme(self) -> bool:
        return not self.ecarts

    def texte(self) -> str:
        origine = "fournis" if self.typologie_fournie else "calculés"
        types = (f"types d'hospitalisation ({origine}) : {self.types}"
                 if self.types else "types d'hospitalisation : non calculables")
        tete = (f"fichier {self.fichier.name} — {self.n_lignes} lignes, {types}, "
                + ("colonnes OK" if self.conforme
                   else f"{len(self.ecarts)} ÉCART(S) BLOQUANT(S)"))
        lignes = [tete]
        lignes += [f"  - ÉCART : {e}" for e in self.ecarts]
        lignes += [f"  - signalé : {s}" for s in self.signalements]
        return "\n".join(lignes)


def _type_ok(dtype: pl.DataType, attendu: str) -> bool:
    chaine = dtype == pl.String or isinstance(dtype, (pl.Categorical, pl.Enum))
    if attendu == "chaine":
        return chaine
    if attendu == "numerique":
        return dtype.is_numeric()
    if attendu == "entier":
        return dtype.is_integer()
    if attendu == "booleen":
        return dtype == pl.Boolean
    if attendu == "chaine_ou_entier":
        return chaine or dtype.is_integer()
    raise ValueError(f"type d'exigence inconnu : {attendu!r}")


def verifier_source(
    source_path: Path | str,
    df: pl.DataFrame | None = None,
) -> RapportSource:
    """Contrôle des prérequis du fichier de scénarios (:data:`SCHEMA_SOURCE`).

    Le fichier existe et se lit en parquet ; colonnes présentes selon leur
    statut (``agean`` absente → dérivée de ``cage``, alors requise avec
    ``id_scenario``) ; types ; encodage du sexe (PMSI 1/2) et du mode
    d'hospitalisation (HC/HP) ; DP et DAS lisibles (codes compacts, DAS
    séparés par des espaces) ; âge numérique s'il est fourni, libellé de
    classe d'âge « [a-b[ » sinon ; typologie — fournie par le
    fichier (``TPEC``/``DPEC``, modalités affichées, modalités inconnues de
    :data:`DPEC_TO_TPEC` SIGNALÉES sans échec) ou calculable
    (:data:`COLONNES_TYPOLOGIE`, modalités calculées pour le rapport).

    Imprime le rapport, le retourne, et lève :class:`BenchError` (le rapport
    en message) au moindre écart bloquant : colonne manquante, type
    inattendu, encodage inconnu, forme de code illisible. Les colonnes
    supplémentaires et les modalités nouvelles sont des informations, pas
    des erreurs. ``df`` : le fichier déjà chargé, pour ne pas le relire.
    """
    chemin = _chemin(source_path)
    try:
        chemin = resolve_parquet_path(chemin)
    except FileNotFoundError as exc:
        raise BenchError(str(exc)) from None
    if df is None:
        try:
            df = pl.read_parquet(chemin)
        except Exception as exc:  # polars lève diverses classes
            raise BenchError(f"{chemin} : lecture parquet impossible — {exc}") from None

    typologie_fournie = {"TPEC", "DPEC"} <= set(df.columns)
    agean_absente = "agean" not in df.columns
    rapport = RapportSource(chemin, df.height, list(df.columns), typologie_fournie)
    ecarts, signal = rapport.ecarts, rapport.signalements
    if agean_absente:
        signal.append("agean absente : DÉRIVÉE de cage par deriver_agean (tirage entier "
                      "uniforme dans la classe, déterministe par id_scenario) — variable "
                      "dérivée, pas une donnée observée")

    for col, ex in SCHEMA_SOURCE.items():
        requise = (ex.statut == "obligatoire"
                   or (ex.statut == "typologie" and not typologie_fournie)
                   or (ex.statut == "derivation" and agean_absente)
                   or (ex.statut == "reparable" and "ghm2" not in df.columns))
        if col not in df.columns:
            if requise:
                ecarts.append(f"colonne manquante : {col} ({ex.statut} — {ex.role})")
            elif ex.statut == "reparable":
                signal.append(f"{col} absente : réparée depuis ghm2[:5] (reparer_racine)")
            continue
        serie = df[col]
        if not _type_ok(serie.dtype, ex.type):
            ecarts.append(
                f"type inattendu : {col} est {serie.dtype}, attendu {ex.type} "
                f"({ex.role})")
            continue
        nuls = serie.null_count()
        if nuls and not ex.nuls:
            ecarts.append(f"valeurs nulles : {col} ({nuls} ligne(s)) — nuls interdits ({ex.role})")
        elif nuls and ex.statut == "reparable":
            signal.append(f"{col} : {nuls} valeur(s) nulle(s) — réparées depuis ghm2[:5] "
                          "(reparer_racine ; compteur au récap, attendu 0 après correction amont)")
        elif nuls and requise:
            signal.append(f"{col} : {nuls} valeur(s) nulle(s) tolérée(s)")
        texte = serie.drop_nulls().cast(pl.String)
        if ex.valeurs is not None:
            inconnues = sorted(set(texte.unique().to_list()) - set(ex.valeurs))
            if inconnues:
                ecarts.append(
                    f"encodage inconnu : {col} vaut {inconnues}, attendu "
                    f"{list(ex.valeurs)} ({ex.role})")
        if ex.motif is not None:
            non_vides = texte.filter(texte != "")
            mauvais = non_vides.filter(~non_vides.str.contains(ex.motif))
            if mauvais.len():
                ecarts.append(
                    f"forme illisible : {col} — {mauvais.len()} valeur(s) hors "
                    f"motif, ex. {mauvais.head(3).to_list()} ({ex.role})")

    supplementaires = [c for c in df.columns if c not in SCHEMA_SOURCE]
    if supplementaires:
        signal.append(f"colonnes supplémentaires hors schéma (ignorées) : {supplementaires}")

    # Typologie : fournie → modalités affichées, nouvelles signalées ;
    # absente → calculée pour le rapport si ses colonnes sont saines.
    if typologie_fournie:
        if _type_ok(df["DPEC"].dtype, "chaine"):
            comptes = df.group_by("DPEC").len().sort("DPEC")
            rapport.types = {str(k): int(v) for k, v in comptes.iter_rows()}
            nouvelles = sorted(m for m in rapport.types if m not in DPEC_TO_TPEC)
            if nouvelles:
                signal.append(
                    f"modalités de DPEC inconnues de DPEC_TO_TPEC (nouvelles, "
                    f"conservées telles quelles) : {nouvelles}")
    else:
        # agean dérivée à la volée pour le rapport (mêmes tirages que preparer_pool)
        pour_typologie = df
        if agean_absente and {"cage", "id_scenario"} <= set(df.columns) and not any(
                e.startswith(("forme illisible : cage", "type inattendu : cage",
                              "valeurs nulles : cage")) for e in ecarts):
            pour_typologie = deriver_agean(df)[0]
        if "ghm2" in pour_typologie.columns and _type_ok(pour_typologie["ghm2"].dtype, "chaine"):
            pour_typologie = reparer_racine(pour_typologie)[0]
        colonnes_saines = all(
            c in pour_typologie.columns
            and _type_ok(pour_typologie[c].dtype, SCHEMA_SOURCE[c].type)
            for c in COLONNES_TYPOLOGIE)
        if colonnes_saines:
            comptes = with_typologie(pour_typologie).group_by("DPEC").len().sort("DPEC")
            rapport.types = {str(k): int(v) for k, v in comptes.iter_rows()}
        else:
            signal.append("typologie non calculable (voir les écarts ci-dessus)")

    print(rapport.texte())
    if not rapport.conforme:
        raise BenchError(rapport.texte())
    return rapport


# ---------------------------------------------------------------------------
# Pool candidat — chargement, typologie, filtre, tirage, enrichissement,
# contrôle du contrat
# ---------------------------------------------------------------------------

def preparer_pool(
    source_path: Path | str,
    quotas: dict[str, int] | str | None,
    seed: int = 42,
    *,
    by: str = "DPEC",
    enrichir: bool = True,
    enrichissement_seed: int | None = None,
    politique: Any = None,
    filtre_dp_suffixe: str | None = "8",
    target_n: int | None = None,
    referentials: Path = REFERENTIALS,
    specialite: bool = True,
) -> pl.DataFrame:
    """Le pool candidat, prêt pour fictomed : :func:`verifier_source`
    d'abord, puis chargement, dérivation d'``agean`` si le fichier ne la
    fournit pas (``deriver_agean`` — premier geste : l'aval lit l'âge
    final), réparation de ``racine`` depuis ``ghm2`` (``reparer_racine``,
    compteur au récap), typologie (conservée si le fichier la fournit,
    sinon ``with_typologie``), identifiants de traçabilité, filtre
    DP (séjours dont le DP se termine par ``filtre_dp_suffixe`` — ``None``
    pour ne rien filtrer), exclusion des séjours incomplets pour fictomed
    (:data:`COLONNES_REQUISES_FICTOMED` nuls, comptés), tirage,
    enrichissement (lot E1), contrôle du contrat fiches côté pool, récap de
    la couverture par type.

    ``quotas`` : ``{modalité de by: effectif}`` (tirage stratifié),
    ``"couverture"`` (un séjour par modalité présente — le smoke d'un
    nouveau fichier), ou ``None`` (tirage simple de ``target_n`` séjours).
    ``enrichissement_seed`` vaut ``seed`` par défaut ; ``politique`` est une
    :class:`enrichissement.Politique` (défaut : ``Politique()``).

    Après le tirage et avant l'enrichissement, la spécialité (service
    d'hospitalisation) est attribuée à chaque ligne du pool
    (``deriver_specialite`` : mapping ``type_unite`` valide → dictionnaire
    des spécialités par racine et groupe d'âge → repli) depuis
    ``<referentials>/dictionnaire_spe_racine.parquet`` (requis) et
    ``<referentials>/mapping_type_unite.yaml`` (facultatif) ; ``specialite=False``
    la désactive (fictomed appliquera alors sa propre jointure « première
    spécialité de la racine », sans groupe d'âge — le comportement d'avant).
    Le récap montre la répartition des sources et les paires (type de
    séjour, spécialité) : les combinaisons surprenantes se voient à l'œil.
    """
    source_path = resolve_parquet_path(_chemin(source_path))
    source_df = pl.read_parquet(source_path)
    print("Source :", source_path)
    print("Shape  :", source_df.shape, "— colonnes :", source_df.columns)

    verifier_source(source_path, df=source_df)

    # agean en PREMIER geste après le contrôle : la typologie et
    # l'enrichisseur consomment l'âge numérique, ils doivent voir la valeur
    # finale (même principe d'ordre que la substitution des DP en amont).
    source_df, _agean = deriver_agean(source_df)
    print(_agean.texte())

    # Garde-fou racine : réparée depuis ghm2[:5] quand elle manque (branche
    # courte de C1) — la typologie et la spécialité lisent la racine finale.
    source_df, _racine = reparer_racine(source_df)
    print(_racine.texte())

    if {"TPEC", "DPEC"} <= set(source_df.columns):
        print("Typologie TPEC/DPEC fournie par le fichier — conservée telle quelle.")
    else:
        source_df = with_typologie(source_df)
    _afficher(
        source_df.group_by("TPEC", "DPEC").len()
        .sort(["TPEC", "DPEC"])
    )

    # Filtre du run : ne garder que les séjours dont le DP se termine par le
    # suffixe (« 8 » : sous-catégories « autres formes précisées »). Les
    # identifiants de traçabilité sont posés AVANT le filtre — source_row_id
    # doit rester celui du parquet complet.
    source_df = ensure_source_ids(source_df, source_path)
    if filtre_dp_suffixe:
        _avant = source_df.height
        source_df = source_df.filter(pl.col("diag2").str.ends_with(filtre_dp_suffixe))
        print(f"Filtre DP terminant par {filtre_dp_suffixe} : {_avant} -> {source_df.height} séjours")
        _afficher(source_df.group_by("TPEC", "DPEC").len().sort(["TPEC", "DPEC"]))

    # Séjours incomplets pour fictomed : fictive.py écarte silencieusement les
    # profils sans age2 / los / admission_mode / discharge_disposition — un
    # tirage qui les retient fait échouer generate_and_select (cible non
    # atteinte). On les écarte AVANT le tirage, en le disant.
    _requises = [c for c in COLONNES_REQUISES_FICTOMED if c in source_df.columns]
    if _requises:
        _avant = source_df.height
        source_df = source_df.filter(pl.all_horizontal([pl.col(c).is_not_null() for c in _requises]))
        _incomplets = _avant - source_df.height
        print(f"Séjours incomplets pour fictomed ({' / '.join(_requises)} nuls) : "
              f"{_incomplets} écarté(s) — {_avant} -> {source_df.height} séjours")
    else:
        _incomplets = 0

    if quotas is None:
        if target_n is None:
            raise BenchError("quotas=None (tirage simple) : préciser target_n.")
        _n = min(int(target_n), source_df.height)
        candidate_source = source_df.sample(
            n=_n, with_replacement=False, shuffle=True, seed=seed)
        print(f"Tirage simple : {_n} séjours (seed={seed}).")
    elif not quotas:
        raise BenchError("QUOTAS vide — à renseigner : la cellule de tirage en a besoin.")
    else:
        candidate_source = tirage_stratifie(
            ensure_source_ids(source_df, source_path), quotas, by=by, seed=seed
        )
    _afficher(candidate_source.group_by("TPEC", "DPEC").len().sort(["TPEC", "DPEC"]))

    # Spécialité (service d'hospitalisation) — observée (mapping type_unite
    # valide) ou dérivée (dictionnaire par racine réparée et groupe d'âge),
    # sinon repli : la colonne `specialty` traverse fictomed telle quelle.
    if specialite:
        _dico_path = Path(referentials) / DICO_SPECIALITE
        if not _dico_path.is_file():
            raise BenchError(
                f"dictionnaire des spécialités absent : {_dico_path} — référentiel AP-HP "
                "requis pour attribuer le service (deriver_specialite) ; specialite=False "
                "pour s'en passer (fictomed appliquera sa jointure « première spécialité »).")
        _dico = pl.read_parquet(_dico_path)
        _mapping_path = Path(referentials) / MAPPING_TYPE_UNITE
        _mapping = (charger_mapping_type_unite(_mapping_path, vocabulaire=_dico["lib_spe_uma"].unique().to_list())
                    if _mapping_path.is_file() else {})
        candidate_source, _spec = deriver_specialite(candidate_source, _dico, _mapping)
        print(_spec.texte())
        _afficher(candidate_source.group_by("TPEC", "DPEC", "specialty", "specialite_source").len()
                  .sort(["TPEC", "DPEC", "specialty"]))
    else:
        print("specialite=False — pas de colonne specialty : fictomed joindra sa « première spécialité » par racine.")

    # Enrichissement du pool candidat (lot E1) — codes DAS tabac/alcool/
    # corpulence + contexte patient. Le pool sort de la préparation des données
    # DÉJÀ enrichi : la génération fictomed (seeder) n'enrichit plus rien.
    if not enrichir:
        print("ENRICHIR_SCENARIOS = False — pool candidat inchangé.")
    elif "enrichi" in candidate_source.columns:
        print("SKIP — pool déjà enrichi "
              f"({int(candidate_source['enrichi'].sum())}/{candidate_source.height} lignes).")
    else:
        from enrichissement import Politique
        from enrichissement.integration_stream import enrichir_candidats

        candidate_source = enrichir_candidats(
            candidate_source,
            seed=seed if enrichissement_seed is None else enrichissement_seed,
            politique=Politique() if politique is None else politique,
        )
        _afficher(candidate_source.filter(pl.col("enrichi")).select(
            [c for c in ("DPEC", "agean", "sexe", "taille_cm", "poids_kg", "imc",
                         "tabac", "alcool", "codes_ajoutes")
             if c in candidate_source.columns]
        ))

    # Contrôle du contrat fiches côté pool (bench.fiches — l'index fait foi).
    # Codes du pool sans fiche : JOURNALISÉS, jamais ignorés (motifs détaillés :
    # recode-icd resoudre --journal). Codes ajoutés par l'enrichissement :
    # doivent être émissibles (classe_generation).
    _index_fiches = charger_index(Path(referentials) / "cards_library")
    _codes_pool: set[str] = set(candidate_source["diag2"].drop_nulls().to_list())
    for _col in ("diagnostic_associes", "codes_ajoutes"):
        if _col in candidate_source.columns:
            for _v in candidate_source[_col].drop_nulls().to_list():
                _codes_pool.update(str(_v).split())
    _absents = codes_sans_fiche(_index_fiches, sorted(_codes_pool))
    print(f"Pool : {len(_codes_pool)} codes distincts, "
          f"{len(_absents)} sans fiche à l'index"
          + (f" — JOURNAL : {_absents}" if _absents else ""))
    if "codes_ajoutes" in candidate_source.columns:
        _emissibles = {c.replace(".", "") for c in codes_emissibles(_index_fiches)}
        _ajoutes = {c for _v in candidate_source["codes_ajoutes"].drop_nulls().to_list()
                    for c in str(_v).split()}
        _non_emissibles = sorted(c for c in _ajoutes
                                 if c.replace(".", "") not in _emissibles)
        assert not _non_emissibles, (
            f"codes ajoutés par l'enrichissement non émissibles : {_non_emissibles}")
        print(f"Enrichissement : {len(_ajoutes)} code(s) ajouté(s) distincts, "
              "tous émissibles.")

    print(f"Pool candidat : {candidate_source.height} séjours — agean {_agean.source} — "
          f"racine réparée sur {_racine.n_reparees} ligne(s) — {_incomplets} séjour(s) incomplet(s) "
          "écarté(s) avant tirage — couverture par type :")
    _afficher(candidate_source.group_by("TPEC", "DPEC").len().sort(["TPEC", "DPEC"]))
    return candidate_source


# ---------------------------------------------------------------------------
# Test courant — chemins, état, montage du jeu
# ---------------------------------------------------------------------------

def dossiers_test(
    test_num: str,
    prev_test: str | None,
    *,
    tests_dir: Path = TESTS_DIR,
) -> tuple[Path, Path | None]:
    """``(TD, PREV_TD)`` : le dossier du test courant et celui du test
    précédent de la chaîne (``None`` pour un tout premier test)."""
    td = Path(tests_dir) / test_num
    prev_td = Path(tests_dir) / prev_test if prev_test else None
    return td, prev_td


def etat_test(td: Path, prev_td: Path | None | EllipsisType = ...) -> None:
    """État du test courant : présent ?, jeu ``system/one_gen`` ?, dossiers
    scénario ?, figement ? ``prev_td`` (facultatif) : le test amont, pour
    rappeler d'où le jeu sera monté."""
    if prev_td is not ...:
        print("Test courant :", td, "(existe)" if td.is_dir() else "(à créer)")
        print(
            "Jeu amont    :",
            prev_td / "system" / "one_gen"
            if prev_td
            else "(premier test d'une topologie : jeu initial à fournir à la main "
                 "dans TD/system/one_gen)",
        )
    _sys_dir = td / "system" / "one_gen"
    _scen = scenario_dirs(td) if td.is_dir() else []
    print("Test               :", td, "— présent" if td.is_dir() else "— à créer")
    print("Jeu system/one_gen :", "présent" if _sys_dir.is_dir() else "absent")
    print("Dossiers scénario  :", len(_scen), _scen[:5], "…" if len(_scen) > 5 else "")
    if _scen:
        _fige = (td / _scen[0] / "prompt_system_one_gen.txt").is_file()
        print("Figement (1er dossier, prompt_system_one_gen.txt) :",
              "présent" if _fige else "absent")


def monter_jeu(td: Path, prev_td: Path | None) -> None:
    """Montage du jeu ``system/one_gen`` par la chaîne (copie du jeu du test
    précédent) — skip si déjà monté ; refus si ``prev_td`` est ``None``
    (premier test : jeu initial à fournir à la main)."""
    _sys_dir = td / "system" / "one_gen"
    if _sys_dir.is_dir():
        print("SKIP — jeu déjà monté :", _sys_dir)
    elif prev_td is None:
        raise RuntimeError(
            "premier test d'une topologie : fournir un jeu initial dans "
            f"{_sys_dir} à la main (les jeux historiques sont dans git : generation/runs/01)"
        )
    else:
        src = Path(prev_td) / "system" / "one_gen"
        # (historique : tests/01 utilisait la position "first" — sans importance,
        #  le notebook vise les tests futurs)
        td.mkdir(parents=True, exist_ok=True)
        shutil.copytree(src, _sys_dir)
        print("MONTÉ :", _sys_dir, "<-", src)


# ---------------------------------------------------------------------------
# Seeding puis figement
# ---------------------------------------------------------------------------

def seeder(
    td: Path,
    pool: pl.DataFrame | None,
    *,
    source_path: Path | str,
    enrichir: bool = True,
    enrichissement_seed: int | None = None,
    politique: Any = None,
    seed: int = 42,
    scenario_filters: list[dict] | None = None,
    random_selection: bool = True,
    system_prompt_file: str = "prompt_system_one_gen.txt",
    repo_root: Path = REPO_ROOT,
) -> pl.DataFrame | None:
    """SEEDING puis FIGEMENT, idempotents, dans cet ordre :

    1. génération fictomed — un scénario par ligne du ``pool`` (skip si le
       test est déjà seedé : l'archive du tirage est affichée) ; garde : le
       pool arrive DÉJÀ enrichi quand ``enrichir`` est actif ; la colonne
       ``cage`` est retirée du profil transmis (collision ``age`` → ``cage``
       du loader fictomed, ``agean`` présente) ;
    2. graine : ``prefix.txt`` du jeu (prime sur le prefix fictomed), user
       prompts avec contexte patient, ``test.json`` annoté ;
    3. figement du jeu par famille en ``system_prompt_file`` dans chaque
       dossier (skip si déjà figé partout).

    Retourne les scénarios sélectionnés (``None`` si rien n'a été généré).
    ``enrichissement_seed`` et ``politique`` ne servent qu'à l'annotation de
    ``test.json`` (défauts : ``seed``, ``Politique()``).
    """
    from enrichissement import Politique
    from enrichissement.integration_stream import user_fn_enrichi

    source_path = _chemin(source_path)
    if enrichissement_seed is None:
        enrichissement_seed = seed
    if politique is None:
        politique = Politique()
    if scenario_filters is None:
        scenario_filters = []
    selected_scenarios: pl.DataFrame | None = None

    # Génération fictomed — un scénario par ligne du pool candidat (QUOTAS).
    # Ré-exécutable tant que le test n'est pas seedé : rien n'est écrit dans les
    # dossiers scénario, seuls les fichiers de travail vont sous TD/.fictomed/.
    _scen = scenario_dirs(td) if td.is_dir() else []
    if _scen:
        print(f"SKIP — test déjà seedé : {len(_scen)} dossiers scénario.")
        _tirage = td / ".fictomed" / "scenarios_fictomed_selected.parquet"
        if _tirage.is_file():
            # archive du tirage de CE test (scénarios générés, enrichissement
            # compris) — pas les profils sources
            _archive = pl.read_parquet(_tirage)
            _afficher(_archive.select(
                [c for c in _COLONNES_CONTROLE if c in _archive.columns]
            ))
        else:
            print("(pas d'archive du tirage :", _tirage, ")")
    elif pool is None:
        print("Pas de pool candidat en mémoire — exécuter le tirage stratifié "
              "(paramétrage du run) d'abord.")
        return None
    else:
        candidate_source = pool
        # fichiers de travail fictomed sous TD/.fictomed/ (caché => hors découverte)
        FICTOMED_DIR = td / ".fictomed"

        # garde défensive : le pool doit arriver ici DÉJÀ enrichi (cellule
        # d'enrichissement, fin de la préparation des données) — jamais
        # d'enrichissement silencieux dans la génération.
        if enrichir and "enrichi" not in candidate_source.columns:
            raise RuntimeError(
                "Pool candidat non enrichi — exécuter la cellule d'enrichissement "
                "(section 2, après le tirage stratifié) avant la génération."
            )
        (FICTOMED_DIR / "_backups").mkdir(parents=True, exist_ok=True)

        # Collision du loader fictomed : il renomme `age` → `cage` sans test
        # d'existence ; un corpus de campagne porte déjà `cage` (classe d'âge)
        # → DuplicateError. `agean` (→ age2) étant toujours présente ici,
        # fictomed n'a jamais besoin de `cage` : on la retire du profil
        # transmis (le pool en mémoire la garde).
        _profil = candidate_source
        if "cage" in _profil.columns and "agean" in _profil.columns:
            _profil = _profil.drop("cage")
            print("Colonne cage retirée du profil transmis à fictomed (collision age→cage du "
                  "loader ; agean présente).")

        write_fictomed_config(
            config_file=FICTOMED_DIR / "servers.yaml",
            project_root=repo_root,
            run_dir=FICTOMED_DIR,
        )

        _, _, selected_scenarios = generate_and_select_fictomed_scenarios(
            candidate_source=_profil,
            config_file=FICTOMED_DIR / "servers.yaml",
            aphp_data_dir=Path(repo_root) / "data" / "aphp",
            paths={"backups": FICTOMED_DIR / "_backups"},
            scenario_filters=scenario_filters,
            target_n=candidate_source.height,
            random_selection=random_selection,
            random_seed=seed,
            run_dir=FICTOMED_DIR,
        )

        # contrôle avant écriture : les quotas ont-ils survécu à la génération ?
        _ctrl = [c for c in _COLONNES_CONTROLE if c in selected_scenarios.columns]
        _afficher(selected_scenarios.select(_ctrl))
        if "DPEC" in selected_scenarios.columns:
            _afficher(selected_scenarios.group_by("TPEC", "DPEC").len().sort(["TPEC", "DPEC"]))
        else:
            print("TPEC/DPEC non propagées par fictomed — réappliquer with_typologie "
                  "sur selected_scenarios si le contrôle des quotas est requis.")

        # Écriture de la graine — après contrôle du tirage
        # prefix porté par le jeu : system/one_gen/prefix.txt prime sur fictomed
        _prefix_file = td / "system" / "one_gen" / "prefix.txt"
        if _prefix_file.is_file():
            _prefix = _prefix_file.read_text(encoding="utf-8").rstrip("\n")
            selected_scenarios = selected_scenarios.with_columns(
                pl.lit(_prefix).alias("prefix")
            )
            print(f"Prefix REMPLACÉ par celui du jeu ({_prefix_file}) — "
                  + (f"{len(_prefix)} caractère(s)." if _prefix
                     else "fichier vide : pas de prefix."))
        else:
            print(f"Prefix fictomed d'origine CONSERVÉ (pas de {_prefix_file.name} dans le jeu).")

        # user prompt : insertion du contexte patient (Stream uniquement — dans
        # fictomed, le template appellera bloc_contexte directement)
        _user_fn = user_fn_enrichi() if enrichir else None
        print(
            "Scénarios créés :",
            seed_user_prompts(td, selected_scenarios, user_fn=_user_fn,
                              seed_path=source_path),
        )

        if enrichir:
            # trace des décisions dans test.json (champ notes, spec §2.2)
            _tj = td / "test.json"
            _data = json.loads(_tj.read_text(encoding="utf-8"))
            _data["notes"] = (f"enrichissement: seed={enrichissement_seed}, "
                              f"décisions={politique}")
            _tj.write_text(json.dumps(_data, ensure_ascii=False, indent=2) + "\n",
                           encoding="utf-8")
            print("test.json annoté :", _data["notes"][:100], "…")

    # Figement — skip si le fichier figé est déjà présent dans tous les dossiers
    _names = scenario_dirs(td) if td.is_dir() else []
    _manquants = [n for n in _names if not (td / n / system_prompt_file).is_file()]
    if not _names:
        print("Pas de dossiers scénario — seeder d'abord (3.1a).")
    elif not _manquants:
        print(f"SKIP — {system_prompt_file} déjà figé dans tous les dossiers.")
    else:
        print("Scénarios servis :", copy_system_prompts(td, "one_gen", dest=system_prompt_file))
    return selected_scenarios


def prompts_verificateur(td: Path, verif_system: str, verif_user: str) -> None:
    """Prompts partagés du vérificateur, posés une fois par ``write_prompts``
    — skip s'ils sont déjà présents partout."""
    _names = scenario_dirs(td) if td.is_dir() else []
    for _fname, _text in (
        ("prompt_system_verif.txt", verif_system),
        ("user_verification.txt", verif_user),
    ):
        if not _names:
            print("Pas de dossiers scénario — seeder d'abord (3.1a).")
            break
        if all((td / n / _fname).is_file() for n in _names):
            print(f"SKIP — {_fname} déjà présent dans tous les dossiers.")
        else:
            print(f"{_fname} :", write_prompts(td, _fname, _text))


# ---------------------------------------------------------------------------
# Génération — client, affichage du dry-run, lecture des CR, vérificateur
# ---------------------------------------------------------------------------

def mistral_client():
    """Client Mistral construit à la demande — uniquement pour les runs réels."""
    try:
        api_key = os.environ["MISTRAL_API_KEY"]
    except KeyError:
        raise RuntimeError(
            "Variable d'environnement MISTRAL_API_KEY absente.\n"
            "Exporter la clé AVANT de lancer le kernel :\n"
            "    export MISTRAL_API_KEY=...    # puis relancer jupyter\n"
            "La clé ne doit JAMAIS être écrite dans ce notebook ni dans un "
            "fichier versionné."
        ) from None
    if not api_key.strip():
        raise RuntimeError("MISTRAL_API_KEY est définie mais vide.")
    from core.clients import MistralClient

    return MistralClient(api_key=api_key)


def show_first_prompt(result: GenResult, *, max_chars: int = 6000) -> None:
    """Affiche le premier prompt assemblé d'un `GenResult` dry-run.

    Contrôle à sec ET test de complétude : si `generate` a rendu la main,
    aucun fichier ne manquait dans aucun dossier scénario (§3.5).
    """
    if result.reports.height == 0:
        print("Aucun scénario retenu.")
        return
    row = result.reports.row(0, named=True)
    print(f"Scénario : {row['scenario']} — famille : {row['template']}")
    for label, key in (
        ("PROMPT SYSTÈME", "system_prompt"),
        ("PROMPT USER", "user_prompt"),
        ("PREFIX (assistant)", "prefix"),
    ):
        text = row[key] or ""
        print(f"\n{'=' * 28} {label} — {len(text)} caractère(s) {'=' * 28}")
        print(text[:max_chars])
        if len(text) > max_chars:
            print(f"[... tronqué à {max_chars} caractères]")


def _lancer_script(script: Path, *args: str) -> int:
    """Lance ``python scripts/<script> args`` et REIMPRIME sa sortie : un
    sous-processus non capturé écrit sur le descripteur du noyau Jupyter,
    invisible dans le notebook (contrairement au ``!python`` d'origine).
    Retourne le code retour (jamais levé : les contrôles sont un rapport)."""
    result = subprocess.run(
        [sys.executable, str(script), *args],
        capture_output=True, text=True, check=False,
    )
    if result.stdout:
        print(result.stdout, end="" if result.stdout.endswith("\n") else "\n")
    if result.stderr:
        print(result.stderr, end="" if result.stderr.endswith("\n") else "\n", file=sys.stderr)
    return result.returncode


def _module_show_crh():
    """scripts/show_crh.py chargé comme module (rendu lisible d'un CR)."""
    import importlib.util

    _spec_show = importlib.util.spec_from_file_location(
        "show_crh", SCRIPTS_DIR / "show_crh.py"
    )
    _show_mod = importlib.util.module_from_spec(_spec_show)
    _spec_show.loader.exec_module(_show_mod)
    return _show_mod


def afficher_crh(td: Path, scenario: str, out: str = "crh_generation.txt") -> None:
    """Affiche en markdown le CR d'un dossier scénario du test courant
    (réutilise scripts/show_crh.py)."""
    from IPython.display import Markdown

    path = td / scenario / out
    if not path.is_file():
        print("Pas encore généré :", path)
        return
    text = _module_show_crh().render(path)
    if text is None:
        print("CR illisible (JSON) :", path)
        return
    _afficher(Markdown(text))


def ecrire_apercus_md(td: Path, out: str = "crh_generation.txt") -> None:
    """Écrit pour TOUT le test un aperçu ``.md`` à côté de chaque ``out``
    (ex. ``0007/crh_generation.md``, versionné avec le test) —
    ``python scripts/show_crh.py TD --md --out OUT``."""
    _lancer_script(SCRIPTS_DIR / "show_crh.py", str(td), "--md", "--out", out)


def contexte_verificateur(td: Path, out_file: str = "crh_generation.txt") -> pl.DataFrame:
    """Contexte du vérificateur : les CR sur disque (``load_reports``), sinon
    un placeholder par scénario (contrôle à sec possible sans run réel)."""
    try:
        return load_reports(td, out_file)
    except BenchError:
        _names = scenario_dirs(td)
        ctx = pl.DataFrame(
            {
                "scenario": _names,
                "report": ["[CR généré — placeholder de contrôle à sec]"] * len(_names),
            }
        )
        print(f"Pas de {out_file} sur disque : contexte placeholder.")
        return ctx


# ---------------------------------------------------------------------------
# Bilan — coûts, journal CSV, vérification mécanique
# ---------------------------------------------------------------------------

def bilan(
    td: Path,
    *,
    out_file: str = "crh_generation.txt",
    tests_dir: Path = TESTS_DIR,
    usage_log: Path = USAGE_LOG,
) -> None:
    """Coûts de tous les tests (``summarize_costs``), stats du journal CSV
    global (skip s'il n'existe pas), puis les contrôles mécaniques hors
    modèle sur ``td`` : ``scripts/check_crh.py`` et ``scripts/reancre_crh.py``
    (skip si absent)."""
    tests_dir = Path(tests_dir)
    if tests_dir.is_dir():
        for _td in sorted(tests_dir.iterdir()):
            if _td.is_dir() and not _td.name.startswith("."):
                print(f"=== {_td.name} — {_td} ===")
                _afficher(summarize_costs(_td))
    else:
        print("Aucun test encore créé sous", tests_dir)

    # Stats rapides sur le journal CSV global des appels (spec §7) — observation ;
    # usage.json reste la source de summarize_costs. Skip propre si absent.
    usage_log = Path(usage_log)
    if usage_log.is_file():
        _log = pl.read_csv(
            usage_log,
            schema_overrides={"test": pl.String, "scenario": pl.String, "batch_id": pl.String},
        )
        _aggs = [
            pl.len().alias("n_lignes"),
            pl.col("input_tokens").sum(),
            pl.col("output_tokens").sum(),
            pl.col("cost_usd").sum().round(6),
        ]
        try:
            _rel = usage_log.relative_to(REPO_ROOT)
        except ValueError:
            _rel = usage_log
        print(f"{_rel} — {_log.height} ligne(s)")
        print("Coût et tokens par (test, out) :")
        _afficher(_log.group_by(["test", "out"]).agg(_aggs).sort(["test", "out"]))
        print(f"Test courant {td.name} — par template :")
        _afficher(
            _log.filter(pl.col("test") == td.name)
            .group_by("template")
            .agg(_aggs)
            .sort("template")
        )
    else:
        print("SKIP — pas encore de journal CSV :", usage_log)

    _lancer_script(SCRIPTS_DIR / "check_crh.py", str(td), "--out", out_file)
    _reancre = SCRIPTS_DIR / "reancre_crh.py"
    if _reancre.is_file():
        _lancer_script(_reancre, str(td), "--out", out_file)
    else:
        print("SKIP — script absent (pas encore commité) :", _reancre)


# ---------------------------------------------------------------------------
# Entrées du juge d'équivalence — nettoyage d'export puis JSONL (optionnel)
# ---------------------------------------------------------------------------

def _module_juge_io():
    """scripts/juge_io.py chargé comme module (contrat d'E/S du juge dans
    sa docstring ; il rend lui-même check_crh importable)."""
    import importlib.util

    _spec = importlib.util.spec_from_file_location("juge_io", SCRIPTS_DIR / "juge_io.py")
    _mod = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_mod)
    return _mod


def preparer_entrees_juge(
    td: Path,
    *,
    out_file: str = "crh_generation.txt",
    seuil: float = 0.75,
    out_jsonl: Path | None = None,
    apercu: int = 5,
) -> list[dict]:
    """Prépare les entrées du juge d'équivalence pour le test ``td`` :

    1. nettoyage d'export des dictionnaires (``scripts/nettoie_dictionnaire.py``
       sur ``out_file``, sortie ``<td>/export_dict/`` — lecture seule sur
       les dossiers scénario) ;
    2. ``juge_io.ecrire_entrees_juge`` → ``<td>/entrees_juge.jsonl`` (une
       ligne par code du scénario : code, libellé, fiche, passages propres —
       contrat dans la docstring de ``scripts/juge_io.py``) ;
    3. affichage du compte d'entrées et des ``apercu`` premières lignes
       (scénario, code, libellé, nombre de passages, fiche présente).

    Sans CR nettoyable (aucun run réel), dit pourquoi et rend une liste
    vide — jamais d'exception. Retourne les lignes écrites.
    """
    td = Path(td)
    export = td / "export_dict"
    code_retour = _lancer_script(
        SCRIPTS_DIR / "nettoie_dictionnaire.py", str(td),
        "--source", out_file, "--seuil", str(seuil), "--out", str(export),
    )
    if code_retour != 0:
        print(f"Pas d'entrées juge : aucun CR nettoyable dans {td} "
              f"(lancer le run réel de {out_file} d'abord).")
        return []
    cible = Path(out_jsonl) if out_jsonl is not None else td / "entrees_juge.jsonl"
    lignes = _module_juge_io().ecrire_entrees_juge(td, export, cible)
    scenarios = sorted({l["scenario"] for l in lignes})
    avec_fiche = sum(1 for l in lignes if l["fiche"])
    sans_passage = sum(1 for l in lignes if not l["passages"])
    print(f"Entrées juge : {len(lignes)} code(s) sur {len(scenarios)} scénario(s) — "
          f"{avec_fiche} avec fiche, {sans_passage} sans passage — écrit : {cible}")
    for l in lignes[:apercu]:
        print(f"  {l['scenario']}  {l['code']:8s} {len(l['passages'])} passage(s)  "
              f"fiche {'oui' if l['fiche'] else 'NON'}  — {l['libelle'][:70]}")
    return lignes


__all__ = [
    "DATA_APHP",
    "Exigence",
    "FICTOMED_SRC",
    "RECAP_TIRAGE_COLUMNS",
    "REFERENTIALS",
    "REPO_ROOT",
    "RapportSource",
    "SCHEMA_SOURCE",
    "TESTS_DIR",
    "USAGE_LOG",
    "WORK_DIR",
    "afficher_crh",
    "bilan",
    "contexte_verificateur",
    "dossiers_test",
    "ecrire_apercus_md",
    "etat_test",
    "mistral_client",
    "monter_jeu",
    "preparer_entrees_juge",
    "preparer_pool",
    "prompts_verificateur",
    "seeder",
    "show_first_prompt",
    "verifier_environnement",
    "verifier_source",
]

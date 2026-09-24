"""Chaîne amont des scénarios : sélection des profils source et génération
fictomed.

Extrait de l'ancien ``aphp_generation_utils.py`` (chaîne fictomed AP-HP,
``work_modif_prompts/``), à l'identique — mêmes signatures, même
comportement, sorties ``print`` comprises. Le notebook les utilisait déjà
telles quelles ; seul leur emplacement change (lot R1 de la consolidation).

Fonctions appelées par le notebook : ``resolve_parquet_path``,
``write_fictomed_config``, ``generate_and_select_fictomed_scenarios``.
Dépendances internes : ``build_filter_expr``, ``apply_filters``.
``prepare_source_candidates`` n'est plus appelée par le notebook (le tirage
stratifié s'y substitue) mais reste ici : c'est l'étape filtres +
échantillon historique, réutilisable pour un pool candidat simple.

Depuis l'amincissement du notebook (septembre 2026), le module porte aussi
les fonctions de données qui y étaient définies en cellules, à
l'identique : la typologie des séjours (``with_typologie``, ``DPEC_TO_TPEC``),
les identifiants de traçabilité (``ensure_source_ids``) et le tirage
stratifié (``tirage_stratifie``, ``quotas_couverture``), et depuis le
24/09/2026 la dérivation de l'âge numérique (``deriver_agean``) depuis la
classe d'âge des corpus de campagne. L'orchestration (gardes, idempotence,
messages) vit dans ``bench/banc.py``.

``generate_and_select_fictomed_scenarios`` REMPLACE TEMPORAIREMENT le
fichier ``profiles`` actif du dossier de données AP-HP par les candidats
fournis (backup horodaté dans ``paths["backups"]``), lance
``fictomed.generate``, puis RESTAURE l'original dans un ``finally`` — le
fichier n'est jamais laissé modifié, même sur échec. Elle exige fictomed
installé (import local à la fonction) et n'est donc pas couverte par les
tests unitaires (voir tests/test_bench_scenarios.py) ; le smoke de chaîne
sur répertoire scratch en tient lieu.
"""

from __future__ import annotations

import hashlib
import re
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

import polars as pl
import yaml


def resolve_parquet_path(path: Path) -> Path:
    """Résout un fichier Parquet, avec prise en charge de .parquet et .pq."""
    path = Path(path).expanduser().resolve()
    if path.exists():
        return path

    if path.suffix == "":
        for suffix in (".parquet", ".pq"):
            candidate = path.with_suffix(suffix)
            if candidate.exists():
                return candidate

    raise FileNotFoundError(f"Fichier parquet introuvable : {path}")


def build_filter_expr(spec: dict[str, Any]) -> pl.Expr:
    """Construit une expression Polars à partir d'une spécification de filtre."""
    column = spec["column"]
    op = str(spec["op"]).lower()
    value = spec.get("value")
    exclude = bool(spec.get("exclude", False))
    expr = pl.col(column)

    if op == "eq":
        condition = expr == value
    elif op == "ne":
        condition = expr != value
    elif op == "in":
        condition = expr.is_in(list(value))
    elif op == "not_in":
        condition = ~expr.is_in(list(value))
    elif op == "startswith":
        condition = expr.cast(pl.Utf8).str.starts_with(str(value))
    elif op == "endswith":
        condition = expr.cast(pl.Utf8).str.ends_with(str(value))
    elif op == "contains":
        condition = expr.cast(pl.Utf8).str.contains(str(value), literal=True)
    elif op == "regex":
        condition = expr.cast(pl.Utf8).str.contains(str(value))
    elif op == "gt":
        condition = expr > value
    elif op == "ge":
        condition = expr >= value
    elif op == "lt":
        condition = expr < value
    elif op == "le":
        condition = expr <= value
    elif op == "is_null":
        condition = expr.is_null()
    elif op == "not_null":
        condition = expr.is_not_null()
    else:
        raise ValueError(f"Opérateur inconnu : {op}")

    condition = condition.fill_null(False)
    return ~condition if exclude else condition


def apply_filters(
    df: pl.DataFrame,
    filters: list[dict[str, Any]],
    *,
    label: str,
) -> pl.DataFrame:
    """Applique successivement les filtres et affiche l'évolution des effectifs."""
    result = df

    for index, spec in enumerate(filters, start=1):
        column = spec["column"]
        if column not in result.columns:
            raise ValueError(
                f"{label}, filtre {index}: colonne absente {column!r}. "
                f"Colonnes : {result.columns}"
            )

        before = result.height
        result = result.filter(build_filter_expr(spec))
        print(f"{label}, filtre {index}: {spec} | {before} -> {result.height}")

    return result


def prepare_source_candidates(
    *,
    source_profiles_path: Path,
    source_filters: list[dict[str, Any]],
    candidate_pool_size: int,
    random_selection: bool,
    random_seed: int,
) -> tuple[Path, pl.DataFrame, pl.DataFrame, pl.DataFrame]:
    """Lit, identifie, filtre et échantillonne les profils source."""
    source_path = resolve_parquet_path(source_profiles_path)
    source_df = pl.read_parquet(source_path)

    print("Fichier source :", source_path)
    print("Shape          :", source_df.shape)
    print("Colonnes       :", source_df.columns)

    source_df = ensure_source_ids(source_df, source_path)

    source_filtered = apply_filters(source_df, source_filters, label="SOURCE")
    if source_filtered.height == 0:
        raise ValueError("Aucune ligne ne respecte les filtres source.")

    candidate_n = min(int(candidate_pool_size), source_filtered.height)
    if random_selection:
        candidate_source = source_filtered.sample(
            n=candidate_n,
            with_replacement=False,
            shuffle=True,
            seed=int(random_seed),
        )
    else:
        candidate_source = source_filtered.head(candidate_n)

    print("\nCandidats envoyés à fictomed :", candidate_source.shape)

    return source_path, source_df, source_filtered, candidate_source


def write_fictomed_config(
    *,
    config_file: Path,
    project_root: Path,
    run_dir: Path,
) -> dict[str, Path]:
    """Écrit un servers.yaml avec des chemins absolus et cohérents."""
    config_file = Path(config_file).expanduser().resolve()
    project_root = Path(project_root).expanduser().resolve()
    run_dir = Path(run_dir).expanduser().resolve()

    aphp_input_dir = (project_root / "data" / "aphp").resolve()
    aphp_referentials_dir = (aphp_input_dir / "referentials").resolve()
    aphp_output_dir = (run_dir / "sorties" / "scenarios").resolve()
    brest_input_dir = (project_root / "data" / "brest").resolve()
    brest_output_dir = (run_dir / "sorties" / "scenarios_brest").resolve()

    config_file.parent.mkdir(parents=True, exist_ok=True)
    aphp_output_dir.mkdir(parents=True, exist_ok=True)
    brest_output_dir.mkdir(parents=True, exist_ok=True)

    config = {
        "pipelines": {
            "brest": {
                "data": {
                    "input": str(brest_input_dir),
                    "output": str(brest_output_dir),
                }
            },
            "aphp": {
                "data": {
                    "input": str(aphp_input_dir),
                    "output": str(aphp_output_dir),
                    "referentials": str(aphp_referentials_dir),
                }
            },
        }
    }

    with config_file.open("w", encoding="utf-8") as file:
        yaml.safe_dump(
            config,
            file,
            allow_unicode=True,
            sort_keys=False,
        )

    print("Configuration fictomed :", config_file)
    print()
    print(config_file.read_text(encoding="utf-8"))

    if not aphp_input_dir.is_dir():
        raise FileNotFoundError(
            f"Le dossier de données AP-HP est introuvable : {aphp_input_dir}"
        )

    if not aphp_referentials_dir.is_dir():
        raise FileNotFoundError(
            f"Le dossier de référentiels AP-HP est introuvable : "
            f"{aphp_referentials_dir}"
        )

    return {
        "config_file": config_file,
        "aphp_input": aphp_input_dir,
        "aphp_referentials": aphp_referentials_dir,
        "aphp_output": aphp_output_dir,
        "brest_input": brest_input_dir,
        "brest_output": brest_output_dir,
    }


def generate_and_select_fictomed_scenarios(
    *,
    candidate_source: pl.DataFrame,
    config_file: Path,
    aphp_data_dir: Path,
    paths: dict[str, Path],
    scenario_filters: list[dict[str, Any]],
    target_n: int,
    random_selection: bool,
    random_seed: int,
    run_dir: Path,
) -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame]:
    """Remplace temporairement profiles, génère puis sélectionne les scénarios."""
    import fictomed
    from fictomed.sites.aphp.loader import _resolve_pmsi_file

    config_file = Path(config_file).expanduser().resolve()
    aphp_data_dir = Path(aphp_data_dir).expanduser().resolve()
    run_dir = Path(run_dir).expanduser().resolve()

    with config_file.open("r", encoding="utf-8") as file:
        loaded_config = yaml.safe_load(file) or {}

    configured_input = Path(
        loaded_config["pipelines"]["aphp"]["data"]["input"]
    ).expanduser().resolve()

    if configured_input != aphp_data_dir:
        raise RuntimeError(
            "Le dossier AP-HP passé au notebook et celui de servers.yaml diffèrent :\n"
            f"- APHP_DATA_DIR : {aphp_data_dir}\n"
            f"- config input  : {configured_input}"
        )

    active_profiles_path = Path(
        _resolve_pmsi_file(configured_input, "profiles")
    ).resolve()

    print("fictomed importé depuis :", fictomed.__file__)
    print("Dossier lu par fictomed :", configured_input)
    print("Profiles actif          :", active_profiles_path)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = (
        Path(paths["backups"])
        / f"{active_profiles_path.name}.{timestamp}.backup"
    )
    shutil.copy2(active_profiles_path, backup_path)
    print("Backup                  :", backup_path)

    try:
        candidate_source.write_parquet(active_profiles_path)
        active_check = pl.read_parquet(active_profiles_path)
        if active_check.height != candidate_source.height:
            raise RuntimeError(
                f"Le profiles actif contient {active_check.height} lignes "
                f"au lieu de {candidate_source.height}."
            )

        generated_candidates = fictomed.generate(
            pipeline_name="aphp",
            n_sejours=candidate_source.height,
            config_file=config_file,
        )
    finally:
        shutil.copy2(backup_path, active_profiles_path)
        print("Profiles original restauré :", active_profiles_path)

    if not isinstance(generated_candidates, pl.DataFrame):
        generated_candidates = pl.DataFrame(generated_candidates)

    print("\nScénarios candidats générés :", generated_candidates.shape)
    for column in ("source_row_id", "source_scenario_id", "generation_id"):
        if column in generated_candidates.columns:
            print(
                f"{column}: {generated_candidates[column].n_unique()} "
                f"uniques / {generated_candidates.height}"
            )

    generated_filtered = apply_filters(
        generated_candidates,
        scenario_filters,
        label="SCÉNARIO FICTOMED",
    )

    if generated_filtered.height < int(target_n):
        if "template_name" in generated_candidates.columns:
            print("\nRépartition des templates disponibles :")
            print(
                generated_candidates
                .group_by("template_name")
                .len()
                .sort("len", descending=True)
            )
        raise ValueError(
            f"Seulement {generated_filtered.height} scénario(s) après filtres, "
            f"mais TARGET_N={target_n}. Augmenter CANDIDATE_POOL_SIZE ou "
            "élargir les filtres."
        )

    if random_selection:
        selected_scenarios = generated_filtered.sample(
            n=int(target_n),
            with_replacement=False,
            shuffle=True,
            seed=int(random_seed),
        )
    else:
        selected_scenarios = generated_filtered.head(int(target_n))

    selected_path = run_dir / "scenarios_fictomed_selected.parquet"
    selected_scenarios.write_parquet(selected_path)

    print("\nScénarios retenus :", selected_scenarios.shape)
    print("Écrit             :", selected_path)

    return generated_candidates, generated_filtered, selected_scenarios


# ---------------------------------------------------------------------------
# Typologie des séjours et tirage stratifié
#
# Extraits du notebook de génération (cellules « typologie » et « tirage
# stratifié », septembre 2026), à l'identique — mêmes règles, mêmes messages.
# ---------------------------------------------------------------------------

# Typologie des séjours — TPEC (type de prise en charge) / DPEC (détail).
# CMD = 2 premiers caractères du GHM ; type GHM = 3e ; sévérité = dernier.
# L'ordre des .when() fait la précédence : le spécifique (séances, obstétrique,
# néonat, séjours complexes) AVANT le tout-venant médecine/chirurgie, sinon les
# GHM 14Z/15M/27Z/28Z seraient avalés par « type M ou Z ».

RACINES_GREFFES_CART = ["27Z02", "27Z03"]
RACINES_TRANSPLANT = ["27C02", "27C03", "27C04", "27C05", "27C06", "27C07"]
RACINES_IMG_FC = ["14Z04", "14C05", "14C06", "14C09", "14Z10", "14Z15", "14Z09"]
GHM_ACC_NORMAL = ["14C03A","14C07A", "14C08A", "14Z11A", "14Z12A",
                  "14Z13A", "14Z13T", "14Z14A", "14Z14T"]
RACINES_ACC_PATHO = ["14C07", "14C08", "14Z10", "14Z11", "14Z12", "14Z13", "14Z14"]
GHM_BB_NORMAL = ["15M05A", "15M06A", "15M07A", "15M08A", "15M09A",
                 "15M10A", "15M11A", "15M13A", "15M14A"]
RACINES_BB_MED = ["15M05", "15M06", "15M07", "15M08", "15M09",
                  "15M10", "15M11", "15M13", "15M14"]
RACINES_BB_CHIR = ["15C02", "15C03", "15C04", "15C05", "15C06",
                   "15M10", "15M11", "15M13", "15M14"]
RACINES_AUTRE_NEONAT = ["15M02", "15M03", "15M04"]

DPEC_TO_TPEC = {
    "Séances simples": "Médecine",
    "Séance polysomno": "Médecine",
    "Séance chimiothérapie simple adulte": "Médecine",
    "HDJ médecine adultes": "Médecine",
    "Médecine adultes > 3 nuits": "Médecine",
    "Médecine adultes < 3 nuits": "Médecine",
    "Interventionnel adultes < 3 nuits": "Chirurgie et interventionnel",
    "Chirurgie adultes < 3 nuits": "Chirurgie et interventionnel",
    "Interventionnel adultes > 3 nuits": "Chirurgie et interventionnel",
    "Chirurgie adultes > 3 nuits": "Chirurgie et interventionnel",
    "Greffes de moelle, CAR-T Cells": "Séjours complexes",
    "Transplantations": "Séjours complexes",
    "Brûlés": "Séjours complexes",
    "IVG": "Obstétrique",
    "IMG & fausses couches": "Obstétrique",
    "Accouchement normal mère": "Obstétrique",
    "Accouchement pathologique mère": "Obstétrique",
    "Bébé normal": "Néonatalogie",
    "Bébé néonat med": "Néonatalogie",
    "Bébé néonat chir": "Néonatalogie",
    "Autre néonat": "Néonatalogie",
    "Autre": "Autre",
}

# Colonnes du fichier source lues par with_typologie.
COLONNES_TYPOLOGIE = ("ghm2", "racine", "diag2", "duree", "mode_hospit", "agean")


def with_typologie(df: pl.DataFrame) -> pl.DataFrame:
    """Ajoute les colonnes ``DPEC`` (détail de la prise en charge, une
    vingtaine de modalités) et ``TPEC`` (type de prise en charge, six
    modalités agrégées via :data:`DPEC_TO_TPEC`).

    Colonnes requises (:data:`COLONNES_TYPOLOGIE`) : ``ghm2`` (GHM — CMD,
    type, sévérité), ``racine``, ``diag2`` (DP), ``duree``, ``mode_hospit``
    (``HP`` = hospitalisation partielle), ``agean`` (âge en années).
    Applicable au parquet source ; à reporter au niveau scénario (mêmes noms
    de colonnes dans le DataFrame fictomed). Une ligne qui ne tombe dans
    aucune règle (durée nulle, GHM inconnu…) est classée ``Autre``.
    """
    cmd = pl.col("ghm2").str.slice(0, 2)
    type_ghm = pl.col("ghm2").str.slice(2, 1)
    sev = pl.col("ghm2").str.slice(-1)
    racine = pl.col("racine")
    dp = pl.col("diag2")
    duree = pl.col("duree")
    adulte = pl.col("agean") >= 18
    hdj = pl.col("mode_hospit") == "HP"

    dpec = (
        # --- Séjours complexes (CMD 27, 22)
        pl.when(racine.is_in(RACINES_GREFFES_CART))
        .then(pl.lit("Greffes de moelle, CAR-T Cells"))
        .when(racine.is_in(RACINES_TRANSPLANT)).then(pl.lit("Transplantations"))
        .when(cmd == "22").then(pl.lit("Brûlés"))  # critère à confirmer (CMD 22)
        # --- Obstétrique
        .when(pl.col("ghm2") == "14Z08Z").then(pl.lit("IVG"))
        .when(racine.is_in(RACINES_IMG_FC)).then(pl.lit("IMG & fausses couches"))
        .when(pl.col("ghm2").is_in(GHM_ACC_NORMAL))
        .then(pl.lit("Accouchement normal mère"))
        .when(((racine.is_in(RACINES_ACC_PATHO) & ~sev.is_in(["A", "T"]))))
        .then(pl.lit("Accouchement pathologique mère"))
        # --- Néonatalogie
        .when(pl.col("ghm2").is_in(GHM_BB_NORMAL)).then(pl.lit("Bébé normal"))
        .when(racine.is_in(RACINES_BB_MED)).then(pl.lit("Bébé néonat med"))
        .when(racine.is_in(RACINES_BB_CHIR)).then(pl.lit("Bébé néonat chir"))
        .when(racine.is_in(RACINES_AUTRE_NEONAT)).then(pl.lit("Autre néonat"))
        # --- Médecine : séances (les spécifiques avant le tout-venant CMD 28)
        .when((cmd == "28") & (dp == "Z04801")).then(pl.lit("Séance polysomno"))
        .when((cmd == "28") & (dp == "Z511") & adulte)
        .then(pl.lit("Séance chimiothérapie simple adulte"))
        .when(cmd == "28").then(pl.lit("Séances simples"))
        # --- Médecine hors séances (HDJ d'abord, puis durée ; borne : 3 nuits
        #     et plus => « > 3 nuits », pour ne pas laisser duree == 3 sans case)
        .when(hdj & type_ghm.is_in(["M", "Z"])).then(pl.lit("HDJ médecine adultes"))
        .when((duree >= 3) & type_ghm.is_in(["M", "Z"]))
        .then(pl.lit("Médecine adultes > 3 nuits"))
        .when((duree < 3) & type_ghm.is_in(["M", "Z"]))
        .then(pl.lit("Médecine adultes < 3 nuits"))
        # --- Chirurgie et interventionnel (même borne à 3)
        .when((duree < 3) & (type_ghm == "K"))
        .then(pl.lit("Interventionnel adultes < 3 nuits"))
        .when((duree < 3) & (type_ghm == "C")).then(pl.lit("Chirurgie adultes < 3 nuits"))
        .when((duree >= 3) & (type_ghm == "K"))
        .then(pl.lit("Interventionnel adultes > 3 nuits"))
        .when((duree >= 3) & (type_ghm == "C")).then(pl.lit("Chirurgie adultes > 3 nuits"))
        .otherwise(pl.lit("Autre"))
    )
    return df.with_columns(dpec.alias("DPEC")).with_columns(
        pl.col("DPEC").replace_strict(DPEC_TO_TPEC, default="Autre").alias("TPEC")
    )


def ensure_source_ids(df: pl.DataFrame, source_path: Path) -> pl.DataFrame:
    """Pose les identifiants de traçabilité aval s'ils manquent :
    ``source_row_id`` (index de ligne) et ``source_scenario_id``
    (``<stem du fichier source>_row_<index sur 7 chiffres>``).

    Réplique l'identification de :func:`prepare_source_candidates` — à
    appeler sur le parquet COMPLET, avant tout filtre, pour que
    ``source_row_id`` reste celui du fichier. Idempotent.
    """
    if "source_row_id" not in df.columns:
        df = df.with_row_index("source_row_id")
    if "source_scenario_id" not in df.columns:
        df = df.with_columns(
            (
                pl.lit(Path(source_path).stem + "_row_")
                + pl.col("source_row_id").cast(pl.Utf8).str.zfill(7)
            ).alias("source_scenario_id")
        )
    return df


def quotas_couverture(df: pl.DataFrame, by: str = "DPEC") -> dict[str, int]:
    """Quotas « couverture » : un séjour par modalité de ``by`` présente dans
    ``df`` (modalités triées, nuls ignorés) — le smoke d'un nouveau fichier.
    """
    modalites = sorted(m for m in df[by].unique().to_list() if m is not None)
    return {m: 1 for m in modalites}


def tirage_stratifie(
    df: pl.DataFrame,
    quotas: dict[str, int] | str,
    *,
    by: str = "DPEC",
    seed: int = 42,
) -> pl.DataFrame:
    """Tire au sort `quotas[modalité]` lignes dans chaque strate de `by`.

    ``quotas`` : ``{modalité: effectif}`` (un quota à 0 documente une strate
    volontairement exclue), ou la chaîne ``"couverture"`` — un séjour par
    modalité présente (:func:`quotas_couverture`).

    Refuse si une modalité est inconnue ou si l'effectif disponible est
    insuffisant. Retourne la concaténation des strates (ordre des quotas) ;
    reproductible à ``seed`` donné.
    """
    if isinstance(quotas, str):
        if quotas != "couverture":
            raise ValueError(
                f"quotas inconnus : {quotas!r} — dict {{modalité: n}}, "
                "\"couverture\" ou None (tirage simple)."
            )
        quotas = quotas_couverture(df, by)
        print(f"Couverture : 1 séjour par modalité de {by} présente "
              f"({len(quotas)} modalité(s)).")
    dispo = dict(df.group_by(by).len().iter_rows())
    absentes_zero = [m for m, n in quotas.items() if n == 0 and m not in dispo]
    if absentes_zero:
        print(f"(quotas à 0 sur modalités absentes de {by} — sans effet : "
              f"{absentes_zero})")
    manquants = {m: (n, dispo.get(m, 0)) for m, n in quotas.items()
                 if n > 0 and dispo.get(m, 0) < n}
    if manquants:
        raise ValueError(
            f"Effectifs insuffisants (demandé, disponible) : {manquants} — "
            f"modalités disponibles : {sorted(dispo)}"
        )
    parts = [
        df.filter(pl.col(by) == m).sample(n=n, with_replacement=False,
                                          shuffle=True, seed=seed)
        for m, n in quotas.items() if n > 0
    ]
    tirage = pl.concat(parts)
    print(f"Tirage stratifié par {by} : {tirage.height} séjours "
          f"({len(parts)} strate(s), seed={seed}).")
    return tirage


# ---------------------------------------------------------------------------
# Dérivation de l'âge numérique (agean) depuis la classe d'âge (cage)
#
# Les corpus de campagne (scenarios_bn_pmsi) ne livrent PAS l'âge exact :
# il est agrégé en classes (« cage », libellés « [a-b[ ») dès l'extraction —
# protection assumée. Le contrat historique du producteur (utils.R v7,
# l. 236/275) fabriquait agean en aval ; reproduit ici côté Python. agean
# est donc une VARIABLE DÉRIVÉE que le CRH utilise ; elle ne doit jamais
# être confondue avec une donnée observée.
# ---------------------------------------------------------------------------

_MOTIF_CAGE = re.compile(r"^\[(\d+)-(\d*)\[$")

# Classe ouverte du haut (« [80-[ ») : borne basse à borne basse + 9. Choix
# documenté : une largeur de dix ans comme les classes fermées adultes ; les
# âges réels y dépassent 89 (C1 : jusqu'à 95), l'uniforme d'abord — voir la
# question consignée sur une distribution intra-classe côté producteur.
LARGEUR_CLASSE_OUVERTE = 10

# Frontière mineur / majeur : la Politique d'enrichissement exclut les
# mineurs (age_min = 18) ; un tirage à cheval ferait basculer un même
# scénario enrichi / exclu selon la graine.
SEUIL_MAJORITE = 18
PIVOTS_MAJORITE = {"lt_18": (None, SEUIL_MAJORITE - 1), "ge_18": (SEUIL_MAJORITE, None)}


def graine_ligne(cle: object, domaine: str = "agean") -> int:
    """Graine stable d'une ligne : sha256 de ``"<domaine>|<cle>"``, 8 premiers
    octets en entier. Même mécanique que ``scripts/substituer_dp_imprecis.py``
    (JAMAIS ``hash()`` natif, salé par processus) ; le préfixe ``domaine``
    sépare les tirages (DP substitué, âge) d'une même ligne."""
    return int.from_bytes(
        hashlib.sha256(f"{domaine}|{cle}".encode("utf-8")).digest()[:8], "big"
    )


def bornes_cage(libelle: str) -> tuple[int, int]:
    """Bornes ENTIÈRES INCLUSES d'une classe d'âge « [a-b[ » : ``a`` à
    ``b - 1`` ; « [0-1[ » → (0, 0) ; classe ouverte « [a-[ » → ``a`` à
    ``a + LARGEUR_CLASSE_OUVERTE - 1``. Libellé inattendu → ``ValueError``
    explicite (aucune interprétation silencieuse)."""
    texte = str(libelle).strip()
    m = _MOTIF_CAGE.match(texte)
    if not m:
        raise ValueError(
            f"classe d'âge illisible : {libelle!r} — libellé attendu « [a-b[ » "
            "(bornes entières, haute exclue) ou « [a-[ » (classe ouverte)."
        )
    lo = int(m.group(1))
    hi = int(m.group(2)) - 1 if m.group(2) else lo + LARGEUR_CLASSE_OUVERTE - 1
    if hi < lo:
        raise ValueError(f"classe d'âge vide : {libelle!r} (borne haute ≤ borne basse).")
    return lo, hi


@dataclass
class DerivationAgean:
    """Ce que :func:`deriver_agean` a fait — à imprimer dans le récap du pool."""

    derive: bool                      # agean dérivée (True) ou lue du fichier
    source: str                       # "lu du fichier" | "dérivé de cage" | "dérivé de cage, pivot age"
    n_lignes: int = 0
    n_derives: int = 0
    n_pivot_restreint: int = 0        # lignes où le pivot a resserré l'intervalle
    n_pivot_contradictoire: int = 0   # pivot incompatible avec la classe : pivot ignoré
    n_pivot_inconnu: int = 0          # pivot hors ge_18 / lt_18 (ex. valeur numérique)
    n_sans_classe: int = 0            # cage nulle : agean nul
    classes_chevauchant_18: list[str] = field(default_factory=list)
    n_chevauchant_18_sans_pivot: int = 0
    constats: list[str] = field(default_factory=list)

    def texte(self) -> str:
        if not self.derive:
            return f"agean : {self.source} ({self.n_lignes} lignes) — conservée telle quelle."
        lignes = [f"agean : {self.source} — {self.n_derives}/{self.n_lignes} lignes "
                  "(tirage entier uniforme dans la classe, déterministe par id_scenario ; "
                  "variable DÉRIVÉE, pas une donnée observée)."]
        lignes += [f"  - {c}" for c in self.constats]
        return "\n".join(lignes)


def deriver_agean(
    df: pl.DataFrame,
    *,
    colonne_cage: str = "cage",
    colonne_cle: str = "id_scenario",
    colonne_pivot: str = "age",
) -> tuple[pl.DataFrame, DerivationAgean]:
    """Ajoute ``agean`` (Int32) : tirage ENTIER uniforme dans les bornes de
    la classe d'âge ``colonne_cage`` (:func:`bornes_cage`), DÉTERMINISTE —
    graine par ligne :func:`graine_ligne` dérivée de ``colonne_cle`` (deux
    passes, y compris entre processus, donnent le même résultat ; les
    lignes partageant la clé — variantes d'un même scénario — reçoivent le
    même âge). L'entier uniforme est le sha256 tronqué réduit modulo la
    largeur de la classe (biais < 2⁻⁵⁷, sans objet).

    NE JAMAIS ÉCRASER : si ``df`` porte déjà un ``agean`` numérique (ancien
    format), il est rendu tel quel (``derive=False``) ; un ``agean`` non
    numérique est une erreur explicite.

    Cohérence à la frontière des 18 ans : quand la colonne pivot
    ``colonne_pivot`` vaut ``ge_18`` / ``lt_18`` (branche longue des
    campagnes), le tirage est restreint au sous-intervalle de la classe
    compatible ; un pivot contradictoire avec la classe est ignoré et
    compté ; une autre valeur (ex. âge numérique en chaîne, branche courte
    de C1) n'est pas un pivot : comptée, sans effet. Sans pivot, une classe
    qui chevauche 18 ans est CONSIGNÉE dans le rapport (information de
    campagne, pas un choix silencieux). Une classe nulle donne un ``agean``
    nul, compté.

    Retourne ``(df, rapport)`` ; ``rapport.texte()`` est la ligne du récap.
    """
    if "agean" in df.columns:
        if not df["agean"].dtype.is_numeric():
            raise ValueError(
                f"agean présente mais non numérique ({df['agean'].dtype}) : "
                "la dérivation ne s'applique qu'à son absence, et un agean "
                "illisible n'est pas écrasé — corriger le fichier."
            )
        return df, DerivationAgean(False, "lu du fichier", n_lignes=df.height)
    manquantes = [c for c in (colonne_cage, colonne_cle) if c not in df.columns]
    if manquantes:
        raise ValueError(
            f"dérivation d'agean impossible : colonne(s) manquante(s) {manquantes} "
            f"(classe d'âge {colonne_cage!r}, clé de graine {colonne_cle!r})."
        )

    classes = df[colonne_cage].cast(pl.String).str.strip_chars()
    bornes = {lib: bornes_cage(lib) for lib in classes.drop_nulls().unique().to_list()}
    a_pivot = colonne_pivot in df.columns
    pivots = df[colonne_pivot].cast(pl.String).to_list() if a_pivot else None
    cles = df[colonne_cle].to_list()

    rapport = DerivationAgean(
        True, "dérivé de cage" + (", pivot age" if a_pivot else ""), n_lignes=df.height)
    rapport.classes_chevauchant_18 = sorted(
        lib for lib, (lo, hi) in bornes.items() if lo < SEUIL_MAJORITE <= hi)

    graines: dict[object, int] = {}
    valeurs: list[int | None] = []
    for i, lib in enumerate(classes.to_list()):
        if lib is None:
            rapport.n_sans_classe += 1
            valeurs.append(None)
            continue
        lo, hi = bornes[lib]
        chevauche = lo < SEUIL_MAJORITE <= hi
        pivot_valide = False
        if a_pivot:
            p = pivots[i]
            if p in PIVOTS_MAJORITE:
                pivot_valide = True
                p_lo, p_hi = PIVOTS_MAJORITE[p]
                lo2 = lo if p_lo is None else max(lo, p_lo)
                hi2 = hi if p_hi is None else min(hi, p_hi)
                if lo2 > hi2:
                    rapport.n_pivot_contradictoire += 1
                elif (lo2, hi2) != (lo, hi):
                    rapport.n_pivot_restreint += 1
                    lo, hi = lo2, hi2
            elif p is not None:
                rapport.n_pivot_inconnu += 1
        if chevauche and not pivot_valide:
            rapport.n_chevauchant_18_sans_pivot += 1
        cle = cles[i]
        g = graines.get(cle)
        if g is None:
            g = graines[cle] = graine_ligne(cle)
        valeurs.append(lo + g % (hi - lo + 1))
        rapport.n_derives += 1

    if rapport.n_pivot_restreint:
        rapport.constats.append(
            f"pivot {colonne_pivot} (ge_18 / lt_18) : intervalle resserré sur "
            f"{rapport.n_pivot_restreint} ligne(s) (classe à cheval sur 18 ans).")
    if rapport.n_pivot_contradictoire:
        rapport.constats.append(
            f"pivot {colonne_pivot} contradictoire avec la classe sur "
            f"{rapport.n_pivot_contradictoire} ligne(s) : pivot ignoré, classe conservée.")
    if rapport.n_pivot_inconnu:
        rapport.constats.append(
            f"pivot {colonne_pivot} hors ge_18 / lt_18 sur {rapport.n_pivot_inconnu} "
            "ligne(s) (ex. âge numérique en chaîne) : sans effet sur le tirage.")
    if rapport.classes_chevauchant_18:
        rapport.constats.append(
            f"classe(s) chevauchant 18 ans : {rapport.classes_chevauchant_18} — "
            + (f"{rapport.n_chevauchant_18_sans_pivot} ligne(s) tirée(s) sans pivot : "
               "peut basculer mineur / majeur selon la graine (enrichissement exclu < 18)."
               if rapport.n_chevauchant_18_sans_pivot else "toutes résolues par le pivot."))
    if rapport.n_sans_classe:
        rapport.constats.append(
            f"{rapport.n_sans_classe} ligne(s) sans classe d'âge : agean nul.")
    return df.with_columns(pl.Series("agean", valeurs, dtype=pl.Int32)), rapport


# ---------------------------------------------------------------------------
# Garde-fou racine — réparation depuis le GHM (24/09/2026)
#
# La branche courte de C1 livre `racine` nulle (erreur du producteur,
# correction amont prévue). La relation vraie : racine = ghm2[:5]. Après la
# correction amont, le compteur de réparations DEVRA valoir 0 — c'est un
# contrôle d'intégrité, pas un service permanent.
# ---------------------------------------------------------------------------

@dataclass
class ReparationRacine:
    """Ce que :func:`reparer_racine` a fait — à imprimer dans le récap."""

    n_lignes: int = 0
    n_reparees: int = 0            # racine nulle, ghm2 présent → ghm2[:5]
    n_irreparables: int = 0        # racine ET ghm2 nuls : racine reste nulle
    n_divergentes: int = 0         # racine observée ≠ ghm2[:5] : NON modifiée
    exemples_divergence: list[tuple[str, str]] = field(default_factory=list)
    colonne_creee: bool = False    # `racine` absente du fichier : créée entièrement

    def texte(self) -> str:
        lignes = [f"racine : {self.n_reparees}/{self.n_lignes} réparée(s) depuis ghm2[:5]"
                  + (" (colonne absente du fichier : créée)" if self.colonne_creee else "")
                  + " — après la correction amont, ce compteur doit valoir 0."]
        if self.n_irreparables:
            lignes.append(f"  - {self.n_irreparables} ligne(s) sans racine ni ghm2 : racine nulle.")
        if self.n_divergentes:
            lignes.append(f"  - {self.n_divergentes} ligne(s) où racine observée ≠ ghm2[:5] — "
                          f"NON modifiées (l'observé prime), ex. {self.exemples_divergence}")
        return "\n".join(lignes)


def reparer_racine(df: pl.DataFrame) -> tuple[pl.DataFrame, ReparationRacine]:
    """Répare ``racine`` depuis ``ghm2`` : ``racine = ghm2[:5]`` quand
    ``racine`` est nulle et ``ghm2`` non nul, sinon ``racine`` inchangée.
    Colonne de trace ``racine_reparee`` (booléen). Une racine observée qui
    diverge de ``ghm2[:5]`` est SIGNALÉE (comptée, exemples) sans être
    modifiée : l'observé prime, la divergence est une information de
    campagne. Sans ``racine`` ni ``ghm2`` → ``ValueError``.

    Retourne ``(df, rapport)`` ; ``rapport.n_reparees`` doit tomber à 0
    après la correction amont (contrôle d'intégrité).
    """
    a_racine, a_ghm2 = "racine" in df.columns, "ghm2" in df.columns
    if not a_racine and not a_ghm2:
        raise ValueError("réparation de racine impossible : ni `racine` ni `ghm2` dans le fichier.")
    rapport = ReparationRacine(n_lignes=df.height, colonne_creee=not a_racine)
    if not a_ghm2:
        return df.with_columns(pl.lit(False).alias("racine_reparee")), rapport
    if not a_racine:
        df = df.with_columns(pl.lit(None, dtype=pl.String).alias("racine"))
    ghm5 = pl.col("ghm2").cast(pl.String).str.slice(0, 5)
    reparable = pl.col("racine").is_null() & pl.col("ghm2").is_not_null()
    divergente = pl.col("racine").is_not_null() & pl.col("ghm2").is_not_null() & (ghm5 != pl.col("racine"))
    stats = df.select(
        reparable.sum().alias("reparees"),
        (pl.col("racine").is_null() & pl.col("ghm2").is_null()).sum().alias("irreparables"),
        divergente.sum().alias("divergentes"),
    ).row(0, named=True)
    rapport.n_reparees = int(stats["reparees"])
    rapport.n_irreparables = int(stats["irreparables"])
    rapport.n_divergentes = int(stats["divergentes"])
    if rapport.n_divergentes:
        rapport.exemples_divergence = [
            (r, g) for r, g in df.filter(divergente).select("racine", "ghm2").unique().head(5).iter_rows()
        ]
    return df.with_columns(
        pl.when(reparable).then(ghm5).otherwise(pl.col("racine")).alias("racine"),
        reparable.alias("racine_reparee"),
    ), rapport


# ---------------------------------------------------------------------------
# Spécialité (service d'hospitalisation) — observée ou dérivée (24/09/2026)
#
# Trois étages, par LIGNE (la spécialité est une propriété du séjour, pas du
# cas : les variantes de contexte d'un même id_scenario peuvent différer) :
#   1. type_unite a une entrée « valide » du mapping YAML → spécialité
#      observée ;
#   2. dictionnaire des spécialités par (racine réparée, groupe d'âge
#      ge_18 / lt_18 dérivé d'agean) : une candidate → elle ; plusieurs →
#      tirage pondéré par ratio, graine composite par ligne ;
#   3. aucune entrée → pas de spécialité (la ligne « - Service : » du prompt
#      restera absente, le modèle propose), compté.
# La colonne s'appelle `specialty` pour traverser fictomed tel quel
# (profile["specialty"] → scenario["department"] → « - Service : »).
# ---------------------------------------------------------------------------

DERIVER = "DERIVER"  # valeur du mapping : « pas une spécialité, l'étage 2 décide »
COLONNES_DICO_SPECIALITE = ("racine", "age", "lib_spe_uma", "ratio_spe_racine")  # schéma BRUT du parquet
COLONNES_GRAINE_SPECIALITE = ("id_scenario", "duree", "mode_entree", "mode_sortie", "mdp")
SOURCES_SPECIALITE = ("observee", "unique", "tiree", "repli")


def charger_mapping_type_unite(
    chemin: Path,
    vocabulaire: Iterable[str] | None = None,
) -> dict[str, str]:
    """Lit ``mapping_type_unite.yaml`` et rend les seules entrées
    APPLICABLES : ``statut: valide`` et spécialité différente de
    :data:`DERIVER` → ``{type_unite: spécialité}``. Une entrée en
    ``proposition`` est ignorée (l'étage 2 prend le relais) — corriger les
    statuts suffit à activer, sans autre geste. Si ``vocabulaire`` est
    donné (les libellés du dictionnaire des spécialités), une entrée
    valide hors vocabulaire est une erreur explicite.
    """
    import yaml

    chemin = Path(chemin)
    contenu = yaml.safe_load(chemin.read_text(encoding="utf-8")) or {}
    entrees = contenu.get("entrees", {}) or {}
    if not isinstance(entrees, dict):
        raise ValueError(f"{chemin} : `entrees` doit être un dictionnaire type_unite → entrée.")
    vocab = set(vocabulaire) if vocabulaire is not None else None
    applicables: dict[str, str] = {}
    for type_unite, entree in entrees.items():
        if not isinstance(entree, dict):
            raise ValueError(f"{chemin} : entrée {type_unite!r} illisible ({entree!r}).")
        if str(entree.get("statut", "")).strip().lower() != "valide":
            continue
        specialite = str(entree.get("specialite", "")).strip()
        if not specialite or specialite == DERIVER:
            continue
        if vocab is not None and specialite not in vocab:
            raise ValueError(
                f"{chemin} : entrée {type_unite!r} valide avec une spécialité hors "
                f"vocabulaire du dictionnaire : {specialite!r}.")
        applicables[str(type_unite).strip().upper()] = specialite
    return applicables


def _candidats_specialite(dico: pl.DataFrame) -> dict[tuple[str, str], list[tuple[str, float]]]:
    """``{(racine, groupe d'âge): [(spécialité, ratio), …]}`` triés par
    libellé ; vérifie le schéma BRUT et que les ratios somment à 1 par
    (racine, groupe) — échec bruyant sinon."""
    manquantes = [c for c in COLONNES_DICO_SPECIALITE if c not in dico.columns]
    if manquantes:
        raise ValueError(
            f"dictionnaire des spécialités : colonne(s) manquante(s) {manquantes} — "
            f"schéma brut attendu {list(COLONNES_DICO_SPECIALITE)}, trouvé {dico.columns}.")
    sommes = dico.group_by("racine", "age").agg(pl.col("ratio_spe_racine").sum().alias("s"))
    hors = sommes.filter((pl.col("s") - 1.0).abs() > 1e-6)
    if hors.height:
        raise ValueError(
            "dictionnaire des spécialités : les ratios ne somment pas à 1 par (racine, age) sur "
            f"{hors.height} groupe(s), ex. {hors.head(3).to_dicts()}.")
    table: dict[tuple[str, str], list[tuple[str, float]]] = {}
    for racine, age, lib, ratio in dico.select("racine", "age", "lib_spe_uma", "ratio_spe_racine") \
            .sort("racine", "age", "lib_spe_uma").iter_rows():
        table.setdefault((str(racine), str(age)), []).append((str(lib), float(ratio)))
    return table


@dataclass
class DerivationSpecialite:
    """Ce que :func:`deriver_specialite` a fait — à imprimer dans le récap."""

    n_lignes: int = 0
    par_source: dict[str, int] = field(default_factory=lambda: {s: 0 for s in SOURCES_SPECIALITE})
    n_mapping_applicable: int = 0
    colonnes_graine: tuple[str, ...] = ()
    racines_sans_entree: dict[str, int] = field(default_factory=dict)  # repli : racine → n (top)
    constats: list[str] = field(default_factory=list)

    def texte(self) -> str:
        repartition = ", ".join(f"{s} {n}" for s, n in self.par_source.items())
        lignes = [f"spécialité : {repartition} (sur {self.n_lignes}) — mapping type_unite : "
                  f"{self.n_mapping_applicable} entrée(s) valide(s) appliquée(s) ; graine composite "
                  f"{list(self.colonnes_graine)}."]
        if self.par_source["repli"]:
            lignes.append(f"  - repli (pas de ligne Service, le modèle propose) : "
                          f"{self.par_source['repli']} ligne(s) — racines sans entrée : "
                          f"{self.racines_sans_entree}")
        lignes += [f"  - {c}" for c in self.constats]
        return "\n".join(lignes)


def deriver_specialite(
    df: pl.DataFrame,
    dico: pl.DataFrame,
    mapping: dict[str, str] | None = None,
    *,
    colonne_type_unite: str = "type_unite",
) -> tuple[pl.DataFrame, DerivationSpecialite]:
    """Ajoute ``specialty`` et ``specialite_source`` (voir le bloc de
    commentaires ci-dessus pour les trois étages).

    ``dico`` : le parquet BRUT ``dictionnaire_spe_racine`` (colonnes
    :data:`COLONNES_DICO_SPECIALITE`) ; ``mapping`` : les entrées
    applicables de :func:`charger_mapping_type_unite`. Requiert ``racine``
    (réparée) et ``agean`` (dérivée) : le groupe d'âge est ``ge_18`` si
    ``agean >= 18`` sinon ``lt_18`` ; sans ``agean`` ni ``racine`` → repli.

    Tirage (étage 2, plusieurs candidates) : uniforme ``u`` en [0, 1) tiré du
    sha256 de ``"specialite" ‖ id_scenario ‖ duree ‖ mode_entree ‖
    mode_sortie ‖ mdp`` (:data:`COLONNES_GRAINE_SPECIALITE`, celles
    présentes), premier libellé dont le ratio cumulé dépasse ``u`` :
    déterministe par ligne, entre passes et entre processus, indépendant
    de l'ordre ; deux lignes identiques sur ces colonnes tirent la même
    spécialité, deux contextes différents tirent indépendamment.
    """
    candidats = _candidats_specialite(dico)
    mapping = {k.strip().upper(): v for k, v in (mapping or {}).items()}
    rapport = DerivationSpecialite(n_lignes=df.height, n_mapping_applicable=len(mapping))
    colonnes_graine = tuple(c for c in COLONNES_GRAINE_SPECIALITE if c in df.columns)
    rapport.colonnes_graine = colonnes_graine
    if "id_scenario" not in colonnes_graine:
        rapport.constats.append("id_scenario absent : graine composite sur les seules colonnes de contexte.")

    racines = df["racine"].cast(pl.String).to_list() if "racine" in df.columns else [None] * df.height
    ages = df["agean"].to_list() if "agean" in df.columns else [None] * df.height
    types = (df[colonne_type_unite].cast(pl.String).str.strip_chars().str.to_uppercase().to_list()
             if colonne_type_unite in df.columns else [None] * df.height)
    parties = [df[c].to_list() for c in colonnes_graine]
    if "agean" not in df.columns:
        rapport.constats.append("agean absente : groupe d'âge inconnu, étage 2 impossible (repli).")

    specialites: list[str | None] = []
    sources: list[str] = []
    sans_entree: dict[str, int] = {}
    for i in range(df.height):
        tu = types[i]
        if tu is not None and tu in mapping:
            specialites.append(mapping[tu]); sources.append("observee"); continue
        racine, age = racines[i], ages[i]
        cand = None
        if racine is not None and age is not None:
            groupe = "ge_18" if int(age) >= SEUIL_MAJORITE else "lt_18"
            cand = candidats.get((racine, groupe))
        if not cand:
            specialites.append(None); sources.append("repli")
            cle = racine if racine is not None else "(racine nulle)"
            sans_entree[cle] = sans_entree.get(cle, 0) + 1
            continue
        if len(cand) == 1:
            specialites.append(cand[0][0]); sources.append("unique"); continue
        graine = graine_ligne("‖".join(str(p[i]) for p in parties), domaine="specialite")
        u = graine / 2 ** 64
        cumul = 0.0
        choix = cand[-1][0]
        for lib, ratio in cand:
            cumul += ratio
            if u < cumul:
                choix = lib
                break
        specialites.append(choix); sources.append("tiree")

    for s in sources:
        rapport.par_source[s] += 1
    rapport.racines_sans_entree = dict(sorted(sans_entree.items(), key=lambda kv: -kv[1])[:8])
    return df.with_columns(
        pl.Series("specialty", specialites, dtype=pl.String),
        pl.Series("specialite_source", sources, dtype=pl.String),
    ), rapport

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

import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

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

    if "source_row_id" not in source_df.columns:
        source_df = source_df.with_row_index("source_row_id")

    if "source_scenario_id" not in source_df.columns:
        source_df = source_df.with_columns(
            (
                pl.lit(source_path.stem + "_row_")
                + pl.col("source_row_id").cast(pl.Utf8).str.zfill(7)
            ).alias("source_scenario_id")
        )

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

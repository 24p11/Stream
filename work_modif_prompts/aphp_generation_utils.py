from __future__ import annotations

"""Fonctions utilitaires du notebook AP-HP une/deux générations.

Le module ne contient aucune configuration propre à une expérience : les chemins,
filtres, modèles, limites de tokens et tarifs sont fournis par le notebook.
"""

from datetime import datetime
from pathlib import Path
from typing import Any
import importlib
import json
import re
import shutil
import subprocess
import sys
import time

import polars as pl
import yaml


# =============================================================================
# Localisation et installation
# =============================================================================


def looks_like_stream_root(path: Path) -> bool:
    """Indique si ``path`` ressemble à la racine du projet Stream."""
    path = Path(path)
    return (
        (path / "data" / "aphp").is_dir()
        and (path / "pipelines" / "aphp").is_dir()
        and (path / "core").is_dir()
    )


def find_stream_root(start: Path) -> Path:
    """Cherche la racine Stream dans ``start`` puis dans ses parents."""
    start = Path(start).expanduser().resolve()
    for candidate in (start, *start.parents):
        if looks_like_stream_root(candidate):
            return candidate.resolve()

    raise FileNotFoundError(
        "Impossible de détecter automatiquement la racine du projet Stream "
        f"depuis {start}. Renseignez PROJECT_ROOT_OVERRIDE."
    )


def run_command(
    command: list[str | Path],
    *,
    cwd: Path | None = None,
    check: bool = True,
    capture_output: bool = False,
) -> subprocess.CompletedProcess[str]:
    """Exécute une commande et affiche une trace lisible dans le notebook."""
    normalised_command = [str(part) for part in command]

    print("\n" + "=" * 100)
    print("$", " ".join(normalised_command))
    if cwd is not None:
        print("cwd :", Path(cwd))
    print("=" * 100)

    process = subprocess.run(
        normalised_command,
        cwd=cwd,
        stdout=subprocess.PIPE if capture_output else None,
        stderr=subprocess.STDOUT if capture_output else None,
        text=True,
    )

    if capture_output and process.stdout:
        print(process.stdout)

    if check and process.returncode != 0:
        raise RuntimeError(
            f"Commande échouée avec le code {process.returncode} :\n"
            f"{' '.join(normalised_command)}\n\n"
            f"Sortie complète :\n{process.stdout or ''}"
        )

    return process


def install_or_update_fictomed(
    *,
    dependencies_dir: Path,
    local_dir: Path,
    repo_url: str,
    branch: str,
    project_root: Path,
    python_executable: str | Path | None = None,
) -> None:
    """Clone/met à jour fictomed puis l'installe en mode éditable."""
    dependencies_dir = Path(dependencies_dir).expanduser().resolve()
    local_dir = Path(local_dir).expanduser().resolve()
    project_root = Path(project_root).expanduser().resolve()
    python_executable = str(python_executable or sys.executable)

    if shutil.which("git") is None:
        raise RuntimeError("Git n'est pas installé ou n'est pas disponible dans PATH.")

    dependencies_dir.mkdir(parents=True, exist_ok=True)

    branch_check = run_command(
        [
            "git",
            "ls-remote",
            "--heads",
            repo_url,
            f"refs/heads/{branch}",
        ],
        capture_output=True,
    )

    if not (branch_check.stdout or "").strip():
        raise RuntimeError(
            f"Branche distante introuvable : {branch!r} sur {repo_url}"
        )

    if not local_dir.exists():
        run_command(
            [
                "git",
                "clone",
                "--branch",
                branch,
                "--single-branch",
                repo_url,
                local_dir,
            ]
        )
    elif not (local_dir / ".git").is_dir():
        raise RuntimeError(
            f"{local_dir} existe mais n'est pas un dépôt Git. "
            "Renommez ou supprimez ce dossier avant de relancer."
        )
    else:
        status = (
            run_command(
                ["git", "status", "--porcelain"],
                cwd=local_dir,
                capture_output=True,
            ).stdout
            or ""
        ).strip()

        if status:
            print(
                "\nModifications locales détectées dans fictomed : la mise à jour "
                "distante est ignorée pour ne rien écraser."
            )
            print(status)
        else:
            run_command(
                ["git", "fetch", "origin", branch],
                cwd=local_dir,
            )
            run_command(
                ["git", "switch", branch],
                cwd=local_dir,
            )
            run_command(
                ["git", "pull", "--ff-only", "origin", branch],
                cwd=local_dir,
            )

    run_command(
        [
            python_executable,
            "-m",
            "pip",
            "install",
            "--editable",
            local_dir,
        ]
    )

    for path in (local_dir, project_root):
        path_text = str(path)
        if path_text not in sys.path:
            sys.path.insert(0, path_text)

    importlib.invalidate_caches()

    for module_name in list(sys.modules):
        if module_name == "fictomed" or module_name.startswith("fictomed."):
            del sys.modules[module_name]

    print("\nInstallation fictomed terminée.")


def verify_fictomed_installation(
    *,
    local_dir: Path,
    expected_branch: str,
) -> dict[str, Any]:
    """Vérifie le dépôt Git et le module fictomed effectivement importé."""
    import fictomed

    local_dir = Path(local_dir).expanduser().resolve()
    import_path = Path(fictomed.__file__).resolve()
    current_branch = (
        run_command(
            ["git", "branch", "--show-current"],
            cwd=local_dir,
            capture_output=True,
        ).stdout
        or ""
    ).strip()
    current_commit = (
        run_command(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=local_dir,
            capture_output=True,
        ).stdout
        or ""
    ).strip()

    is_expected_checkout = str(import_path).startswith(str(local_dir))

    print("fictomed importé depuis :", import_path)
    print("Branche active          :", current_branch)
    print("Commit                  :", current_commit)
    print("Dépôt local utilisé     :", is_expected_checkout)

    if current_branch != expected_branch:
        raise RuntimeError(
            f"Branche fictomed incorrecte : {current_branch!r}, "
            f"attendu {expected_branch!r}."
        )

    if not is_expected_checkout:
        raise RuntimeError(
            "Le kernel n'importe pas fictomed depuis le dépôt local attendu. "
            "Redémarrez le kernel puis réexécutez les cellules depuis le début."
        )

    print("\n✅ fictomed est correctement installé et importé.")

    return {
        "import_path": import_path,
        "branch": current_branch,
        "commit": current_commit,
        "is_expected_checkout": is_expected_checkout,
    }


# =============================================================================
# Filtres, données source et arborescence
# =============================================================================


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


def create_run_tree(run_dir: Path) -> dict[str, Path]:
    """Crée l'arborescence d'un run et renvoie ses chemins nommés."""
    run_dir = Path(run_dir).expanduser().resolve()
    paths = {
        "one_system": run_dir / "prompts/une_gen/system_prompt",
        "one_user": run_dir / "prompts/une_gen/user_prompt",
        "first_system": run_dir / "prompts/deux_gen/premiere_gen/system_prompt",
        "first_user": run_dir / "prompts/deux_gen/premiere_gen/user_prompt",
        "second_system": run_dir / "prompts/deux_gen/deuxieme_gen/system_prompt",
        "second_user": run_dir / "prompts/deux_gen/deuxieme_gen/user_prompt",
        "out_one": run_dir / "sorties/CR_1gen",
        "out_two": run_dir / "sorties/resume_CR_2gen",
        "backups": run_dir / "_backups",
        "batches": run_dir / "_mistral_batches",
    }

    for path in paths.values():
        path.mkdir(parents=True, exist_ok=True)

    return paths


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


# =============================================================================
# Fichiers de prompts
# =============================================================================


def safe_stem(value: Any) -> str:
    """Nettoie une valeur pour l'utiliser dans un nom de fichier."""
    text = re.sub(r"[^A-Za-z0-9._-]+", "_", str(value or "")).strip("_")
    return text or "scenario"


def write_text(path: Path, value: Any) -> None:
    """Écrit une valeur sous forme de texte UTF-8."""
    Path(path).write_text(str(value or ""), encoding="utf-8")


def create_prompt_files(
    *,
    selected_scenarios: pl.DataFrame,
    run_dir: Path,
    paths: dict[str, Path],
    one_gen_templates_dir: Path,
    first_gen_templates_dir: Path,
    second_gen_templates_dir: Path,
    clean_existing_prompts: bool = False,
) -> pl.DataFrame:
    """Crée les six familles de prompts et le manifest du run."""
    run_dir = Path(run_dir).expanduser().resolve()
    one_gen_templates_dir = Path(one_gen_templates_dir).expanduser().resolve()
    first_gen_templates_dir = Path(first_gen_templates_dir).expanduser().resolve()
    second_gen_templates_dir = Path(second_gen_templates_dir).expanduser().resolve()

    prompt_dirs = [
        paths["one_system"],
        paths["one_user"],
        paths["first_system"],
        paths["first_user"],
        paths["second_system"],
        paths["second_user"],
    ]

    if clean_existing_prompts:
        deleted_count = 0
        for directory in prompt_dirs:
            for path in Path(directory).glob("*.txt"):
                path.unlink()
                deleted_count += 1
        print("Anciens fichiers de prompts supprimés :", deleted_count)

    rows = list(selected_scenarios.iter_rows(named=True))
    missing_templates: set[Path] = set()

    for row in rows:
        template_name = str(row["template_name"])
        for template_path in (
            one_gen_templates_dir / template_name,
            first_gen_templates_dir / template_name,
            second_gen_templates_dir / template_name,
        ):
            if not template_path.exists():
                missing_templates.add(template_path)

    if missing_templates:
        print("Templates manquants :")
        for path in sorted(missing_templates, key=str):
            print("-", path)
        raise FileNotFoundError(
            "Créer les templates manquants avec exactement les noms de template_name."
        )

    manifest_rows: list[dict[str, Any]] = []

    for index, row in enumerate(rows):
        generation_id = str(row["generation_id"])
        template_name = str(row["template_name"])
        stem = (
            f"{index:04d}__{safe_stem(generation_id)}__"
            f"{safe_stem(Path(template_name).stem)}"
        )
        filename = stem + ".txt"

        one_system_path = Path(paths["one_system"]) / filename
        one_user_path = Path(paths["one_user"]) / filename
        first_system_path = Path(paths["first_system"]) / filename
        first_user_path = Path(paths["first_user"]) / filename
        second_system_path = Path(paths["second_system"]) / filename
        second_user_path = Path(paths["second_user"]) / filename

        source_one_template = one_gen_templates_dir / template_name
        source_first_template = first_gen_templates_dir / template_name
        source_second_template = second_gen_templates_dir / template_name

        write_text(one_user_path, row.get("user_prompt"))
        write_text(first_user_path, row.get("user_prompt"))
        write_text(second_user_path, row.get("user_prompt"))

        shutil.copy2(source_one_template, one_system_path)
        shutil.copy2(source_first_template, first_system_path)
        shutil.copy2(source_second_template, second_system_path)

        manifest_rows.append(
            {
                "generation_id": generation_id,
                "template_name": template_name,
                "file_stem": stem,
                "one_system_path": str(one_system_path.relative_to(run_dir)),
                "one_user_path": str(one_user_path.relative_to(run_dir)),
                "first_system_path": str(first_system_path.relative_to(run_dir)),
                "first_user_path": str(first_user_path.relative_to(run_dir)),
                "second_system_path": str(second_system_path.relative_to(run_dir)),
                "second_user_path": str(second_user_path.relative_to(run_dir)),
            }
        )

    manifest = pl.DataFrame(manifest_rows, infer_schema_length=None)
    manifest_path = run_dir / "manifest.parquet"
    manifest.write_parquet(manifest_path)
    print("Manifest écrit :", manifest_path)

    return manifest


def preview_prompt_files(
    *,
    run_dir: Path,
    preview_index: int = 0,
    max_chars: int = 8_000,
) -> None:
    """Affiche les six prompts d'une ligne du manifest."""
    from IPython.display import Markdown, display

    run_dir = Path(run_dir).expanduser().resolve()
    manifest = pl.read_parquet(run_dir / "manifest.parquet")

    if not 0 <= int(preview_index) < manifest.height:
        raise IndexError(
            f"PROMPT_PREVIEW_INDEX={preview_index} hors limites "
            f"pour un manifest de {manifest.height} ligne(s)."
        )

    row = manifest.row(int(preview_index), named=True)
    display(
        Markdown(
            f"### Scénario `{row['generation_id']}` — `{row['template_name']}`"
        )
    )

    for title, key in [
        ("Une génération — system prompt", "one_system_path"),
        ("Une génération — user prompt", "one_user_path"),
        ("Deux générations, première — system prompt", "first_system_path"),
        ("Deux générations, première — user prompt", "first_user_path"),
        ("Deux générations, deuxième — system prompt", "second_system_path"),
        ("Deux générations, deuxième — user prompt", "second_user_path"),
    ]:
        display(Markdown(f"#### {title}"))
        content = (run_dir / str(row[key])).read_text(encoding="utf-8")
        print(content[: int(max_chars)])


# =============================================================================
# Préparation et validation Mistral
# =============================================================================


def load_state(run_dir: Path) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Charge les scénarios sélectionnés et leur manifest."""
    run_dir = Path(run_dir).expanduser().resolve()
    scenarios = pl.read_parquet(run_dir / "scenarios_fictomed_selected.parquet")
    manifest = pl.read_parquet(run_dir / "manifest.parquet")
    return scenarios, manifest


def load_stage_prompts(
    scenarios: pl.DataFrame,
    manifest_df: pl.DataFrame,
    *,
    run_dir: Path,
    system_key: str,
    user_key: str,
    prefix_mode: str,
    first_gen_prefix: str,
    summary_insert_header: str,
    summary_insert_footer: str,
    summaries: dict[str, str] | None = None,
) -> pl.DataFrame:
    """Charge les prompts édités du disque pour une étape de génération."""
    run_dir = Path(run_dir).expanduser().resolve()
    rows: list[dict[str, str]] = []
    scenario_prefix = {
        str(row["generation_id"]): str(row.get("prefix") or "")
        for row in scenarios.iter_rows(named=True)
    }

    for item in manifest_df.iter_rows(named=True):
        generation_id = str(item["generation_id"])
        system_prompt = (run_dir / str(item[system_key])).read_text(
            encoding="utf-8"
        )
        user_prompt = (run_dir / str(item[user_key])).read_text(
            encoding="utf-8"
        )

        if summaries is not None:
            summary = summaries.get(generation_id, "")
            user_prompt = (
                user_prompt.rstrip()
                + "\n\n"
                + summary_insert_header.strip()
                + "\n\n"
                + summary.strip()
                + "\n\n"
                + summary_insert_footer.strip()
                + "\n"
            )

        if prefix_mode == "original":
            prefix = scenario_prefix[generation_id]
        elif prefix_mode == "first":
            prefix = first_gen_prefix
        elif prefix_mode == "empty":
            prefix = ""
        else:
            raise ValueError(f"prefix_mode inconnu : {prefix_mode}")

        rows.append(
            {
                "generation_id": generation_id,
                "system_prompt_edit": system_prompt,
                "user_prompt_edit": user_prompt,
                "prefix_edit": prefix,
            }
        )

    prompt_df = pl.DataFrame(rows, infer_schema_length=None)
    drop_cols = [
        column
        for column in ("system_prompt", "user_prompt", "prefix")
        if column in scenarios.columns
    ]

    return (
        scenarios.drop(drop_cols)
        .join(prompt_df, on="generation_id", how="inner")
        .rename(
            {
                "system_prompt_edit": "system_prompt",
                "user_prompt_edit": "user_prompt",
                "prefix_edit": "prefix",
            }
        )
    )


def reports_to_map(reports_df: pl.DataFrame) -> dict[str, str]:
    """Transforme un DataFrame de rapports en mapping generation_id -> report."""
    return {
        str(row["generation_id"]): str(row.get("report") or "")
        for row in reports_df.iter_rows(named=True)
    }


def save_individual_outputs(
    reports_df: pl.DataFrame,
    manifest_df: pl.DataFrame,
    *,
    output_dir: Path,
    filename_prefix: str,
) -> None:
    """Enregistre chaque sortie Mistral dans un fichier texte individuel."""
    stems = {
        str(row["generation_id"]): str(row["file_stem"])
        for row in manifest_df.iter_rows(named=True)
    }
    output_dir = Path(output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    for row in reports_df.iter_rows(named=True):
        generation_id = str(row["generation_id"])
        output_path = output_dir / f"{filename_prefix}_{stems[generation_id]}.txt"
        output_path.write_text(str(row.get("report") or ""), encoding="utf-8")


def validate_reports(
    reports_df: pl.DataFrame,
    *,
    expected_ids: set[str],
    label: str,
) -> None:
    """Vérifie l'exhaustivité, les contenus vides et les erreurs batch."""
    report_ids = set(reports_df["generation_id"].cast(pl.Utf8).to_list())
    missing = expected_ids - report_ids
    extra = report_ids - expected_ids

    if missing or extra:
        raise RuntimeError(
            f"{label}: IDs manquants={len(missing)}, IDs en trop={len(extra)}"
        )

    empty = reports_df.filter(
        pl.col("report").is_null()
        | (pl.col("report").cast(pl.Utf8).str.strip_chars() == "")
    ).height

    if empty:
        raise RuntimeError(f"{label}: {empty} sortie(s) vide(s).")

    if "mistral_batch_error" in reports_df.columns:
        errors = reports_df.filter(
            pl.col("mistral_batch_error").is_not_null()
            & (
                pl.col("mistral_batch_error")
                .cast(pl.Utf8)
                .str.strip_chars()
                != ""
            )
        ).height

        if errors:
            raise RuntimeError(f"{label}: {errors} erreur(s) Mistral.")

    print(f"OK — {label}: {reports_df.height} sortie(s)")


def _object_get(value: Any, key: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(key, default)
    return getattr(value, key, default)


def _normalise_batch_status(batch_job: Any) -> str:
    status = str(_object_get(batch_job, "status", "")).upper()
    return status.rsplit(".", 1)[-1]


def _read_downloaded_file(download: Any) -> bytes:
    if hasattr(download, "read"):
        content = download.read()
    else:
        content = download

    if isinstance(content, str):
        return content.encode("utf-8")
    return bytes(content)


def _message_content_to_text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content

    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                text = item.get("text") or item.get("content")
                if text is not None:
                    parts.append(str(text))
            else:
                text = getattr(item, "text", None)
                if text is not None:
                    parts.append(str(text))
        return "".join(parts)

    return str(content)


def _error_to_text(error: Any) -> str:
    if error in (None, "", {}):
        return ""
    if isinstance(error, str):
        return error
    try:
        return json.dumps(error, ensure_ascii=False, default=str)
    except Exception:
        return str(error)


def _parse_batch_jsonl(raw_bytes: bytes) -> dict[str, dict[str, Any]]:
    parsed: dict[str, dict[str, Any]] = {}
    text = raw_bytes.decode("utf-8").strip()

    if not text:
        return parsed

    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue

        try:
            item = json.loads(line)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                f"JSONL Mistral invalide à la ligne {line_number}."
            ) from exc

        custom_id = str(item.get("custom_id", ""))
        response = item.get("response") or {}
        body = response.get("body") or item.get("body") or {}
        choices = body.get("choices") or []
        first_choice = choices[0] if choices else {}
        message = first_choice.get("message") or {}
        content = _message_content_to_text(message.get("content"))

        usage = body.get("usage") or {}
        prompt_tokens = usage.get("prompt_tokens")
        completion_tokens = usage.get("completion_tokens")
        total_tokens = usage.get("total_tokens")

        if (
            total_tokens is None
            and prompt_tokens is not None
            and completion_tokens is not None
        ):
            total_tokens = int(prompt_tokens) + int(completion_tokens)

        error = item.get("error") or response.get("error")

        parsed[custom_id] = {
            "report": content,
            "mistral_batch_error": _error_to_text(error),
            "mistral_finish_reason": first_choice.get("finish_reason"),
            "mistral_model": body.get("model"),
            "prompt_tokens": (
                int(prompt_tokens) if prompt_tokens is not None else None
            ),
            "completion_tokens": (
                int(completion_tokens) if completion_tokens is not None else None
            ),
            "total_tokens": (
                int(total_tokens) if total_tokens is not None else None
            ),
        }

    return parsed


def run_mistral_batch(
    prompt_df: pl.DataFrame,
    *,
    client: Any,
    output_dir: Path,
    model: str,
    max_tokens: int,
    poll_interval_seconds: float,
) -> pl.DataFrame:
    """Lance un batch Mistral et conserve l'usage exact de chaque requête."""
    required = {"generation_id", "system_prompt", "user_prompt", "prefix"}
    missing = required - set(prompt_df.columns)
    if missing:
        raise ValueError(
            f"Colonnes absentes pour le batch Mistral : {sorted(missing)}"
        )

    output_dir = Path(output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    batch_requests: list[dict[str, Any]] = []

    for index, row in enumerate(prompt_df.iter_rows(named=True)):
        system_prompt = str(row.get("system_prompt") or "").strip()
        user_prompt = str(row.get("user_prompt") or "").strip()
        prefix = str(row.get("prefix") or "").strip()

        if not system_prompt:
            raise ValueError(
                f"System prompt vide pour generation_id={row['generation_id']}"
            )
        if not user_prompt:
            raise ValueError(
                f"User prompt vide pour generation_id={row['generation_id']}"
            )

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        if prefix:
            messages.append(
                {
                    "role": "assistant",
                    "content": prefix,
                    "prefix": True,
                }
            )

        batch_requests.append(
            {
                "custom_id": str(index),
                "body": {
                    "messages": messages,
                    "max_tokens": int(max_tokens),
                },
            }
        )

    input_bytes = (
        "\n".join(
            json.dumps(request, ensure_ascii=False)
            for request in batch_requests
        )
        + "\n"
    ).encode("utf-8")

    input_path = output_dir / f"batch_input_{timestamp}.jsonl"
    input_path.write_bytes(input_bytes)

    print("\n" + "=" * 88)
    print("Lancement batch Mistral")
    print("=" * 88)
    print("Modèle                   :", model)
    print("Nombre de requêtes       :", prompt_df.height)
    print("Limite tokens de sortie  :", max_tokens)
    print("Fichier JSONL d'entrée   :", input_path)

    sdk_client = client._client
    input_file = sdk_client.files.upload(
        file={
            "file_name": input_path.name,
            "content": input_bytes,
        },
        purpose="batch",
    )

    batch_job = sdk_client.batch.jobs.create(
        input_files=[input_file.id],
        model=model,
        endpoint="/v1/chat/completions",
        metadata={"job_type": "stream_aphp_with_usage"},
    )

    batch_job_id = str(_object_get(batch_job, "id", ""))
    print("Batch job ID             :", batch_job_id)
    status = _normalise_batch_status(batch_job)

    while status in {"QUEUED", "RUNNING"}:
        time.sleep(float(poll_interval_seconds))
        batch_job = sdk_client.batch.jobs.get(job_id=batch_job_id)
        status = _normalise_batch_status(batch_job)
        completed = _object_get(batch_job, "completed_requests", None)
        total = _object_get(batch_job, "total_requests", None)

        if completed is not None and total is not None:
            print(
                f"\rStatut : {status} — {completed}/{total}",
                end="",
                flush=True,
            )

    print()
    print("Statut final             :", status)

    output_file_id = _object_get(batch_job, "output_file", None)
    error_file_id = _object_get(batch_job, "error_file", None)
    parsed_responses: dict[str, dict[str, Any]] = {}

    if output_file_id:
        output_bytes = _read_downloaded_file(
            sdk_client.files.download(file_id=output_file_id)
        )
        output_path = output_dir / f"batch_output_{timestamp}.jsonl"
        output_path.write_bytes(output_bytes)
        parsed_responses.update(_parse_batch_jsonl(output_bytes))
        print("Résultats JSONL          :", output_path)

    if error_file_id:
        error_bytes = _read_downloaded_file(
            sdk_client.files.download(file_id=error_file_id)
        )
        error_path = output_dir / f"batch_errors_{timestamp}.jsonl"
        error_path.write_bytes(error_bytes)
        parsed_responses.update(_parse_batch_jsonl(error_bytes))
        print("Erreurs JSONL            :", error_path)

    if status not in {"SUCCESS", "SUCCEEDED"}:
        raise RuntimeError(
            f"Le batch Mistral {batch_job_id} s'est terminé avec le statut "
            f"{status!r}. Consulter les JSONL dans {output_dir}."
        )

    result_rows: list[dict[str, Any]] = []
    for index, row in enumerate(prompt_df.iter_rows(named=True)):
        response = parsed_responses.get(str(index))
        if response is None:
            response = {
                "report": "",
                "mistral_batch_error": (
                    "Réponse absente du fichier de sortie Mistral."
                ),
                "mistral_finish_reason": None,
                "mistral_model": model,
                "prompt_tokens": None,
                "completion_tokens": None,
                "total_tokens": None,
            }

        result_rows.append(
            {
                "generation_id": str(row["generation_id"]),
                **response,
                "mistral_batch_job_id": batch_job_id,
            }
        )

    response_df = pl.DataFrame(result_rows, infer_schema_length=None)
    return prompt_df.join(response_df, on="generation_id", how="left")


# =============================================================================
# Tokens, coûts et workflow de génération
# =============================================================================


def format_token_count(value: int) -> str:
    return f"{value:,}".replace(",", " ")


def calculate_and_print_usage(
    reports_df: pl.DataFrame,
    *,
    label: str,
    input_usd_per_million: float,
    output_usd_per_million: float,
) -> dict[str, Any]:
    """Agrège les tokens et affiche une estimation du coût Batch."""
    required = {"prompt_tokens", "completion_tokens", "total_tokens"}
    missing = required - set(reports_df.columns)
    if missing:
        raise RuntimeError(
            f"{label}: colonnes d'usage absentes : {sorted(missing)}"
        )

    missing_usage = reports_df.filter(
        pl.col("prompt_tokens").is_null()
        | pl.col("completion_tokens").is_null()
        | pl.col("total_tokens").is_null()
    ).height

    if missing_usage:
        raise RuntimeError(
            f"{label}: l'API n'a pas fourni l'usage pour "
            f"{missing_usage} requête(s). Consultez le JSONL brut du batch."
        )

    totals = reports_df.select(
        pl.col("prompt_tokens").cast(pl.Int64).sum().alias("prompt_tokens"),
        pl.col("completion_tokens")
        .cast(pl.Int64)
        .sum()
        .alias("completion_tokens"),
        pl.col("total_tokens").cast(pl.Int64).sum().alias("total_tokens"),
    ).row(0, named=True)

    prompt_tokens = int(totals["prompt_tokens"] or 0)
    completion_tokens = int(totals["completion_tokens"] or 0)
    total_tokens = int(totals["total_tokens"] or 0)
    input_cost_usd = (
        prompt_tokens / 1_000_000 * float(input_usd_per_million)
    )
    output_cost_usd = (
        completion_tokens / 1_000_000 * float(output_usd_per_million)
    )
    total_cost_usd = input_cost_usd + output_cost_usd
    request_count = reports_df.height
    average_tokens = total_tokens / request_count if request_count else 0

    summary = {
        "label": label,
        "request_count": request_count,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
        "average_tokens_per_request": average_tokens,
        "input_cost_usd": input_cost_usd,
        "output_cost_usd": output_cost_usd,
        "total_cost_usd": total_cost_usd,
    }

    print("\n" + "=" * 88)
    print(label)
    print("=" * 88)
    print("Nombre de requêtes       :", format_token_count(request_count))
    print("Tokens d'entrée          :", format_token_count(prompt_tokens))
    print("Tokens de sortie         :", format_token_count(completion_tokens))
    print("Tokens totaux            :", format_token_count(total_tokens))
    print("Moyenne / requête        :", f"{average_tokens:,.0f}".replace(",", " "))
    print("Coût entrée estimé       :", f"${input_cost_usd:.6f}")
    print("Coût sortie estimé       :", f"${output_cost_usd:.6f}")
    print("COÛT TOTAL ESTIMÉ        :", f"${total_cost_usd:.6f}")

    return summary


def combine_and_print_usage(
    *summaries: dict[str, Any],
    label: str,
) -> dict[str, Any]:
    """Additionne plusieurs bilans d'usage et affiche leur total."""
    valid_summaries = [summary for summary in summaries if summary is not None]
    if not valid_summaries:
        raise ValueError("Aucun bilan d'usage à combiner.")

    combined = {
        "label": label,
        "request_count": sum(
            int(item["request_count"]) for item in valid_summaries
        ),
        "prompt_tokens": sum(
            int(item["prompt_tokens"]) for item in valid_summaries
        ),
        "completion_tokens": sum(
            int(item["completion_tokens"]) for item in valid_summaries
        ),
        "total_tokens": sum(
            int(item["total_tokens"]) for item in valid_summaries
        ),
        "input_cost_usd": sum(
            float(item["input_cost_usd"]) for item in valid_summaries
        ),
        "output_cost_usd": sum(
            float(item["output_cost_usd"]) for item in valid_summaries
        ),
        "total_cost_usd": sum(
            float(item["total_cost_usd"]) for item in valid_summaries
        ),
    }

    request_count = combined["request_count"]
    combined["average_tokens_per_request"] = (
        combined["total_tokens"] / request_count if request_count else 0
    )

    print("\n" + "#" * 88)
    print(label)
    print("#" * 88)
    print(
        "Nombre total de requêtes :",
        format_token_count(combined["request_count"]),
    )
    print(
        "Tokens d'entrée totaux   :",
        format_token_count(combined["prompt_tokens"]),
    )
    print(
        "Tokens de sortie totaux  :",
        format_token_count(combined["completion_tokens"]),
    )
    print(
        "TOKENS TOTAUX            :",
        format_token_count(combined["total_tokens"]),
    )
    print("COÛT TOTAL ESTIMÉ        :", f"${combined['total_cost_usd']:.6f}")

    return combined


def run_generation_workflow(
    *,
    generation_mode: str,
    api_key: str | None,
    run_dir: Path,
    paths: dict[str, Path],
    model: str,
    max_tokens_summary: int,
    max_tokens_cr: int,
    poll_interval_seconds: float,
    use_original_prefix_one_gen: bool,
    use_original_prefix_second_gen: bool,
    first_gen_prefix: str,
    summary_insert_header: str,
    summary_insert_footer: str,
    batch_input_usd_per_million: float,
    batch_output_usd_per_million: float,
) -> dict[str, Any]:
    """Exécute le mode one/two/both, sauvegarde les sorties et les coûts."""
    from core.clients import MistralClient

    run_dir = Path(run_dir).expanduser().resolve()
    mode = generation_mode.lower().strip()
    if mode not in {"none", "one", "two", "both"}:
        raise ValueError("GENERATION_MODE doit valoir none, one, two ou both.")

    if mode == "none":
        print(
            "Aucun appel Mistral. Modifiez les prompts puis choisissez "
            "one, two ou both."
        )
        return {"mode": mode, "usage": {}}

    if not api_key:
        raise RuntimeError(
            "Variable d'environnement MISTRAL_API_KEY absente. "
            "Définissez-la dans la cellule precedente."
        )

    scenarios, manifest = load_state(run_dir)
    expected_ids = set(
        scenarios["generation_id"].cast(pl.Utf8).to_list()
    )
    client = MistralClient(api_key=api_key)

    usage_results: dict[str, Any] = {}
    results: dict[str, Any] = {
        "mode": mode,
        "scenarios": scenarios,
        "manifest": manifest,
        "usage": usage_results,
    }
    one_usage = None
    first_usage = None
    second_usage = None

    if mode in {"one", "both"}:
        one_df = load_stage_prompts(
            scenarios,
            manifest,
            run_dir=run_dir,
            system_key="one_system_path",
            user_key="one_user_path",
            prefix_mode=(
                "original" if use_original_prefix_one_gen else "empty"
            ),
            first_gen_prefix=first_gen_prefix,
            summary_insert_header=summary_insert_header,
            summary_insert_footer=summary_insert_footer,
        )

        one_reports = run_mistral_batch(
            one_df,
            client=client,
            output_dir=paths["batches"] / "one_gen",
            model=model,
            max_tokens=max_tokens_cr,
            poll_interval_seconds=poll_interval_seconds,
        )
        validate_reports(
            one_reports,
            expected_ids=expected_ids,
            label="génération directe",
        )
        one_usage = calculate_and_print_usage(
            one_reports,
            label="GÉNÉRATION DIRECTE — CR",
            input_usd_per_million=batch_input_usd_per_million,
            output_usd_per_million=batch_output_usd_per_million,
        )
        usage_results["one_generation"] = one_usage

        one_reports.write_parquet(run_dir / "sorties/reports_1gen.parquet")
        save_individual_outputs(
            one_reports,
            manifest,
            output_dir=paths["out_one"],
            filename_prefix="CR",
        )
        results["one_reports"] = one_reports
        print("\nSorties directes :", paths["out_one"])

    if mode in {"two", "both"}:
        first_df = load_stage_prompts(
            scenarios,
            manifest,
            run_dir=run_dir,
            system_key="first_system_path",
            user_key="first_user_path",
            prefix_mode="first",
            first_gen_prefix=first_gen_prefix,
            summary_insert_header=summary_insert_header,
            summary_insert_footer=summary_insert_footer,
        )

        first_reports = run_mistral_batch(
            first_df,
            client=client,
            output_dir=paths["batches"] / "two_gen_first",
            model=model,
            max_tokens=max_tokens_summary,
            poll_interval_seconds=poll_interval_seconds,
        )
        validate_reports(
            first_reports,
            expected_ids=expected_ids,
            label="première génération / résumés",
        )
        first_usage = calculate_and_print_usage(
            first_reports,
            label="PREMIÈRE GÉNÉRATION — RÉSUMÉS",
            input_usd_per_million=batch_input_usd_per_million,
            output_usd_per_million=batch_output_usd_per_million,
        )
        usage_results["two_generation_first"] = first_usage

        first_reports.write_parquet(run_dir / "sorties/resumes_2gen.parquet")
        save_individual_outputs(
            first_reports,
            manifest,
            output_dir=paths["out_two"],
            filename_prefix="resume",
        )

        second_df = load_stage_prompts(
            scenarios,
            manifest,
            run_dir=run_dir,
            system_key="second_system_path",
            user_key="second_user_path",
            prefix_mode=(
                "original" if use_original_prefix_second_gen else "empty"
            ),
            first_gen_prefix=first_gen_prefix,
            summary_insert_header=summary_insert_header,
            summary_insert_footer=summary_insert_footer,
            summaries=reports_to_map(first_reports),
        )

        second_reports = run_mistral_batch(
            second_df,
            client=client,
            output_dir=paths["batches"] / "two_gen_second",
            model=model,
            max_tokens=max_tokens_cr,
            poll_interval_seconds=poll_interval_seconds,
        )
        validate_reports(
            second_reports,
            expected_ids=expected_ids,
            label="deuxième génération / CR",
        )
        second_usage = calculate_and_print_usage(
            second_reports,
            label="DEUXIÈME GÉNÉRATION — CR",
            input_usd_per_million=batch_input_usd_per_million,
            output_usd_per_million=batch_output_usd_per_million,
        )
        usage_results["two_generation_second"] = second_usage

        second_reports.write_parquet(run_dir / "sorties/reports_2gen.parquet")
        save_individual_outputs(
            second_reports,
            manifest,
            output_dir=paths["out_two"],
            filename_prefix="CR",
        )

        two_step_usage = combine_and_print_usage(
            first_usage,
            second_usage,
            label="TOTAL — GÉNÉRATION EN DEUX ÉTAPES",
        )
        usage_results["two_generation_total"] = two_step_usage
        results["first_reports"] = first_reports
        results["second_reports"] = second_reports
        print("\nSorties two-step :", paths["out_two"])

    if mode == "both":
        global_usage = combine_and_print_usage(
            one_usage,
            first_usage,
            second_usage,
            label="TOTAL GLOBAL — DIRECTE + DEUX ÉTAPES",
        )
        usage_results["global_total"] = global_usage

    usage_output_path = run_dir / "sorties/mistral_token_usage_and_cost.json"
    usage_payload = {
        "model": model,
        "generation_mode": mode,
        "batch_input_usd_per_million": batch_input_usd_per_million,
        "batch_output_usd_per_million": batch_output_usd_per_million,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "usage": usage_results,
    }

    with usage_output_path.open("w", encoding="utf-8") as file:
        json.dump(usage_payload, file, ensure_ascii=False, indent=2)

    results["usage_output_path"] = usage_output_path
    print("\nBilan tokens/coûts écrit :", usage_output_path)

    return results


# =============================================================================
# Visualisation
# =============================================================================


def visualize_run_outputs(
    *,
    run_dir: Path,
    paths: dict[str, Path],
    view_index: int = 0,
    scenario_max_chars: int = 12_000,
    output_max_chars: int = 20_000,
) -> None:
    """Affiche un scénario et les sorties Mistral disponibles sur disque."""
    from IPython.display import Markdown, display

    run_dir = Path(run_dir).expanduser().resolve()
    scenarios, manifest = load_state(run_dir)

    if not 0 <= int(view_index) < manifest.height:
        raise IndexError(
            f"VIEW_INDEX={view_index} hors limites pour un manifest "
            f"de {manifest.height} ligne(s)."
        )

    item = manifest.row(int(view_index), named=True)
    generation_id = str(item["generation_id"])
    file_stem = str(item["file_stem"])
    scenario_row = (
        scenarios
        .filter(pl.col("generation_id").cast(pl.Utf8) == generation_id)
        .row(0, named=True)
    )

    display(
        Markdown(
            f"# Visualisation\n"
            f"- `generation_id` : `{generation_id}`\n"
            f"- `template_name` : `{item['template_name']}`\n"
            f"- `DP` : `{scenario_row.get('icd_primary_code')}`\n"
            f"- `racine GHM` : `{scenario_row.get('drg_parent_code')}`"
        )
    )

    display(Markdown("## Scénario"))
    print(str(scenario_row.get("scenario") or "")[: int(scenario_max_chars)])

    one_cr_path = Path(paths["out_one"]) / f"CR_{file_stem}.txt"
    summary_path = Path(paths["out_two"]) / f"resume_{file_stem}.txt"
    two_cr_path = Path(paths["out_two"]) / f"CR_{file_stem}.txt"

    if one_cr_path.exists():
        display(Markdown("## CR — une génération"))
        print(one_cr_path.read_text(encoding="utf-8")[: int(output_max_chars)])

    if summary_path.exists():
        display(Markdown("## Résumé — première génération"))
        print(summary_path.read_text(encoding="utf-8")[: int(output_max_chars)])

    if two_cr_path.exists():
        display(Markdown("## CR — deuxième génération"))
        print(two_cr_path.read_text(encoding="utf-8")[: int(output_max_chars)])

    if not any(
        path.exists() for path in (one_cr_path, summary_path, two_cr_path)
    ):
        print("Aucune sortie Mistral trouvée pour ce scénario.")

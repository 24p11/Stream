"""Amorçage d'un test : graine, figement des prompts système, prompts partagés.

Spécification : docs/spec_testrun_run_stage.md (v3.4), §2 et §3.1-3.4.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import warnings
from datetime import datetime
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse
from urllib.request import url2pathname

import polars as pl

from bench.errors import BenchError

_EXCLUDED_DIRS = {"system", "batches"}


def scenario_dirs(test_dir: Path) -> list[str]:
    """Découverte disque (§2) : sous-dossiers directs hors `system/`, `batches/`
    et dossiers cachés, triés alphabétiquement. Les fichiers à la racine sont
    ignorés."""
    if not test_dir.is_dir():
        raise BenchError(f"Dossier de test introuvable : {test_dir}")
    return sorted(
        entry.name
        for entry in test_dir.iterdir()
        if entry.is_dir()
        and entry.name not in _EXCLUDED_DIRS
        and not entry.name.startswith(".")
    )


def user_from_column(column: str = "user_prompt") -> Callable[[dict], str]:
    """`user_fn` par défaut : recopie la colonne `column` de la graine."""

    def build_user(row: dict) -> str:
        if column not in row:
            raise BenchError(
                f"Colonne '{column}' absente de la graine "
                f"(colonnes disponibles : {sorted(row)})."
            )
        value = row[column]
        if value is None:
            raise BenchError(
                f"Valeur nulle dans la colonne '{column}' de la graine "
                f"(generation_id={row.get('generation_id')!r})."
            )
        return str(value)

    return build_user


def seed_user_prompts(
    test_dir: Path,
    seed: pl.DataFrame,
    *,
    filename: str = "user_generation.txt",
    user_fn: Callable[[dict], str] | None = None,
    seed_path: Path | None = None,
) -> list[str]:
    """Matérialise la graine : un dossier scénario par ligne (§3.2).

    Refuse si des dossiers scénario existent déjà — une graine par test.
    Écrit `filename` (via `user_fn`), `template.txt` (stem de `template_name`),
    `prefix.txt` si la graine a une colonne `prefix` non vide, puis
    `test.json` (§2.2).
    """
    test_dir.mkdir(parents=True, exist_ok=True)
    existing = scenario_dirs(test_dir)
    if existing:
        raise BenchError(
            f"{test_dir} contient déjà des dossiers scénario : {existing}. "
            "Une graine par test — créer un nouveau dossier de test pour repartir."
        )
    _validate_seed(seed, test_dir)

    if user_fn is None:
        user_fn = user_from_column()

    created: list[str] = []
    generation_ids: dict[str, str] = {}
    templates: dict[str, str] = {}
    for index, row in enumerate(seed.iter_rows(named=True)):
        name = f"{index:04d}"
        scenario_dir = test_dir / name
        scenario_dir.mkdir()
        (scenario_dir / filename).write_text(user_fn(row), encoding="utf-8")
        template = Path(str(row["template_name"]).strip()).stem
        (scenario_dir / "template.txt").write_text(template + "\n", encoding="utf-8")
        prefix = row.get("prefix")
        if prefix is not None and str(prefix).strip():
            (scenario_dir / "prefix.txt").write_text(str(prefix), encoding="utf-8")
        created.append(name)
        generation_ids[name] = str(row["generation_id"])
        templates[name] = template

    _write_test_json(test_dir, seed_path, generation_ids, templates)
    return created


def copy_system_prompts(
    test_dir: Path,
    position: str,
    *,
    dest: str | None = None,
) -> list[str]:
    """Fige le jeu du test par scénario (§3.3).

    Pour chaque scénario : lit `template.txt` et copie
    `system/<position>/<template>.txt` sous `<scenario>/<dest>`. Refus
    d'écraser atomique : si un dossier a déjà `dest`, rien n'est écrit.
    """
    if dest is None:
        dest = f"prompt_system_{position}.txt"
    system_dir = test_dir / "system" / position
    if not system_dir.is_dir():
        raise BenchError(
            f"Jeu de templates absent : {system_dir}. Le monter d'abord, "
            f"ex. shutil.copytree(SRC, test_dir / 'system' / {position!r})."
        )

    scenarios = scenario_dirs(test_dir)
    plan: list[tuple[Path, Path]] = []
    already_served: list[str] = []
    for name in scenarios:
        scenario_dir = test_dir / name
        template_file = scenario_dir / "template.txt"
        if not template_file.is_file():
            raise BenchError(f"Scénario '{name}' : {template_file} absent.")
        template = template_file.read_text(encoding="utf-8").strip()
        source = system_dir / f"{template}.txt"
        if not source.is_file():
            raise BenchError(
                f"Scénario '{name}' : famille '{template}' absente du jeu — "
                f"fichier attendu : {source}."
            )
        if (scenario_dir / dest).exists():
            already_served.append(name)
        plan.append((source, scenario_dir / dest))
    if already_served:
        raise BenchError(
            f"'{dest}' existe déjà dans {already_served} (sous {test_dir}) : "
            "rien n'est écrit. Choisir un autre `dest` pour une variante."
        )

    for source, target in plan:
        shutil.copyfile(source, target)
    return scenarios


def write_prompts(test_dir: Path, filename: str, text: str) -> list[str]:
    """Écrit `text` sous `filename` dans chaque dossier découvert (§3.4).

    Refus d'écraser atomique : si un dossier a déjà `filename`, rien n'est
    écrit nulle part.
    """
    scenarios = scenario_dirs(test_dir)
    already_served = [
        name for name in scenarios if (test_dir / name / filename).exists()
    ]
    if already_served:
        raise BenchError(
            f"'{filename}' existe déjà dans {already_served} (sous {test_dir}) : "
            "rien n'est écrit."
        )
    for name in scenarios:
        (test_dir / name / filename).write_text(text, encoding="utf-8")
    return scenarios


def _validate_seed(seed: pl.DataFrame, test_dir: Path) -> None:
    """Valide la graine (§3.2) : provenance et famille obligatoires."""
    for column in ("generation_id", "template_name"):
        if column not in seed.columns:
            raise BenchError(
                f"Colonne '{column}' absente de la graine pour {test_dir} "
                f"(colonnes : {seed.columns})."
            )
        if seed[column].null_count():
            raise BenchError(
                f"Valeurs nulles dans la colonne '{column}' de la graine "
                f"pour {test_dir}."
            )
    if seed["generation_id"].n_unique() < seed.height:
        duplicated = (
            seed["generation_id"].filter(seed["generation_id"].is_duplicated())
        ).unique().to_list()
        raise BenchError(
            f"`generation_id` dupliqués dans la graine pour {test_dir} : "
            f"{sorted(map(str, duplicated))}."
        )


def _write_test_json(
    test_dir: Path,
    seed_path: Path | None,
    generation_ids: dict[str, str],
    templates: dict[str, str],
) -> None:
    """Écrit `test.json` (§2.2) — provenance, jamais relu par le code."""
    version, commit = _fictomed_provenance()
    payload = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "seed_path": _seed_path_str(seed_path) if seed_path is not None else None,
        "generation_ids": generation_ids,
        "templates": templates,
        "fictomed_version": version,
        "fictomed_commit": commit,
        "notes": "",
    }
    (test_dir / "test.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _seed_path_str(seed_path: Path) -> str:
    """Chemin de graine relatif à la racine du repo si possible, en `as_posix()`."""
    repo_root = Path(__file__).resolve().parents[1]
    try:
        return seed_path.resolve().relative_to(repo_root).as_posix()
    except (ValueError, OSError):
        return seed_path.as_posix()


def _fictomed_provenance() -> tuple[str | None, str | None]:
    """Version et commit de fictomed si possible, sinon (None, None) + warning."""
    version: str | None = None
    commit: str | None = None
    try:
        from importlib import metadata

        distribution = metadata.distribution("fictomed")
        version = distribution.version
        commit = _fictomed_commit(distribution)
    except Exception:
        pass
    if version is None or commit is None:
        missing = [
            name
            for name, value in (("version", version), ("commit", commit))
            if value is None
        ]
        warnings.warn(
            f"Provenance fictomed incomplète pour test.json : {', '.join(missing)} "
            "introuvable — mis à null.",
            stacklevel=2,
        )
    return version, commit


def _fictomed_commit(distribution) -> str | None:
    """Commit via `direct_url.json` (install editable), `git rev-parse` en repli."""
    text = distribution.read_text("direct_url.json")
    if not text:
        return None
    info = json.loads(text)
    commit = info.get("vcs_info", {}).get("commit_id")
    if commit:
        return str(commit)
    url = info.get("url", "")
    if info.get("dir_info", {}).get("editable") and url.startswith("file:"):
        source_dir = url2pathname(urlparse(url).path)
        result = subprocess.run(
            ["git", "-C", source_dir, "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    return None

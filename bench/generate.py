"""Cycle de génération (§3.5) et injection de contexte (§4).

Spécification : docs/spec_testrun_run_stage.md (v3.4). Lot 2 : chemin
`dry_run` uniquement — découverte, assemblage, complétude. Le batch
Mistral (étapes 4 à 7) arrive au lot 3.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

import polars as pl

from bench.errors import BenchError
from bench.seeding import scenario_dirs

if TYPE_CHECKING:
    from core.clients import MistralClient


@dataclass(frozen=True)
class Pricing:
    """Tarifs batch Mistral, en USD par million de tokens."""

    batch_input_usd_per_million: float
    batch_output_usd_per_million: float


@dataclass(frozen=True)
class Usage:
    """Consommation et coût d'un run."""

    n_requests: int
    input_tokens: int
    output_tokens: int
    total_tokens: int
    input_cost_usd: float
    output_cost_usd: float
    total_cost_usd: float


@dataclass
class GenResult:
    """Résultat d'un appel `generate` (§3.5)."""

    out: str
    reports: pl.DataFrame
    usage: Usage
    partial: bool
    dry_run: bool


_ZERO_USAGE = Usage(0, 0, 0, 0, 0.0, 0.0, 0.0)

_REPORTS_SCHEMA: dict[str, type[pl.DataType]] = {
    "scenario": pl.String,
    "template": pl.String,
    "system_prompt": pl.String,
    "user_prompt": pl.String,
    "prefix": pl.String,
    "report": pl.String,
    "model": pl.String,
    "timestamp": pl.String,
    "input_tokens": pl.Int64,
    "output_tokens": pl.Int64,
}


def generate(
    test_dir: Path,
    *,
    system: str,
    user: str,
    out: str,
    client: MistralClient,
    model: str,
    max_tokens: int,
    pricing: Pricing,
    prefix_file: str | None = None,
    prefix_text: str = "",
    context: pl.DataFrame | None = None,
    context_header: str = "",
    context_footer: str = "",
    only: list[str] | None = None,
    dry_run: bool = False,
    poll_interval_seconds: float = 1.0,
    timeout_seconds: float = 3600.0,
) -> GenResult:
    """Un cycle de génération (§3.5).

    `system`, `user`, `out`, `prefix_file` : noms de fichiers relatifs au
    dossier de chaque scénario — aucune résolution ici, elle a eu lieu au
    figement (§3.3). `dry_run=True` s'arrête après l'assemblage : aucun
    appel API, aucune écriture — c'est le test de complétude.
    """
    if prefix_file is not None and prefix_text:
        raise BenchError(
            "`prefix_file` et `prefix_text` sont exclusifs : fournir l'un ou "
            f"l'autre (reçus : prefix_file={prefix_file!r}, "
            f"prefix_text={prefix_text!r})."
        )

    # Étape 1 — découverte + filtre.
    discovered = scenario_dirs(test_dir)
    if only is not None:
        unknown = sorted(set(only) - set(discovered))
        if unknown:
            raise BenchError(
                f"Scénarios inconnus dans `only` : {unknown}. "
                f"Dossiers de {test_dir} : {discovered}."
            )
        selected = [name for name in discovered if name in set(only)]
    else:
        selected = discovered
    partial = len(selected) < len(discovered)

    context_reports = (
        _context_reports(context, selected) if context is not None else None
    )

    # Étape 2 — assemblage, dans le dossier de CHAQUE scénario.
    timestamp = datetime.now().isoformat(timespec="seconds")
    rows: list[dict] = []
    for name in selected:
        scenario_dir = test_dir / name
        system_prompt = _read_required(scenario_dir / system, name)
        user_prompt = _read_required(scenario_dir / user, name)
        prefix = (
            _read_required(scenario_dir / prefix_file, name)
            if prefix_file is not None
            else prefix_text
        )
        if context_reports is not None:
            user_prompt = _inject_context(
                user_prompt, context_header, context_reports[name], context_footer
            )
        template_file = scenario_dir / "template.txt"
        template = (
            template_file.read_text(encoding="utf-8").strip()
            if template_file.is_file()
            else None
        )
        rows.append(
            {
                "scenario": name,
                "template": template,
                "system_prompt": system_prompt,
                "user_prompt": user_prompt,
                "prefix": prefix,
                "report": "",
                "model": model,
                "timestamp": timestamp,
                "input_tokens": None,
                "output_tokens": None,
            }
        )
    reports = pl.DataFrame(rows, schema=_REPORTS_SCHEMA)

    # Étape 3 — point d'arrêt dry_run : aucun appel API, aucune écriture.
    if dry_run:
        return GenResult(
            out=out,
            reports=reports,
            usage=_ZERO_USAGE,
            partial=partial,
            dry_run=True,
        )

    raise NotImplementedError("lot 3")


def _read_required(path: Path, scenario: str) -> str:
    """Lit un fichier obligatoire — complétude §3.5, jamais de perte silencieuse."""
    if not path.is_file():
        raise BenchError(f"Scénario '{scenario}' : fichier manquant {path}.")
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise BenchError(
            f"Scénario '{scenario}' : lecture impossible de {path} ({exc})."
        ) from exc


def _context_reports(context: pl.DataFrame, selected: list[str]) -> dict[str, str]:
    """Valide le contexte (§4) et retourne `report` par scénario retenu."""
    for column in ("scenario", "report"):
        if column not in context.columns:
            raise BenchError(
                f"Colonne '{column}' absente du contexte "
                f"(colonnes : {context.columns})."
            )
    by_scenario = dict(
        zip(context["scenario"].to_list(), context["report"].to_list())
    )
    missing = [name for name in selected if name not in by_scenario]
    if missing:
        raise BenchError(f"Scénarios absents du contexte : {missing}.")
    blank = [name for name in selected if not (by_scenario[name] or "").strip()]
    if blank:
        raise BenchError(f"`report` vide ou blanc dans le contexte pour : {blank}.")
    return {name: by_scenario[name] for name in selected}


def _inject_context(
    user_prompt: str, header: str, report: str, footer: str
) -> str:
    """Injection terminale du contexte (§4), blocs séparés par une ligne vide."""
    parts = [user_prompt.rstrip(), header.strip(), report.strip(), footer.strip()]
    return "\n\n".join(part for part in parts if part)

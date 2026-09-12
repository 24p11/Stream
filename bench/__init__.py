"""Banc d'essai de génération AP-HP.

Spécification : docs/spec_testrun_run_stage.md (v3.7). Lots 1 à 3 :
amorçage, figement des prompts, cycle `generate` complet (dry-run, puis
transport Mistral `sync` ou `batch`), reprise `load_reports`, coûts
`summarize_costs`.
"""

from bench.costs import Pricing, Usage, summarize_costs
from bench.errors import BenchError
from bench.generate import GenResult, generate, load_reports
from bench.scenarios import (
    apply_filters,
    build_filter_expr,
    generate_and_select_fictomed_scenarios,
    prepare_source_candidates,
    resolve_parquet_path,
    write_fictomed_config,
)
from bench.seeding import (
    copy_system_prompts,
    scenario_dirs,
    seed_user_prompts,
    user_from_column,
    write_prompts,
)

__all__ = [
    "BenchError",
    "GenResult",
    "Pricing",
    "Usage",
    "apply_filters",
    "build_filter_expr",
    "copy_system_prompts",
    "generate",
    "generate_and_select_fictomed_scenarios",
    "load_reports",
    "prepare_source_candidates",
    "resolve_parquet_path",
    "scenario_dirs",
    "seed_user_prompts",
    "summarize_costs",
    "user_from_column",
    "write_fictomed_config",
    "write_prompts",
]

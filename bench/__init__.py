"""Banc d'essai de génération AP-HP.

Spécification : docs/spec_testrun_run_stage.md (v3.4). Lots 1 et 2 :
amorçage, figement des prompts, `generate` en dry-run ; le batch Mistral,
`load_reports` et `summarize_costs` arrivent aux lots suivants.
"""

from bench.errors import BenchError
from bench.generate import GenResult, Pricing, Usage, generate
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
    "copy_system_prompts",
    "generate",
    "scenario_dirs",
    "seed_user_prompts",
    "user_from_column",
    "write_prompts",
]

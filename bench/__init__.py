"""Banc d'essai de génération AP-HP.

Spécification : docs/spec_testrun_run_stage.md (v3.4). Lot 1 : amorçage
et figement des prompts ; `generate`, `load_reports` et `summarize_costs`
arrivent aux lots suivants.
"""

from bench.errors import BenchError
from bench.seeding import (
    copy_system_prompts,
    scenario_dirs,
    seed_user_prompts,
    user_from_column,
    write_prompts,
)

__all__ = [
    "BenchError",
    "copy_system_prompts",
    "scenario_dirs",
    "seed_user_prompts",
    "user_from_column",
    "write_prompts",
]

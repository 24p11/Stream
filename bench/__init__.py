"""Banc d'essai de génération AP-HP.

Spécification : docs/spec_testrun_run_stage.md (v3.9). Lots 1 à 3 :
amorçage, figement des prompts, cycle `generate` complet (dry-run, puis
transport Mistral `sync` ou `batch`), reprise `load_reports`, coûts
`summarize_costs`. Chaîne amont des scénarios et typologie : `bench.scenarios` ;
orchestration du notebook (gardes, idempotence) : `bench.banc`.
"""

from bench.costs import Pricing, Usage, summarize_costs
from bench.errors import BenchError
from bench.fiches import charger_index, codes_emissibles, codes_sans_fiche
from bench.generate import GenResult, generate, load_reports
from bench.scenarios import (
    COLONNES_TYPOLOGIE,
    DPEC_TO_TPEC,
    DerivationAgean,
    DerivationSpecialite,
    ReparationRacine,
    apply_filters,
    bornes_cage,
    build_filter_expr,
    charger_mapping_type_unite,
    deriver_agean,
    deriver_specialite,
    ensure_source_ids,
    graine_ligne,
    reparer_racine,
    generate_and_select_fictomed_scenarios,
    prepare_source_candidates,
    quotas_couverture,
    resolve_parquet_path,
    tirage_stratifie,
    with_typologie,
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
    "COLONNES_TYPOLOGIE",
    "DPEC_TO_TPEC",
    "DerivationAgean",
    "DerivationSpecialite",
    "ReparationRacine",
    "GenResult",
    "Pricing",
    "Usage",
    "apply_filters",
    "build_filter_expr",
    "charger_index",
    "codes_emissibles",
    "codes_sans_fiche",
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
    "ensure_source_ids",
    "quotas_couverture",
    "tirage_stratifie",
    "with_typologie",
    "bornes_cage",
    "deriver_agean",
    "graine_ligne",
    "charger_mapping_type_unite",
    "deriver_specialite",
    "reparer_racine",
    "write_prompts",
]

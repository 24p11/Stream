"""Brest pipeline — weighted PMSI sampling (SNDS source).

This module implements the Brest-specific logic for generating synthetic
medical reports from SNDS PMSI data. It inherits from the common
:class:`~pipelines.pipeline.BasePipeline` and overrides the specific methods
as needed.
"""

from __future__ import annotations

from pathlib import Path
from typing import override

import polars as pl

from pipelines.brest.report import generate_brest_report
from pipelines.pipeline import BasePipeline
from pipelines.report import generate_reports


class BrestPipeline(BasePipeline):
    """CHU Brest pipeline — weighted PMSI sampling (SNDS source).

    Source data is extracted via ``liabilities/extract_pmsi_tables_SNDS.sas``
    and placed as CSV files in the ``data.input`` directory configured in
    ``servers.yaml``.
    """

    name = "brest"

    # -- Data loading ------------------------------------------------------

    @override
    def check_data(self) -> None:
        """Convert PMSI CSV files to Parquet if not already present."""
        return NotImplemented

    @override
    def load_data(self) -> dict[str, pl.LazyFrame]:
        """Load all PMSI Parquet files as LazyFrames."""
        return NotImplemented

    # -- Fictitious stay generation ----------------------------------------

    @override
    def get_fictive(
        self,
        data: dict[str, pl.LazyFrame],
        n_sejours: int = 1000,
        n_ccam: int = 3,
        n_das: int = 3,
        ghm5_pattern: str | None = None,
        **kwargs,
    ) -> pl.DataFrame:
        """Generate fictitious stays via weighted PMSI sampling.

        Returns
        -------
        pl.DataFrame
            Columns: generation_id, AGE, SEXE, GHM5, GHM5_CODE, DP, DP_CODE,
            CCAM (list[str]), DAS (list[str]), DMS (int).
        """
        return NotImplemented

    # -- Scenario formatting -----------------------------------------------

    @override
    def get_scenario(self, df: pl.DataFrame) -> pl.DataFrame:
        """Format fictitious stays as text scenarios for the LLM."""
        # return format_scenarios(df, scenario_fn=format_brest_scenario)
        return NotImplemented

    @override
    def get_report(
        self,
        df: pl.DataFrame,
        client: AnthropicClient | MistralClient | OllamaClient,
        model: str,
        batch_size: int = 1000,
    ) -> pl.DataFrame:
        output_dir = Path(self.config["data"]["output"])
        system_prompt = self.prompt["generate"]["system_prompt"]
        return generate_reports(
            df=df,
            client=client,
            model=model,
            generate_fn=generate_brest_report,
            batch_size=batch_size,
            output_dir=output_dir,
            system_prompt=system_prompt,
        )

"""AP-HP pipeline — ATIH PMSI sampling → clinical scenario → LLM report.

This module implements the AP-HP-specific logic for generating synthetic
medical reports from ATIH PMSI data. It inherits from the common
:class:`~pipelines.pipeline.BasePipeline` and overrides the specific methods
as needed.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, override

import polars as pl

from core.clients import AnthropicClient, MistralClient, OllamaClient
from pipelines.aphp.report import (
    generate_aphp_report,
    generate_aphp_reports_mistral_batch,
)
from pipelines.pipeline import BasePipeline
from pipelines.report import generate_reports



class APHPPipeline(BasePipeline):
    """AP-HP pipeline — report generation only.

    The input DataFrame is expected to come from fictomed and to contain:
    generation_id, scenario, user_prompt, system_prompt, prefix, prefix_len.
    """

    name = "aphp"

    @override
    def check_data(self) -> None:
        """Check only the Stream report output directory.
        AP-HP source data and referentials are checked by fictomed.
        """
        output_dir = Path(self.config["data"]["output"])
        output_dir.mkdir(parents=True, exist_ok=True)

    @override
    def load_data(self) -> dict[str, pl.LazyFrame]:
        """No data loading in Stream for AP-HP.
        Scenario generation is handled by fictomed.
        """
        return {}

    @override
    def get_fictive(
        self,
        data: dict[str, pl.LazyFrame],
        **kwargs: Any,
    ) -> pl.DataFrame:
        """Not used for AP-HP in Stream.
        fictomed.generate("aphp", ...) is called by runner.py.
        """
        raise NotImplementedError(
            "AP-HP scenario generation is handled by fictomed, not Stream."
        )

    @override
    def get_scenario(self, df: pl.DataFrame) -> pl.DataFrame:
        """Not used for AP-HP in Stream.
        The DataFrame returned by fictomed already contains scenario prompts.
        """
        return df

    @override
    def get_report(
        self,
        df: pl.DataFrame,
        client: AnthropicClient | MistralClient | OllamaClient,
        model: str,
        batch_size: int = 1000,
    ) -> pl.DataFrame:
        """Generate AP-HP reports.

        Default mode is direct and works with Ollama, Claude and Mistral.
        The optional mistral_batch mode reproduces the AP-HP historical Mistral batch method.
        """
        output_dir = Path(self.config["data"]["output"])
        output_dir.mkdir(parents=True, exist_ok=True)

        generation_cfg = self.config.get("generation", {})
        mode = generation_cfg.get("mode", "direct")

        if mode == "mistral_batch":
            if not isinstance(client, MistralClient):
                raise TypeError(
                    "generation.mode='mistral_batch' requires --client mistral."
                )

            return generate_aphp_reports_mistral_batch(
                df,
                client,
                model,
                output_dir=output_dir,
                max_tokens=generation_cfg.get("max_tokens", 128_000),
                poll_interval_seconds=generation_cfg.get("poll_interval_seconds", 1),
            )

        return generate_reports(
            df,
            client,
            model,
            batch_size=batch_size,
            output_dir=output_dir,
            generate_fn=generate_aphp_report,
            system_prompt="",
        )
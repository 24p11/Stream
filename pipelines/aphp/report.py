from datetime import datetime
from pathlib import Path
from typing import Any
import json

import polars as pl


def generate_aphp_report(
    row: dict,
    client: Any,
    model: str,
    system_prompt: str = "",
) -> dict:
    """
    Génération spécifique pour AP-HP.

    Parameters
    ----------
    row : dict
        Une ligne du DataFrame avec au moins 'scenario' et 'generation_id'.
        Doit contenir 'system_prompt' si tu veux l'overrider par ligne.
    client : Any
        Client LLM (AnthropicClient, MistralClient, etc.)
    model : str
        Nom du modèle à utiliser.
    system_prompt : str
        Prompt système spécifique au pipeline AP-HP.
        On utilise en priorité le system_prompt porté par la ligne,
        car chaque scénario peut avoir un template différent.
        Si absent, on utilise le system_prompt global passé par le pipeline.

    Returns
    -------
    dict
        La réponse du client LLM avec le texte généré.
    """
    row_system_prompt = row.get("system_prompt") or system_prompt

    messages = [
        {"role": "system", "content": row_system_prompt},
        {"role": "user", "content": row["scenario"]},
    ]
    return client.chat(model=model, messages=messages)


def generate_aphp_reports_mistral_batch(
    df: pl.DataFrame,
    client: Any,
    model: str,
    *,
    output_dir: Path,
    max_tokens: int = 128_000,
    poll_interval_seconds: int = 1,
) -> pl.DataFrame:
    """Generate AP-HP reports using the Mistral batch method."""
    batch_requests: list[dict] = []

    for idx, row in enumerate(df.iter_rows(named=True)):
        batch_requests.append(
            {
                "custom_id": str(idx),
                "generation_id": row.get("generation_id"),
                "system_prompt": row["system_prompt"],
                "user_prompt": row.get("user_prompt") or row["scenario"],
                "prefix": row.get("prefix") or "",
            }
        )

    responses = client.batch_chat(
        model=model,
        requests=batch_requests,
        max_tokens=max_tokens,
        poll_interval_seconds=poll_interval_seconds,
    )

    responses_by_idx = {
        int(response["custom_id"]): response for response in responses
    }

    timestamp = datetime.now().isoformat()
    output_rows: list[dict] = []

    for idx, row in enumerate(df.iter_rows(named=True)):
        response = responses_by_idx.get(idx, {})
        content = response.get("content", "")
        error = response.get("error")
        raw = response.get("raw")

        out = dict(row)
        out["report"] = content
        out["model"] = model
        out["timestamp"] = timestamp
        out["mistral_batch_error"] = (
            json.dumps(error, ensure_ascii=False) if error else ""
        )
        out["mistral_batch_raw"] = (
            json.dumps(raw, ensure_ascii=False) if raw else ""
        )

        output_rows.append(out)

    out_df = pl.DataFrame(output_rows)

    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / (
        f"aphp_mistral_batch_reports_{out_df.height}_"
        f"{datetime.now().strftime('%Y%m%d_%H%M%S')}.parquet"
    )

    out_df.write_parquet(output_path)

    return out_df
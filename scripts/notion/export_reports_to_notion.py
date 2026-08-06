from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import polars as pl
import requests
from dotenv import load_dotenv


NOTION_API_BASE = "https://api.notion.com/v1"
NOTION_PAGE_API_VERSION = "2022-06-28"

DEFAULT_V1_PATH = Path("reports/aphp/eval_scenarios_v1_14_20260612_165043.parquet")
DEFAULT_V2_PATH = Path("reports/aphp/eval_scenarios_v2_14_20260612_165043.parquet")


EVALUATOR_ASSIGNMENTS: dict[str, list[str]] = {
    "S1_1": ["Remi", "Basile"],
    "S1_2": ["Stephane", "Francesco"],

    "S2_1": ["Remi", "Stephane"],
    "S2_2": ["Basile", "Francesco"],

    "S3_1": ["Remi", "Francesco"],
    "S3_2": ["Basile", "Stephane"],

    "S4_1": ["Remi", "Basile"],
    "S4_2": ["Stephane", "Francesco"],

    "S5_1": ["Remi", "Stephane"],
    "S5_2": ["Basile", "Francesco"],

    "S6_1": ["Remi", "Francesco"],
    "S6_2": ["Basile", "Stephane"],

    "S7_1": ["Remi", "Basile"],
    "S7_2": ["Stephane", "Francesco"],
}

# ---------------------------------------------------------------------
# Merge / blinding helpers
# ---------------------------------------------------------------------


def anonymous_crh_id(eval_scenario: str, prompt_variant: str, salt: str) -> str:
    """Create a stable anonymised CRH id.

    The id does not expose eval_scenario or prompt_variant.
    """
    raw = f"{salt}|{eval_scenario}|{prompt_variant}".encode("utf-8")
    digest = hashlib.blake2s(raw, digest_size=5).hexdigest().upper()
    return f"CRH-{digest}"


def slugify(value: str) -> str:
    value = value.lower()
    value = re.sub(r"[^a-z0-9]+", "_", value)
    value = value.strip("_")
    return value or "unknown"


def parse_assigned_evaluators(value: Any) -> list[str]:
    if value is None:
        return []

    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]

    return [
        part.strip()
        for part in str(value).split(";")
        if part.strip()
    ]


def infer_eval_scenario_from_generation_id(value: Any) -> str:
    """Recover S1_1 from generation_id like S1_1_v1 or S1_1_v2."""
    text = "" if value is None else str(value)

    match = re.match(r"^(S\d+_\d+)_v[12]$", text)
    if match:
        return match.group(1)

    match = re.match(r"^(S\d+_\d+)", text)
    if match:
        return match.group(1)

    return ""


def infer_eval_scenario_type(eval_scenario: Any) -> str:
    """Recover S1 from S1_1."""
    text = "" if eval_scenario is None else str(eval_scenario)
    match = re.match(r"^(S\d+)_\d+$", text)
    if match:
        return match.group(1)
    return ""


def ensure_eval_scenario(df: pl.DataFrame, path: Path) -> pl.DataFrame:
    if "eval_scenario" in df.columns:
        if "eval_scenario_type" not in df.columns:
            df = df.with_columns(
                pl.col("eval_scenario")
                .map_elements(infer_eval_scenario_type, return_dtype=pl.Utf8)
                .alias("eval_scenario_type")
            )
        return df

    if "eval_pair_id" in df.columns:
        df = df.with_columns(pl.col("eval_pair_id").alias("eval_scenario"))
        if "eval_scenario_type" not in df.columns:
            df = df.with_columns(
                pl.col("eval_scenario")
                .map_elements(infer_eval_scenario_type, return_dtype=pl.Utf8)
                .alias("eval_scenario_type")
            )
        return df

    if "generation_id" in df.columns:
        df = df.with_columns(
            pl.col("generation_id")
            .map_elements(infer_eval_scenario_from_generation_id, return_dtype=pl.Utf8)
            .alias("eval_scenario")
        )

        missing = df.filter(pl.col("eval_scenario") == "")
        if missing.height > 0:
            raise ValueError(
                f"Impossible de reconstruire eval_scenario depuis generation_id dans {path}."
            )

        df = df.with_columns(
            pl.col("eval_scenario")
            .map_elements(infer_eval_scenario_type, return_dtype=pl.Utf8)
            .alias("eval_scenario_type")
        )

        return df

    raise ValueError(
        f"Le fichier {path} ne contient ni eval_scenario, ni eval_pair_id, ni generation_id."
    )


def prepare_variant_df(
    path: Path,
    *,
    prompt_variant: str,
    salt: str,
) -> pl.DataFrame:
    df = pl.read_parquet(path)
    df = ensure_eval_scenario(df, path)

    if "generation_id" in df.columns:
        df = df.rename({"generation_id": "private_generation_id"})

    df = df.with_columns(
        pl.lit(prompt_variant).alias("prompt_variant"),
        pl.col("eval_scenario").alias("eval_pair_id"),
    )

    ids = [
        anonymous_crh_id(row["eval_scenario"], prompt_variant, salt)
        for row in df.select("eval_scenario").iter_rows(named=True)
    ]

    df = df.with_columns(pl.Series("id_crh", ids))

    # Public Notion deduplication id.
    df = df.with_columns(pl.col("id_crh").alias("generation_id"))

    assigned_evaluators = []
    for row in df.select("eval_scenario").iter_rows(named=True):
        evaluators = EVALUATOR_ASSIGNMENTS.get(row["eval_scenario"], [])
        assigned_evaluators.append(";".join(evaluators))

    df = df.with_columns(pl.Series("assigned_evaluators", assigned_evaluators))

    return df


def merge_eval_reports(
    *,
    v1_path: Path,
    v2_path: Path,
    output_dir: Path,
    salt: str,
) -> tuple[Path, Path, Path, Path, pl.DataFrame]:
    df_v1 = prepare_variant_df(v1_path, prompt_variant="v1", salt=salt)
    df_v2 = prepare_variant_df(v2_path, prompt_variant="v2", salt=salt)

    merged = pl.concat([df_v1, df_v2], how="diagonal_relaxed")

    first_cols = [
        "id_crh",
        "generation_id",
        "eval_pair_id",
        "eval_scenario",
        "eval_scenario_type",
        "prompt_variant",
        "assigned_evaluators",
        "private_generation_id",
        "eval_source_row_nr",
        "eval_dp_true",
        "eval_libelle_dp_true",
        "eval_reason",
        "eval_das_count",
        "report",
        "model",
        "timestamp",
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
    ]

    first_cols = [c for c in first_cols if c in merged.columns]
    other_cols = [c for c in merged.columns if c not in first_cols]
    merged = merged.select(first_cols + other_cols)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir.mkdir(parents=True, exist_ok=True)

    merged_parquet = output_dir / f"eval_reports_merged_28_{timestamp}.parquet"
    merged_csv = output_dir / f"eval_reports_merged_28_{timestamp}.csv"
    assignment_parquet = output_dir / f"eval_assignments_56_{timestamp}.parquet"
    assignment_csv = output_dir / f"eval_assignments_56_{timestamp}.csv"

    merged.write_parquet(merged_parquet)
    merged.write_csv(merged_csv, separator=";")

    assignment_rows: list[dict[str, Any]] = []

    for row in merged.iter_rows(named=True):
        evaluators = parse_assigned_evaluators(row.get("assigned_evaluators", ""))
        for evaluator in evaluators:
            assignment_rows.append(
                {
                    "id_evaluation": f"{row['id_crh']}_{slugify(evaluator)}",
                    "id_crh": row["id_crh"],
                    "evaluator": evaluator,
                    # Private local key. Do not export as Notion visible property.
                    "eval_scenario": row.get("eval_scenario", ""),
                    "eval_pair_id": row.get("eval_pair_id", ""),
                    "eval_scenario_type": row.get("eval_scenario_type", ""),
                    "prompt_variant": row.get("prompt_variant", ""),
                    "private_generation_id": row.get("private_generation_id", ""),
                }
            )

    assignments = pl.DataFrame(assignment_rows)
    assignments.write_parquet(assignment_parquet)
    assignments.write_csv(assignment_csv, separator=";")

    return merged_parquet, merged_csv, assignment_parquet, assignment_csv, merged


# ---------------------------------------------------------------------
# Notion API helpers
# ---------------------------------------------------------------------


def notion_headers(version: str = NOTION_PAGE_API_VERSION) -> dict[str, str]:
    token = os.environ["NOTION_TOKEN"]
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Notion-Version": version,
    }


def notion_request(
    method: str,
    endpoint: str,
    *,
    version: str = NOTION_PAGE_API_VERSION,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    response = requests.request(
        method,
        f"{NOTION_API_BASE}{endpoint}",
        headers=notion_headers(version),
        json=payload,
        timeout=60,
    )

    if not response.ok:
        raise RuntimeError(
            f"Notion API error {response.status_code} on {method} {endpoint}:\n"
            f"{response.text}"
        )

    return response.json()


def get_database_schema(database_id: str) -> dict[str, dict[str, Any]]:
    result = notion_request("GET", f"/databases/{database_id}")
    return result.get("properties", {})


def get_title_property_name(schema: dict[str, dict[str, Any]], preferred: str) -> str:
    if preferred in schema and schema[preferred].get("type") == "title":
        return preferred

    for name, prop in schema.items():
        if prop.get("type") == "title":
            return name

    raise ValueError("Aucune propriété de type Title trouvée dans la base Notion.")


def get_relation_property_name(schema: dict[str, dict[str, Any]], preferred: str) -> str:
    if preferred in schema and schema[preferred].get("type") == "relation":
        return preferred

    for name, prop in schema.items():
        if prop.get("type") == "relation":
            return name

    raise ValueError("Aucune propriété de type Relation trouvée dans la base Évaluations.")


# ---------------------------------------------------------------------
# Notion property builders
# ---------------------------------------------------------------------


def title_text(text: Any, max_len: int = 200) -> dict[str, Any]:
    value = "" if text is None else str(text)
    if len(value) > max_len:
        value = value[: max_len - 3] + "..."

    return {
        "title": [
            {
                "type": "text",
                "text": {"content": value},
            }
        ]
    }


def rich_text(text: Any, max_len: int = 1900) -> dict[str, Any]:
    value = "" if text is None else str(text)
    if len(value) > max_len:
        value = value[: max_len - 3] + "..."

    return {
        "rich_text": [
            {
                "type": "text",
                "text": {"content": value},
            }
        ]
    }


def select_value(value: Any) -> dict[str, Any]:
    if value is None or str(value).strip() == "":
        return {"select": None}

    return {"select": {"name": str(value)}}


def status_value(value: Any) -> dict[str, Any]:
    if value is None or str(value).strip() == "":
        return {"status": None}

    return {"status": {"name": str(value)}}


def relation_value(page_id: str) -> dict[str, Any]:
    return {"relation": [{"id": page_id}]}


def property_value_for_schema(
    schema: dict[str, dict[str, Any]],
    prop_name: str,
    value: Any,
) -> dict[str, Any] | None:
    if prop_name not in schema:
        return None

    prop_type = schema[prop_name].get("type")

    if prop_type == "title":
        return title_text(value)

    if prop_type == "rich_text":
        return rich_text(value)

    if prop_type == "select":
        return select_value(value)

    if prop_type == "status":
        return status_value(value)

    if prop_type == "number":
        if value is None or str(value).strip() == "":
            return {"number": None}
        try:
            return {"number": float(value)}
        except (TypeError, ValueError):
            return {"number": None}

    if prop_type == "checkbox":
        return {"checkbox": bool(value)}

    return None


def add_property_if_exists(
    properties: dict[str, Any],
    schema: dict[str, dict[str, Any]],
    prop_name: str,
    value: Any,
) -> None:
    prop_value = property_value_for_schema(schema, prop_name, value)
    if prop_value is not None:
        properties[prop_name] = prop_value


def equal_filter_for_property(
    schema: dict[str, dict[str, Any]],
    prop_name: str,
    value: str,
) -> dict[str, Any] | None:
    if prop_name not in schema:
        return None

    prop_type = schema[prop_name].get("type")

    if prop_type == "title":
        return {"property": prop_name, "title": {"equals": value}}

    if prop_type == "rich_text":
        return {"property": prop_name, "rich_text": {"equals": value}}

    if prop_type == "select":
        return {"property": prop_name, "select": {"equals": value}}

    return None


# ---------------------------------------------------------------------
# Notion block builders
# ---------------------------------------------------------------------


def heading_2(text: str) -> dict[str, Any]:
    return {
        "object": "block",
        "type": "heading_2",
        "heading_2": {
            "rich_text": [
                {
                    "type": "text",
                    "text": {"content": text},
                }
            ]
        },
    }


def heading_3(text: str) -> dict[str, Any]:
    return {
        "object": "block",
        "type": "heading_3",
        "heading_3": {
            "rich_text": [
                {
                    "type": "text",
                    "text": {"content": text},
                }
            ]
        },
    }


def strip_inline_markdown(text: str) -> str:
    text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)
    return text.strip()


def rich_text_from_markdown(text: str) -> list[dict[str, Any]]:
    """Convert minimal markdown **bold** into Notion rich_text."""
    text = text or ""
    parts: list[dict[str, Any]] = []
    pos = 0

    for match in re.finditer(r"\*\*(.+?)\*\*", text):
        before = text[pos : match.start()]
        bold_text = match.group(1)

        if before:
            parts.append(
                {
                    "type": "text",
                    "text": {"content": before},
                }
            )

        if bold_text:
            parts.append(
                {
                    "type": "text",
                    "text": {"content": bold_text},
                    "annotations": {"bold": True},
                }
            )

        pos = match.end()

    after = text[pos:]
    if after:
        parts.append(
            {
                "type": "text",
                "text": {"content": after},
            }
        )

    return parts


def paragraph_markdown(text: str) -> dict[str, Any]:
    return {
        "object": "block",
        "type": "paragraph",
        "paragraph": {"rich_text": rich_text_from_markdown(text)},
    }


def bulleted_item_markdown(text: str) -> dict[str, Any]:
    return {
        "object": "block",
        "type": "bulleted_list_item",
        "bulleted_list_item": {"rich_text": rich_text_from_markdown(text)},
    }



def paragraph(text: str) -> dict[str, Any]:
    if not text:
        rich_text_content: list[dict[str, Any]] = []
    else:
        rich_text_content = [
            {
                "type": "text",
                "text": {"content": text},
            }
        ]

    return {
        "object": "block",
        "type": "paragraph",
        "paragraph": {"rich_text": rich_text_content},
    }


def bulleted_item(text: str) -> dict[str, Any]:
    return {
        "object": "block",
        "type": "bulleted_list_item",
        "bulleted_list_item": {
            "rich_text": [
                {
                    "type": "text",
                    "text": {"content": text},
                }
            ]
        },
    }


def divider() -> dict[str, Any]:
    return {"object": "block", "type": "divider", "divider": {}}


def split_text(text: str, chunk_size: int = 1800) -> list[str]:
    text = text or ""
    chunks: list[str] = []

    while text:
        chunks.append(text[:chunk_size])
        text = text[chunk_size:]

    return chunks or [""]


def append_children(block_id: str, children: list[dict[str, Any]]) -> None:
    if not children:
        return

    batch_size = 90

    for start in range(0, len(children), batch_size):
        batch = children[start : start + batch_size]
        notion_request(
            "PATCH",
            f"/blocks/{block_id}/children",
            payload={"children": batch},
        )
        time.sleep(0.2)


# ---------------------------------------------------------------------
# Data extraction helpers
# ---------------------------------------------------------------------


def normalize_code_value(value: Any) -> str:
    if value is None:
        return ""

    if isinstance(value, list):
        return " ".join(str(v) for v in value if str(v).strip())

    if hasattr(value, "to_list"):
        return " ".join(str(v) for v in value.to_list() if str(v).strip())

    return str(value)


def get_first_existing(row: dict[str, Any], names: list[str], default: str = "") -> str:
    for name in names:
        if name in row and row[name] is not None:
            value = normalize_code_value(row[name])
            if value.strip() and value.strip().lower() not in {
                "nan",
                "none",
                "null",
            }:
                return value

    return default


def clean_cr_text(text: str) -> str:
    text = text.strip()

    if text.startswith("`") and text.endswith("`"):
        text = text[1:-1].strip()

    text = text.replace("\\n", "\n")
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()


def extract_cr_from_report(report: Any) -> str:
    if report is None:
        return ""

    text = str(report).strip()

    fenced = re.search(r"```(?:json)?(.*?)```", text, flags=re.DOTALL)
    if fenced:
        text = fenced.group(1).strip()

    try:
        data = json.loads(text)
        if isinstance(data, dict) and isinstance(data.get("CR"), str):
            return clean_cr_text(data["CR"])
    except json.JSONDecodeError:
        pass

    match = re.search(
        r'"CR"\s*:\s*`(.*?)`\s*,\s*"formulations"',
        text,
        flags=re.DOTALL,
    )
    if match:
        return clean_cr_text(match.group(1))

    cr_pos = text.find('"CR"')
    if cr_pos != -1:
        colon_pos = text.find(":", cr_pos)
        if colon_pos != -1:
            after_colon = text[colon_pos + 1 :].lstrip()
            if after_colon.startswith('"'):
                try:
                    value, _ = json.JSONDecoder().raw_decode(after_colon)
                    if isinstance(value, str):
                        return clean_cr_text(value)
                except json.JSONDecodeError:
                    pass

    return clean_cr_text(text)


def get_report_text(row: dict[str, Any]) -> str:
    if "CR" in row and row["CR"] is not None:
        return str(row["CR"])

    if "report" in row and row["report"] is not None:
        return extract_cr_from_report(row["report"])

    return get_first_existing(
        row,
        [
            "clinical_report",
            "compte_rendu",
            "compte_rendu_genere",
            "generated_report",
        ],
    )


def extract_codes_from_scenario(scenario: Any) -> dict[str, str]:
    text = "" if scenario is None else str(scenario)

    dp = ""
    dp_line_match = re.search(
        r"Diagnostic principal\s*:\s*([^\n\r]*)",
        text,
        flags=re.IGNORECASE,
    )

    if dp_line_match:
        dp_line = dp_line_match.group(1)
        codes = re.findall(r"\(([A-Z][A-Z0-9+\.-]*)\)", dp_line)
        codes = [
            code.replace(".", "")
            for code in codes
            if "-" not in code
        ]

        if codes:
            dp = codes[-1]

    das = []
    das_section_match = re.search(
        r"Diagnostic associés\s*:\s*(.*?)(?:\n\s*\* Acte CCAM|\n- Nom du médecin|\n- Service|\n- Hôpital|\Z)",
        text,
        flags=re.DOTALL | re.IGNORECASE,
    )

    if das_section_match:
        das_section = das_section_match.group(1)
        das = re.findall(r"\(([A-Z][A-Z0-9+\.-]*)\)", das_section)

    das = [
        code.replace(".", "")
        for code in das
        if code.upper() not in {"NA", "NAN"}
        and "-" not in code
    ]

    return {
        "dp": dp,
        "dr": "",
        "das": " ".join(das),
    }


def get_gold_codes(row: dict[str, Any]) -> dict[str, str]:
    dp = get_first_existing(
        row,
        [
            "DP_gold",
            "dp_gold",
            "DP",
            "dp",
            "icd_primary_code",
            "diag2",
            "eval_dp_true",
        ],
    )

    dr = get_first_existing(
        row,
        [
            "DR_gold",
            "dr_gold",
            "DR",
            "dr",
            "case_management_type",
            "mdp",
        ],
    )

    das = get_first_existing(
        row,
        [
            "DAS_gold",
            "das_gold",
            "DAS",
            "das",
            "icd_secondary_code",
            "diagnostic_associes",
        ],
    )

    extracted = extract_codes_from_scenario(row.get("scenario"))

    return {
        "dp": dp or extracted["dp"],
        "dr": dr or extracted["dr"],
        "das": das or extracted["das"],
    }


# ---------------------------------------------------------------------
# Page content
# ---------------------------------------------------------------------


def cr_text_to_blocks(text: str) -> list[dict[str, Any]]:
    """Convert generated CR markdown into clean Notion blocks."""
    text = clean_cr_text(text)
    blocks: list[dict[str, Any]] = []
    paragraph_buffer: list[str] = []

    def flush_paragraph() -> None:
        nonlocal paragraph_buffer

        if not paragraph_buffer:
            return

        para = " ".join(line.strip() for line in paragraph_buffer).strip()
        paragraph_buffer = []

        if not para:
            return

        for chunk in split_text(para):
            blocks.append(paragraph_markdown(chunk))

    for raw_line in text.splitlines():
        line = raw_line.strip()

        if not line:
            flush_paragraph()
            continue

        # Markdown headings: #, ##, ###
        heading_match = re.match(r"^(#{1,3})\s+(.+)$", line)
        if heading_match:
            flush_paragraph()

            level = len(heading_match.group(1))
            title = strip_inline_markdown(heading_match.group(2))

            if level <= 2:
                blocks.append(heading_2(title))
            else:
                blocks.append(heading_3(title))

            continue

        # Standalone bold heading: **Antécédents**
        bold_heading_match = re.match(r"^\*\*(.+?)\*\*\s*:?\s*$", line)
        if bold_heading_match:
            flush_paragraph()
            blocks.append(heading_3(strip_inline_markdown(bold_heading_match.group(1))))
            continue

        # Bold heading with text on same line:
        # **Antécédents** : texte...
        bold_heading_with_rest = re.match(r"^\*\*(.+?)\*\*\s*:?\s+(.+)$", line)
        if bold_heading_with_rest:
            flush_paragraph()
            blocks.append(heading_3(strip_inline_markdown(bold_heading_with_rest.group(1))))
            rest = bold_heading_with_rest.group(2).strip()
            if rest:
                for chunk in split_text(rest):
                    blocks.append(paragraph_markdown(chunk))
            continue

        # Bullets, with inline bold support.
        if line.startswith("- "):
            flush_paragraph()
            blocks.append(bulleted_item_markdown(line[2:].strip()))
            continue

        paragraph_buffer.append(line)

    flush_paragraph()

    return blocks


def build_crh_page_properties(
    row: dict[str, Any],
    *,
    schema: dict[str, dict[str, Any]],
    title_prop: str,
) -> dict[str, Any]:
    id_crh = str(row.get("id_crh") or row.get("generation_id", ""))
    codes = get_gold_codes(row)

    properties: dict[str, Any] = {}

    properties[title_prop] = title_text(id_crh)

    add_property_if_exists(properties, schema, "id_crh", id_crh)
    add_property_if_exists(properties, schema, "generation_id", id_crh)
    add_property_if_exists(properties, schema, "pipeline", row.get("pipeline", "aphp"))
    add_property_if_exists(properties, schema, "model", row.get("model", ""))
    add_property_if_exists(properties, schema, "template_name", row.get("template_name", ""))
    add_property_if_exists(properties, schema, "coding_rule", row.get("coding_rule", ""))
    add_property_if_exists(properties, schema, "DP_gold", codes["dp"])
    add_property_if_exists(properties, schema, "DR_gold", codes["dr"])
    add_property_if_exists(properties, schema, "DAS_gold", codes["das"])
    add_property_if_exists(properties, schema, "Statut évaluation", "À évaluer")

    return properties


def build_crh_page_children(row: dict[str, Any]) -> list[dict[str, Any]]:
    report = get_report_text(row)
    scenario = str(row.get("scenario") or "")
    codes = get_gold_codes(row)

    blocks: list[dict[str, Any]] = [
        heading_2("Codes gold"),
        paragraph(f"DP : {codes['dp']}"),
        paragraph(f"DR / MDP : {codes['dr']}"),
        paragraph(f"DAS : {codes['das']}"),
    ]

    if scenario:
        blocks.extend(
            [
                divider(),
                heading_2("Scénario source"),
            ]
        )

        for chunk in split_text(scenario):
            blocks.append(paragraph(chunk))

    blocks.extend(
        [
            divider(),
            heading_2("Compte rendu généré"),
        ]
    )

    blocks.extend(cr_text_to_blocks(report))

    return blocks


# ---------------------------------------------------------------------
# Notion page creation
# ---------------------------------------------------------------------


def find_existing_page_by_value(
    database_id: str,
    value: str,
    *,
    schema: dict[str, dict[str, Any]],
    title_prop: str,
    candidate_props: list[str],
) -> str | None:
    for prop_name in candidate_props:
        filter_payload = equal_filter_for_property(schema, prop_name, value)
        if filter_payload is None:
            continue

        result = notion_request(
            "POST",
            f"/databases/{database_id}/query",
            payload={"filter": filter_payload},
        )

        results = result.get("results", [])
        if results:
            return results[0]["id"]

    filter_payload = equal_filter_for_property(schema, title_prop, value)
    if filter_payload is not None:
        result = notion_request(
            "POST",
            f"/databases/{database_id}/query",
            payload={"filter": filter_payload},
        )
        results = result.get("results", [])
        if results:
            return results[0]["id"]

    return None


def create_crh_page(
    crh_database_id: str,
    row: dict[str, Any],
    *,
    schema: dict[str, dict[str, Any]],
    title_prop: str,
) -> str:
    payload = {
        "parent": {"database_id": crh_database_id},
        "properties": build_crh_page_properties(
            row,
            schema=schema,
            title_prop=title_prop,
        ),
    }

    result = notion_request("POST", "/pages", payload=payload)
    page_id = result["id"]

    children = build_crh_page_children(row)
    append_children(page_id, children)

    return page_id


def create_eval_page(
    eval_database_id: str,
    *,
    eval_schema: dict[str, dict[str, Any]],
    crh_page_id: str,
    id_crh: str,
    evaluator: str,
    title_prop: str,
    relation_prop: str,
    evaluator_prop: str,
    skip_existing: bool,
) -> str | None:
    id_evaluation = f"{id_crh}_{slugify(evaluator)}"
    title = f"Éval - {id_crh} - {evaluator}"

    if skip_existing:
        existing = find_existing_page_by_value(
            eval_database_id,
            title,
            schema=eval_schema,
            title_prop=title_prop,
            candidate_props=[],
        )
        if existing:
            return None

    properties: dict[str, Any] = {
        title_prop: title_text(title),
        relation_prop: relation_value(crh_page_id),
    }

    add_property_if_exists(properties, eval_schema, "id_evaluation", id_evaluation)
    add_property_if_exists(properties, eval_schema, "id_crh", id_crh)

    if evaluator and evaluator_prop in eval_schema:
        add_property_if_exists(properties, eval_schema, evaluator_prop, evaluator)

    payload = {
        "parent": {"database_id": eval_database_id},
        "properties": properties,
    }

    result = notion_request("POST", "/pages", payload=payload)
    return result["id"]


# ---------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------


def main() -> None:
    load_dotenv(Path(".env"))

    parser = argparse.ArgumentParser()
    parser.add_argument("--v1", type=str, default=str(DEFAULT_V1_PATH))
    parser.add_argument("--v2", type=str, default=str(DEFAULT_V2_PATH))
    parser.add_argument("--folder", type=str, default="reports/aphp")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--skip-existing", action="store_true")
    parser.add_argument(
        "--prepare-only",
        action="store_true",
        help="Merge les fichiers et écrit les parquets/csv sans envoyer vers Notion.",
    )
    parser.add_argument(
        "--id-salt",
        type=str,
        default="eval_prompt_20260612",
        help="Sel utilisé pour générer des id_crh anonymisés stables.",
    )
    args = parser.parse_args()

    output_dir = Path(args.folder)

    (
        merged_parquet,
        merged_csv,
        assignment_parquet,
        assignment_csv,
        df,
    ) = merge_eval_reports(
        v1_path=Path(args.v1),
        v2_path=Path(args.v2),
        output_dir=output_dir,
        salt=args.id_salt,
    )

    print("Fichier merged parquet :", merged_parquet)
    print("Fichier merged csv     :", merged_csv)
    print("Fichier assignments pq :", assignment_parquet)
    print("Fichier assignments csv:", assignment_csv)

    print(
        df.select(
            [
                "id_crh",
                "eval_scenario",
                "eval_scenario_type",
                "prompt_variant",
                "assigned_evaluators",
            ]
        ).sort(["eval_scenario", "prompt_variant"])
    )

    if args.prepare_only:
        print("\nprepare-only activé : aucun envoi vers Notion.")
        return

    crh_database_id = os.environ["NOTION_CRH_DATABASE_ID"]
    eval_database_id = os.environ["NOTION_EVAL_DATABASE_ID"]

    crh_schema = get_database_schema(crh_database_id)
    eval_schema = get_database_schema(eval_database_id)

    crh_title_prop = get_title_property_name(
        crh_schema,
        os.getenv("NOTION_CRH_TITLE_PROP", "CRH"),
    )
    eval_title_prop = get_title_property_name(
        eval_schema,
        os.getenv("NOTION_EVAL_TITLE_PROP", "Nom"),
    )
    eval_relation_prop = get_relation_property_name(
        eval_schema,
        os.getenv("NOTION_EVAL_RELATION_PROP", "CRH évalué"),
    )

    evaluator_prop = os.getenv("NOTION_EVALUATOR_PROP", "Évaluateur")

    if args.limit is not None:
        df = df.head(args.limit)

    print(f"Nombre de CRH à exporter : {df.height}")
    print(f"Propriété titre CRH : {crh_title_prop}")
    print(f"Propriété titre évaluation : {eval_title_prop}")
    print(f"Propriété relation évaluation → CRH : {eval_relation_prop}")

    for idx, row in enumerate(df.iter_rows(named=True), start=1):
        id_crh = str(row.get("id_crh", ""))
        if not id_crh:
            print(f"[{idx}] Ligne ignorée : id_crh manquant")
            continue

        existing_page_id = find_existing_page_by_value(
            crh_database_id,
            id_crh,
            schema=crh_schema,
            title_prop=crh_title_prop,
            candidate_props=["id_crh", "generation_id"],
        )

        if existing_page_id and args.skip_existing:
            crh_page_id = existing_page_id
            print(f"[{idx}] Page CRH déjà présente : {id_crh}")
        elif existing_page_id:
            crh_page_id = existing_page_id
            print(f"[{idx}] Page CRH déjà existante : {id_crh}")
        else:
            crh_page_id = create_crh_page(
                crh_database_id,
                row,
                schema=crh_schema,
                title_prop=crh_title_prop,
            )
            print(f"[{idx}] Page CRH créée : {id_crh}")

        evaluators = parse_assigned_evaluators(row.get("assigned_evaluators", ""))

        if not evaluators:
            print(f"      Aucun évaluateur assigné pour {id_crh}")
            continue

        for evaluator in evaluators:
            created = create_eval_page(
                eval_database_id,
                eval_schema=eval_schema,
                crh_page_id=crh_page_id,
                id_crh=id_crh,
                evaluator=evaluator,
                title_prop=eval_title_prop,
                relation_prop=eval_relation_prop,
                evaluator_prop=evaluator_prop,
                skip_existing=args.skip_existing,
            )

            if created is None:
                print(f"      Évaluation déjà présente : {evaluator}")
            else:
                print(f"      Ligne évaluation créée : {evaluator}")

        time.sleep(0.35)


if __name__ == "__main__":
    main()
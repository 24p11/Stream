from __future__ import annotations

import argparse
import json
import os
import re
import time
from pathlib import Path
from typing import Any

import polars as pl
import requests
from dotenv import load_dotenv


NOTION_API_BASE = "https://api.notion.com/v1"
NOTION_PAGE_API_VERSION = "2022-06-28"


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
    """Build a Notion property value matching the existing property type."""
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
    """Append blocks to a Notion page/block in batches."""
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


def extract_cr_from_report(report: Any) -> str:
    """Extract the CR field from a JSON-like model response.

    Falls back to raw report text when parsing fails.
    """
    if report is None:
        return ""

    text = str(report).strip()

    fenced = re.search(r"```json(.*?)```", text, flags=re.DOTALL)
    if fenced:
        text = fenced.group(1).strip()

    try:
        data = json.loads(text)
        if isinstance(data, dict) and isinstance(data.get("CR"), str):
            return data["CR"]
    except json.JSONDecodeError:
        pass

    return str(report)


def get_report_text(row: dict[str, Any]) -> str:
    """Return only the generated CR text, not the full JSON response."""
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
    """Extract DP and DAS from the scenario text when columns are absent."""
    text = "" if scenario is None else str(scenario)

    dp_match = re.search(
        r"Diagnostic principal\s*:\s*.*?\(([A-Z][A-Z0-9+\.-]*)\)",
        text,
        flags=re.DOTALL,
    )
    dp = dp_match.group(1).replace(".", "") if dp_match else ""

    das: list[str] = []

    das_section_match = re.search(
        r"Diagnostic associés\s*:\s*(.*?)(?:\n\s*\* Acte CCAM|\n- Nom du médecin|\n- Service|\Z)",
        text,
        flags=re.DOTALL,
    )

    if das_section_match:
        das_section = das_section_match.group(1)
        das = re.findall(r"\(([A-Z][A-Z0-9+\.-]*)\)", das_section)

    das = [
        code.replace(".", "")
        for code in das
        if code.upper() not in {"NA", "NAN"}
    ]

    return {
        "dp": dp,
        "dr": "",
        "das": " ".join(das),
    }


def get_gold_codes(row: dict[str, Any]) -> dict[str, str]:
    """Return gold DP/DR/DAS from columns, or extract them from scenario."""
    dp = get_first_existing(
        row,
        [
            "DP_gold",
            "dp_gold",
            "DP",
            "dp",
            "icd_primary_code",
            "diag2",
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


def build_crh_page_properties(
    row: dict[str, Any],
    *,
    schema: dict[str, dict[str, Any]],
    title_prop: str,
) -> dict[str, Any]:
    generation_id = str(row.get("generation_id", ""))
    codes = get_gold_codes(row)

    title = f"CRH - {generation_id[:8]}"
    if codes["dp"]:
        title += f" - {codes['dp']}"

    properties: dict[str, Any] = {}

    properties[title_prop] = title_text(title)

    add_property_if_exists(properties, schema, "generation_id", generation_id)
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
        paragraph(f"DR : {codes['dr']}"),
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

    for chunk in split_text(report):
        blocks.append(paragraph(chunk))

    return blocks


# ---------------------------------------------------------------------
# Notion page creation
# ---------------------------------------------------------------------


def find_existing_crh_page(
    crh_database_id: str,
    generation_id: str,
    *,
    schema: dict[str, dict[str, Any]],
) -> str | None:
    if "generation_id" not in schema:
        return None

    payload = {
        "filter": {
            "property": "generation_id",
            "rich_text": {"equals": generation_id},
        }
    }

    result = notion_request(
        "POST",
        f"/databases/{crh_database_id}/query",
        payload=payload,
    )

    results = result.get("results", [])
    if not results:
        return None

    return results[0]["id"]


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
    generation_id: str,
    evaluator: str,
    title_prop: str,
    relation_prop: str,
    evaluator_prop: str,
) -> str:
    title = f"Éval - {generation_id[:8]}"
    if evaluator:
        title += f" - {evaluator}"

    properties: dict[str, Any] = {
        title_prop: title_text(title),
        relation_prop: relation_value(crh_page_id),
    }

    if evaluator and evaluator_prop in eval_schema:
        add_property_if_exists(properties, eval_schema, evaluator_prop, evaluator)

    payload = {
        "parent": {"database_id": eval_database_id},
        "properties": properties,
    }

    result = notion_request("POST", "/pages", payload=payload)
    return result["id"]



# ---------------------------------------------------------------------
# IO
# ---------------------------------------------------------------------


def latest_parquet(folder: str) -> Path:
    files = sorted(Path(folder).glob("*.parquet"), key=lambda p: p.stat().st_mtime)
    if not files:
        raise FileNotFoundError(f"Aucun fichier parquet trouvé dans {folder}")

    return files[-1]


def main() -> None:
    load_dotenv(Path(".env"))

    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=str, default=None)
    parser.add_argument("--folder", type=str, default="reports/aphp")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--evaluators", nargs="*", default=[])
    parser.add_argument("--skip-existing", action="store_true")
    args = parser.parse_args()

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

    input_path = Path(args.input) if args.input else latest_parquet(args.folder)
    df = pl.read_parquet(input_path)

    if args.limit is not None:
        df = df.head(args.limit)

    print(f"Fichier lu : {input_path}")
    print(f"Nombre de CRH à exporter : {df.height}")
    print(f"Propriété titre CRH : {crh_title_prop}")
    print(f"Propriété titre évaluation : {eval_title_prop}")
    print(f"Propriété relation évaluation → CRH : {eval_relation_prop}")

    for idx, row in enumerate(df.iter_rows(named=True), start=1):
        generation_id = str(row.get("generation_id", ""))

        if not generation_id:
            print(f"[{idx}] Ligne ignorée : generation_id manquant")
            continue

        existing_page_id = find_existing_crh_page(
            crh_database_id,
            generation_id,
            schema=crh_schema,
        )

        if existing_page_id and args.skip_existing:
            print(f"[{idx}] Déjà présent, ignoré : {generation_id}")
            continue

        if existing_page_id:
            crh_page_id = existing_page_id
            print(f"[{idx}] Page CRH déjà existante : {generation_id}")
        else:
            crh_page_id = create_crh_page(
                crh_database_id,
                row,
                schema=crh_schema,
                title_prop=crh_title_prop,
            )
            print(f"[{idx}] Page CRH créée : {generation_id}")

        evaluators = args.evaluators or [""]

        for evaluator in evaluators:
            create_eval_page(
                eval_database_id,
                eval_schema=eval_schema,
                crh_page_id=crh_page_id,
                generation_id=generation_id,
                evaluator=evaluator,
                title_prop=eval_title_prop,
                relation_prop=eval_relation_prop,
                evaluator_prop=evaluator_prop,
            )
            print(f"      Ligne évaluation créée : {evaluator or 'à compléter'}")

        time.sleep(0.35)


if __name__ == "__main__":
    main()
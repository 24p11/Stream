"""Coûts (§7) : Usage depuis les tokens, journal `usage.json`, synthèse,
journal CSV global des appels (`usage_log.csv`).

Spécification : docs/spec_testrun_run_stage.md (v3.7).
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import polars as pl

from bench.errors import BenchError


@dataclass(frozen=True)
class Pricing:
    """Tarifs Mistral du transport utilisé (sync ou batch), en USD par
    million de tokens. Les noms de champs datent du transport batch."""

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


# Colonnes du journal CSV global (§7), dans l'ordre d'écriture.
USAGE_CSV_COLUMNS: tuple[str, ...] = (
    "timestamp_utc",
    "test",
    "out",
    "scenario",
    "template",
    "model",
    "input_tokens",
    "output_tokens",
    "cost_usd",
    "batch_id",
    "partial",
)

_SUMMARY_SCHEMA: dict[str, type[pl.DataType]] = {
    "out": pl.String,
    "n_runs": pl.Int64,
    "committed_usd": pl.Float64,
    "current_usd": pl.Float64,
}


def compute_usage(
    *,
    n_requests: int,
    input_tokens: int,
    output_tokens: int,
    pricing: Pricing,
) -> Usage:
    """Calcule un `Usage` depuis les tokens agrégés et le tarif fourni."""
    input_cost = input_tokens / 1_000_000 * pricing.batch_input_usd_per_million
    output_cost = output_tokens / 1_000_000 * pricing.batch_output_usd_per_million
    return Usage(
        n_requests=n_requests,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=input_tokens + output_tokens,
        input_cost_usd=input_cost,
        output_cost_usd=output_cost,
        total_cost_usd=input_cost + output_cost,
    )


def append_usage(
    test_dir: Path,
    *,
    out: str,
    partial: bool,
    model: str,
    usage: Usage,
    transport: str = "batch",
    at: datetime | None = None,
) -> None:
    """Ajoute une entrée au journal `usage.json` (§7, append-only).

    L'argent dépensé reste tracé même quand les sorties sont écrasées :
    chaque run réel ajoute son entrée, étiquetée par `out`, re-runs compris.
    `transport` (sync ou batch) est noté : les tarifs diffèrent. `at` : instant
    du run (défaut : maintenant), écrit en heure locale sans fuseau — le même
    instant sert au journal CSV (`append_usage_csv`, en UTC).
    """
    stamp = at if at is not None else datetime.now()
    if stamp.tzinfo is not None:
        stamp = stamp.astimezone().replace(tzinfo=None)
    runs = _load_runs(test_dir)
    runs.append(
        {
            "out": out,
            "at": stamp.isoformat(timespec="seconds"),
            "partial": partial,
            "n_requests": usage.n_requests,
            "model": model,
            "transport": transport,
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
            "input_cost_usd": usage.input_cost_usd,
            "output_cost_usd": usage.output_cost_usd,
            "total_cost_usd": usage.total_cost_usd,
        }
    )
    (test_dir / "usage.json").write_text(
        json.dumps({"runs": runs}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def append_usage_csv(path: Path, rows: list[dict]) -> None:
    """Journal CSV global des appels (§7) : une ligne par scénario traité.

    Rôle d'observation, tous tests confondus (`usage.json` reste la source de
    `summarize_costs`). Création avec en-tête si le fichier n'existe pas,
    sinon append pur — jamais de réécriture. `cost_usd` arrondi à 6 décimales.
    Colonnes : `USAGE_CSV_COLUMNS`. Échec d'écriture → `BenchError`.
    """
    path = Path(path)
    for index, row in enumerate(rows):
        missing = [column for column in USAGE_CSV_COLUMNS if column not in row]
        if missing:
            raise BenchError(
                f"Journal CSV {path} : colonnes absentes de la ligne {index} : "
                f"{missing}."
            )
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        write_header = not path.is_file() or path.stat().st_size == 0
        with path.open("a", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(
                handle, fieldnames=USAGE_CSV_COLUMNS, extrasaction="raise"
            )
            if write_header:
                writer.writeheader()
            for row in rows:
                record = {column: row[column] for column in USAGE_CSV_COLUMNS}
                record["cost_usd"] = round(float(record["cost_usd"]), 6)
                writer.writerow(record)
    except OSError as exc:
        raise BenchError(
            f"Journal CSV inaccessible en écriture : {path} ({exc})."
        ) from exc


def summarize_costs(test_dir: Path) -> pl.DataFrame:
    """Synthèse du journal `usage.json` (§7), une ligne par `out`.

    `committed_usd` = total engagé (toutes les entrées, re-runs compris) ;
    `current_usd` = coût de l'état courant (entrées depuis le dernier run
    complet de ce `out`, celui-ci inclus — les runs partiels suivants
    raffinent l'état courant). Ligne finale `out="TOTAL"` pour le global.
    Journal absent → DataFrame vide.
    """
    runs = _load_runs(test_dir)
    by_out: dict[str, list[dict]] = {}
    for entry in runs:
        by_out.setdefault(str(entry["out"]), []).append(entry)

    rows: list[dict] = []
    for out in sorted(by_out):
        entries = by_out[out]
        last_full = 0
        for index, entry in enumerate(entries):
            if not entry.get("partial", False):
                last_full = index
        rows.append(
            {
                "out": out,
                "n_runs": len(entries),
                "committed_usd": sum(float(e["total_cost_usd"]) for e in entries),
                "current_usd": sum(
                    float(e["total_cost_usd"]) for e in entries[last_full:]
                ),
            }
        )
    if rows:
        rows.append(
            {
                "out": "TOTAL",
                "n_runs": len(runs),
                "committed_usd": sum(row["committed_usd"] for row in rows),
                "current_usd": sum(row["current_usd"] for row in rows),
            }
        )
    return pl.DataFrame(rows, schema=_SUMMARY_SCHEMA)


def _load_runs(test_dir: Path) -> list[dict]:
    """Lit les entrées du journal, liste vide si le fichier n'existe pas."""
    path = test_dir / "usage.json"
    if not path.is_file():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BenchError(f"Journal illisible : {path} ({exc}).") from exc
    runs = payload.get("runs") if isinstance(payload, dict) else None
    if not isinstance(runs, list):
        raise BenchError(
            f"Journal invalide : {path} — clé 'runs' absente ou non-liste."
        )
    return runs

"""Cycle de génération (§3.5), injection de contexte (§4), reprise (§3.6).

Spécification : docs/spec_testrun_run_stage.md (v3.4). La logique batch est
une copie adaptée de `run_mistral_batch` (work_modif_prompts/
aphp_generation_utils.py, non modifié) : JSONL sous `batches/<stem de out>/`,
`custom_id` = nom du scénario, polling borné par `timeout_seconds`.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import polars as pl

from bench.costs import Pricing, Usage, append_usage, compute_usage
from bench.errors import BenchError
from bench.seeding import scenario_dirs

if TYPE_CHECKING:
    from core.clients import MistralClient


@dataclass
class GenResult:
    """Résultat d'un appel `generate` (§3.5)."""

    out: str
    reports: pl.DataFrame
    usage: Usage
    partial: bool
    dry_run: bool


_ZERO_USAGE = Usage(0, 0, 0, 0, 0.0, 0.0, 0.0)

_REPORTS_SCHEMA: dict[str, type[pl.DataType]] = {
    "scenario": pl.String,
    "template": pl.String,
    "system_prompt": pl.String,
    "user_prompt": pl.String,
    "prefix": pl.String,
    "report": pl.String,
    "model": pl.String,
    "timestamp": pl.String,
    "input_tokens": pl.Int64,
    "output_tokens": pl.Int64,
}


def generate(
    test_dir: Path,
    *,
    system: str,
    user: str,
    out: str,
    client: MistralClient,
    model: str,
    max_tokens: int,
    pricing: Pricing,
    prefix_file: str | None = None,
    prefix_text: str = "",
    context: pl.DataFrame | None = None,
    context_header: str = "",
    context_footer: str = "",
    only: list[str] | None = None,
    dry_run: bool = False,
    poll_interval_seconds: float = 1.0,
    timeout_seconds: float = 3600.0,
) -> GenResult:
    """Un cycle de génération (§3.5).

    `system`, `user`, `out`, `prefix_file` : noms de fichiers relatifs au
    dossier de chaque scénario — aucune résolution ici, elle a eu lieu au
    figement (§3.3). `dry_run=True` s'arrête après l'assemblage : aucun
    appel API, aucune écriture — c'est le test de complétude. Un run réel
    valide les réponses (§3.5.5) avant toute écriture, puis écrit `out`
    dans chaque dossier traité et ajoute une entrée au journal (§7).
    """
    if prefix_file is not None and prefix_text:
        raise BenchError(
            "`prefix_file` et `prefix_text` sont exclusifs : fournir l'un ou "
            f"l'autre (reçus : prefix_file={prefix_file!r}, "
            f"prefix_text={prefix_text!r})."
        )

    # Étape 1 — découverte + filtre.
    discovered = scenario_dirs(test_dir)
    if only is not None:
        unknown = sorted(set(only) - set(discovered))
        if unknown:
            raise BenchError(
                f"Scénarios inconnus dans `only` : {unknown}. "
                f"Dossiers de {test_dir} : {discovered}."
            )
        selected = [name for name in discovered if name in set(only)]
    else:
        selected = discovered
    partial = len(selected) < len(discovered)

    context_reports = (
        _context_reports(context, selected) if context is not None else None
    )

    # Étape 2 — assemblage, dans le dossier de CHAQUE scénario.
    timestamp = datetime.now().isoformat(timespec="seconds")
    rows: list[dict] = []
    for name in selected:
        scenario_dir = test_dir / name
        system_prompt = _read_required(scenario_dir / system, name)
        user_prompt = _read_required(scenario_dir / user, name)
        prefix = (
            _read_required(scenario_dir / prefix_file, name)
            if prefix_file is not None
            else prefix_text
        )
        if context_reports is not None:
            user_prompt = _inject_context(
                user_prompt, context_header, context_reports[name], context_footer
            )
        template_file = scenario_dir / "template.txt"
        template = (
            template_file.read_text(encoding="utf-8").strip()
            if template_file.is_file()
            else None
        )
        rows.append(
            {
                "scenario": name,
                "template": template,
                "system_prompt": system_prompt,
                "user_prompt": user_prompt,
                "prefix": prefix,
                "report": "",
                "model": model,
                "timestamp": timestamp,
                "input_tokens": None,
                "output_tokens": None,
            }
        )

    # Étape 3 — point d'arrêt dry_run : aucun appel API, aucune écriture.
    if dry_run:
        return GenResult(
            out=out,
            reports=pl.DataFrame(rows, schema=_REPORTS_SCHEMA),
            usage=_ZERO_USAGE,
            partial=partial,
            dry_run=True,
        )

    # Étape 4 — batch Mistral, JSONL sous batches/<stem de out>/.
    batch_job_id, responses = _run_mistral_batch(
        rows,
        client=client,
        batches_dir=test_dir / "batches" / Path(out).stem,
        model=model,
        max_tokens=max_tokens,
        poll_interval_seconds=poll_interval_seconds,
        timeout_seconds=timeout_seconds,
    )

    # Étape 5 — validation (§3.5.5), AVANT toute écriture de `out` ou du journal.
    _validate_responses(selected, responses, batch_job_id=batch_job_id, out=out)

    # Étape 6 — sauvegarde : `out` par scénario traité (écrasement = geste
    # normal), puis entrée au journal usage.json (§7, append-only).
    for row in rows:
        response = responses[row["scenario"]]
        row["report"] = response["report"]
        row["input_tokens"] = int(response["prompt_tokens"])
        row["output_tokens"] = int(response["completion_tokens"])
        (test_dir / row["scenario"] / out).write_text(
            response["report"], encoding="utf-8"
        )
    usage = compute_usage(
        n_requests=len(rows),
        input_tokens=sum(row["input_tokens"] for row in rows),
        output_tokens=sum(row["output_tokens"] for row in rows),
        pricing=pricing,
    )
    append_usage(test_dir, out=out, partial=partial, model=model, usage=usage)

    # Étape 7.
    return GenResult(
        out=out,
        reports=pl.DataFrame(rows, schema=_REPORTS_SCHEMA),
        usage=usage,
        partial=partial,
        dry_run=False,
    )


def load_reports(
    test_dir: Path, filename: str, *, strict: bool = True
) -> pl.DataFrame:
    """Relit `filename` dans les dossiers découverts (§3.6) — reprise de session.

    `strict=True` → `BenchError` listant les scénarios sans fichier ;
    `strict=False` → retourne les présents (colonnes `scenario`, `report`).
    """
    rows: list[dict] = []
    missing: list[str] = []
    for name in scenario_dirs(test_dir):
        path = test_dir / name / filename
        if path.is_file():
            rows.append(
                {"scenario": name, "report": path.read_text(encoding="utf-8")}
            )
        else:
            missing.append(name)
    if strict and missing:
        raise BenchError(
            f"'{filename}' absent des scénarios {missing} (sous {test_dir}). "
            "Utiliser strict=False pour ne charger que les présents."
        )
    return pl.DataFrame(rows, schema={"scenario": pl.String, "report": pl.String})


def _read_required(path: Path, scenario: str) -> str:
    """Lit un fichier obligatoire — complétude §3.5, jamais de perte silencieuse."""
    if not path.is_file():
        raise BenchError(f"Scénario '{scenario}' : fichier manquant {path}.")
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise BenchError(
            f"Scénario '{scenario}' : lecture impossible de {path} ({exc})."
        ) from exc


def _context_reports(context: pl.DataFrame, selected: list[str]) -> dict[str, str]:
    """Valide le contexte (§4) et retourne `report` par scénario retenu."""
    for column in ("scenario", "report"):
        if column not in context.columns:
            raise BenchError(
                f"Colonne '{column}' absente du contexte "
                f"(colonnes : {context.columns})."
            )
    by_scenario = dict(
        zip(context["scenario"].to_list(), context["report"].to_list())
    )
    missing = [name for name in selected if name not in by_scenario]
    if missing:
        raise BenchError(f"Scénarios absents du contexte : {missing}.")
    blank = [name for name in selected if not (by_scenario[name] or "").strip()]
    if blank:
        raise BenchError(f"`report` vide ou blanc dans le contexte pour : {blank}.")
    return {name: by_scenario[name] for name in selected}


def _inject_context(
    user_prompt: str, header: str, report: str, footer: str
) -> str:
    """Injection terminale du contexte (§4), blocs séparés par une ligne vide."""
    parts = [user_prompt.rstrip(), header.strip(), report.strip(), footer.strip()]
    return "\n\n".join(part for part in parts if part)


# =============================================================================
# Batch Mistral — copie adaptée de run_mistral_batch (ancien monde, §8, §11)
# =============================================================================


def _run_mistral_batch(
    rows: list[dict],
    *,
    client: MistralClient,
    batches_dir: Path,
    model: str,
    max_tokens: int,
    poll_interval_seconds: float,
    timeout_seconds: float,
) -> tuple[str, dict[str, dict[str, Any]]]:
    """Lance un batch Mistral, retourne (id du batch, réponses par scénario).

    Copie adaptée de `run_mistral_batch` (work_modif_prompts/
    aphp_generation_utils.py) : `custom_id` = nom du scénario, JSONL archivés
    sous `batches_dir`, polling borné par `timeout_seconds`. L'accès
    `client._client` est conservé tel quel (§8 — la réunification dans
    `MistralClient` est un chantier séparé).
    """
    batches_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")

    batch_requests: list[dict[str, Any]] = []
    for row in rows:
        name = row["scenario"]
        system_prompt = str(row["system_prompt"] or "").strip()
        user_prompt = str(row["user_prompt"] or "").strip()
        prefix = str(row["prefix"] or "").strip()
        if not system_prompt:
            raise BenchError(f"Scénario '{name}' : prompt système vide.")
        if not user_prompt:
            raise BenchError(f"Scénario '{name}' : prompt user vide.")
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        if prefix:
            messages.append(
                {"role": "assistant", "content": prefix, "prefix": True}
            )
        batch_requests.append(
            {
                "custom_id": name,
                "body": {"messages": messages, "max_tokens": int(max_tokens)},
            }
        )

    input_bytes = (
        "\n".join(
            json.dumps(request, ensure_ascii=False) for request in batch_requests
        )
        + "\n"
    ).encode("utf-8")
    input_path = batches_dir / f"batch_input_{timestamp}.jsonl"
    input_path.write_bytes(input_bytes)

    sdk_client = client._client
    input_file = sdk_client.files.upload(
        file={"file_name": input_path.name, "content": input_bytes},
        purpose="batch",
    )
    batch_job = sdk_client.batch.jobs.create(
        input_files=[input_file.id],
        model=model,
        endpoint="/v1/chat/completions",
        metadata={"job_type": "bench_generate"},
    )
    batch_job_id = str(_object_get(batch_job, "id", ""))
    print(
        f"Batch Mistral {batch_job_id} — {len(batch_requests)} requête(s), "
        f"modèle {model}, JSONL : {input_path}"
    )

    deadline = time.monotonic() + float(timeout_seconds)
    status = _normalise_batch_status(batch_job)
    while status in {"QUEUED", "RUNNING"}:
        if time.monotonic() >= deadline:
            raise BenchError(
                f"Timeout ({timeout_seconds}s) sur le batch Mistral "
                f"{batch_job_id} (statut {status}). Le batch continue côté "
                "Mistral : récupérer ses résultats manuellement avec cet id."
            )
        time.sleep(float(poll_interval_seconds))
        batch_job = sdk_client.batch.jobs.get(job_id=batch_job_id)
        status = _normalise_batch_status(batch_job)
        completed = _object_get(batch_job, "completed_requests", None)
        total = _object_get(batch_job, "total_requests", None)
        if completed is not None and total is not None:
            print(f"\rStatut : {status} — {completed}/{total}", end="", flush=True)
    print(f"\nStatut final : {status}")

    responses: dict[str, dict[str, Any]] = {}
    output_file_id = _object_get(batch_job, "output_file", None)
    error_file_id = _object_get(batch_job, "error_file", None)
    if output_file_id:
        output_bytes = _read_downloaded_file(
            sdk_client.files.download(file_id=output_file_id)
        )
        output_path = batches_dir / f"batch_output_{timestamp}.jsonl"
        output_path.write_bytes(output_bytes)
        responses.update(_parse_batch_jsonl(output_bytes, output_path))
    if error_file_id:
        error_bytes = _read_downloaded_file(
            sdk_client.files.download(file_id=error_file_id)
        )
        error_path = batches_dir / f"batch_errors_{timestamp}.jsonl"
        error_path.write_bytes(error_bytes)
        responses.update(_parse_batch_jsonl(error_bytes, error_path))

    if status not in {"SUCCESS", "SUCCEEDED"}:
        raise BenchError(
            f"Le batch Mistral {batch_job_id} s'est terminé avec le statut "
            f"{status!r}. JSONL archivés sous {batches_dir}."
        )
    return batch_job_id, responses


def _validate_responses(
    selected: list[str],
    responses: dict[str, dict[str, Any]],
    *,
    batch_job_id: str,
    out: str,
) -> None:
    """Validation §3.5.5 — chaque écart → `BenchError` listant les scénarios,
    avant toute écriture de `out` et du journal."""
    missing = [name for name in selected if name not in responses]
    extra = sorted(set(responses) - set(selected))
    errors = [
        name
        for name in selected
        if name in responses
        and str(responses[name].get("mistral_batch_error") or "").strip()
    ]
    blank = [
        name
        for name in selected
        if name in responses
        and name not in errors
        and not str(responses[name].get("report") or "").strip()
    ]
    no_usage = [
        name
        for name in selected
        if name in responses
        and name not in errors
        and name not in blank
        and (
            responses[name].get("prompt_tokens") is None
            or responses[name].get("completion_tokens") is None
        )
    ]

    problems: list[str] = []
    if missing:
        problems.append(f"réponses absentes pour {missing}")
    if extra:
        problems.append(f"scénarios inattendus dans la sortie : {extra}")
    if errors:
        details = {
            name: str(responses[name]["mistral_batch_error"]) for name in errors
        }
        problems.append(f"erreurs batch Mistral : {details}")
    if blank:
        problems.append(f"réponses vides ou blanches pour {blank}")
    if no_usage:
        problems.append(f"usage (tokens) absent pour {no_usage}")
    if problems:
        raise BenchError(
            f"Batch Mistral {batch_job_id}, sortie '{out}' : "
            + " ; ".join(problems)
            + ". Rien n'est écrit (ni sorties, ni journal usage.json)."
        )


def _object_get(value: Any, key: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(key, default)
    return getattr(value, key, default)


def _normalise_batch_status(batch_job: Any) -> str:
    status = str(_object_get(batch_job, "status", "")).upper()
    return status.rsplit(".", 1)[-1]


def _read_downloaded_file(download: Any) -> bytes:
    if hasattr(download, "read"):
        content = download.read()
    else:
        content = download
    if isinstance(content, str):
        return content.encode("utf-8")
    return bytes(content)


def _message_content_to_text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                text = item.get("text") or item.get("content")
                if text is not None:
                    parts.append(str(text))
            else:
                text = getattr(item, "text", None)
                if text is not None:
                    parts.append(str(text))
        return "".join(parts)
    return str(content)


def _error_to_text(error: Any) -> str:
    if error in (None, "", {}):
        return ""
    if isinstance(error, str):
        return error
    try:
        return json.dumps(error, ensure_ascii=False, default=str)
    except Exception:
        return str(error)


def _parse_batch_jsonl(raw_bytes: bytes, path: Path) -> dict[str, dict[str, Any]]:
    """Parse un JSONL Mistral (sortie ou erreurs) en réponses par `custom_id`."""
    parsed: dict[str, dict[str, Any]] = {}
    text = raw_bytes.decode("utf-8").strip()
    if not text:
        return parsed

    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError as exc:
            raise BenchError(
                f"JSONL Mistral invalide : {path}, ligne {line_number}."
            ) from exc

        custom_id = str(item.get("custom_id", ""))
        response = item.get("response") or {}
        body = response.get("body") or item.get("body") or {}
        choices = body.get("choices") or []
        first_choice = choices[0] if choices else {}
        message = first_choice.get("message") or {}
        content = _message_content_to_text(message.get("content"))

        usage = body.get("usage") or {}
        prompt_tokens = usage.get("prompt_tokens")
        completion_tokens = usage.get("completion_tokens")
        error = item.get("error") or response.get("error")

        parsed[custom_id] = {
            "report": content,
            "mistral_batch_error": _error_to_text(error),
            "mistral_finish_reason": first_choice.get("finish_reason"),
            "mistral_model": body.get("model"),
            "prompt_tokens": (
                int(prompt_tokens) if prompt_tokens is not None else None
            ),
            "completion_tokens": (
                int(completion_tokens) if completion_tokens is not None else None
            ),
        }
    return parsed

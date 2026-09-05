# recover_batch.py — récupère les résultats d'un batch Mistral indépendamment
# du notebook. Le batch continue côté Mistral même kernel fermé / mac éteint :
# ce script permet de lister les jobs, d'attendre la fin d'un job et d'écrire
# ses résultats dans le test — même logique que generate() (§3.5.5-3.5.6 :
# validation, écriture de `out` par scénario, entrée usage.json).
#
# Usage :
#   python scripts/recover_batch.py --list
#       liste les jobs batch récents (statut, avancement, id).
#   python scripts/recover_batch.py work_prompts/tests/03 --job <job_id> \
#       [--out crh_generation.txt] [--wait 7200]
#       télécharge les résultats du job (en attendant sa fin si --wait),
#       archive les JSONL sous tests/NN/batches/<stem>/, écrit <out> dans
#       chaque dossier scénario et ajoute l'entrée usage.json.
#   python scripts/recover_batch.py work_prompts/tests/03 --from-file sortie.jsonl
#       même écriture depuis un JSONL de sortie déjà téléchargé (hors ligne,
#       pas de clé requise) ; usage.json est alors alimenté par les tokens
#       du JSONL.
#
# La clé vient exclusivement de MISTRAL_API_KEY (jamais en argument).
# Le tarif batch par défaut est celui du notebook (0.25/0.75 $/M tokens).

from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from bench.costs import Pricing, append_usage, compute_usage  # noqa: E402
from bench.errors import BenchError  # noqa: E402
from bench.generate import (  # noqa: E402
    _normalise_batch_status,
    _parse_batch_jsonl,
    _read_downloaded_file,
    _validate_responses,
)
from bench.seeding import scenario_dirs  # noqa: E402

TERMINAL = {"SUCCESS", "SUCCEEDED", "FAILED", "CANCELLED", "TIMEOUT_EXCEEDED", "EXPIRED"}


def sdk_client():
    api_key = os.environ.get("MISTRAL_API_KEY", "")
    if not api_key:
        raise SystemExit(
            "MISTRAL_API_KEY absente de l'environnement — requise sauf --from-file."
        )
    from mistralai import Mistral

    return Mistral(api_key=api_key, timeout_ms=120_000)


def job_summary(job) -> str:
    get = lambda name: getattr(job, name, None)  # noqa: E731
    return (
        f"{get('id')}  {_normalise_batch_status(job):<10} "
        f"{get('completed_requests')}/{get('total_requests')}  "
        f"modèle={get('model')}  créé={get('created_at')}"
    )


def list_jobs() -> int:
    sdk = sdk_client()
    jobs = sdk.batch.jobs.list()
    data = getattr(jobs, "data", None) or []
    if not data:
        print("Aucun job batch.")
        return 0
    for job in data:
        print(job_summary(job))
    return 0


def fetch_job_jsonl(sdk, job_id: str, wait_seconds: float, poll: float = 30.0):
    """Attend (si demandé) la fin du job, retourne (job, bytes sortie, bytes erreurs)."""
    job = sdk.batch.jobs.get(job_id=job_id)
    status = _normalise_batch_status(job)
    deadline = time.monotonic() + wait_seconds
    while status not in TERMINAL:
        if time.monotonic() >= deadline:
            raise SystemExit(
                f"Job {job_id} toujours {status} "
                f"({getattr(job, 'completed_requests', '?')}/"
                f"{getattr(job, 'total_requests', '?')}). "
                "Relancer plus tard (ou --wait N pour patienter)."
            )
        print(f"\r{job_summary(job)} — nouvelle vérification dans {poll:.0f}s",
              end="", flush=True)
        time.sleep(poll)
        job = sdk.batch.jobs.get(job_id=job_id)
        status = _normalise_batch_status(job)
    print(f"\nStatut final : {status}")

    def download(attr: str) -> bytes:
        file_id = getattr(job, attr, None)
        if not file_id:
            return b""
        return _read_downloaded_file(sdk.files.download(file_id=file_id))

    return job, download("output_file"), download("error_file")


def write_results(
    test_dir: Path,
    out: str,
    responses: dict,
    *,
    model: str,
    pricing: Pricing,
) -> int:
    """Validation puis écriture — même séquence que generate() étapes 5-6."""
    discovered = scenario_dirs(test_dir)
    selected = sorted(responses)
    orphans = [name for name in selected if name not in discovered]
    if orphans:
        raise BenchError(
            f"custom_id sans dossier scénario dans {test_dir} : {orphans} — "
            "mauvais test ciblé ?"
        )
    _validate_responses(selected, responses, run_id="(récupération)", out=out)

    input_tokens = 0
    output_tokens = 0
    for name in selected:
        response = responses[name]
        (test_dir / name / out).write_text(response["report"], encoding="utf-8")
        input_tokens += int(response["prompt_tokens"])
        output_tokens += int(response["completion_tokens"])

    usage = compute_usage(
        n_requests=len(selected),
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        pricing=pricing,
    )
    append_usage(
        test_dir,
        out=out,
        partial=len(selected) < len(discovered),
        model=model,
        usage=usage,
    )
    print(f"Écrit : {len(selected)} × {out} sous {test_dir}")
    print(f"Usage : {usage}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Récupération des résultats d'un batch Mistral (hors notebook)"
    )
    ap.add_argument("test_dir", nargs="?", type=Path,
                    help="dossier du test (ex. work_prompts/tests/03)")
    ap.add_argument("--list", action="store_true", help="lister les jobs batch")
    ap.add_argument("--job", help="id du job batch à récupérer")
    ap.add_argument("--from-file", type=Path,
                    help="JSONL de sortie déjà téléchargé (mode hors ligne)")
    ap.add_argument("--out", default="crh_generation.txt",
                    help="nom du fichier de sortie par dossier scénario")
    ap.add_argument("--wait", type=float, default=0.0,
                    help="secondes d'attente maximale si le job court encore")
    ap.add_argument("--price-input", type=float, default=0.25,
                    help="tarif batch $/M tokens d'entrée")
    ap.add_argument("--price-output", type=float, default=0.75,
                    help="tarif batch $/M tokens de sortie")
    args = ap.parse_args()

    if args.list:
        return list_jobs()
    if args.test_dir is None or not args.test_dir.is_dir():
        ap.error("test_dir requis (ou --list). Ex. work_prompts/tests/03")
    if bool(args.job) == bool(args.from_file):
        ap.error("fournir soit --job <id>, soit --from-file <jsonl>")

    pricing = Pricing(
        batch_input_usd_per_million=args.price_input,
        batch_output_usd_per_million=args.price_output,
    )
    batches_dir = args.test_dir / "batches" / Path(args.out).stem
    batches_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")

    if args.from_file:
        raw = args.from_file.read_bytes()
        responses = _parse_batch_jsonl(raw, args.from_file)
        model = next(
            (r["mistral_model"] for r in responses.values() if r.get("mistral_model")),
            "(récupéré)",
        )
    else:
        sdk = sdk_client()
        job, output_bytes, error_bytes = fetch_job_jsonl(sdk, args.job, args.wait)
        status = _normalise_batch_status(job)
        responses = {}
        if output_bytes:
            output_path = batches_dir / f"batch_output_recovered_{timestamp}.jsonl"
            output_path.write_bytes(output_bytes)
            print("Archivé :", output_path)
            responses.update(_parse_batch_jsonl(output_bytes, output_path))
        if error_bytes:
            error_path = batches_dir / f"batch_errors_recovered_{timestamp}.jsonl"
            error_path.write_bytes(error_bytes)
            print("Archivé :", error_path)
            responses.update(_parse_batch_jsonl(error_bytes, error_path))
        if status not in {"SUCCESS", "SUCCEEDED"}:
            raise BenchError(
                f"Job {args.job} terminé en {status!r} — JSONL archivés sous "
                f"{batches_dir}, rien n'est écrit dans les dossiers scénario."
            )
        model = str(getattr(job, "model", None) or "(récupéré)")

    if not responses:
        raise BenchError("Aucune réponse dans le JSONL — rien à écrire.")
    return write_results(args.test_dir, args.out, responses,
                         model=model, pricing=pricing)


if __name__ == "__main__":
    raise SystemExit(main())

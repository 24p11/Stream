"""Tests du lot 3 de `bench` — §10 de la spec : cas 8 (écriture partielle),
10 (validation batch), 11 (journal usage.json et synthèse des coûts) et 13
(`load_reports`).

Client Mistral MOCKÉ, aucun réseau : le faux SDK reproduit la surface
utilisée par les deux transports — batch (`files.upload/download`,
`batch.jobs.create/get`, JSONL de sortie avec `choices`/`usage`, fichier
d'erreurs séparé donnant la colonne d'erreur `mistral_batch_error`) et sync
(`chat.complete`, un objet réponse par appel, exceptions transitoires ou
persistantes).
"""

import json
from pathlib import Path
from types import SimpleNamespace

import csv
import importlib
import re

import polars as pl
import pytest

from bench import (
    BenchError,
    Pricing,
    generate,
    load_reports,
    seed_user_prompts,
    summarize_costs,
)
from bench.costs import USAGE_CSV_COLUMNS

# Le module, pas la fonction `bench.generate` ré-exportée par le paquet.
generate_module = importlib.import_module("bench.generate")

PRICING = Pricing(1.0, 3.0)
PROMPT_TOKENS = 100
COMPLETION_TOKENS = 50
# Coût d'une requête avec PRICING : (100 * 1.0 + 50 * 3.0) / 1e6.
COST_PER_REQUEST = 0.00025

SYSTEM_BY_FAMILY = {
    "medical_outpatient": "SYSTÈME MÉDECINE",
    "surgery_inpatient": "SYSTÈME CHIRURGIE",
}
# Transport sync : `chat.complete` ne reçoit pas de custom_id — le faux SDK
# retrouve le scénario par le début de son user prompt (voir make_test_dir).
SCENARIO_BY_USER_PREFIX = {
    "USER MÉDECINE": "0000",
    "USER CHIRURGIE": "0001",
}


def make_test_dir(tmp_path: Path) -> Path:
    """Un test amorcé et figé (lot 1) : deux familles, prompts système posés."""
    test_dir = tmp_path / "tests" / "01"
    seed = pl.DataFrame(
        {
            "generation_id": ["id-0", "id-1"],
            "template_name": ["medical_outpatient.txt", "surgery_inpatient.txt"],
            "user_prompt": ["USER MÉDECINE", "USER CHIRURGIE"],
            "prefix": ["PRÉFIXE MÉDECINE", "PRÉFIXE CHIRURGIE"],
        }
    )
    seed_user_prompts(test_dir, seed)
    for name in ("0000", "0001"):
        family = (test_dir / name / "template.txt").read_text(encoding="utf-8").strip()
        (test_dir / name / "prompt_system_first.txt").write_text(
            SYSTEM_BY_FAMILY[family], encoding="utf-8"
        )
    return test_dir


class FakeMistralSdk:
    """Surface SDK utilisée par le batch, formes de retour du SDK réel.

    `reports` : contenu par custom_id (défaut : "RAPPORT <custom_id>") ;
    `errors` : message d'erreur batch par custom_id (le scénario passe alors
    dans le fichier d'erreurs, comme Mistral) ; `drop` : custom_id absents de
    la sortie ; `stuck=True` : le job reste RUNNING (test du timeout).

    Transport sync : `sync_failures` : nombre d'exceptions transitoires avant
    succès, par scénario ; `sync_errors` : exception à chaque appel (erreur
    persistante). `sync_calls` journalise les appels reçus, `sync_requests`
    garde les arguments du dernier appel par scénario.
    """

    def __init__(
        self,
        *,
        reports=None,
        errors=None,
        drop=(),
        stuck=False,
        sync_failures=None,
        sync_errors=None,
    ):
        self.reports = reports or {}
        self.errors = errors or {}
        self.drop = set(drop)
        self.stuck = stuck
        self.custom_ids: list[str] = []
        self.files = SimpleNamespace(upload=self._upload, download=self._download)
        self.batch = SimpleNamespace(
            jobs=SimpleNamespace(create=self._create, get=self._get)
        )
        self.sync_failures = dict(sync_failures or {})
        self.sync_errors = dict(sync_errors or {})
        self.sync_calls: list[str] = []
        self.sync_requests: dict[str, dict] = {}
        self.chat = SimpleNamespace(complete=self._complete)

    def _complete(self, *, model, messages, max_tokens, timeout_ms=None, **kwargs):
        assert messages[0]["role"] == "system"
        user_prompt = messages[1]["content"]
        custom_id = next(
            name
            for prefix, name in SCENARIO_BY_USER_PREFIX.items()
            if user_prompt.startswith(prefix)
        )
        self.sync_calls.append(custom_id)
        self.sync_requests[custom_id] = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "timeout_ms": timeout_ms,
        }
        if custom_id in self.sync_errors:
            raise RuntimeError(self.sync_errors[custom_id])
        if self.sync_failures.get(custom_id, 0) > 0:
            self.sync_failures[custom_id] -= 1
            raise ConnectionError("réseau indisponible")
        if custom_id in self.drop:
            return SimpleNamespace(
                id=f"cmpl-{custom_id}", model=model, choices=[], usage=None
            )
        return SimpleNamespace(
            id=f"cmpl-{custom_id}",
            model="mistral-large-latest",
            choices=[
                SimpleNamespace(
                    index=0,
                    finish_reason="stop",
                    message=SimpleNamespace(
                        role="assistant",
                        content=self.reports.get(custom_id, f"RAPPORT {custom_id}"),
                    ),
                )
            ],
            usage=SimpleNamespace(
                prompt_tokens=PROMPT_TOKENS,
                completion_tokens=COMPLETION_TOKENS,
                total_tokens=PROMPT_TOKENS + COMPLETION_TOKENS,
            ),
        )

    def _upload(self, *, file, purpose):
        assert purpose == "batch"
        content = file["content"].decode("utf-8")
        self.custom_ids = [
            json.loads(line)["custom_id"]
            for line in content.splitlines()
            if line.strip()
        ]
        return SimpleNamespace(id="input-file-1")

    def _job(self, status):
        return SimpleNamespace(
            id="batch-42",
            status=status,
            output_file="output-file-1",
            error_file="error-file-1" if self.errors else None,
            completed_requests=len(self.custom_ids),
            total_requests=len(self.custom_ids),
        )

    def _create(self, *, input_files, model, endpoint, metadata=None):
        assert input_files == ["input-file-1"]
        assert endpoint == "/v1/chat/completions"
        return self._job("QUEUED")

    def _get(self, *, job_id):
        assert job_id == "batch-42"
        return self._job("RUNNING" if self.stuck else "SUCCESS")

    def _download(self, *, file_id):
        if file_id == "output-file-1":
            lines = [
                json.dumps(
                    {
                        "custom_id": name,
                        "response": {
                            "body": {
                                "choices": [
                                    {
                                        "message": {
                                            "content": self.reports.get(
                                                name, f"RAPPORT {name}"
                                            )
                                        },
                                        "finish_reason": "stop",
                                    }
                                ],
                                "usage": {
                                    "prompt_tokens": PROMPT_TOKENS,
                                    "completion_tokens": COMPLETION_TOKENS,
                                    "total_tokens": PROMPT_TOKENS
                                    + COMPLETION_TOKENS,
                                },
                                "model": "mistral-large-latest",
                            }
                        },
                    },
                    ensure_ascii=False,
                )
                for name in self.custom_ids
                if name not in self.drop and name not in self.errors
            ]
        elif file_id == "error-file-1":
            lines = [
                json.dumps(
                    {"custom_id": name, "error": {"message": message}},
                    ensure_ascii=False,
                )
                for name, message in self.errors.items()
                if name in self.custom_ids
            ]
        else:
            raise AssertionError(f"file_id inconnu : {file_id}")
        return ("\n".join(lines) + "\n").encode("utf-8")


class FakeMistralClient:
    """Doublure de core.clients.MistralClient : seul `_client` est utilisé (§8)."""

    def __init__(self, sdk: FakeMistralSdk):
        self._client = sdk


def run_real(test_dir: Path, sdk: FakeMistralSdk, **kwargs):
    """`generate` en run réel (dry_run=False) sur le faux SDK."""
    kwargs.setdefault("system", "prompt_system_first.txt")
    kwargs.setdefault("user", "user_generation.txt")
    kwargs.setdefault("out", "crh_generation.txt")
    kwargs.setdefault("client", FakeMistralClient(sdk))
    kwargs.setdefault("model", "mistral-large-latest")
    kwargs.setdefault("max_tokens", 1000)
    kwargs.setdefault("pricing", PRICING)
    kwargs.setdefault("poll_interval_seconds", 0.0)
    kwargs.setdefault("transport", "batch")
    return generate(test_dir, dry_run=False, **kwargs)


def run_sync(test_dir: Path, sdk: FakeMistralSdk, **kwargs):
    """`generate` en run réel, transport sync, deux appels en parallèle."""
    kwargs.setdefault("transport", "sync")
    kwargs.setdefault("max_workers", 2)
    return run_real(test_dir, sdk, **kwargs)


def read_out(test_dir: Path, scenario: str, out: str = "crh_generation.txt") -> str:
    return (test_dir / scenario / out).read_text(encoding="utf-8")


def journal_runs(test_dir: Path) -> list[dict]:
    return json.loads((test_dir / "usage.json").read_text(encoding="utf-8"))["runs"]


def usage_log_path(test_dir: Path) -> Path:
    """Chemin par défaut du journal CSV : <racine des tests>.parent/usage_log.csv."""
    return test_dir.parent.parent / "usage_log.csv"


def csv_rows(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


class TestRunComplet:
    """Chemin nominal : sorties écrites, usage calculé, JSONL archivés."""

    def test_out_reports_et_usage(self, tmp_path: Path):
        test_dir = make_test_dir(tmp_path)
        result = run_real(test_dir, FakeMistralSdk())

        assert result.dry_run is False
        assert result.partial is False
        assert read_out(test_dir, "0000") == "RAPPORT 0000"
        assert read_out(test_dir, "0001") == "RAPPORT 0001"

        row = result.reports.filter(pl.col("scenario") == "0000").row(0, named=True)
        assert row["report"] == "RAPPORT 0000"
        assert row["input_tokens"] == PROMPT_TOKENS
        assert row["output_tokens"] == COMPLETION_TOKENS

        assert result.usage.n_requests == 2
        assert result.usage.input_tokens == 2 * PROMPT_TOKENS
        assert result.usage.output_tokens == 2 * COMPLETION_TOKENS
        assert result.usage.total_tokens == 2 * (PROMPT_TOKENS + COMPLETION_TOKENS)
        assert result.usage.total_cost_usd == pytest.approx(2 * COST_PER_REQUEST)

    def test_jsonl_sous_batches_stem_de_out_et_custom_id_scenario(
        self, tmp_path: Path
    ):
        test_dir = make_test_dir(tmp_path)
        sdk = FakeMistralSdk()
        run_real(test_dir, sdk, out="crh_v2.txt")

        assert sdk.custom_ids == ["0000", "0001"]
        batch_dir = test_dir / "batches" / "crh_v2"
        inputs = list(batch_dir.glob("batch_input_*.jsonl"))
        outputs = list(batch_dir.glob("batch_output_*.jsonl"))
        assert len(inputs) == 1 and len(outputs) == 1
        first_request = json.loads(
            inputs[0].read_text(encoding="utf-8").splitlines()[0]
        )
        assert first_request["custom_id"] == "0000"
        assert first_request["body"]["messages"][0]["role"] == "system"

    def test_timeout_mentionne_l_id_du_batch(self, tmp_path: Path):
        test_dir = make_test_dir(tmp_path)
        with pytest.raises(BenchError, match="batch-42"):
            run_real(test_dir, FakeMistralSdk(stuck=True), timeout_seconds=0.0)
        assert not (test_dir / "0000" / "crh_generation.txt").exists()
        assert not (test_dir / "usage.json").exists()


class TestEcriturePartielle:
    """§10.8 — run partiel : `out` écrit seulement dans les dossiers traités."""

    def test_only_n_ecrit_que_les_dossiers_traites(self, tmp_path: Path):
        test_dir = make_test_dir(tmp_path)
        sdk = FakeMistralSdk()
        result = run_real(test_dir, sdk, only=["0001"])

        assert result.partial is True
        assert result.reports["scenario"].to_list() == ["0001"]
        assert sdk.custom_ids == ["0001"]
        assert not (test_dir / "0000" / "crh_generation.txt").exists()
        assert read_out(test_dir, "0001") == "RAPPORT 0001"

        (entry,) = journal_runs(test_dir)
        assert entry["partial"] is True
        assert entry["n_requests"] == 1

    def test_run_partiel_laisse_les_autres_sorties_intactes(self, tmp_path: Path):
        test_dir = make_test_dir(tmp_path)
        run_real(test_dir, FakeMistralSdk())
        result = run_real(
            test_dir,
            FakeMistralSdk(reports={"0001": "RAPPORT 0001 v2"}),
            only=["0001"],
        )

        assert result.partial is True
        assert read_out(test_dir, "0000") == "RAPPORT 0000"
        assert read_out(test_dir, "0001") == "RAPPORT 0001 v2"


class TestValidationBatch:
    """§10.10 — réponse manquante, vide ou en erreur → BenchError, AUCUNE
    écriture (ni `out`, ni journal)."""

    @pytest.mark.parametrize(
        "sdk",
        [
            pytest.param(FakeMistralSdk(drop={"0001"}), id="reponse-manquante"),
            pytest.param(
                FakeMistralSdk(reports={"0001": "   \n"}), id="reponse-vide"
            ),
            pytest.param(
                FakeMistralSdk(errors={"0001": "Rate limit exceeded"}),
                id="erreur-batch",
            ),
        ],
    )
    def test_ecart_leve_bencherror_sans_aucune_ecriture(
        self, tmp_path: Path, sdk: FakeMistralSdk
    ):
        test_dir = make_test_dir(tmp_path)
        with pytest.raises(BenchError, match="0001"):
            run_real(test_dir, sdk)
        assert not (test_dir / "0000" / "crh_generation.txt").exists()
        assert not (test_dir / "0001" / "crh_generation.txt").exists()
        assert not (test_dir / "usage.json").exists()

    def test_message_actionnable(self, tmp_path: Path):
        """L'erreur nomme le batch, la sortie et le détail de l'erreur Mistral."""
        test_dir = make_test_dir(tmp_path)
        sdk = FakeMistralSdk(errors={"0001": "Rate limit exceeded"})
        with pytest.raises(BenchError) as excinfo:
            run_real(test_dir, sdk)
        message = str(excinfo.value)
        assert "batch-42" in message
        assert "crh_generation.txt" in message
        assert "Rate limit exceeded" in message


class TestJournalUsage:
    """§10.11 — journal append-only, synthèse total engagé / état courant."""

    def test_journal_append_only(self, tmp_path: Path):
        test_dir = make_test_dir(tmp_path)
        run_real(test_dir, FakeMistralSdk())
        first_entry = journal_runs(test_dir)[0]

        run_real(test_dir, FakeMistralSdk())

        runs = journal_runs(test_dir)
        assert len(runs) == 2
        assert runs[0] == first_entry
        assert all(entry["out"] == "crh_generation.txt" for entry in runs)
        assert runs[1]["total_cost_usd"] == pytest.approx(2 * COST_PER_REQUEST)
        assert runs[1]["model"] == "mistral-large-latest"

    def test_summarize_costs_total_engage_vs_etat_courant(self, tmp_path: Path):
        test_dir = make_test_dir(tmp_path)
        # Deux runs complets puis un re-run partiel du même `out` : l'état
        # courant = dernier run complet + le partiel qui le raffine.
        run_real(test_dir, FakeMistralSdk())
        run_real(test_dir, FakeMistralSdk())
        run_real(test_dir, FakeMistralSdk(), only=["0001"])
        # Un autre `out`, un seul run complet.
        run_real(test_dir, FakeMistralSdk(), out="crh_v2.txt")

        summary = summarize_costs(test_dir)

        crh = summary.filter(pl.col("out") == "crh_generation.txt").row(
            0, named=True
        )
        assert crh["n_runs"] == 3
        assert crh["committed_usd"] == pytest.approx(5 * COST_PER_REQUEST)
        assert crh["current_usd"] == pytest.approx(3 * COST_PER_REQUEST)

        v2 = summary.filter(pl.col("out") == "crh_v2.txt").row(0, named=True)
        assert v2["n_runs"] == 1
        assert v2["committed_usd"] == pytest.approx(2 * COST_PER_REQUEST)
        assert v2["current_usd"] == pytest.approx(2 * COST_PER_REQUEST)

        total = summary.filter(pl.col("out") == "TOTAL").row(0, named=True)
        assert total["n_runs"] == 4
        assert total["committed_usd"] == pytest.approx(7 * COST_PER_REQUEST)
        assert total["current_usd"] == pytest.approx(5 * COST_PER_REQUEST)

    def test_summarize_costs_sans_journal(self, tmp_path: Path):
        test_dir = make_test_dir(tmp_path)
        summary = summarize_costs(test_dir)
        assert summary.height == 0
        assert summary.columns == ["out", "n_runs", "committed_usd", "current_usd"]


class TestLoadReports:
    """§10.13 — reconstruction fidèle ; fichier manquant → BenchError en
    strict, ignoré en non-strict."""

    def test_reconstruction_fidele(self, tmp_path: Path):
        test_dir = make_test_dir(tmp_path)
        run_real(test_dir, FakeMistralSdk())

        reports = load_reports(test_dir, "crh_generation.txt")

        assert reports["scenario"].to_list() == ["0000", "0001"]
        assert reports["report"].to_list() == ["RAPPORT 0000", "RAPPORT 0001"]

    def test_strict_fichier_manquant(self, tmp_path: Path):
        test_dir = make_test_dir(tmp_path)
        run_real(test_dir, FakeMistralSdk())
        (test_dir / "0000" / "crh_generation.txt").unlink()

        with pytest.raises(BenchError) as excinfo:
            load_reports(test_dir, "crh_generation.txt")
        message = str(excinfo.value)
        assert "0000" in message
        assert "crh_generation.txt" in message

    def test_non_strict_retourne_les_presents(self, tmp_path: Path):
        test_dir = make_test_dir(tmp_path)
        run_real(test_dir, FakeMistralSdk())
        (test_dir / "0000" / "crh_generation.txt").unlink()

        reports = load_reports(test_dir, "crh_generation.txt", strict=False)

        assert reports["scenario"].to_list() == ["0001"]
        assert reports["report"].to_list() == ["RAPPORT 0001"]


class TestRunSync:
    """Transport sync (§3.5.4) : un `chat.complete` par scénario, même
    validation, mêmes écritures, JSONL archivés sous `batches/`."""

    @pytest.fixture(autouse=True)
    def _sans_pause_entre_tentatives(self, monkeypatch):
        monkeypatch.setattr(generate_module, "_SYNC_BACKOFF_SECONDS", (0.0,))

    def test_out_reports_usage_et_journal(self, tmp_path: Path):
        test_dir = make_test_dir(tmp_path)
        sdk = FakeMistralSdk()
        result = run_sync(
            test_dir, sdk, max_tokens=1000, timeout_seconds=600, prefix_file="prefix.txt"
        )

        assert sorted(sdk.sync_calls) == ["0000", "0001"]
        assert result.dry_run is False and result.partial is False
        assert read_out(test_dir, "0000") == "RAPPORT 0000"
        assert read_out(test_dir, "0001") == "RAPPORT 0001"
        assert result.usage.n_requests == 2
        assert result.usage.total_cost_usd == pytest.approx(2 * COST_PER_REQUEST)

        # La requête envoyée : système, user, prefix assistant, max_tokens,
        # délai par requête dérivé de timeout_seconds.
        sent = sdk.sync_requests["0000"]
        assert sent["max_tokens"] == 1000
        assert sent["timeout_ms"] == 600_000
        assert sent["messages"][2] == {
            "role": "assistant",
            "content": "PRÉFIXE MÉDECINE",
            "prefix": True,
        }

        entry = journal_runs(test_dir)[0]
        assert entry["transport"] == "sync"
        assert entry["n_requests"] == 2

    def test_jsonl_sync_sous_batches_stem_de_out(self, tmp_path: Path):
        test_dir = make_test_dir(tmp_path)
        run_sync(test_dir, FakeMistralSdk(), out="crh_v2.txt")

        batch_dir = test_dir / "batches" / "crh_v2"
        inputs = list(batch_dir.glob("sync_input_*.jsonl"))
        outputs = list(batch_dir.glob("sync_output_*.jsonl"))
        assert len(inputs) == 1 and len(outputs) == 1
        assert not list(batch_dir.glob("batch_*.jsonl"))

        requests = [
            json.loads(line)
            for line in inputs[0].read_text(encoding="utf-8").splitlines()
        ]
        assert [r["custom_id"] for r in requests] == ["0000", "0001"]
        assert requests[0]["body"]["messages"][0]["role"] == "system"

        # Sortie au format batch : même parseur, ordre des scénarios conservé.
        lines = [
            json.loads(line)
            for line in outputs[0].read_text(encoding="utf-8").splitlines()
        ]
        assert [line["custom_id"] for line in lines] == ["0000", "0001"]
        body = lines[0]["response"]["body"]
        assert body["choices"][0]["message"]["content"] == "RAPPORT 0000"
        assert body["choices"][0]["finish_reason"] == "stop"
        assert body["usage"]["prompt_tokens"] == PROMPT_TOKENS
        assert body["model"] == "mistral-large-latest"

    def test_reprise_apres_echec_transitoire(self, tmp_path: Path):
        test_dir = make_test_dir(tmp_path)
        sdk = FakeMistralSdk(sync_failures={"0000": 2})
        run_sync(test_dir, sdk)

        assert sdk.sync_calls.count("0000") == 3
        assert sdk.sync_calls.count("0001") == 1
        assert read_out(test_dir, "0000") == "RAPPORT 0000"

    @pytest.mark.parametrize(
        "sdk",
        [
            pytest.param(
                FakeMistralSdk(sync_errors={"0001": "Rate limit exceeded"}),
                id="erreur-persistante",
            ),
            pytest.param(FakeMistralSdk(drop={"0001"}), id="reponse-sans-choix"),
            pytest.param(
                FakeMistralSdk(reports={"0001": "   \n"}), id="reponse-vide"
            ),
        ],
    )
    def test_ecart_leve_bencherror_sans_aucune_ecriture(
        self, tmp_path: Path, sdk: FakeMistralSdk
    ):
        test_dir = make_test_dir(tmp_path)
        with pytest.raises(BenchError, match="0001"):
            run_sync(test_dir, sdk)
        assert not (test_dir / "0000" / "crh_generation.txt").exists()
        assert not (test_dir / "0001" / "crh_generation.txt").exists()
        assert not (test_dir / "usage.json").exists()

    def test_message_actionnable_nomme_le_run(self, tmp_path: Path):
        test_dir = make_test_dir(tmp_path)
        sdk = FakeMistralSdk(sync_errors={"0001": "Rate limit exceeded"})
        with pytest.raises(BenchError) as excinfo:
            run_sync(test_dir, sdk)
        message = str(excinfo.value)
        assert "sync_" in message
        assert "crh_generation.txt" in message
        assert "Rate limit exceeded" in message
        # Trois tentatives avant d'abandonner, l'autre scénario servi une fois.
        assert sdk.sync_calls.count("0001") == 3
        assert sdk.sync_calls.count("0000") == 1

    def test_only_n_ecrit_que_les_dossiers_traites(self, tmp_path: Path):
        test_dir = make_test_dir(tmp_path)
        sdk = FakeMistralSdk()
        result = run_sync(test_dir, sdk, only=["0001"])

        assert result.partial is True
        assert sdk.sync_calls == ["0001"]
        assert not (test_dir / "0000" / "crh_generation.txt").exists()
        assert read_out(test_dir, "0001") == "RAPPORT 0001"

    def test_transport_inconnu_refuse_avant_tout_appel(self, tmp_path: Path):
        test_dir = make_test_dir(tmp_path)
        sdk = FakeMistralSdk()
        with pytest.raises(BenchError, match="fax"):
            run_real(test_dir, sdk, transport="fax")
        assert sdk.sync_calls == [] and sdk.custom_ids == []
        assert not (test_dir / "batches").exists()


class TestJournalCsv:
    """§7 — journal CSV global des appels : une ligne par scénario traité,
    append pur, écrit au même moment que l'entrée usage.json."""

    def test_creation_avec_en_tete_puis_append_sans_doublon(self, tmp_path: Path):
        test_dir = make_test_dir(tmp_path)
        log = usage_log_path(test_dir)
        assert not log.exists()

        run_real(test_dir, FakeMistralSdk())
        lines = log.read_text(encoding="utf-8").splitlines()
        assert lines[0] == ",".join(USAGE_CSV_COLUMNS)
        assert len(lines) == 1 + 2

        run_real(test_dir, FakeMistralSdk())
        lines = log.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 1 + 4
        assert sum(1 for line in lines if line.startswith("timestamp_utc")) == 1

    def test_une_ligne_par_scenario_avec_les_colonnes(self, tmp_path: Path):
        test_dir = make_test_dir(tmp_path)
        run_real(test_dir, FakeMistralSdk())
        rows = csv_rows(usage_log_path(test_dir))

        assert [r["scenario"] for r in rows] == ["0000", "0001"]
        assert [r["template"] for r in rows] == [
            "medical_outpatient",
            "surgery_inpatient",
        ]
        first = rows[0]
        assert list(first) == list(USAGE_CSV_COLUMNS)
        assert first["test"] == "01"
        assert first["out"] == "crh_generation.txt"
        assert first["model"] == "mistral-large-latest"
        assert first["input_tokens"] == str(PROMPT_TOKENS)
        assert first["output_tokens"] == str(COMPLETION_TOKENS)
        assert float(first["cost_usd"]) == pytest.approx(COST_PER_REQUEST)
        assert first["batch_id"] == "batch-42"
        assert first["partial"] == "False"
        assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", first["timestamp_utc"])

    def test_somme_des_lignes_egale_l_entree_usage_json(self, tmp_path: Path):
        test_dir = make_test_dir(tmp_path)
        run_real(test_dir, FakeMistralSdk())
        run_real(test_dir, FakeMistralSdk(), only=["0001"])
        run_real(test_dir, FakeMistralSdk(), out="crh_v2.txt")

        rows = csv_rows(usage_log_path(test_dir))
        entries = journal_runs(test_dir)
        assert len(rows) == sum(entry["n_requests"] for entry in entries)

        cursor = 0
        for entry in entries:
            chunk = rows[cursor : cursor + entry["n_requests"]]
            cursor += entry["n_requests"]
            assert {r["out"] for r in chunk} == {entry["out"]}
            assert sum(int(r["input_tokens"]) for r in chunk) == entry["input_tokens"]
            assert sum(int(r["output_tokens"]) for r in chunk) == entry["output_tokens"]
            assert sum(float(r["cost_usd"]) for r in chunk) == pytest.approx(
                entry["total_cost_usd"], abs=1e-6
            )

    def test_run_partiel_marque_ses_lignes(self, tmp_path: Path):
        test_dir = make_test_dir(tmp_path)
        run_real(test_dir, FakeMistralSdk())
        run_real(test_dir, FakeMistralSdk(), only=["0001"])
        rows = csv_rows(usage_log_path(test_dir))

        assert [r["partial"] for r in rows] == ["False", "False", "True"]
        assert rows[-1]["scenario"] == "0001"

    def test_usage_csv_none_aucun_fichier(self, tmp_path: Path):
        test_dir = make_test_dir(tmp_path)
        run_real(test_dir, FakeMistralSdk(), usage_csv=None)
        assert not usage_log_path(test_dir).exists()
        assert (test_dir / "usage.json").exists()

    def test_usage_csv_chemin_explicite(self, tmp_path: Path):
        test_dir = make_test_dir(tmp_path)
        target = tmp_path / "ailleurs" / "appels.csv"
        run_real(test_dir, FakeMistralSdk(), usage_csv=target)
        assert not usage_log_path(test_dir).exists()
        assert len(csv_rows(target)) == 2

    def test_validation_echouee_n_ecrit_rien_dans_le_csv(self, tmp_path: Path):
        test_dir = make_test_dir(tmp_path)
        with pytest.raises(BenchError):
            run_real(test_dir, FakeMistralSdk(errors={"0001": "Rate limit exceeded"}))
        assert not usage_log_path(test_dir).exists()

    def test_transport_sync_note_l_id_du_run(self, tmp_path: Path, monkeypatch):
        monkeypatch.setattr(generate_module, "_SYNC_BACKOFF_SECONDS", (0.0,))
        test_dir = make_test_dir(tmp_path)
        run_sync(test_dir, FakeMistralSdk())
        rows = csv_rows(usage_log_path(test_dir))
        assert all(r["batch_id"].startswith("sync_") for r in rows)

"""Tests du lot 3 de `bench` — §10 de la spec : cas 8 (écriture partielle),
10 (validation batch), 11 (journal usage.json et synthèse des coûts) et 13
(`load_reports`).

Client Mistral MOCKÉ, aucun réseau : le faux SDK reproduit la surface
utilisée par le batch (`files.upload/download`, `batch.jobs.create/get`) et
la forme des retours actuels de `run_mistral_batch` — JSONL de sortie avec
`choices`/`usage`, fichier d'erreurs séparé donnant la colonne d'erreur
batch (`mistral_batch_error`).
"""

import json
from pathlib import Path
from types import SimpleNamespace

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

PRICING = Pricing(1.0, 3.0)
PROMPT_TOKENS = 100
COMPLETION_TOKENS = 50
# Coût d'une requête avec PRICING : (100 * 1.0 + 50 * 3.0) / 1e6.
COST_PER_REQUEST = 0.00025

SYSTEM_BY_FAMILY = {
    "medical_outpatient": "SYSTÈME MÉDECINE",
    "surgery_inpatient": "SYSTÈME CHIRURGIE",
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
    """

    def __init__(self, *, reports=None, errors=None, drop=(), stuck=False):
        self.reports = reports or {}
        self.errors = errors or {}
        self.drop = set(drop)
        self.stuck = stuck
        self.custom_ids: list[str] = []
        self.files = SimpleNamespace(upload=self._upload, download=self._download)
        self.batch = SimpleNamespace(
            jobs=SimpleNamespace(create=self._create, get=self._get)
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
    return generate(test_dir, dry_run=False, **kwargs)


def read_out(test_dir: Path, scenario: str, out: str = "crh_generation.txt") -> str:
    return (test_dir / scenario / out).read_text(encoding="utf-8")


def journal_runs(test_dir: Path) -> list[dict]:
    return json.loads((test_dir / "usage.json").read_text(encoding="utf-8"))["runs"]


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

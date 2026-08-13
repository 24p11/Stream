"""Tests du lot 2 de `bench` — §10 de la spec : cas 5, 6, 7, 9 et le
filtrage du cas 8 (l'écriture partielle de `out` attendra le lot 3).

Tous sans réseau (`dry_run=True`, client jamais appelé), sur `tmp_path`.
"""

import json
from pathlib import Path

import polars as pl
import pytest

from bench import BenchError, Pricing, generate, seed_user_prompts

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


def run_dry(test_dir: Path, **kwargs):
    """`generate` en dry-run avec les arguments obligatoires par défaut."""
    kwargs.setdefault("system", "prompt_system_first.txt")
    kwargs.setdefault("user", "user_generation.txt")
    kwargs.setdefault("out", "crh_generation.txt")
    kwargs.setdefault("client", None)
    kwargs.setdefault("model", "mistral-large-latest")
    kwargs.setdefault("max_tokens", 1000)
    kwargs.setdefault("pricing", Pricing(1.0, 3.0))
    kwargs.setdefault("dry_run", True)
    return generate(test_dir, **kwargs)


def report_row(result, scenario: str) -> dict:
    return result.reports.filter(pl.col("scenario") == scenario).row(0, named=True)


class TestDryRun:
    """§10.5 — prompts assemblés corrects, aucune écriture."""

    def test_prompts_lus_dans_le_dossier_de_chaque_scenario(self, tmp_path: Path):
        test_dir = make_test_dir(tmp_path)
        result = run_dry(test_dir)

        assert result.dry_run is True
        assert result.partial is False
        assert result.out == "crh_generation.txt"
        assert result.reports["scenario"].to_list() == ["0000", "0001"]

        row_0 = report_row(result, "0000")
        row_1 = report_row(result, "0001")
        assert row_0["system_prompt"] == "SYSTÈME MÉDECINE"
        assert row_1["system_prompt"] == "SYSTÈME CHIRURGIE"
        assert row_0["user_prompt"] == "USER MÉDECINE"
        assert row_1["user_prompt"] == "USER CHIRURGIE"
        assert row_0["template"] == "medical_outpatient"
        assert row_1["template"] == "surgery_inpatient"
        assert row_0["report"] == ""
        assert row_0["model"] == "mistral-large-latest"

        assert result.usage.n_requests == 0
        assert result.usage.total_tokens == 0
        assert result.usage.total_cost_usd == 0.0

    def test_template_null_si_absent(self, tmp_path: Path):
        test_dir = make_test_dir(tmp_path)
        (test_dir / "0000" / "template.txt").unlink()
        result = run_dry(test_dir)
        assert report_row(result, "0000")["template"] is None
        assert report_row(result, "0001")["template"] == "surgery_inpatient"

    def test_prefix_file(self, tmp_path: Path):
        test_dir = make_test_dir(tmp_path)
        result = run_dry(test_dir, prefix_file="prefix.txt")
        assert report_row(result, "0000")["prefix"] == "PRÉFIXE MÉDECINE"
        assert report_row(result, "0001")["prefix"] == "PRÉFIXE CHIRURGIE"

    def test_prefix_text(self, tmp_path: Path):
        test_dir = make_test_dir(tmp_path)
        result = run_dry(test_dir, prefix_text="PRÉFIXE PARTAGÉ")
        assert report_row(result, "0000")["prefix"] == "PRÉFIXE PARTAGÉ"
        assert report_row(result, "0001")["prefix"] == "PRÉFIXE PARTAGÉ"

    def test_sans_prefix(self, tmp_path: Path):
        test_dir = make_test_dir(tmp_path)
        result = run_dry(test_dir)
        assert report_row(result, "0000")["prefix"] == ""

    def test_aucune_ecriture(self, tmp_path: Path):
        """Dry-run : ni `out`, ni `usage.json`, ni modification de `test.json`."""
        test_dir = make_test_dir(tmp_path)
        test_json_before = (test_dir / "test.json").read_text(encoding="utf-8")

        run_dry(test_dir)

        assert not (test_dir / "0000" / "crh_generation.txt").exists()
        assert not (test_dir / "0001" / "crh_generation.txt").exists()
        assert not (test_dir / "usage.json").exists()
        assert not (test_dir / "batches").exists()
        assert (test_dir / "test.json").read_text(encoding="utf-8") == test_json_before


class TestCompletude:
    """§10.6 — fichier manquant → BenchError nommant fichier et scénario."""

    def test_system_manquant(self, tmp_path: Path):
        test_dir = make_test_dir(tmp_path)
        (test_dir / "0001" / "prompt_system_first.txt").unlink()
        with pytest.raises(BenchError) as excinfo:
            run_dry(test_dir)
        message = str(excinfo.value)
        assert "0001" in message
        assert str(test_dir / "0001" / "prompt_system_first.txt") in message

    def test_user_manquant(self, tmp_path: Path):
        test_dir = make_test_dir(tmp_path)
        (test_dir / "0000" / "user_generation.txt").unlink()
        with pytest.raises(BenchError) as excinfo:
            run_dry(test_dir)
        message = str(excinfo.value)
        assert "0000" in message
        assert str(test_dir / "0000" / "user_generation.txt") in message


class TestContexte:
    """§10.7 — validation du contexte, et format exact d'injection (§4)."""

    def test_format_injection(self, tmp_path: Path):
        """user.rstrip(), puis header/report/footer strip(), séparés par une
        ligne vide — injection toujours terminale."""
        test_dir = make_test_dir(tmp_path)
        (test_dir / "0000" / "user_generation.txt").write_text(
            "USER MÉDECINE\n\n", encoding="utf-8"
        )
        context = pl.DataFrame(
            {
                "scenario": ["0000", "0001"],
                "report": ["  RÉSUMÉ MÉDECINE \n", "RÉSUMÉ CHIRURGIE"],
            }
        )
        result = run_dry(
            test_dir,
            context=context,
            context_header=" Résumé du dossier : \n",
            context_footer="Fin du résumé.\n",
        )
        assert report_row(result, "0000")["user_prompt"] == (
            "USER MÉDECINE"
            "\n\nRésumé du dossier :"
            "\n\nRÉSUMÉ MÉDECINE"
            "\n\nFin du résumé."
        )

    def test_format_sans_header_ni_footer(self, tmp_path: Path):
        """Header/footer vides (défaut) : pas de lignes vides surnuméraires."""
        test_dir = make_test_dir(tmp_path)
        context = pl.DataFrame(
            {"scenario": ["0000", "0001"], "report": ["RÉSUMÉ A", "RÉSUMÉ B"]}
        )
        result = run_dry(test_dir, context=context)
        assert report_row(result, "0000")["user_prompt"] == (
            "USER MÉDECINE\n\nRÉSUMÉ A"
        )

    def test_scenario_absent_du_contexte(self, tmp_path: Path):
        test_dir = make_test_dir(tmp_path)
        context = pl.DataFrame({"scenario": ["0000"], "report": ["RÉSUMÉ A"]})
        with pytest.raises(BenchError, match="0001"):
            run_dry(test_dir, context=context)

    def test_report_vide_ou_blanc(self, tmp_path: Path):
        test_dir = make_test_dir(tmp_path)
        context = pl.DataFrame(
            {"scenario": ["0000", "0001"], "report": ["RÉSUMÉ A", "   \n"]}
        )
        with pytest.raises(BenchError, match="0001"):
            run_dry(test_dir, context=context)


class TestOnly:
    """§10.8 (partie filtrage) — `only` correct, nom inconnu → BenchError."""

    def test_filtrage(self, tmp_path: Path):
        test_dir = make_test_dir(tmp_path)
        result = run_dry(test_dir, only=["0001"])
        assert result.reports["scenario"].to_list() == ["0001"]
        assert result.partial is True

    def test_only_complet_pas_partiel(self, tmp_path: Path):
        test_dir = make_test_dir(tmp_path)
        result = run_dry(test_dir, only=["0000", "0001"])
        assert result.partial is False

    def test_nom_inconnu(self, tmp_path: Path):
        """L'erreur liste les dossiers existants."""
        test_dir = make_test_dir(tmp_path)
        with pytest.raises(BenchError) as excinfo:
            run_dry(test_dir, only=["9999"])
        message = str(excinfo.value)
        assert "9999" in message
        assert "0000" in message
        assert "0001" in message


class TestPrefix:
    """§10.9 — erreurs de prefix."""

    def test_prefix_file_absent_du_dossier(self, tmp_path: Path):
        test_dir = make_test_dir(tmp_path)
        (test_dir / "0001" / "prefix.txt").unlink()
        with pytest.raises(BenchError) as excinfo:
            run_dry(test_dir, prefix_file="prefix.txt")
        message = str(excinfo.value)
        assert "0001" in message
        assert str(test_dir / "0001" / "prefix.txt") in message

    def test_prefix_file_et_prefix_text_exclusifs(self, tmp_path: Path):
        test_dir = make_test_dir(tmp_path)
        with pytest.raises(BenchError, match="exclusifs"):
            run_dry(test_dir, prefix_file="prefix.txt", prefix_text="PRÉFIXE")

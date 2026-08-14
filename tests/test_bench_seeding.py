"""Tests du lot 1 de `bench` — §10 de la spec : cas 1, 2, 3, 4, 12 et 14.

Tous sans réseau, sur `tmp_path`.
"""

import json
import shutil
from pathlib import Path

import polars as pl
import pytest

from bench import (
    BenchError,
    copy_system_prompts,
    scenario_dirs,
    seed_user_prompts,
    user_from_column,
    write_prompts,
)


def make_seed(**overrides) -> pl.DataFrame:
    """Graine minimale à deux familles, une ligne avec prefix."""
    data = {
        "generation_id": ["id-0", "id-1"],
        "template_name": ["medical_outpatient.txt", "surgery_inpatient.txt"],
        "user_prompt": ["Cas médical.", "Cas chirurgical."],
        "prefix": ["PREFIXE MÉDICAL", None],
    }
    data.update(overrides)
    return pl.DataFrame(data)


def seeded_test_dir(tmp_path: Path) -> Path:
    """Un test amorcé avec la graine minimale."""
    test_dir = tmp_path / "tests" / "01"
    seed_user_prompts(test_dir, make_seed())
    return test_dir


def mount_system(test_dir: Path, position: str = "first") -> Path:
    """Monte un jeu de templates système à deux familles (geste notebook)."""
    system_dir = test_dir / "system" / position
    system_dir.mkdir(parents=True)
    (system_dir / "medical_outpatient.txt").write_text("SYSTÈME MÉDECINE")
    (system_dir / "surgery_inpatient.txt").write_text("SYSTÈME CHIRURGIE")
    return system_dir


class TestSeedUserPrompts:
    """§10.1 — la graine, une fois."""

    def test_dossiers_numerotes_et_contenus(self, tmp_path: Path):
        """Dossiers dans l'ordre de la graine, avec user, template.txt (stem)
        et prefix.txt si la colonne est non vide ; plusieurs familles admises."""
        test_dir = tmp_path / "tests" / "01"
        created = seed_user_prompts(test_dir, make_seed())

        assert created == ["0000", "0001"]
        assert (test_dir / "0000" / "user_generation.txt").read_text(
            encoding="utf-8"
        ) == "Cas médical."
        assert (test_dir / "0000" / "template.txt").read_text(
            encoding="utf-8"
        ).strip() == "medical_outpatient"
        assert (test_dir / "0001" / "template.txt").read_text(
            encoding="utf-8"
        ).strip() == "surgery_inpatient"
        assert (test_dir / "0000" / "prefix.txt").read_text(
            encoding="utf-8"
        ) == "PREFIXE MÉDICAL"
        assert not (test_dir / "0001" / "prefix.txt").exists()

    def test_filename_et_user_fn_personnalises(self, tmp_path: Path):
        """`filename` et `user_fn` sont des arguments libres."""
        test_dir = tmp_path / "tests" / "01"
        seed_user_prompts(
            test_dir,
            make_seed(),
            filename="user_custom.txt",
            user_fn=lambda row: f"ID={row['generation_id']}",
        )
        assert (test_dir / "0000" / "user_custom.txt").read_text(
            encoding="utf-8"
        ) == "ID=id-0"

    def test_refus_si_deja_seme(self, tmp_path: Path):
        """Une graine par test : refuse si des dossiers scénario existent."""
        test_dir = seeded_test_dir(tmp_path)
        with pytest.raises(BenchError, match="0000"):
            seed_user_prompts(test_dir, make_seed())

    def test_refus_generation_id_duplique(self, tmp_path: Path):
        seed = make_seed(generation_id=["id-0", "id-0"])
        with pytest.raises(BenchError, match="generation_id"):
            seed_user_prompts(tmp_path / "t", seed)

    def test_refus_generation_id_nul(self, tmp_path: Path):
        seed = make_seed(generation_id=["id-0", None])
        with pytest.raises(BenchError, match="generation_id"):
            seed_user_prompts(tmp_path / "t", seed)

    def test_refus_template_name_nul(self, tmp_path: Path):
        seed = make_seed(template_name=["medical_outpatient.txt", None])
        with pytest.raises(BenchError, match="template_name"):
            seed_user_prompts(tmp_path / "t", seed)

    def test_refus_colonne_absente(self, tmp_path: Path):
        seed = make_seed().drop("generation_id")
        with pytest.raises(BenchError, match="generation_id"):
            seed_user_prompts(tmp_path / "t", seed)

    def test_test_json_conforme(self, tmp_path: Path):
        """`test.json` : `seed_path` en as_posix, blocs `generation_ids`
        et `templates`."""
        test_dir = tmp_path / "tests" / "01"
        seed_path = tmp_path / "data" / "scenarios_20260810.parquet"
        seed_user_prompts(test_dir, make_seed(), seed_path=seed_path)

        payload = json.loads((test_dir / "test.json").read_text(encoding="utf-8"))
        assert payload["seed_path"] == seed_path.as_posix()
        assert payload["generation_ids"] == {"0000": "id-0", "0001": "id-1"}
        assert payload["templates"] == {
            "0000": "medical_outpatient",
            "0001": "surgery_inpatient",
        }
        assert "created_at" in payload
        assert "fictomed_version" in payload
        assert "fictomed_commit" in payload
        assert payload["notes"] == ""


class TestScenarioDirs:
    """§10.2 — découverte disque."""

    def test_exclusions_tri_et_copie_manuelle(self, tmp_path: Path):
        """Exclut `system/`, `batches/` et cachés ; ignore les fichiers à la
        racine ; tri alphabétique ; un dossier copié à la main apparaît."""
        test_dir = seeded_test_dir(tmp_path)
        (test_dir / "system" / "first").mkdir(parents=True)
        (test_dir / "batches" / "crh_final").mkdir(parents=True)
        (test_dir / ".fictomed").mkdir()
        (test_dir / "prompt_local.py").write_text("def build_user(row): ...\n")
        shutil.copytree(test_dir / "0001", test_dir / "0001_bis")

        assert scenario_dirs(test_dir) == ["0000", "0001", "0001_bis"]

    def test_pycache_exclu(self, tmp_path: Path):
        """Un `__pycache__/` créé dans le test_dir (ex. import d'un
        `prompt_local.py`) n'apparaît pas dans la découverte."""
        test_dir = seeded_test_dir(tmp_path)
        (test_dir / "__pycache__").mkdir()

        assert scenario_dirs(test_dir) == ["0000", "0001"]

    def test_dossier_introuvable(self, tmp_path: Path):
        with pytest.raises(BenchError, match="introuvable"):
            scenario_dirs(tmp_path / "absent")


class TestCopySystemPrompts:
    """§10.3 — figement du jeu du test par scénario."""

    def test_figement_par_famille_dest_defaut(self, tmp_path: Path):
        """Deux familles reçoivent des contenus différents sous le même `dest`,
        depuis `system/<position>/` ; dest par défaut =
        `prompt_system_<position>.txt`."""
        test_dir = seeded_test_dir(tmp_path)
        mount_system(test_dir)

        served = copy_system_prompts(test_dir, "first")

        assert served == ["0000", "0001"]
        assert (test_dir / "0000" / "prompt_system_first.txt").read_text(
            encoding="utf-8"
        ) == "SYSTÈME MÉDECINE"
        assert (test_dir / "0001" / "prompt_system_first.txt").read_text(
            encoding="utf-8"
        ) == "SYSTÈME CHIRURGIE"

    def test_dest_explicite_les_variantes_coexistent(self, tmp_path: Path):
        test_dir = seeded_test_dir(tmp_path)
        mount_system(test_dir)
        copy_system_prompts(test_dir, "first")
        copy_system_prompts(test_dir, "first", dest="prompt_system_first_v2.txt")

        assert (test_dir / "0000" / "prompt_system_first.txt").exists()
        assert (test_dir / "0000" / "prompt_system_first_v2.txt").exists()

    def test_jeu_absent(self, tmp_path: Path):
        test_dir = seeded_test_dir(tmp_path)
        with pytest.raises(BenchError, match="system"):
            copy_system_prompts(test_dir, "first")

    def test_template_txt_absent(self, tmp_path: Path):
        test_dir = seeded_test_dir(tmp_path)
        mount_system(test_dir)
        (test_dir / "0000" / "template.txt").unlink()
        with pytest.raises(BenchError, match="template.txt"):
            copy_system_prompts(test_dir, "first")

    def test_famille_absente_du_jeu(self, tmp_path: Path):
        """L'erreur nomme le chemin attendu du fichier de famille."""
        test_dir = seeded_test_dir(tmp_path)
        system_dir = mount_system(test_dir)
        (system_dir / "surgery_inpatient.txt").unlink()
        with pytest.raises(BenchError) as excinfo:
            copy_system_prompts(test_dir, "first")
        assert str(system_dir / "surgery_inpatient.txt") in str(excinfo.value)
        assert not (test_dir / "0000" / "prompt_system_first.txt").exists()
        assert not (test_dir / "0001" / "prompt_system_first.txt").exists()

    def test_refus_ecraser_atomique(self, tmp_path: Path):
        """`dest` déjà présent dans UN dossier → BenchError listant les
        dossiers, rien n'est écrit — y compris dans les dossiers indemnes."""
        test_dir = seeded_test_dir(tmp_path)
        mount_system(test_dir)
        (test_dir / "0000" / "prompt_system_first.txt").write_text("DÉJÀ LÀ")

        with pytest.raises(BenchError, match="0000"):
            copy_system_prompts(test_dir, "first")

        assert (test_dir / "0000" / "prompt_system_first.txt").read_text(
            encoding="utf-8"
        ) == "DÉJÀ LÀ"
        assert not (test_dir / "0001" / "prompt_system_first.txt").exists()


class TestWritePrompts:
    """§10.4 — texte constant dans chaque dossier."""

    def test_ecrit_dans_chaque_dossier_y_compris_copie(self, tmp_path: Path):
        test_dir = seeded_test_dir(tmp_path)
        shutil.copytree(test_dir / "0001", test_dir / "0001_bis")

        served = write_prompts(test_dir, "prompt_system_verif.txt", "VÉRIFIE.")

        assert served == ["0000", "0001", "0001_bis"]
        for name in served:
            assert (test_dir / name / "prompt_system_verif.txt").read_text(
                encoding="utf-8"
            ) == "VÉRIFIE."

    def test_refus_ecraser_atomique(self, tmp_path: Path):
        test_dir = seeded_test_dir(tmp_path)
        (test_dir / "0001" / "user_verification.txt").write_text("DÉJÀ LÀ")

        with pytest.raises(BenchError, match="0001"):
            write_prompts(test_dir, "user_verification.txt", "NOUVEAU")

        assert not (test_dir / "0000" / "user_verification.txt").exists()
        assert (test_dir / "0001" / "user_verification.txt").read_text(
            encoding="utf-8"
        ) == "DÉJÀ LÀ"


class TestUserFromColumn:
    """§10.12 — `user_from_column`."""

    def test_colonne_absente(self):
        build_user = user_from_column("user_prompt")
        with pytest.raises(BenchError, match="user_prompt"):
            build_user({"generation_id": "id-0"})

    def test_valeur_nulle(self):
        build_user = user_from_column("user_prompt")
        with pytest.raises(BenchError, match="user_prompt"):
            build_user({"generation_id": "id-0", "user_prompt": None})


class TestPortabilite:
    """§10.14 — `seed_path` en `/`, `test.json` relisible tel quel."""

    def test_seed_path_posix_et_json_relisible(self, tmp_path: Path):
        test_dir = tmp_path / "tests" / "01"
        seed_path = tmp_path / "data" / "aphp" / "scenarios.parquet"
        seed_user_prompts(test_dir, make_seed(), seed_path=seed_path)

        raw = (test_dir / "test.json").read_text(encoding="utf-8")
        payload = json.loads(raw)
        assert "\\" not in payload["seed_path"]
        assert "/" in payload["seed_path"]
        assert payload["seed_path"].endswith("data/aphp/scenarios.parquet")

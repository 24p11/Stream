"""Tests de bench/scenarios.py — chaîne amont des scénarios (lot R1).

Sans fictomed et sans réseau : `generate_and_select_fictomed_scenarios`
(qui exige fictomed installé) n'est pas couverte ici — le smoke de chaîne
sur répertoire scratch (lot R3) en tient lieu.
"""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest
import yaml

from bench.scenarios import (
    apply_filters,
    build_filter_expr,
    prepare_source_candidates,
    resolve_parquet_path,
    write_fictomed_config,
)

JOUET = pl.DataFrame({
    "dp": ["N858", "K358", "Z468", "N858", None],
    "age": [42, 7, 15, 63, 30],
    "ghm2": ["12C08", "06C12", "23M20", "12C08", "12C08"],
})


class TestResolveParquetPath:
    def test_chemin_existant_tel_quel(self, tmp_path):
        p = tmp_path / "source.pq"
        p.touch()
        assert resolve_parquet_path(p) == p.resolve()

    def test_suffixe_devine_parquet_et_pq(self, tmp_path):
        for suffix in (".parquet", ".pq"):
            p = tmp_path / f"src_{suffix.strip('.')}{suffix}"
            p.touch()
            assert resolve_parquet_path(p.with_suffix("")) == p.resolve()

    def test_chemin_relatif_resolu_depuis_cwd(self, tmp_path, monkeypatch):
        (tmp_path / "rel.pq").touch()
        monkeypatch.chdir(tmp_path)
        assert resolve_parquet_path(Path("rel.pq")) == (tmp_path / "rel.pq").resolve()

    def test_introuvable(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="introuvable"):
            resolve_parquet_path(tmp_path / "absent.pq")


class TestFiltres:
    def test_operateurs(self):
        cas = [
            ({"column": "dp", "op": "eq", "value": "N858"}, [0, 3]),
            ({"column": "dp", "op": "ne", "value": "N858"}, [1, 2]),
            ({"column": "dp", "op": "in", "value": ["K358", "Z468"]}, [1, 2]),
            ({"column": "dp", "op": "not_in", "value": ["K358"]}, [0, 2, 3]),
            ({"column": "dp", "op": "startswith", "value": "N"}, [0, 3]),
            ({"column": "dp", "op": "endswith", "value": "8"}, [0, 1, 2, 3]),
            ({"column": "dp", "op": "contains", "value": "46"}, [2]),
            ({"column": "dp", "op": "regex", "value": r"^[NZ]"}, [0, 2, 3]),
            ({"column": "age", "op": "gt", "value": 42}, [3]),
            ({"column": "age", "op": "ge", "value": 42}, [0, 3]),
            ({"column": "age", "op": "lt", "value": 15}, [1]),
            ({"column": "age", "op": "le", "value": 15}, [1, 2]),
            ({"column": "dp", "op": "is_null"}, [4]),
            ({"column": "dp", "op": "not_null"}, [0, 1, 2, 3]),
        ]
        indexe = JOUET.with_row_index("i")
        for spec, attendu in cas:
            obtenu = indexe.filter(build_filter_expr(spec))["i"].to_list()
            assert obtenu == attendu, spec

    def test_exclude_inverse_et_nulls(self):
        # eq laisse tomber les nulls (fill_null(False)) ; exclude=True les
        # garde donc — l'inverse porte aussi sur les lignes nulles.
        spec = {"column": "dp", "op": "eq", "value": "N858", "exclude": True}
        obtenu = JOUET.with_row_index("i").filter(build_filter_expr(spec))["i"].to_list()
        assert obtenu == [1, 2, 4]

    def test_operateur_inconnu(self):
        with pytest.raises(ValueError, match="Opérateur inconnu"):
            build_filter_expr({"column": "dp", "op": "between", "value": 1})

    def test_apply_filters_enchaine_et_trace(self, capsys):
        result = apply_filters(
            JOUET,
            [{"column": "dp", "op": "not_null"},
             {"column": "age", "op": "ge", "value": 40}],
            label="TEST",
        )
        assert result.height == 2
        out = capsys.readouterr().out
        assert "TEST, filtre 1" in out and "5 -> 4" in out
        assert "TEST, filtre 2" in out and "4 -> 2" in out

    def test_apply_filters_colonne_absente(self):
        with pytest.raises(ValueError, match="colonne absente"):
            apply_filters(JOUET, [{"column": "inconnue", "op": "eq",
                                   "value": 1}], label="TEST")


class TestWriteFictomedConfig:
    def test_config_ecrite_et_chemins(self, tmp_path, capsys):
        racine = tmp_path / "projet"
        (racine / "data" / "aphp" / "referentials").mkdir(parents=True)
        (racine / "data" / "brest").mkdir(parents=True)
        run_dir = tmp_path / "run"
        config_file = run_dir / "servers.yaml"

        chemins = write_fictomed_config(
            config_file=config_file, project_root=racine, run_dir=run_dir)

        config = yaml.safe_load(config_file.read_text(encoding="utf-8"))
        aphp = config["pipelines"]["aphp"]["data"]
        assert Path(aphp["input"]) == (racine / "data" / "aphp").resolve()
        assert Path(aphp["referentials"]) == \
            (racine / "data" / "aphp" / "referentials").resolve()
        assert Path(aphp["output"]) == \
            (run_dir / "sorties" / "scenarios").resolve()
        assert Path(config["pipelines"]["brest"]["data"]["input"]) == \
            (racine / "data" / "brest").resolve()
        # chemins retournés cohérents, dossiers de sortie créés
        assert chemins["config_file"] == config_file.resolve()
        assert chemins["aphp_output"].is_dir()
        assert chemins["brest_output"].is_dir()

    def test_donnees_aphp_absentes(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="AP-HP"):
            write_fictomed_config(
                config_file=tmp_path / "servers.yaml",
                project_root=tmp_path / "vide",
                run_dir=tmp_path / "run")


class TestPrepareSourceCandidates:
    @pytest.fixture
    def parquet_jouet(self, tmp_path) -> Path:
        p = tmp_path / "profils.pq"
        pl.DataFrame({
            "dp": [f"N85{i}" if i % 2 else f"K35{i}" for i in range(20)],
            "age": list(range(20, 40)),
        }).write_parquet(p)
        return p

    def test_identification_filtres_et_pool(self, parquet_jouet):
        source_path, source_df, filtres, candidats = prepare_source_candidates(
            source_profiles_path=parquet_jouet,
            source_filters=[{"column": "dp", "op": "startswith", "value": "N"}],
            candidate_pool_size=5,
            random_selection=False,
            random_seed=42,
        )
        assert source_path == parquet_jouet.resolve()
        # identification répliquée dans le notebook (_ensure_source_ids)
        assert {"source_row_id", "source_scenario_id"} <= set(source_df.columns)
        assert source_df["source_scenario_id"][0] == "profils_row_0000000"
        assert filtres.height == 10
        assert candidats.height == 5
        # sans tirage aléatoire : les premières lignes filtrées
        assert candidats["source_row_id"].to_list() == [1, 3, 5, 7, 9]

    def test_tirage_seede_reproductible(self, parquet_jouet):
        def tirage():
            return prepare_source_candidates(
                source_profiles_path=parquet_jouet,
                source_filters=[],
                candidate_pool_size=6,
                random_selection=True,
                random_seed=7,
            )[3]["source_row_id"].to_list()

        premier = tirage()
        assert tirage() == premier
        assert len(premier) == 6

    def test_aucune_ligne_apres_filtres(self, parquet_jouet):
        with pytest.raises(ValueError, match="filtres source"):
            prepare_source_candidates(
                source_profiles_path=parquet_jouet,
                source_filters=[{"column": "dp", "op": "eq", "value": "X"}],
                candidate_pool_size=5,
                random_selection=False,
                random_seed=1,
            )

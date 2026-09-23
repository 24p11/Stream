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
    DPEC_TO_TPEC,
    apply_filters,
    build_filter_expr,
    ensure_source_ids,
    prepare_source_candidates,
    quotas_couverture,
    resolve_parquet_path,
    tirage_stratifie,
    with_typologie,
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


# ---------------------------------------------------------------------------
# Typologie, identifiants, tirage stratifié — fonctions extraites du notebook
# (amincissement de septembre 2026)
# ---------------------------------------------------------------------------

def source_jouet() -> pl.DataFrame:
    """Neuf séjours au schéma du parquet source, un par modalité attendue
    (+ une ligne sans case → « Autre »)."""
    return pl.DataFrame({
        "diag2": ["Z511", "Z491", "J188", "K358", "O048", "Z380", "Z04880", "I208", "R51"],
        "diagnostic_associes": ["C50 Z923", "N185 I10", "I10 NA", "", "Z640", "",
                                "F03+02", "E119 F172", ""],
        "sexe": ["2", "1", "1", "2", "2", "1", "2", "1", "1"],
        "agean": [55, 70, 80, 40, 30, 0, 25, 60, 45],
        "age": ["ge_18", "ge_18", "ge_18", "ge_18", "ge_18", "lt_18", "ge_18",
                "ge_18", "ge_18"],
        "ghm2": ["28Z07Z", "28Z04Z", "04M10T", "06C12A", "14Z08Z", "15M05A",
                 "23M20T", "05K101", "90Z00Z"],
        "racine": ["28Z07", "28Z04", "04M10", "06C12", "14Z08", "15M05", "23M20",
                   "05K10", "90Z00"],
        "duree": [0.0, 0.0, 1.0, 5.0, 0.0, 3.0, 0.0, 1.0, None],
        "mode_hospit": ["HP", "HP", "HC", "HC", "HP", "HC", "HP", "HC", "HC"],
        "mode_entree": [None, None, "URGENCES", "DOMICILE", None, None, None,
                        "DOMICILE", None],
        "mode_sortie": ["DOMICILE"] * 9,
        "mdp": [""] * 9,
        "n": [3, 5, 2, 1, 4, 7, 2, 1, 1],
        "nbda": [2, 2, 1, 0, 1, 0, 1, 2, 0],
    })


MODALITES_JOUET = [
    "Séance chimiothérapie simple adulte", "Séances simples",
    "Médecine adultes < 3 nuits", "Chirurgie adultes > 3 nuits", "IVG",
    "Bébé normal", "HDJ médecine adultes", "Interventionnel adultes < 3 nuits",
    "Autre",
]


class TestWithTypologie:
    def test_modalites_attendues(self):
        typee = with_typologie(source_jouet())
        assert typee["DPEC"].to_list() == MODALITES_JOUET
        assert typee["TPEC"].to_list() == [DPEC_TO_TPEC[m] for m in MODALITES_JOUET]
        assert typee["TPEC"].to_list()[:2] == ["Médecine", "Médecine"]
        assert typee["TPEC"][4] == "Obstétrique" and typee["TPEC"][5] == "Néonatalogie"

    def test_precedence_du_specifique(self):
        # un GHM 14Z/15M/28Z n'est jamais avalé par « type M ou Z »
        df = source_jouet().filter(pl.col("ghm2").is_in(["14Z08Z", "15M05A", "28Z04Z"]))
        assert with_typologie(df)["DPEC"].to_list() == ["Séances simples", "IVG", "Bébé normal"]

    def test_borne_trois_nuits(self):
        base = source_jouet().filter(pl.col("ghm2") == "04M10T")
        for duree, attendu in ((2.0, "Médecine adultes < 3 nuits"),
                               (3.0, "Médecine adultes > 3 nuits")):
            df = base.with_columns(pl.lit(duree).alias("duree"))
            assert with_typologie(df)["DPEC"][0] == attendu

    def test_chimio_reservee_aux_adultes(self):
        df = source_jouet().filter(pl.col("ghm2") == "28Z07Z").with_columns(
            pl.lit(12).alias("agean"))
        assert with_typologie(df)["DPEC"][0] == "Séances simples"

    def test_colonnes_conservees(self):
        typee = with_typologie(source_jouet())
        assert set(source_jouet().columns) | {"DPEC", "TPEC"} == set(typee.columns)


class TestEnsureSourceIds:
    def test_identifiants_poses_depuis_le_stem(self, tmp_path):
        df = ensure_source_ids(source_jouet(), tmp_path / "profils.pq")
        assert df["source_row_id"].to_list() == list(range(9))
        assert df["source_scenario_id"][0] == "profils_row_0000000"
        assert df["source_scenario_id"][8] == "profils_row_0000008"

    def test_idempotent_et_avant_filtre(self, tmp_path):
        df = ensure_source_ids(source_jouet(), tmp_path / "profils.pq")
        filtre = df.filter(pl.col("diag2").str.ends_with("8"))
        # les identifiants du parquet complet survivent au filtre
        assert filtre["source_row_id"].to_list() == [2, 3, 4, 7]
        assert ensure_source_ids(filtre, tmp_path / "autre.pq")["source_scenario_id"].to_list() \
            == filtre["source_scenario_id"].to_list()


def strates_jouet() -> pl.DataFrame:
    """Effectifs par DPEC : A ×5, B ×3, C ×1."""
    dpec = ["A"] * 5 + ["B"] * 3 + ["C"]
    return pl.DataFrame({
        "DPEC": dpec,
        "TPEC": ["T1"] * 8 + ["T2"],
        "i": list(range(9)),
    })


class TestTirageStratifie:
    def test_quotas_respectes_et_ordre(self, capsys):
        tirage = tirage_stratifie(strates_jouet(), {"B": 2, "A": 3}, seed=1)
        assert tirage["DPEC"].to_list() == ["B", "B", "A", "A", "A"]
        assert "Tirage stratifié par DPEC : 5 séjours (2 strate(s), seed=1)." \
            in capsys.readouterr().out

    def test_seed_reproductible(self):
        a = tirage_stratifie(strates_jouet(), {"A": 3}, seed=7)["i"].to_list()
        b = tirage_stratifie(strates_jouet(), {"A": 3}, seed=7)["i"].to_list()
        c = tirage_stratifie(strates_jouet(), {"A": 3}, seed=8)["i"].to_list()
        assert a == b
        assert sorted(a) != sorted(c) or a != c  # autre graine, autre tirage (sauf hasard)

    def test_quota_superieur_a_l_effectif_refuse(self):
        with pytest.raises(ValueError, match=r"Effectifs insuffisants.*'C': \(2, 1\)"):
            tirage_stratifie(strates_jouet(), {"C": 2})

    def test_modalite_inconnue_refusee_sauf_quota_zero(self, capsys):
        with pytest.raises(ValueError, match="Effectifs insuffisants"):
            tirage_stratifie(strates_jouet(), {"Z": 1})
        tirage = tirage_stratifie(strates_jouet(), {"Z": 0, "C": 1})
        assert tirage.height == 1
        assert "quotas à 0 sur modalités absentes de DPEC — sans effet : ['Z']" \
            in capsys.readouterr().out

    def test_par_tpec(self):
        tirage = tirage_stratifie(strates_jouet(), {"T2": 1, "T1": 2}, by="TPEC")
        assert tirage["TPEC"].to_list() == ["T2", "T1", "T1"]

    def test_couverture_un_par_modalite(self, capsys):
        assert quotas_couverture(strates_jouet()) == {"A": 1, "B": 1, "C": 1}
        tirage = tirage_stratifie(strates_jouet(), "couverture", seed=3)
        assert tirage["DPEC"].to_list() == ["A", "B", "C"]
        out = capsys.readouterr().out
        assert "Couverture : 1 séjour par modalité de DPEC présente (3 modalité(s))." in out
        assert "Tirage stratifié par DPEC : 3 séjours (3 strate(s), seed=3)." in out

    def test_couverture_ignore_les_nuls(self):
        df = strates_jouet().with_columns(
            pl.when(pl.col("i") == 8).then(None).otherwise(pl.col("DPEC")).alias("DPEC"))
        assert quotas_couverture(df) == {"A": 1, "B": 1}

    def test_chaine_inconnue_refusee(self):
        with pytest.raises(ValueError, match="quotas inconnus"):
            tirage_stratifie(strates_jouet(), "tout")

"""Tests de bench/scenarios.py — chaîne amont des scénarios (lot R1).

Sans fictomed et sans réseau : `generate_and_select_fictomed_scenarios`
(qui exige fictomed installé) n'est pas couverte ici — le smoke de chaîne
sur répertoire scratch (lot R3) en tient lieu.
"""

from __future__ import annotations

from collections import Counter
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
        # le dernier séjour (« Autre », durée nulle) est aussi sans mode
        # d'entrée : incomplet pour fictomed, écarté avant le tirage
        "mode_entree": ["DOMICILE", "DOMICILE", "URGENCES", "DOMICILE", "DOMICILE",
                        "DOMICILE", "DOMICILE", "DOMICILE", None],
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


# ---------------------------------------------------------------------------
# Dérivation de l'âge numérique depuis la classe d'âge (24/09/2026)
# ---------------------------------------------------------------------------

from bench.scenarios import (  # noqa: E402
    LARGEUR_CLASSE_OUVERTE, bornes_cage, deriver_agean, graine_ligne,
)


class TestBornesCage:
    def test_nominal_et_extremes(self):
        assert bornes_cage("[18-30[") == (18, 29)
        assert bornes_cage("[5-10[") == (5, 9)
        assert bornes_cage("[0-1[") == (0, 0)
        assert bornes_cage("[15-18[") == (15, 17)
        assert bornes_cage("[80-[") == (80, 80 + LARGEUR_CLASSE_OUVERTE - 1) == (80, 89)
        assert bornes_cage("  [1-5[ ") == (1, 4)

    @pytest.mark.parametrize("libelle", ["80+", "18-30", "[18-30]", "", "ge_18", "[a-b[", None])
    def test_libelle_inattendu_erreur_explicite(self, libelle):
        with pytest.raises(ValueError, match="classe d'âge illisible"):
            bornes_cage(libelle)

    def test_classe_vide_refusee(self):
        with pytest.raises(ValueError, match="classe d'âge vide"):
            bornes_cage("[30-30[")


def corpus_cage(n: int = 200, cage: str = "[18-30[", pivot: str | None = None) -> pl.DataFrame:
    df = pl.DataFrame({"id_scenario": [f"s-{i:04d}" for i in range(n)],
                       "cage": [cage] * n, "diag2": ["K358"] * n})
    return df.with_columns(pl.lit(pivot).alias("age")) if pivot is not None else df


class TestDeriverAgean:
    def test_tirage_dans_la_classe_et_couverture(self):
        out, rapport = deriver_agean(corpus_cage(600, "[18-30["))
        assert out["agean"].dtype == pl.Int32
        assert out["agean"].min() == 18 and out["agean"].max() == 29
        assert set(out["agean"].to_list()) == set(range(18, 30))  # uniforme : toutes les valeurs sorties
        assert rapport.derive and rapport.source == "dérivé de cage"
        assert rapport.n_derives == 600 and rapport.n_lignes == 600
        assert "variable DÉRIVÉE" in rapport.texte()

    def test_classes_extremes(self):
        df = pl.DataFrame({"id_scenario": ["a", "b"], "cage": ["[0-1[", "[80-["]})
        out, _ = deriver_agean(df)
        assert out["agean"][0] == 0 and 80 <= out["agean"][1] <= 89

    def test_deterministe_deux_passes_et_ordre(self):
        df = corpus_cage(300).with_columns(pl.Series("cage", ["[18-30[", "[60-70[", "[0-1["] * 100))
        a, _ = deriver_agean(df)
        b, _ = deriver_agean(df)
        assert a["agean"].to_list() == b["agean"].to_list()
        c, _ = deriver_agean(df.sample(fraction=1.0, shuffle=True, seed=3))
        assert a.sort("id_scenario")["agean"].to_list() == c.sort("id_scenario")["agean"].to_list()

    def test_deterministe_deux_processus(self, tmp_path):
        import subprocess, sys
        corpus_cage(50, "[40-50[").write_parquet(tmp_path / "c.parquet")
        code = ("import polars as pl, sys; sys.path.insert(0, %r); "
                "from bench.scenarios import deriver_agean; "
                "print(deriver_agean(pl.read_parquet(%r))[0]['agean'].to_list())"
                % (str(Path(__file__).resolve().parents[1]), str(tmp_path / "c.parquet")))
        sorties = []
        for graine_processus in ("1", "2"):
            res = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                                 env={"PYTHONHASHSEED": graine_processus, "PATH": ""})
            assert res.returncode == 0, res.stderr
            sorties.append(res.stdout)
        assert sorties[0] == sorties[1]

    def test_meme_cle_meme_age(self):
        df = pl.DataFrame({"id_scenario": ["v"] * 20, "cage": ["[50-60["] * 20, "duree": list(range(20))})
        out, _ = deriver_agean(df)
        assert out["agean"].n_unique() == 1

    def test_graine_stable_separee_par_domaine(self):
        assert graine_ligne("x") == graine_ligne("x")
        assert graine_ligne("x") != graine_ligne("y")
        assert graine_ligne("x", "agean") != graine_ligne("x", "dp")

    def test_agean_existant_jamais_ecrase(self):
        df = corpus_cage(5).with_columns(pl.Series("agean", [3, 99, 7, 42, 0]))
        out, rapport = deriver_agean(df)
        assert out.equals(df)
        assert not rapport.derive and rapport.source == "lu du fichier"
        assert "conservée telle quelle" in rapport.texte()

    def test_agean_non_numerique_erreur(self):
        df = corpus_cage(3).with_columns(pl.lit("ge_18").alias("agean"))
        with pytest.raises(ValueError, match="agean présente mais non numérique"):
            deriver_agean(df)

    def test_colonnes_manquantes(self):
        with pytest.raises(ValueError, match=r"colonne\(s\) manquante\(s\) \['cage'\]"):
            deriver_agean(pl.DataFrame({"id_scenario": ["a"]}))
        with pytest.raises(ValueError, match=r"\['id_scenario'\]"):
            deriver_agean(pl.DataFrame({"cage": ["[0-1["]}))

    def test_pivot_restreint_la_classe_a_cheval(self):
        n = 300
        df = pl.DataFrame({"id_scenario": [f"p-{i}" for i in range(n)],
                           "cage": ["[15-20["] * n,
                           "age": ["lt_18", "ge_18"] * (n // 2)})
        out, rapport = deriver_agean(df)
        mineurs = out.filter(pl.col("age") == "lt_18")["agean"]
        majeurs = out.filter(pl.col("age") == "ge_18")["agean"]
        assert set(mineurs.to_list()) == {15, 16, 17}
        assert set(majeurs.to_list()) == {18, 19}
        assert rapport.source == "dérivé de cage, pivot age"
        assert rapport.n_pivot_restreint == n and rapport.n_chevauchant_18_sans_pivot == 0
        assert rapport.classes_chevauchant_18 == ["[15-20["]
        assert any("toutes résolues par le pivot" in c for c in rapport.constats)

    def test_pivot_contradictoire_ignore_et_compte(self):
        df = pl.DataFrame({"id_scenario": ["a", "b"], "cage": ["[18-30[", "[0-1["],
                           "age": ["lt_18", "ge_18"]})
        out, rapport = deriver_agean(df)
        assert 18 <= out["agean"][0] <= 29 and out["agean"][1] == 0
        assert rapport.n_pivot_contradictoire == 2
        assert any("contradictoire" in c for c in rapport.constats)

    def test_pivot_numerique_sans_effet_signale(self):
        df = pl.DataFrame({"id_scenario": ["a", "b"], "cage": ["[18-30["] * 2, "age": ["25", "27"]})
        out, rapport = deriver_agean(df)
        assert rapport.n_pivot_inconnu == 2 and rapport.n_pivot_restreint == 0
        assert any("hors ge_18 / lt_18 sur 2 ligne(s)" in c for c in rapport.constats)

    def test_classe_a_cheval_sans_pivot_consignee_sans_echec(self):
        df = pl.DataFrame({"id_scenario": [f"c-{i}" for i in range(40)],
                           "cage": ["[15-20[", "[18-30["] * 20})
        out, rapport = deriver_agean(df)
        assert out["agean"].null_count() == 0
        assert rapport.classes_chevauchant_18 == ["[15-20["]
        assert rapport.n_chevauchant_18_sans_pivot == 20
        assert any("peut basculer mineur / majeur" in c for c in rapport.constats)

    def test_classe_nulle_donne_agean_nul(self):
        df = pl.DataFrame({"id_scenario": ["a", "b"], "cage": ["[18-30[", None]})
        out, rapport = deriver_agean(df)
        assert out["agean"][1] is None and rapport.n_sans_classe == 1
        assert any("sans classe d'âge" in c for c in rapport.constats)

    def test_libelle_inattendu_remonte(self):
        with pytest.raises(ValueError, match="classe d'âge illisible"):
            deriver_agean(corpus_cage(3, "80+"))


# ---------------------------------------------------------------------------
# Garde-fou racine et spécialité (service d'hospitalisation) — 24/09/2026
# ---------------------------------------------------------------------------

from bench.scenarios import (  # noqa: E402
    DERIVER, charger_mapping_type_unite, deriver_specialite, reparer_racine,
)


class TestReparerRacine:
    def test_reparation_nominale_et_compteur(self):
        df = pl.DataFrame({"racine": [None, "01C03", None], "ghm2": ["01C031", "01C031", "06C08A"]})
        out, rapport = reparer_racine(df)
        assert out["racine"].to_list() == ["01C03", "01C03", "06C08"]
        assert out["racine_reparee"].to_list() == [True, False, True]
        assert rapport.n_reparees == 2 and rapport.n_lignes == 3
        assert rapport.n_irreparables == 0 and rapport.n_divergentes == 0
        assert "2/3 réparée(s) depuis ghm2[:5]" in rapport.texte()
        assert "doit valoir 0" in rapport.texte()

    def test_les_deux_nuls_signale(self):
        df = pl.DataFrame({"racine": [None, "01C03"], "ghm2": [None, "01C031"]})
        out, rapport = reparer_racine(df)
        assert out["racine"].to_list() == [None, "01C03"]
        assert rapport.n_reparees == 0 and rapport.n_irreparables == 1
        assert "sans racine ni ghm2" in rapport.texte()

    def test_divergence_detectee_sans_ecrasement(self):
        df = pl.DataFrame({"racine": ["01C05", "01C03"], "ghm2": ["01C999", "01C031"]})
        out, rapport = reparer_racine(df)
        assert out["racine"].to_list() == ["01C05", "01C03"]  # l'observé prime
        assert out["racine_reparee"].to_list() == [False, False]
        assert rapport.n_divergentes == 1 and rapport.exemples_divergence == [("01C05", "01C999")]
        assert "NON modifiées" in rapport.texte()

    def test_compteur_zero_apres_correction_amont(self):
        df = pl.DataFrame({"racine": ["01C03", "06C08"], "ghm2": ["01C031", "06C08A"]})
        out, rapport = reparer_racine(df)
        assert rapport.n_reparees == 0 and not out["racine_reparee"].any()

    def test_colonne_racine_absente_creee_et_sans_ghm2_erreur(self):
        out, rapport = reparer_racine(pl.DataFrame({"ghm2": ["01C031", None]}))
        assert out["racine"].to_list() == ["01C03", None] and rapport.colonne_creee
        assert rapport.n_reparees == 1 and rapport.n_irreparables == 1
        with pytest.raises(ValueError, match="ni `racine` ni `ghm2`"):
            reparer_racine(pl.DataFrame({"diag2": ["A00"]}))


def dico_jouet() -> pl.DataFrame:
    """Dictionnaire brut : 01C03 adulte unique ; 01C05 adulte 3 candidates
    (0.6 / 0.3 / 0.1) ; 01C05 enfant unique ; 05K10 adulte 2 candidates ;
    15M05 enfant unique (NEONATOLOGIE)."""
    lignes = [
        ("01C03", "ge_18", "NEURO-CHIRURGIE", 1.0),
        ("01C05", "ge_18", "NEURO-CHIRURGIE", 0.6),
        ("01C05", "ge_18", "CH.ORTHO.ET TRAUMATO", 0.3),
        ("01C05", "ge_18", "MEDECINE INTERNE", 0.1),
        ("01C05", "lt_18", "NEURO-CHIRURGIE INFANTILE", 1.0),
        ("05K10", "ge_18", "CARDIOLOGIE", 0.5),
        ("05K10", "ge_18", "CHIR.CARDIO-VASC.", 0.5),
        ("15M05", "lt_18", "NEONATOLOGIE", 1.0),
    ]
    return pl.DataFrame(lignes, schema=["racine", "age", "lib_spe_uma", "ratio_spe_racine"], orient="row") \
        .with_columns(pl.lit(1).alias("nb_spe"), pl.lit(100).alias("effectifs_aphp"))


def yaml_mapping(tmp_path: Path, texte: str) -> Path:
    p = tmp_path / "mapping_type_unite.yaml"
    p.write_text(texte, encoding="utf-8")
    return p


class TestChargerMappingTypeUnite:
    def test_valide_applique_proposition_ignoree(self, tmp_path):
        p = yaml_mapping(tmp_path, """
entrees:
  NEONAT: {specialite: NEONATOLOGIE, statut: valide}
  geriatrie: {specialite: MEDECINE INTERNE, statut: proposition}
  HC: {specialite: DERIVER, statut: valide}
""")
        assert charger_mapping_type_unite(p) == {"NEONAT": "NEONATOLOGIE"}
        assert charger_mapping_type_unite(p, ["NEONATOLOGIE"]) == {"NEONAT": "NEONATOLOGIE"}

    def test_valide_hors_vocabulaire_refuse_sauf_assume(self, tmp_path):
        p = yaml_mapping(tmp_path, "entrees:\n  X: {specialite: URGENCES, statut: valide}\n")
        with pytest.raises(ValueError, match="hors vocabulaire.*hors_vocabulaire: true"):
            charger_mapping_type_unite(p, ["NEONATOLOGIE"])
        p = yaml_mapping(tmp_path, "entrees:\n  X: {specialite: URGENCES, statut: valide, hors_vocabulaire: true}\n")
        assert charger_mapping_type_unite(p, ["NEONATOLOGIE"]) == {"X": "URGENCES"}

    def test_fichier_vide_ou_illisible(self, tmp_path):
        assert charger_mapping_type_unite(yaml_mapping(tmp_path, "# rien\n")) == {}
        with pytest.raises(ValueError, match="illisible"):
            charger_mapping_type_unite(yaml_mapping(tmp_path, "entrees:\n  X: NEONATOLOGIE\n"))

    def test_yaml_du_depot_charge_avec_le_vocabulaire_reel(self):
        # les décisions de Rémi (25/09/2026) : cinq entrées appliquées, dont quatre hors
        # vocabulaire assumées ; HC et HP en DERIVER (étage 2)
        racine = Path(__file__).resolve().parents[1]
        p = racine / "data" / "aphp" / "referentials" / "mapping_type_unite.yaml"
        dico = racine / "data" / "aphp" / "referentials" / "dictionnaire_spe_racine.parquet"
        if not (p.is_file() and dico.is_file()):
            pytest.skip("mapping ou dictionnaire absent de data/ sur ce poste")
        vocab = pl.read_parquet(dico)["lib_spe_uma"].unique().to_list()
        applicables = charger_mapping_type_unite(p, vocab)
        assert "HC" not in applicables and "HP" not in applicables  # DERIVER
        assert applicables["NEONAT"] == "NEONATOLOGIE"
        assert set(applicables) >= {"GERIATRIE", "NEONAT", "SC", "SC-NEONAT", "UHCD"}


def corpus_specialite(n: int = 1, **colonnes) -> pl.DataFrame:
    base = {"id_scenario": ["s"] * n, "racine": ["01C05"] * n, "agean": [40] * n,
            "duree": list(range(n)), "mode_entree": ["DOMICILE"] * n,
            "mode_sortie": ["DOMICILE"] * n, "mdp": [""] * n, "type_unite": [None] * n}
    base.update(colonnes)
    return pl.DataFrame(base)


class TestDeriverSpecialite:
    def test_etage1_mapping_observee(self):
        df = corpus_specialite(2, type_unite=["NEONAT", " neonat "])
        out, rapport = deriver_specialite(df, dico_jouet(), {"NEONAT": "NEONATOLOGIE"})
        assert out["specialty"].to_list() == ["NEONATOLOGIE"] * 2
        assert out["specialite_source"].to_list() == ["observee"] * 2
        assert rapport.par_source["observee"] == 2 and rapport.n_mapping_applicable == 1

    def test_etage2_unique_sans_tirage(self):
        out, rapport = deriver_specialite(corpus_specialite(1, racine=["01C03"]), dico_jouet())
        assert out["specialty"][0] == "NEURO-CHIRURGIE" and out["specialite_source"][0] == "unique"

    def test_etage2_pondere_proportions_sous_graine(self):
        n = 3000
        df = corpus_specialite(n, id_scenario=[f"s-{i}" for i in range(n)])
        out, rapport = deriver_specialite(df, dico_jouet())
        assert set(out["specialite_source"].to_list()) == {"tiree"}
        comptes = Counter(out["specialty"].to_list())
        assert abs(comptes["NEURO-CHIRURGIE"] / n - 0.6) < 0.03
        assert abs(comptes["CH.ORTHO.ET TRAUMATO"] / n - 0.3) < 0.03
        assert abs(comptes["MEDECINE INTERNE"] / n - 0.1) < 0.03

    def test_frontiere_age_17_vs_18(self):
        df = corpus_specialite(2, agean=[17, 18], duree=[0, 0])
        out, _ = deriver_specialite(df, dico_jouet())
        assert out["specialty"].to_list() == ["NEURO-CHIRURGIE INFANTILE", out["specialty"][1]]
        assert out["specialite_source"].to_list()[0] == "unique"
        assert out["specialty"][1] in ("NEURO-CHIRURGIE", "CH.ORTHO.ET TRAUMATO", "MEDECINE INTERNE")

    def test_graine_composite_par_ligne(self):
        # même id_scenario, contextes différents → tirages indépendants ; lignes identiques → même résultat
        n = 400
        df = corpus_specialite(n, id_scenario=["v"] * n, racine=["05K10"] * n, duree=list(range(n)))
        out, rapport = deriver_specialite(df, dico_jouet())
        assert rapport.colonnes_graine == ("id_scenario", "duree", "mode_entree", "mode_sortie", "mdp")
        assert out["specialty"].n_unique() == 2  # les deux candidates sortent : contextes indépendants
        identiques = corpus_specialite(50, id_scenario=["v"] * 50, racine=["05K10"] * 50, duree=[7] * 50)
        assert deriver_specialite(identiques, dico_jouet())[0]["specialty"].n_unique() == 1

    def test_deterministe_ordre_et_deux_processus(self, tmp_path):
        import subprocess, sys
        n = 300
        df = corpus_specialite(n, id_scenario=[f"s-{i % 60}" for i in range(n)],
                               racine=["01C05", "05K10", "01C03"] * 100)
        a, _ = deriver_specialite(df, dico_jouet())
        b, _ = deriver_specialite(df.sample(fraction=1.0, shuffle=True, seed=5), dico_jouet())
        assert a.sort("id_scenario", "duree")["specialty"].to_list() == b.sort("id_scenario", "duree")["specialty"].to_list()
        df.write_parquet(tmp_path / "c.parquet"); dico_jouet().write_parquet(tmp_path / "d.parquet")
        code = ("import polars as pl, sys; sys.path.insert(0, %r); from bench.scenarios import deriver_specialite; "
                "print(deriver_specialite(pl.read_parquet(%r), pl.read_parquet(%r))[0]['specialty'].to_list())"
                % (str(Path(__file__).resolve().parents[1]), str(tmp_path / "c.parquet"), str(tmp_path / "d.parquet")))
        sorties = []
        for g in ("1", "2"):
            res = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                                 env={"PYTHONHASHSEED": g, "PATH": ""})
            assert res.returncode == 0, res.stderr
            sorties.append(res.stdout)
        assert sorties[0] == sorties[1] and str(a["specialty"].to_list()) in sorties[0]

    def test_repli_trace_et_compte(self):
        df = corpus_specialite(3, racine=["99Z99", None, "01C03"], agean=[40, 40, None])
        out, rapport = deriver_specialite(df, dico_jouet())
        assert out["specialty"].to_list() == [None, None, None]
        assert out["specialite_source"].to_list() == ["repli"] * 3
        assert rapport.par_source["repli"] == 3
        assert rapport.racines_sans_entree == {"99Z99": 1, "(racine nulle)": 1, "01C03": 1}
        assert "pas de ligne Service" in rapport.texte()

    def test_ratios_ne_sommant_pas_a_1_echec_bruyant(self):
        dico = dico_jouet().with_columns(
            pl.when(pl.col("lib_spe_uma") == "MEDECINE INTERNE").then(0.3).otherwise(pl.col("ratio_spe_racine")).alias("ratio_spe_racine"))
        with pytest.raises(ValueError, match="ne somment pas à 1"):
            deriver_specialite(corpus_specialite(1), dico)

    def test_schema_brut_verifie(self):
        with pytest.raises(ValueError, match=r"colonne\(s\) manquante\(s\) \['lib_spe_uma'\]"):
            deriver_specialite(corpus_specialite(1), dico_jouet().rename({"lib_spe_uma": "specialty"}))

    def test_mapping_sans_vocabulaire_deriver_ignore(self):
        out, _ = deriver_specialite(corpus_specialite(1, type_unite=["HC"], racine=["01C03"]), dico_jouet(), {"HC": DERIVER})
        # DERIVER n'est jamais transmis par charger_mapping ; passé à la main il s'appliquerait : on vérifie que
        # charger_mapping l'écarte (voir TestChargerMappingTypeUnite) et que l'étage 2 fonctionne sans mapping
        out2, _ = deriver_specialite(corpus_specialite(1, racine=["01C03"]), dico_jouet(), None)
        assert out2["specialite_source"][0] == "unique"

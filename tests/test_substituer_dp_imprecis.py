"""Tests de scripts/substituer_dp_imprecis.py — substitution des DP imprécis
d'un corpus (fichier → fichier). Fixtures construites ici : petit corpus,
petite référence. Sans réseau, sur tmp_path.
"""

from __future__ import annotations

import subprocess
import sys
from collections import Counter
from pathlib import Path

import polars as pl
import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "substituer_dp_imprecis.py"
if str(SCRIPT.parent) not in sys.path:
    sys.path.insert(0, str(SCRIPT.parent))

import substituer_dp_imprecis as sdi  # noqa: E402


# ---------------------------------------------------------------- fixtures

def reference() -> pl.DataFrame:
    """Référence jouet.

    - K35 : K358 imprécis partout ; précis K350 (30) et K351 (10) dans la
      strate (A, 1) → niveau 0 ; en (A, 2) aucun précis, mais K351 (5) en
      (B, 2) → niveau 1 pour un patient (A, 2) ;
    - J18 : J189 imprécis ; J180 précis seulement en (A, 1) → un patient
      (B, 2) tombe au niveau 2 ;
    - R69 : R69 imprécis, aucun précis nulle part → conservé faute de
      candidat ;
    - niveau (sévérité CMA) présent et ignoré : les nb sont sommés (K350
      est éclaté sur deux niveaux, 20 + 10 = 30).
    """
    lignes = [
        # cat, code, cage, sexe, nb, niveau, imprecis
        ("K35", "K358", "A", "1", 50, 1, True),
        ("K35", "K358", "A", "2", 50, 1, True),
        ("K35", "K358", "B", "2", 50, 1, True),
        ("K35", "K350", "A", "1", 20, 1, False),
        ("K35", "K350", "A", "1", 10, 2, False),
        ("K35", "K351", "A", "1", 10, 1, False),
        ("K35", "K351", "B", "2", 5, 1, False),
        ("J18", "J189", "A", "1", 40, 1, True),
        ("J18", "J189", "B", "2", 40, 1, True),
        ("J18", "J180", "A", "1", 7, 1, False),
        ("R69", "R69", "A", "1", 9, 1, True),
    ]
    return pl.DataFrame(
        lignes, schema=["cat", "code", "cage", "sexe", "nb", "niveau", "imprecis"], orient="row"
    )


def corpus() -> pl.DataFrame:
    lignes = [
        # id_scenario, branche, diag2, diagnostic_associes, cage, sexe, type_unite
        ("s-niv0", "long", "K358", "I10 K358", "A", "1", "HC"),      # substitué niveau 0
        ("s-niv1", "long", "K358", "", "A", "2", "HC"),              # niveau 1 → K351
        ("s-niv2", "long", "J189", "J189 E119", "B", "2", "HC"),     # niveau 2 → J180
        ("s-uhcd", "long", "K358", "", "A", "1", "UHCD"),           # conservé UHCD
        ("s-sans", "long", "R69", "", "A", "1", "HC"),               # conservé faute de candidat
        ("s-precis", "long", "K350", "K358", "A", "1", "HC"),        # DP déjà précis : rien
        ("s-court", "court", "K358", "", "A", "1", None),            # court : type_unite nulle → substitué
        ("s-court2", "court", "J189", "", "A", "1", None),           # niveau 0 → J180
    ]
    return pl.DataFrame(
        lignes,
        schema=["id_scenario", "branche", "diag2", "diagnostic_associes", "cage", "sexe", "type_unite"],
        orient="row",
    )


def ecrire(tmp_path: Path, corp: pl.DataFrame | None = None, ref: pl.DataFrame | None = None
           ) -> tuple[Path, Path]:
    c, r = tmp_path / "scenarios_T.parquet", tmp_path / "ref_substitution_imprecis.parquet"
    (corpus() if corp is None else corp).write_parquet(c)
    (reference() if ref is None else ref).write_parquet(r)
    return c, r


def substituer(corp: pl.DataFrame, ref: pl.DataFrame | None = None) -> tuple[pl.DataFrame, sdi.Rapport]:
    rapport = sdi.Rapport(Path("c.parquet"), Path("r.parquet"), Path("c_dp.parquet"))
    normalisee = sdi.normaliser_reference(reference() if ref is None else ref)
    return sdi.substituer(corp, normalisee, rapport), rapport


# ---------------------------------------------------------------- règle

class TestRegle:
    def test_substitution_et_niveaux_de_repli(self):
        out, rapport = substituer(corpus())
        r = {row["id_scenario"]: row for row in out.iter_rows(named=True)}
        assert r["s-niv0"]["diag2"] in ("K350", "K351") and r["s-niv0"]["repli_substitution"] == 0
        assert r["s-niv1"]["diag2"] == "K351" and r["s-niv1"]["repli_substitution"] == 1
        assert r["s-niv2"]["diag2"] == "J180" and r["s-niv2"]["repli_substitution"] == 2
        assert r["s-court2"]["diag2"] == "J180" and r["s-court2"]["repli_substitution"] == 0
        for k in ("s-niv0", "s-niv1", "s-niv2", "s-court", "s-court2"):
            assert r[k]["dp_substitue"] is True

    def test_exemption_uhcd(self):
        out, rapport = substituer(corpus())
        row = out.filter(pl.col("id_scenario") == "s-uhcd").row(0, named=True)
        assert row["diag2"] == "K358" and row["dp_substitue"] is False
        assert row["repli_substitution"] is None
        assert rapport.branches["long"].conserves_uhcd == 1

    def test_conservation_faute_de_candidat(self):
        out, rapport = substituer(corpus())
        row = out.filter(pl.col("id_scenario") == "s-sans").row(0, named=True)
        assert row["diag2"] == "R69" and row["dp_substitue"] is False
        assert rapport.branches["long"].conserves_sans_candidat == 1

    def test_dp_precis_intouche(self):
        out, _ = substituer(corpus())
        row = out.filter(pl.col("id_scenario") == "s-precis").row(0, named=True)
        assert row["diag2"] == "K350" and row["dp_substitue"] is False
        assert row["dp_origine"] == "K350" and row["repli_substitution"] is None

    def test_court_sans_type_unite_substitue_par_defaut(self):
        out, rapport = substituer(corpus())
        row = out.filter(pl.col("id_scenario") == "s-court").row(0, named=True)
        assert row["dp_substitue"] is True and row["repli_substitution"] == 0
        assert rapport.branches["court"].imprecis == 2
        assert sum(rapport.branches["court"].substitues.values()) == 2
        assert any("type_unite nulle sur toute la branche court" in c for c in rapport.constats)

    def test_das_strictement_intouches_et_tracabilite(self):
        corp = corpus()
        out, _ = substituer(corp)
        assert out["diagnostic_associes"].to_list() == corp["diagnostic_associes"].to_list()
        # toutes les colonnes d'entrée conservées, dans l'ordre, sauf diag2
        for c in corp.columns:
            if c != "diag2":
                assert out[c].to_list() == corp[c].to_list(), c
        assert out.columns == corp.columns + ["dp_origine", "dp_substitue", "repli_substitution"]
        assert out["dp_origine"].to_list() == corp["diag2"].to_list()
        assert out["dp_substitue"].dtype == pl.Boolean
        change = (out["diag2"] != out["dp_origine"]).to_list()
        assert change == out["dp_substitue"].to_list()
        assert all((r is not None) == s for r, s in zip(out["repli_substitution"].to_list(), change))

    def test_jamais_un_code_hors_reference(self):
        out, _ = substituer(corpus())
        codes_ref = set(reference()["code"].to_list())
        assert set(out["diag2"].to_list()) <= codes_ref | {"K350"}
        assert all(c in codes_ref for c in out.filter(pl.col("dp_substitue"))["diag2"].to_list())

    def test_uhcd_insensible_a_la_casse_et_niveau_ignore(self):
        corp = corpus().with_columns(
            pl.when(pl.col("id_scenario") == "s-uhcd").then(pl.lit(" uhcd ")).otherwise(pl.col("type_unite")).alias("type_unite"))
        out, rapport = substituer(corp)
        assert out.filter(pl.col("id_scenario") == "s-uhcd")["diag2"][0] == "K358"
        assert rapport.n_codes_imprecis_ref == 3 and rapport.n_codes_precis_ref == 3

    def test_sans_colonne_branche_ni_type_unite(self):
        corp = corpus().drop("branche", "type_unite")
        out, rapport = substituer(corp)
        assert list(rapport.branches) == [sdi.BRANCHE_UNIQUE]
        assert rapport.branches[sdi.BRANCHE_UNIQUE].conserves_uhcd == 0
        assert out.filter(pl.col("id_scenario") == "s-uhcd")["dp_substitue"][0] is True
        assert any("type_unite absente" in c for c in rapport.constats)

    def test_colonne_manquante_refusee(self):
        with pytest.raises(sdi.ErreurSubstitution, match=r"colonne\(s\) manquante\(s\) \['cage'\]"):
            substituer(corpus().drop("cage"))
        with pytest.raises(sdi.ErreurSubstitution, match=r"référence : colonne\(s\) manquante\(s\) \['imprecis'\]"):
            sdi.normaliser_reference(reference().drop("imprecis"))
        with pytest.raises(sdi.ErreurSubstitution, match="référence illisible"):
            sdi.charger_reference(Path(__file__))


# ---------------------------------------------------------------- tirage pondéré

class TestTiragePondere:
    def test_proportions_sous_graine(self):
        # 2 000 patients (A, 1) avec K358 : K350 pèse 30, K351 pèse 10 → ~75 % / 25 %
        n = 2000
        corp = pl.DataFrame({
            "id_scenario": [f"p-{i:05d}" for i in range(n)],
            "diag2": ["K358"] * n, "cage": ["A"] * n, "sexe": ["1"] * n,
        })
        out, rapport = substituer(corp)
        comptes = Counter(out["diag2"].to_list())
        assert set(comptes) == {"K350", "K351"}
        assert abs(comptes["K350"] / n - 0.75) < 0.04
        assert rapport.branches[sdi.BRANCHE_UNIQUE].substitues == Counter({0: n})

    def test_effectif_nul_ignore(self):
        ref = reference().with_columns(
            pl.when(pl.col("code") == "K351").then(0).otherwise(pl.col("nb")).alias("nb"))
        n = 200
        corp = pl.DataFrame({
            "id_scenario": [f"q-{i}" for i in range(n)],
            "diag2": ["K358"] * n, "cage": ["A"] * n, "sexe": ["1"] * n,
        })
        out, _ = substituer(corp, ref)
        assert set(out["diag2"].to_list()) == {"K350"}


# ---------------------------------------------------------------- déterminisme

class TestDeterminisme:
    def test_graine_stable_sans_hash_natif(self):
        assert sdi.graine_ligne("kfb3576726ac210f-001") == sdi.graine_ligne("kfb3576726ac210f-001")
        assert sdi.graine_ligne("a") != sdi.graine_ligne("b")
        assert sdi.graine_ligne(12) == sdi.graine_ligne("12")
        assert 0 <= sdi.graine_ligne("x") < 2 ** 64

    def test_ordre_des_lignes_indifferent(self):
        n = 300
        corp = pl.DataFrame({
            "id_scenario": [f"o-{i}" for i in range(n)],
            "diag2": ["K358", "J189"] * (n // 2),
            "cage": ["A", "B"] * (n // 2), "sexe": ["1", "2"] * (n // 2),
        })
        a, _ = substituer(corp)
        b, _ = substituer(corp.sample(fraction=1.0, shuffle=True, seed=7))
        assert a.sort("id_scenario").equals(b.sort("id_scenario"))

    def test_memes_id_meme_substitution(self):
        # variantes de contexte d'un même scénario (constat C1) : même DP final
        corp = pl.DataFrame({
            "id_scenario": ["v"] * 50, "diag2": ["K358"] * 50,
            "cage": ["A"] * 50, "sexe": ["1"] * 50, "duree": list(range(50)),
        })
        out, _ = substituer(corp)
        assert out["diag2"].n_unique() == 1

    def test_deux_processus_bit_a_bit(self, tmp_path):
        c, r = ecrire(tmp_path)
        outs = []
        for k in (1, 2):
            out = tmp_path / f"sortie_{k}.parquet"
            res = subprocess.run(
                [sys.executable, str(SCRIPT), str(c), "--ref", str(r), "--out", str(out)],
                capture_output=True, text=True, env={"PYTHONHASHSEED": str(k), "PATH": ""},
            )
            assert res.returncode == 0, res.stderr
            assert "Substitution des DP imprécis" in res.stdout
            outs.append(out)
        assert outs[0].read_bytes() == outs[1].read_bytes()
        assert outs[0].with_suffix(".rapport.txt").read_text() == \
            outs[1].with_suffix(".rapport.txt").read_text().replace("sortie_2", "sortie_1")


# ---------------------------------------------------------------- CLI et rapport

class TestCli:
    def test_sortie_par_defaut_et_rapport(self, tmp_path, capsys):
        c, r = ecrire(tmp_path)
        out, rapport = sdi.executer(c, r)
        assert out == tmp_path / "scenarios_T_dp.parquet" and out.is_file()
        rapport_path = tmp_path / "scenarios_T_dp.rapport.txt"
        assert rapport_path.is_file()
        texte = rapport_path.read_text(encoding="utf-8")
        assert texte == rapport.texte() + "\n"
        assert "[branche court] 2 ligne(s) — DP imprécis rencontrés : 2" in texte
        assert "[branche long] 6 ligne(s) — DP imprécis rencontrés : 5" in texte
        assert "substitués : 3 — niveau 0 (cat, cage, sexe) : 1 — niveau 1 (cat, sexe) : 1 — niveau 2 (cat, tous confondus) : 1" in texte
        assert "conservés UHCD : 1" in texte and "conservés faute de candidat précis : 1" in texte
        assert "[TOTAL] 8 ligne(s) — DP imprécis rencontrés : 7" in texte
        assert "type_unite nulle sur toute la branche court (2 lignes)" in texte
        assert "type_unite sur la branche long : valeurs ['HC', 'UHCD']" in texte
        assert "ghm2 a été groupé sur le DP d'origine" in texte
        assert "niveau (sévérité CMA) non utilisé en v1" in texte
        relu = pl.read_parquet(out)
        assert relu.height == 8 and "dp_origine" in relu.columns

    def test_main_erreurs(self, tmp_path):
        c, r = ecrire(tmp_path)
        res = subprocess.run([sys.executable, str(SCRIPT), str(tmp_path / "absent.parquet"), "--ref", str(r)],
                             capture_output=True, text=True)
        assert res.returncode == 2 and "corpus introuvable" in res.stderr
        res = subprocess.run([sys.executable, str(SCRIPT), str(c), "--ref", str(tmp_path / "absent.parquet")],
                             capture_output=True, text=True)
        assert res.returncode == 2 and "référence introuvable" in res.stderr

    def test_constat_id_scenario_non_unique(self, tmp_path):
        corp = pl.concat([corpus(), corpus()])
        _, rapport = substituer(corp)
        assert any("id_scenario non unique par ligne (8 valeurs pour 16 lignes)" in c for c in rapport.constats)


# ---------------------------------------------------------------- aval : verifier_source

class TestSchemaSourceAval:
    def test_colonnes_de_campagne_et_de_tracabilite_reconnues(self, tmp_path):
        from bench.banc import SCHEMA_SOURCE, verifier_source
        from tests.test_bench_scenarios import source_jouet
        for c in ("type_unite", "branche", "id_scenario", "cage",
                  "dp_origine", "dp_substitue", "repli_substitution"):
            assert SCHEMA_SOURCE[c].statut == "facultative"
        assert SCHEMA_SOURCE["agean"].statut == "obligatoire"
        df = source_jouet().with_columns(
            pl.lit("HC").alias("type_unite"), pl.lit("long").alias("branche"),
            pl.Series("id_scenario", [f"s-{i}" for i in range(9)]),
            pl.lit("[18-30[").alias("cage"),
            pl.col("diag2").alias("dp_origine"), pl.lit(False).alias("dp_substitue"),
            pl.lit(None, dtype=pl.Int32).alias("repli_substitution"),
        )
        p = tmp_path / "campagne_dp.parquet"
        df.write_parquet(p)
        rapport = verifier_source(p)
        assert rapport.conforme
        assert not any("supplémentaires" in s for s in rapport.signalements)
        # type inattendu détecté sur une facultative
        df.with_columns(pl.lit("non").alias("dp_substitue")).write_parquet(p)
        from bench.errors import BenchError
        with pytest.raises(BenchError, match="type inattendu : dp_substitue est String, attendu booleen"):
            verifier_source(p)

    def test_fichier_sans_ces_colonnes_toujours_conforme(self, tmp_path):
        from bench.banc import verifier_source
        from tests.test_bench_scenarios import source_jouet
        p = tmp_path / "ancien.parquet"
        source_jouet().write_parquet(p)
        assert verifier_source(p).conforme

"""Tests de bench/banc.py — orchestration du notebook (amincissement de
septembre 2026).

Sans fictomed et sans réseau : `verifier_environnement` et la branche
« génération » de `seeder` (qui appellent fictomed) sont couvertes par le
rejeu du notebook, pas ici. Tout sur `tmp_path`.
"""

from __future__ import annotations

import csv
from pathlib import Path

import polars as pl
import pytest

from bench import BenchError, scenario_dirs, seed_user_prompts
from bench.banc import (
    SCHEMA_SOURCE,
    contexte_verificateur,
    dossiers_test,
    etat_test,
    monter_jeu,
    preparer_pool,
    prompts_verificateur,
    seeder,
    verifier_source,
)
from tests.test_bench_scenarios import MODALITES_JOUET, source_jouet

# Codes que l'enrichissement (lot E1) peut ajouter — tous émissibles dans la
# bibliothèque jouet pour que le contrôle du contrat passe avec enrichir=True.
CODES_ENRICHISSEMENT = [
    "E6603", "E6604", "E6605", "E6606", "E6607", "E6690", "E6691", "E6692",
    "E6693", "E6694", "E6695", "E6696", "E6697", "E6699", "E440",
    "F17202", "F1724", "F1725", "F17241", "F101", "F102", "F1020", "F10200",
    "F10201", "F10202", "F1024", "F10240", "F10241", "F1025", "F1026",
]


def parquet_jouet(tmp_path: Path, df: pl.DataFrame | None = None,
                  nom: str = "profils.pq") -> Path:
    p = tmp_path / nom
    (source_jouet() if df is None else df).write_parquet(p)
    return p


def bibliotheque_jouet(tmp_path: Path, codes: list[str]) -> Path:
    """`referentials/cards_library/index.csv` au schéma du contrat
    (format_version 1, classe_generation emissible)."""
    lib = tmp_path / "referentials" / "cards_library"
    lib.mkdir(parents=True)
    with (lib / "index.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["code", "fichier", "statut_mco", "format_version",
                    "classe_generation"])
        # au moins une ligne : le contrat garantit format_version constant
        for c in ["A00.0", *codes]:
            w.writerow([c, f"I/{c}.md", "autorise", "1", "emissible"])
    # dictionnaire des spécialités (brut) : requis par preparer_pool (deriver_specialite)
    from tests.test_bench_scenarios import dico_jouet
    dico_jouet().write_parquet(tmp_path / "referentials" / "dictionnaire_spe_racine.parquet")
    return tmp_path / "referentials"


# ---------------------------------------------------------------------------
# verifier_source
# ---------------------------------------------------------------------------

class TestVerifierSource:
    def test_fichier_conforme(self, tmp_path, capsys):
        rapport = verifier_source(parquet_jouet(tmp_path))
        assert rapport.conforme
        assert rapport.n_lignes == 9
        assert not rapport.typologie_fournie
        # types calculés pour le rapport, un séjour par modalité
        assert rapport.types == {m: 1 for m in MODALITES_JOUET}
        out = capsys.readouterr().out
        assert out.startswith("fichier profils.pq — 9 lignes, types d'hospitalisation (calculés) : {")
        assert "colonnes OK" in out
        # nuls tolérés sur duree : signalé, pas bloquant ; « NA » et « +02 » lisibles
        assert rapport.signalements == ["duree : 1 valeur(s) nulle(s) tolérée(s)"]

    def test_chemin_relatif_depuis_la_racine_et_suffixe_devine(self, tmp_path, monkeypatch):
        import bench.banc as banc
        parquet_jouet(tmp_path)
        monkeypatch.setattr(banc, "REPO_ROOT", tmp_path)
        assert verifier_source("profils").fichier == (tmp_path / "profils.pq").resolve()

    def test_fichier_absent(self, tmp_path):
        with pytest.raises(BenchError, match="introuvable"):
            verifier_source(tmp_path / "absent.pq")

    def test_fichier_illisible(self, tmp_path):
        p = tmp_path / "faux.parquet"
        p.write_text("ceci n'est pas un parquet")
        with pytest.raises(BenchError, match="lecture parquet impossible"):
            verifier_source(p)

    def test_colonne_manquante_listee(self, tmp_path, capsys):
        p = parquet_jouet(tmp_path, source_jouet().drop("sexe"))
        with pytest.raises(BenchError, match="colonne manquante : sexe \\(obligatoire") as exc:
            verifier_source(p)
        assert "1 ÉCART(S) BLOQUANT(S)" in str(exc.value)

    def test_agean_absente_exige_cage_et_id_scenario(self, tmp_path):
        # ancien format sans agean : ni cage ni id_scenario → deux écarts, typologie non calculable
        p = parquet_jouet(tmp_path, source_jouet().drop("agean"))
        with pytest.raises(BenchError) as exc:
            verifier_source(p)
        texte = str(exc.value)
        assert "colonne manquante : id_scenario (derivation" in texte
        assert "colonne manquante : cage (derivation" in texte
        assert "typologie non calculable" in texte
        assert "2 ÉCART(S) BLOQUANT(S)" in texte
        assert "agean absente : DÉRIVÉE de cage" in texte

    def test_agean_derivee_quand_absente(self, tmp_path, capsys):
        # C1-like : pas d'agean, mais cage + id_scenario (+ pivot age) → conforme,
        # typologie calculée sur l'âge dérivé
        df = source_jouet().drop("agean").with_columns(
            pl.Series("cage", ["[50-60[", "[70-80[", "[80-[", "[40-50[", "[30-40[",
                               "[0-1[", "[18-30[", "[60-70[", "[40-50["]),
            pl.Series("id_scenario", [f"s-{i}" for i in range(9)]),
            pl.Series("age", ["ge_18"] * 5 + ["lt_18"] + ["ge_18"] * 3),
        )
        rapport = verifier_source(parquet_jouet(tmp_path, df))
        assert rapport.conforme
        assert rapport.types == {m: 1 for m in MODALITES_JOUET}
        assert any(s.startswith("agean absente : DÉRIVÉE de cage") for s in rapport.signalements)
        assert not any("supplémentaires" in s for s in rapport.signalements)
        # libellé de classe illisible : écart explicite
        df.with_columns(pl.lit("80+").alias("cage")).write_parquet(tmp_path / "b.pq")
        with pytest.raises(BenchError, match="forme illisible : cage"):
            verifier_source(tmp_path / "b.pq")

    def test_ancien_format_avec_agean_toujours_conforme(self, tmp_path):
        # agean fournie : cage et id_scenario ne sont pas exigées
        rapport = verifier_source(parquet_jouet(tmp_path))
        assert rapport.conforme and not any("agean" in s for s in rapport.signalements)

    def test_colonne_typologie_facultative_si_typologie_fournie(self, tmp_path):
        df = source_jouet().drop("ghm2", "racine").with_columns(
            pl.Series("DPEC", MODALITES_JOUET),
            pl.Series("TPEC", ["Médecine"] * 9),
        )
        # sans ghm2 NI racine : non conforme (racine réparable seulement depuis ghm2)
        with pytest.raises(BenchError, match="colonne manquante : racine \\(reparable"):
            verifier_source(parquet_jouet(tmp_path, df))
        rapport = verifier_source(parquet_jouet(tmp_path, df.with_columns(pl.lit("01C03").alias("racine")), "r.pq"))
        assert rapport.conforme and rapport.typologie_fournie
        # mais obligatoire sans typologie
        with pytest.raises(BenchError, match="colonne manquante : ghm2 \\(typologie"):
            verifier_source(parquet_jouet(tmp_path, source_jouet().drop("ghm2"), "b.pq"))

    def test_sexe_mal_encode(self, tmp_path):
        df = source_jouet().with_columns(pl.Series("sexe", ["M", "F"] * 4 + ["M"]))
        with pytest.raises(BenchError, match=r"encodage inconnu : sexe vaut \['F', 'M'\], attendu \['1', '2'\]"):
            verifier_source(parquet_jouet(tmp_path, df))

    def test_sexe_entier_admis(self, tmp_path):
        df = source_jouet().with_columns(pl.col("sexe").cast(pl.Int32))
        assert verifier_source(parquet_jouet(tmp_path, df)).conforme

    def test_mode_hospit_inconnu(self, tmp_path):
        df = source_jouet().with_columns(pl.lit("AMBU").alias("mode_hospit"))
        with pytest.raises(BenchError, match="encodage inconnu : mode_hospit vaut \\['AMBU'\\]"):
            verifier_source(parquet_jouet(tmp_path, df))

    def test_type_inattendu(self, tmp_path):
        df = source_jouet().with_columns(pl.col("agean").cast(pl.String))
        with pytest.raises(BenchError, match="type inattendu : agean est String, attendu numerique"):
            verifier_source(parquet_jouet(tmp_path, df))

    def test_codes_pointes_illisibles(self, tmp_path):
        df = source_jouet().with_columns(
            pl.Series("diagnostic_associes", ["C50.0 Z92.3"] + [""] * 8))
        with pytest.raises(BenchError, match="forme illisible : diagnostic_associes — 1 valeur"):
            verifier_source(parquet_jouet(tmp_path, df))

    def test_nuls_interdits_sur_le_dp(self, tmp_path):
        df = source_jouet().with_columns(
            pl.when(pl.col("diag2") == "R51").then(None).otherwise(pl.col("diag2")).alias("diag2"))
        with pytest.raises(BenchError, match="valeurs nulles : diag2 \\(1 ligne"):
            verifier_source(parquet_jouet(tmp_path, df))

    def test_modalite_nouvelle_signalee_sans_echec(self, tmp_path, capsys):
        modalites = MODALITES_JOUET[:-1] + ["Soins palliatifs"]
        df = source_jouet().with_columns(
            pl.Series("DPEC", modalites), pl.Series("TPEC", ["Médecine"] * 9))
        rapport = verifier_source(parquet_jouet(tmp_path, df))
        assert rapport.conforme and rapport.typologie_fournie
        assert rapport.types["Soins palliatifs"] == 1
        assert any("Soins palliatifs" in s and "nouvelles" in s for s in rapport.signalements)
        out = capsys.readouterr().out
        assert "types d'hospitalisation (fournis)" in out and "signalé : modalités de DPEC inconnues" in out

    def test_colonnes_supplementaires_signalees(self, tmp_path):
        df = source_jouet().with_columns(pl.lit("C1").alias("campagne"))
        rapport = verifier_source(parquet_jouet(tmp_path, df))
        assert rapport.conforme
        assert "colonnes supplémentaires hors schéma (ignorées) : ['campagne']" in rapport.signalements

    def test_schema_documente(self):
        for col, ex in SCHEMA_SOURCE.items():
            assert ex.statut in ("obligatoire", "typologie", "derivee", "derivation", "reparable", "facultative"), col
            assert ex.role, col
        assert SCHEMA_SOURCE["agean"].statut == "derivee"
        assert SCHEMA_SOURCE["cage"].statut == SCHEMA_SOURCE["id_scenario"].statut == "derivation"
        assert SCHEMA_SOURCE["racine"].statut == "reparable"

    def test_racine_reparable(self, tmp_path):
        # racine nulle → signalée, réparée ; racine absente avec ghm2 → signalée ; ni l'une ni l'autre → écart
        df = source_jouet().with_columns(pl.lit(None, dtype=pl.String).alias("racine"))
        rapport = verifier_source(parquet_jouet(tmp_path, df))
        assert rapport.conforme and any("réparées depuis ghm2[:5]" in s for s in rapport.signalements)
        assert rapport.types == {m: 1 for m in MODALITES_JOUET}  # typologie calculée sur la racine réparée
        rapport = verifier_source(parquet_jouet(tmp_path, source_jouet().drop("racine"), "b.pq"))
        assert rapport.conforme and any(s.startswith("racine absente : réparée") for s in rapport.signalements)
        with pytest.raises(BenchError, match="colonne manquante : racine \\(reparable"):
            verifier_source(parquet_jouet(tmp_path, source_jouet().drop("racine", "ghm2"), "c.pq"))


# ---------------------------------------------------------------------------
# preparer_pool
# ---------------------------------------------------------------------------

class TestPreparerPool:
    def test_couverture_un_par_type_apres_filtre_dp(self, tmp_path, capsys):
        p = parquet_jouet(tmp_path)
        ref = bibliotheque_jouet(tmp_path, ["K35.8", "O04.8", "J18.8", "I10"])
        pool = preparer_pool(p, "couverture", 1, enrichir=False, referentials=ref)
        # DP en 8 : J188, K358, O048, I208 → 4 strates, 1 séjour chacune
        assert pool.height == 4
        assert pool.group_by("DPEC").len()["len"].to_list() == [1] * 4
        assert {"source_row_id", "source_scenario_id", "TPEC", "DPEC"} <= set(pool.columns)
        assert pool["source_row_id"].sort().to_list() == [2, 3, 4, 7]  # ids du parquet complet
        out = capsys.readouterr().out
        assert "colonnes OK" in out
        assert "Filtre DP terminant par 8 : 9 -> 4 séjours" in out
        assert "Couverture : 1 séjour par modalité de DPEC présente (4 modalité(s))." in out
        assert "ENRICHIR_SCENARIOS = False — pool candidat inchangé." in out
        # codes sans fiche journalisés, jamais ignorés (I208, E119, F172, Z640
        # absents ; le jeton « NA » d'un DAS est journalisé lui aussi —
        # comportement de la cellule d'origine, conservé)
        assert "sans fiche à l'index — JOURNAL : ['E119', 'F172', 'I208', 'NA', 'Z640']" in out
        assert "Pool candidat : 4 séjours — agean lu du fichier — racine réparée sur 0 ligne(s) — couverture par type :" in out

    def test_quotas_dict_et_sans_filtre(self, tmp_path):
        p = parquet_jouet(tmp_path)
        ref = bibliotheque_jouet(tmp_path, [])
        pool = preparer_pool(p, {"Séances simples": 1, "IVG": 1}, 42,
                             enrichir=False, filtre_dp_suffixe=None, referentials=ref)
        assert pool["DPEC"].to_list() == ["Séances simples", "IVG"]

    def test_tirage_simple_target_n(self, tmp_path, capsys):
        p = parquet_jouet(tmp_path)
        ref = bibliotheque_jouet(tmp_path, [])
        pool = preparer_pool(p, None, 5, enrichir=False, filtre_dp_suffixe=None,
                             target_n=3, referentials=ref)
        assert pool.height == 3
        assert "Tirage simple : 3 séjours (seed=5)." in capsys.readouterr().out
        with pytest.raises(BenchError, match="préciser target_n"):
            preparer_pool(p, None, 5, enrichir=False, referentials=ref)

    def test_quotas_vides_refuses(self, tmp_path):
        with pytest.raises(BenchError, match="QUOTAS vide — à renseigner"):
            preparer_pool(parquet_jouet(tmp_path), {}, 1, enrichir=False,
                          referentials=bibliotheque_jouet(tmp_path, []))

    def test_typologie_fournie_conservee(self, tmp_path, capsys):
        df = source_jouet().with_columns(
            pl.Series("DPEC", ["X"] * 9), pl.Series("TPEC", ["TX"] * 9))
        pool = preparer_pool(parquet_jouet(tmp_path, df), "couverture", 1,
                             enrichir=False, filtre_dp_suffixe=None,
                             referentials=bibliotheque_jouet(tmp_path, []))
        assert pool["DPEC"].to_list() == ["X"]
        assert "Typologie TPEC/DPEC fournie par le fichier — conservée telle quelle." \
            in capsys.readouterr().out

    def test_source_non_conforme_arrete_avant_le_tirage(self, tmp_path):
        p = parquet_jouet(tmp_path, source_jouet().drop("sexe"))
        with pytest.raises(BenchError, match="colonne manquante : sexe"):
            preparer_pool(p, "couverture", 1, enrichir=False,
                          referentials=bibliotheque_jouet(tmp_path, []))

    def test_enrichissement_et_contrat(self, tmp_path, capsys):
        p = parquet_jouet(tmp_path)
        ref = bibliotheque_jouet(tmp_path, CODES_ENRICHISSEMENT)
        pool = preparer_pool(p, "couverture", 42, enrichir=True, filtre_dp_suffixe=None,
                             referentials=ref)
        assert pool.height == 9 and "enrichi" in pool.columns
        out = capsys.readouterr().out
        assert "Enrichissement : " in out and "ligne(s) enrichie(s)" in out
        # codes ajoutés (s'il y en a) vérifiés émissibles ; codes du pool sans
        # fiche journalisés
        assert "sans fiche à l'index — JOURNAL :" in out
        if "codes_ajoutes" in pool.columns and pool["codes_ajoutes"].drop_nulls().len():
            assert "tous émissibles." in out

    def test_agean_derive_dans_le_recap(self, tmp_path, capsys):
        df = source_jouet().drop("agean").with_columns(
            pl.Series("cage", ["[50-60[", "[70-80[", "[80-[", "[40-50[", "[30-40[",
                               "[0-1[", "[18-30[", "[60-70[", "[40-50["]),
            pl.Series("id_scenario", [f"s-{i}" for i in range(9)]),
        )
        pool = preparer_pool(parquet_jouet(tmp_path, df), "couverture", 1, enrichir=False,
                             filtre_dp_suffixe=None, referentials=bibliotheque_jouet(tmp_path, []))
        assert "agean" in pool.columns and pool["agean"].null_count() == 0
        out = capsys.readouterr().out
        # source_jouet porte la colonne pivot `age` (ge_18 / lt_18)
        assert "agean : dérivé de cage, pivot age — 9/9 lignes" in out
        assert "Pool candidat : 9 séjours — agean dérivé de cage, pivot age — racine réparée sur 0 ligne(s) — couverture par type :" in out
        # typologie calculée sur l'âge dérivé : une modalité par ligne
        assert pool["DPEC"].n_unique() == 9

    def test_agean_lu_du_fichier_dans_le_recap(self, tmp_path, capsys):
        preparer_pool(parquet_jouet(tmp_path), "couverture", 1, enrichir=False,
                      filtre_dp_suffixe=None, referentials=bibliotheque_jouet(tmp_path, []))
        out = capsys.readouterr().out
        assert "agean : lu du fichier (9 lignes) — conservée telle quelle." in out
        assert "Pool candidat : 9 séjours — agean lu du fichier — racine réparée sur 0 ligne(s) — couverture par type :" in out

    def test_specialite_attribuee_et_recap(self, tmp_path, capsys):
        # racines du jouet : 06C12 / 28Z07 … absentes du dictionnaire jouet → repli ;
        # on force deux racines connues pour voir « unique » et « observee »
        df = source_jouet().with_columns(
            pl.Series("racine", ["01C03", "28Z04", "04M10", "01C05", "14Z08", "15M05", "23M20", "05K10", "90Z00"]),
            pl.Series("type_unite", [None, None, None, None, None, "NEONAT", None, None, None]),
        )
        ref = bibliotheque_jouet(tmp_path, [])
        (ref / "mapping_type_unite.yaml").write_text(
            "entrees:\n  NEONAT: {specialite: NEONATOLOGIE, statut: valide}\n"
            "  HC: {specialite: DERIVER, statut: proposition}\n", encoding="utf-8")
        pool = preparer_pool(parquet_jouet(tmp_path, df), "couverture", 1, enrichir=False,
                             filtre_dp_suffixe=None, referentials=ref)
        assert {"specialty", "specialite_source", "racine_reparee"} <= set(pool.columns)
        par = dict(pool.group_by("specialite_source").len().iter_rows())
        assert par["observee"] == 1 and par["unique"] == 1 and par["tiree"] >= 1 and par["repli"] >= 1
        assert pool.filter(pl.col("type_unite") == "NEONAT")["specialty"][0] == "NEONATOLOGIE"
        out = capsys.readouterr().out
        assert "racine : 0/9 réparée(s) depuis ghm2[:5]" in out
        assert "spécialité : observee 1, unique 1, tiree" in out
        assert "mapping type_unite : 1 entrée(s) valide(s) appliquée(s)" in out
        assert "racine réparée sur 0 ligne(s)" in out

    def test_racine_reparee_dans_le_pool(self, tmp_path, capsys):
        df = source_jouet().with_columns(pl.lit(None, dtype=pl.String).alias("racine"))
        pool = preparer_pool(parquet_jouet(tmp_path, df), "couverture", 1, enrichir=False,
                             filtre_dp_suffixe=None, referentials=bibliotheque_jouet(tmp_path, []))
        assert pool["racine_reparee"].all() and pool["racine"].null_count() == 0
        out = capsys.readouterr().out
        assert "racine : 9/9 réparée(s) depuis ghm2[:5]" in out
        assert "racine réparée sur 9 ligne(s)" in out

    def test_dictionnaire_absent_refus_explicite_et_specialite_false(self, tmp_path, capsys):
        ref = bibliotheque_jouet(tmp_path, [])
        (ref / "dictionnaire_spe_racine.parquet").unlink()
        with pytest.raises(BenchError, match="dictionnaire des spécialités absent"):
            preparer_pool(parquet_jouet(tmp_path), "couverture", 1, enrichir=False,
                          filtre_dp_suffixe=None, referentials=ref)
        pool = preparer_pool(parquet_jouet(tmp_path), "couverture", 1, enrichir=False,
                             filtre_dp_suffixe=None, referentials=ref, specialite=False)
        assert "specialty" not in pool.columns
        assert "specialite=False" in capsys.readouterr().out

    def test_bibliotheque_hors_contrat_refusee(self, tmp_path):
        from tests.test_bench_scenarios import dico_jouet
        (tmp_path / "referentials" / "cards_library").mkdir(parents=True)
        dico_jouet().write_parquet(tmp_path / "referentials" / "dictionnaire_spe_racine.parquet")
        with pytest.raises(BenchError, match="index.csv absent"):
            preparer_pool(parquet_jouet(tmp_path), "couverture", 1, enrichir=False,
                          referentials=tmp_path / "referentials")


# ---------------------------------------------------------------------------
# Test courant — chemins, état, montage, seeding, prompts, contexte
# ---------------------------------------------------------------------------

def graine() -> pl.DataFrame:
    return pl.DataFrame({
        "generation_id": ["id-0", "id-1"],
        "template_name": ["medical_outpatient.txt", "surgery_inpatient.txt"],
        "user_prompt": ["Cas médical.", "Cas chirurgical."],
        "prefix": ["PREFIXE", None],
    })


def jeu(td: Path) -> Path:
    system_dir = td / "system" / "one_gen"
    system_dir.mkdir(parents=True)
    (system_dir / "medical_outpatient.txt").write_text("SYSTÈME MÉDECINE")
    (system_dir / "surgery_inpatient.txt").write_text("SYSTÈME CHIRURGIE")
    return system_dir


class TestDossiersTest:
    def test_chemins(self, tmp_path):
        td, prev = dossiers_test("07", "06", tests_dir=tmp_path)
        assert td == tmp_path / "07" and prev == tmp_path / "06"
        assert dossiers_test("01", None, tests_dir=tmp_path)[1] is None


class TestEtatTest:
    def test_test_a_creer(self, tmp_path, capsys):
        etat_test(tmp_path / "07", tmp_path / "06")
        out = capsys.readouterr().out
        assert "Test courant : " in out and "(à créer)" in out
        assert f"Jeu amont    : {tmp_path / '06' / 'system' / 'one_gen'}" in out
        assert "— à créer" in out
        assert "Jeu system/one_gen : absent" in out
        assert "Dossiers scénario  : 0 []" in out
        assert "Figement" not in out

    def test_premier_test_sans_amont(self, tmp_path, capsys):
        etat_test(tmp_path / "01", None)
        assert "premier test d'une topologie : jeu initial à fournir à la main" \
            in capsys.readouterr().out

    def test_test_seede_et_fige(self, tmp_path, capsys):
        td = tmp_path / "07"
        seed_user_prompts(td, graine())
        jeu(td)
        etat_test(td)  # sans prev_td : pas de ligne « Jeu amont »
        out = capsys.readouterr().out
        assert "Jeu amont" not in out
        assert "— présent" in out and "Jeu system/one_gen : présent" in out
        assert "Dossiers scénario  : 2 ['0000', '0001']" in out
        assert "Figement (1er dossier, prompt_system_one_gen.txt) : absent" in out


class TestMonterJeu:
    def test_monte_depuis_le_test_precedent(self, tmp_path, capsys):
        prev = tmp_path / "06"
        jeu(prev)
        td = tmp_path / "07"
        monter_jeu(td, prev)
        assert (td / "system" / "one_gen" / "medical_outpatient.txt").read_text() \
            == "SYSTÈME MÉDECINE"
        assert "MONTÉ :" in capsys.readouterr().out
        monter_jeu(td, prev)
        assert "SKIP — jeu déjà monté :" in capsys.readouterr().out

    def test_premier_test_refuse(self, tmp_path):
        with pytest.raises(RuntimeError, match="premier test d'une topologie"):
            monter_jeu(tmp_path / "01", None)


class TestSeeder:
    def test_refus_de_re_seeding_puis_figement(self, tmp_path, capsys):
        td = tmp_path / "07"
        seed_user_prompts(td, graine())
        jeu(td)
        pool = source_jouet().with_columns(pl.lit(True).alias("enrichi"))
        assert seeder(td, pool, source_path=tmp_path / "profils.pq") is None
        out = capsys.readouterr().out
        assert "SKIP — test déjà seedé : 2 dossiers scénario." in out
        assert "(pas d'archive du tirage :" in out
        assert "Scénarios servis : ['0000', '0001']" in out
        assert (td / "0000" / "prompt_system_one_gen.txt").read_text() == "SYSTÈME MÉDECINE"
        # re-run : tout skippe
        seeder(td, None, source_path=tmp_path / "profils.pq")
        out = capsys.readouterr().out
        assert "SKIP — test déjà seedé" in out
        assert "SKIP — prompt_system_one_gen.txt déjà figé dans tous les dossiers." in out

    def test_archive_du_tirage_affichee(self, tmp_path, capsys):
        td = tmp_path / "07"
        seed_user_prompts(td, graine())
        jeu(td)
        (td / ".fictomed").mkdir()
        pl.DataFrame({"generation_id": ["id-0", "id-1"], "DPEC": ["A", "B"],
                      "autre": [1, 2]}).write_parquet(
            td / ".fictomed" / "scenarios_fictomed_selected.parquet")
        seeder(td, None, source_path=tmp_path / "profils.pq")
        out = capsys.readouterr().out
        assert "generation_id" in out and "DPEC" in out and "autre" not in out

    def test_pas_de_pool(self, tmp_path, capsys):
        td = tmp_path / "07"
        assert seeder(td, None, source_path=tmp_path / "profils.pq") is None
        assert "Pas de pool candidat en mémoire — exécuter le tirage stratifié" \
            in capsys.readouterr().out
        assert not td.exists()

    def test_pool_non_enrichi_refuse_avant_fictomed(self, tmp_path):
        td = tmp_path / "07"
        with pytest.raises(RuntimeError, match="Pool candidat non enrichi"):
            seeder(td, source_jouet(), source_path=tmp_path / "profils.pq")
        assert not (td / ".fictomed").exists()

    def test_figement_seul_quand_seede_sans_jeu(self, tmp_path):
        td = tmp_path / "07"
        seed_user_prompts(td, graine())
        with pytest.raises(BenchError, match="Jeu de templates absent"):
            seeder(td, None, source_path=tmp_path / "profils.pq")


class TestPromptsVerificateur:
    def test_pose_une_fois(self, tmp_path, capsys):
        td = tmp_path / "07"
        seed_user_prompts(td, graine())
        prompts_verificateur(td, "SYS VERIF", "USER VERIF")
        assert (td / "0001" / "prompt_system_verif.txt").read_text() == "SYS VERIF"
        assert (td / "0000" / "user_verification.txt").read_text() == "USER VERIF"
        out = capsys.readouterr().out
        assert "prompt_system_verif.txt : ['0000', '0001']" in out
        prompts_verificateur(td, "SYS VERIF", "USER VERIF")
        out = capsys.readouterr().out
        assert "SKIP — prompt_system_verif.txt déjà présent dans tous les dossiers." in out
        assert "SKIP — user_verification.txt déjà présent dans tous les dossiers." in out

    def test_sans_dossiers(self, tmp_path, capsys):
        td = tmp_path / "07"
        td.mkdir()
        prompts_verificateur(td, "S", "U")
        assert "Pas de dossiers scénario — seeder d'abord (3.1a)." in capsys.readouterr().out
        assert scenario_dirs(td) == []


class TestContexteVerificateur:
    def test_placeholder_sans_cr(self, tmp_path, capsys):
        td = tmp_path / "07"
        seed_user_prompts(td, graine())
        ctx = contexte_verificateur(td, "crh_generation.txt")
        assert ctx["scenario"].to_list() == ["0000", "0001"]
        assert ctx["report"][0] == "[CR généré — placeholder de contrôle à sec]"
        assert "Pas de crh_generation.txt sur disque : contexte placeholder." \
            in capsys.readouterr().out

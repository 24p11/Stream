"""Tests du package d'enrichissement (work_prompts/enrichissement).

Sans fictomed en exécution, sans réseau : les fixtures reproduisent le schéma
relevé dans fictomed (sites/aphp) —

- profils (avant ``build_scenario``) : ``icd_primary_code`` str compact,
  ``icd_secondary_code`` chaîne de codes compacts séparés par des espaces,
  ``age2`` int, ``sexe`` int PMSI (1/2) ;
- scénarios construits : idem avec ``icd_secondary_code`` liste de codes et
  ``age`` int ;
- user prompt : bloc « **SCÉNARIO DE DÉPART :** » de ``prompt.make_user_prompt``.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import polars as pl
import pytest

from work_prompts.enrichissement import (
    Politique,
    bloc_contexte,
    enrichir_scenarios,
)
from work_prompts.enrichissement.integration_stream import user_fn_enrichi

REPO = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# Fixtures — schéma fictomed
# ---------------------------------------------------------------------------

def profils() -> pl.DataFrame:
    """Schéma « profils » : DAS en chaîne espace-séparée, âge dans age2."""
    return pl.DataFrame({
        "icd_primary_code": ["E1120", "I210", "K703", "F1124", "J441",
                             "O800", "Z940", "T862", "C509", "R53"],
        "icd_secondary_code": ["N083 I10", "", "F1025", "B182", "E6605",
                               "Z370", "I10", "N185", "", ""],
        "age2": [62, 55, 51, 34, 66, 31, 58, 47, 15, 44],
        "sexe": [1, 2, 1, 1, 2, 2, 1, 2, 2, 1],
    })


def scenarios_listes() -> pl.DataFrame:
    """Schéma « scénario construit » : DAS en liste, âge dans age."""
    return pl.DataFrame({
        "icd_primary_code": ["E1120", "I210"],
        "icd_secondary_code": [["N083", "I10"], []],
        "age": [62, 55],
        "sexe": [1, 2],
    })


USER_PROMPT = (
    "**SCÉNARIO DE DÉPART :**\n"
    "- Âge du patient : 62 ans\n"
    "- Sexe du patient : Masculin\n"
    "- Date d'entrée : 12/03/2025\n"
    "- Codage CIM10 :\n"
    "   * Diagnostic principal : Diabète sucré de type 2 (E1120)\n"
)


# ---------------------------------------------------------------------------
# Déterminisme
# ---------------------------------------------------------------------------

def test_determinisme_a_seed_fixe():
    df = profils()
    a = enrichir_scenarios(df, seed=42)
    b = enrichir_scenarios(df, seed=42)
    assert a.equals(b)
    c = enrichir_scenarios(df, seed=43)
    assert not a.equals(c)   # la graine agit


# ---------------------------------------------------------------------------
# Codes ajoutés : DAS seulement, format natif
# ---------------------------------------------------------------------------

def test_codes_en_das_jamais_dp_ni_doublon_format_compact():
    out = enrichir_scenarios(profils(), seed=7)
    for r in out.iter_rows(named=True):
        assert r["icd_primary_code"] == profils()["icd_primary_code"][out.get_column("icd_primary_code").to_list().index(r["icd_primary_code"])]  # DP inchangé
        das = (r["icd_secondary_code"] or "").split()
        assert len(das) == len(set(das)), "DAS dupliqué"
        ajoutes = (r["codes_ajoutes"] or "").split()
        for c in ajoutes:
            assert c in das, "code ajouté absent du DAS"
            assert c != r["icd_primary_code"], "code ajouté égal au DP"
            assert "." not in c, "format compact attendu (sans point)"


def test_dp_colonne_inchangee():
    df = profils()
    out = enrichir_scenarios(df, seed=7)
    assert out["icd_primary_code"].to_list() == df["icd_primary_code"].to_list()


def test_das_liste_reste_liste():
    out = enrichir_scenarios(scenarios_listes(), seed=3)
    assert out.schema["icd_secondary_code"] == pl.List(pl.Utf8)
    das = out["icd_secondary_code"][0].to_list()
    assert das[:2] == ["N083", "I10"]   # codes d'origine préservés, en tête


# ---------------------------------------------------------------------------
# Politique
# ---------------------------------------------------------------------------

def _ligne(out: pl.DataFrame, dp: str) -> dict:
    return out.filter(pl.col("icd_primary_code") == dp).row(0, named=True)


def test_politique_exclusions_intactes():
    df = profils()
    out = enrichir_scenarios(df, seed=42)
    for dp in ("O800", "Z940", "T862", "C509"):   # grossesse, greffés, mineure (15 ans)
        r = _ligne(out, dp)
        assert r["enrichi"] is False
        assert r["taille_cm"] is None and r["codes_ajoutes"] is None
        origine = df.filter(pl.col("icd_primary_code") == dp)["icd_secondary_code"][0]
        assert r["icd_secondary_code"] == origine, "ligne exclue modifiée"


def test_politique_mineur_intact():
    out = enrichir_scenarios(profils(), seed=42)
    assert _ligne(out, "C509")["enrichi"] is False   # 15 ans < age_min=18


def test_scenario_dnid_corpulence_decalee():
    # E11* impose la répartition DNID : sur 400 tirages, la part d'obésité
    # doit approcher 41 % (contre ~17 % en population générale).
    df = pl.DataFrame({
        "icd_primary_code": ["E1120"] * 400,
        "icd_secondary_code": [""] * 400,
        "age2": [62] * 400,
        "sexe": [1] * 400,
    })
    out = enrichir_scenarios(df, seed=42)
    part_obesite = (out["classe_imc"] == "obesite").mean()
    assert 0.30 < part_obesite < 0.52, f"part obésité DNID {part_obesite:.2f}"


def test_scenario_e6605_impose_imc():
    df = pl.DataFrame({
        "icd_primary_code": ["J441"] * 50,
        "icd_secondary_code": ["E6605"] * 50,
        "age2": [66] * 50,
        "sexe": [2] * 50,
    })
    out = enrichir_scenarios(df, seed=1)
    assert out["imc"].min() >= 35.0 and out["imc"].max() < 40.0
    assert all((c or "") == "" or "E66" not in c for c in out["codes_ajoutes"]), \
        "E66 déjà présent : rien à ajouter"


# ---------------------------------------------------------------------------
# Surpoids jamais codé ; obésité tirée -> code en DAS
# ---------------------------------------------------------------------------

def test_scenario_e6693_surpoids_impose_imc_das_inchange():
    # Codes « sans précision » E669x présents dans data/aphp : E6693 est un
    # surpoids -> IMC dans [25,30[, aucun code ajouté, DAS strictement
    # inchangé (intoxications neutralisées pour isoler l'anthropométrie).
    sans_intox = Politique(p_tabac=0.0, p_alcool=0.0,
                           p_tabac_poly=0.0, p_alcool_poly=0.0)
    df = pl.DataFrame({
        "icd_primary_code": ["I10"] * 50,
        "icd_secondary_code": ["E6693 N185"] * 50,
        "age2": [58] * 50,
        "sexe": [1] * 50,
    })
    out = enrichir_scenarios(df, seed=9, politique=sans_intox)
    assert out["imc"].min() >= 25.0 and out["imc"].max() < 30.0
    assert out["icd_secondary_code"].to_list() == ["E6693 N185"] * 50, "DAS modifié"
    assert all(not v for v in out["codes_ajoutes"].to_list()), "code ajouté"


def test_serie_e669x_obesites_sans_precision():
    sans_intox = Politique(p_tabac=0.0, p_alcool=0.0,
                           p_tabac_poly=0.0, p_alcool_poly=0.0)
    bornes = {"E6694": (30.0, 35.0), "E6697": (50.0, 60.0), "E6699": (30.0, 50.0)}
    for code, (lo, hi) in bornes.items():
        df = pl.DataFrame({
            "icd_primary_code": ["I10"] * 30,
            "icd_secondary_code": [code] * 30,
            "age2": [58] * 30,
            "sexe": [2] * 30,
        })
        out = enrichir_scenarios(df, seed=4, politique=sans_intox)
        assert out["imc"].min() >= lo and out["imc"].max() < hi, code
        assert all(not v for v in out["codes_ajoutes"].to_list()), code


def test_codage_systematique_selon_classe():
    # Doctrine révisée (RF) : toute classe tirée à IMC >= 25 est codée en
    # DAS — E6603 pour le surpoids, E6604-E6607 pour l'obésité ; corpulence
    # normale -> aucun ajout.
    sans_intox = Politique(p_tabac=0.0, p_alcool=0.0,
                           p_tabac_poly=0.0, p_alcool_poly=0.0)
    df = pl.DataFrame({
        "icd_primary_code": ["I10"] * 600,
        "icd_secondary_code": [""] * 600,
        "age2": [60] * 600,
        "sexe": [1] * 600,
    })
    out = enrichir_scenarios(df, seed=5, politique=sans_intox)
    bornes = {"E6603": (25.0, 30.0), "E6604": (30.0, 35.0), "E6605": (35.0, 40.0),
              "E6606": (40.0, 50.0), "E6607": (50.0, 60.0)}
    vus = set()
    for r in out.iter_rows(named=True):
        ajoutes = (r["codes_ajoutes"] or "").split()
        if r["imc"] < 25.0:
            assert not ajoutes, "corpulence normale codée"
        else:
            assert len(ajoutes) == 1, f"un seul code attendu ({ajoutes})"
            code = ajoutes[0]
            lo, hi = bornes[code]
            assert lo <= r["imc"] < hi, f"{code} hors bornes (IMC {r['imc']})"
            assert code in r["icd_secondary_code"].split()
            vus.add(code)
    assert "E6603" in vus, "surpoids tiré jamais codé E6603"
    assert vus & {"E6604", "E6605", "E6606"}, "aucune obésité codée"


# ---------------------------------------------------------------------------
# bloc_contexte et user_fn_enrichi
# ---------------------------------------------------------------------------

def test_bloc_contexte_contenu_et_style():
    out = enrichir_scenarios(profils(), seed=42)
    r = _ligne(out, "E1120")
    bloc = bloc_contexte(r)
    lignes = bloc.splitlines()
    assert lignes[0].startswith("- Taille : ") and lignes[0].endswith(" cm")
    assert lignes[1].startswith("- Poids : ") and "(IMC " in lignes[1]
    assert "," in lignes[1].split("IMC ")[1], "IMC en notation française"
    assert lignes[2].startswith("- Tabac : ")
    assert lignes[3].startswith("- Alcool : ")
    assert bloc.endswith("\n")
    assert bloc_contexte(_ligne(out, "O800")) == ""   # exclue -> vide


def test_user_fn_enrichi_insertion_idempotence_noop():
    out = enrichir_scenarios(profils(), seed=42)
    r = dict(_ligne(out, "E1120"))
    r["user_prompt"] = USER_PROMPT
    fn = user_fn_enrichi()

    une_fois = fn(r)
    lignes = une_fois.splitlines()
    i_sexe = next(i for i, l in enumerate(lignes) if l.startswith("- Sexe du patient"))
    assert lignes[i_sexe + 1].startswith("- Taille : "), "bloc pas inséré après Sexe"
    assert lignes[i_sexe + 5].startswith("- Date d'entrée"), "suite du prompt déplacée"

    r2 = dict(r); r2["user_prompt"] = une_fois
    assert fn(r2) == une_fois, "pas idempotent"

    r3 = dict(_ligne(out, "O800")); r3["user_prompt"] = USER_PROMPT
    assert fn(r3) == USER_PROMPT, "no-op attendu pour une ligne non enrichie"


# ---------------------------------------------------------------------------
# Auto-contrôles épidémiologiques des modules
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("module", [
    "work_prompts.enrichissement.intoxications",
    "work_prompts.enrichissement.anthropometrie",
    "work_prompts.enrichissement.enrichissement",
])
def test_auto_controles_modules(module):
    proc = subprocess.run([sys.executable, "-m", module], cwd=REPO,
                          capture_output=True, text=True, timeout=300)
    assert proc.returncode == 0, proc.stderr[-800:]

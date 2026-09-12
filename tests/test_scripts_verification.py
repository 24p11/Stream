"""Tests des maillons Python de la chaîne de vérification-régénération
(scripts/) : complétude du codage et rapport --json de check_crh, nettoyage
d'export (nettoie_dictionnaire), contrat d'E/S du juge d'équivalence
(juge_io), préparation de la régénération (prepare_regeneration).

Sans réseau. Les fixtures reproduisent le format réel de
work_prompts/tests/06 : bloc « Codage CIM10 » (codes compacts), fiches
<fiche_code> (codes pointés), sortie {"CR", "formulations"} avec clés de
diagnostics à habillage variable (« Libellé (N85.8) », « Libellé (N328) »).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import check_crh  # noqa: E402
import juge_io  # noqa: E402
import nettoie_dictionnaire  # noqa: E402

from bench.errors import BenchError  # noqa: E402


# ---------------------------------------------------------------- fixtures

def _fiche(code_affiche: str, libelle: str, entites: list[str],
           alternatives: list[str] = []) -> str:
    puces = "\n".join(f"- {e}" for e in entites)
    alts = "\n".join(f"- {a}" for a in alternatives)
    return f"""<fiche_code code="{code_affiche}">

# {code_affiche} — {libelle}

## Position dans la classification
- Chapitre X : fixture

## Périmètre clinique du code

Au niveau du code :
{puces}

## À ne pas décrire

Affections relevant d'autres codes :

- entité interdite d'une autre catégorie (X99)

## Formulations cliniques alternatives
{alts}

</fiche_code>"""


def _user_generation(dp: tuple[str, str], das: list[tuple[str, str]] = [],
                     fiches: list[str] = [],
                     poids_taille: tuple[int, int] | None = None) -> str:
    lignes = [
        "**SCÉNARIO DE DÉPART :**",
        "- Âge du patient : 42 ans",
        "- Sexe du patient : Féminin",
    ]
    if poids_taille:
        lignes += [f"- Taille : {poids_taille[1]} cm",
                   f"- Poids : {poids_taille[0]} kg"]
    lignes += [
        "- Codage CIM10 :",
        f"   * Diagnostic principal : {dp[1]} ({dp[0]})",
        "   * Diagnostics associés :",
    ]
    for code, libelle in das:
        lignes.append(f"      - {libelle} ({code})")
    lignes += [
        "- Acte CCAM : geste de fixture (ABCD001)",
        "- Service : FIXTURE",
    ]
    texte = "\n".join(lignes)
    if fiches:
        texte += ("\n\n**FICHES DESCRIPTIVES DES CODES CIM-10 DU SCÉNARIO :**"
                  "\n\n" + "\n\n".join(fiches))
    return texte + "\n"


INFOS_COMPLETES = {k: [] for k in check_crh.EXPECTED_INFO_KEYS}


def _crh(cr: str, diagnostics: dict,
         informations: dict | None = None) -> str:
    return json.dumps(
        {"CR": cr, "formulations": {
            "diagnostics": diagnostics,
            "informations": (dict(INFOS_COMPLETES) if informations is None
                             else informations)}},
        ensure_ascii=False)


def _scenario(test_dir: Path, nom: str, user_txt: str, crh_txt: str | None,
              template: str = "medical_outpatient") -> Path:
    d = test_dir / nom
    d.mkdir(parents=True)
    (d / "user_generation.txt").write_text(user_txt, encoding="utf-8")
    (d / "template.txt").write_text(template, encoding="utf-8")
    if crh_txt is not None:
        (d / "crh_generation.txt").write_text(crh_txt, encoding="utf-8")
    return d


CR_UTERUS = ("En-tête. Le patient présente une atrophie utérine confirmée "
             "à l'échographie, sans complication.")


@pytest.fixture
def test_uterus(tmp_path: Path) -> Path:
    """Un test à un scénario : DP N858 couvert (une exacte, une réancrable),
    DAS O034 sans clé (code manquant), une clé orpheline Z999 dont la
    formulation est fantôme."""
    td = tmp_path / "06"
    td.mkdir()
    user = _user_generation(
        ("N858", "Autres affections (non inflammatoires précisées) de l'utérus"),
        das=[("O034", "Avortement spontané incomplet, sans complication")])
    crh = _crh(CR_UTERUS, {
        "Autres affections non inflammatoires de l'utérus (N85.8)": [
            "atrophie utérine",                     # exacte
            "atrophie utérine confirmée par échographie",  # réancrable
        ],
        "Diagnostic sans rapport (Z999)": [
            "insuffisance cardiaque terminale",     # orpheline + fantôme
        ],
    })
    _scenario(td, "0000", user, crh)
    return td


# ---------------------------------------------------------------- complétude

class TestCompletudeCodage:
    def test_code_du_scenario_absent_du_dictionnaire(self, test_uterus, capsys):
        rapport = check_crh.check_scenario(test_uterus / "0000",
                                           "crh_generation.txt")
        codes_manquants = [e for e in rapport["echecs"]
                           if e["type"] == "code_absent_texte"]
        assert [e["code"] for e in codes_manquants] == ["O034"]
        assert "Avortement spontané" in codes_manquants[0]["detail"]
        assert rapport["codes_scenario"] == ["N858", "O034"]
        assert rapport["codes_dictionnaire"] == ["N858", "Z999"]
        assert "code du scénario absent du dictionnaire : O034" \
            in capsys.readouterr().out

    def test_cle_orpheline_en_avertissement(self, test_uterus):
        rapport = check_crh.check_scenario(test_uterus / "0000",
                                           "crh_generation.txt")
        orphelines = [a for a in rapport["avertissements"]
                      if a["type"] == "cle_orpheline"]
        assert [a["cle"] for a in orphelines] == \
            ["Diagnostic sans rapport (Z999)"]

    def test_dictionnaire_complet_sans_echec_de_codage(self, tmp_path):
        td = tmp_path / "t"
        td.mkdir()
        user = _user_generation(("I10", "Hypertension essentielle (primitive)"))
        crh = _crh("CR. hypertension artérielle essentielle.",
                   {"Hypertension essentielle (I10)":
                    ["hypertension artérielle essentielle"]})
        d = _scenario(td, "0000", user, crh)
        rapport = check_crh.check_scenario(d, "crh_generation.txt")
        types = {e["type"] for e in rapport["echecs"]}
        assert "code_absent_texte" not in types
        assert not [a for a in rapport["avertissements"]
                    if a["type"] == "cle_orpheline"]

    def test_habillages_de_cles(self):
        for cle in ("Libellé quelconque (Z431)",
                    "Libellé quelconque (Z43.1)",
                    "Z43.1 — Libellé quelconque",
                    "Z431 - Libellé quelconque",
                    "Libellé (avec parenthèses) internes (Z43.1)"):
            assert check_crh.code_de_cle(cle) == "Z431", cle
        assert check_crh.code_de_cle("Libellé sans code") is None
        # extension PMSI « +n » (relevée sur tests/06/0005) : appariement
        # sur le code de base
        assert check_crh.code_de_cle(
            "Tumeur maligne du pancréas endocrine (C254+8)") == "C254"
        assert check_crh.code_de_cle("Tumeur (C25.4+8)") == "C254"

    def test_codage_avec_extension_pmsi(self):
        texte = _user_generation(
            ("C254+8", "Tumeur maligne du pancréas endocrine, autre et non "
                       "précisée"),
            das=[("C787", "Tumeur maligne secondaire du foie")])
        assert [c for c, _ in check_crh.codage_du_scenario(texte)] == \
            ["C254", "C787"]

    def test_codage_du_scenario_parse_le_format_reel(self):
        texte = _user_generation(
            ("E1198", "Diabète sucré de type 2 non insulinotraité, sans "
                      "complication"),
            das=[("I10", "Hypertension essentielle (primitive)"),
                 ("E6604", "Obésité avec indice de masse corporelle [IMC] "
                           "égal ou supérieur à 30 kg/m² (excès calorique)")])
        assert check_crh.codage_du_scenario(texte) == [
            ("E1198", "Diabète sucré de type 2 non insulinotraité, sans "
                      "complication"),
            ("I10", "Hypertension essentielle (primitive)"),
            ("E6604", "Obésité avec indice de masse corporelle [IMC] égal "
                      "ou supérieur à 30 kg/m² (excès calorique)"),
        ]


# ---------------------------------------------------------------- --json

class TestRapportJson:
    def test_rapport_conforme(self, test_uterus, tmp_path):
        user = _user_generation(("I10", "Hypertension essentielle"))
        crh = _crh("CR. hypertension artérielle. IPP Nom Prénom "
                   "Date de naissance.",
                   {"Hypertension essentielle (I10)":
                    ["hypertension artérielle"]})
        _scenario(test_uterus, "0001", user, crh, template="surgery_inpatient")

        chemin = tmp_path / "rapport.json"
        res = subprocess.run(
            [sys.executable, str(SCRIPTS / "check_crh.py"), str(test_uterus),
             "--json", str(chemin)],
            capture_output=True, text=True)
        assert res.returncode == 1          # 0000 porte des échecs
        assert "Bilan : " in res.stdout     # sortie texte inchangée
        assert f"Rapport JSON : {chemin}" in res.stdout

        rapports = json.loads(chemin.read_text(encoding="utf-8"))
        assert [r["scenario"] for r in rapports] == ["0000", "0001"]
        for r in rapports:
            assert set(r) == {"scenario", "template", "echecs",
                              "avertissements", "codes_scenario",
                              "codes_dictionnaire"}
            for e in r["echecs"]:
                assert e["type"] in {"fichier_absent", "json_invalide", "gras",
                                     "fantome", "code_absent_texte",
                                     "fidelite_poids_taille"}
                assert e["detail"]
            for a in r["avertissements"]:
                assert a["type"] in {"json_repare", "cles_manquantes",
                                     "cle_orpheline", "mention_en_tete",
                                     "score_standardise", "maladie_chronique",
                                     "tabac_non_evoque"}
        assert rapports[0]["template"] == "medical_outpatient"
        assert rapports[1]["template"] == "surgery_inpatient"
        types_0000 = [e["type"] for e in rapports[0]["echecs"]]
        assert "fantome" in types_0000 and "code_absent_texte" in types_0000
        assert rapports[1]["echecs"] == []


# ---------------------------------------------------------------- nettoyage

class TestNettoyage:
    def test_trois_classes_et_tracabilite(self, test_uterus, tmp_path):
        out = tmp_path / "export"
        avant = {p.name: p.read_bytes()
                 for p in (test_uterus / "0000").iterdir()}

        rapports = nettoie_dictionnaire.nettoie_test(
            test_uterus, seuil=0.75, out_dir=out)

        # le test n'est pas modifié (lecture seule)
        apres = {p.name: p.read_bytes()
                 for p in (test_uterus / "0000").iterdir()}
        assert apres == avant

        exporte = json.loads((out / "0000.json").read_text(encoding="utf-8"))
        assert exporte == rapports["0000"]
        diag = exporte["formulations"]["diagnostics"]
        garde = diag["Autres affections non inflammatoires de l'utérus (N85.8)"]
        # exacte gardée telle quelle
        assert garde[0] == "atrophie utérine"
        # réancrée : remplacée par un extrait exact du texte
        assert garde[1] != "atrophie utérine confirmée par échographie"
        assert check_crh.normalize(garde[1]) in check_crh.normalize(CR_UTERUS)
        # orpheline supprimée, tracée
        assert diag["Diagnostic sans rapport (Z999)"] == []
        assert [s["formulation"] for s in exporte["supprimees"]] == \
            ["insuffisance cardiaque terminale"]
        assert {"section", "cle", "formulation", "meilleur_candidat",
                "score"} <= set(exporte["supprimees"][0])

    def test_export_dict_par_defaut_hors_decouverte(self, test_uterus):
        res = subprocess.run(
            [sys.executable, str(SCRIPTS / "nettoie_dictionnaire.py"),
             str(test_uterus)],
            capture_output=True, text=True)
        assert res.returncode == 0, res.stdout + res.stderr
        assert (test_uterus / "export_dict" / "0000.json").is_file()

        # export_dict n'est pas pris pour un scénario par check_crh
        res2 = subprocess.run(
            [sys.executable, str(SCRIPTS / "check_crh.py"), str(test_uterus)],
            capture_output=True, text=True)
        assert "[export_dict]" not in res2.stdout
        # ni par un second nettoyage
        res3 = subprocess.run(
            [sys.executable, str(SCRIPTS / "nettoie_dictionnaire.py"),
             str(test_uterus)],
            capture_output=True, text=True)
        assert "[export_dict]" not in res3.stdout


# ---------------------------------------------------------------- juge

FICHE_G122 = _fiche("G12.2", "Maladie du motoneurone",
                    ["sclérose latérale amyotrophique", "maladie de Charcot",
                     "atteinte dégénérative du motoneurone"],
                    alternatives=["paralysie bulbaire progressive"])


@pytest.fixture
def test_motoneurone(tmp_path: Path) -> Path:
    """DP I10 couvert par le dictionnaire, DAS G122 (avec fiche) sans clé."""
    td = tmp_path / "07"
    td.mkdir()
    user = _user_generation(
        ("I10", "Hypertension essentielle (primitive)"),
        das=[("G122", "Maladie du motoneurone")],
        fiches=[FICHE_G122],
        poids_taille=(83, 183))
    crh = _crh("CR. hypertension artérielle traitée. Poids 83 kg, "
               "taille 183 cm.",
               {"Hypertension essentielle (I10)":
                ["hypertension artérielle traitée"]})
    _scenario(td, "0000", user, crh)
    return td


class TestContratJuge:
    def test_fiches_du_scenario(self, test_motoneurone):
        texte = (test_motoneurone / "0000" / "user_generation.txt") \
            .read_text(encoding="utf-8")
        fiches = juge_io.fiches_du_scenario(texte)
        assert list(fiches) == ["G122"]
        fiche = fiches["G122"]
        assert fiche["code_affiche"] == "G12.2"
        assert fiche["libelle"] == "Maladie du motoneurone"
        assert fiche["entites"] == [
            "sclérose latérale amyotrophique", "maladie de Charcot",
            "atteinte dégénérative du motoneurone",
            "paralysie bulbaire progressive"]
        # les puces de « À ne pas décrire » sont exclues
        assert not any("interdite" in e for e in fiche["entites"])
        assert "# G12.2 — Maladie du motoneurone" in fiche["texte"]

    def test_entrees_juge_aller(self, test_motoneurone, tmp_path):
        rapports = nettoie_dictionnaire.nettoie_test(
            test_motoneurone, out_dir=tmp_path / "export")
        out = tmp_path / "entrees_juge.jsonl"
        lignes = juge_io.ecrire_entrees_juge(test_motoneurone, rapports, out)

        relues = [json.loads(l) for l in
                  out.read_text(encoding="utf-8").splitlines() if l.strip()]
        assert relues == lignes
        assert [(l["scenario"], l["code"]) for l in lignes] == \
            [("0000", "I10"), ("0000", "G122")]
        i10, g122 = lignes
        assert set(i10) == {"scenario", "code", "libelle", "fiche", "passages"}
        assert i10["libelle"] == "Hypertension essentielle (primitive)"
        assert i10["passages"] == ["hypertension artérielle traitée"]
        assert i10["fiche"] is None            # pas de fiche pour I10
        assert g122["passages"] == []          # code sans clé au dictionnaire
        assert "# G12.2 — Maladie du motoneurone" in g122["fiche"]

    def test_entrees_juge_depuis_le_dossier_export(self, test_motoneurone,
                                                   tmp_path):
        export = tmp_path / "export"
        nettoie_dictionnaire.nettoie_test(test_motoneurone, out_dir=export)
        lignes = juge_io.ecrire_entrees_juge(
            test_motoneurone, export, tmp_path / "entrees.jsonl")
        assert len(lignes) == 2

    def test_verdicts_aller_retour(self, tmp_path):
        chemin = tmp_path / "verdicts.jsonl"
        chemin.write_text(
            json.dumps({"scenario": "0000", "code": "I10",
                        "preuve_directe": True,
                        "passage_retenu": "hypertension artérielle traitée",
                        "score": 0.93}) + "\n\n"
            + json.dumps({"scenario": "0000", "code": "G12.2",
                          "preuve_directe": False,
                          "passage_retenu": None, "score": 0.12}) + "\n",
            encoding="utf-8")
        verdicts = juge_io.lire_verdicts_juge(chemin)
        assert set(verdicts) == {("0000", "I10"), ("0000", "G122")}
        assert verdicts[("0000", "I10")]["preuve_directe"] is True
        assert verdicts[("0000", "G122")] == {
            "preuve_directe": False, "passage_retenu": None, "score": 0.12}

    @pytest.mark.parametrize("ligne", [
        '{"scenario": "0000", "code": "I10", "preuve_directe": true, '
        '"score": 0.9}',                                   # clé manquante
        '{"scenario": "0000", "code": "I10", "preuve_directe": true, '
        '"passage_retenu": "x", "score": 0.9, "extra": 1}',  # clé inattendue
        '{"scenario": "0000", "code": "I10", "preuve_directe": "oui", '
        '"passage_retenu": "x", "score": 0.9}',            # bool non strict
        '{"scenario": "0000", "code": "I10", "preuve_directe": true, '
        '"passage_retenu": "x", "score": 1.5}',            # score hors [0,1]
        'pas du json',                                     # JSON invalide
    ])
    def test_verdicts_invalides(self, tmp_path, ligne):
        chemin = tmp_path / "verdicts.jsonl"
        chemin.write_text(ligne + "\n", encoding="utf-8")
        with pytest.raises(BenchError):
            juge_io.lire_verdicts_juge(chemin)

    def test_verdicts_doublon(self, tmp_path):
        ligne = json.dumps({"scenario": "0000", "code": "I10",
                            "preuve_directe": True, "passage_retenu": "x",
                            "score": 0.9})
        chemin = tmp_path / "verdicts.jsonl"
        chemin.write_text(ligne + "\n" + ligne + "\n", encoding="utf-8")
        with pytest.raises(BenchError, match="doublon"):
            juge_io.lire_verdicts_juge(chemin)


# ---------------------------------------------------------------- régénération

def _lance_prepare(td: Path, rapport: Path, *options: str):
    return subprocess.run(
        [sys.executable, str(SCRIPTS / "prepare_regeneration.py"), str(td),
         "--check", str(rapport), *options],
        capture_output=True, text=True)


@pytest.fixture
def test_a_regenerer(tmp_path: Path) -> tuple[Path, Path]:
    """(test_dir, rapport check) : 0000 rejeté (G122 manquant, poids/taille
    absents du CR, une formulation fautive au dictionnaire), 0001 propre."""
    td = tmp_path / "07"
    td.mkdir()
    user0 = _user_generation(
        ("G122", "Maladie du motoneurone"), fiches=[FICHE_G122],
        poids_taille=(83, 183))
    crh0 = _crh("CR sans le diagnostic ni les mesures.",
                {"Diagnostic hors sujet (Z999)":
                 ["formulation fautive du dictionnaire"]})
    _scenario(td, "0000", user0, crh0)

    user1 = _user_generation(("I10", "Hypertension essentielle"))
    crh1 = _crh("CR. hypertension artérielle.",
                {"Hypertension essentielle (I10)":
                 ["hypertension artérielle"]})
    _scenario(td, "0001", user1, crh1)

    rapport = tmp_path / "rapport.json"
    subprocess.run(
        [sys.executable, str(SCRIPTS / "check_crh.py"), str(td),
         "--json", str(rapport)],
        capture_output=True, text=True)
    return td, rapport


class TestPrepareRegeneration:
    def test_bloc_prescriptif_et_fichiers(self, test_a_regenerer):
        td, rapport = test_a_regenerer
        res = _lance_prepare(td, rapport, "--seed", "42")
        assert res.returncode == 0, res.stdout + res.stderr

        # seuls les dossiers rejetés reçoivent user_regeneration.txt
        cible = td / "0000" / "user_regeneration.txt"
        assert cible.is_file()
        assert not (td / "0001" / "user_regeneration.txt").exists()

        contenu = cible.read_text(encoding="utf-8")
        user0 = (td / "0000" / "user_generation.txt").read_text(encoding="utf-8")
        assert contenu.startswith(user0.rstrip())
        assert "**CORRECTION REQUISE (régénération) :**" in contenu
        assert "Le diagnostic Maladie du motoneurone (G122) doit être " \
            "exprimé dans le texte." in contenu
        assert "Le poids (83 kg) et la taille (183 cm) fournis doivent " \
            "apparaître dans le texte." in contenu
        # gabarit prescriptif : formulation imposée tirée de la fiche...
        assert any(f'"{e}"' in contenu for e in
                   juge_io.fiches_du_scenario(user0)["G122"]["entites"])
        # ... et JAMAIS une formulation du dictionnaire fautif
        assert "formulation fautive du dictionnaire" not in contenu

        # liste des rejetés + rappel du geste
        assert "only=['0000']" in res.stdout
        assert 'generate(user="user_regeneration.txt", only=only, ' \
            'out="crh_v2.txt")' in res.stdout

        # journal des formulations imposées, pour le re-check
        journal = json.loads((td / "regeneration_42.json")
                             .read_text(encoding="utf-8"))
        assert journal["seed"] == 42
        imposees = journal["scenarios"]["0000"]["formulations_imposees"]
        assert [i["code"] for i in imposees] == ["G122"]
        assert f'"{imposees[0]["formulation"]}"' in contenu
        assert journal["scenarios"]["0000"]["poids_taille"] == \
            {"poids_kg": "83", "taille_cm": "183"}

    def test_tirage_seede_reproductible(self, test_a_regenerer, tmp_path):
        td, rapport = test_a_regenerer
        assert _lance_prepare(td, rapport, "--seed", "7").returncode == 0
        premier = json.loads((td / "regeneration_7.json")
                             .read_text(encoding="utf-8"))
        assert _lance_prepare(td, rapport, "--seed", "7",
                              "--force").returncode == 0
        second = json.loads((td / "regeneration_7.json")
                            .read_text(encoding="utf-8"))
        assert premier["scenarios"] == second["scenarios"]

    def test_refus_d_ecraser_sauf_force(self, test_a_regenerer):
        td, rapport = test_a_regenerer
        assert _lance_prepare(td, rapport).returncode == 0
        contenu = (td / "0000" / "user_regeneration.txt") \
            .read_text(encoding="utf-8")

        res = _lance_prepare(td, rapport)
        assert res.returncode == 1
        assert "--force" in res.stdout
        assert (td / "0000" / "user_regeneration.txt") \
            .read_text(encoding="utf-8") == contenu

        assert _lance_prepare(td, rapport, "--force").returncode == 0

    def test_verdicts_sans_preuve_directe_declenchent(self, test_a_regenerer,
                                                      tmp_path):
        td, rapport = test_a_regenerer
        verdicts = tmp_path / "verdicts.jsonl"
        verdicts.write_text(
            json.dumps({"scenario": "0001", "code": "I10",
                        "preuve_directe": False, "passage_retenu": None,
                        "score": 0.2}) + "\n",
            encoding="utf-8")
        res = _lance_prepare(td, rapport, "--verdicts", str(verdicts))
        assert res.returncode == 0, res.stdout + res.stderr
        assert "only=['0000', '0001']" in res.stdout
        contenu = (td / "0001" / "user_regeneration.txt") \
            .read_text(encoding="utf-8")
        # pas de fiche pour I10 : le libellé du codage est imposé
        assert "Le diagnostic Hypertension essentielle (I10)" in contenu
        assert '"Hypertension essentielle"' in contenu

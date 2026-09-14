"""Tests de bench/fiches.py — accès aux bibliothèques de fiches recode-icd
sous le contrat d'interface (docs/livraison/CONTRAT.md du producteur).

Aucun test de shim `_index.csv → index.csv` : le shim (épisode du
2026-09-12) n'a jamais eu de code ni de test dans ce dépôt, et l'absence
de repli vers `_index.csv` est justement ce que vérifie
`test_index_canonique_sans_repli_sur_index_deprecie`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from bench import charger_index, codes_emissibles, codes_sans_fiche
from bench.errors import BenchError

ENTETE = ("code,chapter,fichier,libelle,statut_mco,classe_generation,"
          "format_version")
LIGNES = [
    'D50.8,III,III/D50.8.md,"Autres anémies par carence en fer",codable,emissible,1',
    'F17.25,V,V/F17.25.md,"Dépendance au tabac — utilisation continue",codable,emissible,1',
    'W00,XX,XX/W00.md,"Chute de plain-pied (tronc)",codable,tronc_composition,1',
]


def _bibliotheque(tmp_path: Path, lignes: list[str] = LIGNES,
                  entete: str = ENTETE, nom_index: str = "index.csv") -> Path:
    bib = tmp_path / "cards_library"
    bib.mkdir(parents=True, exist_ok=True)
    (bib / nom_index).write_text("\n".join([entete, *lignes]) + "\n",
                                 encoding="utf-8")
    return bib


class TestChargerIndex:
    def test_chargement_et_noyau(self, tmp_path):
        index = charger_index(_bibliotheque(tmp_path))
        assert index.height == 3
        assert {"code", "fichier", "statut_mco", "format_version"} <= \
            set(index.columns)

    def test_index_canonique_sans_repli_sur_index_deprecie(self, tmp_path):
        # seul `_index.csv` (déprécié) est présent : échec bruyant, pas de
        # repli — l'index canonique fait foi
        bib = _bibliotheque(tmp_path, nom_index="_index.csv")
        with pytest.raises(BenchError, match="index.csv absent"):
            charger_index(bib)

    @pytest.mark.parametrize("colonne", ["fichier", "statut_mco",
                                         "format_version"])
    def test_noyau_incomplet(self, tmp_path, colonne):
        noms = ENTETE.split(",")
        i = noms.index(colonne)
        entete = ",".join(n for n in noms if n != colonne)
        lignes = [",".join(v for j, v in enumerate(l.split(","))
                           if j != i) for l in LIGNES]
        with pytest.raises(BenchError, match=f"noyau garanti.*{colonne}"):
            charger_index(_bibliotheque(tmp_path, lignes, entete))

    def test_format_version_superieur_refuse_bruyamment(self, tmp_path):
        lignes = [l.rsplit(",", 1)[0] + ",2" for l in LIGNES]
        with pytest.raises(BenchError,
                           match="format_version 2 > 1.*rupture"):
            charger_index(_bibliotheque(tmp_path, lignes))

    def test_format_version_non_constant(self, tmp_path):
        lignes = [LIGNES[0], LIGNES[1].rsplit(",", 1)[0] + ",0"]
        with pytest.raises(BenchError, match="non constant"):
            charger_index(_bibliotheque(tmp_path, lignes))


class TestCodesEmissibles:
    def test_filtre_emissible_exclut_les_troncs(self, tmp_path):
        index = charger_index(_bibliotheque(tmp_path))
        assert codes_emissibles(index) == ["D50.8", "F17.25"]  # W00 exclu

    def test_bibliotheque_sans_classe_generation(self, tmp_path):
        entete = ENTETE.replace(",classe_generation", "")
        lignes = [",".join(v for j, v in enumerate(l.split(","))
                           if j != 5) for l in LIGNES]
        index = charger_index(_bibliotheque(tmp_path, lignes, entete))
        with pytest.raises(BenchError, match="classe_generation"):
            codes_emissibles(index)


class TestCodesSansFiche:
    def test_appariement_pointe_et_compact(self, tmp_path):
        index = charger_index(_bibliotheque(tmp_path))
        assert codes_sans_fiche(index, ["D508", "F17.25", "Z370", "G122"]) \
            == ["Z370", "G122"]

    def test_l_index_fait_foi_pas_le_disque(self, tmp_path):
        # une fiche .md présente sur disque mais absente de l'index
        # n'existe pas (résidu d'ancien build)
        bib = _bibliotheque(tmp_path)
        (bib / "V").mkdir()
        (bib / "V" / "F10.1.md").write_text("# F10.1 — résidu hors index",
                                            encoding="utf-8")
        index = charger_index(bib)
        assert codes_sans_fiche(index, ["F101"]) == ["F101"]

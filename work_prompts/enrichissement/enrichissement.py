"""Enrichissement d'un DataFrame de scénarios CIM-10 (AP-HP) : intoxications
(tabac, alcool -> codes F17/F10) puis anthropométrie (taille, poids, IMC ->
codes E660x, codage systématique dès IMC >= 25), aux conventions fictomed.

L'ordre est load-bearing : chaque enrichisseur lit le scénario COMPLET
(DP + DAS déjà enrichis) — les intoxications lisent les codes de substances
(F11/F12/F14/F16), l'anthropométrie lit E11 (DNID), E66/E43/E44 et, demain,
d'autres codes. Les codes ajoutés le sont TOUJOURS en DAS, jamais en DP.

Conventions (celles de fictomed, relevées sur ``sites/aphp``)
-------------------------------------------------------------
- colonnes : ``icd_primary_code`` (DP), ``icd_secondary_code`` (DAS),
  ``age`` (entier ; repli sur ``age2``, le nom du profil avant
  ``build_scenario``), ``sexe`` (PMSI : 1 = masculin, 2 = féminin) ;
- codes compacts sans point (``E1120``, ``F10202``) — le format interne ;
  la forme pointée n'existe que dans les fiches descriptives ;
- DAS : liste de codes OU chaîne séparée par des espaces (les deux formes
  circulent dans fictomed : chaîne dans les profils, liste après
  ``build_scenario``) — le type d'entrée est préservé en sortie ;
- polars, itération ligne à ligne dans l'ordre (déterminisme à seed et
  ordre fixés).

Emploi dans fictomed : appeler :func:`enrichir_scenarios` sur le DataFrame
de profils AVANT ``build_scenario`` — fictomed génère alors lui-même les
lignes « Diagnostics associés » (libellés officiels du référentiel) et les
fiches descriptives des codes ajoutés. :func:`bloc_contexte` fournit les
lignes patient prêtes pour le template du prompt user.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

import polars as pl

from .anthropometrie import SimulateurAnthropometrie
from .intoxications import SimulateurIntoxications

# Colonnes ajoutées par l'enrichissement, avec leur type polars.
COLONNES_ENRICHISSEMENT: dict[str, type[pl.DataType]] = {
    "taille_cm": pl.Int64,
    "poids_kg": pl.Int64,
    "imc": pl.Float64,
    "classe_imc": pl.Utf8,
    "tabac": pl.Utf8,
    "alcool": pl.Utf8,
    "contexte_texte": pl.Utf8,
    "codes_ajoutes": pl.Utf8,
    "enrichi": pl.Boolean,
}


@dataclass(frozen=True)
class Politique:
    """Politique d'enrichissement — porte les décisions de doctrine (RF).

    Attributes
    ----------
    age_min:
        En dessous, la ligne est passée intacte (``enrichi=False``) : les
        simulateurs sont calibrés sur des adultes (Esteban, Obépi).
    prefixes_exclusion:
        Préfixes de codes (DP + DAS, compacts) qui excluent la ligne de
        l'enrichissement : O00-O99 (grossesse — anthropométrie et
        consommations non représentatives), Z94/T86 (transplantés).
    p_tabac, p_alcool, p_tabac_poly, p_alcool_poly:
        Probabilités de tirage des codes d'intoxication (cf.
        :mod:`intoxications`) — float ou dict ``{1: .., 2: ..}`` par sexe.
    feuilles_seulement:
        Restreint les tirages aux feuilles du référentiel de fiches.
    """

    age_min: int = 18
    prefixes_exclusion: tuple[str, ...] = ("O", "Z94", "T86")
    p_tabac: float | dict = 0.30
    p_alcool: float | dict = 0.10
    p_tabac_poly: float | dict = 0.90
    p_alcool_poly: float | dict = 0.70
    feuilles_seulement: bool = True


# ---------------------------------------------------------------------------
# Lecture / écriture du DAS dans les deux formes fictomed
# ---------------------------------------------------------------------------

def _lire_das(das: Any) -> list[str]:
    """Liste de codes compacts depuis une liste ou une chaîne espace-séparée
    (mêmes tolérances que ``scenario._parse_secondary_codes``)."""
    if das is None or das == "" or das == []:
        return []
    if isinstance(das, (list, tuple)):
        valeurs: Iterable[Any] = das
    else:
        valeurs = str(das).replace(";", " ").split()
    return [str(c).strip().upper() for c in valeurs
            if str(c).strip() and str(c).strip().upper() not in ("NA", "NAN")]


def _ecrire_das(codes: list[str], comme: Any) -> Any:
    """Réécrit le DAS dans le type de la valeur d'origine (liste ou chaîne)."""
    if isinstance(comme, (list, tuple)):
        return list(codes)
    return " ".join(codes)


def _age_de(ligne: Mapping[str, Any]) -> int | None:
    """``age`` (scénario construit), sinon ``age2`` (profil)."""
    for col in ("age", "age2"):
        v = ligne.get(col)
        if v is not None:
            try:
                return int(v)
            except (TypeError, ValueError):
                return None
    return None


# ---------------------------------------------------------------------------
# Enrichissement
# ---------------------------------------------------------------------------

class _Enrichisseur:
    """Enrichit ligne à ligne ; les deux simulateurs ont des graines dérivées
    (seed+1, seed+2), indépendants et reproductibles."""

    def __init__(self, seed: int | None, politique: Politique):
        self.politique = politique
        s = None if seed is None else int(seed)
        self.intox = SimulateurIntoxications(
            seed=None if s is None else s + 1,
            p_tabac=politique.p_tabac, p_alcool=politique.p_alcool,
            p_tabac_poly=politique.p_tabac_poly,
            p_alcool_poly=politique.p_alcool_poly,
            feuilles_seulement=politique.feuilles_seulement,
        )
        self.anthro = SimulateurAnthropometrie(seed=None if s is None else s + 2)

    def exclue(self, dp: str, das: list[str], age: int | None) -> bool:
        if age is None or age < self.politique.age_min:
            return True
        codes = [dp] + das if dp else das
        return any(c.startswith(self.politique.prefixes_exclusion) for c in codes)

    def enrichir_ligne(self, ligne: dict) -> dict:
        out = dict(ligne)
        dp = str(out.get("icd_primary_code") or "").strip().upper()
        das_origine = out.get("icd_secondary_code")
        das = _lire_das(das_origine)
        age = _age_de(out)
        vides = {c: None for c in COLONNES_ENRICHISSEMENT}
        vides["enrichi"] = False

        if self.exclue(dp, das, age):
            out.update(vides)
            return out
        sexe = out.get("sexe")
        if sexe is None:
            out.update(vides)
            return out

        ajoutes: list[str] = []

        # 1. Intoxications — lit DP + DAS
        intox = self.intox.completer([dp] + das, age, sexe)
        das += [c for c in intox.codes_ajoutes if c not in das and c != dp]
        ajoutes += intox.codes_ajoutes

        # 2. Anthropométrie — lit DP + DAS (dont les codes tout juste ajoutés)
        anthro, codes_anthro = self.anthro.tirer_pour_scenario(
            [dp] + das, age, sexe)
        das += [c for c in codes_anthro if c not in das and c != dp]
        ajoutes += codes_anthro

        # 3. Écriture — DAS dans son format d'origine, colonnes descriptives
        feminin = int(sexe) == 2
        out["icd_secondary_code"] = _ecrire_das(das, das_origine)
        out.update({
            "taille_cm": anthro.taille_cm,
            "poids_kg": anthro.poids_kg,
            "imc": anthro.imc,
            "classe_imc": anthro.classe_imc,
            "tabac": intox.tabac.as_ligne(),
            "alcool": intox.alcool.as_ligne(),
            "contexte_texte": (
                f"Patient{'e' if feminin else ''} de {age} ans, "
                f"{anthro.taille_cm} cm, {anthro.poids_kg} kg (IMC {anthro.imc}). "
                f"{intox.as_texte(sexe)}"
            ),
            "codes_ajoutes": " ".join(ajoutes),
            "enrichi": True,
        })
        return out


def enrichir_scenarios(df: pl.DataFrame, seed: int | None,
                       politique: Politique = Politique()) -> pl.DataFrame:
    """Enrichit un DataFrame de scénarios/profils fictomed, ligne à ligne.

    Déterministe à ``seed`` et ordre des lignes fixés. Les lignes exclues par
    la politique (âge, préfixes de codes) sont passées intactes
    (``enrichi=False``, colonnes descriptives nulles) et ne consomment aucun
    tirage. Colonnes ajoutées : cf. ``COLONNES_ENRICHISSEMENT`` ; le DAS est
    étendu dans son format natif (liste ou chaîne espace-séparée).
    """
    enr = _Enrichisseur(seed, politique)
    lignes = [enr.enrichir_ligne(r) for r in df.iter_rows(named=True)]
    schema = {**df.schema, **COLONNES_ENRICHISSEMENT}
    return pl.from_dicts(lignes, schema=schema)


# ---------------------------------------------------------------------------
# Bloc de contexte pour le prompt user
# ---------------------------------------------------------------------------

def bloc_contexte(ligne: Mapping[str, Any]) -> str:
    """Lignes « contexte patient » prêtes pour le prompt user AP-HP.

    Style des lignes existantes de ``prompt.make_user_prompt``
    (« - Âge du patient : 62 ans »). Retourne une chaîne terminée par un
    retour à la ligne, vide si la ligne n'a pas été enrichie — dans
    fictomed, à appeler depuis le template du prompt user, à la suite des
    lignes d'identité du patient.
    """
    if not ligne.get("enrichi"):
        return ""
    imc = str(ligne.get("imc", "")).replace(".", ",")
    return (
        f"- Taille : {ligne['taille_cm']} cm\n"
        f"- Poids : {ligne['poids_kg']} kg (IMC {imc})\n"
        f"- Tabac : {ligne['tabac']}\n"
        f"- Alcool : {ligne['alcool']}\n"
    )


# ---------------------------------------------------------------------------
# Auto-contrôle : enrichissement d'une petite table aux conventions fictomed
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    scenarios = [
        {"id": 1, "icd_primary_code": "E1120", "icd_secondary_code": "N083 I10",
         "age": 62, "sexe": 1},
        {"id": 2, "icd_primary_code": "I210", "icd_secondary_code": "",
         "age": 55, "sexe": 2},
        {"id": 3, "icd_primary_code": "K703", "icd_secondary_code": "F1025",
         "age": 51, "sexe": 1},
        {"id": 4, "icd_primary_code": "F1124", "icd_secondary_code": "B182",
         "age": 34, "sexe": 1},
        {"id": 5, "icd_primary_code": "E43", "icd_secondary_code": "C169",
         "age": 78, "sexe": 2},
        {"id": 6, "icd_primary_code": "J441", "icd_secondary_code": "E6605",
         "age": 66, "sexe": 2},
        {"id": 7, "icd_primary_code": "O800", "icd_secondary_code": "Z370",
         "age": 31, "sexe": 2},   # grossesse : exclue
        {"id": 8, "icd_primary_code": "P073", "icd_secondary_code": "",
         "age": 0, "sexe": 1},    # nouveau-né : exclu (age_min)
    ]
    df = pl.DataFrame(scenarios)
    out = enrichir_scenarios(df, seed=42)
    with pl.Config(tbl_width_chars=170, fmt_str_lengths=44, tbl_rows=12):
        print(out.select("id", "icd_primary_code", "icd_secondary_code",
                         "codes_ajoutes", "enrichi", "taille_cm", "poids_kg",
                         "imc", "tabac", "alcool"))
    print("\nSchéma :", dict(out.schema))
    print("\nbloc_contexte (ligne 4, contexte poly) :")
    print(bloc_contexte(out.row(3, named=True)))
    print("bloc_contexte (ligne 7, exclue) :", repr(bloc_contexte(out.row(6, named=True))))

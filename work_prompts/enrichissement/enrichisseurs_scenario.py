"""
enrichisseurs_scenario.py — Enrichit un scénario CIM-10 (une ligne : DP, DAS,
age, sexe, …) avec les paramètres descriptifs et les codes manquants :

  1. intoxications (tabac, alcool)  → codes F17.–/F10.– ajoutés en DAS
  2. anthropométrie (taille, poids, IMC) → codes E66.0x ajoutés en DAS

L'ordre est load-bearing : chaque enrichisseur lit le scénario COMPLET
(DP + DAS déjà enrichis) — les intoxications lisent les codes de substances
(F11/F12/F14/F16), l'anthropométrie lit E11 (DNID), E66/E43/E44 et, demain,
d'autres codes. Les codes ajoutés le sont TOUJOURS en DAS, jamais en DP.

Entrée : dict, ou DataFrame POLARS (pandas accepté aussi) avec les colonnes
`DP`, `DAS`, `age`, `sexe`
(noms configurables). `DAS` est une chaîne de codes séparés par `sep`
(défaut "|"), ou une liste. Sortie : la même ligne, DAS étendu, plus les
colonnes taille_cm, poids_kg, imc, classe_imc, tabac, alcool,
contexte_texte (phrase prête pour le prompt) et codes_ajoutes.

Usage
-----
    enr = EnrichisseurScenario(seed=42, sep="|")
    ligne = enr.enrichir({"DP": "E11.20", "DAS": "N08.3|I10", "age": 62, "sexe": "H"})
    df_enrichi = enr.enrichir_table(df)      # polars (ou pandas), une ligne par scénario

Dépendances : numpy, polars (pandas accepté en alternative pour enrichir_table).
"""

from __future__ import annotations

from anthropometrie_fr import SimulateurAnthropometrie
from intoxications_fr import SimulateurIntoxications


class EnrichisseurScenario:
    def __init__(self, seed: int | None = None, sep: str = "|",
                 col_dp: str = "DP", col_das: str = "DAS",
                 col_age: str = "age", col_sexe: str = "sexe",
                 params_intoxications: dict | None = None,
                 p_codage_obesite: float = 1.0, p_codage_surpoids: float = 0.0):
        self.sep = sep
        self.cols = (col_dp, col_das, col_age, col_sexe)
        self.p_codage_obesite, self.p_codage_surpoids = p_codage_obesite, p_codage_surpoids
        # graines dérivées : les deux simulateurs sont indépendants et reproductibles
        s = None if seed is None else int(seed)
        self.intox = SimulateurIntoxications(seed=None if s is None else s + 1,
                                             **(params_intoxications or {}))
        self.anthro = SimulateurAnthropometrie(seed=None if s is None else s + 2)

    # ----- utilitaires ------------------------------------------------------
    def _lire_das(self, das) -> list[str]:
        if das is None:
            return []
        if isinstance(das, (list, tuple)):
            return [str(c).strip() for c in das if str(c).strip()]
        if isinstance(das, float):        # NaN pandas
            return []
        return [c.strip() for c in str(das).split(self.sep) if c.strip()]

    def _ecrire_das(self, codes: list[str]) -> str:
        return self.sep.join(codes)

    # ----- enrichissement d'une ligne --------------------------------------
    def enrichir(self, ligne: dict) -> dict:
        col_dp, col_das, col_age, col_sexe = self.cols
        out = dict(ligne)
        dp = str(out.get(col_dp, "")).strip()
        das = self._lire_das(out.get(col_das))
        age, sexe = int(out[col_age]), str(out[col_sexe])
        ajoutes: list[str] = []

        # 1. Intoxications — lit DP + DAS
        intox = self.intox.completer([dp] + das, age, sexe)
        das += [c for c in intox.codes_ajoutes if c not in das and c != dp]
        ajoutes += intox.codes_ajoutes

        # 2. Anthropométrie — lit DP + DAS (dont les codes tout juste ajoutés)
        anthro, codes_anthro = self.anthro.tirer_pour_scenario(
            [dp] + das, age, sexe, self.p_codage_obesite, self.p_codage_surpoids)
        das += [c for c in codes_anthro if c not in das and c != dp]
        ajoutes += codes_anthro

        # 3. Écriture
        out[col_das] = self._ecrire_das(das)
        out.update({
            "taille_cm": anthro.taille_cm, "poids_kg": anthro.poids_kg,
            "imc": anthro.imc, "classe_imc": anthro.classe_imc,
            "tabac": intox.tabac.statut, "alcool": intox.alcool.statut,
            "contexte_texte": (f"Patient{'e' if sexe.upper().startswith('F') else ''} de {age} ans, "
                               f"{anthro.taille_cm} cm, {anthro.poids_kg} kg (IMC {anthro.imc}). "
                               f"{intox.as_texte(sexe)}"),
            "codes_ajoutes": self.sep.join(ajoutes),
        })
        return out

    # ----- table polars (ou pandas) ------------------------------------------
    def enrichir_table(self, df):
        """Enrichit un DataFrame polars (ou pandas) ligne à ligne, dans l'ordre.
        Retourne un DataFrame du même type : colonne DAS modifiée, colonnes
        taille_cm / poids_kg / imc / classe_imc / tabac / alcool /
        contexte_texte / codes_ajoutes ajoutées, autres colonnes préservées."""
        try:
            import polars as pl
        except ImportError:
            pl = None
        if pl is not None and isinstance(df, pl.DataFrame):
            lignes = [self.enrichir(r) for r in df.iter_rows(named=True)]
            schema = {**df.schema,
                      "taille_cm": pl.Int64, "poids_kg": pl.Int64, "imc": pl.Float64,
                      "classe_imc": pl.Utf8, "tabac": pl.Utf8, "alcool": pl.Utf8,
                      "contexte_texte": pl.Utf8, "codes_ajoutes": pl.Utf8}
            schema[self.cols[1]] = pl.Utf8      # DAS réécrit en chaîne
            return pl.from_dicts(lignes, schema=schema)
        import pandas as pd
        return pd.DataFrame([self.enrichir(r) for r in df.to_dict("records")])


# ---------------------------------------------------------------------------
if __name__ == "__main__":
    enr = EnrichisseurScenario(seed=42)
    scenarios = [
        {"id": 1, "DP": "E11.20", "DAS": "N08.3|I10", "age": 62, "sexe": "H"},
        {"id": 2, "DP": "I21.0",  "DAS": "",            "age": 55, "sexe": "F"},
        {"id": 3, "DP": "K70.3",  "DAS": "F10.25",      "age": 51, "sexe": "H"},
        {"id": 4, "DP": "F11.24", "DAS": "B18.2",       "age": 34, "sexe": "H"},
        {"id": 5, "DP": "E43",    "DAS": "C16.9",       "age": 78, "sexe": "F"},
        {"id": 6, "DP": "J44.1",  "DAS": "E66.05",      "age": 66, "sexe": "F"},
    ]
    import polars as pl
    df = pl.DataFrame(scenarios)
    out = enr.enrichir_table(df)
    with pl.Config(tbl_width_chars=160, fmt_str_lengths=40, tbl_rows=10):
        print(out.select("id", "DP", "DAS", "codes_ajoutes", "taille_cm", "poids_kg", "imc", "tabac", "alcool"))
    print("\nSchéma :", dict(out.schema))
    print("\nExemple de contexte_texte :", out["contexte_texte"][3])

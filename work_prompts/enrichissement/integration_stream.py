"""Colle entre le package d'enrichissement et le banc d'essai Stream.

NON destiné à fictomed — ne pas copier ce fichier avec le package. Tout ce
qui suit n'a de sens que dans Stream : adaptation du schéma des profils
sources (avant le rename du loader fictomed), insertion dans un user prompt
DÉJÀ construit par fictomed (via ``bench.seed_user_prompts``). Dans fictomed,
ni l'un ni l'autre n'existeront : le loader fournit les noms natifs, et le
template du prompt appellera :func:`~enrichissement.bloc_contexte`
directement.
"""

from __future__ import annotations

from typing import Callable

import polars as pl

from .enrichissement import (
    COLONNES_ENRICHISSEMENT,
    Politique,
    bloc_contexte,
    enrichir_scenarios,
)

# Schéma des profils sources Stream -> noms natifs fictomed (sous-ensemble du
# _PROFILE_RENAME du loader fictomed, limité aux colonnes lues par
# l'enrichissement).
_VERS_FICTOMED = {
    "diag2": "icd_primary_code",
    "diagnostic_associes": "icd_secondary_code",
    "agean": "age2",
    "age": "cage",   # l'« age » des profils est CATÉGORIEL (ge_18/lt_18) —
                     # le loader fictomed le renomme cage ; sans ce rename il
                     # masquerait l'âge numérique (age2) pour l'enrichissement
}
_DEPUIS_FICTOMED = {v: k for k, v in _VERS_FICTOMED.items()}


def enrichir_candidats(candidate_source: pl.DataFrame, seed: int | None,
                       politique: Politique = Politique()) -> pl.DataFrame:
    """Enrichit le pool candidat du tirage stratifié, AVANT fictomed.

    Le pool est au schéma des profils sources (``diag2``,
    ``diagnostic_associes`` chaîne espace-séparée, ``agean``, ``sexe``) : on
    le traduit vers les noms natifs fictomed, on enrichit, on retraduit.
    ``nbda`` est mis à jour du nombre de codes ajoutés. fictomed génère
    ensuite lui-même les libellés officiels et les fiches des codes ajoutés
    (``build_scenario`` reconstruit ``text_secondary_icd_official`` et les
    fiches depuis le DAS du profil).
    """
    natif = candidate_source.rename(
        {k: v for k, v in _VERS_FICTOMED.items() if k in candidate_source.columns}
    )
    enrichi = enrichir_scenarios(natif, seed=seed, politique=politique)
    enrichi = enrichi.rename(
        {k: v for k, v in _DEPUIS_FICTOMED.items() if k in enrichi.columns}
    )
    if "nbda" in enrichi.columns:
        n_ajoutes = (
            pl.when(pl.col("codes_ajoutes").fill_null("") != "")
            .then(pl.col("codes_ajoutes").str.split(" ").list.len())
            .otherwise(0)
        )
        enrichi = enrichi.with_columns(
            (pl.col("nbda") + n_ajoutes).cast(candidate_source["nbda"].dtype).alias("nbda")
        )

    total = enrichi.height
    faits = int(enrichi["enrichi"].sum())
    codes = [c for v in enrichi["codes_ajoutes"].drop_nulls() for c in v.split() if v]
    print(f"Enrichissement : {faits}/{total} ligne(s) enrichie(s), "
          f"{total - faits} exclue(s), {len(codes)} code(s) DAS ajouté(s).")

    from collections import Counter

    if total - faits:
        # motif d'exclusion par ligne (même logique que la politique)
        motifs: Counter[str] = Counter()
        for r in enrichi.filter(~pl.col("enrichi").fill_null(False)).iter_rows(named=True):
            age = r.get("agean") if r.get("agean") is not None else r.get("age2")
            if age is None or int(age) < politique.age_min:
                motifs[f"âge < {politique.age_min} (ou manquant)"] += 1
                continue
            codes_ligne = [str(r.get("diag2") or "")] + str(
                r.get("diagnostic_associes") or "").split()
            prefixe = next((p for p in politique.prefixes_exclusion
                            if any(c.startswith(p) for c in codes_ligne)), "?")
            motifs[f"préfixe {prefixe}"] += 1
        print("Exclusions :", ", ".join(f"{m} ×{n}" for m, n in motifs.most_common()))
    if codes:
        comptes = Counter(codes).most_common(12)
        print("Codes ajoutés :", ", ".join(f"{c}×{n}" for c, n in comptes))
    return enrichi


def user_fn_enrichi(col_user: str = "user_prompt") -> Callable[[dict], str]:
    """Closure ``row -> str`` pour ``bench.seed_user_prompts`` : insère le
    bloc contexte dans le user prompt déjà construit par fictomed, après la
    ligne « - Sexe du patient : ... ».

    Idempotent (marqueur « - Taille : ») ; no-op si la ligne n'a pas été
    enrichie. (Dans fictomed, cette insertion n'existera pas : le template
    du prompt user appellera ``bloc_contexte`` directement.)
    """
    def build_user(row: dict) -> str:
        prompt = str(row.get(col_user) or "")
        bloc = bloc_contexte(row)
        if not bloc or "- Taille : " in prompt:
            return prompt
        lignes = prompt.splitlines(keepends=True)
        for i, l in enumerate(lignes):
            if l.lstrip().startswith("- Sexe du patient :"):
                return "".join(lignes[: i + 1]) + bloc + "".join(lignes[i + 1:])
        return prompt  # ancre absente : prompt inchangé (prudence)

    return build_user

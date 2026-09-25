# substituer_dp_imprecis.py — substitution des DP « sans précision » d'un corpus
# de scénarios (étape FICHIER → FICHIER, en amont du banc de génération)
#
# Le corpus d'une campagne (projet amont scenarios_bn_pmsi) porte des DP
# imprécis. Décision actée : tout DP imprécis est REMPLACÉ par un code précis
# de la même catégorie CIM-10, vraisemblable pour le patient (tirage pondéré
# par les effectifs réels observés), SAUF pour les séjours typés UHCD (unité
# d'hospitalisation de courte durée des urgences, où l'imprécision est
# cliniquement réaliste). Les DAS ne sont PAS substitués (décision : DP
# seulement). Aucun appel payant.
#
# ORDRE : la substitution précède TOUT — typologie, filtres, tirage,
# enrichissement, fictomed. Le corpus substitué est un artefact identifié
# (<corpus>_dp.parquet) que le notebook consomme comme n'importe quelle
# source (SOURCE_PROFILES_PATH ; verifier_source le contrôle). L'aval opère
# donc naturellement sur le DP final ; en particulier l'enrichisseur lit le
# DP (E11 → corpulence diabétique, exclusions Z94/T86/O, E66 → contrainte
# IMC) : il DOIT voir le DP substitué, ce que l'architecture fichier→fichier
# garantit par construction.
#
# ENTRÉES
#   corpus scenarios_<C>.parquet — colonnes lues : id_scenario (clé de la
#     graine), diag2 (LE DP, cible), cage (classe d'âge), sexe ; facultatives :
#     branche ("long"/"court", axe du rapport), type_unite ("UHCD" = séjour
#     entièrement passé en UHCD). Si type_unite est absente ou nulle (constaté
#     sur toute la branche « court » de C1), la règle par défaut — substituer —
#     s'applique : un court programmé n'est pas une UHCD ; le constat est
#     inscrit au rapport.
#   data/aphp/referentials/ref_substitution_imprecis.parquet — agrégat seuillé exporté de la
#     plateforme : cat (catégorie CIM 3 caractères), code (chaque code observé
#     de la catégorie), cage, sexe, nb (effectif réel observé = poids du
#     tirage), niveau (sévérité CMA — NON utilisé en v1 : les effectifs sont
#     sommés sur niveau), imprecis (TRUE pour les codes sans précision — c'est
#     AUSSI la liste de détection : un DP est imprécis s'il figure dans
#     ref[imprecis].code).
#
# RÈGLE, pour chaque ligne du corpus
#   - diag2 absent de la liste des imprécis → rien ;
#   - type_unite == "UHCD" → CONSERVÉ tel quel (compté) ;
#   - sinon → SUBSTITUÉ : tirage pondéré par nb parmi les codes de la MÊME cat,
#     imprecis == FALSE, dans la strate (cage, sexe) du patient. Repli
#     hiérarchique si la strate est vide ou sans candidat précis :
#     niveau 0 (cat, cage, sexe) → 1 (cat, sexe) → 2 (cat, tous confondus) ;
#     si toujours aucun candidat précis observé → CONSERVÉ et compté (JAMAIS
#     de code hors référence, JAMAIS d'échec silencieux). Niveau tracé par ligne.
#
# DÉTERMINISME — graine PAR LIGNE dérivée de id_scenario par un hash STABLE
# (sha256 tronqué ; jamais hash() natif, salé par processus) : le même corpus
# resubstitué donne un résultat bit à bit identique, quel que soit l'ordre des
# lignes et le processus. id_scenario n'est PAS unique par ligne (C1 :
# 474 077 valeurs pour 1 087 525 lignes) — les lignes qui le partagent sont des
# variantes de contexte de séjour (duree, mode_entree, mode_sortie, mdp) du
# MÊME scénario clinique (DP, DAS, cage, sexe identiques). Décision (Rémi,
# 24/09/2026) : un scénario = un cas clinique ; ses variantes de contexte
# (durée, modes) partagent le DP final, par construction de la graine — VOULU.
#
# CONSTATS CAMPAGNE C1 (scenarios_C1.parquet, décision Rémi du 24/09/2026)
#   - C1 ne contient AUCUN séjour UHCD : type_unite est nulle sur toute la
#     branche « court » et ne vaut jamais UHCD sur « long » (GERIATRIE, HC,
#     HP, NEONAT, SC, SC-NEONAT). Les séjours UHCD arriveront en campagne 2,
#     avec type_unite renseigné sur la branche courte. Conséquence : sur C1
#     la substitution s'applique UNIFORMÉMENT — le compteur « conservés
#     UHCD » du rapport doit valoir 0 ; toute autre valeur est une anomalie.
#
# TRAÇABILITÉ — sortie : toutes les colonnes d'entrée inchangées SAUF diag2
# (valeur finale) ; ajoutées : dp_origine (diag2 d'entrée), dp_substitue
# (booléen), repli_substitution (0/1/2, nul si pas de substitution). Rapport
# imprimé ET écrit à côté de la sortie (<out sans extension>.rapport.txt) :
# effectifs par branche (lignes, DP imprécis rencontrés, substitués par niveau
# de repli, conservés UHCD, conservés faute de candidat), constat type_unite,
# constat id_scenario.
#
# NOTE DE COHÉRENCE — le ghm2 du séjour a été groupé sur le DP d'origine :
# après substitution, DP et GHM peuvent diverger finement. Compromis accepté
# pour un corpus d'entraînement (même doctrine que les codes ajoutés par
# l'enrichissement) ; il est écrit au rapport, pas implicite. Les codes
# substitués sont des codes observés du PMSI réel : ils passeront le contrôle
# de fiches existant en aval (contrat recode-icd dans preparer_pool) — aucun
# contrôle de fiches ici.
#
# QUESTIONS CONSIGNÉES (aucune action en v1)
#   - niveau (sévérité CMA) comme critère « à sévérité comparable » : v2
#     possible, à valider cliniquement ;
#   - les DAS imprécis : hors périmètre par décision ; la même référence
#     servirait le jour venu ;
#   - probabilité de conservation aux urgences hors UHCD (mode d'entrée
#     urgences, hospitalisation classique) : 0 en v1 (on substitue) ; réglable
#     si la revue clinique des CRH le demande.
#
# Usage :
#   python scripts/substituer_dp_imprecis.py <corpus.parquet>
#       --ref data/aphp/referentials/ref_substitution_imprecis.parquet [--out <corpus_dp.parquet>]
#   (défaut --out : <corpus>_dp.parquet, à côté du corpus)

from __future__ import annotations

import argparse
import hashlib
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import polars as pl

COLONNES_CORPUS = ("id_scenario", "diag2", "cage", "sexe")
COLONNES_REF = ("cat", "code", "cage", "sexe", "nb", "imprecis")
UHCD = "UHCD"
NIVEAUX = {0: "(cat, cage, sexe)", 1: "(cat, sexe)", 2: "(cat, tous confondus)"}
BRANCHE_UNIQUE = "(toutes)"  # rapport quand la colonne branche est absente


class ErreurSubstitution(ValueError):
    """Entrée inexploitable (fichier, colonnes) — message pour l'utilisateur."""


# ---------------------------------------------------------------- graine

def graine_ligne(id_scenario: object) -> int:
    """Graine stable d'une ligne : sha256 de str(id_scenario), 8 premiers
    octets en entier. JAMAIS hash() natif (salé par processus)."""
    return int.from_bytes(
        hashlib.sha256(str(id_scenario).encode("utf-8")).digest()[:8], "big"
    )


# ---------------------------------------------------------------- référence

def charger_reference(path: Path) -> pl.DataFrame:
    """Lit la référence et la normalise (:func:`normaliser_reference`)."""
    try:
        ref = pl.read_parquet(path)
    except Exception as exc:
        raise ErreurSubstitution(f"référence illisible : {path} — {exc}") from None
    try:
        return normaliser_reference(ref)
    except ErreurSubstitution as exc:
        raise ErreurSubstitution(f"{path} : {exc}") from None


def normaliser_reference(ref: pl.DataFrame) -> pl.DataFrame:
    """Vérifie les colonnes de la référence et normalise les types (cat, code,
    cage, sexe en chaînes ; nb numérique ; imprecis booléen)."""
    manquantes = [c for c in COLONNES_REF if c not in ref.columns]
    if manquantes:
        raise ErreurSubstitution(
            f"référence : colonne(s) manquante(s) {manquantes} "
            f"(attendues : {list(COLONNES_REF)})")
    imprecis = ref["imprecis"]
    if imprecis.dtype != pl.Boolean:
        imprecis = imprecis.cast(pl.String).str.to_uppercase().is_in(["TRUE", "1", "T", "VRAI"])
    return ref.with_columns(
        pl.col("cat").cast(pl.String).str.strip_chars(),
        pl.col("code").cast(pl.String).str.strip_chars(),
        pl.col("cage").cast(pl.String).str.strip_chars(),
        pl.col("sexe").cast(pl.String).str.strip_chars(),
        pl.col("nb").cast(pl.Float64),
        imprecis.alias("imprecis"),
    )


@dataclass
class Candidats:
    """Candidats précis par niveau de repli — pour chaque clé, les codes et
    leurs poids normalisés (effectifs nb sommés sur niveau et, aux niveaux
    1 et 2, sur les strates confondues)."""

    imprecis: dict[str, str]  # code imprécis -> cat
    niveaux: list[dict[tuple, tuple[list[str], np.ndarray]]]

    @classmethod
    def depuis_reference(cls, ref: pl.DataFrame) -> "Candidats":
        imprecis = dict(ref.filter(pl.col("imprecis")).select("code", "cat").unique().iter_rows())
        precis = ref.filter(~pl.col("imprecis") & (pl.col("nb") > 0))
        niveaux: list[dict] = []
        for cles in (("cat", "cage", "sexe"), ("cat", "sexe"), ("cat",)):
            agg = precis.group_by(list(cles) + ["code"]).agg(pl.col("nb").sum()).sort(list(cles) + ["code"])
            table: dict[tuple, tuple[list[str], np.ndarray]] = {}
            for row in agg.iter_rows(named=True):
                cle = tuple(row[c] for c in cles)
                table.setdefault(cle, ([], []))
                table[cle][0].append(row["code"])
                table[cle][1].append(row["nb"])
            niveaux.append({
                cle: (codes, np.asarray(poids, dtype=float) / float(sum(poids)))
                for cle, (codes, poids) in table.items()
            })
        return cls(imprecis, niveaux)

    def tirer(self, cat: str, cage: str, sexe: str, rng: np.random.Generator
              ) -> tuple[str | None, int | None]:
        """Un code précis et le niveau de repli utilisé, ou (None, None)."""
        for niveau, cle in enumerate(((cat, cage, sexe), (cat, sexe), (cat,))):
            cand = self.niveaux[niveau].get(cle)
            if cand is not None:
                codes, p = cand
                return codes[int(rng.choice(len(codes), p=p))], niveau
        return None, None


# ---------------------------------------------------------------- rapport

@dataclass
class CompteurBranche:
    lignes: int = 0
    imprecis: int = 0
    substitues: Counter = field(default_factory=Counter)  # niveau -> n
    conserves_uhcd: int = 0
    conserves_sans_candidat: int = 0


@dataclass
class Rapport:
    corpus: Path
    reference: Path
    sortie: Path
    n_codes_imprecis_ref: int = 0
    n_codes_precis_ref: int = 0
    branches: dict[str, CompteurBranche] = field(default_factory=dict)
    constats: list[str] = field(default_factory=list)

    def texte(self) -> str:
        lignes = [
            f"Substitution des DP imprécis — corpus {self.corpus.name} → {self.sortie.name}",
            f"Référence : {self.reference.name} — {self.n_codes_imprecis_ref} code(s) imprécis "
            f"(liste de détection), {self.n_codes_precis_ref} code(s) précis candidats ; "
            "niveau (sévérité CMA) non utilisé en v1 (effectifs sommés).",
            "",
        ]
        total = CompteurBranche()
        for nom, c in sorted(self.branches.items()):
            lignes += self._bloc(f"branche {nom}", c)
            total.lignes += c.lignes
            total.imprecis += c.imprecis
            total.substitues.update(c.substitues)
            total.conserves_uhcd += c.conserves_uhcd
            total.conserves_sans_candidat += c.conserves_sans_candidat
        if len(self.branches) > 1:
            lignes += self._bloc("TOTAL", total)
        lignes.append("Constats :")
        lignes += [f"  - {c}" for c in self.constats]
        lignes += [
            "  - cohérence : le ghm2 a été groupé sur le DP d'origine ; après substitution, DP et "
            "GHM peuvent diverger finement — compromis accepté pour un corpus d'entraînement "
            "(même doctrine que les codes ajoutés par l'enrichissement).",
            "  - les codes substitués sont des codes observés du PMSI réel : le contrôle de fiches "
            "de l'aval (preparer_pool) s'applique tel quel.",
        ]
        return "\n".join(lignes)

    @staticmethod
    def _bloc(titre: str, c: CompteurBranche) -> list[str]:
        n_sub = sum(c.substitues.values())
        return [
            f"[{titre}] {c.lignes} ligne(s) — DP imprécis rencontrés : {c.imprecis}",
            f"    substitués : {n_sub}"
            + "".join(f" — niveau {k} {NIVEAUX[k]} : {c.substitues.get(k, 0)}" for k in (0, 1, 2)),
            f"    conservés UHCD : {c.conserves_uhcd}",
            f"    conservés faute de candidat précis : {c.conserves_sans_candidat}",
        ]


# ---------------------------------------------------------------- cœur

def substituer(corpus: pl.DataFrame, ref: pl.DataFrame, rapport: Rapport) -> pl.DataFrame:
    """Applique la règle ligne à ligne ; retourne le corpus substitué avec ses
    colonnes de traçabilité, et remplit ``rapport``."""
    manquantes = [c for c in COLONNES_CORPUS if c not in corpus.columns]
    if manquantes:
        raise ErreurSubstitution(
            f"corpus : colonne(s) manquante(s) {manquantes} (attendues : {list(COLONNES_CORPUS)})")
    candidats = Candidats.depuis_reference(ref)
    rapport.n_codes_imprecis_ref = len(candidats.imprecis)
    rapport.n_codes_precis_ref = ref.filter(~pl.col("imprecis"))["code"].n_unique()

    a_branche = "branche" in corpus.columns
    a_type_unite = "type_unite" in corpus.columns
    branche = (corpus["branche"].cast(pl.String) if a_branche
               else pl.Series([BRANCHE_UNIQUE] * corpus.height))
    type_unite = (corpus["type_unite"].cast(pl.String).str.strip_chars().str.to_uppercase()
                  if a_type_unite else pl.Series([None] * corpus.height, dtype=pl.String))
    dp = corpus["diag2"].cast(pl.String)
    cage = corpus["cage"].cast(pl.String).str.strip_chars()
    sexe = corpus["sexe"].cast(pl.String).str.strip_chars()
    ids = corpus["id_scenario"]

    est_imprecis = dp.is_in(list(candidats.imprecis)).fill_null(False)
    est_uhcd = (type_unite == UHCD).fill_null(False)

    nouveau: list[str | None] = dp.to_list()
    substitue = [False] * corpus.height
    repli: list[int | None] = [None] * corpus.height
    branches = rapport.branches
    for i, (b, imp, uhcd) in enumerate(zip(branche.to_list(), est_imprecis.to_list(), est_uhcd.to_list())):
        c = branches.setdefault(b if b is not None else "(nulle)", CompteurBranche())
        c.lignes += 1
        if not imp:
            continue
        c.imprecis += 1
        if uhcd:
            c.conserves_uhcd += 1
            continue
        code_origine = nouveau[i]
        cat = candidats.imprecis[code_origine]
        rng = np.random.default_rng(graine_ligne(ids[i]))
        code, niveau = candidats.tirer(cat, cage[i], sexe[i], rng)
        if code is None:
            c.conserves_sans_candidat += 1
            continue
        nouveau[i] = code
        substitue[i] = True
        repli[i] = niveau
        c.substitues[niveau] += 1

    # Constats
    if not a_type_unite:
        rapport.constats.append("type_unite absente du corpus : règle par défaut (substituer) "
                                "appliquée à toutes les lignes — aucune exemption UHCD.")
    else:
        for nom in sorted(branches):
            masque = branche == nom if nom != "(nulle)" else branche.is_null()
            n = int(masque.sum())
            nuls = int(type_unite.filter(masque).is_null().sum())
            valeurs = sorted(v for v in type_unite.filter(masque).unique().to_list() if v is not None)
            if nuls == n:
                rapport.constats.append(
                    f"type_unite nulle sur toute la branche {nom} ({n} lignes) : règle par défaut "
                    "(substituer) appliquée — un court programmé n'est pas une UHCD.")
            else:
                rapport.constats.append(
                    f"type_unite sur la branche {nom} : valeurs {valeurs}"
                    + (f", {nuls} nulle(s)" if nuls else "")
                    + ("" if UHCD in valeurs else " — aucune valeur UHCD : exemption sans objet."))
    n_ids = ids.n_unique()
    if n_ids < corpus.height:
        rapport.constats.append(
            f"id_scenario non unique par ligne ({n_ids} valeurs pour {corpus.height} lignes) : "
            "les lignes qui le partagent (variantes de contexte de séjour d'un même scénario) "
            "reçoivent la même graine, donc la même substitution.")
    n_sub = sum(sum(c.substitues.values()) for c in branches.values())
    n_niveau0 = sum(c.substitues.get(0, 0) for c in branches.values())
    if n_sub and not n_niveau0:
        rapport.constats.append(
            "aucune substitution au niveau 0 (cat, cage, sexe) : vérifier que cage et sexe sont "
            "encodés de la même façon dans le corpus et la référence.")

    return corpus.with_columns(
        pl.Series("diag2", nouveau, dtype=pl.String),
        dp.alias("dp_origine"),
        pl.Series("dp_substitue", substitue, dtype=pl.Boolean),
        pl.Series("repli_substitution", repli, dtype=pl.Int32),
    )


# ---------------------------------------------------------------- CLI

def executer(corpus_path: Path, ref_path: Path, out_path: Path | None = None) -> tuple[Path, Rapport]:
    """Lit, substitue, écrit le parquet et le rapport ; retourne (sortie, rapport)."""
    corpus_path = Path(corpus_path)
    ref_path = Path(ref_path)
    if out_path is None:
        out_path = corpus_path.with_name(corpus_path.stem + "_dp.parquet")
    out_path = Path(out_path)
    if not corpus_path.is_file():
        raise ErreurSubstitution(f"corpus introuvable : {corpus_path}")
    if not ref_path.is_file():
        raise ErreurSubstitution(f"référence introuvable : {ref_path}")
    try:
        corpus = pl.read_parquet(corpus_path)
    except Exception as exc:
        raise ErreurSubstitution(f"corpus illisible : {corpus_path} — {exc}") from None
    ref = charger_reference(ref_path)
    rapport = Rapport(corpus_path, ref_path, out_path)
    sortie = substituer(corpus, ref, rapport)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    sortie.write_parquet(out_path)
    rapport_path = out_path.with_suffix(".rapport.txt")
    rapport_path.write_text(rapport.texte() + "\n", encoding="utf-8")
    return out_path, rapport


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Substitue les DP imprécis d'un corpus de scénarios (fichier → fichier).")
    ap.add_argument("corpus", type=Path, help="corpus scenarios_<C>.parquet")
    ap.add_argument("--ref", type=Path, required=True,
                    help="data/aphp/referentials/ref_substitution_imprecis.parquet (agrégat seuillé)")
    ap.add_argument("--out", type=Path, default=None,
                    help="parquet de sortie (défaut : <corpus>_dp.parquet)")
    args = ap.parse_args()
    try:
        out, rapport = executer(args.corpus, args.ref, args.out)
    except ErreurSubstitution as exc:
        print("ERREUR :", exc, file=sys.stderr)
        return 2
    print(rapport.texte())
    print(f"\nÉcrit : {out}\nRapport : {out.with_suffix('.rapport.txt')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

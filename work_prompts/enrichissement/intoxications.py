"""Tabac et alcool dans les scénarios CIM-10 (AP-HP).

Complète un scénario avec un statut tabagique et un statut alcool cohérents
avec ses codes (F17.– / F10.–), en tirant au sort un code quand le scénario
n'en porte pas. Les codes sont au format interne fictomed : compact, sans
point (``F17202``, ``F1025``) — comme ``icd_primary_code`` /
``icd_secondary_code``.

Règle (décidée pour les scénarios)
----------------------------------
- Si le scénario porte déjà un code F17.– (resp. F10.–) : les paramètres
  descriptifs sont dérivés de ce code (statut, quantités, ancienneté).
- Sinon : avec probabilité ``p_tabac`` (resp. ``p_alcool``), un code est tiré
  selon la table pondérée (feuille Google « Répartition codes intoxications »)
  et ses paramètres sont dérivés ; sinon le patient est non-fumeur (resp.
  sans mésusage d'alcool), sans code.

Contexte de polyaddiction : si le scénario porte un code d'autre substance
(F11 opiacés, F12 cannabis, F14 cocaïne, F16 hallucinogènes — liste
``substances_poly`` configurable ; F13, F15, F19 peuvent y être ajoutés), les
probabilités passent à ``p_tabac_poly`` / ``p_alcool_poly`` (élevées), les
tirages sont biaisés vers les usages ACTIFS, et si aucun code F10 n'est tiré
le patient a au minimum une consommation d'alcool modérée régulière (statut
descriptif sans code).

Table de pondération : 14 codes. Quatre ne sont PAS des feuilles du
référentiel courant (F1724, F102, F1020, F1024) — présents dans les données
réelles mais sans fiche descriptive. Par défaut leur poids est redistribué
sur leurs feuilles (``feuilles_seulement=True``) ; passer ``False`` reproduit
le codage réel, non-feuilles comprises.

Les paramètres quantitatifs (cigarettes/jour, paquets-années, verres/jour,
ancienneté du sevrage) sont des ORDRES DE GRANDEUR plausibles — hypothèses
d'expert, à ajuster (voir ``_PARAMS``). Les définitions de rémission
récente/partielle/complète suivent les seuils indiqués, à confirmer contre
les définitions ATIH.

Sexe : encodage PMSI (1 = masculin, 2 = féminin), comme la colonne ``sexe``
de fictomed. Les probabilités par sexe s'écrivent ``{1: .., 2: ..}``.

Dépendances : numpy.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

# ---------------------------------------------------------------------------
# Table de pondération (feuille Google « Répartition codes intoxications »)
# Codes au format compact fictomed.
# ---------------------------------------------------------------------------
_TABLE: dict[str, tuple[str, float]] = {
    # tabac
    "F17202": ("Syndrome de dépendance au tabac, abstinent, rémission complète", 16),
    "F1724":  ("Syndrome de dépendance au tabac, utilisation actuelle", 22),
    "F1725":  ("Syndrome de dépendance au tabac, utilisation continue", 21),
    # alcool
    "F101":   ("Utilisation d'alcool nocive pour la santé", 2),
    "F102":   ("Syndrome de dépendance à l'alcool", 13),
    "F1020":  ("Dépendance à l'alcool, abstinent", 3),
    "F10200": ("Dépendance à l'alcool, abstinent, rémission récente", 5),
    "F10201": ("Dépendance à l'alcool, abstinent, rémission partielle", 1),
    "F10202": ("Dépendance à l'alcool, abstinent, rémission complète", 4),
    "F1024":  ("Dépendance à l'alcool, utilisation actuelle", 12),
    "F10240": ("Dépendance à l'alcool, utilisation actuelle, sans symptôme physique", 8),
    "F10241": ("Dépendance à l'alcool, utilisation actuelle, avec symptômes physiques", 3),
    "F1025":  ("Dépendance à l'alcool, utilisation continue", 13),
    "F1026":  ("Dépendance à l'alcool, utilisation épisodique", 2),
}

# Non-feuilles -> feuilles cibles (redistribution proportionnelle aux poids
# des feuilles quand elles sont dans la table, sinon parts indiquées).
_REDISTRIBUTION: dict[str, dict[str, float | None]] = {
    "F1724": {"F17240": 0.7, "F17241": 0.3},        # feuilles absentes de la table
    "F1020": {"F10200": None, "F10201": None, "F10202": None},
    "F1024": {"F10240": None, "F10241": None},
    "F102":  {"F10200": None, "F10201": None, "F10202": None,
              "F10240": None, "F10241": None, "F1025": None, "F1026": None},
}

_SUBSTANCES_POLY = ("F11", "F12", "F14", "F16")  # opiacés, cannabis, cocaïne, hallucinogènes
_CODES_ABSTINENTS = ("F17200", "F17201", "F17202", "F10200", "F10201", "F10202")

# ---------------------------------------------------------------------------
# Paramètres descriptifs — hypothèses d'expert, à ajuster
# ---------------------------------------------------------------------------
_PARAMS = {
    "verres_moderee": (2, 4),             # consommation modérée régulière (poly sans code F10)
    "poids_abstinent_poly": 0.2,          # facteur appliqué aux codes abstinents en contexte poly
    "age_debut_tabac": (14, 25),          # uniforme
    "cig_par_jour_median": 12, "cig_par_jour_sigma": 0.55,   # log-normale, bornée 3-40
    "sevrage_recent_mois": (1, 6),        # rémission récente  (à valider ATIH)
    "sevrage_complet_annees": (1, 30),    # rémission complète (>= 1 an, à valider)
    "verres_nocif": (3, 6),               # F101   — verres standard / jour
    "verres_dependance": (6, 15),         # F1024x / F1025
    "verres_episodique": (6, 12),         # F1026  — verres par épisode
    "episodes_par_semaine": (1, 3),       # F1026
    "age_debut_alcool": (16, 30),
}


def _ans(n: int) -> str:
    return f"{n} an" if n == 1 else f"{n} ans"


def _sexe_hf(sexe: int | str) -> str:
    """PMSI (1/2) -> clé interne 'H'/'F' ; 'H'/'F'/'M' acceptés par tolérance."""
    s = str(sexe).strip().upper()
    if s in ("1", "H", "M"):
        return "H"
    if s in ("2", "F"):
        return "F"
    raise ValueError(f"sexe PMSI attendu (1/2), reçu {sexe!r}")


@dataclass
class Tabac:
    statut: str                    # "non-fumeur" | "fumeur actif" | "ex-fumeur"
    code: str | None = None
    cigarettes_par_jour: int | None = None
    paquets_annees: int | None = None
    annees_tabagisme: int | None = None
    sevrage: str | None = None     # ex. "depuis 4 mois" / "depuis 12 ans"

    def as_ligne(self) -> str:
        """Description courte pour une ligne de prompt (« - Tabac : ... »)."""
        if self.statut == "non-fumeur":
            return "non-fumeur"
        if self.statut == "fumeur actif":
            return (f"tabagisme actif, {self.cigarettes_par_jour} cigarettes/jour, "
                    f"{self.paquets_annees} paquets-années")
        return (f"ex-fumeur, sevré {self.sevrage} "
                f"({self.paquets_annees} paquets-années)")

    def as_texte(self, sexe: int | str | None = None) -> str:
        if self.statut == "non-fumeur":
            feminin = sexe is not None and _sexe_hf(sexe) == "F"
            return "Non-fumeuse." if feminin else "Non-fumeur."
        if self.statut == "fumeur actif":
            return (f"Tabagisme actif, {self.cigarettes_par_jour} cigarettes/jour, "
                    f"{self.paquets_annees} paquets-années.")
        return (f"Tabagisme sevré {self.sevrage}, {self.paquets_annees} paquets-années "
                f"(consommation antérieure {self.cigarettes_par_jour} cig/jour).")


@dataclass
class Alcool:
    statut: str          # "pas de mésusage" | "consommation modérée" | "usage nocif"
                         # | "dépendance active" | "dépendance, abstinent"
                         # | "dépendance, usage épisodique"
    code: str | None = None
    verres_par_jour: int | None = None
    verres_par_episode: int | None = None
    episodes_par_semaine: int | None = None
    symptomes_physiques: bool = False
    sevrage: str | None = None
    annees_consommation: int | None = None

    def as_ligne(self) -> str:
        """Description courte pour une ligne de prompt (« - Alcool : ... »)."""
        if self.statut == "pas de mésusage":
            return "pas de mésusage"
        if self.statut == "consommation modérée":
            return f"consommation régulière modérée, environ {self.verres_par_jour} verres/jour"
        if self.statut == "usage nocif":
            return f"usage nocif, environ {self.verres_par_jour} verres/jour"
        if self.statut == "dépendance active":
            s = f"dépendance, environ {self.verres_par_jour} verres/jour"
            return s + (", symptômes physiques de sevrage" if self.symptomes_physiques else "")
        if self.statut == "dépendance, usage épisodique":
            return (f"dépendance à usage épisodique, {self.verres_par_episode} verres "
                    f"par épisode, {self.episodes_par_semaine} épisode(s)/semaine")
        return f"dépendance, abstinent {self.sevrage}"

    def as_texte(self) -> str:
        if self.statut == "pas de mésusage":
            return "Pas de mésusage d'alcool."
        if self.statut == "consommation modérée":
            return f"Consommation d'alcool régulière modérée, environ {self.verres_par_jour} verres/jour."
        if self.statut == "usage nocif":
            return f"Consommation d'alcool nocive, environ {self.verres_par_jour} verres/jour."
        if self.statut == "dépendance active":
            s = f"Dépendance à l'alcool, consommation actuelle d'environ {self.verres_par_jour} verres/jour"
            s += " avec symptômes physiques de sevrage." if self.symptomes_physiques else "."
            return s
        if self.statut == "dépendance, usage épisodique":
            return (f"Dépendance à l'alcool à usage épisodique, {self.verres_par_episode} verres "
                    f"par épisode, {self.episodes_par_semaine} épisode(s)/semaine.")
        return f"Dépendance à l'alcool, abstinent {self.sevrage}."


@dataclass
class Intoxications:
    tabac: Tabac
    alcool: Alcool
    codes_ajoutes: list[str] = field(default_factory=list)
    polyaddiction: bool = False

    def as_texte(self, sexe: int | str | None = None) -> str:
        return f"{self.tabac.as_texte(sexe)} {self.alcool.as_texte()}"

    def as_dict(self) -> dict:
        return {"tabac": self.tabac.__dict__, "alcool": self.alcool.__dict__,
                "codes_ajoutes": list(self.codes_ajoutes),
                "polyaddiction": self.polyaddiction}


class SimulateurIntoxications:
    """Tirage et dérivation des statuts tabac / alcool d'un scénario.

    Parameters
    ----------
    seed:
        Graine du générateur (déterminisme à séquence d'appels fixée).
    p_tabac, p_alcool:
        Probabilité de tirer un code quand le scénario n'en porte pas — un
        float, ou un dict ``{1: .., 2: ..}`` (sexe PMSI) pour moduler.
    p_tabac_poly, p_alcool_poly:
        Idem en contexte de polyaddiction (présence d'un code d'une des
        ``substances_poly``).
    feuilles_seulement:
        Redistribue le poids des codes non-feuilles sur leurs feuilles
        (défaut) ; ``False`` reproduit le codage réel.
    """

    def __init__(self, seed: int | None = None, p_tabac: float | dict = 0.30,
                 p_alcool: float | dict = 0.10, feuilles_seulement: bool = True,
                 p_tabac_poly: float | dict = 0.90, p_alcool_poly: float | dict = 0.70,
                 substances_poly: tuple[str, ...] = _SUBSTANCES_POLY):
        self.rng = np.random.default_rng(seed)
        self.p_tabac, self.p_alcool = p_tabac, p_alcool
        self.p_tabac_poly, self.p_alcool_poly = p_tabac_poly, p_alcool_poly
        self.substances_poly = tuple(substances_poly)
        self.table = self._table(feuilles_seulement)

    # ----- table pondérée --------------------------------------------------
    @staticmethod
    def _table(feuilles_seulement: bool) -> dict[str, float]:
        poids = {c: float(w) for c, (_, w) in _TABLE.items()}
        if not feuilles_seulement:
            return poids
        for parent, cibles in _REDISTRIBUTION.items():
            w = poids.pop(parent, 0.0)
            if not w:
                continue
            explicites = {c: p for c, p in cibles.items() if p is not None}
            if explicites:
                parts = explicites
            else:   # proportionnel aux poids existants des feuilles cibles
                base = {c: poids.get(c, 0.0) for c in cibles}
                tot = sum(base.values())
                parts = ({c: v / tot for c, v in base.items()} if tot
                         else {c: 1 / len(cibles) for c in cibles})
            for c, p in parts.items():
                poids[c] = poids.get(c, 0.0) + w * p
        return poids

    def _tirer_code(self, prefixe: str, poly: bool = False) -> str:
        codes = [c for c in self.table if c.startswith(prefixe)]
        w = np.array([self.table[c]
                      * (_PARAMS["poids_abstinent_poly"]
                         if poly and c in _CODES_ABSTINENTS else 1.0)
                      for c in codes])
        return str(self.rng.choice(codes, p=w / w.sum()))

    def _proba(self, p: float | dict, sexe_pmsi: int) -> float:
        return p[sexe_pmsi] if isinstance(p, dict) else p

    # ----- dérivation des paramètres depuis un code ------------------------
    def _tabac_depuis_code(self, code: str, age: int) -> Tabac:
        lo, hi = _PARAMS["age_debut_tabac"]
        debut = int(self.rng.integers(lo, min(hi, max(lo + 1, age - 1)) + 1))
        cig = int(np.clip(round(np.exp(self.rng.normal(
            np.log(_PARAMS["cig_par_jour_median"]), _PARAMS["cig_par_jour_sigma"]))), 3, 40))
        if code.startswith("F1720"):           # abstinent
            if code == "F17200":
                mois = int(self.rng.integers(*_PARAMS["sevrage_recent_mois"]))
                sevrage, annees_sevre = f"depuis {mois} mois", 0
            elif code == "F17201":
                mois = int(self.rng.integers(3, 12))
                sevrage, annees_sevre = f"depuis {mois} mois (rechutes occasionnelles)", 0
            else:
                a_max = max(1, min(_PARAMS["sevrage_complet_annees"][1], age - debut - 1))
                annees_sevre = int(self.rng.integers(1, a_max + 1))
                sevrage = f"depuis {_ans(annees_sevre)}"
            duree = max(1, age - debut - annees_sevre)
            return Tabac("ex-fumeur", code, cig, max(1, round(cig / 20 * duree)), duree, sevrage)
        duree = max(1, age - debut)
        return Tabac("fumeur actif", code, cig, max(1, round(cig / 20 * duree)), duree)

    def _alcool_depuis_code(self, code: str, age: int) -> Alcool:
        lo, hi = _PARAMS["age_debut_alcool"]
        duree = max(1, age - int(self.rng.integers(lo, min(hi, max(lo + 1, age - 1)) + 1)))
        if code == "F101":
            return Alcool("usage nocif", code,
                          verres_par_jour=int(self.rng.integers(*_PARAMS["verres_nocif"])),
                          annees_consommation=duree)
        if code == "F1026":
            return Alcool("dépendance, usage épisodique", code,
                          verres_par_episode=int(self.rng.integers(*_PARAMS["verres_episodique"])),
                          episodes_par_semaine=int(self.rng.integers(*_PARAMS["episodes_par_semaine"])),
                          annees_consommation=duree)
        if code.startswith("F1020"):
            if code == "F10200":
                sevrage = f"depuis {int(self.rng.integers(*_PARAMS['sevrage_recent_mois']))} mois"
            elif code == "F10201":
                sevrage = f"depuis {int(self.rng.integers(3, 12))} mois (rechutes occasionnelles)"
            else:
                sevrage = f"depuis {_ans(int(self.rng.integers(1, max(2, min(20, duree)))))}"
            return Alcool("dépendance, abstinent", code, sevrage=sevrage,
                          annees_consommation=duree)
        # F1024x, F1025 (et non-feuilles F102 / F1024 si conservées)
        return Alcool("dépendance active", code,
                      verres_par_jour=int(self.rng.integers(*_PARAMS["verres_dependance"])),
                      symptomes_physiques=(code == "F10241"),
                      annees_consommation=duree)

    # ----- point d'entrée ---------------------------------------------------
    def completer(self, codes_scenario: list[str], age: int, sexe: int | str) -> Intoxications:
        """Complète un scénario : dérive tabac/alcool des codes présents, ou en tire.

        ``codes_scenario`` : DP + DAS, codes compacts fictomed. ``sexe`` :
        PMSI 1/2. Les codes ajoutés le sont TOUJOURS en DAS (le simulateur
        ne retourne que la liste — l'appelant les range).
        """
        sexe_pmsi = 1 if _sexe_hf(sexe) == "H" else 2
        codes = [str(c).strip().upper() for c in codes_scenario if str(c).strip()]
        ajoutes: list[str] = []
        poly = any(c.startswith(self.substances_poly) for c in codes)
        p_t = self.p_tabac_poly if poly else self.p_tabac
        p_a = self.p_alcool_poly if poly else self.p_alcool

        f17 = next((c for c in codes if c.startswith("F17")), None)
        if f17 is None and self.rng.random() < self._proba(p_t, sexe_pmsi):
            f17 = self._tirer_code("F17", poly)
            ajoutes.append(f17)
        tabac = self._tabac_depuis_code(f17, age) if f17 else Tabac("non-fumeur")

        f10 = next((c for c in codes if c.startswith("F10")), None)
        if f10 is None and self.rng.random() < self._proba(p_a, sexe_pmsi):
            f10 = self._tirer_code("F10", poly)
            ajoutes.append(f10)
        if f10:
            alcool = self._alcool_depuis_code(f10, age)
        elif poly:   # au minimum une consommation modérée régulière, sans code
            alcool = Alcool("consommation modérée",
                            verres_par_jour=int(self.rng.integers(*_PARAMS["verres_moderee"])))
        else:
            alcool = Alcool("pas de mésusage")

        return Intoxications(tabac, alcool, ajoutes, polyaddiction=poly)


# ---------------------------------------------------------------------------
# Auto-contrôle : fréquences attendues (tests épidémiologiques du module)
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    sim = SimulateurIntoxications(seed=11, p_tabac={1: 0.35, 2: 0.25},
                                  p_alcool={1: 0.14, 2: 0.06})
    print("Table pondérée effective (feuilles seulement) :")
    for c, w in sorted(sim.table.items()):
        print(f"  {c:8} {w:5.1f}")
    print("\nScénario sans code d'intoxication, H 58 ans :")
    for _ in range(4):
        r = sim.completer(["E1120", "N083", "I10"], 58, 1)
        print(" ", r.codes_ajoutes, "->", r.as_texte(1))
    print("\nScénario portant déjà F1725 et F10202, F 47 ans :")
    r = sim.completer(["C341", "F1725", "F10202"], 47, 2)
    print(" ", r.codes_ajoutes, "->", r.as_texte(2))
    print("\nScénario avec F1124 (opiacés, usage actuel), H 34 ans — contexte poly :")
    for _ in range(4):
        r = sim.completer(["F1124", "B182"], 34, 1)
        print(" ", r.codes_ajoutes, "->", r.as_texte(1))
    n = 20_000
    t = a = ab = 0
    for _ in range(n):
        r = sim.completer(["F121"], 30, 2)
        t += r.tabac.code is not None
        a += r.alcool.code is not None
        ab += (r.alcool.code in _CODES_ABSTINENTS) or (r.tabac.code in _CODES_ABSTINENTS)
    print(f"  poly (F121, F 30 ans) : F17 tiré {100*t/n:.1f} % (attendu 90) | "
          f"F10 tiré {100*a/n:.1f} % (attendu 70) | "
          f"au moins un code abstinent {100*ab/n:.1f} %")
    print("\nContrôle des fréquences sur 20 000 scénarios H 60 ans :")
    n = 20_000
    t = a = 0
    for _ in range(n):
        r = sim.completer(["I210"], 60, 1)
        t += r.tabac.code is not None
        a += r.alcool.code is not None
    print(f"  code F17 ajouté : {100*t/n:.1f} % (attendu 35)  |  "
          f"code F10 ajouté : {100*a/n:.1f} % (attendu 14)")

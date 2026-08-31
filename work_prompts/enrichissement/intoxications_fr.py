"""
intoxications_fr.py — Tabac et alcool dans les scénarios CIM-10 : complète un
scénario avec un statut tabagique et un statut alcool cohérents avec ses codes
(F17.– / F10.–), en tirant au sort un code quand le scénario n'en porte pas.

Règle (décidée pour les scénarios)
----------------------------------
- Si le scénario porte déjà un code F17.– (resp. F10.–) : les paramètres
  descriptifs sont dérivés de ce code (statut, quantités, ancienneté).
- Sinon : avec probabilité p_tabac (resp. p_alcool), un code est tiré selon
  la table pondérée (feuille Google « Répartition codes intoxications ») et
  ses paramètres sont dérivés ; sinon le patient est non-fumeur (resp. sans
  mésusage d'alcool), sans code.

Contexte de polyaddiction : si le scénario porte un code d'autre substance
(F11 opiacés, F12 cannabis, F14 cocaïne, F16 hallucinogènes — liste
`substances_poly` configurable ; F13, F15, F19 peuvent y être ajoutés), les
probabilités passent à p_tabac_poly / p_alcool_poly (élevées), les tirages
sont biaisés vers les usages ACTIFS, et si aucun code F10 n'est tiré le
patient a au minimum une consommation d'alcool modérée régulière (statut
descriptif sans code).

Table de pondération : 14 codes. Quatre ne sont PAS des feuilles du
référentiel courant (F17.24, F10.2, F10.20, F10.24) — présents dans les
données réelles mais sans fiche descriptive. Par défaut leur poids est
redistribué sur leurs feuilles (`feuilles_seulement=True`) ; passer False
reproduit le codage réel, non-feuilles comprises.

Les paramètres quantitatifs (cigarettes/jour, paquets-années, verres/jour,
ancienneté du sevrage) sont des ORDRES DE GRANDEUR plausibles — hypothèses
d'expert, à ajuster (voir `_PARAMS`). Les définitions de rémission
récente/partielle/complète suivent les seuils indiqués, à confirmer contre
les définitions ATIH.

Dépendances : numpy.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

# ---------------------------------------------------------------------------
# Table de pondération (feuille Google, codes reformatés avec point)
# ---------------------------------------------------------------------------
_TABLE = {
    # tabac
    "F17.202": ("Syndrome de dépendance au tabac, abstinent, rémission complète", 16),
    "F17.24":  ("Syndrome de dépendance au tabac, utilisation actuelle", 22),
    "F17.25":  ("Syndrome de dépendance au tabac, utilisation continue", 21),
    # alcool
    "F10.1":   ("Utilisation d'alcool nocive pour la santé", 2),
    "F10.2":   ("Syndrome de dépendance à l'alcool", 13),
    "F10.20":  ("Dépendance à l'alcool, abstinent", 3),
    "F10.200": ("Dépendance à l'alcool, abstinent, rémission récente", 5),
    "F10.201": ("Dépendance à l'alcool, abstinent, rémission partielle", 1),
    "F10.202": ("Dépendance à l'alcool, abstinent, rémission complète", 4),
    "F10.24":  ("Dépendance à l'alcool, utilisation actuelle", 12),
    "F10.240": ("Dépendance à l'alcool, utilisation actuelle, sans symptôme physique", 8),
    "F10.241": ("Dépendance à l'alcool, utilisation actuelle, avec symptômes physiques", 3),
    "F10.25":  ("Dépendance à l'alcool, utilisation continue", 13),
    "F10.26":  ("Dépendance à l'alcool, utilisation épisodique", 2),
}

# Non-feuilles → feuilles cibles (redistribution proportionnelle aux poids
# des feuilles quand elles sont dans la table, sinon parts indiquées)
_REDISTRIBUTION = {
    "F17.24": {"F17.240": 0.7, "F17.241": 0.3},          # feuilles absentes de la table
    "F10.20": {"F10.200": None, "F10.201": None, "F10.202": None},
    "F10.24": {"F10.240": None, "F10.241": None},
    "F10.2":  {"F10.200": None, "F10.201": None, "F10.202": None,
               "F10.240": None, "F10.241": None, "F10.25": None, "F10.26": None},
}

_SUBSTANCES_POLY = ("F11", "F12", "F14", "F16")   # opiacés, cannabis, cocaïne, hallucinogènes
_CODES_ABSTINENTS = ("F17.200", "F17.201", "F17.202", "F10.200", "F10.201", "F10.202")

# ---------------------------------------------------------------------------
# Paramètres descriptifs — hypothèses d'expert, à ajuster
# ---------------------------------------------------------------------------
_PARAMS = {
    "verres_moderee": (2, 4),             # consommation modérée régulière (poly sans code F10)
    "poids_abstinent_poly": 0.2,          # facteur appliqué aux codes abstinents en contexte poly
    "age_debut_tabac": (14, 25),          # uniforme
    "cig_par_jour_median": 12, "cig_par_jour_sigma": 0.55,   # log-normale, bornée 3-40
    "sevrage_recent_mois": (1, 6),        # rémission récente  (à valider ATIH)
    "sevrage_complet_annees": (1, 30),    # rémission complète (≥ 1 an, à valider)
    "verres_nocif": (3, 6),               # F10.1  — verres standard / jour
    "verres_dependance": (6, 15),         # F10.24x / F10.25
    "verres_episodique": (6, 12),         # F10.26 — verres par épisode
    "episodes_par_semaine": (1, 3),       # F10.26
    "age_debut_alcool": (16, 30),
}


@dataclass
class Tabac:
    statut: str                    # "non-fumeur" | "fumeur actif" | "ex-fumeur"
    code: str | None = None
    cigarettes_par_jour: int | None = None
    paquets_annees: int | None = None
    annees_tabagisme: int | None = None
    sevrage: str | None = None     # ex. "depuis 4 mois" / "depuis 12 ans"

    def as_texte(self, sexe: str | None = None) -> str:
        if self.statut == "non-fumeur":
            return "Non-fumeuse." if sexe and sexe.upper().startswith("F") else "Non-fumeur."
        if self.statut == "fumeur actif":
            return (f"Tabagisme actif, {self.cigarettes_par_jour} cigarettes/jour, "
                    f"{self.paquets_annees} paquets-années.")
        return (f"Tabagisme sevré {self.sevrage}, {self.paquets_annees} paquets-années "
                f"(consommation antérieure {self.cigarettes_par_jour} cig/jour).")


@dataclass
class Alcool:
    statut: str          # "pas de mésusage" | "usage nocif" | "dépendance active" | "dépendance, abstinent" | "dépendance, usage épisodique"
    code: str | None = None
    verres_par_jour: int | None = None
    verres_par_episode: int | None = None
    episodes_par_semaine: int | None = None
    symptomes_physiques: bool = False
    sevrage: str | None = None
    annees_consommation: int | None = None

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

    def as_texte(self, sexe: str | None = None) -> str:
        return f"{self.tabac.as_texte(sexe)} {self.alcool.as_texte()}"

    def as_dict(self) -> dict:
        return {"tabac": self.tabac.__dict__, "alcool": self.alcool.__dict__,
                "codes_ajoutes": list(self.codes_ajoutes), "polyaddiction": self.polyaddiction}


class SimulateurIntoxications:
    def __init__(self, seed: int | None = None, p_tabac: float | dict = 0.30,
                 p_alcool: float | dict = 0.10, feuilles_seulement: bool = True,
                 p_tabac_poly: float | dict = 0.90, p_alcool_poly: float | dict = 0.70,
                 substances_poly: tuple[str, ...] = _SUBSTANCES_POLY):
        """p_tabac / p_alcool : probabilité de tirer un code quand le scénario n'en
        porte pas — un float, ou un dict {'H': ., 'F': .} pour moduler par sexe.
        p_tabac_poly / p_alcool_poly : idem en contexte de polyaddiction (présence
        d'un code d'une des `substances_poly`)."""
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
                parts = {c: v / tot for c, v in base.items()} if tot else {c: 1 / len(cibles) for c in cibles}
            for c, p in parts.items():
                poids[c] = poids.get(c, 0.0) + w * p
        return poids

    def _tirer_code(self, prefixe: str, poly: bool = False) -> str:
        codes = [c for c in self.table if c.startswith(prefixe)]
        w = np.array([self.table[c] * (_PARAMS["poids_abstinent_poly"] if poly and c in _CODES_ABSTINENTS else 1.0)
                      for c in codes])
        return str(self.rng.choice(codes, p=w / w.sum()))

    def _proba(self, p, sexe: str) -> float:
        return p[sexe] if isinstance(p, dict) else p

    # ----- dérivation des paramètres depuis un code ------------------------
    def _tabac_depuis_code(self, code: str, age: int) -> Tabac:
        lo, hi = _PARAMS["age_debut_tabac"]
        debut = int(self.rng.integers(lo, min(hi, max(lo + 1, age - 1)) + 1))
        cig = int(np.clip(round(np.exp(self.rng.normal(np.log(_PARAMS["cig_par_jour_median"]),
                                                      _PARAMS["cig_par_jour_sigma"]))), 3, 40))
        if code.startswith("F17.20"):          # abstinent
            if code == "F17.200":
                mois = int(self.rng.integers(*_PARAMS["sevrage_recent_mois"]))
                sevrage, annees_sevre = f"depuis {mois} mois", 0
            elif code == "F17.201":
                mois = int(self.rng.integers(3, 12)); sevrage, annees_sevre = f"depuis {mois} mois (rechutes occasionnelles)", 0
            else:
                a_max = max(1, min(_PARAMS["sevrage_complet_annees"][1], age - debut - 1))
                annees_sevre = int(self.rng.integers(1, a_max + 1))
                sevrage = f"depuis {annees_sevre} ans"
            duree = max(1, age - debut - annees_sevre)
            return Tabac("ex-fumeur", code, cig, max(1, round(cig / 20 * duree)), duree, sevrage)
        duree = max(1, age - debut)
        return Tabac("fumeur actif", code, cig, max(1, round(cig / 20 * duree)), duree)

    def _alcool_depuis_code(self, code: str, age: int) -> Alcool:
        lo, hi = _PARAMS["age_debut_alcool"]
        duree = max(1, age - int(self.rng.integers(lo, min(hi, max(lo + 1, age - 1)) + 1)))
        if code == "F10.1":
            return Alcool("usage nocif", code, verres_par_jour=int(self.rng.integers(*_PARAMS["verres_nocif"])),
                          annees_consommation=duree)
        if code == "F10.26":
            return Alcool("dépendance, usage épisodique", code,
                          verres_par_episode=int(self.rng.integers(*_PARAMS["verres_episodique"])),
                          episodes_par_semaine=int(self.rng.integers(*_PARAMS["episodes_par_semaine"])),
                          annees_consommation=duree)
        if code.startswith("F10.20"):
            if code == "F10.200":
                sevrage = f"depuis {int(self.rng.integers(*_PARAMS['sevrage_recent_mois']))} mois"
            elif code == "F10.201":
                sevrage = f"depuis {int(self.rng.integers(3, 12))} mois (rechutes occasionnelles)"
            else:
                sevrage = f"depuis {int(self.rng.integers(1, max(2, min(20, duree))))} ans"
            return Alcool("dépendance, abstinent", code, sevrage=sevrage, annees_consommation=duree)
        # F10.24x, F10.25 (et non-feuilles F10.2 / F10.24 si conservées)
        return Alcool("dépendance active", code, verres_par_jour=int(self.rng.integers(*_PARAMS["verres_dependance"])),
                      symptomes_physiques=(code == "F10.241"), annees_consommation=duree)

    # ----- point d'entrée ---------------------------------------------------
    def completer(self, codes_scenario: list[str], age: int, sexe: str) -> Intoxications:
        """Complète un scénario : dérive tabac/alcool des codes présents, ou en tire."""
        sexe = sexe.upper()[0]
        codes = [c.strip().upper() for c in codes_scenario]
        ajoutes: list[str] = []
        poly = any(c.startswith(self.substances_poly) for c in codes)
        p_t = self.p_tabac_poly if poly else self.p_tabac
        p_a = self.p_alcool_poly if poly else self.p_alcool

        f17 = next((c for c in codes if c.startswith("F17")), None)
        if f17 is None and self.rng.random() < self._proba(p_t, sexe):
            f17 = self._tirer_code("F17", poly); ajoutes.append(f17)
        tabac = self._tabac_depuis_code(f17, age) if f17 else Tabac("non-fumeur")

        f10 = next((c for c in codes if c.startswith("F10")), None)
        if f10 is None and self.rng.random() < self._proba(p_a, sexe):
            f10 = self._tirer_code("F10", poly); ajoutes.append(f10)
        if f10:
            alcool = self._alcool_depuis_code(f10, age)
        elif poly:   # au minimum une consommation modérée régulière, sans code
            alcool = Alcool("consommation modérée", verres_par_jour=int(self.rng.integers(*_PARAMS["verres_moderee"])))
        else:
            alcool = Alcool("pas de mésusage")

        return Intoxications(tabac, alcool, ajoutes, polyaddiction=poly)


# ---------------------------------------------------------------------------
if __name__ == "__main__":
    sim = SimulateurIntoxications(seed=11, p_tabac={"H": 0.35, "F": 0.25}, p_alcool={"H": 0.14, "F": 0.06})
    print("Table pondérée effective (feuilles seulement) :")
    for c, w in sorted(sim.table.items()):
        print(f"  {c:8} {w:5.1f}")
    print("\nScénario sans code d'intoxication, H 58 ans :")
    for _ in range(4):
        r = sim.completer(["E11.20", "N08.3", "I10"], 58, "H")
        print(" ", r.codes_ajoutes, "→", r.as_texte())
    print("\nScénario portant déjà F17.25 et F10.202, F 47 ans :")
    r = sim.completer(["C34.1", "F17.25", "F10.202"], 47, "F")
    print(" ", r.codes_ajoutes, "→", r.as_texte())
    print("\nScénario avec F11.24 (opiacés, usage actuel), H 34 ans — contexte poly :")
    for _ in range(4):
        r = sim.completer(["F11.24", "B18.2"], 34, "H")
        print(" ", r.codes_ajoutes, "→", r.as_texte())
    n = 20_000; t = a = ab = 0
    for _ in range(n):
        r = sim.completer(["F12.1"], 30, "F"); t += r.tabac.code is not None
        a += r.alcool.code is not None; ab += r.alcool.code in _CODES_ABSTINENTS or (r.tabac.code in _CODES_ABSTINENTS)
    print(f"  poly (F12.1, F 30 ans) : F17 tiré {100*t/n:.1f} % (attendu 90) | F10 tiré {100*a/n:.1f} % (attendu 70)"
          f" | au moins un code abstinent {100*ab/n:.1f} %")
    print("\nContrôle des fréquences sur 20 000 scénarios H 60 ans :")
    n = 20_000; t = a = 0
    for _ in range(n):
        r = sim.completer(["I21.0"], 60, "H"); t += r.tabac.code is not None; a += r.alcool.code is not None
    print(f"  code F17 ajouté : {100*t/n:.1f} % (attendu 35)  |  code F10 ajouté : {100*a/n:.1f} % (attendu 14)")

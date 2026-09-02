"""Taille, poids et IMC d'adultes français, pour l'enrichissement de
scénarios CIM-10 (AP-HP). Les codes sont au format interne fictomed :
compact, sans point (``E6604``, ``E440``).

Sources
-------
- Esteban 2014-2016 (Gorokhova et al., BEH 2021;10:166-75, tableau 5) :
  répartition de l'IMC MESURÉ par classe OMS, par sexe et par âge.
- Obépi-Roche 2020 (Ligue contre l'obésité) : tailles moyennes 176,6 cm (H)
  et 163,9 cm (F) ; tranches de taille validant les écarts-types 7 / 6,5 cm ;
  poids moyens 81,2 / 67,3 kg et IMC moyen 25,5 (utilisés en contrôle).
- Obépi 2012 : sous-classes d'obésité (grades I/II/III ~ 71 / 21 / 8 % des obèses).

Méthode
-------
1. Taille ~ Normale(mu(sexe, âge), sd_sexe). Pente d'âge -0,10 cm/an autour de
   45 ans (effet cohorte + tassement) — HYPOTHÈSE documentée, non ajustée.
2. Classe d'IMC tirée selon les proportions Esteban croisées sexe x âge
   (croisement par ajustement proportionnel des deux marges publiées).
3. IMC tiré dans la classe par log-normale tronquée (forme intra-classe
   lisse, prévalences des classes exactes par construction).
4. Poids = IMC x taille². Arrondis réalistes (cm, kg entiers).

Contraintes : ``imc_min`` / ``imc_max`` (ou un code E660x, E669x, E43 ou
E440 déjà présent dans le scénario) forcent le tirage dans l'intervalle voulu — c'est
l'usage principal pour les scénarios.

Convention de scénario (doctrine révisée) : le tirage LIBRE (sans code) ne
produit jamais de dénutrition (IMC < 18,5), état supposé toujours codé — elle
n'entre qu'explicitement via ``code=``. Toute classe tirée à IMC >= 25 est
CODÉE en DAS par l'appelant : E6603 [25,30[, E6604 [30,35[, E6605 [35,40[,
E6606 [40,50[, E6607 [50,60[ — le grade IV est tirable (poids 0.01)
puisque systématiquement codé. ``exclure_codees=False`` restitue la
distribution populationnelle complète (maigreur comprise).

Sexe : encodage PMSI (1 = masculin, 2 = féminin), comme la colonne ``sexe``
de fictomed.

Dépendances : numpy uniquement (statistics.NormalDist pour la CDF inverse).

Limites : adultes >= 18 ans ; au-delà de 74 ans les proportions sont
EXTRAPOLÉES (Esteban s'arrête à 74) — voir ``_PROP_75PLUS``, à valider.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from statistics import NormalDist

import numpy as np

from .intoxications import _sexe_hf

# ---------------------------------------------------------------------------
# Paramètres — tous documentés par leur source
# ---------------------------------------------------------------------------

# Taille (cm) : moyenne Obépi 2020, sd validé sur les tranches Obépi
_TAILLE = {"H": (176.6, 7.0), "F": (163.9, 6.5)}
_PENTE_TAILLE_PAR_AN = -0.10   # cm par année d'âge, centré à 45 ans (hypothèse)
_AGE_CENTRE = 45

# Bornes des classes OMS + sous-classes d'obésité (ATIH E660x)
_CLASSES = ["maigreur", "normal", "surpoids", "obesite"]
_BORNES = {"maigreur": (14.0, 18.5), "normal": (18.5, 25.0),
           "surpoids": (25.0, 30.0), "obesite": (30.0, 60.0)}

# Esteban tableau 5 (IMC mesuré) — proportions en %
_PROP_SEXE = {"H": [2.1, 43.5, 37.5, 16.9], "F": [2.5, 53.9, 26.3, 17.2]}
_PROP_AGE = {"18-29": [5.4, 64.3, 22.9, 7.5],
             "30-54": [1.9, 50.7, 30.1, 17.4],
             "55-74": [1.5, 39.5, 38.2, 20.8]}
_EFFECTIFS_AGE = {"18-29": 166, "30-54": 1173, "55-74": 1090}
# >= 75 ans : EXTRAPOLATION (sarcopénie, baisse de l'obésité après 80 ans) — à valider
_PROP_75PLUS = [4.0, 44.0, 36.0, 16.0]

# Diabète de type 2 (E11) : corpulence très décalée vers le haut. Ordres de
# grandeur Entred 2007 (obésité ~41 %, surpoids ~39 %, normal ~19 %) — HYPOTHÈSE
# à ajuster sur données réelles. Sous-classes d'obésité plus sévères aussi.
_PROP_DNID = [1.0, 19.0, 39.0, 41.0]
_SOUS_OBESITE_DNID = {"E6604": 0.62, "E6605": 0.25, "E6606": 0.12, "E6607": 0.01}

# Sous-classes d'obésité, part des obèses (Obépi 2012 : 10,5 / 3,1 / 1,2 % pop.)
_SOUS_OBESITE = {"E6604": ((30.0, 35.0), 0.70),   # grade I
                 "E6605": ((35.0, 40.0), 0.21),   # grade II
                 "E6606": ((40.0, 50.0), 0.08),   # grade III
                 "E6607": ((50.0, 60.0), 0.01)}   # >= 50

# Forme intra-classe : log-normale ajustée sur Esteban (sexe)
_LOGN = {"H": (3.2386, 0.1677), "F": (3.2027, 0.1843)}

# Contraintes d'IMC par code déjà présent dans le scénario. Seuils HAS de
# dénutrition (à confirmer contre les candidates DEN-10..16). La série E669x
# (« sans précision », fréquente dans les données AP-HP) porte ses bornes
# dans les libellés ATIH : E6693 = surpoids [25,30[ ; E6694-97 = obésité par
# tranche ; E6690-92 = anciennes extensions SU17 ; E6699 (IMC non précisé)
# est bornée [30,50[ — le grade IV est supposé toujours codé explicitement.
_CONTRAINTES_CODE = {
    "E6603": lambda age: (25.0, 30.0),
    "E6604": lambda age: (30.0, 35.0),
    "E6605": lambda age: (35.0, 40.0),
    "E6606": lambda age: (40.0, 50.0),
    "E6607": lambda age: (50.0, 60.0),
    "E6690": lambda age: (30.0, 40.0),   # SU17 — obésité SP [30,40[
    "E6691": lambda age: (40.0, 50.0),   # SU17 — obésité SP [40,50[
    "E6692": lambda age: (50.0, 60.0),   # SU17 — obésité SP >= 50
    "E6693": lambda age: (25.0, 30.0),   # surpoids sans précision
    "E6694": lambda age: (30.0, 35.0),   # obésité SP [30,35[
    "E6695": lambda age: (35.0, 40.0),   # obésité SP [35,40[
    "E6696": lambda age: (40.0, 50.0),   # obésité SP [40,50[
    "E6697": lambda age: (50.0, 60.0),   # obésité SP >= 50
    "E6699": lambda age: (30.0, 50.0),   # obésité SP, IMC non précisé
    "E43":   lambda age: (14.0, 17.0) if age < 70 else (14.0, 20.0),   # sévère
    "E440":  lambda age: (17.0, 18.5) if age < 70 else (20.0, 22.0),   # modérée
}


def _tranche_age(age: int) -> str:
    if age < 18:
        raise ValueError("Simulateur adulte uniquement (âge >= 18).")
    if age <= 29:
        return "18-29"
    if age <= 54:
        return "30-54"
    if age <= 74:
        return "55-74"
    return "75+"


def _proportions(sexe_hf: str, age: int) -> np.ndarray:
    """Classe d'IMC croisée sexe x âge : P(c|s,a) proportionnel à P(c|s)·P(c|a)/P(c)."""
    ps = np.array(_PROP_SEXE[sexe_hf]) / 100
    tranche = _tranche_age(age)
    if tranche == "75+":
        pa = np.array(_PROP_75PLUS) / 100
    else:
        pa = np.array(_PROP_AGE[tranche]) / 100
    w = np.array(list(_EFFECTIFS_AGE.values()), dtype=float)
    p_all = sum(wi * np.array(_PROP_AGE[k]) / 100
                for wi, k in zip(w, _EFFECTIFS_AGE)) / w.sum()
    p = ps * pa / p_all
    return p / p.sum()


def _lognorm_tronquee(rng: np.random.Generator, mu: float, sigma: float,
                      lo: float, hi: float) -> float:
    """Tirage d'une log-normale tronquée à [lo, hi[ par CDF inverse."""
    nd = NormalDist(mu, sigma)
    a, b = nd.cdf(math.log(lo)), nd.cdf(math.log(hi))
    u = rng.uniform(a, b)
    return math.exp(nd.inv_cdf(u))


@dataclass
class Anthropometrie:
    sexe: int              # PMSI : 1 = masculin, 2 = féminin
    age: int
    taille_cm: int
    poids_kg: int
    imc: float
    classe_imc: str
    code_e66: str | None   # sous-classe ATIH (compact) si surpoids/obésité

    def as_dict(self) -> dict:
        return self.__dict__.copy()


class SimulateurAnthropometrie:
    """Tirage de taille / poids / IMC cohérents avec un scénario CIM-10."""

    def __init__(self, seed: int | None = None):
        self.rng = np.random.default_rng(seed)

    # ----- taille -----------------------------------------------------------
    def taille(self, sexe: int | str, age: int) -> int:
        mu, sd = _TAILLE[_sexe_hf(sexe)]
        mu += _PENTE_TAILLE_PAR_AN * (age - _AGE_CENTRE)
        return int(round(self.rng.normal(mu, sd)))

    # ----- IMC --------------------------------------------------------------
    def imc(self, sexe: int | str, age: int,
            imc_min: float | None = None, imc_max: float | None = None,
            exclure_codees: bool = True, proportions=None,
            sous_obesite=None) -> tuple[float, float, float]:
        """Retourne (imc, lo, hi) — l'IMC tiré et l'intervalle [lo, hi[ visé.

        IMC tiré selon Esteban. Par défaut (``exclure_codees=True``), le tirage
        libre exclut la dénutrition (IMC < 18,5), état supposé TOUJOURS codé
        dans un scénario — elle n'entre qu'explicitement, via ``code=``. Les
        proportions restantes sont renormalisées. Toutes les autres classes,
        grade IV compris, sont tirables : elles sont codées par l'appelant.
        """
        hf = _sexe_hf(sexe)
        mu, sigma = _LOGN[hf]
        if imc_min is not None or imc_max is not None:
            lo = imc_min if imc_min is not None else 14.0
            hi = imc_max if imc_max is not None else 60.0
            return _lognorm_tronquee(self.rng, mu, sigma, lo, hi), lo, hi
        # 1. classe selon les proportions croisées sexe x âge (ou imposées)
        p = (np.array(proportions, dtype=float) / 100 if proportions is not None
             else _proportions(hf, age))
        if exclure_codees:
            p = p.copy()
            p[_CLASSES.index("maigreur")] = 0.0
            p /= p.sum()
        classe = self.rng.choice(_CLASSES, p=p)
        if classe == "obesite":
            # 2. sous-classe d'obésité
            table_so = (sous_obesite if sous_obesite is not None
                        else {c: v[1] for c, v in _SOUS_OBESITE.items()})
            codes = list(table_so)
            poids = np.array([table_so[c] for c in codes])
            code = self.rng.choice(codes, p=poids / poids.sum())
            lo, hi = _SOUS_OBESITE[code][0]
        else:
            lo, hi = _BORNES[classe]
        # 3. valeur intra-classe
        return _lognorm_tronquee(self.rng, mu, sigma, lo, hi), lo, hi

    # ----- tirage complet ---------------------------------------------------
    def tirer(self, age: int, sexe: int | str,
              imc_min: float | None = None, imc_max: float | None = None,
              code: str | None = None, exclure_codees: bool = True,
              proportions=None, sous_obesite=None) -> Anthropometrie:
        """Tire taille, poids, IMC.

        ``code`` (E660x, E669x, E43, E440 — compact) impose l'intervalle
        d'IMC. Sans contrainte, le tirage exclut la dénutrition (état supposé
        toujours codé) sauf ``exclure_codees=False``.
        """
        sexe_pmsi = 1 if _sexe_hf(sexe) == "H" else 2
        if code is not None:
            if code not in _CONTRAINTES_CODE:
                raise ValueError(f"Pas de contrainte d'IMC connue pour {code}")
            imc_min, imc_max = _CONTRAINTES_CODE[code](age)

        t = self.taille(sexe_pmsi, age)
        i, lo, hi = self.imc(sexe_pmsi, age, imc_min, imc_max,
                             exclure_codees, proportions, sous_obesite)
        p = int(round(i * (t / 100) ** 2))
        # L'arrondi au kg/cm peut faire sortir l'IMC de l'intervalle visé :
        # on corrige le poids au kg près (jamais plus de 2-3 itérations).
        m2 = (t / 100) ** 2
        for _ in range(10):
            imc_final = round(p / m2, 1)
            if imc_final < lo:
                p += 1
            elif imc_final >= hi:
                p -= 1
            else:
                break
        return Anthropometrie(sexe_pmsi, age, t, p, imc_final,
                              classe_imc=_classe(imc_final),
                              code_e66=_code_e66(imc_final))

    def tirer_pour_scenario(self, codes: list[str], age: int, sexe: int | str,
                            ) -> tuple[Anthropometrie, list[str]]:
        """Tire l'anthropométrie cohérente avec un scénario complet.

        - un code E66* (E660x, E669x) ou de dénutrition (E43, E440) présent
          est conservé tel quel : il impose l'intervalle d'IMC et AUCUN code
          n'est ajouté ;
        - sinon un E11* (DNID) impose la répartition de corpulence du
          diabétique de type 2 (``_PROP_DNID``) ;
        - sinon tirage libre (dénutrition exclue).

        Retourne (anthropométrie, codes à ajouter en DAS) : le codage est
        SYSTÉMATIQUE — toute classe tirée à IMC >= 25 produit son code
        (E6603 surpoids, E6604-E6607 obésité). Décision de doctrine révisée
        (RF) : E6603 « Surpoids dû à un excès calorique » est un code valide.
        """
        codes = [str(c).strip().upper() for c in codes if str(c).strip()]
        contraint = next((c for c in codes if c in _CONTRAINTES_CODE), None)
        if contraint:
            return self.tirer(age, sexe, code=contraint), []
        dnid = any(c.startswith("E11") for c in codes)
        r = self.tirer(age, sexe,
                       proportions=_PROP_DNID if dnid else None,
                       sous_obesite=_SOUS_OBESITE_DNID if dnid else None)
        return r, [r.code_e66] if r.code_e66 else []

    def tirer_n(self, n: int, age: int, sexe: int | str, **kw) -> list[Anthropometrie]:
        return [self.tirer(age, sexe, **kw) for _ in range(n)]


def _classe(imc: float) -> str:
    if imc < 18.5:
        return "maigreur"
    if imc < 25:
        return "normal"
    if imc < 30:
        return "surpoids"
    return "obesite"


def _code_e66(imc: float) -> str | None:
    if imc < 25:
        return None
    if imc < 30:
        return "E6603"
    for code, ((lo, hi), _) in _SOUS_OBESITE.items():
        if lo <= imc < hi:
            return code
    return "E6607"


# ---------------------------------------------------------------------------
# Auto-contrôle : reproduit-on Esteban et Obépi ?
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    sim = SimulateurAnthropometrie(seed=2026)
    rng = np.random.default_rng(1)
    print("Contrôle des classes d'IMC (simulé vs Esteban tableau 5)")
    for hf, sexe_pmsi in (("H", 1), ("F", 2)):
        tir = []
        for _ in range(40_000):
            tr = rng.choice(list(_EFFECTIFS_AGE),
                            p=np.array(list(_EFFECTIFS_AGE.values())) / 2429)
            lo, hi = {"18-29": (18, 29), "30-54": (30, 54), "55-74": (55, 74)}[tr]
            tir.append(sim.tirer(int(rng.integers(lo, hi + 1)), sexe_pmsi,
                                 exclure_codees=False))
        cl = np.array([t.classe_imc for t in tir])
        parts = [100 * np.mean(cl == c) for c in _CLASSES]
        print(f"  {hf}: simulé={np.round(parts, 1)}  cible={_PROP_SEXE[hf]}"
              f"  | taille moy={np.mean([t.taille_cm for t in tir]):.1f}"
              f"  poids moy={np.mean([t.poids_kg for t in tir]):.1f}"
              f"  IMC moy={np.mean([t.imc for t in tir]):.1f}")
    print("\nTirage libre par défaut (dénutrition exclue), F 30-54 ans :")
    lib = [sim.tirer(int(rng.integers(30, 55)), 2) for _ in range(20_000)]
    cl = np.array([t.classe_imc for t in lib])
    im = np.array([t.imc for t in lib])
    print(f"  classes={np.round([100*np.mean(cl==c) for c in _CLASSES],1)}  "
          f"IMC min={im.min()}  IMC max={im.max()}")
    print("\nScénario DNID (E1120 sans code E66), H 62 ans — 20 000 tirages :")
    dn = [sim.tirer_pour_scenario(["E1120", "N083", "I10"], 62, 1)
          for _ in range(20_000)]
    cl = np.array([r.classe_imc for r, _ in dn])
    print(f"  classes={np.round([100*np.mean(cl==c) for c in _CLASSES],1)}  "
          f"(cible DNID ~[0, 19, 39, 41] hors maigreur)"
          f"  | codes ajoutés (E6603-E6607, systématique IMC >= 25) dans "
          f"{100*np.mean([bool(a) for _, a in dn]):.1f} % des scénarios (attendu ~80)")
    print("\nExemples contraints par code :")
    for code, age in [("E6605", 58), ("E43", 82), ("E440", 45)]:
        print(f"  {code} ({age} ans, F) ->", sim.tirer(age, 2, code=code).as_dict())

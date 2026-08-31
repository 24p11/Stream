"""
anthropometrie_fr.py — Simulation de taille, poids et IMC d'adultes français
selon le sexe et l'âge, pour l'enrichissement de scénarios CIM-10.

Sources
-------
- Esteban 2014-2016 (Gorokhova et al., BEH 2021;10:166-75, tableau 5) :
  répartition de l'IMC MESURÉ par classe OMS, par sexe et par âge.
- Obépi-Roche 2020 (Ligue contre l'obésité) : tailles moyennes 176,6 cm (H)
  et 163,9 cm (F) ; tranches de taille validant les écarts-types 7 / 6,5 cm ;
  poids moyens 81,2 / 67,3 kg et IMC moyen 25,5 (utilisés en contrôle).
- Obépi 2012 : sous-classes d'obésité (grades I/II/III ≈ 71 / 21 / 8 % des obèses).

Méthode
-------
1. Taille ~ Normale(mu(sexe, âge), sd_sexe). Pente d'âge -0,10 cm/an autour de
   45 ans (effet cohorte + tassement) — HYPOTHÈSE documentée, non ajustée.
2. Classe d'IMC tirée selon les proportions Esteban croisées sexe × âge
   (croisement par ajustement proportionnel des deux marges publiées).
3. IMC tiré dans la classe par log-normale tronquée (forme intra-classe
   lisse, prévalences des classes exactes par construction).
4. Poids = IMC × taille². Arrondis réalistes (cm, kg entiers).

Contraintes : imc_min / imc_max (ou un code E66.0x / E43 / E44.0) forcent
le tirage dans l'intervalle voulu — c'est l'usage principal pour les scénarios.

Convention de scénario : le tirage LIBRE (sans code) ne produit jamais de
dénutrition (IMC < 18,5) ni d'obésité de grade IV (IMC ≥ 50), états supposés
toujours codés — ils n'entrent qu'explicitement via `code=`. Surpoids et
obésité I-III restent tirables librement (codage inconstant en pratique).
`exclure_codees=False` restitue la distribution populationnelle complète.

Dépendances : numpy uniquement (statistics.NormalDist pour la CDF inverse).

Limites : adultes ≥ 18 ans ; au-delà de 74 ans les proportions sont
EXTRAPOLÉES (Esteban s'arrête à 74) — voir `_PROP_75PLUS`, à valider.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from statistics import NormalDist

import numpy as np

# ---------------------------------------------------------------------------
# Paramètres — tous documentés par leur source
# ---------------------------------------------------------------------------

# Taille (cm) : moyenne Obépi 2020, sd validé sur les tranches Obépi
_TAILLE = {"H": (176.6, 7.0), "F": (163.9, 6.5)}
_PENTE_TAILLE_PAR_AN = -0.10   # cm par année d'âge, centré à 45 ans (hypothèse)
_AGE_CENTRE = 45

# Bornes des classes OMS + sous-classes d'obésité (ATIH E66.0x)
_CLASSES = ["maigreur", "normal", "surpoids", "obesite"]
_BORNES = {"maigreur": (14.0, 18.5), "normal": (18.5, 25.0),
           "surpoids": (25.0, 30.0), "obesite": (30.0, 60.0)}

# Esteban tableau 5 (IMC mesuré) — proportions en %
_PROP_SEXE = {"H": [2.1, 43.5, 37.5, 16.9], "F": [2.5, 53.9, 26.3, 17.2]}
_PROP_AGE = {"18-29": [5.4, 64.3, 22.9, 7.5],
             "30-54": [1.9, 50.7, 30.1, 17.4],
             "55-74": [1.5, 39.5, 38.2, 20.8]}
_EFFECTIFS_AGE = {"18-29": 166, "30-54": 1173, "55-74": 1090}
# ≥ 75 ans : EXTRAPOLATION (sarcopénie, baisse de l'obésité après 80 ans) — à valider
_PROP_75PLUS = [4.0, 44.0, 36.0, 16.0]

# Diabète de type 2 (E11) : corpulence très décalée vers le haut. Ordres de
# grandeur Entred 2007 (obésité ~41 %, surpoids ~39 %, normal ~19 %) — HYPOTHÈSE
# à ajuster sur données réelles. Sous-classes d'obésité plus sévères aussi.
_PROP_DNID = [1.0, 19.0, 39.0, 41.0]
_SOUS_OBESITE_DNID = {"E66.04": 0.62, "E66.05": 0.25, "E66.06": 0.12, "E66.07": 0.01}

# Sous-classes d'obésité, part des obèses (Obépi 2012 : 10,5 / 3,1 / 1,2 % pop.)
_SOUS_OBESITE = {"E66.04": ((30.0, 35.0), 0.70),   # grade I
                 "E66.05": ((35.0, 40.0), 0.21),   # grade II
                 "E66.06": ((40.0, 50.0), 0.08),   # grade III
                 "E66.07": ((50.0, 60.0), 0.01)}   # ≥ 50

# Forme intra-classe : log-normale ajustée sur Esteban (sexe)
_LOGN = {"H": (3.2386, 0.1677), "F": (3.2027, 0.1843)}

# Seuils HAS de dénutrition (à confirmer contre les candidates DEN-10..16)
_CONTRAINTES_CODE = {
    "E66.03": lambda age: (25.0, 30.0),
    "E66.04": lambda age: (30.0, 35.0),
    "E66.05": lambda age: (35.0, 40.0),
    "E66.06": lambda age: (40.0, 50.0),
    "E66.07": lambda age: (50.0, 60.0),
    "E43":    lambda age: (14.0, 17.0) if age < 70 else (14.0, 20.0),   # sévère
    "E44.0":  lambda age: (17.0, 18.5) if age < 70 else (20.0, 22.0),   # modérée
}


def _tranche_age(age: int) -> str:
    if age < 18:
        raise ValueError("Simulateur adulte uniquement (âge ≥ 18).")
    if age <= 29:
        return "18-29"
    if age <= 54:
        return "30-54"
    if age <= 74:
        return "55-74"
    return "75+"


def _proportions(sexe: str, age: int) -> np.ndarray:
    """Classe d'IMC croisée sexe × âge : P(c|s,a) ∝ P(c|s)·P(c|a)/P(c)."""
    ps = np.array(_PROP_SEXE[sexe]) / 100
    tranche = _tranche_age(age)
    if tranche == "75+":
        pa = np.array(_PROP_75PLUS) / 100
    else:
        pa = np.array(_PROP_AGE[tranche]) / 100
    w = np.array(list(_EFFECTIFS_AGE.values()), dtype=float)
    p_all = sum(wi * np.array(_PROP_AGE[k]) / 100 for wi, k in zip(w, _EFFECTIFS_AGE)) / w.sum()
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
    sexe: str
    age: int
    taille_cm: int
    poids_kg: int
    imc: float
    classe_imc: str
    code_e66: str | None   # sous-classe ATIH si surpoids/obésité, sinon None

    def as_dict(self) -> dict:
        return self.__dict__.copy()


class SimulateurAnthropometrie:
    def __init__(self, seed: int | None = None):
        self.rng = np.random.default_rng(seed)

    # ----- taille -----------------------------------------------------------
    def taille(self, sexe: str, age: int) -> int:
        mu, sd = _TAILLE[sexe]
        mu += _PENTE_TAILLE_PAR_AN * (age - _AGE_CENTRE)
        return int(round(self.rng.normal(mu, sd)))

    # ----- IMC --------------------------------------------------------------
    def imc(self, sexe: str, age: int,
            imc_min: float | None = None, imc_max: float | None = None,
            exclure_codees: bool = True, proportions=None, sous_obesite=None) -> tuple[float, float, float]:
        """Retourne (imc, lo, hi) — l'IMC tiré et l'intervalle [lo, hi[ visé.
        IMC tiré selon Esteban. Par défaut (`exclure_codees=True`), le tirage
        libre exclut les états supposés TOUJOURS codés dans un scénario — la
        dénutrition (IMC < 18,5) et l'obésité de grade IV (IMC ≥ 50) — qui ne
        doivent entrer qu'explicitement, via `code=`. Le surpoids et l'obésité
        de grades I à III restent tirables sans code (codage inconstant en
        pratique). Les proportions restantes sont renormalisées."""
        mu, sigma = _LOGN[sexe]
        if imc_min is not None or imc_max is not None:
            lo = imc_min if imc_min is not None else 14.0
            hi = imc_max if imc_max is not None else 60.0
            return _lognorm_tronquee(self.rng, mu, sigma, lo, hi), lo, hi
        # 1. classe selon les proportions croisées sexe × âge (ou proportions imposées)
        p = np.array(proportions, dtype=float) / 100 if proportions is not None else _proportions(sexe, age)
        if exclure_codees:
            p = p.copy()
            p[_CLASSES.index("maigreur")] = 0.0
            p /= p.sum()
        classe = self.rng.choice(_CLASSES, p=p)
        if classe == "obesite":
            # 2. sous-classe d'obésité
            table_so = sous_obesite if sous_obesite is not None else {c: v[1] for c, v in _SOUS_OBESITE.items()}
            codes = [c for c in table_so if not (exclure_codees and c == "E66.07")]
            poids = np.array([table_so[c] for c in codes])
            code = self.rng.choice(codes, p=poids / poids.sum())
            lo, hi = _SOUS_OBESITE[code][0]
        else:
            lo, hi = _BORNES[classe]
        # 3. valeur intra-classe
        return _lognorm_tronquee(self.rng, mu, sigma, lo, hi), lo, hi

    # ----- tirage complet ---------------------------------------------------
    def tirer(self, age: int, sexe: str,
              imc_min: float | None = None, imc_max: float | None = None,
              code: str | None = None, exclure_codees: bool = True,
              proportions=None, sous_obesite=None) -> Anthropometrie:
        """Tire taille, poids, IMC. `code` (E66.0x, E43, E44.0) impose l'intervalle
        d'IMC. Sans contrainte, le tirage exclut dénutrition et obésité grade IV
        (états supposés toujours codés) sauf `exclure_codees=False`."""
        sexe = sexe.upper()[0]
        if sexe not in ("H", "F"):
            raise ValueError("sexe ∈ {'H','F'}")
        if code is not None:
            if code not in _CONTRAINTES_CODE:
                raise ValueError(f"Pas de contrainte d'IMC connue pour {code}")
            imc_min, imc_max = _CONTRAINTES_CODE[code](age)

        t = self.taille(sexe, age)
        i, lo, hi = self.imc(sexe, age, imc_min, imc_max, exclure_codees, proportions, sous_obesite)
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
        return Anthropometrie(sexe, age, t, p, imc_final,
                              classe_imc=_classe(imc_final),
                              code_e66=_code_e66(imc_final))

    def tirer_pour_scenario(self, codes: list[str], age: int, sexe: str,
                            p_codage_obesite: float = 1.0,
                            p_codage_surpoids: float = 0.0) -> tuple[Anthropometrie, list[str]]:
        """Tire l'anthropométrie cohérente avec un scénario complet.
        - un code E66.0x / E43 / E44.0 présent impose l'intervalle d'IMC ;
        - sinon un E11.* (DNID) impose la répartition de corpulence du diabétique
          de type 2 (`_PROP_DNID`) ;
        - sinon tirage libre (dénutrition et grade IV exclus).
        Retourne (anthropométrie, codes à ajouter en DAS) : E66.0x ajouté avec
        probabilité p_codage_obesite si obésité tirée librement, E66.03 avec
        p_codage_surpoids si surpoids."""
        codes = [c.strip().upper() for c in codes]
        contraint = next((c for c in codes if c in _CONTRAINTES_CODE), None)
        if contraint:
            return self.tirer(age, sexe, code=contraint), []
        dnid = any(c.startswith("E11") for c in codes)
        r = self.tirer(age, sexe,
                       proportions=_PROP_DNID if dnid else None,
                       sous_obesite=_SOUS_OBESITE_DNID if dnid else None)
        ajoutes: list[str] = []
        if r.code_e66 and r.code_e66 != "E66.03" and self.rng.random() < p_codage_obesite:
            ajoutes.append(r.code_e66)
        elif r.code_e66 == "E66.03" and self.rng.random() < p_codage_surpoids:
            ajoutes.append("E66.03")
        return r, ajoutes

    def tirer_n(self, n: int, age: int, sexe: str, **kw) -> list[Anthropometrie]:
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
        return "E66.03"
    for code, ((lo, hi), _) in _SOUS_OBESITE.items():
        if lo <= imc < hi:
            return code
    return "E66.07"


# ---------------------------------------------------------------------------
# Auto-contrôle : reproduit-on Esteban et Obépi ?
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    sim = SimulateurAnthropometrie(seed=2026)
    ages = {"H": None, "F": None}
    # Âges tirés selon la structure Esteban (18-74) pour comparer aux marges publiées
    rng = np.random.default_rng(1)
    print("Contrôle des classes d'IMC (simulé vs Esteban tableau 5)")
    for sexe in ("H", "F"):
        tir = []
        for _ in range(40_000):
            tr = rng.choice(list(_EFFECTIFS_AGE), p=np.array(list(_EFFECTIFS_AGE.values())) / 2429)
            lo, hi = {"18-29": (18, 29), "30-54": (30, 54), "55-74": (55, 74)}[tr]
            tir.append(sim.tirer(int(rng.integers(lo, hi + 1)), sexe, exclure_codees=False))
        cl = np.array([t.classe_imc for t in tir])
        parts = [100 * np.mean(cl == c) for c in _CLASSES]
        print(f"  {sexe}: simulé={np.round(parts, 1)}  cible={_PROP_SEXE[sexe]}"
              f"  | taille moy={np.mean([t.taille_cm for t in tir]):.1f}"
              f"  poids moy={np.mean([t.poids_kg for t in tir]):.1f}"
              f"  IMC moy={np.mean([t.imc for t in tir]):.1f}")
    print("\nTirage libre par défaut (dénutrition et grade IV exclus), F 30-54 ans :")
    lib = [sim.tirer(int(rng.integers(30, 55)), "F") for _ in range(20_000)]
    cl = np.array([t.classe_imc for t in lib]); im = np.array([t.imc for t in lib])
    print(f"  classes={np.round([100*np.mean(cl==c) for c in _CLASSES],1)}  "
          f"IMC min={im.min()}  IMC max={im.max()}")
    print("\nScénario DNID (E11.20 sans code E66), H 62 ans — 20 000 tirages :")
    dn = [sim.tirer_pour_scenario(["E11.20", "N08.3", "I10"], 62, "H") for _ in range(20_000)]
    cl = np.array([r.classe_imc for r, _ in dn])
    print(f"  classes={np.round([100*np.mean(cl==c) for c in _CLASSES],1)}  (cible DNID ~[0, 19, 39, 41] hors maigreur)"
          f"  | E66.0x ajoutés dans {100*np.mean([bool(a) for _, a in dn]):.1f} % des scénarios")
    print("\nExemples contraints par code :")
    for code, age in [("E66.05", 58), ("E43", 82), ("E44.0", 45)]:
        print(f"  {code} ({age} ans, F) →", sim.tirer(age, "F", code=code).as_dict())

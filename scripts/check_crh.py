# check_crh.py — vérification mécanique des CRH générés par bench
# Usage : python check_crh.py work_prompts/tests/01 [--out crh_generation.txt]
# Aucune dépendance hors stdlib. Code retour 1 si au moins un échec.

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from pathlib import Path

RESERVED_DIRS = {"system", "batches", "__pycache__"}

# Champs attendus dans formulations.informations (schéma stable attendu,
# listes vides comprises — leur absence est une dérive de schéma)
EXPECTED_INFO_KEYS = [
    "Date entrée", "Date de sortie", "Service d'hospitalisation",
    "Nom/Prénom du médecin", "Nom/Prénom du patient", "Poids", "Âge",
    "Sexe", "État général", "NFS", "Créatinine", "Bilan hépatique",
    "Traitements",
]

# Scores standardisés tolérés uniquement si le contexte les justifie :
# signalés en avertissement, à juger à la main
SCORE_RE = re.compile(r"\b(ECOG|NYHA|Glasgow|NIHSS|Karnofsky)\b", re.IGNORECASE)

# Maladies chroniques interdites en antécédents "de réalisme"
CHRONIC_RE = re.compile(
    r"\b(hypertension|HTA|diab[eè]te|dyslipid[ée]mie|RGO|reflux gastro"
    r"|asthme|BPCO|fibrillation)\b",
    re.IGNORECASE,
)


def normalize(s: str) -> str:
    """Normalisation douce pour la recherche de sous-chaînes :
    unicode NFC, apostrophes/espaces typographiques unifiées, espaces répétés."""
    s = unicodedata.normalize("NFC", s)
    s = s.replace("\u2019", "'").replace("\u00a0", " ")
    return re.sub(r"\s+", " ", s)


def load_json(path: Path) -> tuple[dict | None, list[str]]:
    """Retourne (données, avertissements de réparation)."""
    raw = path.read_text(encoding="utf-8").strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    repairs: list[str] = []
    try:
        # strict=False tolère les retours à la ligne littéraux dans les
        # chaînes (défaut fréquent de la sortie Mistral)
        return json.loads(raw, strict=False), repairs
    except json.JSONDecodeError as exc:
        # Réparation : fermetures manquantes en fin de fichier (le modèle
        # omet parfois une accolade finale). On ne répare QUE si l'erreur
        # est à la toute fin, et on le signale.
        if exc.pos >= len(raw) - 1:
            opens = raw.count("{") - raw.count("}")
            brackets = raw.count("[") - raw.count("]")
            if 0 < opens <= 3 and brackets == 0:
                try:
                    data = json.loads(raw + "}" * opens, strict=False)
                    repairs.append(
                        f"JSON réparé : {opens} accolade(s) fermante(s) "
                        "manquante(s) en fin de fichier"
                    )
                    return data, repairs
                except json.JSONDecodeError:
                    pass
        ctx = raw[max(0, exc.pos - 60):exc.pos + 60].replace("\n", "\\n")
        print(f"    ERREUR JSON : {exc.msg} (char {exc.pos})")
        print(f"      contexte : ...{ctx}...")
        return None, repairs


def check_scenario(sdir: Path, out_name: str) -> tuple[int, int]:
    """Retourne (nb_echecs, nb_avertissements)."""
    fails, warns = 0, 0
    path = sdir / out_name
    if not path.exists():
        print(f"    ECHEC  fichier absent : {path.name}")
        return 1, 0

    data, repairs = load_json(path)
    for r in repairs:
        warns += 1
        print(f"    AVERT  {r}")
    if data is None:
        return fails + 1, warns

    cr = data.get("CR", "")
    cr_norm = normalize(cr)

    # 1. Gras hors titres ### (les titres n'utilisent pas **)
    bold = re.findall(r"\*\*[^*\n]+\*\*", cr)
    if bold:
        fails += 1
        sample = ", ".join(b[:40] for b in bold[:4])
        print(f"    ECHEC  gras interdit ({len(bold)} occurrence(s)) : {sample}")

    # 2. Fidélité du dictionnaire : chaque formulation doit être dans le texte
    formulations = data.get("formulations", {})
    for section in ("diagnostics", "informations"):
        for key, values in (formulations.get(section) or {}).items():
            for v in values or []:
                if normalize(v) not in cr_norm:
                    fails += 1
                    print(f"    ECHEC  formulation fantôme [{section}/{key}] : « {v[:60]} »")

    # 3. Schéma du dictionnaire informations : clés attendues présentes
    info = formulations.get("informations") or {}
    missing_keys = [k for k in EXPECTED_INFO_KEYS if k not in info]
    if missing_keys:
        warns += 1
        print(f"    AVERT  clés absentes du dictionnaire : {', '.join(missing_keys)}")

    # 4. Mentions obligatoires de l'en-tête
    if "IPP" not in cr:
        fails += 1
        print("    ECHEC  mention IPP absente de l'en-tête")
    for label in ("Nom", "Prénom", "Date de naissance"):
        if label not in cr:
            fails += 1
            print(f"    ECHEC  mention « {label} » absente de l'en-tête")

    # 5. Scores standardisés (avertissement : légitimité à juger)
    for m in sorted({m.upper() for m in SCORE_RE.findall(cr)}):
        warns += 1
        print(f"    AVERT  score standardisé présent : {m}")

    # 6. Maladies chroniques hors scénario (avertissement : vérifier le scénario)
    for m in sorted({m.lower() for m in CHRONIC_RE.findall(cr)}):
        warns += 1
        print(f"    AVERT  maladie chronique mentionnée : {m} (à confronter au scénario)")

    if fails == 0 and warns == 0:
        print("    OK")
    return fails, warns


def main() -> int:
    ap = argparse.ArgumentParser(description="Vérification mécanique des CRH générés")
    ap.add_argument("test_dir", type=Path)
    ap.add_argument("--out", default="crh_generation.txt",
                    help="nom du fichier de sortie à vérifier dans chaque dossier")
    args = ap.parse_args()

    if (args.test_dir / args.out).exists():
        # Le chemin donné est directement un dossier scénario
        print(f"[{args.test_dir.name}]")
        f, w = check_scenario(args.test_dir, args.out)
        print(f"\nBilan : {f} échec(s), {w} avertissement(s) sur 1 scénario")
        return 1 if f else 0

    dirs = sorted(
        d.name for d in args.test_dir.iterdir()
        if d.is_dir() and d.name not in RESERVED_DIRS and not d.name.startswith(".")
    )
    if not dirs:
        print(f"Aucun dossier scénario dans {args.test_dir} "
              f"(et pas de {args.out} à sa racine)")
        return 1

    total_fails = total_warns = 0
    for name in dirs:
        print(f"[{name}]")
        f, w = check_scenario(args.test_dir / name, args.out)
        total_fails += f
        total_warns += w

    print(f"\nBilan : {total_fails} échec(s), {total_warns} avertissement(s) "
          f"sur {len(dirs)} scénario(s)")
    return 1 if total_fails else 0


if __name__ == "__main__":
    sys.exit(main())

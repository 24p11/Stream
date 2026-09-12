# prepare_regeneration.py — préparation de la régénération des scénarios rejetés
#
# Entrées : le rapport --json de check_crh, et (optionnels) les verdicts du
# juge d'équivalence (contrat dans juge_io). Sans verdicts, seuls les échecs
# mécaniques déclenchent.
#
# Déclencheurs de rejet d'un scénario :
#   - échec check "code_absent_texte" (code du scénario sans clé au
#     dictionnaire)                            -> formulation imposée ;
#   - verdict juge preuve_directe == false     -> formulation imposée ;
#   - échec check "fidelite_poids_taille"      -> gabarit poids/taille.
# Les autres échecs (gras, fantome, ...) ne déclenchent pas : ils relèvent
# du nettoyage d'export (nettoie_dictionnaire), pas de la régénération.
# Un scénario est rejeté s'il produit au moins une ligne de correction.
#
# Le bloc CORRECTION REQUISE est construit par gabarits PRESCRIPTIFS —
# jamais la citation d'une formulation fautive du dictionnaire. La
# formulation imposée d'un code est tirée au hasard SEEDÉ (--seed, graine
# dérivée de (seed, scenario, code) : stable quel que soit l'ordre de
# traitement) parmi les entités/synonymes de la fiche <fiche_code> du code
# dans user_generation.txt ; à défaut de fiche ou d'entité, le libellé du
# bloc « Codage CIM10 » est imposé.
#
# Écritures (jamais ailleurs) :
#   - <scenario>/user_regeneration.txt : contenu de user_generation.txt + le
#     bloc — dans les SEULS dossiers rejetés ; refus d'écraser ATOMIQUE
#     (rien n'est écrit nulle part) sauf --force ;
#   - <test_dir>/regeneration_<seed>.json : les formulations imposées —
#     c'est ce fichier que le re-check utilisera (présence normalisée de
#     chaque formulation imposée dans crh_v2 : Python pur, pas de
#     re-jugement) :
#       {"seed": 42, "cree_le": ..., "check": ..., "verdicts": ...,
#        "scenarios": {"0003": {
#            "formulations_imposees": [{"code", "libelle", "formulation"}],
#            "poids_taille": {"poids_kg": "83", "taille_cm": "183"} | null}}}
#
# Sortie texte : la liste des rejetés au format only= et le rappel du geste :
#   generate(user="user_regeneration.txt", only=only, out="crh_v2.txt")
#
# Usage :
#   python prepare_regeneration.py work_prompts/tests/06 --check rapport.json
#       [--verdicts verdicts.jsonl] [--seed 0] [--force]

from __future__ import annotations

import argparse
import json
import random
import sys
from datetime import datetime
from pathlib import Path

if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from check_crh import codage_du_scenario, contexte_enrichi  # noqa: E402
from juge_io import fiches_du_scenario, lire_verdicts_juge  # noqa: E402

GABARIT_CODE = (
    "Le diagnostic {libelle} ({code}) doit être exprimé dans le texte. "
    "Attention, ce code est complexe : utilisez précisément cette "
    "formulation : \"{formulation}\" (déclinaisons grammaticales admises), "
    "et le dictionnaire doit citer l'extrait exact du texte où elle "
    "apparaît."
)
GABARIT_POIDS_TAILLE = (
    "Le poids ({poids} kg) et la taille ({taille} cm) fournis doivent "
    "apparaître dans le texte."
)


def formulation_imposee(seed: int, scenario: str, code: str,
                        entites: list[str], libelle: str) -> str:
    """Tirage seedé, stable par (seed, scenario, code)."""
    if not entites:
        return libelle
    return random.Random(f"{seed}|{scenario}|{code}").choice(entites)


def corrections_du_scenario(scenario: str, rapport: dict | None,
                            verdicts: dict) -> tuple[list[str], bool]:
    """(codes à imposer, gabarit poids/taille requis)."""
    codes: list[str] = []
    poids_taille = False
    for e in (rapport or {}).get("echecs", []):
        if e.get("type") == "code_absent_texte" and e.get("code"):
            if e["code"] not in codes:
                codes.append(e["code"])
        elif e.get("type") == "fidelite_poids_taille":
            poids_taille = True
    for (sc, code), v in verdicts.items():
        if sc == scenario and not v["preuve_directe"] and code not in codes:
            codes.append(code)
    return codes, poids_taille


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Prépare la régénération des scénarios rejetés "
                    "(bloc CORRECTION REQUISE prescriptif)")
    ap.add_argument("test_dir", type=Path)
    ap.add_argument("--check", type=Path, required=True,
                    help="rapport --json de check_crh")
    ap.add_argument("--verdicts", type=Path, default=None,
                    help="verdicts du juge d'équivalence (JSONL, contrat juge_io)")
    ap.add_argument("--seed", type=int, default=0,
                    help="graine du tirage des formulations imposées (défaut 0)")
    ap.add_argument("--force", action="store_true",
                    help="écraser user_regeneration.txt et "
                         "regeneration_<seed>.json existants")
    args = ap.parse_args()

    if not args.check.is_file():
        print(f"ERREUR rapport check introuvable : {args.check}")
        return 1
    rapports = {r["scenario"]: r
                for r in json.loads(args.check.read_text(encoding="utf-8"))}
    verdicts = lire_verdicts_juge(args.verdicts) if args.verdicts else {}

    scenarios = sorted(set(rapports) | {sc for sc, _ in verdicts})
    rejets: dict[str, dict] = {}
    for scenario in scenarios:
        codes, poids_taille = corrections_du_scenario(
            scenario, rapports.get(scenario), verdicts)
        if not codes and not poids_taille:
            continue

        sdir = args.test_dir / scenario
        ug = sdir / "user_generation.txt"
        if not ug.is_file():
            print(f"ERREUR user_generation.txt absent pour {scenario} : {ug}")
            return 1
        texte = ug.read_text(encoding="utf-8")
        libelles = dict(codage_du_scenario(texte))
        fiches = fiches_du_scenario(texte)

        imposees: list[dict] = []
        lignes: list[str] = []
        for code in codes:
            if code not in libelles:
                print(f"ERREUR code {code} absent du bloc « Codage CIM10 » "
                      f"du scénario {scenario} (vérifier check/verdicts)")
                return 1
            entites = (fiches.get(code) or {}).get("entites") or []
            formulation = formulation_imposee(
                args.seed, scenario, code, entites, libelles[code])
            imposees.append({"code": code, "libelle": libelles[code],
                             "formulation": formulation})
            lignes.append("- " + GABARIT_CODE.format(
                libelle=libelles[code], code=code, formulation=formulation))

        ctx = contexte_enrichi(sdir) if poids_taille else None
        if poids_taille:
            if ctx is None:
                print(f"ERREUR poids/taille introuvables dans {ug} "
                      "(échec fidelite_poids_taille pourtant rapporté)")
                return 1
            lignes.append("- " + GABARIT_POIDS_TAILLE.format(
                poids=ctx["poids_kg"], taille=ctx["taille_cm"]))

        bloc = "\n".join(["", "**CORRECTION REQUISE (régénération) :**", ""]
                         + lignes)
        rejets[scenario] = {
            "contenu": texte.rstrip() + "\n" + bloc + "\n",
            "formulations_imposees": imposees,
            "poids_taille": ({"poids_kg": ctx["poids_kg"],
                              "taille_cm": ctx["taille_cm"]}
                             if poids_taille else None),
        }

    if not rejets:
        print("Aucun scénario rejeté — rien à régénérer.")
        return 0

    # Refus d'écraser atomique : tout est vérifié avant la première écriture
    cibles = {sc: args.test_dir / sc / "user_regeneration.txt" for sc in rejets}
    journal = args.test_dir / f"regeneration_{args.seed}.json"
    existants = [p for p in [*cibles.values(), journal] if p.exists()]
    if existants and not args.force:
        print("ERREUR fichiers déjà présents (utiliser --force pour écraser) :")
        for p in existants:
            print(f"  {p}")
        return 1

    for sc, cible in cibles.items():
        cible.write_text(rejets[sc]["contenu"], encoding="utf-8")
    journal.write_text(json.dumps({
        "seed": args.seed,
        "cree_le": datetime.now().isoformat(timespec="seconds"),
        "check": args.check.as_posix(),
        "verdicts": args.verdicts.as_posix() if args.verdicts else None,
        "scenarios": {sc: {"formulations_imposees": r["formulations_imposees"],
                           "poids_taille": r["poids_taille"]}
                      for sc, r in rejets.items()},
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    rejetes = sorted(rejets)
    print(f"{len(rejetes)} scénario(s) rejeté(s), user_regeneration.txt écrit ; "
          f"formulations imposées : {journal}")
    print(f"only={rejetes!r}")
    print('generate(user="user_regeneration.txt", only=only, out="crh_v2.txt")')
    return 0


if __name__ == "__main__":
    sys.exit(main())

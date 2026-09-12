# nettoie_dictionnaire.py — nettoyage d'export des dictionnaires de formulations
#
# Pour chaque scénario d'un test, reprend le tri de reancre_crh
# (trier_formulations) et écrit <out>/<scenario>.json : le dictionnaire
# "formulations" où chaque formulation est
#   - EXACTE    : gardée telle quelle ;
#   - RÉANCRÉE  : REMPLACÉE par l'extrait exact du texte (fuzzy >= seuil) ;
#   - ORPHELINE : SUPPRIMÉE, tracée dans le champ "supprimees"
#                 (avec son meilleur candidat et son score).
# Les formulations vides sont écartées ; une clé dont toutes les
# formulations sont supprimées reste présente, avec une liste vide.
#
# LECTURE SEULE sur le test : n'écrit jamais dans les dossiers scénario.
# Sortie par défaut : <test_dir>/export_dict/ — nom réservé, ignoré par la
# découverte de scénarios (check_crh, reancre_crh et ce script).
#
# Fichier produit par scénario :
#   {"scenario": "0003", "source": "crh_generation.txt", "seuil": 0.75,
#    "formulations": {"diagnostics": {...}, "informations": {...}},
#    "supprimees": [{"section", "cle", "formulation",
#                    "meilleur_candidat", "score"}, ...]}
#
# Usage :
#   python nettoie_dictionnaire.py work_prompts/tests/06
#       [--source crh_generation.txt] [--seuil 0.75] [--out DIR]
#
# Stdlib uniquement (via reancre_crh).

from __future__ import annotations

import argparse
import json
import sys
from collections import deque
from pathlib import Path

from reancre_crh import RESERVED_DIRS, load_json, trier_formulations


def nettoie_scenario(sdir: Path, source: str, seuil: float) -> dict | None:
    """Rapport de nettoyage d'un scénario (None si fichier absent ou JSON
    illisible — le scénario est ignoré, signalé sur la sortie texte)."""
    path = sdir / source
    if not path.exists():
        print(f"    (pas de {source})")
        return None
    data = load_json(path)
    if data is None:
        print("    JSON illisible — scénario ignoré")
        return None

    tri = trier_formulations(data, seuil)
    # Reconstruction dans l'ordre d'origine : le tri parcourt le dictionnaire
    # dans le même ordre, chaque formulation est donc en tête d'exactement
    # une des trois files (les vides ne sont dans aucune : écartées).
    files = {classe: deque(entries) for classe, entries in tri.items()}

    def classe_de(section: str, cle: str, v: str) -> tuple[str | None, dict | None]:
        for classe, dq in files.items():
            if dq and dq[0]["section"] == section and dq[0]["cle"] == cle \
                    and dq[0]["formulation"] == v:
                return classe, dq.popleft()
        return None, None

    propres: dict = {}
    supprimees: list[dict] = []
    for section in ("diagnostics", "informations"):
        sec_src = (data.get("formulations", {}).get(section) or {})
        sec_out: dict = {}
        for cle, values in sec_src.items():
            garde = []
            for v in values or []:
                classe, entry = classe_de(section, cle, v)
                if classe == "exactes":
                    garde.append(v)
                elif classe == "reancrees":
                    garde.append(entry["extrait_propose"])
                elif classe == "orphelines":
                    supprimees.append(entry)
                # None : formulation vide, écartée sans trace
            sec_out[cle] = garde
        propres[section] = sec_out

    e, r, o = (len(tri[k]) for k in ("exactes", "reancrees", "orphelines"))
    print(f"    bilan : {e} gardée(s), {r} réancrée(s), {o} supprimée(s)")
    return {
        "scenario": sdir.name,
        "source": source,
        "seuil": seuil,
        "formulations": propres,
        "supprimees": supprimees,
    }


def nettoie_test(test_dir: Path, *, source: str = "crh_generation.txt",
                 seuil: float = 0.75, out_dir: Path | None = None) -> dict[str, dict]:
    """Nettoie tous les scénarios de test_dir, écrit <out_dir>/<scenario>.json
    et retourne {scenario: rapport}. out_dir par défaut : test_dir/export_dict."""
    test_dir = Path(test_dir)
    out_dir = Path(out_dir) if out_dir is not None else test_dir / "export_dict"

    dirs = sorted(
        d.name for d in test_dir.iterdir()
        if d.is_dir() and d.name not in RESERVED_DIRS and not d.name.startswith(".")
    )
    rapports: dict[str, dict] = {}
    for name in dirs:
        print(f"[{name}]")
        rapport = nettoie_scenario(test_dir / name, source, seuil)
        if rapport is not None:
            rapports[name] = rapport

    out_dir.mkdir(parents=True, exist_ok=True)
    for name, rapport in rapports.items():
        (out_dir / f"{name}.json").write_text(
            json.dumps(rapport, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    return rapports


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Nettoyage d'export des dictionnaires de formulations "
                    "(lecture seule sur le test)")
    ap.add_argument("test_dir", type=Path)
    ap.add_argument("--source", default="crh_generation.txt",
                    help="nom du fichier de sortie lu dans chaque dossier")
    ap.add_argument("--seuil", type=float, default=0.75,
                    help="score de similarité minimal pour réancrer (défaut 0.75)")
    ap.add_argument("--out", type=Path, default=None,
                    help="dossier d'export (défaut : <test_dir>/export_dict/)")
    args = ap.parse_args()

    rapports = nettoie_test(args.test_dir, source=args.source,
                            seuil=args.seuil, out_dir=args.out)
    if not rapports:
        print(f"Aucun scénario nettoyé dans {args.test_dir}")
        return 1

    exportees = sum(len(v) for r in rapports.values()
                    for sec in r["formulations"].values() for v in sec.values())
    supprimees = sum(len(r["supprimees"]) for r in rapports.values())
    out_dir = args.out if args.out is not None else args.test_dir / "export_dict"
    print(f"\nBilan global : {exportees} formulation(s) exportée(s), "
          f"{supprimees} supprimée(s), sur {len(rapports)} scénario(s)")
    print(f"Export : {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

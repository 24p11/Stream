# reancre_crh.py — réancrage des formulations du dictionnaire sur le texte du CR
#
# Pour chaque formulation du dictionnaire "formulations" d'un CRH généré :
#   - EXACTE    : présente telle quelle dans le texte (après normalisation douce)
#   - RÉANCRÉE  : absente, mais un passage très proche existe (fuzzy matching)
#                 → l'extrait exact du texte est proposé en remplacement
#   - ORPHELINE : aucun passage suffisamment proche → soit le texte exprime le
#                 diagnostic autrement (à extraire par la passe LLM), soit le
#                 contenu manque au CR (motif de régénération)
#
# Usage :
#   python reancre_crh.py work_prompts/tests/01 [--out crh_generation.txt]
#                         [--seuil 0.75] [--json rapport.json]
#
# Stdlib uniquement. Rapport en lecture seule : n'écrit jamais dans les tests.

from __future__ import annotations

import argparse
import difflib
import json
import sys
from pathlib import Path

if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

# Chargement et normalisation partag\u00e9s avec le v\u00e9rificateur : m\u00eame
# tol\u00e9rance de r\u00e9paration JSON (fermetures manquantes ET exc\u00e9dentaires),
# m\u00eames r\u00e8gles de normalisation douce.
from check_crh import RESERVED_DIRS, load_json as _load_json_repare, normalize


def load_json(path: Path) -> dict | None:
    """Chargement tol\u00e9rant (check_crh), r\u00e9parations silencieuses."""
    data, _repairs = _load_json_repare(path)
    return data


# ---------------------------------------------------------------- réancrage

def best_window(cr_words: list[str], target: str) -> tuple[float, str]:
    """Meilleure fenêtre de mots du CR pour `target` (déjà normalisé).
    Retourne (score, extrait)."""
    t_words = target.split()
    n = len(t_words)
    best_score, best_text = 0.0, ""
    sizes = range(max(1, n - 2), n + 5)
    matcher = difflib.SequenceMatcher(autojunk=False)
    matcher.set_seq2(target)
    for size in sizes:
        for i in range(0, len(cr_words) - size + 1):
            window = " ".join(cr_words[i:i + size])
            matcher.set_seq1(window)
            # bornes rapides avant le ratio complet
            if matcher.real_quick_ratio() <= best_score:
                continue
            if matcher.quick_ratio() <= best_score:
                continue
            score = matcher.ratio()
            if score > best_score:
                best_score, best_text = score, window
    return best_score, best_text


def trier_formulations(data: dict, seuil: float) -> dict:
    """Trie les formulations du dictionnaire d'un CRH généré en trois
    classes — le cœur du réancrage, partagé avec nettoie_dictionnaire.

    Retourne {"exactes": [...], "reancrees": [...], "orphelines": [...]},
    chaque entrée portant {"section", "cle", "formulation"} plus, hors
    exactes, "score" et "extrait_propose" (réancrées) ou
    "meilleur_candidat" (orphelines). Les formulations vides sont ignorées.
    L'ordre de parcours (diagnostics puis informations, clés puis valeurs
    dans l'ordre du dictionnaire) est préservé dans chaque classe."""
    cr_norm = normalize(data.get("CR", ""))
    cr_words = cr_norm.split()

    result: dict = {"exactes": [], "reancrees": [], "orphelines": []}
    formulations = data.get("formulations", {})
    for section in ("diagnostics", "informations"):
        for key, values in (formulations.get(section) or {}).items():
            for v in values or []:
                v_norm = normalize(v)
                if not v_norm:
                    continue
                entry = {"section": section, "cle": key, "formulation": v}
                if v_norm in cr_norm:
                    result["exactes"].append(entry)
                    continue
                score, extrait = best_window(cr_words, v_norm)
                entry["score"] = round(score, 3)
                if score >= seuil:
                    entry["extrait_propose"] = extrait
                    result["reancrees"].append(entry)
                else:
                    entry["meilleur_candidat"] = extrait
                    result["orphelines"].append(entry)
    return result


def reancre_scenario(sdir: Path, out_name: str, seuil: float) -> dict | None:
    path = sdir / out_name
    if not path.exists():
        print(f"    (pas de {out_name})")
        return None
    data = load_json(path)
    if data is None:
        print("    JSON illisible — scénario ignoré")
        return None

    result = trier_formulations(data, seuil)
    for entry in result["reancrees"]:
        print(f"    RÉANCRÉE  [{entry['cle']}] ({entry['score']:.2f})")
        print(f"      dico  : « {entry['formulation'][:70]} »")
        print(f"      texte : « {entry['extrait_propose'][:70]} »")
    for entry in result["orphelines"]:
        print(f"    ORPHELINE [{entry['cle']}] (meilleur score {entry['score']:.2f})")
        print(f"      dico  : « {entry['formulation'][:70]} »")

    e, r, o = (len(result[k]) for k in ("exactes", "reancrees", "orphelines"))
    print(f"    bilan : {e} exacte(s), {r} réancrée(s), {o} orpheline(s)")
    return result


# ---------------------------------------------------------------- main

def main() -> int:
    ap = argparse.ArgumentParser(description="Réancrage des formulations sur le texte des CRH")
    ap.add_argument("test_dir", type=Path)
    ap.add_argument("--out", default="crh_generation.txt")
    ap.add_argument("--seuil", type=float, default=0.75,
                    help="score de similarité minimal pour réancrer (défaut 0.75)")
    ap.add_argument("--json", type=Path, default=None,
                    help="écrire le rapport détaillé en JSON à ce chemin")
    args = ap.parse_args()

    if (args.test_dir / args.out).exists():
        dirs = [args.test_dir.name]
        base = args.test_dir.parent
    else:
        base = args.test_dir
        dirs = sorted(
            d.name for d in args.test_dir.iterdir()
            if d.is_dir() and d.name not in RESERVED_DIRS
            and not d.name.startswith(".")
        )
    if not dirs:
        print(f"Aucun dossier scénario dans {args.test_dir}")
        return 1

    rapport: dict[str, dict] = {}
    tot = {"exactes": 0, "reancrees": 0, "orphelines": 0}
    for name in dirs:
        print(f"[{name}]")
        res = reancre_scenario(base / name, args.out, args.seuil)
        if res is not None:
            rapport[name] = res
            for k in tot:
                tot[k] += len(res[k])

    total = sum(tot.values()) or 1
    print(f"\nBilan global : {tot['exactes']} exactes "
          f"({100*tot['exactes']//total} %), "
          f"{tot['reancrees']} réancrées "
          f"({100*tot['reancrees']//total} %), "
          f"{tot['orphelines']} orphelines "
          f"({100*tot['orphelines']//total} %) "
          f"— seuil {args.seuil}")

    if args.json:
        args.json.write_text(
            json.dumps(rapport, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"Rapport détaillé : {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

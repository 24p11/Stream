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
import re
import sys
import unicodedata
from pathlib import Path

RESERVED_DIRS = {"system", "batches", "__pycache__"}


# ---------------------------------------------------------------- chargement

def normalize(s: str) -> str:
    s = unicodedata.normalize("NFC", s)
    s = s.replace("\u2019", "'").replace("\u00a0", " ")
    return re.sub(r"\s+", " ", s).strip()


def _parse(raw: str) -> dict:
    try:
        return json.loads(raw, strict=False)
    except json.JSONDecodeError as exc:
        if exc.pos >= len(raw) - 1:
            opens = raw.count("{") - raw.count("}")
            if 0 < opens <= 3 and raw.count("[") == raw.count("]"):
                return json.loads(raw + "}" * opens, strict=False)
        raise


def load_json(path: Path) -> dict | None:
    raw = path.read_text(encoding="utf-8").strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    try:
        return _parse(raw)
    except json.JSONDecodeError:
        m = re.search(r"```(?:json)?\s*(\{.*)\s*```", raw, re.DOTALL)
        candidate = m.group(1) if m else None
        if candidate is None:
            i, j = raw.find("{"), raw.rfind("}")
            candidate = raw[i:j + 1] if 0 <= i < j else None
        if candidate:
            try:
                return _parse(candidate.strip())
            except json.JSONDecodeError:
                return None
        return None


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


def reancre_scenario(sdir: Path, out_name: str, seuil: float) -> dict | None:
    path = sdir / out_name
    if not path.exists():
        print(f"    (pas de {out_name})")
        return None
    data = load_json(path)
    if data is None:
        print("    JSON illisible — scénario ignoré")
        return None

    cr = data.get("CR", "")
    cr_norm = normalize(cr)
    cr_words = cr_norm.split()

    result = {"exactes": [], "reancrees": [], "orphelines": []}
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
                    print(f"    RÉANCRÉE  [{key}] ({score:.2f})")
                    print(f"      dico  : « {v[:70]} »")
                    print(f"      texte : « {extrait[:70]} »")
                else:
                    entry["meilleur_candidat"] = extrait
                    result["orphelines"].append(entry)
                    print(f"    ORPHELINE [{key}] (meilleur score {score:.2f})")
                    print(f"      dico  : « {v[:70]} »")

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

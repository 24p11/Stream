# show_crh.py — lecture des CRH générés par bench (le JSON sur une ligne est
# illisible dans l'éditeur : ici le champ "CR" est déplié en vrai texte).
# Usage :
#   python scripts/show_crh.py work_prompts/tests/02/0007/crh_generation.txt
#   python scripts/show_crh.py work_prompts/tests/02 [--out crh_generation.txt]
#   python scripts/show_crh.py work_prompts/tests/02 --md
# Sans --md : impression sur stdout. Avec --md : écrit un aperçu markdown À
# CÔTÉ de chaque .txt (ex. 0007/crh_generation.md — versionné avec le test) —
# à ouvrir dans VS Code avec « Markdown: Open Preview » (⇧⌘V).
# Aucune dépendance hors stdlib ; parsing tolérant réutilisé de check_crh.py.

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_crh import RESERVED_DIRS, load_json  # noqa: E402


def render(path: Path) -> str | None:
    """Texte lisible d'un fichier CRH : champ CR déplié + formulations."""
    data, repairs = load_json(path)
    if data is None:
        print(f"[{path}] JSON illisible — rien à afficher", file=sys.stderr)
        return None
    parts = []
    for note in repairs:
        parts.append(f"> réparation JSON : {note}\n")
    parts.append(str(data.get("CR", "(champ CR absent)")).strip() + "\n")
    formulations = data.get("formulations")
    if formulations is not None:
        parts.append("\n---\n\n## Formulations\n")
        parts.append("```json\n"
                     + json.dumps(formulations, ensure_ascii=False, indent=2)
                     + "\n```\n")
    return "\n".join(parts)


def scenario_files(test_dir: Path, out: str) -> list[Path]:
    return sorted(
        d / out
        for d in test_dir.iterdir()
        if d.is_dir()
        and d.name not in RESERVED_DIRS
        and not d.name.startswith(".")
        and (d / out).is_file()
    )


def main() -> int:
    ap = argparse.ArgumentParser(description="Affichage lisible des CRH générés")
    ap.add_argument("target", type=Path,
                    help="fichier CRH, dossier scénario ou dossier de test")
    ap.add_argument("--out", default="crh_generation.txt",
                    help="nom du fichier de sortie dans chaque dossier scénario")
    ap.add_argument("--md", action="store_true",
                    help="écrire un aperçu .md à côté de chaque .txt")
    args = ap.parse_args()

    if args.target.is_file():
        files = [args.target]
    elif (args.target / args.out).is_file():  # dossier scénario
        files = [args.target / args.out]
    elif args.target.is_dir():  # dossier de test
        files = scenario_files(args.target, args.out)
    else:
        print(f"Introuvable : {args.target}", file=sys.stderr)
        return 2
    if not files:
        print(f"Aucun {args.out} sous {args.target}", file=sys.stderr)
        return 2

    if args.md:
        for f in files:
            text = render(f)
            if text is None:
                continue
            dest = f.with_suffix(".md")
            dest.write_text(f"# {f.parent.name} — {f.name}\n\n" + text,
                            encoding="utf-8")
            print(dest)
    else:
        for f in files:
            text = render(f)
            if text is None:
                continue
            if len(files) > 1:
                print(f"\n{'=' * 25} {f.parent.name} — {f.name} {'=' * 25}\n")
            print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

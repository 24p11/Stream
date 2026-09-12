# check_crh.py — vérification mécanique des CRH générés par bench
# Usage : python check_crh.py work_prompts/tests/01 [--out crh_generation.txt]
#                             [--json rapport.json]
# Aucune dépendance hors stdlib. Code retour 1 si au moins un échec.
#
# Rapport structuré (--json <chemin>) : liste JSON, un objet par scénario —
#   {"scenario": "0003", "template": "medical_outpatient",
#    "echecs": [{"type": ..., "detail": ...}, ...],
#    "avertissements": [{"type": ..., "detail": ...}, ...],
#    "codes_scenario": [codes CIM-10 normalisés du bloc « Codage CIM10 »],
#    "codes_dictionnaire": [codes extraits des clés du dictionnaire]}
# Types d'échec STABLES (contrat pour prepare_regeneration) :
#   fichier_absent, json_invalide, gras, fantome, code_absent_texte,
#   fidelite_poids_taille.
# Types d'avertissement STABLES :
#   json_repare, cles_manquantes, cle_orpheline, mention_en_tete,
#   score_standardise, maladie_chronique, tabac_non_evoque.
# Champs additionnels par type : code_absent_texte porte "code" (normalisé) ;
#   cle_orpheline porte "cle" (la clé complète). La sortie texte reste le
#   format historique ; le JSON en est la forme exploitable.

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from pathlib import Path

RESERVED_DIRS = {"system", "batches", "export_dict", "__pycache__"}

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


# Code CIM-10 normalisé (sans point) : lettre + 2 chiffres + suffixe alphanum
CODE_CIM_RE = re.compile(r"[A-Z]\d{2}[0-9A-Z]{0,5}")


def normalise_code(code: str) -> str:
    """Forme canonique d'un code CIM-10 : majuscules, sans point ni espace,
    extension PMSI « +n » tronquée (« N85.8 » → « N858 », « C254+8 » →
    « C254 ») — l'appariement scénario/dictionnaire se fait sur le code de
    base, l'extension étant d'habillage variable."""
    code = code.replace(".", "").replace(" ", "").strip().upper()
    return code.split("+", 1)[0]


def codage_du_scenario(texte: str) -> list[tuple[str, str]]:
    """Paires (code normalisé, libellé) du bloc « Codage CIM10 » d'un
    user_generation.txt — DP d'abord, puis les DAS dans l'ordre. Le bloc
    s'arrête à la puce de premier niveau suivante (« - Acte CCAM : ... »).
    Le code est le dernier groupe parenthésé de la ligne qui a la forme
    d'un code (les libellés contiennent leurs propres parenthèses)."""
    paires: list[tuple[str, str]] = []
    dans_bloc = False
    for ligne in texte.splitlines():
        if ligne.startswith("- Codage CIM10"):
            dans_bloc = True
            continue
        if not dans_bloc:
            continue
        if ligne.startswith("- "):
            break
        brut = re.sub(r"^[*-]\s*", "", ligne.strip())
        brut = re.sub(r"^Diagnostic principal\s*:\s*", "", brut)
        for grp in reversed(re.findall(r"\(([^()]+)\)", brut)):
            code = normalise_code(grp)
            if CODE_CIM_RE.fullmatch(code):
                libelle = brut[: brut.rfind(f"({grp})")].strip().rstrip(",")
                paires.append((code, libelle))
                break
    return paires


def code_de_cle(cle: str) -> str | None:
    """Code CIM-10 d'une clé du dictionnaire diagnostics, quel que soit son
    habillage : « Libellé (Z431) », « Libellé (Z43.1) », « Z43.1 — Libellé »...
    Priorité aux groupes parenthésés (du dernier au premier) ; à défaut,
    premier motif de code dans la clé (heuristique : un libellé peut contenir
    « B12 » — l'habillage parenthésé reste la forme sûre). None si rien."""
    for grp in reversed(re.findall(r"\(([^()]+)\)", cle)):
        code = normalise_code(grp)
        if CODE_CIM_RE.fullmatch(code):
            return code
    for m in re.finditer(r"\b[A-Z]\d{2}(?:\.[0-9A-Z]{1,4}|[0-9A-Z]{0,4})\b", cle):
        code = normalise_code(m.group())
        if CODE_CIM_RE.fullmatch(code):
            return code
    return None


def normalize(s: str) -> str:
    """Normalisation douce pour la recherche de sous-chaînes :
    unicode NFC, apostrophes/espaces typographiques unifiées, espaces répétés."""
    s = unicodedata.normalize("NFC", s)
    s = s.replace("\u2019", "'").replace("\u00a0", " ")
    return re.sub(r"\s+", " ", s)


def _parse(raw: str, repairs: list[str]) -> dict | None:
    """Parse tolérant : strict=False + réparation des fermetures finales
    (manquantes OU excédentaires — le modèle omet parfois une accolade,
    ou glisse un `]`/`}` orphelin juste avant la fin)."""
    try:
        return json.loads(raw, strict=False)
    except json.JSONDecodeError as exc:
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
                    return data
                except json.JSONDecodeError:
                    pass
        # Fermeture excédentaire en toute fin (ex. `...]}}]}` au lieu de
        # `...]}}}`) : on retire un à un les `]`/`}` pointés par l'erreur,
        # UNIQUEMENT dans les derniers caractères, et on le signale.
        candidate = raw
        removed = 0
        last_exc = exc
        while removed < 3:
            pos = last_exc.pos
            if pos < len(candidate) - 8 or pos >= len(candidate) \
                    or candidate[pos] not in "]}":
                break
            candidate = candidate[:pos] + candidate[pos + 1:]
            removed += 1
            try:
                data = json.loads(candidate, strict=False)
                repairs.append(
                    f"JSON réparé : {removed} fermeture(s) excédentaire(s) "
                    "(']' ou '}') retirée(s) en fin de fichier"
                )
                return data
            except json.JSONDecodeError as next_exc:
                last_exc = next_exc
        raise


def load_json(path: Path) -> tuple[dict | None, list[str]]:
    """Retourne (données, avertissements de réparation)."""
    raw = path.read_text(encoding="utf-8").strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    repairs: list[str] = []
    try:
        return _parse(raw, repairs), repairs
    except json.JSONDecodeError as first_exc:
        # Extraction : sortie non-JSON pure (préambule/prose autour de
        # l'objet — typique des CRH v1 au prefix déclaratif). On cherche un
        # bloc ```json ... ``` n'importe où, sinon du premier { au dernier }.
        m = re.search(r"```(?:json)?\s*(\{.*)\s*```", raw, re.DOTALL)
        candidate = m.group(1) if m else None
        if candidate is None:
            i, j = raw.find("{"), raw.rfind("}")
            candidate = raw[i:j + 1] if 0 <= i < j else None
        if candidate and candidate.strip() != raw:
            try:
                data = _parse(candidate.strip(), repairs)
                repairs.append(
                    "sortie non-JSON pure : texte hors objet détecté "
                    "(préambule/prefix déclaratif), JSON extrait"
                )
                return data, repairs
            except json.JSONDecodeError:
                pass
        ctx = raw[max(0, first_exc.pos - 60):first_exc.pos + 60]
        ctx = ctx.replace("\n", "\\n")
        print(f"    ERREUR JSON : {first_exc.msg} (char {first_exc.pos})")
        print(f"      contexte : ...{ctx}...")
        return None, repairs


def contexte_enrichi(sdir: Path) -> dict | None:
    """Contexte patient fourni par l'enrichissement, lu dans
    user_generation.txt (lignes « - Taille : N cm » / « - Poids : N kg ») —
    la détection se fait sur le prompt lui-même, pas sur un fichier d'état.
    Retourne None si le scénario n'est pas enrichi."""
    ug = sdir / "user_generation.txt"
    if not ug.is_file():
        return None
    texte = ug.read_text(encoding="utf-8")
    m_taille = re.search(r"^- Taille : (\d+) cm", texte, re.M)
    m_poids = re.search(r"^- Poids : (\d+) kg", texte, re.M)
    if not (m_taille and m_poids):
        return None
    m_tabac = re.search(r"^- Tabac : (.+)$", texte, re.M)
    return {
        "taille_cm": m_taille.group(1),
        "poids_kg": m_poids.group(1),
        "tabac": (m_tabac.group(1).strip() if m_tabac else ""),
    }


def check_scenario(sdir: Path, out_name: str) -> dict:
    """Vérifie un scénario : imprime le détail (format historique) et
    retourne le rapport structuré (schéma documenté en tête de fichier)."""
    rapport: dict = {
        "scenario": sdir.name,
        "template": None,
        "echecs": [],
        "avertissements": [],
        "codes_scenario": [],
        "codes_dictionnaire": [],
    }
    tpl = sdir / "template.txt"
    if tpl.is_file():
        rapport["template"] = tpl.read_text(encoding="utf-8").strip()

    def echec(type_: str, detail: str, **extra) -> None:
        rapport["echecs"].append({"type": type_, "detail": detail, **extra})
        print(f"    ECHEC  {detail}")

    def avert(type_: str, detail: str, **extra) -> None:
        rapport["avertissements"].append({"type": type_, "detail": detail, **extra})
        print(f"    AVERT  {detail}")

    path = sdir / out_name
    if not path.exists():
        echec("fichier_absent", f"fichier absent : {path.name}")
        return rapport

    data, repairs = load_json(path)
    for r in repairs:
        avert("json_repare", r)
    if data is None:
        # le détail (ERREUR JSON + contexte) est déjà imprimé par load_json
        rapport["echecs"].append(
            {"type": "json_invalide", "detail": "JSON illisible (voir ERREUR JSON)"})
        return rapport

    cr = data.get("CR", "")
    cr_norm = normalize(cr)

    # 1. Gras hors titres ### (les titres n'utilisent pas **)
    bold = re.findall(r"\*\*[^*\n]+\*\*", cr)
    if bold:
        sample = ", ".join(b[:40] for b in bold[:4])
        echec("gras", f"gras interdit ({len(bold)} occurrence(s)) : {sample}")

    # 2. Fidélité du dictionnaire : chaque formulation doit être dans le texte
    formulations = data.get("formulations", {})
    for section in ("diagnostics", "informations"):
        for key, values in (formulations.get(section) or {}).items():
            for v in values or []:
                if normalize(v) not in cr_norm:
                    echec("fantome",
                          f"formulation fantôme [{section}/{key}] : « {v[:60]} »")

    # 2 bis. Complétude du codage : chaque code du scénario (bloc « Codage
    # CIM10 » de user_generation.txt) doit porter une clé du dictionnaire
    # diagnostics ; une clé sans code du scénario est signalée.
    ug = sdir / "user_generation.txt"
    codage = codage_du_scenario(ug.read_text(encoding="utf-8")) if ug.is_file() else []
    rapport["codes_scenario"] = [code for code, _ in codage]
    diag = formulations.get("diagnostics") or {}
    codes_cles = {cle: code_de_cle(cle) for cle in diag}
    rapport["codes_dictionnaire"] = sorted({c for c in codes_cles.values() if c})
    for code, libelle in codage:
        if code not in codes_cles.values():
            echec("code_absent_texte",
                  f"code du scénario absent du dictionnaire : {code} ({libelle[:60]})",
                  code=code)
    for cle, code in codes_cles.items():
        if code is None or code not in rapport["codes_scenario"]:
            avert("cle_orpheline",
                  f"clé du dictionnaire sans code du scénario : « {cle[:60]} »",
                  cle=cle)

    # 3. Schéma du dictionnaire informations : clés attendues présentes
    info = formulations.get("informations") or {}
    missing_keys = [k for k in EXPECTED_INFO_KEYS if k not in info]
    if missing_keys:
        avert("cles_manquantes",
              f"clés absentes du dictionnaire : {', '.join(missing_keys)}")

    # 4. Mentions obligatoires de l'en-tête — en avertissement : l'IPP sera
    # fourni par l'enrichissement des scénarios (chantier futur) ; repassera
    # en ECHEC (contrôle de fidélité) quand l'identité viendra du scénario.
    if "IPP" not in cr:
        avert("mention_en_tete", "mention IPP absente de l'en-tête")
    for label in ("Nom", "Prénom", "Date de naissance"):
        if label not in cr:
            avert("mention_en_tete", f"mention « {label} » absente de l'en-tête")

    # 5. Scores standardisés (avertissement : légitimité à juger)
    for m in sorted({m.upper() for m in SCORE_RE.findall(cr)}):
        avert("score_standardise", f"score standardisé présent : {m}")

    # 6. Maladies chroniques hors scénario (avertissement : vérifier le scénario)
    for m in sorted({m.lower() for m in CHRONIC_RE.findall(cr)}):
        avert("maladie_chronique",
              f"maladie chronique mentionnée : {m} (à confronter au scénario)")

    # 7. Contexte patient enrichi : poids/taille restitués, tabac évoqué
    ctx7 = contexte_enrichi(sdir)
    if ctx7:
        for valeur, unite, label in ((ctx7["poids_kg"], "kg", "poids"),
                                     (ctx7["taille_cm"], "cm", "taille")):
            if not re.search(rf"\b{valeur}\s*{unite}", cr):
                echec("fidelite_poids_taille",
                      f"{label} du scénario ({valeur} {unite}) absent du CR")
        if "actif" in ctx7["tabac"].lower() and not re.search(
                r"tabac|tabagi|fume", cr, re.IGNORECASE):
            avert("tabac_non_evoque",
                  "fumeur actif au scénario, tabac non évoqué dans le CR")

    if not rapport["echecs"] and not rapport["avertissements"]:
        print("    OK")
    return rapport


def ecrire_rapport_json(path: Path | None, rapports: list[dict]) -> None:
    if path is None:
        return
    path.write_text(json.dumps(rapports, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")
    print(f"Rapport JSON : {path}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Vérification mécanique des CRH générés")
    ap.add_argument("test_dir", type=Path)
    ap.add_argument("--out", default="crh_generation.txt",
                    help="nom du fichier de sortie à vérifier dans chaque dossier")
    ap.add_argument("--json", type=Path, default=None,
                    help="écrire le rapport structuré par scénario (JSON) à ce chemin")
    args = ap.parse_args()

    if (args.test_dir / args.out).exists():
        # Le chemin donné est directement un dossier scénario
        print(f"[{args.test_dir.name}]")
        rapports = [check_scenario(args.test_dir, args.out)]
        f = len(rapports[0]["echecs"])
        w = len(rapports[0]["avertissements"])
        print(f"\nBilan : {f} échec(s), {w} avertissement(s) sur 1 scénario")
        ecrire_rapport_json(args.json, rapports)
        return 1 if f else 0

    dirs = sorted(
        d.name for d in args.test_dir.iterdir()
        if d.is_dir() and d.name not in RESERVED_DIRS and not d.name.startswith(".")
    )
    if not dirs:
        print(f"Aucun dossier scénario dans {args.test_dir} "
              f"(et pas de {args.out} à sa racine)")
        return 1

    rapports = []
    total_fails = total_warns = 0
    for name in dirs:
        print(f"[{name}]")
        r = check_scenario(args.test_dir / name, args.out)
        rapports.append(r)
        total_fails += len(r["echecs"])
        total_warns += len(r["avertissements"])

    print(f"\nBilan : {total_fails} échec(s), {total_warns} avertissement(s) "
          f"sur {len(dirs)} scénario(s)")
    ecrire_rapport_json(args.json, rapports)
    return 1 if total_fails else 0


if __name__ == "__main__":
    sys.exit(main())

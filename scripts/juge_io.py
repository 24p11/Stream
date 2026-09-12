"""Contrat d'E/S du juge d'équivalence sémantique (modèle encodeur externe).

Le juge décide, pour chaque code CIM-10 d'un scénario, si le texte du CRH
apporte une PREUVE DIRECTE du diagnostic — c'est-à-dire si l'un des passages
proposés (ou le texte, éclairé par la fiche du code) exprime le diagnostic
codé. Ce module ne juge rien : il fixe le CONTRAT d'interface entre le banc
(`bench`/scripts) et l'équipe qui entraîne l'encodeur. Ce docstring est la
référence du contrat.

Entrées du juge — `ecrire_entrees_juge` produit un JSONL UTF-8, une ligne
par code du scénario (DP puis DAS, dans l'ordre du bloc « Codage CIM10 » de
user_generation.txt), scénarios triés :

    {"scenario": "0003",          # nom du dossier scénario
     "code": "G122",              # code CIM-10 normalisé (majuscules, sans
                                  # point : « G12.2 » -> « G122 »)
     "libelle": "...",            # libellé du bloc « Codage CIM10 »
     "fiche": "...",              # contenu de la balise <fiche_code> du code
                                  # dans user_generation.txt, ou null si le
                                  # scénario n'a pas de fiche pour ce code
     "passages": ["...", ...]}    # formulations PROPRES du dictionnaire pour
                                  # ce code : celles des clés du dictionnaire
                                  # "diagnostics" rattachées au code, APRÈS
                                  # nettoie_dictionnaire (exactes ou
                                  # réancrées — toutes présentes verbatim
                                  # dans le texte du CR). Liste vide
                                  # possible : le code n'a ni clé ni passage.

Verdicts du juge — `lire_verdicts_juge` lit un JSONL UTF-8, une ligne par
entrée jugée, portant EXACTEMENT les clés suivantes (lignes vides admises) :

    {"scenario": "0003",
     "code": "G122",              # normalisé ou pointé, re-normalisé ici
     "preuve_directe": true,      # booléen strict (pas 0/1, pas "oui")
     "passage_retenu": "...",     # le passage qui fait preuve (chaîne),
                                  # ou null (attendu si preuve_directe false)
     "score": 0.93}               # confiance du juge, nombre dans [0, 1]

Validation STRICTE à la lecture — toute entorse lève BenchError en nommant
fichier et ligne : JSON invalide, clé manquante ou inattendue, types
incorrects, score hors [0, 1], doublon (scenario, code). Le résultat est
{(scenario, code): {"preuve_directe", "passage_retenu", "score"}}.

Aval : les verdicts sans preuve directe nourrissent prepare_regeneration
(bloc CORRECTION REQUISE) ; les passages retenus documentent l'export.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

# importable depuis la racine du repo (bench) comme depuis scripts/
_RACINE = Path(__file__).resolve().parents[1]
for chemin in (_RACINE, _RACINE / "scripts"):
    if str(chemin) not in sys.path:
        sys.path.insert(0, str(chemin))

from bench.errors import BenchError  # noqa: E402
from check_crh import codage_du_scenario, code_de_cle, normalise_code  # noqa: E402

# Sections de fiche dont les puces sont des entités/synonymes du code
# (les autres — « À ne pas décrire », « Formes spécifiées »... — décrivent
# le périmètre des AUTRES codes)
SECTIONS_ENTITES = ("Périmètre clinique du code",
                    "Formulations cliniques alternatives")

FICHE_RE = re.compile(r'<fiche_code code="([^"]+)">\s*(.*?)\s*</fiche_code>',
                      re.DOTALL)

CLES_VERDICT = {"scenario", "code", "preuve_directe", "passage_retenu", "score"}


def fiches_du_scenario(texte: str) -> dict[str, dict]:
    """Fiches <fiche_code> d'un user_generation.txt, indexées par code
    normalisé : {"code_affiche", "libelle", "texte" (contenu de la balise),
    "entites" (puces des sections SECTIONS_ENTITES, hors renvois [→ ...])}."""
    fiches: dict[str, dict] = {}
    for code_affiche, corps in FICHE_RE.findall(texte):
        m = re.search(r"^#\s*\S+\s*—\s*(.+)$", corps, re.M)
        libelle = m.group(1).strip() if m else None
        entites: list[str] = []
        section = None
        for ligne in corps.splitlines():
            m_sec = re.match(r"^##\s*(.+)$", ligne)
            if m_sec:
                section = m_sec.group(1).strip()
                continue
            if section in SECTIONS_ENTITES:
                m_puce = re.match(r"^\s*-\s+(.+)$", ligne)
                if m_puce and "[→" not in m_puce.group(1):
                    entites.append(m_puce.group(1).strip())
        fiches[normalise_code(code_affiche)] = {
            "code_affiche": code_affiche,
            "libelle": libelle,
            "texte": corps,
            "entites": entites,
        }
    return fiches


def ecrire_entrees_juge(test_dir: Path,
                        rapport_nettoyage: dict[str, dict] | Path | str,
                        out_jsonl: Path | str) -> list[dict]:
    """Écrit le fichier d'entrées du juge (contrat en tête de module) et
    retourne les lignes écrites.

    rapport_nettoyage : le retour de nettoie_dictionnaire.nettoie_test
    ({scenario: rapport}), ou le chemin du dossier d'export
    (<test_dir>/export_dict/) dont les <scenario>.json sont relus."""
    test_dir = Path(test_dir)
    if isinstance(rapport_nettoyage, (str, Path)):
        dossier = Path(rapport_nettoyage)
        if not dossier.is_dir():
            raise BenchError(
                f"dossier de nettoyage introuvable : {dossier} "
                "(lancer nettoie_dictionnaire d'abord)")
        rapports = {p.stem: json.loads(p.read_text(encoding="utf-8"))
                    for p in sorted(dossier.glob("*.json"))}
    else:
        rapports = dict(rapport_nettoyage)
    if not rapports:
        raise BenchError(f"aucun rapport de nettoyage pour {test_dir}")

    lignes: list[dict] = []
    for scenario in sorted(rapports):
        ug = test_dir / scenario / "user_generation.txt"
        if not ug.is_file():
            raise BenchError(f"user_generation.txt absent pour le scénario "
                             f"{scenario} : {ug}")
        texte = ug.read_text(encoding="utf-8")
        codage = codage_du_scenario(texte)
        if not codage:
            raise BenchError(f"bloc « Codage CIM10 » introuvable ou vide "
                             f"dans {ug}")
        fiches = fiches_du_scenario(texte)
        diag = (rapports[scenario].get("formulations") or {}).get("diagnostics") or {}
        for code, libelle in codage:
            passages: list[str] = []
            for cle, valeurs in diag.items():
                if code_de_cle(cle) == code:
                    passages.extend(valeurs or [])
            lignes.append({
                "scenario": scenario,
                "code": code,
                "libelle": libelle,
                "fiche": (fiches.get(code) or {}).get("texte"),
                "passages": passages,
            })

    out = Path(out_jsonl)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        "".join(json.dumps(l, ensure_ascii=False) + "\n" for l in lignes),
        encoding="utf-8")
    return lignes


def lire_verdicts_juge(jsonl: Path | str) -> dict[tuple[str, str], dict]:
    """Lit et valide strictement les verdicts du juge (contrat en tête de
    module). Retourne {(scenario, code normalisé): {"preuve_directe",
    "passage_retenu", "score"}} ; BenchError à la moindre entorse."""
    path = Path(jsonl)
    if not path.is_file():
        raise BenchError(f"fichier de verdicts introuvable : {path}")

    verdicts: dict[tuple[str, str], dict] = {}
    for num, ligne in enumerate(path.read_text(encoding="utf-8").splitlines(),
                                start=1):
        if not ligne.strip():
            continue
        try:
            obj = json.loads(ligne)
        except json.JSONDecodeError as exc:
            raise BenchError(f"{path}:{num} : JSON invalide ({exc.msg})") from exc
        if not isinstance(obj, dict) or set(obj) != CLES_VERDICT:
            recu = sorted(obj) if isinstance(obj, dict) else type(obj).__name__
            raise BenchError(f"{path}:{num} : clés attendues "
                             f"{sorted(CLES_VERDICT)}, reçu {recu}")
        if not isinstance(obj["scenario"], str) or not obj["scenario"]:
            raise BenchError(f"{path}:{num} : scenario doit être une chaîne "
                             "non vide")
        if not isinstance(obj["code"], str) or not obj["code"]:
            raise BenchError(f"{path}:{num} : code doit être une chaîne non vide")
        if not isinstance(obj["preuve_directe"], bool):
            raise BenchError(f"{path}:{num} : preuve_directe doit être un "
                             "booléen strict")
        if obj["passage_retenu"] is not None \
                and not isinstance(obj["passage_retenu"], str):
            raise BenchError(f"{path}:{num} : passage_retenu doit être une "
                             "chaîne ou null")
        score = obj["score"]
        if isinstance(score, bool) or not isinstance(score, (int, float)) \
                or not 0 <= score <= 1:
            raise BenchError(f"{path}:{num} : score doit être un nombre "
                             "dans [0, 1]")
        cle = (obj["scenario"], normalise_code(obj["code"]))
        if cle in verdicts:
            raise BenchError(f"{path}:{num} : doublon (scenario, code) = {cle}")
        verdicts[cle] = {
            "preuve_directe": obj["preuve_directe"],
            "passage_retenu": obj["passage_retenu"],
            "score": float(score),
        }
    if not verdicts:
        raise BenchError(f"aucun verdict dans {path}")
    return verdicts

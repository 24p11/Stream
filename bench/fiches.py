"""Accès consommateur aux bibliothèques de fiches CIM-10 de recode-icd.

Le CONTRAT d'interface fait foi et vit à une seule adresse (ne pas le
copier ici — une copie divergerait silencieusement) :

    https://github.com/24p11/recode-icd/blob/main/docs/livraison/CONTRAT.md

Un exemplaire épinglé (``CONTRAT.md``) est embarqué à la racine de chaque
bibliothèque livrée et dans l'archive de livraison consommée.

Règles du contrat implémentées ici — ce module est le SEUL point d'accès
du projet aux bibliothèques :

- **l'index fait foi** : la liste des fiches est exactement le contenu de
  ``index.csv`` (nom canonique ; ``_index.csv`` est déprécié et n'est
  jamais lu — aucun repli). Un ``.md`` sur disque hors index n'existe
  pas : jamais de parcours du répertoire, toute jointure passe par la
  colonne ``code`` ;
- **noyau garanti** (``format_version`` 1) : ``code``, ``fichier``,
  ``statut_mco``, ``format_version``. Un ``format_version`` supérieur à
  :data:`FORMAT_VERSION_CONNUE` fait échouer le chargement bruyamment —
  c'est le mécanisme d'annonce des ruptures ;
- **tirage/génération** : ne retenir que ``classe_generation ==
  "emissible"`` (:func:`codes_emissibles`). Les fiches
  ``tronc_composition`` (chapitre XX) ne sont pas émissibles telles
  quelles — un code composé se résout via ``recode-icd resoudre``,
  jamais par jointure manuelle sur le tronc. ``classe_generation`` est
  une colonne informative : couplage accepté, à suivre avec le dépôt
  producteur ;
- **codes introuvables** : jamais silencieux — :func:`codes_sans_fiche`
  rend la liste à journaliser (la raison motivée de chaque absence
  s'obtient côté producteur : ``recode-icd resoudre --journal``).
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

import polars as pl

from bench.errors import BenchError

# Version du contrat connue de ce projet (voir CONTRAT.md). Une livraison
# d'un format_version supérieur exige de relire les notes de livraison et
# d'adapter ce module AVANT de consommer.
FORMAT_VERSION_CONNUE = 1

NOYAU = ("code", "fichier", "statut_mco", "format_version")


def _normaliser_code(code: str) -> str:
    """Forme d'appariement d'un code CIM-10 : majuscules, sans point
    (l'index écrit les codes pointés — « D50.8 » — quand la chaîne aval
    manipule des codes compacts — « D508 »)."""
    return str(code).replace(".", "").replace(" ", "").strip().upper()


def charger_index(bibliotheque: Path) -> pl.DataFrame:
    """Charge et valide l'index d'une bibliothèque de fiches.

    ``bibliotheque`` est la racine livrée (ex.
    ``data/aphp/referentials/cards_library``). Échec bruyant
    (:class:`BenchError`) si ``index.csv`` manque, si le noyau de
    colonnes du contrat est absent, ou si ``format_version`` est inconnu
    ou non constant. Ne lit JAMAIS ``_index.csv`` (déprécié)."""
    bibliotheque = Path(bibliotheque)
    chemin = bibliotheque / "index.csv"
    if not chemin.is_file():
        raise BenchError(
            f"index.csv absent de la bibliothèque {bibliotheque} — l'index "
            "canonique fait foi (CONTRAT.md du producteur recode-icd) ; "
            "`_index.csv` est déprécié et n'est pas lu. Vérifier que la "
            "bibliothèque provient d'une archive de livraison sous contrat."
        )

    # tout en chaînes : le noyau est textuel, format_version est converti
    # explicitement plus bas, et un index partiel ne doit pas faire échouer
    # la lecture avant le diagnostic des colonnes manquantes
    index = pl.read_csv(chemin, infer_schema_length=0)

    manquantes = [c for c in NOYAU if c not in index.columns]
    if manquantes:
        raise BenchError(
            f"{chemin} : colonne(s) du noyau garanti absente(s) : "
            f"{', '.join(manquantes)} (contrat format_version "
            f"{FORMAT_VERSION_CONNUE}, noyau {', '.join(NOYAU)}). "
            "Bibliothèque antérieure au contrat, ou rupture non annoncée."
        )

    versions = index["format_version"].unique().to_list()
    if len(versions) != 1:
        raise BenchError(
            f"{chemin} : format_version non constant ({versions}) — le "
            "contrat le garantit constant sur toutes les lignes."
        )
    try:
        version = int(versions[0])
    except (TypeError, ValueError):
        raise BenchError(
            f"{chemin} : format_version illisible ({versions[0]!r})."
        ) from None
    if version > FORMAT_VERSION_CONNUE:
        raise BenchError(
            f"{chemin} : format_version {version} > {FORMAT_VERSION_CONNUE} "
            "(version connue du projet) — rupture de contrat annoncée par "
            "le producteur : lire les notes de la livraison et CONTRAT.md, "
            "adapter bench/fiches.py, puis relever FORMAT_VERSION_CONNUE."
        )

    return index


def codes_emissibles(index: pl.DataFrame) -> list[str]:
    """Codes autorisés pour un tirage ou une génération :
    ``classe_generation == "emissible"`` (les ``tronc_composition`` du
    chapitre XX sont exclus — composition via ``recode-icd resoudre``).

    BenchError si l'index ne porte pas ``classe_generation`` (bibliothèque
    qui n'est pas une bibliothèque de génération)."""
    if "classe_generation" not in index.columns:
        raise BenchError(
            "index sans colonne classe_generation : cette bibliothèque "
            "n'est pas une bibliothèque de génération — aucun code ne peut "
            "y être tiré pour générer."
        )
    return (
        index.filter(pl.col("classe_generation") == "emissible")["code"]
        .to_list()
    )


def codes_sans_fiche(index: pl.DataFrame, codes: Iterable[str]) -> list[str]:
    """Codes demandés absents de l'index — à JOURNALISER par l'appelant,
    jamais à ignorer (contrat : pas d'échec silencieux, pas de bricolage ;
    motifs détaillés via ``recode-icd resoudre --journal`` côté
    producteur). Appariement par la colonne ``code`` de l'index, formes
    pointées et compactes confondues ; l'ordre d'appel est préservé."""
    connus = {_normaliser_code(c) for c in index["code"].to_list()}
    absents: list[str] = []
    for code in codes:
        if _normaliser_code(code) not in connus and code not in absents:
            absents.append(code)
    return absents

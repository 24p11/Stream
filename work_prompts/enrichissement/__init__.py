"""Enrichissement de scénarios CIM-10 AP-HP (tabac/alcool, anthropométrie).

Package autonome destiné à être copié dans fictomed (voir
``README_fictomed.md``). API publique :

- :func:`enrichir_scenarios` — enrichit un DataFrame de profils/scénarios ;
- :func:`bloc_contexte` — lignes « contexte patient » pour le prompt user ;
- :class:`Politique` — décisions de doctrine (âge minimal, exclusions,
  probabilités de codage) ;
- les simulateurs :class:`SimulateurAnthropometrie` et
  :class:`SimulateurIntoxications` pour un usage direct.

``integration_stream.py`` (colle avec le banc d'essai Stream) n'est PAS
exporté ici et n'est pas à copier dans fictomed.
"""

from .anthropometrie import Anthropometrie, SimulateurAnthropometrie
from .enrichissement import (
    COLONNES_ENRICHISSEMENT,
    Politique,
    bloc_contexte,
    enrichir_scenarios,
)
from .intoxications import Alcool, Intoxications, SimulateurIntoxications, Tabac

__all__ = [
    "Alcool",
    "Anthropometrie",
    "COLONNES_ENRICHISSEMENT",
    "Intoxications",
    "Politique",
    "SimulateurAnthropometrie",
    "SimulateurIntoxications",
    "Tabac",
    "bloc_contexte",
    "enrichir_scenarios",
]

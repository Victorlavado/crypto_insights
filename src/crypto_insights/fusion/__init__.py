"""Fusion: combina signals en estado por proyecto.

- layer2.py: filtro de viabilidad (green/amber/red/blocked)
- layer1.py: composite score + state_from_scores (Fase 3)
- archetype_rules.py: pesos por archetype (Fase 3)
"""

from .layer2 import Layer2Result, evaluate_layer2

__all__ = ["Layer2Result", "evaluate_layer2"]

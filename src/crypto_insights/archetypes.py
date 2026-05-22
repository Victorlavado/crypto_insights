"""Archetype metadata: quién aplica qué signal y con qué peso.

Tabla declarativa, no decisión por LLM. Cuando se reweighta vía learnings/,
modificar aquí + bumpear formula_version donde corresponda.

Fuente de verdad para el weighting está en fusion/archetype_rules.py — esto
solo expone metadatos (consolidation_applies, etc.) que necesitan pipeline,
signals y dashboard.
"""

from __future__ import annotations

from dataclasses import dataclass

from .models import Archetype


@dataclass(frozen=True, slots=True)
class ArchetypeMeta:
    """Metadata aplicable a un archetype completo."""

    name: Archetype
    consolidation_applies: bool  # True si el signal consolidation_breakout aplica


_META: dict[Archetype, ArchetypeMeta] = {
    Archetype.MEMECOIN_BRAND: ArchetypeMeta(Archetype.MEMECOIN_BRAND, consolidation_applies=False),
    Archetype.INFRA_PMF: ArchetypeMeta(Archetype.INFRA_PMF, consolidation_applies=True),
    Archetype.TESIS_MACRO: ArchetypeMeta(Archetype.TESIS_MACRO, consolidation_applies=True),
    Archetype.L1_MADURO: ArchetypeMeta(Archetype.L1_MADURO, consolidation_applies=True),
    Archetype.DEFI_BLUE_CHIP: ArchetypeMeta(Archetype.DEFI_BLUE_CHIP, consolidation_applies=True),
    Archetype.POST_TGE: ArchetypeMeta(Archetype.POST_TGE, consolidation_applies=False),
}


def get_archetype_meta(archetype: Archetype) -> ArchetypeMeta:
    return _META[archetype]


def all_archetypes() -> list[Archetype]:
    return list(_META.keys())

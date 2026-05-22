"""Tipos puros internos: dataclasses sin overhead de validación.

Pydantic se reserva para boundaries externos (config, payloads de connectors,
schemas de output CLI). Aquí van los tipos que viajan dentro del pipeline en
el hot loop (30 proyectos × ~10 signals × 365 días en backfill).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Any


class Archetype(StrEnum):
    """Archetypes definidos en el brainstorm + ADR 0001."""

    MEMECOIN_BRAND = "memecoin-brand"
    INFRA_PMF = "infra-pmf"
    TESIS_MACRO = "tesis-macro"
    L1_MADURO = "l1-maduro"
    DEFI_BLUE_CHIP = "defi-blue-chip"
    POST_TGE = "post-tge"


class ProjectStateValue(StrEnum):
    """Estados de PROJECT_STATE.current_state. Coincide con CHECK del schema."""

    ACUMULACION = "acumulacion"
    ACELERACION = "aceleracion"
    DISTRIBUCION = "distribucion"
    COLAPSO = "colapso"
    RESET = "reset"
    BLOCKED = "blocked"
    DEGRADED = "degraded"
    UNKNOWN = "unknown"


class Layer2Flag(StrEnum):
    GREEN = "green"
    AMBER = "amber"
    RED = "red"


class ReasonCode(StrEnum):
    """Códigos estructurados para PROJECT_STATE.reason_code (extensible vía migration)."""

    NORMAL = "NORMAL"
    UNLOCK_INMINENTE = "UNLOCK_INMINENTE"
    DEV_ABANDONED = "DEV_ABANDONED"
    TVL_COLLAPSE = "TVL_COLLAPSE"
    LISTING_RECENT = "LISTING_RECENT"
    GAP_DATOS = "GAP_DATOS"


class BatchStatus(StrEnum):
    RUNNING = "running"
    COMPLETE = "complete"
    PARTIAL = "partial"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class Project:
    """Proyecto en la watchlist. Cargado desde data/watchlist.yaml y persistido en projects."""

    id: int | None  # None hasta primer INSERT
    symbol: str
    archetype: Archetype
    coingecko_id: str | None = None
    chain: str | None = None
    contract: str | None = None
    notes: str | None = None


@dataclass(frozen=True, slots=True)
class SourceSnapshot:
    """Resultado normalizado de un connector.fetch(project).

    payload contiene lo que devolvió la API ya parseado a estructura python
    pero NO normalizado a signals. La normalización a derived_signals la hace
    pipeline/derived.py.
    """

    project_id: int
    source: str
    snapshot_date: date
    payload: dict[str, Any]
    payload_schema_version: int = 1
    connector_version: str = "v0.1.0"
    fetched_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True, slots=True)
class ConnectorFailure:
    source: str
    project_symbol: str
    error: str


@dataclass(frozen=True, slots=True)
class ConnectorResult:
    """Resultado de _safe_fetch en pipeline. Sum type sobre snapshot u error."""

    snapshot: SourceSnapshot | None
    failure: ConnectorFailure | None

    @property
    def is_ok(self) -> bool:
        return self.snapshot is not None

    @classmethod
    def ok(cls, snap: SourceSnapshot) -> ConnectorResult:
        return cls(snapshot=snap, failure=None)

    @classmethod
    def failed(cls, source: str, project_symbol: str, error: str) -> ConnectorResult:
        return cls(snapshot=None, failure=ConnectorFailure(source, project_symbol, error))


@dataclass(frozen=True, slots=True)
class DerivedSignal:
    project_id: int
    signal_date: date
    signal_name: str
    value: float | None
    formula_version: str = "v1"


@dataclass(frozen=True, slots=True)
class BatchResult:
    batch_id: str
    status: BatchStatus
    sources_ok: int
    sources_failed: list[ConnectorFailure]
    started_at: datetime
    finished_at: datetime

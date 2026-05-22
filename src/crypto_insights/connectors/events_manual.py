"""Events connector — fuente: manual YAML curated.

Plan B confirmado tras Q11 (2026-05-10): DeFiLlama /emissions es Pro-only.
Para el MVP, `data/events.yaml` (gitignored) es la fuente primaria de unlocks
y eventos categóricos (listings, halvings, forks).

Diferencia conceptual con un connector HTTP: este NO es async ni necesita
rate limiter ni retry — leer un YAML local es síncrono y idempotente. Sin
embargo, expone la misma firma `fetch(project, target_date)` para poder
integrarse en el pipeline batch igual que los HTTP connectors.

UPSERT directamente a `EVENTS` desde aquí en lugar de via raw_snapshots:
los eventos son la fuente de verdad estructurada (no payload crudo que
hay que normalizar).
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any, ClassVar

import yaml

from ..config import get_settings
from ..logging_config import get_logger
from ..models import Project, SourceSnapshot

log = get_logger(__name__)

# Pesos por categoría (ADR 0003 — Messari best practice).
CATEGORY_WEIGHTS: dict[str, float] = {
    "team": 1.5,
    "investors": 1.2,
    "foundation": 0.8,
    "treasury": 0.8,
    "ecosystem": 0.7,
    "community": 0.7,
    "public": 1.0,
    "unknown": 1.0,
}

VALID_EVENT_TYPES: frozenset[str] = frozenset(
    {"unlock", "listing", "halving", "fork", "tge", "other"}
)


def compute_magnitude_weighted(magnitude_pct: float | None, category: str | None) -> float | None:
    """magnitude_pct × category_weight. None si magnitude_pct es None.

    Si category es None o no reconocida, peso = 1.0 (fallback unknown).
    """
    if magnitude_pct is None:
        return None
    cat = (category or "unknown").lower()
    weight = CATEGORY_WEIGHTS.get(cat, 1.0)
    return magnitude_pct * weight


def _synth_external_id(
    symbol: str,
    event_type: str,
    event_date: date,
    category: str | None,
    magnitude: float | None = None,
) -> str:
    """Sintetiza un external_event_id estable para eventos manuales.

    Incluye category para permitir múltiples unlocks en la misma fecha
    (típico: team cliff + investors cliff coincidentes). Magnitude se incluye
    como tie-breaker si una categoría tiene varios eventos en mismo día
    (raro, pero observado en algunos esquemas vesting).
    """
    cat = category or "uncat"
    mag = f":m{magnitude:.4f}" if magnitude is not None else ""
    return f"manual:{symbol}:{event_type}:{event_date.isoformat()}:{cat}{mag}"


def _events_path() -> Path:
    settings = get_settings()
    real = settings.data_dir / "events.yaml"
    if real.exists():
        return real
    fallback = settings.data_dir / "events.example.yaml"
    if fallback.exists():
        log.warning("events_using_fallback", path=str(fallback))
        return fallback
    raise FileNotFoundError(f"Neither {real} nor {fallback} exists")


def load_events_file(path: Path | None = None) -> list[dict[str, Any]]:
    """Parsea events.yaml a lista de dicts normalizados.

    Valida event_type contra enum + magnitude_pct para unlocks + fecha ISO.
    """
    if path is None:
        path = _events_path()

    with path.open(encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    if not isinstance(raw, dict) or "events" not in raw:
        raise ValueError(f"{path}: expected top-level dict with 'events' key")

    items = raw["events"]
    if not isinstance(items, list):
        raise ValueError(f"{path}: 'events' must be a list")

    out: list[dict[str, Any]] = []
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            raise ValueError(f"{path}: event #{i} is not a mapping")
        symbol = item.get("symbol")
        event_type = item.get("event_type")
        event_date_raw = item.get("event_date")
        if not symbol:
            raise ValueError(f"{path}: event #{i} missing 'symbol'")
        if event_type not in VALID_EVENT_TYPES:
            raise ValueError(
                f"{path}: event #{i} ({symbol}) has invalid event_type {event_type!r}. "
                f"Valid: {sorted(VALID_EVENT_TYPES)}"
            )
        # Parse date — accept str or date object (PyYAML may auto-parse YYYY-MM-DD).
        if isinstance(event_date_raw, date):
            event_date = event_date_raw
        elif isinstance(event_date_raw, str):
            event_date = date.fromisoformat(event_date_raw)
        else:
            raise ValueError(
                f"{path}: event #{i} ({symbol}) missing or invalid event_date {event_date_raw!r}"
            )

        magnitude_pct = item.get("magnitude_pct")
        if magnitude_pct is not None and not isinstance(magnitude_pct, (int, float)):
            raise ValueError(
                f"{path}: event #{i} ({symbol}) magnitude_pct must be numeric, got {type(magnitude_pct).__name__}"
            )
        if event_type == "unlock" and magnitude_pct is None:
            log.warning(
                "event_unlock_no_magnitude",
                path=str(path),
                symbol=symbol,
                event_date=event_date.isoformat(),
            )

        category = item.get("allocation_category")
        magnitude_weighted = compute_magnitude_weighted(
            float(magnitude_pct) if magnitude_pct is not None else None, category
        )

        out.append(
            {
                "symbol": str(symbol),
                "event_type": event_type,
                "event_date": event_date,
                "magnitude_pct": float(magnitude_pct) if magnitude_pct is not None else None,
                "allocation_category": category,
                "magnitude_weighted": magnitude_weighted,
                "external_event_id": item.get("external_event_id"),
                "notes": item.get("notes"),
                "source": "manual",
            }
        )
    log.info("events_parsed", count=len(out), path=str(path))
    return out


def sync_events_to_db(conn: Any, path: Path | None = None) -> int:
    """UPSERT events to EVENTS table. Resuelve project_id por symbol.

    Idempotente: índice único parcial idx_events_manual_dedup dedupe por
    (project_id, event_type, event_date, source='manual').

    Retorna cantidad de eventos persistidos.
    """
    events = load_events_file(path)
    # Resolver symbol → project_id
    rows = conn.execute("SELECT id, symbol FROM projects").fetchall()
    sym_to_id = {r["symbol"]: r["id"] for r in rows}

    persisted = 0
    skipped: list[str] = []
    for e in events:
        proj_id = sym_to_id.get(e["symbol"])
        if proj_id is None:
            skipped.append(e["symbol"])
            continue
        # Sintetizar external_event_id incluyendo category — permite múltiples
        # unlocks en la misma fecha para el mismo proyecto (team + investors,
        # típico de schedules de TGE). Si el caller proporciona explícitamente
        # external_event_id, lo respetamos.
        external_id = e["external_event_id"] or _synth_external_id(
            e["symbol"],
            e["event_type"],
            e["event_date"],
            e.get("allocation_category"),
            magnitude=e.get("magnitude_pct"),
        )
        conn.execute(
            """
            INSERT INTO events (
                project_id, event_type, event_date, magnitude_pct,
                allocation_category, magnitude_weighted, source, external_event_id, notes
            )
            VALUES (?, ?, ?, ?, ?, ?, 'manual', ?, ?)
            ON CONFLICT(project_id, event_type, event_date, external_event_id)
                WHERE external_event_id IS NOT NULL
                DO UPDATE SET
                    magnitude_pct = excluded.magnitude_pct,
                    allocation_category = excluded.allocation_category,
                    magnitude_weighted = excluded.magnitude_weighted,
                    notes = excluded.notes
            """,
            (
                proj_id,
                e["event_type"],
                e["event_date"].isoformat(),
                e["magnitude_pct"],
                e["allocation_category"],
                e["magnitude_weighted"],
                external_id,
                e["notes"],
            ),
        )
        persisted += 1

    if skipped:
        log.warning("events_skipped_unknown_symbol", symbols=sorted(set(skipped)))
    log.info("events_synced", persisted=persisted, skipped=len(skipped))
    return persisted


class EventsManualConnector:
    """Connector con interfaz compatible para integración en pipeline batch.

    NO hace fetch HTTP — lee YAML y persiste a EVENTS directamente desde
    sync_events_to_db. El método fetch() retorna un snapshot vacío para
    cumplir el contract, pero el trabajo real ocurre en sync_events_to_db
    invocado UNA VEZ al inicio del batch.
    """

    source: ClassVar[str] = "events_manual"

    def __init__(self) -> None:
        pass

    def supports_project(self, project: Project) -> bool:
        # Aplica a todos — events.yaml es global; el filtro real está en
        # qué events declara el YAML para qué symbol.
        return True

    async def fetch(self, project: Project, *, target_date: date) -> SourceSnapshot:
        """No-op por proyecto: el verdadero trabajo se hace al inicio del batch.

        Mantiene la firma para futuras integraciones donde queramos persistir
        un raw_snapshot por proyecto con sus eventos.
        """
        assert project.id is not None
        return SourceSnapshot(
            project_id=project.id,
            source=self.source,
            snapshot_date=target_date,
            payload={"strategy": "global_sync_at_batch_start"},
        )

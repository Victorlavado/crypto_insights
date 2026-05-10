"""Helpers de persistencia: batches, raw_snapshots, derived_signals.

UPSERT con COALESCE explícito para no perder datos buenos en re-run parcial
(R-crítico #6 del plan): si una fuente devolvió null este batch pero el
último valor era válido, mantenemos el válido.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from typing import Any

from ..models import BatchStatus, ConnectorFailure, DerivedSignal, SourceSnapshot


def register_batch_started(conn: sqlite3.Connection, batch_id: str) -> None:
    """Inserta batch con status=running. Si ya existe, lo resetea (re-run idempotente)."""
    now = datetime.now(UTC).isoformat()
    conn.execute(
        """
        INSERT INTO batches (batch_id, started_at, heartbeat_at, status)
        VALUES (?, ?, ?, 'running')
        ON CONFLICT(batch_id) DO UPDATE SET
            started_at = excluded.started_at,
            heartbeat_at = excluded.heartbeat_at,
            status = 'running',
            finished_at = NULL,
            error_summary = NULL
        """,
        (batch_id, now, now),
    )


def update_heartbeat(conn: sqlite3.Connection, batch_id: str) -> None:
    """Touch heartbeat_at para que el batch siguiente detecte que sigue vivo."""
    conn.execute(
        "UPDATE batches SET heartbeat_at = ? WHERE batch_id = ?",
        (datetime.now(UTC).isoformat(), batch_id),
    )


def cleanup_orphan_batches(conn: sqlite3.Connection, *, threshold_hours: int = 2) -> int:
    """Marca como 'failed' los batches con status=running y heartbeat antiguo.

    Cubre el caso de un proceso crashed abruptly que no pudo actualizar status.
    Retorna cantidad marcada como failed.
    """
    threshold = (datetime.now(UTC) - timedelta(hours=threshold_hours)).isoformat()
    cursor = conn.execute(
        """
        UPDATE batches
        SET status = 'failed',
            finished_at = ?,
            error_summary = ?
        WHERE status = 'running'
          AND (heartbeat_at IS NULL OR heartbeat_at < ?)
        """,
        (
            datetime.now(UTC).isoformat(),
            json.dumps({"reason": "orphan_no_heartbeat", "threshold_hours": threshold_hours}),
            threshold,
        ),
    )
    return cursor.rowcount


def finalize_batch(
    conn: sqlite3.Connection,
    batch_id: str,
    *,
    status: BatchStatus,
    failures: Iterable[ConnectorFailure],
) -> None:
    """Marca batch como complete/partial/failed con error_summary estructurado."""
    error_summary: dict[str, Any] | None = None
    failures_list = list(failures)
    if failures_list:
        error_summary = {
            "sources_failed": [
                {
                    "source": f.source,
                    "project": f.project_symbol,
                    "error": f.error,
                }
                for f in failures_list
            ]
        }
    conn.execute(
        """
        UPDATE batches
        SET status = ?,
            finished_at = ?,
            error_summary = ?
        WHERE batch_id = ?
        """,
        (
            status.value,
            datetime.now(UTC).isoformat(),
            json.dumps(error_summary) if error_summary else None,
            batch_id,
        ),
    )


def upsert_raw_snapshot(
    conn: sqlite3.Connection,
    snapshot: SourceSnapshot,
    batch_id: str,
) -> None:
    """UPSERT con COALESCE: NO sobrescribir payload válido con NULL.

    Crítico #6 del plan: si la fuente devuelve null este batch pero ya teníamos
    el payload, mantenemos el viejo. excluded.payload IS NULL → preservar.
    """
    payload_json = json.dumps(snapshot.payload, default=str)
    conn.execute(
        """
        INSERT INTO raw_snapshots
            (project_id, source, batch_id, snapshot_date, payload,
             payload_schema_version, connector_version, fetched_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(project_id, source, snapshot_date) DO UPDATE SET
            payload = COALESCE(NULLIF(excluded.payload, ''), payload),
            payload_schema_version = excluded.payload_schema_version,
            connector_version = excluded.connector_version,
            fetched_at = excluded.fetched_at,
            batch_id = excluded.batch_id
        """,
        (
            snapshot.project_id,
            snapshot.source,
            batch_id,
            snapshot.snapshot_date.isoformat(),
            payload_json,
            snapshot.payload_schema_version,
            snapshot.connector_version,
            snapshot.fetched_at.isoformat(),
        ),
    )


def upsert_derived_signal(conn: sqlite3.Connection, signal: DerivedSignal, batch_id: str) -> None:
    """UPSERT en derived_signals por (project, signal, date, formula_version)."""
    conn.execute(
        """
        INSERT INTO derived_signals
            (project_id, batch_id, signal_date, signal_name, value, formula_version)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(project_id, signal_name, signal_date, formula_version) DO UPDATE SET
            value = excluded.value,
            batch_id = excluded.batch_id
        """,
        (
            signal.project_id,
            batch_id,
            signal.signal_date.isoformat(),
            signal.signal_name,
            signal.value,
            signal.formula_version,
        ),
    )

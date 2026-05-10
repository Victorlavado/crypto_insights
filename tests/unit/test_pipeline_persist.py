"""Persistence helpers tests: UPSERT COALESCE, orphan cleanup, batch lifecycle."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from crypto_insights.db import apply_migrations, connect
from crypto_insights.models import BatchStatus, ConnectorFailure, SourceSnapshot
from crypto_insights.pipeline.persist import (
    cleanup_orphan_batches,
    finalize_batch,
    register_batch_started,
    update_heartbeat,
    upsert_raw_snapshot,
)


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    db = tmp_path / "test.db"
    apply_migrations(db_path=db)
    return db


def _make_project(conn, symbol: str = "BTC") -> int:
    conn.execute("INSERT INTO projects (symbol, archetype) VALUES (?, 'l1-maduro')", (symbol,))
    return conn.execute("SELECT id FROM projects WHERE symbol=?", (symbol,)).fetchone()["id"]


def test_register_batch_started_creates_running_row(db_path: Path) -> None:
    with connect(db_path) as conn:
        register_batch_started(conn, "2026-05-10")
        row = conn.execute("SELECT * FROM batches WHERE batch_id=?", ("2026-05-10",)).fetchone()
    assert row["status"] == "running"
    assert row["started_at"] is not None
    assert row["heartbeat_at"] is not None
    assert row["finished_at"] is None


def test_register_batch_started_resets_existing_finished_batch(db_path: Path) -> None:
    """Re-correr batch terminado debe resetear su status a running (idempotente)."""
    with connect(db_path) as conn:
        register_batch_started(conn, "2026-05-10")
        finalize_batch(conn, "2026-05-10", status=BatchStatus.COMPLETE, failures=[])
        register_batch_started(conn, "2026-05-10")  # re-run
        row = conn.execute("SELECT * FROM batches WHERE batch_id=?", ("2026-05-10",)).fetchone()
    assert row["status"] == "running"
    assert row["finished_at"] is None
    assert row["error_summary"] is None


def test_cleanup_orphan_batches_marks_old_running_as_failed(db_path: Path) -> None:
    with connect(db_path) as conn:
        # Inject a batch with heartbeat 3 hours ago
        old_hb = (datetime.now(UTC) - timedelta(hours=3)).isoformat()
        conn.execute(
            "INSERT INTO batches (batch_id, started_at, heartbeat_at, status) "
            "VALUES (?, ?, ?, 'running')",
            ("2026-05-09", old_hb, old_hb),
        )
        n = cleanup_orphan_batches(conn, threshold_hours=2)
        row = conn.execute("SELECT * FROM batches WHERE batch_id=?", ("2026-05-09",)).fetchone()
    assert n == 1
    assert row["status"] == "failed"
    assert row["finished_at"] is not None
    summary = json.loads(row["error_summary"])
    assert summary["reason"] == "orphan_no_heartbeat"


def test_cleanup_orphan_batches_skips_recent_heartbeat(db_path: Path) -> None:
    with connect(db_path) as conn:
        register_batch_started(conn, "2026-05-10")
        update_heartbeat(conn, "2026-05-10")
        n = cleanup_orphan_batches(conn, threshold_hours=2)
    assert n == 0


def test_finalize_batch_records_structured_error_summary(db_path: Path) -> None:
    with connect(db_path) as conn:
        register_batch_started(conn, "2026-05-10")
        finalize_batch(
            conn,
            "2026-05-10",
            status=BatchStatus.PARTIAL,
            failures=[
                ConnectorFailure(source="binance", project_symbol="HYPE", error="not listed"),
                ConnectorFailure(source="defillama", project_symbol="GRASS", error="HTTP 500"),
            ],
        )
        row = conn.execute("SELECT * FROM batches WHERE batch_id=?", ("2026-05-10",)).fetchone()
    summary = json.loads(row["error_summary"])
    assert row["status"] == "partial"
    assert len(summary["sources_failed"]) == 2
    assert {f["source"] for f in summary["sources_failed"]} == {"binance", "defillama"}


def test_upsert_raw_snapshot_is_idempotent(db_path: Path) -> None:
    with connect(db_path) as conn:
        proj_id = _make_project(conn)
        register_batch_started(conn, "2026-05-10")
        snap = SourceSnapshot(
            project_id=proj_id,
            source="binance",
            snapshot_date=date(2026, 5, 10),
            payload={"close": 100.0, "candles": 400},
        )
        upsert_raw_snapshot(conn, snap, "2026-05-10")
        upsert_raw_snapshot(conn, snap, "2026-05-10")
        count = conn.execute("SELECT COUNT(*) FROM raw_snapshots").fetchone()[0]
    assert count == 1

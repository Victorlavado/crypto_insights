"""Layer 2 unlocks hard constraint tests."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from crypto_insights.db import apply_migrations, connect
from crypto_insights.fusion.layer2 import evaluate_layer2, upsert_layer2_state
from crypto_insights.models import (
    Archetype,
    Layer2Flag,
    Project,
    ProjectStateValue,
    ReasonCode,
)
from crypto_insights.signals.unlocks import evaluate_unlock_constraint


@pytest.fixture
def db_with_project(tmp_path: Path) -> tuple[Path, Project, str]:
    db = tmp_path / "test.db"
    apply_migrations(db_path=db)
    with connect(db) as conn:
        conn.execute("INSERT INTO projects (symbol, archetype) VALUES ('HYPE', 'infra-pmf')")
        conn.execute("INSERT INTO batches (batch_id) VALUES ('2026-05-10')")
        row = conn.execute("SELECT id FROM projects WHERE symbol='HYPE'").fetchone()
    proj = Project(id=row["id"], symbol="HYPE", archetype=Archetype.INFRA_PMF)
    return db, proj, "2026-05-10"


def _insert_unlock(
    conn, project_id: int, event_date: str, pct: float, category: str, weighted: float, ext_id: str
) -> None:
    conn.execute(
        """
        INSERT INTO events (
            project_id, event_type, event_date, magnitude_pct,
            allocation_category, magnitude_weighted, source, external_event_id
        ) VALUES (?, 'unlock', ?, ?, ?, ?, 'manual', ?)
        """,
        (project_id, event_date, pct, category, weighted, ext_id),
    )


def test_unlock_constraint_triggers_above_threshold(
    db_with_project: tuple[Path, Project, str],
) -> None:
    """ADR 0003: magnitude_weighted >= 5% en 4-8w → blocked."""
    db, proj, batch = db_with_project
    eval_date = date(2026, 5, 10)
    with connect(db) as conn:
        # team 3.5% × 1.5 = 5.25% weighted, dentro de window (28-56d)
        _insert_unlock(conn, proj.id, "2026-06-29", 3.5, "team", 5.25, "e1")
        result = evaluate_unlock_constraint(conn, proj.id, eval_date)

    assert result.triggered is True
    assert result.total_weighted == pytest.approx(5.25)
    assert result.nearest_event_date == date(2026, 6, 29)


def test_unlock_constraint_skips_below_threshold(
    db_with_project: tuple[Path, Project, str],
) -> None:
    db, proj, _ = db_with_project
    eval_date = date(2026, 5, 10)
    with connect(db) as conn:
        # foundation 1.2% × 0.8 = 0.96% weighted, dentro de window
        _insert_unlock(conn, proj.id, "2026-06-15", 1.2, "foundation", 0.96, "e1")
        result = evaluate_unlock_constraint(conn, proj.id, eval_date)

    assert result.triggered is False
    assert result.total_weighted == pytest.approx(0.96)


def test_unlock_constraint_ignores_outside_window(
    db_with_project: tuple[Path, Project, str],
) -> None:
    """Cliff dentro de 28d o pasado 56d NO debe contar."""
    db, proj, _ = db_with_project
    eval_date = date(2026, 5, 10)
    with connect(db) as conn:
        # Too soon: 10 days away
        _insert_unlock(conn, proj.id, "2026-05-20", 5.0, "team", 7.5, "e_soon")
        # Too far: 100 days away
        _insert_unlock(conn, proj.id, "2026-08-18", 10.0, "team", 15.0, "e_far")
        result = evaluate_unlock_constraint(conn, proj.id, eval_date)

    assert result.triggered is False
    assert result.total_weighted == 0.0
    assert len(result.events) == 0


def test_unlock_constraint_sums_multiple_in_window(
    db_with_project: tuple[Path, Project, str],
) -> None:
    """Cliffs múltiples (team + investors) en la misma fecha se suman."""
    db, proj, _ = db_with_project
    eval_date = date(2026, 5, 10)
    with connect(db) as conn:
        # investors 4.0 × 1.2 = 4.8 + team 2.5 × 1.5 = 3.75 → 8.55 weighted
        _insert_unlock(conn, proj.id, "2026-06-15", 4.0, "investors", 4.8, "e_inv")
        _insert_unlock(conn, proj.id, "2026-06-15", 2.5, "team", 3.75, "e_team")
        result = evaluate_unlock_constraint(conn, proj.id, eval_date)

    assert result.triggered is True
    assert result.total_weighted == pytest.approx(8.55)
    assert len(result.events) == 2


def test_layer2_blocked_on_unlock_inminente(
    db_with_project: tuple[Path, Project, str],
) -> None:
    db, proj, batch_id = db_with_project
    with connect(db) as conn:
        _insert_unlock(conn, proj.id, "2026-06-29", 3.5, "team", 5.25, "e1")
        result = evaluate_layer2(conn, proj, date(2026, 5, 10))

    assert result.blocked is True
    assert result.flag == Layer2Flag.RED
    assert result.reason_code == ReasonCode.UNLOCK_INMINENTE
    assert result.current_state == ProjectStateValue.BLOCKED
    assert "HYPE" in result.reason_human
    assert "team" in result.reason_human


def test_layer2_green_when_no_events(
    db_with_project: tuple[Path, Project, str],
) -> None:
    db, proj, _ = db_with_project
    with connect(db) as proj_conn:
        result = evaluate_layer2(proj_conn, proj, date(2026, 5, 10))

    assert result.blocked is False
    assert result.flag == Layer2Flag.GREEN
    assert result.reason_code == ReasonCode.NORMAL
    assert result.current_state is None  # Layer 1 decide


def test_layer2_amber_on_recent_listing(
    db_with_project: tuple[Path, Project, str],
) -> None:
    db, proj, _ = db_with_project
    with connect(db) as conn:
        conn.execute(
            "INSERT INTO events (project_id, event_type, event_date, source) "
            "VALUES (?, 'listing', '2026-03-15', 'manual')",
            (proj.id,),
        )
        result = evaluate_layer2(conn, proj, date(2026, 5, 10))

    assert result.blocked is False
    assert result.flag == Layer2Flag.AMBER
    assert result.reason_code == ReasonCode.LISTING_RECENT


def test_upsert_layer2_state_increments_hysteresis_counter(
    db_with_project: tuple[Path, Project, str],
) -> None:
    """ADR 0006: batches_in_state se incrementa en consecutivos con el mismo state."""
    db, proj, batch_id = db_with_project
    with connect(db) as conn:
        _insert_unlock(conn, proj.id, "2026-06-29", 3.5, "team", 5.25, "e1")
        r1 = evaluate_layer2(conn, proj, date(2026, 5, 10))
        upsert_layer2_state(conn, r1, batch_id)
        # Second batch — same state
        conn.execute("INSERT INTO batches (batch_id) VALUES ('2026-05-11')")
        r2 = evaluate_layer2(conn, proj, date(2026, 5, 11))
        upsert_layer2_state(conn, r2, "2026-05-11")
        row = conn.execute(
            "SELECT batches_in_state, current_state FROM project_state WHERE project_id=?",
            (proj.id,),
        ).fetchone()

    assert row["current_state"] == "blocked"
    assert row["batches_in_state"] == 2

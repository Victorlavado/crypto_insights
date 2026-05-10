"""Manual events YAML loader + EVENTS table populator."""

from __future__ import annotations

import textwrap
from datetime import date
from pathlib import Path

import pytest

from crypto_insights.connectors.events_manual import (
    CATEGORY_WEIGHTS,
    compute_magnitude_weighted,
    load_events_file,
    sync_events_to_db,
)
from crypto_insights.db import apply_migrations, connect


def test_compute_magnitude_weighted_team_uses_1_5x() -> None:
    assert compute_magnitude_weighted(4.0, "team") == 6.0
    assert compute_magnitude_weighted(4.0, "investors") == 4.8
    assert compute_magnitude_weighted(4.0, "foundation") == pytest.approx(3.2)
    assert compute_magnitude_weighted(4.0, "ecosystem") == pytest.approx(2.8)
    assert compute_magnitude_weighted(4.0, None) == 4.0  # unknown fallback 1.0
    assert compute_magnitude_weighted(None, "team") is None


def test_category_weights_align_with_adr_0003() -> None:
    """ADR 0003: team 1.5, investors 1.2, foundation/treasury 0.8, ecosystem 0.7."""
    assert CATEGORY_WEIGHTS["team"] == 1.5
    assert CATEGORY_WEIGHTS["investors"] == 1.2
    assert CATEGORY_WEIGHTS["foundation"] == 0.8
    assert CATEGORY_WEIGHTS["treasury"] == 0.8
    assert CATEGORY_WEIGHTS["ecosystem"] == 0.7
    assert CATEGORY_WEIGHTS["community"] == 0.7


def test_load_events_file_validates_event_type(tmp_path: Path) -> None:
    bad = tmp_path / "events.yaml"
    bad.write_text(
        textwrap.dedent(
            """
            events:
              - symbol: HYPE
                event_type: bogus
                event_date: 2026-06-15
            """
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="invalid event_type"):
        load_events_file(bad)


def test_load_events_file_parses_unlock_with_category(tmp_path: Path) -> None:
    yaml_path = tmp_path / "events.yaml"
    yaml_path.write_text(
        textwrap.dedent(
            """
            events:
              - symbol: STRK
                event_type: unlock
                event_date: 2026-06-15
                magnitude_pct: 4.0
                allocation_category: investors
            """
        ),
        encoding="utf-8",
    )
    events = load_events_file(yaml_path)
    assert len(events) == 1
    e = events[0]
    assert e["symbol"] == "STRK"
    assert e["event_date"] == date(2026, 6, 15)
    assert e["magnitude_pct"] == 4.0
    assert e["allocation_category"] == "investors"
    assert e["magnitude_weighted"] == pytest.approx(4.8)


def test_sync_events_preserves_multiple_unlocks_same_date_diff_category(tmp_path: Path) -> None:
    """STRK típicamente tiene team + investors unlocks en el mismo dia — ambos deben persistirse."""
    yaml_path = tmp_path / "events.yaml"
    yaml_path.write_text(
        textwrap.dedent(
            """
            events:
              - symbol: STRK
                event_type: unlock
                event_date: 2026-06-15
                magnitude_pct: 4.0
                allocation_category: investors
              - symbol: STRK
                event_type: unlock
                event_date: 2026-06-15
                magnitude_pct: 2.5
                allocation_category: team
            """
        ),
        encoding="utf-8",
    )
    db = tmp_path / "test.db"
    apply_migrations(db_path=db)
    with connect(db) as conn:
        conn.execute("INSERT INTO projects (symbol, archetype) VALUES ('STRK', 'post-tge')")
        n = sync_events_to_db(conn, path=yaml_path)
        # Idempotent re-run
        n2 = sync_events_to_db(conn, path=yaml_path)
        rows = conn.execute(
            "SELECT allocation_category, magnitude_pct, magnitude_weighted "
            "FROM events ORDER BY allocation_category"
        ).fetchall()

    assert n == 2 and n2 == 2
    assert len(rows) == 2  # both rows preserved despite same date
    cats = {r["allocation_category"] for r in rows}
    assert cats == {"investors", "team"}


def test_sync_events_skips_unknown_symbols(tmp_path: Path) -> None:
    yaml_path = tmp_path / "events.yaml"
    yaml_path.write_text(
        textwrap.dedent(
            """
            events:
              - symbol: NONEXISTENT
                event_type: unlock
                event_date: 2026-06-15
                magnitude_pct: 4.0
                allocation_category: team
            """
        ),
        encoding="utf-8",
    )
    db = tmp_path / "test.db"
    apply_migrations(db_path=db)
    with connect(db) as conn:
        n = sync_events_to_db(conn, path=yaml_path)
        rows = conn.execute("SELECT COUNT(*) FROM events").fetchone()
    assert n == 0
    assert rows[0] == 0

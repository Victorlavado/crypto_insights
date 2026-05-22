"""API que el dashboard (y el CLI) consume.

Centraliza todas las queries para que streamlit_app.py NO tenga SQL inline.
Esto cumple el agent-native contract: cualquier widget mostrado al usuario
es equivalente a un endpoint CLI.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import date
from typing import Any


def get_all_states(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Lista todos los proyectos con su state actual + Layer 1 scores.

    Ordenado: blocked primero, luego por composite_score desc.
    """
    rows = conn.execute(
        """
        SELECT p.id, p.symbol, p.archetype, p.chain, p.coingecko_id,
               ps.current_state, ps.composite_score, ps.reason_code,
               ps.reason_data, ps.reason_human, ps.layer2_flag,
               ps.layer1_scores, ps.has_gaps, ps.batches_in_state,
               ps.batch_id, ps.updated_at
        FROM projects p
        LEFT JOIN project_state ps ON ps.project_id = p.id
        ORDER BY
            CASE COALESCE(ps.current_state, 'unknown')
                WHEN 'blocked' THEN 0
                WHEN 'aceleracion' THEN 1
                WHEN 'acumulacion' THEN 2
                WHEN 'distribucion' THEN 3
                WHEN 'colapso' THEN 4
                WHEN 'reset' THEN 5
                WHEN 'degraded' THEN 6
                ELSE 7
            END,
            ps.composite_score DESC NULLS LAST,
            p.symbol
        """
    ).fetchall()
    out: list[dict[str, Any]] = []
    for r in rows:
        out.append(
            {
                "id": r["id"],
                "symbol": r["symbol"],
                "archetype": r["archetype"],
                "chain": r["chain"],
                "coingecko_id": r["coingecko_id"],
                "current_state": r["current_state"] or "unknown",
                "composite_score": r["composite_score"],
                "reason_code": r["reason_code"] or "NORMAL",
                "reason_data": json.loads(r["reason_data"]) if r["reason_data"] else {},
                "reason_human": r["reason_human"] or "",
                "layer2_flag": r["layer2_flag"] or "green",
                "layer1_scores": json.loads(r["layer1_scores"]) if r["layer1_scores"] else {},
                "has_gaps": bool(r["has_gaps"]) if r["has_gaps"] is not None else False,
                "batches_in_state": r["batches_in_state"],
                "batch_id": r["batch_id"],
                "updated_at": r["updated_at"],
            }
        )
    return out


def get_project_detail(conn: sqlite3.Connection, symbol: str) -> dict[str, Any] | None:
    """Detalle de 1 proyecto: estado + últimas raw_snapshots + eventos próximos."""
    state_row = conn.execute(
        """
        SELECT p.id, p.symbol, p.archetype, p.chain, p.coingecko_id, p.notes,
               ps.current_state, ps.composite_score, ps.reason_code,
               ps.reason_data, ps.reason_human, ps.layer2_flag,
               ps.layer1_scores, ps.has_gaps, ps.batches_in_state,
               ps.batch_id, ps.updated_at
        FROM projects p
        LEFT JOIN project_state ps ON ps.project_id = p.id
        WHERE p.symbol = ?
        """,
        (symbol,),
    ).fetchone()
    if not state_row:
        return None

    project_id = state_row["id"]

    raw_rows = conn.execute(
        """
        SELECT source, snapshot_date, fetched_at, payload_schema_version
        FROM raw_snapshots
        WHERE project_id = ?
        ORDER BY snapshot_date DESC, source
        LIMIT 20
        """,
        (project_id,),
    ).fetchall()
    raw_snapshots = [dict(r) for r in raw_rows]

    event_rows = conn.execute(
        """
        SELECT event_type, event_date, magnitude_pct, allocation_category,
               magnitude_weighted, notes
        FROM events
        WHERE project_id = ?
          AND event_date >= date('now', '-30 days')
        ORDER BY event_date
        """,
        (project_id,),
    ).fetchall()
    events = [dict(r) for r in event_rows]

    return {
        "id": project_id,
        "symbol": state_row["symbol"],
        "archetype": state_row["archetype"],
        "chain": state_row["chain"],
        "coingecko_id": state_row["coingecko_id"],
        "notes": state_row["notes"],
        "current_state": state_row["current_state"] or "unknown",
        "composite_score": state_row["composite_score"],
        "reason_code": state_row["reason_code"] or "NORMAL",
        "reason_data": json.loads(state_row["reason_data"]) if state_row["reason_data"] else {},
        "reason_human": state_row["reason_human"] or "",
        "layer2_flag": state_row["layer2_flag"] or "green",
        "layer1_scores": json.loads(state_row["layer1_scores"])
        if state_row["layer1_scores"]
        else {},
        "has_gaps": bool(state_row["has_gaps"]) if state_row["has_gaps"] is not None else False,
        "batches_in_state": state_row["batches_in_state"],
        "batch_id": state_row["batch_id"],
        "updated_at": state_row["updated_at"],
        "raw_snapshots": raw_snapshots,
        "upcoming_events": events,
    }


def get_derived_signals_history(
    conn: sqlite3.Connection, project_id: int, signal_name: str, days: int = 30
) -> list[dict[str, Any]]:
    """Histórico de un signal para sparklines (Fase 4)."""
    rows = conn.execute(
        """
        SELECT signal_date, value, formula_version
        FROM derived_signals
        WHERE project_id = ? AND signal_name = ?
          AND signal_date >= date('now', '-' || ? || ' days')
        ORDER BY signal_date
        """,
        (project_id, signal_name, days),
    ).fetchall()
    return [dict(r) for r in rows]


def get_batch_status(
    conn: sqlite3.Connection, batch_id: str | None = None
) -> dict[str, Any] | None:
    """Estado del último batch o uno específico."""
    if batch_id:
        row = conn.execute("SELECT * FROM batches WHERE batch_id = ?", (batch_id,)).fetchone()
    else:
        row = conn.execute("SELECT * FROM batches ORDER BY started_at DESC LIMIT 1").fetchone()
    if not row:
        return None
    return {
        "batch_id": row["batch_id"],
        "status": row["status"],
        "started_at": row["started_at"],
        "heartbeat_at": row["heartbeat_at"],
        "finished_at": row["finished_at"],
        "error_summary": json.loads(row["error_summary"]) if row["error_summary"] else None,
    }


def create_feedback_entry(
    project_root: str | Any,
    symbols: list[str],
    notes: str,
    signals_referenced: list[str] | None = None,
) -> str:
    """Crea archivo en docs/feedback/YYYY-MM-DD-N.md.

    Retorna path del archivo creado.
    """
    from datetime import datetime
    from pathlib import Path

    today = date.today().isoformat()
    feedback_dir = Path(project_root) / "docs" / "feedback"
    feedback_dir.mkdir(parents=True, exist_ok=True)

    # Encontrar siguiente N para hoy
    existing = list(feedback_dir.glob(f"{today}-*.md"))
    next_n = len(existing) + 1
    path = feedback_dir / f"{today}-{next_n}.md"

    content = f"""---
date: {today}
symbols: {symbols}
signals_referenced: {signals_referenced or []}
created_at: {datetime.now().isoformat()}
---

# Feedback {today}-{next_n}

**Proyectos**: {", ".join(symbols)}

**Signals**: {", ".join(signals_referenced or [])}

## Observación

{notes}

## Acción / Próximos pasos

(rellenar)
"""
    path.write_text(content, encoding="utf-8")
    return str(path)

"""Unlocks hard constraint — ADR 0003.

Layer 2 evalúa para cada proyecto si la suma de cliffs + vesting linear en
las próximas 4-8 semanas, ponderada por categoría (Messari best practice),
supera el threshold del 5% del circulating supply → estado `blocked`.

reason_code = UNLOCK_INMINENTE
reason_data = {
    "total_pct": float,                # suma de magnitude_pct sin ponderar
    "total_weighted": float,           # suma de magnitude_weighted (esto es el que decide)
    "events": [{event_date, magnitude_pct, magnitude_weighted, category}, ...],
    "window_days_from": 28,
    "window_days_to": 56,
    "nearest_event_date": "YYYY-MM-DD",
    "days_until_nearest": int,
}
reason_human = "blocked: HYPE — unlock 16.8% ponderado próximas 6w (2026-06-29, team)"
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

# Ventana de hard constraint: 4 a 8 semanas (ADR 0003).
DEFAULT_WINDOW_FROM_DAYS = 28
DEFAULT_WINDOW_TO_DAYS = 56

# Threshold ponderado: 5% del circulating supply.
DEFAULT_THRESHOLD_PCT = 5.0


@dataclass(frozen=True, slots=True)
class UnlockConstraintResult:
    """Resultado de evaluar la hard constraint para un proyecto."""

    triggered: bool  # True → estado blocked
    total_pct: float  # suma magnitude_pct sin ponderar
    total_weighted: float  # suma magnitude_weighted (la que decide)
    events: list[dict[str, Any]]  # lista de eventos en ventana
    nearest_event_date: date | None
    days_until_nearest: int | None
    window_from: date
    window_to: date

    def to_reason_data(self) -> dict[str, Any]:
        """Estructurado para PROJECT_STATE.reason_data (JSON)."""
        return {
            "total_pct": round(self.total_pct, 2),
            "total_weighted": round(self.total_weighted, 2),
            "events": [
                {
                    "event_date": (
                        e["event_date"].isoformat()
                        if isinstance(e["event_date"], date)
                        else e["event_date"]
                    ),
                    "magnitude_pct": e["magnitude_pct"],
                    "magnitude_weighted": e["magnitude_weighted"],
                    "category": e["allocation_category"],
                }
                for e in self.events
            ],
            "window_days_from": (self.window_from - self.events[0]["evaluation_date"]).days
            if self.events
            else DEFAULT_WINDOW_FROM_DAYS,
            "window_days_to": DEFAULT_WINDOW_TO_DAYS,
            "nearest_event_date": (
                self.nearest_event_date.isoformat() if self.nearest_event_date else None
            ),
            "days_until_nearest": self.days_until_nearest,
            "threshold_pct": DEFAULT_THRESHOLD_PCT,
        }

    def to_reason_human(self, symbol: str) -> str:
        """Frase para PROJECT_STATE.reason_human."""
        if not self.triggered:
            return ""
        nearest = self.nearest_event_date.isoformat() if self.nearest_event_date else "?"
        # Buscar la categoría dominante (la del evento de mayor magnitude_weighted)
        dominant = max(self.events, key=lambda e: e["magnitude_weighted"] or 0)
        cat = dominant.get("allocation_category") or "?"
        return (
            f"blocked: {symbol} — unlock {self.total_weighted:.1f}% ponderado "
            f"próximas {((self.window_to - self.window_from).days // 7) + 4}w "
            f"(nearest {nearest}, dominante {cat})"
        )


def fetch_events_in_window(
    conn: sqlite3.Connection,
    project_id: int,
    evaluation_date: date,
    *,
    window_from_days: int = DEFAULT_WINDOW_FROM_DAYS,
    window_to_days: int = DEFAULT_WINDOW_TO_DAYS,
) -> list[dict[str, Any]]:
    """Trae eventos type=unlock en ventana [evaluation_date + window_from, +window_to]."""
    window_from = evaluation_date + timedelta(days=window_from_days)
    window_to = evaluation_date + timedelta(days=window_to_days)
    rows = conn.execute(
        """
        SELECT event_date, magnitude_pct, allocation_category, magnitude_weighted, notes
        FROM events
        WHERE project_id = ?
          AND event_type = 'unlock'
          AND event_date >= ?
          AND event_date <= ?
        ORDER BY event_date
        """,
        (project_id, window_from.isoformat(), window_to.isoformat()),
    ).fetchall()
    out: list[dict[str, Any]] = []
    for r in rows:
        out.append(
            {
                "event_date": date.fromisoformat(r["event_date"]),
                "magnitude_pct": r["magnitude_pct"],
                "magnitude_weighted": r["magnitude_weighted"],
                "allocation_category": r["allocation_category"],
                "evaluation_date": evaluation_date,
            }
        )
    return out


def evaluate_unlock_constraint(
    conn: sqlite3.Connection,
    project_id: int,
    evaluation_date: date,
    *,
    window_from_days: int = DEFAULT_WINDOW_FROM_DAYS,
    window_to_days: int = DEFAULT_WINDOW_TO_DAYS,
    threshold_pct: float = DEFAULT_THRESHOLD_PCT,
) -> UnlockConstraintResult:
    """Evalúa la hard constraint para un proyecto en `evaluation_date`.

    Suma `magnitude_weighted` (cliffs + vesting linear acumulado) en ventana.
    Si total ≥ threshold → triggered=True → estado blocked.

    Para proyectos sin eventos en ventana, retorna triggered=False con totales 0.
    """
    events = fetch_events_in_window(
        conn,
        project_id,
        evaluation_date,
        window_from_days=window_from_days,
        window_to_days=window_to_days,
    )
    total_pct = sum(e["magnitude_pct"] or 0.0 for e in events)
    total_weighted = sum(e["magnitude_weighted"] or 0.0 for e in events)
    nearest_event_date = events[0]["event_date"] if events else None
    days_until_nearest = (nearest_event_date - evaluation_date).days if nearest_event_date else None
    triggered = total_weighted >= threshold_pct

    return UnlockConstraintResult(
        triggered=triggered,
        total_pct=total_pct,
        total_weighted=total_weighted,
        events=events,
        nearest_event_date=nearest_event_date,
        days_until_nearest=days_until_nearest,
        window_from=evaluation_date + timedelta(days=window_from_days),
        window_to=evaluation_date + timedelta(days=window_to_days),
    )

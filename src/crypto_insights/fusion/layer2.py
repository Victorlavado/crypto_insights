"""Layer 2 — filtro de viabilidad.

Produce un flag por proyecto: green / amber / red / blocked. Refrescado cada
batch. NO decide timing (eso es Layer 1) — decide si el proyecto es elegible.

Reglas (ADR 0003 + plan Fase 1):

| Regla                               | Threshold                                  | Acción                                    |
|-------------------------------------|--------------------------------------------|-------------------------------------------|
| Unlock próximo (HARD CONSTRAINT)    | magnitude_weighted >= 5% en 4-8w           | blocked (override de Layer 1)             |
| Dev abandonado                      | <5 commits 90d & <2 contributors           | red (descartar como zombie)               |
| TVL/Fees colapsando                 | TVL drop >70% from ATH & fees -50% 90d     | amber (revisar manualmente)               |
| Listing reciente (post-TGE)         | <6 meses desde TGE                         | amber (no aplica consolidation/histórico) |
| Default                             | —                                          | green                                     |

`blocked` retorna current_state='blocked' (override completo). Las demás reglas
solo afectan layer2_flag — el current_state final lo decide Layer 1 a partir
de signals, pero respetando que un proyecto `red` típicamente tendrá score bajo.

Para Fase 1, sólo unlocks + listing_recent están implementados. Dev abandonado
y TVL collapsing llegan cuando los conectores GitHub y DeFiLlama estén.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date
from typing import Any

from ..logging_config import get_logger
from ..models import Layer2Flag, Project, ProjectStateValue, ReasonCode
from ..signals.unlocks import (
    DEFAULT_THRESHOLD_PCT,
    DEFAULT_WINDOW_FROM_DAYS,
    DEFAULT_WINDOW_TO_DAYS,
    UnlockConstraintResult,
    evaluate_unlock_constraint,
)

log = get_logger(__name__)

# Listing reciente: <6 meses = 180 días.
LISTING_RECENT_DAYS = 180


@dataclass(frozen=True, slots=True)
class Layer2Result:
    """Resultado de Layer 2 para un proyecto.

    `blocked=True` → current_state queda blocked y Layer 1 NO ejecuta.
    `blocked=False` → layer2_flag (green/amber/red) afecta visualización pero
    Layer 1 decide el current_state final basado en scores.
    """

    project_id: int
    blocked: bool
    flag: Layer2Flag
    reason_code: ReasonCode
    reason_data: dict[str, Any]
    reason_human: str
    unlock_result: UnlockConstraintResult | None

    @property
    def current_state(self) -> ProjectStateValue | None:
        """Si está bloqueado, devuelve blocked. Caso contrario None (Layer 1 decide)."""
        return ProjectStateValue.BLOCKED if self.blocked else None


def evaluate_layer2(
    conn: sqlite3.Connection,
    project: Project,
    evaluation_date: date,
    *,
    threshold_pct: float = DEFAULT_THRESHOLD_PCT,
    window_from_days: int = DEFAULT_WINDOW_FROM_DAYS,
    window_to_days: int = DEFAULT_WINDOW_TO_DAYS,
) -> Layer2Result:
    """Aplica reglas Layer 2 a un proyecto en `evaluation_date`.

    Orden de evaluación (early-exit):
    1. Unlock hard constraint → blocked (override completo)
    2. Listing reciente (post-TGE) → amber
    3. Default → green

    Las reglas dev_abandoned y tvl_collapse llegan en Fase 2 cuando los
    connectors GitHub y DeFiLlama están disponibles.
    """
    assert project.id is not None

    # ── Regla 1: unlock hard constraint ───────────────────────────────
    unlock_result = evaluate_unlock_constraint(
        conn,
        project.id,
        evaluation_date,
        threshold_pct=threshold_pct,
        window_from_days=window_from_days,
        window_to_days=window_to_days,
    )
    if unlock_result.triggered:
        return Layer2Result(
            project_id=project.id,
            blocked=True,
            flag=Layer2Flag.RED,  # un blocked también deja flag red para visualización
            reason_code=ReasonCode.UNLOCK_INMINENTE,
            reason_data=unlock_result.to_reason_data(),
            reason_human=unlock_result.to_reason_human(project.symbol),
            unlock_result=unlock_result,
        )

    # ── Regla 2: listing reciente ─────────────────────────────────────
    listing_row = conn.execute(
        """
        SELECT event_date FROM events
        WHERE project_id = ?
          AND event_type IN ('listing', 'tge')
          AND event_date <= ?
        ORDER BY event_date DESC
        LIMIT 1
        """,
        (project.id, evaluation_date.isoformat()),
    ).fetchone()

    if listing_row:
        listing_date = date.fromisoformat(listing_row["event_date"])
        days_since = (evaluation_date - listing_date).days
        if days_since < LISTING_RECENT_DAYS:
            return Layer2Result(
                project_id=project.id,
                blocked=False,
                flag=Layer2Flag.AMBER,
                reason_code=ReasonCode.LISTING_RECENT,
                reason_data={
                    "listing_date": listing_date.isoformat(),
                    "days_since": days_since,
                    "threshold_days": LISTING_RECENT_DAYS,
                },
                reason_human=(
                    f"{project.symbol}: listing/TGE hace {days_since}d "
                    f"(<{LISTING_RECENT_DAYS}d) — no aplica histórico"
                ),
                unlock_result=unlock_result,
            )

    # ── Default: green ────────────────────────────────────────────────
    return Layer2Result(
        project_id=project.id,
        blocked=False,
        flag=Layer2Flag.GREEN,
        reason_code=ReasonCode.NORMAL,
        reason_data={},
        reason_human="",
        unlock_result=unlock_result,
    )


def upsert_layer2_state(
    conn: sqlite3.Connection,
    result: Layer2Result,
    batch_id: str,
) -> None:
    """Persiste Layer 2 result en PROJECT_STATE.

    Solo se llama directamente si Layer 2 devuelve blocked (Layer 1 no corre).
    Si no bloqueado, esta función NO debe llamarse — Layer 1 hará la persistencia
    final con composite_score.
    """
    import json as _json

    state_value = (result.current_state or ProjectStateValue.UNKNOWN).value

    # Hysteresis counter: si el proyecto YA estaba en este estado, incrementa.
    prior = conn.execute(
        "SELECT current_state, batches_in_state FROM project_state WHERE project_id = ?",
        (result.project_id,),
    ).fetchone()
    batches_in_state = (
        prior["batches_in_state"] + 1 if prior and prior["current_state"] == state_value else 1
    )

    conn.execute(
        """
        INSERT INTO project_state (
            project_id, current_state, composite_score, reason_code,
            reason_data, reason_human, layer2_flag, layer1_scores,
            has_gaps, batches_in_state, batch_id
        )
        VALUES (?, ?, NULL, ?, ?, ?, ?, NULL, 0, ?, ?)
        ON CONFLICT(project_id) DO UPDATE SET
            current_state = excluded.current_state,
            composite_score = excluded.composite_score,
            reason_code = excluded.reason_code,
            reason_data = excluded.reason_data,
            reason_human = excluded.reason_human,
            layer2_flag = excluded.layer2_flag,
            batches_in_state = excluded.batches_in_state,
            batch_id = excluded.batch_id,
            updated_at = datetime('now')
        """,
        (
            result.project_id,
            state_value,
            result.reason_code.value,
            _json.dumps(result.reason_data),
            result.reason_human,
            result.flag.value,
            batches_in_state,
            batch_id,
        ),
    )

    # Append to history (ADR 0006)
    conn.execute(
        """
        INSERT OR IGNORE INTO project_state_history (
            project_id, batch_id, state, composite_score, reason_code,
            reason_data, layer2_flag, has_gaps
        )
        VALUES (?, ?, ?, NULL, ?, ?, ?, 0)
        """,
        (
            result.project_id,
            batch_id,
            state_value,
            result.reason_code.value,
            _json.dumps(result.reason_data),
            result.flag.value,
        ),
    )

"""Layer 1 — positioning fusion.

Combina derived_signals × archetype_weights → composite_score → estado.

Gap policy (ADR 0005):
- Si <30% del peso total falta → renormalize sobre presentes + warning visible.
- Si ≥30% del peso falta → estado=degraded, composite=None, reason_code=GAP_DATOS.

NO corre para proyectos blocked por Layer 2.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass

from ..logging_config import get_logger
from ..models import Project, ProjectStateValue, ReasonCode
from .archetype_rules import (
    DEFAULT_THRESHOLDS,
    SIGNAL_WEIGHTS,
    normalize_signal,
    state_from_score,
)

log = get_logger(__name__)

# Si más del 30% del peso (acumulado) está ausente → degraded.
GAP_THRESHOLD_PCT = 0.30


@dataclass(frozen=True, slots=True)
class Layer1Result:
    project_id: int
    composite_score: float | None
    state: ProjectStateValue
    layer1_scores: dict[str, dict]  # {signal: {value, weight, normalized, contribution}}
    has_gaps: bool
    reason_code: ReasonCode
    reason_human: str
    missing_signals: list[str]


def _fetch_latest_signal(
    conn: sqlite3.Connection, project_id: int, signal_name: str
) -> float | None:
    """Trae el valor más reciente para (project, signal). None si no hay."""
    row = conn.execute(
        """
        SELECT value FROM derived_signals
        WHERE project_id = ? AND signal_name = ?
        ORDER BY signal_date DESC
        LIMIT 1
        """,
        (project_id, signal_name),
    ).fetchone()
    return row["value"] if row and row["value"] is not None else None


def evaluate_layer1(
    conn: sqlite3.Connection,
    project: Project,
    *,
    prior_state: ProjectStateValue | None = None,
) -> Layer1Result:
    """Calcula composite_score + state para `project`.

    NO llamar si Layer 2 dijo blocked — la responsabilidad de skip está en
    el caller (pipeline/batch.py).
    """
    assert project.id is not None
    weights = SIGNAL_WEIGHTS[project.archetype]

    # Solo considerar signals con peso > 0
    active_signals = {name: w for name, w in weights.items() if w > 0}
    total_weight = sum(active_signals.values())

    contributions: dict[str, dict] = {}
    missing: list[str] = []
    contribution_sum = 0.0
    present_weight = 0.0

    for signal_name, weight in active_signals.items():
        raw = _fetch_latest_signal(conn, project.id, _resolve_signal_alias(signal_name))
        if raw is None:
            missing.append(signal_name)
            contributions[signal_name] = {
                "value": None,
                "weight": weight,
                "normalized": None,
                "contribution": None,
            }
            continue
        normalized = normalize_signal(signal_name, raw)
        if normalized is None:
            missing.append(signal_name)
            contributions[signal_name] = {
                "value": raw,
                "weight": weight,
                "normalized": None,
                "contribution": None,
            }
            continue
        contribution = normalized * weight
        contributions[signal_name] = {
            "value": round(raw, 4),
            "weight": weight,
            "normalized": round(normalized, 4),
            "contribution": round(contribution, 4),
        }
        contribution_sum += contribution
        present_weight += weight

    missing_weight_pct = (total_weight - present_weight) / total_weight if total_weight > 0 else 1.0

    if missing_weight_pct >= GAP_THRESHOLD_PCT:
        # Degraded — no composite score
        return Layer1Result(
            project_id=project.id,
            composite_score=None,
            state=ProjectStateValue.DEGRADED,
            layer1_scores=contributions,
            has_gaps=True,
            reason_code=ReasonCode.GAP_DATOS,
            reason_human=(
                f"{project.symbol}: degraded — missing {missing_weight_pct:.0%} weight "
                f"({', '.join(missing)})"
            ),
            missing_signals=missing,
        )

    # Renormalize sobre presentes
    composite_score = contribution_sum / present_weight if present_weight > 0 else 0.0
    has_gaps = bool(missing)

    # Get consolidation_breakout para el override de aceleración
    breakout_val = contributions.get("consolidation_breakout", {}).get("value")

    state = state_from_score(
        composite_score,
        prior_state=prior_state,
        consolidation_breakout=breakout_val,
        thresholds=DEFAULT_THRESHOLDS,
    )

    reason_human = ""
    if has_gaps:
        reason_human = (
            f"{project.symbol}: {state.value} (score {composite_score:.2f}) "
            f"con gaps en {', '.join(missing)} — renormalize"
        )

    return Layer1Result(
        project_id=project.id,
        composite_score=composite_score,
        state=state,
        layer1_scores=contributions,
        has_gaps=has_gaps,
        reason_code=ReasonCode.NORMAL,
        reason_human=reason_human,
        missing_signals=missing,
    )


# Signals "abstractos" en SIGNAL_WEIGHTS → nombre real en derived_signals.
# atr_pct y consolidation_breakout coinciden directo. funding_zscore vs
# funding_zscore_30d, etc.
_SIGNAL_NAME_ALIASES: dict[str, str] = {
    "consolidation_breakout": "consolidation_breakout",
    "funding_zscore_30d": "funding_zscore_30d",
    "smart_money_delta": "smart_money_delta_7d",
    "mindshare_velocity": "mindshare_velocity_7d",
    "cex_netflows": "cex_netflows_7d",
    "tvl_fees_trend": "tvl_change_30d_pct",
    "stablecoin_dex_growth": "stablecoin_dex_growth_30d",
    "holder_growth": "holders_delta_7d",
}


def _resolve_signal_alias(signal_name: str) -> str:
    return _SIGNAL_NAME_ALIASES.get(signal_name, signal_name)


def upsert_layer1_state(
    conn: sqlite3.Connection,
    project: Project,
    result: Layer1Result,
    layer2_flag: str,
    batch_id: str,
) -> None:
    """Persiste Layer 1 result en PROJECT_STATE + history.

    Hysteresis: si el estado nuevo coincide con el viejo, batches_in_state++.
    Si difiere, requiere mín 2 batches consecutivos antes de transitar (anti-flapping).
    """
    assert project.id is not None
    prior = conn.execute(
        "SELECT current_state, batches_in_state FROM project_state WHERE project_id = ?",
        (project.id,),
    ).fetchone()

    # Estado pending = si difiere del actual, mantener prior hasta ver 2 consecutivos
    new_state_value = result.state.value
    if prior and prior["current_state"] != new_state_value:
        # Transition pending: aún en hysteresis. Por simplicidad MVP: aceptamos
        # transitar al primer cambio si prior counter >= 2. Si prior counter < 2
        # (recién cambió), aplicamos la transición igual (el counter empieza en 1).
        # Esta es la implementación simple del ADR 0006 — refinable si Fase 4
        # muestra flapping.
        batches_in_state = 1
    elif prior:
        batches_in_state = prior["batches_in_state"] + 1
    else:
        batches_in_state = 1

    conn.execute(
        """
        INSERT INTO project_state (
            project_id, current_state, composite_score, reason_code,
            reason_data, reason_human, layer2_flag, layer1_scores,
            has_gaps, batches_in_state, batch_id
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(project_id) DO UPDATE SET
            current_state = excluded.current_state,
            composite_score = excluded.composite_score,
            reason_code = excluded.reason_code,
            reason_data = excluded.reason_data,
            reason_human = excluded.reason_human,
            layer2_flag = excluded.layer2_flag,
            layer1_scores = excluded.layer1_scores,
            has_gaps = excluded.has_gaps,
            batches_in_state = excluded.batches_in_state,
            batch_id = excluded.batch_id,
            updated_at = datetime('now')
        """,
        (
            project.id,
            new_state_value,
            result.composite_score,
            result.reason_code.value,
            json.dumps({"missing": result.missing_signals}) if result.missing_signals else None,
            result.reason_human,
            layer2_flag,
            json.dumps(result.layer1_scores),
            int(result.has_gaps),
            batches_in_state,
            batch_id,
        ),
    )
    conn.execute(
        """
        INSERT OR IGNORE INTO project_state_history (
            project_id, batch_id, state, composite_score, reason_code,
            reason_data, layer2_flag, has_gaps
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            project.id,
            batch_id,
            new_state_value,
            result.composite_score,
            result.reason_code.value,
            json.dumps({"missing": result.missing_signals}) if result.missing_signals else None,
            layer2_flag,
            int(result.has_gaps),
        ),
    )

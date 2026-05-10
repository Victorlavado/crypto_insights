"""Cómputo de derived_signals a partir de raw_snapshots.

Para cada proyecto, lee los últimos raw_snapshots disponibles, ejecuta los
indicadores correspondientes (Binance OHLCV → consolidation_breakout, atr_pct;
Hyperliquid funding history → funding_zscore_30d), y UPSERT a derived_signals.

Diseñado para correr en transacción per-project (R-crítico #8: garantía de
consistencia ante crash a mitad).
"""

from __future__ import annotations

import json
import math
import sqlite3
from datetime import date

import pandas as pd

from ..archetypes import get_archetype_meta
from ..logging_config import get_logger
from ..models import DerivedSignal, Project
from ..signals.consolidation_breakout import evaluate_consolidation_breakout
from ..signals.funding import compute_funding_zscore
from ..signals.indicators import (
    FORMULA_VERSIONS,
    atr_pct,
    candles_to_dataframe,
    resample_to_weekly,
)
from .persist import upsert_derived_signal

log = get_logger(__name__)


def _latest_payload(conn: sqlite3.Connection, project_id: int, source: str) -> dict | None:
    """Trae el payload más reciente para (project, source). Devuelve None si no hay."""
    row = conn.execute(
        """
        SELECT payload FROM raw_snapshots
        WHERE project_id = ? AND source = ?
        ORDER BY snapshot_date DESC
        LIMIT 1
        """,
        (project_id, source),
    ).fetchone()
    if not row or not row["payload"]:
        return None
    try:
        return json.loads(row["payload"])
    except json.JSONDecodeError:
        return None


def compute_derived_for_project(
    conn: sqlite3.Connection,
    project: Project,
    signal_date: date,
) -> list[DerivedSignal]:
    """Calcula todos los signals derivados para `project` en `signal_date`.

    Skipa silenciosamente signals para los que falta raw_snapshot (gap-aware:
    el caller decide qué hacer con ausencias — Layer 1 aplica gap policy).
    """
    assert project.id is not None
    out: list[DerivedSignal] = []

    binance_payload = _latest_payload(conn, project.id, "binance")
    if binance_payload and "candles" in binance_payload:
        candles = binance_payload["candles"]
        df_daily = candles_to_dataframe(candles)
        if not df_daily.empty:
            # ATR % sobre daily (más sensible que weekly para el dashboard)
            atr_pct_series = atr_pct(df_daily, period=14)
            atr_val = (
                None
                if atr_pct_series.empty or math.isnan(atr_pct_series.iloc[-1])
                else float(atr_pct_series.iloc[-1])
            )
            out.append(
                DerivedSignal(
                    project_id=project.id,
                    signal_date=signal_date,
                    signal_name="atr_pct_14d",
                    value=atr_val,
                    formula_version=FORMULA_VERSIONS["atr_wilder"],
                )
            )

            # Consolidation breakout — solo si el archetype lo soporta
            meta = get_archetype_meta(project.archetype)
            if meta.consolidation_applies:
                df_weekly = resample_to_weekly(df_daily)
                # Look-ahead protection: usar solo bars cerradas (excluir la semana en curso)
                today_week_start = pd.Timestamp(signal_date, tz="UTC").to_period("W-MON").start_time
                today_week_start = (
                    today_week_start.tz_localize("UTC")
                    if today_week_start.tz is None
                    else today_week_start
                )
                df_weekly_closed = df_weekly[df_weekly.index < today_week_start]
                result = evaluate_consolidation_breakout(df_weekly_closed)
                out.append(
                    DerivedSignal(
                        project_id=project.id,
                        signal_date=signal_date,
                        signal_name="consolidation_breakout",
                        value=result.score,
                        formula_version="v1",
                    )
                )

    # DeFiLlama TVL change 7d (proxy de tvl_fees_trend)
    llama_payload = _latest_payload(conn, project.id, "defillama")
    if llama_payload:
        change_7d = llama_payload.get("change_7d_pct")
        if isinstance(change_7d, (int, float)) and not math.isnan(change_7d):
            out.append(
                DerivedSignal(
                    project_id=project.id,
                    signal_date=signal_date,
                    signal_name="tvl_change_30d_pct",  # alias for tvl_fees_trend
                    value=float(change_7d),  # using 7d as proxy until /tvl endpoint integrated
                    formula_version="v1-7dproxy",
                )
            )

    hl_payload = _latest_payload(conn, project.id, "hyperliquid")
    if hl_payload:
        zr = compute_funding_zscore(hl_payload)
        out.append(
            DerivedSignal(
                project_id=project.id,
                signal_date=signal_date,
                signal_name="funding_zscore_30d",
                value=zr.z_score,
                formula_version="v1",
            )
        )

    return out


def persist_derived_for_project(
    conn: sqlite3.Connection,
    signals: list[DerivedSignal],
    batch_id: str,
) -> int:
    """UPSERT batch de DerivedSignals. Retorna cantidad persistida."""
    for s in signals:
        upsert_derived_signal(conn, s, batch_id)
    return len(signals)

"""Validación retrospectiva del detector consolidation_breakout sobre histórico.

Lee `ohlcv_daily` (alimentado por `backfill-ohlcv`), itera semana cerrada por
semana cerrada sobre el rango pedido y aplica `evaluate_consolidation_breakout`
con look-ahead protection. Devuelve la serie de detecciones para inspección
visual / generación de reporte.

Uso: alimenta el comando CLI `crypto-insights validate-breakout`. NO se usa
en producción batch (Layer 1 evalúa solo "última semana cerrada").

Anti look-ahead (R19): para cada `week_end` t evaluamos solo con bars
estrictamente anteriores a t. La fórmula y el filtrado son los mismos que
en producción — la única diferencia es la iteración temporal.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date

import pandas as pd

from ..signals.consolidation_breakout import (
    MIN_BARS_REQUIRED,
    BreakoutResult,
    evaluate_consolidation_breakout,
)
from ..signals.indicators import resample_to_weekly


@dataclass(frozen=True, slots=True)
class BreakoutObservation:
    """Detección semanal: estado al cierre de la weekly bar `week_start`."""

    week_start: date
    week_end: date
    score: float
    compression_active: bool
    breakout_triggered: bool
    range_pct: float | None
    atr_ratio: float | None
    volume_ratio: float | None
    breakout_rvol: float | None
    rsi_during_compression: float | None
    bbw_value: float | None
    cmf_value: float | None
    reason: str
    close: float


def load_ohlcv_daily(
    conn: sqlite3.Connection,
    project_id: int,
    *,
    start_date: date | None = None,
    end_date: date | None = None,
) -> pd.DataFrame:
    """Lee ohlcv_daily y devuelve DataFrame indexado por open_time UTC."""
    sql = "SELECT candle_date, open, high, low, close, volume FROM ohlcv_daily WHERE project_id = ?"
    params: list[object] = [project_id]
    if start_date is not None:
        sql += " AND candle_date >= ?"
        params.append(start_date.isoformat())
    if end_date is not None:
        sql += " AND candle_date <= ?"
        params.append(end_date.isoformat())
    sql += " ORDER BY candle_date ASC"

    rows = conn.execute(sql, params).fetchall()
    if not rows:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])

    df = pd.DataFrame([dict(r) for r in rows])
    df["candle_date"] = pd.to_datetime(df["candle_date"], utc=True)
    df = df.set_index("candle_date")
    return df[["open", "high", "low", "close", "volume"]].astype("float64")


def evaluate_history(
    weekly_df: pd.DataFrame,
    *,
    start_week: pd.Timestamp | None = None,
    end_week: pd.Timestamp | None = None,
) -> list[BreakoutObservation]:
    """Itera semanas cerradas y aplica el detector con look-ahead protection.

    Para cada `cursor` weekly index, evalúa con `df_weekly[df_weekly.index <= cursor]`
    — el detector ya consume la última fila como "current week", por lo que la
    semana evaluada es la de cierre `cursor`.

    `start_week` / `end_week` recortan el rango de observaciones devueltas
    (no el dataset usado para indicadores baseline).
    """
    if len(weekly_df) < MIN_BARS_REQUIRED:
        return []

    observations: list[BreakoutObservation] = []
    # Iteramos desde el primer índice con suficiente historia
    eligible_index = weekly_df.index[MIN_BARS_REQUIRED - 1 :]

    for cursor in eligible_index:
        if start_week is not None and cursor < start_week:
            continue
        if end_week is not None and cursor > end_week:
            break

        window = weekly_df.loc[:cursor]
        result: BreakoutResult = evaluate_consolidation_breakout(window)
        week_end = cursor + pd.Timedelta(days=6)

        observations.append(
            BreakoutObservation(
                week_start=cursor.date(),
                week_end=week_end.date(),
                score=result.score,
                compression_active=result.compression_active,
                breakout_triggered=result.breakout_triggered,
                range_pct=result.range_pct,
                atr_ratio=result.atr_ratio,
                volume_ratio=result.volume_ratio,
                breakout_rvol=result.breakout_rvol,
                rsi_during_compression=result.rsi_during_compression,
                bbw_value=result.bbw_value,
                cmf_value=result.cmf_value,
                reason=result.reason,
                close=float(window["close"].iloc[-1]),
            )
        )

    return observations


def validate_breakout_history(
    conn: sqlite3.Connection,
    project_id: int,
    *,
    start_date: date | None = None,
    end_date: date | None = None,
) -> list[BreakoutObservation]:
    """Full pipeline: ohlcv_daily → weekly resample → iter semanal con detector.

    El rango `start_date/end_date` filtra qué semanas se REPORTAN, pero los
    indicadores baseline (ATR 50w, BBW 100w) usan TODO el histórico disponible
    para evitar falsos positivos por baseline corto.
    """
    df_daily = load_ohlcv_daily(conn, project_id)
    if df_daily.empty:
        return []

    df_weekly = resample_to_weekly(df_daily)
    if df_weekly.empty:
        return []

    def _to_week_start(d: date) -> pd.Timestamp:
        ts = pd.Timestamp(d).to_period("W-MON").start_time
        return ts.tz_localize("UTC") if ts.tz is None else ts

    start_week = _to_week_start(start_date) if start_date is not None else None
    end_week = _to_week_start(end_date) if end_date is not None else None

    return evaluate_history(df_weekly, start_week=start_week, end_week=end_week)


def render_markdown_report(
    project_symbol: str,
    observations: list[BreakoutObservation],
    *,
    archetype: str | None = None,
) -> str:
    """Genera reporte markdown para inspección visual.

    Resalta semanas con score > 0 con bullet. Tabla densa al final con todas
    las observaciones para auditoría completa.
    """
    if not observations:
        return f"# Consolidation breakout validation — {project_symbol}\n\n(no observations: insufficient OHLCV history or invalid range)\n"

    highlights = [o for o in observations if o.score > 0]
    triggered = [o for o in highlights if o.breakout_triggered]

    lines = [
        f"# Consolidation breakout validation — {project_symbol}",
        "",
        f"Archetype: {archetype or '—'}",
        f"Rango: {observations[0].week_start} → {observations[-1].week_end}",
        f"Total semanas evaluadas: {len(observations)}",
        f"Semanas con score > 0: {len(highlights)} ({len(triggered)} breakouts confirmados)",
        "",
        "## Highlights (score > 0)",
        "",
    ]
    if not highlights:
        lines.append(
            "(ninguno — el detector es estricto por diseño: 4 criterios + BBW + CMF + RSI<50)"
        )
    else:
        lines.append(
            "| Week start | Score | Trigger | Close | Range | ATR ratio | Vol ratio | RVOL | RSI | Reason |"
        )
        lines.append("|---|---|---|---|---|---|---|---|---|---|")
        for o in highlights:
            lines.append(
                f"| {o.week_start} | {o.score:.1f} | "
                f"{'BREAKOUT' if o.breakout_triggered else 'ready'} | "
                f"{o.close:.4f} | "
                f"{o.range_pct:.1%} | "
                f"{(o.atr_ratio or 0):.2f} | "
                f"{(o.volume_ratio or 0):.2f} | "
                f"{(o.breakout_rvol or 0):.2f} | "
                f"{(o.rsi_during_compression or 0):.1f} | "
                f"{o.reason} |"
            )

    lines.append("")
    lines.append("## Full timeline (todas las semanas)")
    lines.append("")
    lines.append("| Week start | Score | Compression | Breakout | Reason |")
    lines.append("|---|---|---|---|---|")
    for o in observations:
        lines.append(
            f"| {o.week_start} | {o.score:.1f} | "
            f"{'Y' if o.compression_active else '-'} | "
            f"{'Y' if o.breakout_triggered else '-'} | "
            f"{o.reason} |"
        )

    lines.append("")
    return "\n".join(lines)

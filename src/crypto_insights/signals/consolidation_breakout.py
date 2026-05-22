"""Consolidation breakout — ADR 0004.

Detector semanal sobre OHLCV diario (resampleado a weekly). 4 criterios
simultáneos + filtro RSI<50.

Look-ahead protection: opera SOLO sobre velas weekly **cerradas**. En
producción, `df.shift(1)` garantiza que "current week" es la última cerrada.

Score derivado:
  0.0 si no hay compresión
  0.5 si hay compresión (3 primeros criterios) pero no breakout
  1.0 si breakout confirmado en la semana corriente
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import pandas as pd

from .indicators import (
    atr_wilder,
    bollinger_band_width,
    chaikin_money_flow,
    range_compression,
    rsi,
)

# Thresholds iniciales (Open Q5 — reweightable tras 4-8 semanas feedback).
DEFAULT_RANGE_THRESHOLD_PCT = 0.15  # < 15% rango sobre min low
DEFAULT_ATR_RATIO_THRESHOLD = 0.7  # ATR_14w < 70% mediana ATR últimas 50w
DEFAULT_VOLUME_RATIO_THRESHOLD = 0.6  # mean vol 4w < 60% mean vol baseline 20w
DEFAULT_BREAKOUT_RVOL_THRESHOLD = 1.5  # volume_current > 1.5x mean 6w
DEFAULT_RSI_FILTER = 50  # RSI < 50 durante compresión
DEFAULT_COMPRESSION_WINDOW = 6  # Q6 — 6w más sensible

# Mínimo de weekly bars para evaluar (criterio 1: 6w; ATR baseline: 50w previas).
MIN_BARS_REQUIRED = 56


@dataclass(frozen=True, slots=True)
class BreakoutResult:
    score: float  # 0.0 / 0.5 / 1.0
    compression_active: bool  # 3 primeros criterios cumplen
    breakout_triggered: bool  # criterio 4 también cumple
    range_pct: float | None
    atr_ratio: float | None
    volume_ratio: float | None
    breakout_rvol: float | None
    rsi_during_compression: float | None
    bbw_value: float | None
    cmf_value: float | None
    reason: str  # legible para reason_human


def evaluate_consolidation_breakout(
    weekly_df: pd.DataFrame,
    *,
    compression_window: int = DEFAULT_COMPRESSION_WINDOW,
    range_threshold: float = DEFAULT_RANGE_THRESHOLD_PCT,
    atr_ratio_threshold: float = DEFAULT_ATR_RATIO_THRESHOLD,
    volume_ratio_threshold: float = DEFAULT_VOLUME_RATIO_THRESHOLD,
    breakout_rvol_threshold: float = DEFAULT_BREAKOUT_RVOL_THRESHOLD,
    rsi_filter: float = DEFAULT_RSI_FILTER,
) -> BreakoutResult:
    """Evalúa los 4 criterios + filtro RSI sobre weekly DataFrame.

    weekly_df debe haberse construido con resample_to_weekly() y filtrado
    para incluir SOLO bars cerradas (caller's responsibility: para detección
    en current week, pasar df hasta last_closed_week_end).
    """
    if len(weekly_df) < MIN_BARS_REQUIRED:
        return BreakoutResult(
            score=0.0,
            compression_active=False,
            breakout_triggered=False,
            range_pct=None,
            atr_ratio=None,
            volume_ratio=None,
            breakout_rvol=None,
            rsi_during_compression=None,
            bbw_value=None,
            cmf_value=None,
            reason=f"insufficient_history ({len(weekly_df)} < {MIN_BARS_REQUIRED} weeks)",
        )

    # ── Criterio 1: range compression ─────────────────────────────────
    rc = range_compression(weekly_df, window=compression_window)
    range_pct = rc.iloc[-1]
    range_ok = range_pct < range_threshold

    # ── Criterio 1.b (refinamiento research): BB Width bottom decile ──
    bbw = bollinger_band_width(weekly_df, period=20)
    # Bottom decile vs last 100w (or all available if <100)
    lookback = min(100, len(bbw) - 1)
    bbw_window = bbw.iloc[-(lookback + 1) : -1]
    bbw_value = bbw.iloc[-1]
    bbw_low = bbw_value <= bbw_window.quantile(0.1) if not bbw_window.isna().all() else False

    # ── Criterio 2: ATR contraction (Wilder) ──────────────────────────
    atr = atr_wilder(weekly_df, period=14)
    atr_current = atr.iloc[-1]
    atr_baseline = atr.iloc[-51:-1].median()
    atr_ratio = (
        atr_current / atr_baseline
        if atr_baseline and not math.isnan(atr_baseline) and atr_baseline > 0
        else None
    )
    atr_ok = atr_ratio is not None and atr_ratio < atr_ratio_threshold

    # ── Criterio 3: volume drying up ──────────────────────────────────
    vol_4w = weekly_df["volume"].iloc[-4:].mean()
    vol_baseline = weekly_df["volume"].iloc[-24:-4].mean()
    volume_ratio = vol_4w / vol_baseline if vol_baseline > 0 else None
    # Refinamiento research: CMF(20w) > 0 también
    cmf = chaikin_money_flow(weekly_df, period=20)
    cmf_value = cmf.iloc[-1] if not cmf.empty else None
    cmf_ok = cmf_value is not None and not math.isnan(cmf_value) and cmf_value > 0
    volume_ok = volume_ratio is not None and volume_ratio < volume_ratio_threshold

    # ── Filtro RSI anti-falso-positivo ────────────────────────────────
    rsi_series = rsi(weekly_df, period=14)
    rsi_window = rsi_series.iloc[-compression_window:]
    rsi_mean_compression = rsi_window.mean() if not rsi_window.empty else None
    rsi_ok = (
        rsi_mean_compression is not None
        and not math.isnan(rsi_mean_compression)
        and rsi_mean_compression < rsi_filter
    )

    # ── Estado: compresión (todos los criterios 1-3 + BBW + CMF + RSI) ─
    compression_active = bool(range_ok and bbw_low and atr_ok and volume_ok and cmf_ok)

    # ── Criterio 4: breakout trigger ──────────────────────────────────
    # Close > max(close last 6w excluding current) AND volume > 1.5x mean(6w)
    closes_excl_current = weekly_df["close"].iloc[-(compression_window + 1) : -1]
    close_current = weekly_df["close"].iloc[-1]
    price_breakout = not closes_excl_current.empty and close_current > closes_excl_current.max()
    vol_mean_6w = weekly_df["volume"].iloc[-(compression_window + 1) : -1].mean()
    vol_current = weekly_df["volume"].iloc[-1]
    breakout_rvol = vol_current / vol_mean_6w if vol_mean_6w > 0 else None
    vol_breakout = breakout_rvol is not None and breakout_rvol > breakout_rvol_threshold

    breakout_triggered = bool(compression_active and price_breakout and vol_breakout)

    if breakout_triggered and not rsi_ok:
        # Downgrade per R-research filter
        score = 0.5
        reason = f"breakout_with_high_rsi (rsi_mean={rsi_mean_compression:.1f} >= {rsi_filter})"
    elif breakout_triggered:
        score = 1.0
        reason = (
            f"breakout (range {range_pct:.1%}, atr {atr_ratio:.2f}, "
            f"vol {volume_ratio:.2f}, rvol {breakout_rvol:.2f})"
        )
    elif compression_active and rsi_ok:
        score = 0.5
        reason = (
            f"compression_ready (range {range_pct:.1%}, atr {atr_ratio:.2f}, "
            f"vol {volume_ratio:.2f}, rsi {rsi_mean_compression:.1f})"
        )
    else:
        score = 0.0
        reason = _explain_why_not(range_ok, bbw_low, atr_ok, volume_ok, cmf_ok, rsi_ok)

    return BreakoutResult(
        score=score,
        compression_active=compression_active,
        breakout_triggered=breakout_triggered,
        range_pct=float(range_pct) if not math.isnan(range_pct) else None,
        atr_ratio=atr_ratio,
        volume_ratio=volume_ratio,
        breakout_rvol=breakout_rvol,
        rsi_during_compression=rsi_mean_compression,
        bbw_value=float(bbw_value) if not math.isnan(bbw_value) else None,
        cmf_value=cmf_value,
        reason=reason,
    )


def _explain_why_not(
    range_ok: bool,
    bbw_low: bool,
    atr_ok: bool,
    volume_ok: bool,
    cmf_ok: bool,
    rsi_ok: bool,
) -> str:
    """Razón legible de por qué no se emitió score > 0."""
    missing = [
        name
        for name, ok in [
            ("range_compression", range_ok),
            ("bbw_bottom_decile", bbw_low),
            ("atr_contraction", atr_ok),
            ("volume_drying", volume_ok),
            ("cmf_positive", cmf_ok),
            ("rsi_under_50", rsi_ok),
        ]
        if not ok
    ]
    return f"no_compression (missing: {','.join(missing)})" if missing else "no_compression"

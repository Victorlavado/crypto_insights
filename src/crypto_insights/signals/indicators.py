"""Indicadores técnicos calculados a mano (ADR 0002).

Auditables, sin opacidad sobre qué variante de media se usa. Todos operan
sobre `pd.DataFrame` con columnas estándar OHLCV (`open`, `high`, `low`,
`close`, `volume`).

Conversión daily → weekly: usar `pd.resample("W-MON", label="left", closed="left")`
para que cada vela semanal sea lunes-domingo y cierre domingo 23:59 UTC.

CRÍTICO: bumpear `FORMULA_VERSIONS[signal]` cuando cambie la fórmula. El
backfill respeta versión histórica (R17).
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

FORMULA_VERSIONS: dict[str, str] = {
    "atr_wilder": "v1",
    "bb_width": "v1",
    "rvol": "v1",
    "range_compression": "v1",
    "cmf": "v1",
    "rsi": "v1",
}


def true_range(df: pd.DataFrame) -> pd.Series:
    """True Range clásico (Welles Wilder).

    TR_t = max(high - low, |high - close_{t-1}|, |low - close_{t-1}|)
    Primera fila: TR = high - low (no hay close previo).
    """
    prev_close = df["close"].shift(1)
    h_l = df["high"] - df["low"]
    h_pc = (df["high"] - prev_close).abs()
    l_pc = (df["low"] - prev_close).abs()
    return pd.concat([h_l, h_pc, l_pc], axis=1).max(axis=1)


def atr_wilder(df: pd.DataFrame, *, period: int = 14) -> pd.Series:
    """ATR Wilder (RMA recursivo). Estándar de TradingView/thinkorswim.

    ATR_t = (ATR_{t-1} × (period - 1) + TR_t) / period

    Seed: primer ATR = media simple de los primeros `period` true ranges.
    """
    tr = true_range(df)
    if len(tr) < period:
        return pd.Series([math.nan] * len(tr), index=df.index)

    atr = pd.Series([math.nan] * len(tr), index=df.index, dtype="float64")
    seed = tr.iloc[:period].mean()
    atr.iloc[period - 1] = seed
    alpha = 1.0 / period
    for i in range(period, len(tr)):
        prev = atr.iloc[i - 1]
        atr.iloc[i] = prev * (1 - alpha) + tr.iloc[i] * alpha
    return atr


def atr_pct(df: pd.DataFrame, *, period: int = 14) -> pd.Series:
    """ATR como porcentaje del close — más comparable entre proyectos."""
    return atr_wilder(df, period=period) / df["close"] * 100.0


def bollinger_band_width(df: pd.DataFrame, *, period: int = 20, num_std: float = 2.0) -> pd.Series:
    """BBW = (upper - lower) / middle.

    Donde middle = SMA(close, period), upper = middle + num_std * stddev,
    lower = middle - num_std * stddev. Detecta squeeze cuando BBW alcanza
    mínimo histórico (R: complemento al range compression simple).
    """
    middle = df["close"].rolling(window=period, min_periods=period).mean()
    std = df["close"].rolling(window=period, min_periods=period).std(ddof=0)
    upper = middle + num_std * std
    lower = middle - num_std * std
    return (upper - lower) / middle


def relative_volume(df: pd.DataFrame, *, baseline_period: int = 20) -> pd.Series:
    """RVOL = volume / mean(volume últimas `baseline_period` barras excluyendo current).

    > 1.5x suele acompañar breakouts; criterio 4 del consolidation breakout.
    """
    baseline = (
        df["volume"].shift(1).rolling(window=baseline_period, min_periods=baseline_period).mean()
    )
    return df["volume"] / baseline


def range_compression(df: pd.DataFrame, *, window: int = 6) -> pd.Series:
    """(max_high_w - min_low_w) / min_low_w over a rolling window.

    Criterio 1 del consolidation breakout: < 15% threshold inicial.
    Window 6 weeks por decisión Q6 (más sensible que 8w default).
    """
    max_high = df["high"].rolling(window=window, min_periods=window).max()
    min_low = df["low"].rolling(window=window, min_periods=window).min()
    return (max_high - min_low) / min_low


def chaikin_money_flow(df: pd.DataFrame, *, period: int = 20) -> pd.Series:
    """CMF: ponderación de volume por close-position en el rango.

    MFM = ((close - low) - (high - close)) / (high - low)
    MFV = MFM × volume
    CMF = sum(MFV, period) / sum(volume, period)

    > 0 → acumulación; < 0 → distribución. R: detecta "volume drying up" mejor
    que media simple porque pondera por close position en el rango.
    """
    hl_range = df["high"] - df["low"]
    # Evita división por cero cuando high == low (vela sin movimiento)
    mfm = pd.Series(
        np.where(
            hl_range > 0,
            ((df["close"] - df["low"]) - (df["high"] - df["close"])) / hl_range,
            0.0,
        ),
        index=df.index,
    )
    mfv = mfm * df["volume"]
    return (
        mfv.rolling(window=period, min_periods=period).sum()
        / df["volume"].rolling(window=period, min_periods=period).sum()
    )


def rsi(df: pd.DataFrame, *, period: int = 14, column: str = "close") -> pd.Series:
    """RSI Wilder (RMA de gains/losses).

    RSI = 100 - 100/(1 + RS), RS = avg_gain / avg_loss.
    Wilder smoothing: alpha = 1/period (igual que ATR).

    Filtro anti-falso-positivo del consolidation breakout: RSI(14w) < 50
    durante compresión para evitar breakouts desde sobrecalentamiento.
    """
    delta = df[column].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    if len(delta) < period + 1:
        return pd.Series([math.nan] * len(delta), index=df.index)

    avg_gain = pd.Series([math.nan] * len(delta), index=df.index, dtype="float64")
    avg_loss = pd.Series([math.nan] * len(delta), index=df.index, dtype="float64")
    avg_gain.iloc[period] = gain.iloc[1 : period + 1].mean()
    avg_loss.iloc[period] = loss.iloc[1 : period + 1].mean()
    alpha = 1.0 / period
    for i in range(period + 1, len(delta)):
        avg_gain.iloc[i] = avg_gain.iloc[i - 1] * (1 - alpha) + gain.iloc[i] * alpha
        avg_loss.iloc[i] = avg_loss.iloc[i - 1] * (1 - alpha) + loss.iloc[i] * alpha

    # avg_loss=0 → RS=inf → RSI=100. avg_loss>0 → normal formula.
    # avg_gain=0 AND avg_loss=0 → market is flat → RSI=50 by convention.
    rsi_values = pd.Series([math.nan] * len(delta), index=df.index, dtype="float64")
    for i in range(period, len(delta)):
        g = avg_gain.iloc[i]
        loss_val = avg_loss.iloc[i]
        if math.isnan(g) or math.isnan(loss_val):
            continue
        if loss_val == 0.0 and g == 0.0:
            rsi_values.iloc[i] = 50.0
        elif loss_val == 0.0:
            rsi_values.iloc[i] = 100.0
        else:
            rs = g / loss_val
            rsi_values.iloc[i] = 100.0 - (100.0 / (1.0 + rs))
    return rsi_values


def candles_to_dataframe(candles: list[dict]) -> pd.DataFrame:
    """Convierte payload Binance (lista de dicts con keys OHLCV) a DataFrame.

    Index = open_time (datetime UTC). Útil para downstream resample weekly.
    """
    if not candles:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    df = pd.DataFrame(candles)
    df["open_time"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    df = df.set_index("open_time")
    return df[["open", "high", "low", "close", "volume"]].astype("float64")


def resample_to_weekly(df: pd.DataFrame) -> pd.DataFrame:
    """Daily → Weekly (lunes-domingo, cierra domingo 23:59 UTC).

    `label='left', closed='left'` para que el index sea el lunes de cada
    semana — fuente de verdad estable para look-ahead protection en
    consolidation_breakout (`df = df[df.week_end < today]`).

    Filtra weekly bars con <5 días no-zero-volume (especificación R-Fase 2).
    """
    if df.empty:
        return df

    # Conteo de días con volume>0 por semana para el filtro de validez
    days_with_vol = (
        (df["volume"] > 0).resample("W-MON", label="left", closed="left").sum().rename("valid_days")
    )

    weekly = df.resample("W-MON", label="left", closed="left").agg(
        {
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum",
        }
    )
    weekly["valid_days"] = days_with_vol
    return weekly[weekly["valid_days"] >= 5].drop(columns=["valid_days"])

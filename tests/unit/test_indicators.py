"""Property tests for indicators (hypothesis where it makes sense)."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
from hypothesis import given, settings
from hypothesis import strategies as st

from crypto_insights.signals.indicators import (
    atr_wilder,
    bollinger_band_width,
    candles_to_dataframe,
    chaikin_money_flow,
    range_compression,
    relative_volume,
    resample_to_weekly,
    rsi,
    true_range,
)


def _make_ohlcv(rows: int, *, seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    closes = 100 * np.cumprod(1 + rng.normal(0, 0.02, rows))
    highs = closes * (1 + np.abs(rng.normal(0, 0.01, rows)))
    lows = closes * (1 - np.abs(rng.normal(0, 0.01, rows)))
    opens = closes * (1 + rng.normal(0, 0.005, rows))
    vols = np.abs(rng.normal(1000, 200, rows))
    return pd.DataFrame(
        {"open": opens, "high": highs, "low": lows, "close": closes, "volume": vols},
        index=pd.date_range("2024-01-01", periods=rows, freq="D"),
    )


def test_true_range_non_negative() -> None:
    df = _make_ohlcv(50)
    tr = true_range(df)
    assert (tr.dropna() >= 0).all()


def test_atr_wilder_non_negative_when_enough_history() -> None:
    df = _make_ohlcv(100)
    atr = atr_wilder(df, period=14)
    assert atr.iloc[-1] >= 0


def test_atr_wilder_nan_when_history_too_short() -> None:
    df = _make_ohlcv(5)
    atr = atr_wilder(df, period=14)
    assert atr.isna().all()


def test_bollinger_band_width_upper_geq_middle_geq_lower() -> None:
    """BB Width = (upper - lower) / middle >= 0 always."""
    df = _make_ohlcv(100)
    bbw = bollinger_band_width(df, period=20)
    assert (bbw.dropna() >= 0).all()


def test_relative_volume_positive() -> None:
    df = _make_ohlcv(100)
    rvol = relative_volume(df, baseline_period=20)
    assert (rvol.dropna() > 0).all()


def test_range_compression_non_negative() -> None:
    df = _make_ohlcv(100)
    rc = range_compression(df, window=6)
    # (max_high - min_low) / min_low >= 0 since max_high >= min_low and min_low > 0
    assert (rc.dropna() >= 0).all()


def test_rsi_in_zero_to_one_hundred() -> None:
    df = _make_ohlcv(100)
    rs = rsi(df, period=14)
    valid = rs.dropna()
    assert ((valid >= 0) & (valid <= 100)).all()


def test_rsi_monotone_up_market_high() -> None:
    """RSI debe estar cerca de 100 cuando todo son ganancias consecutivas."""
    df = pd.DataFrame(
        {
            "open": np.linspace(100, 200, 30),
            "high": np.linspace(101, 201, 30),
            "low": np.linspace(99, 199, 30),
            "close": np.linspace(100, 200, 30),
            "volume": [1000] * 30,
        }
    )
    rs = rsi(df, period=14)
    assert rs.iloc[-1] > 90


def test_cmf_in_minus_one_to_one() -> None:
    df = _make_ohlcv(50)
    cmf = chaikin_money_flow(df, period=20)
    valid = cmf.dropna()
    assert ((valid >= -1) & (valid <= 1)).all()


def test_candles_to_dataframe_handles_empty() -> None:
    df = candles_to_dataframe([])
    assert df.empty
    assert list(df.columns) == ["open", "high", "low", "close", "volume"]


def test_candles_to_dataframe_parses_binance_payload() -> None:
    candles = [
        {
            "open_time": 1746489600000,
            "open": 30.05,
            "high": 31.2,
            "low": 29.81,
            "close": 30.95,
            "volume": 1234567.89,
            "close_time": 1746575999999,
            "quote_volume": 37500000.5,
            "trades": 45234,
        }
    ]
    df = candles_to_dataframe(candles)
    assert len(df) == 1
    assert df["close"].iloc[0] == 30.95


def test_resample_to_weekly_filters_invalid_bars() -> None:
    """Weekly bars con <5 días volume>0 deben filtrarse."""
    # 2 semanas: la primera con todos volume 0, la segunda con 5 volume válidos
    idx = pd.date_range("2024-01-01", periods=14, freq="D")
    vol = [0] * 7 + [100, 100, 100, 100, 100, 0, 0]
    df = pd.DataFrame(
        {
            "open": [100] * 14,
            "high": [101] * 14,
            "low": [99] * 14,
            "close": [100] * 14,
            "volume": vol,
        },
        index=idx,
    )
    weekly = resample_to_weekly(df)
    # Solo 1 semana válida (la segunda)
    assert len(weekly) == 1


@given(period=st.integers(min_value=2, max_value=30), rows=st.integers(min_value=50, max_value=200))
@settings(max_examples=10, deadline=None)
def test_atr_invariant_finite(period: int, rows: int) -> None:
    df = _make_ohlcv(rows)
    atr = atr_wilder(df, period=period)
    valid = atr.dropna()
    if not valid.empty:
        assert valid.iloc[-1] >= 0 and not math.isinf(valid.iloc[-1])

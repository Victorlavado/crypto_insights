"""Funding signal: z-score 30d.

Calcula z-score del funding actual contra distribución últimos 30 días.
- z > +2 → señal de distribución (mercado over-leveraged long)
- z < -2 → señal contrarian de acumulación (capitulation longs)

Input: payload de hyperliquid (funding_current + funding_history_30d).
Output: float z-score (None si insuficiente histórico).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

MIN_HISTORY_FOR_ZSCORE = 14  # mínimo 14 puntos para que std sea estable


@dataclass(frozen=True, slots=True)
class FundingZScoreResult:
    z_score: float | None
    funding_current: float | None
    funding_mean_30d: float | None
    funding_std_30d: float | None
    history_count: int


def compute_funding_zscore(payload: dict) -> FundingZScoreResult:
    """Calcula z-score del funding actual contra distribución 30d.

    z = (funding_current - mean) / std.

    Si std=0 (funding constante) o history < MIN_HISTORY_FOR_ZSCORE → z=None.
    Si funding_current is None → z=None.
    """
    funding_current = payload.get("funding_current")
    history = payload.get("funding_history_30d", [])
    if funding_current is None or not isinstance(history, list):
        return FundingZScoreResult(
            None, funding_current, None, None, len(history) if isinstance(history, list) else 0
        )

    history_arr = np.array(
        [v for v in history if isinstance(v, (int, float)) and not math.isnan(v)],
        dtype="float64",
    )
    if len(history_arr) < MIN_HISTORY_FOR_ZSCORE:
        return FundingZScoreResult(
            None,
            funding_current,
            float(history_arr.mean()) if len(history_arr) else None,
            None,
            len(history_arr),
        )

    mean = float(history_arr.mean())
    std = float(history_arr.std(ddof=0))
    if std == 0.0:
        return FundingZScoreResult(None, funding_current, mean, 0.0, len(history_arr))

    z = (funding_current - mean) / std
    return FundingZScoreResult(z, funding_current, mean, std, len(history_arr))

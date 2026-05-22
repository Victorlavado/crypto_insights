"""Pesos por archetype + thresholds de estado.

Tabla de la sección "Fusión por archetype" del plan. Suma = 1.0 dentro de
cada archetype. Signals con peso 0 NO se evalúan para ese archetype.

Cuando se reweighta vía learnings/, editar este archivo y bumpear
formula_version del signal afectado si la fórmula también cambió.

Gap policy (ADR 0005): si <30% del peso falta → renormalize sobre presentes.
Si ≥30% → degraded.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..models import Archetype, ProjectStateValue

# Signal weights por archetype. Filas: signal name. Cols: archetype.
# Suma por columna = 1.0.
SIGNAL_WEIGHTS: dict[Archetype, dict[str, float]] = {
    Archetype.MEMECOIN_BRAND: {
        "consolidation_breakout": 0.0,
        "smart_money_delta": 0.40,
        "funding_zscore_30d": 0.20,
        "mindshare_velocity": 0.40,
        "cex_netflows": 0.0,
        "tvl_fees_trend": 0.0,
        "stablecoin_dex_growth": 0.0,
        "holder_growth": 0.0,
    },
    Archetype.INFRA_PMF: {
        "consolidation_breakout": 0.25,
        "smart_money_delta": 0.20,
        "funding_zscore_30d": 0.20,
        "mindshare_velocity": 0.10,
        "cex_netflows": 0.10,
        "tvl_fees_trend": 0.15,
        "stablecoin_dex_growth": 0.0,
        "holder_growth": 0.0,
    },
    Archetype.TESIS_MACRO: {
        "consolidation_breakout": 0.25,
        "smart_money_delta": 0.20,
        "funding_zscore_30d": 0.10,
        "mindshare_velocity": 0.20,
        "cex_netflows": 0.10,
        "tvl_fees_trend": 0.0,
        "stablecoin_dex_growth": 0.0,
        "holder_growth": 0.15,
    },
    Archetype.L1_MADURO: {
        "consolidation_breakout": 0.25,
        "smart_money_delta": 0.20,
        "funding_zscore_30d": 0.15,
        "mindshare_velocity": 0.05,
        "cex_netflows": 0.15,
        "tvl_fees_trend": 0.0,
        "stablecoin_dex_growth": 0.20,
        "holder_growth": 0.0,
    },
    Archetype.DEFI_BLUE_CHIP: {
        "consolidation_breakout": 0.25,
        "smart_money_delta": 0.20,
        "funding_zscore_30d": 0.10,
        "mindshare_velocity": 0.05,
        "cex_netflows": 0.10,
        "tvl_fees_trend": 0.20,
        "stablecoin_dex_growth": 0.0,
        "holder_growth": 0.10,
    },
    Archetype.POST_TGE: {
        "consolidation_breakout": 0.0,
        "smart_money_delta": 0.30,
        "funding_zscore_30d": 0.20,
        "mindshare_velocity": 0.50,
        "cex_netflows": 0.0,
        "tvl_fees_trend": 0.0,
        "stablecoin_dex_growth": 0.0,
        "holder_growth": 0.0,
    },
}

# Signals que normalizan: mapeo signal_name → (raw_min, raw_max, sign)
# Donde el rango raw→[-1, 1] para composite, y sign=+1/-1 indica si valor alto
# es bullish (+1) o bearish (-1).
SIGNAL_NORMALIZATION: dict[str, dict] = {
    "consolidation_breakout": {"raw_min": 0.0, "raw_max": 1.0, "sign": 1.0},
    "funding_zscore_30d": {"raw_min": -3.0, "raw_max": 3.0, "sign": -1.0},  # alto z → bearish
    "smart_money_delta": {"raw_min": -5.0, "raw_max": 5.0, "sign": 1.0},
    "mindshare_velocity": {"raw_min": -3.0, "raw_max": 3.0, "sign": 1.0},
    "cex_netflows": {"raw_min": -3.0, "raw_max": 3.0, "sign": -1.0},  # outflow > 0 = bullish
    "tvl_fees_trend": {"raw_min": -50.0, "raw_max": 50.0, "sign": 1.0},  # % change
    "stablecoin_dex_growth": {"raw_min": -30.0, "raw_max": 30.0, "sign": 1.0},
    "holder_growth": {"raw_min": -5.0, "raw_max": 5.0, "sign": 1.0},
}


@dataclass(frozen=True, slots=True)
class StateThresholds:
    """ADR 0006 — thresholds para state_from_scores. Open Q7: calibrables."""

    aceleracion_min: float = 0.6
    acumulacion_min: float = 0.3
    distribucion_max: float = -0.3
    colapso_max: float = -0.6
    reset_abs_max: float = 0.2  # |score| < 0.2 después de colapso → reset


DEFAULT_THRESHOLDS = StateThresholds()


def get_archetype_weights(archetype: Archetype) -> dict[str, float]:
    return dict(SIGNAL_WEIGHTS[archetype])


def normalize_signal(signal_name: str, raw_value: float) -> float | None:
    """Mapea raw value a [-1, 1] con clipping. None si signal no normalizable."""
    norm = SIGNAL_NORMALIZATION.get(signal_name)
    if norm is None:
        return None
    raw_min = norm["raw_min"]
    raw_max = norm["raw_max"]
    sign = norm["sign"]
    clipped = max(raw_min, min(raw_max, raw_value))
    # Map a [-1, +1]
    midpoint = (raw_min + raw_max) / 2
    half_range = (raw_max - raw_min) / 2
    normalized = (clipped - midpoint) / half_range
    return sign * normalized


def state_from_score(
    composite_score: float,
    *,
    prior_state: ProjectStateValue | None = None,
    consolidation_breakout: float | None = None,
    thresholds: StateThresholds = DEFAULT_THRESHOLDS,
) -> ProjectStateValue:
    """Mapea composite_score a estado discreto. ADR 0006 + plan Fase 3.

    Reglas:
    - score > 0.6 Y consolidation_breakout = 1.0 → aceleracion
    - score > 0.3 → acumulacion
    - score < -0.6 → colapso
    - score < -0.3 → distribucion
    - |score| < 0.2 después de colapso → reset
    - resto → acumulacion (zona neutra positiva) o distribucion (negativa)
    """
    if (
        composite_score >= thresholds.aceleracion_min
        and consolidation_breakout is not None
        and consolidation_breakout >= 0.99
    ):
        return ProjectStateValue.ACELERACION
    if composite_score <= thresholds.colapso_max:
        return ProjectStateValue.COLAPSO
    if (
        prior_state == ProjectStateValue.COLAPSO
        and abs(composite_score) <= thresholds.reset_abs_max
    ):
        return ProjectStateValue.RESET
    if composite_score <= thresholds.distribucion_max:
        return ProjectStateValue.DISTRIBUCION
    if composite_score >= thresholds.acumulacion_min:
        return ProjectStateValue.ACUMULACION
    # Zona neutra: si prior era reset → mantener; si no, devolver unknown
    if prior_state == ProjectStateValue.RESET:
        return ProjectStateValue.RESET
    return ProjectStateValue.UNKNOWN

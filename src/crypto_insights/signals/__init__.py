"""Signals: cálculos derivados a partir de raw_snapshots y events.

- unlocks.py: hard constraint Layer 2 (5% ponderado / 4-8 semanas)
- indicators.py: ATR Wilder, BB Width, RVOL, CMF, RSI (Fase 2)
- consolidation_breakout.py: detector semanal (Fase 2)
- smart_money.py: delta filtrado de wallets EOA (Fase 2)
- funding.py: z-score 30d (Fase 2)
"""

from .unlocks import UnlockConstraintResult, evaluate_unlock_constraint

__all__ = ["UnlockConstraintResult", "evaluate_unlock_constraint"]

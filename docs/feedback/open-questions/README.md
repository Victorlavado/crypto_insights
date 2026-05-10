# Open Questions del plan

Cada archivo aquí es una decisión del plan [`docs/plans/2026-05-10-feat-crypto-position-manager-mvp-plan.md`](../../plans/2026-05-10-feat-crypto-position-manager-mvp-plan.md) que requiere input explícito de Victor.

**Convención**:
- Nombre: `YYYY-MM-DD-qN-titulo-corto.md` (mismo N que en el plan).
- Cada archivo: contexto + recomendación + bloqueo (qué fase bloquea, si bloquea).
- Cuando se resuelve, se mueve a `docs/decisions/000N-titulo.md` como ADR si es estructural, o se cierra inline anotando la respuesta en el archivo.

**Estado actual** (vivo, actualizado 2026-05-10 tras resolución de Victor):

| Q | Pregunta | Bloqueante para | Status | Resolución |
|---|---|---|---|---|
| Q1 | Top holders ETH | Fase 2 | ✅ closed | **Alchemy primaria + Moralis fallback** |
| Q2 | Mindshare sin Kaito gratis | Fase 3 | ✅ closed | **Gap explícito + redistribuir pesos** (ver sección Future si Fase 4 muestra que duele) |
| Q3 | CEX netflows sin CryptoQuant | NO bloqueante | ✅ closed | **Omitir del MVP**. Reweightear el 0.10-0.15 de los archetypes a smart_money y funding |
| Q4 | `blocked` con posición abierta | Fase 3 | ✅ closed | **Solo informar**. Materializado en ADR 0003 |
| Q5 | Thresholds consolidation breakout | NO bloqueante | ✅ closed | **Tentativos del plan + recalibrar Fase 4** |
| Q6 | Ventana rango compresión | NO bloqueante | ✅ closed | **6 weeks** (cambio del default 8w del plan original) |
| Q7 | Calibración thresholds de estado | NO bloqueante | ✅ closed | **Tentativos + backtest visual Fase 4** |
| Q8 | Sparklines vs tabla densa | NO bloqueante | ✅ closed | **Tabla densa + drill-down con sparkline** |
| Q9 | Periodicidad daily | NO bloqueante | ✅ closed | **Daily fijo a 9:00 UTC** via Windows Task Scheduler |
| Q10 | Watchlist | Fase 0 | ⚠ parcial | **+MORPHO, +SPX6900, +PEPE = 29 totales**. Falta 1 para llegar a 30 (no bloqueante) |
| Q11 | DeFiLlama unlocks free vs Pro-only | Fase 1 | ⏳ pending | **Verificar empíricamente** en setup de Fase 1, primer paso del connector. Plan B/C documentados en ADR 0003 |
| Q12 | Política de gap (signal=None) | Fase 3 | ✅ closed | **Híbrido**: renormalizar <30%, degraded ≥30%. Materializado en **ADR 0005** |
| Q13 | Matriz transiciones state machine | Fase 3 | ✅ closed | **Matriz propuesta + hysteresis 2-batches**. Materializado en **ADR 0006** |

## ADRs creados como resultado

- [ADR 0002 — Stack técnico](../../decisions/0002-stack-tecnico.md)
- [ADR 0003 — Hard constraint de unlocks](../../decisions/0003-unlocks-hard-constraint.md) (Q4 incluida)
- [ADR 0004 — Consolidation breakout spec](../../decisions/0004-consolidation-breakout-spec.md) (Q5, Q6 incluidas)
- [ADR 0005 — Gap policy](../../decisions/0005-gap-policy.md) (Q12)
- [ADR 0006 — State machine + hysteresis](../../decisions/0006-state-machine-transitions.md) (Q13)

## Pendientes

- **Q11**: requiere ejecución (no decisión más). Acción concreta en primer commit de Fase 1.
- **Q10 parcial**: 1 proyecto más para llegar a 30. NO bloqueante para Fase 0; el loader puede arrancar con 29.

# Signal performance — log de validaciones empíricas

Origen: validaciones retrospectivas y feedback acumulado del MVP.

Regla: una observación entra aquí solo si está respaldada por datos (output de `crypto-insights validate-breakout` o snapshot de pipeline) o por ≥3 casos repetidos en `feedback/`.

---

## consolidation_breakout — thresholds demasiado estrictos para crypto

**Fecha**: 2026-05-11
**Casos analizados**: ZEC, SUI, AAVE (Binance OHLCV 2023-01 a 2025-12)
**Output**: `data/validation/{ZEC,SUI,AAVE}-breakout.md`

**Observación**: ejecutado el detector retrospectivamente sobre 82 weeks (2024-06 a 2025-12) en los 3 proyectos. Resultado: **0 detecciones** con score > 0 en cada uno.

Inspección de las weeks con menor `range_pct` para AAVE (top 8):

| Week | Range | ATR ratio | Vol ratio | BBW | CMF | RSI |
|---|---|---|---|---|---|---|
| 2024-10-21 | 36.9% | 1.20 | 0.70 | 0.949 | 0.03 | 64.3 |
| 2025-08-04 | 38.0% | 1.03 | 0.81 | 1.040 | 0.12 | 59.5 |
| 2025-09-15 | 40.0% | 0.96 | 0.61 | 0.474 | 0.06 | 57.3 |
| 2024-10-28 | 40.5% | 1.22 | 0.57 | 0.898 | 0.01 | 61.9 |
| 2025-12-22 | 41.5% | 0.90 | 0.73 | 0.981 | -0.09 | 38.0 |
| 2024-06-10 | 43.4% | 1.28 | 0.71 | 0.639 | 0.13 | 48.0 |

**Diagnóstico**: los thresholds vienen de TA tradicional (stocks), donde 15% range_pct sobre 6w es realista. En crypto la compresión real está en 30-45% — el threshold de 15% nunca se activa en swing crypto liquido (BTC/SOL excluidos del estudio, podrían ser distintos).

**Implicación**: cualquier evaluación de Layer 1 que dependa de consolidation_breakout en su forma actual va a emitir composite_score=0 sistemáticamente para signals con `consolidation_breakout > 0` peso ≥ 0.15.

**Acción propuesta (Open Q5)**: re-calibrar para crypto. Propuesta inicial a validar:

| Threshold | Original (stocks-derived) | Propuesto crypto | Justificación |
|---|---|---|---|
| `DEFAULT_RANGE_THRESHOLD_PCT` | 0.15 | 0.30 | Compresión empírica AAVE/SUI/ZEC 35-40% |
| `DEFAULT_ATR_RATIO_THRESHOLD` | 0.7 | 0.85 | Crypto ATR contracts menos profundamente |
| `DEFAULT_VOLUME_RATIO_THRESHOLD` | 0.6 | 0.7 | Volume drying menos drástico en spot crypto |
| `bbw_low quantile` | 0.1 | 0.2 | Decile demasiado restrictivo en activos volátiles |
| RSI<50 filtro | mantener | mantener | Filtro anti-sobrecalentamiento sí aplica |

NO aplicado todavía — esperar feedback del usuario antes de tocar ADR 0004. Esto es un hallazgo, no una decisión.

**Limitación del estudio**: HYPE (caso ejemplo del plan, ATH 18-sept-2025) no se pudo validar porque no está en Binance Spot. Requiere fuente alternativa (Bybit klines / Hyperliquid native API perp / Coinbase si listed) — pendiente para iteración futura.

---

## consolidation_breakout — HYPE no es evaluable por el detector

**Fecha**: 2026-05-14
**Backfill ejecutado**: HYPE OHLCV via Hyperliquid `candleSnapshot` desde TGE
**Output**: `data/validation/HYPE-breakout.md` (vacío por diseño)

**Hallazgo**: HYPE TGE = 29-nov-2024. A diciembre-2025 acumula 392 candles diarios = **55 weeks válidas** (valid_days ≥ 5). El detector requiere `MIN_BARS_REQUIRED = 56` (50w baseline ATR + 6w window compresión). Resultado: 0 semanas evaluables.

**Implicaciones**:
1. La validación visual de "HYPE Q3-2025" que pedía el plan original era estructuralmente imposible — el detector requiere baseline histórico que HYPE no tenía durante 2025.
2. Layer 2 ya cubre este caso: regla `LISTING_RECENT < 6m → amber automático` (ADR 0001). HYPE tampoco aplicaría aunque hubiera baseline, porque el archetype `post-tge` tiene `consolidation_applies=False`.
3. Para tokens post-TGE el indicador útil es el delta de holders / smart money / funding z-score, no breakouts técnicos.

**Acción**: ninguna sobre el detector (su strictness aquí es correcta por diseño). Si quisiéramos evaluar HYPE específicamente, habría que esperar a Q3-2026 (TGE + 24m → 100w para BBW decile robusto + 56w mínimo).

---

## FARTCOIN — fuera del scope del detector

**Fecha**: 2026-05-14
**Archetype**: memecoin-brand → `consolidation_applies = False` (ADR 0001).

**Razón**: memecoins no responden a compresión técnica como infra/L1. Mindshare y funding z-score son los signals primarios. Confirmado por diseño del modelo (peso `consolidation_breakout = 0.0` en columna memecoin-brand de archetype_rules).

---

## Validaciones pendientes

- Smart money signal: pendiente validación con keys reales `CI_HELIUS_API_KEY` + `CI_MORALIS_API_KEY`.
- Re-evaluar ZEC/SUI/AAVE con thresholds calibrados crypto (range 30%, atr 0.85, vol 0.7, BBW decile 0.2) cuando se decida aprobar la actualización de ADR 0004.

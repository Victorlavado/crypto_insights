# ADR 0004 — Consolidation breakout: especificación del detector

**Fecha**: 2026-05-10
**Estado**: Aceptado (thresholds tentativos, recalibración Fase 4)
**Supersede**: —
**Origen**: decisión explícita del usuario en brainstorm + refinamientos research deepen-plan

## Contexto

El brainstorm identificó que el patrón "consolidation breakout" aplica al ~60% de los bull runs históricos analizados (12 casos: SOL, ZEC, AAVE, SUI, HYPE, TAO, TIA, JUP, PEPE, WIF, POPCAT, FARTCOIN), específicamente proyectos establecidos con ≥6 meses de historia. NO aplica a memecoins parabólicos ni post-TGE recientes.

El detector debe ser explícito y auditable, sin caja negra, dado que será un signal con peso ~0.25 en archetypes infra-pmf, tesis-macro, l1-maduro, defi-blue-chip.

## Decisión

Detector **semanal** sobre OHLCV diario resampleado a weekly (`pd.resample("W-MON", label="left", closed="left")`). Aplica solo a archetypes con `consolidation_applies=True`.

### 4 condiciones simultáneas (todas requeridas)

1. **Compresión de rango**: `(max_high_6w - min_low_6w) / min_low_6w < 15%` **Y** Bollinger Band Width(20w) en bottom decile vs últimas 100w. Ventana 6 semanas (Q6 confirmado).
2. **ATR contraction (Wilder, RMA)**: `ATR_14w_Wilder / mediana(ATR_14w últimas 50w) < 0.7`. Wilder = `ATR_t = (ATR_{t-1} × 13 + TR_t) / 14`. Estándar TradingView/thinkorswim.
3. **Volumen secándose**: `mean(volume_last_4w) / mean(volume_baseline_20w) < 0.6` **Y** Chaikin Money Flow (CMF, 20w) > 0 (selling pressure se seca).
4. **Breakout con RVOL > 1.5x**: en la semana corriente cerrada, `close > max(close_last_6w_excluding_current)` **Y** `volume_current_week / mean(volume_last_6w) > 1.5`.

### Filtro adicional anti-falso-positivo

**RSI(14w) < 50 durante la fase de compresión**. Evita breakouts desde sobrecalentamiento. Si RSI ≥ 50 en compresión, downgrade `consolidation_breakout` a 0.5 incluso si las 4 condiciones se cumplen.

### Score derivado

- `0.0` si no hay compresión.
- `0.5` si hay compresión pero no breakout (estado "ready").
- `0.5` si las 4 condiciones se cumplen pero RSI ≥ 50 (downgrade).
- `1.0` si las 4 condiciones se cumplen y RSI < 50 (señal completa).

## Look-ahead bias (CRÍTICO)

- Detector opera SOLO sobre velas weekly cerradas.
- Resampleo: `pd.resample("W-MON", label="left", closed="left")` (semana lunes-domingo, cierra domingo 23:59 UTC).
- Backtest y forward-test: `df = df[df.week_end < today]` antes de evaluar. NUNCA evaluar la semana en curso.
- Producción: usar `df.shift(1)` para garantizar que "current week" en condición 4 es la última cerrada.

## Validez de weekly bar

- Descartar bars con <5 días de datos OHLCV no-nulos (`volume > 0`).
- Listings nuevos requieren ≥4 weeks de histórico antes de evaluar.

## Thresholds (tentativos, calibración Fase 4)

Q5 confirmado: empezar con valores propuestos, validar contra HYPE/SOL/ZEC 2024-2025 histórico antes de Fase 3, reweightear via `learnings/signal-performance.md` tras 4-8 semanas de feedback.

| Threshold | Valor inicial | Posibles ajustes |
|---|---|---|
| Range compression | <15% | 12% (estricto) ↔ 18% (laxo) |
| BBW bottom decile | top 10% más bajo / 100w | top 20% si pierde breakouts |
| ATR ratio | <0.7 | 0.6 ↔ 0.8 |
| Volume ratio | <0.6 | 0.5 ↔ 0.7 |
| CMF | >0 | >0.05 (más estricto) |
| RVOL trigger | >1.5× | 1.3× ↔ 2.0× |
| RSI compression | <50 | <55 (laxo) |

## Casos de validación (research)

- **SOL 2023→2024**: consolidación $78-90 mid-2023, breakout Nov-2023, expansión a $200+ Oct-2024. Tiempo compresión-trigger ~6-8w.
- **AAVE 2024**: rising channel, 5+ semanas compresión post-$160, breakout confirmado, ATH $704 vs $328 (+115%).
- **HYPE 2024-2025**: aplica desde "pierna 2" según brainstorm.

## Consecuencias

- **Positivas**: detector explícito, auditable, replicable; cada componente tiene fuente clara (Wilder, BBW Bollinger, CMF Chaikin).
- **Negativas**: 5-7 thresholds = superficie de calibración amplia. Riesgo de overfitting si recalibramos con pocos casos.
- **Riesgo**: false positives típicos (head&shoulders, descending triangle). Mitigación: filtro RSI + cross-check con composite_score completo (no decisión solo por este signal).

## Reglas de evolución

- Cada false positive observado en feedback log se documenta en `learnings/anti-patterns.md`.
- Threshold se ajusta solo tras 3+ casos del mismo error.
- Cambio estructural del detector (añadir/quitar condición) requiere ADR nuevo.

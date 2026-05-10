# ADR 0003 — Hard constraint de unlocks en Layer 2

**Fecha**: 2026-05-10
**Estado**: Aceptado
**Supersede**: —
**Origen**: decisión explícita del usuario en brainstorm + refinamientos research deepen-plan

## Contexto

Layer 2 del modelo de signals (ADR 0001) incluye filtros estructurales para gating de viabilidad. Los unlocks de tokens son uno de los pocos eventos donde el mercado tiene información asimétrica resoluble: las fechas y magnitudes son públicas, y empíricamente el mercado descuenta cliffs grandes 4-8 semanas antes.

Casos validados retrospectivamente (research):
- HYPE: cliff 3.66% el 29-nov-2025; precio cayó -42% en Oct (4-8w previas).
- ARB: cliff ~87% supply el 16-mar-2024; mercado short positions con anticipación.
- APT: cliffs trimestrales ~2%/mes acumulando ~6% en 3 meses.
- SUI: cliff anual 4-5%.

## Decisión

**Hard constraint** que bloquea entrada a un proyecto si:

```
SUM(magnitude_weighted) en eventos con event_date ∈ [today + 4w, today + 8w] >= 5.0%
```

Con:

```
magnitude_weighted = magnitude_pct × category_weight
```

**Pesos por categoría** (Messari best practice):
- `team`: 1.5× (sell pressure esperada ≥70%)
- `investors`: 1.2× (50-70%)
- `treasury / foundation`: 0.8× (governance-dependent)
- `ecosystem / community`: 0.7× (lower sell pressure)
- `unknown`: 1.0× (fallback)

**Suma de cliffs + vesting linear** acumulado dentro de la ventana 4-8w. Cambio respecto al planteamiento inicial (que solo contaba cliffs individuales): si hay un cliff de 3% + vesting linear que acumula 2.5% en la ventana = 5.5% ponderado → bloquea.

**Cálculo de `% circulating`**: `circulating_supply` actual del momento del cálculo (no proyectado), refrescado en cada batch desde CoinGecko `/coins/{id}` (`market_data.circulating_supply`).

**Liberación**: estado `blocked` se libera automáticamente cuando todos los unlocks de la ventana 4-8w pasan (event_date < today). El estado siguiente se recalcula desde scores (puede ser cualquiera de los 6 estados normales).

## Persistencia

`PROJECT_STATE.reason_code = "UNLOCK_INMINENTE"` cuando blocked por esta regla.
`reason_data = {unlock_pct: 11.2, magnitude_weighted: 16.8, days_until: 35, event_date: "2026-06-15", category: "team"}`.
`reason_human = "blocked: HYPE — unlock 11.2% (16.8% ponderado team) el 2026-06-15 (35 días)"`.

## Fuente de datos

**Primaria**: DeFiLlama `/emissions` (PENDIENTE verificación Q11 — puede ser Pro-only).
**Fallback Plan B (si Pro-only)**: scrape HTML público `defillama.com/unlocks/{protocol}` parsing `__NEXT_DATA__` JSON.
**Fallback Plan C**: Tokenomist.ai como primaria.

## Consecuencias

- **Positivas**: regla simple, defendible empíricamente, computable diariamente.
- **Negativas**: bloqueo binario puede perder oportunidades en proyectos sólidos con unlock pequeño bien recibido. Mitigación: solo bloquea entrada nueva; usuario decide si mantiene posición existente (Q4: solo informar).
- **Riesgo**: pesos por categoría son educated guesses (Messari + research). Calibración via `learnings/signal-performance.md` tras 3+ meses de feedback.

## Comportamiento ante posición abierta

`blocked` solo informa (Q4 confirmado). Dashboard muestra "blocked desde día N — razón estructurada". Decisión de salir es del usuario; el MVP no gestiona posiciones.

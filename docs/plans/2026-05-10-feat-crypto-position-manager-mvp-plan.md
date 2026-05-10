---
title: Crypto Position Manager MVP — implementación
type: feat
status: active
date: 2026-05-10
origin: docs/brainstorms/2026-05-09-crypto-tracker-brainstorm.md
related_adrs:
  - docs/decisions/0001-two-layer-signal-model.md
---

# Crypto Position Manager MVP — implementación

## Enhancement Summary (deepened 2026-05-10)

Tras research por 8 agents en paralelo (3 research + 5 review: simplicidad, arquitectura, data-integrity, Python idioms, agent-native parity), el plan se enriquece con:

### Cambios CRÍTICOS bloqueantes (resueltos inline en sus secciones)

1. **`PRAGMA foreign_keys=ON`** debe setearse en cada conexión SQLite (default OFF). Sin esto, el ERD declara FK que SQLite no fuerza.
2. **`payload_schema_version`** en `RAW_SNAPSHOTS` para tolerar evolución upstream.
3. **TaskGroup en lugar de `gather(return_exceptions=True)`** — Python 3.12+ idiom; el segundo silencia `KeyboardInterrupt` y `CancelledError`.
4. **`PROJECT_STATE.reason` debe ser estructurado**: `reason_code` (enum) + `reason_data` (JSON) + `reason_human` (free-text para UI). Sin esto, agent-native parity es imposible.
5. **`PROJECT_STATE_HISTORY` append-only desde día 1** — necesario para validación retrospectiva de Fase 4 y para Open Q4 (ver "blocked desde día N").
6. **UPSERT con `COALESCE`** explícito para no perder datos buenos en re-run parcial: `payload = COALESCE(excluded.payload, payload)`.
7. **Cleanup de batches `running` huérfanos** al iniciar nuevo batch (status=running >2h → marcar failed). Sin esto, un crash abrupto deja status=running para siempre.
8. **Wrapping derived+state per-project en transacción** — sin esto, crash a mitad deja `RAW_SNAPSHOTS` con datos del batch_id pero `DERIVED_SIGNALS`/`PROJECT_STATE` stale.

### Conflicto descubierto (decisión requerida)

**DeFiLlama `/emissions` puede ser Pro-only**, no free. Dos research independientes dieron respuestas contradictorias. Acción: verificar en setup de Fase 1 con request real sin auth. Si es Pro:
- Plan B: scrape DeFiLlama Unlocks public dashboard (HTML estable, frágil).
- Plan C: Tokenomist.ai como primaria (schema documentado, sin API key formal).
- Plan D: presupuesto DeFiLlama Pro ($300/mes) — descartado para MVP.

→ Open Q11 nuevo abierto en `docs/feedback/open-questions/`.

### Trade-offs de simplicidad (NO aplicados sin tu confirmación)

El simplicity reviewer fue brutal y propuso recortes agresivos. Algunos válidos, otros sacrifican opcionalidad futura. Evaluación honesta:

| Recorte propuesto | Mi recomendación | Justificación |
|---|---|---|
| Borrar `AbstractConnector` (8 funciones sueltas) | **Aceptar** | Real: con 8 fuentes heterogéneas (REST/POST/RPC) la abstracción es leaky. Decisión: 8 funciones planas con type alias `Connector = Callable[[Project], Awaitable[SourceSnapshot]]`. |
| Borrar `yoyo-migrations` (single-dev local) | **Rechazar** | Coste de yoyo es ~5min setup. Beneficio: cuando llegue Fase 2-3 y itere schema, no perder histórico. Reseed desde APIs cuesta horas (rate limits). |
| Colapsar Fases 1+2+3 (vertical slice 2 semanas) | **Aceptar parcialmente** | Sí: vertical slice (3 connectors + fusion mínima + Streamlit) en semanas 1-2 antes de signals completos. NO: borrar las fases del plan — son la spec, no el calendario. |
| Quitar mypy strict, hypothesis, coverage 70% | **Rechazar parcial** | Mantener mypy strict en `connectors/` y `signals/indicators.py` (parsing externo + matemática = donde más cazan). Quitar coverage objetivo (vanity metric); quitar hypothesis salvo para indicadores. |
| Borrar tabla `BATCHES` | **Rechazar** | Necesaria para detección de crashes huérfanos y para que dashboard muestre "última actualización: hace X". 1 fila/día = ningún coste. |
| Borrar `vcr.py` | **Aceptar** | Real: cassettes envejecen y mienten. Reemplazar por 3-5 JSONs guardados a mano de respuestas reales. respx-only para tests. |
| `aiolimiter`+`tenacity` overkill (240 req/día) | **Rechazar** | El argumento "240 req/día" ignora backfill OHLCV histórico (~30k requests). Y los rate limits aplican por *segundo*, no por día (Etherscan 5 req/s). Mantener. |
| `DERIVED_SIGNALS` long → wide en `PROJECT_STATE` | **Rechazar** | Wide rompe el modelo histórico (cada nuevo signal = ALTER TABLE pierde historial). Long permite backfill de signals nuevos retroactivamente. |
| `structlog` JSON → `logging` stdlib | **Aceptar parcial** | structlog vale para logs de batch (queryable post-mortem). stdlib `logging` para Streamlit/CLI. |
| `pydantic-settings` + `.env` → `os.environ` | **Rechazar** | 6 keys + paths + URLs justifica validación at-startup. Coste pydantic-settings: 1 archivo `config.py`. |
| `typer` → `argparse` | **Aceptar** | Si el CLI termina con ~5 comandos, argparse zero-dep es defendible. Re-evaluar en Fase 3. |
| Botón "crear feedback" en UI | **Rechazar** | El loop de evolución (`docs/feedback/`) es CRÍTICO al MVP. Friccionar el feedback = mata el mecanismo de mejora. Mantener. |
| `src/` layout → flat | **Rechazar** | Coste de src/: nulo. Beneficio: separación importable/no-importable, evita falsos positivos en tests. Astral lo recomienda. |

**Reducción real aceptada**: ~20-25% LOC, no 45-55%. Tiempo a primer dashboard útil: 12-15 días, no 10.

### Refinamientos técnicos añadidos al plan (research-grounded)

- **Consolidation breakout**: añadir BBW(20) como métrica complementaria al ratio simple, CMF(20w) como detector de "volume drying" más robusto que media simple, filtro adicional **RSI <50 en consolidación**, y umbral de validez de weekly bar (≥5 días con `volume > 0`).
- **Smart money**: pipeline de filtrado en 5 pasos con repos de tagging (`brianleect/etherscan-labels`, `dawsbot/eth-labels`, `tradezon/cex-list`, Dune `labels.addresses`). Solana: resolver `owner` de ATAs y excluir program-owned. Métrica recomendada: **delta ponderado de wallets EOA "smart" filtradas**, no top-50 raw.
- **Unlocks**: ponderar magnitud por categoría (team 1.5×, investors 1.2×, ecosystem 0.7×, treasury 0.8×) — Messari best practice. Sumar cliffs + vesting linear acumulado dentro de la ventana 4-8w.
- **Stack**: `aiolimiter` se usa como `async with`, no decorator. tenacity `@retry` autodetecta coroutines. yoyo soporta SQL puro con bloques `-- rollback:`. Streamlit WAL via SQLAlchemy event listener antes del primer `st.connection`.
- **Agent-native (12 tools MCP-style)**: ver sección nueva "Agent Tools Contract" antes de Implementation Phases.
- **State machine explícita**: matriz de transiciones legales + hysteresis (mín 2 batches en estado nuevo antes de transitar) para evitar flapping. ADR 0005 propuesto.
- **Política de gap (signal=None)**: ADR explícito antes de Fase 3. Recomendación: estado `degraded` separado + renormalización proporcional sobre signals presentes con flag visible.

### Sub-agents que han contribuido a este enhancement

- **Research**: framework-docs (uv/Streamlit/aiolimiter), best-practices (smart money), Explore (consolidation breakout, DeFiLlama unlocks).
- **Review**: code-simplicity, architecture-strategist, data-integrity-guardian, kieran-python, agent-native.

Detalle por sección en bloque **"Research Enhancements"** al final del documento.

---

## Overview

Implementación del MVP descrito en el [brainstorm 2026-05-09](../brainstorms/2026-05-09-crypto-tracker-brainstorm.md): pipeline batch diario que ingiere señales gratuitas para 30 proyectos curados, las normaliza por **archetype** y las expone en un **dashboard Streamlit local** con estado por proyecto (`acumulación / aceleración / distribución / colapso / reset`). Foco: timing de entrada/hold/salida en horizonte swing (semanas–meses), no descubrimiento masivo, no alertas push.

El objetivo del MVP no es generar alfa demostrado en T+0, es **cerrar el loop de feedback** (`docs/feedback/`) con la mínima superficie posible para iterar pesos, thresholds y archetypes desde uso real. Cada decisión se documenta como ADR cuando estructural.

## Problem Statement

El usuario (swing trader, mejores trades documentados: FARTCOIN, HYPE, ZEC) actualmente coordina ~30 posiciones revisando manualmente CT, charts, DeFiLlama y exchanges. Tres problemas concretos:

1. **Sobrecarga cognitiva**: tiempo de revisión escala linealmente con número de proyectos. 30 proyectos × 7-10 fuentes/proyecto = imposible mantener cadencia diaria sin perder señal.
2. **Sesgo de recencia**: la atención va a los proyectos que ya están en TL, no a los que rotan a `acumulación` silenciosamente o entran en `distribución` antes de un top.
3. **Inconsistencia de criterio**: los signals ponderan distinto según archetype (ver ADR 0001) — sin sistema explícito esto se hace "a feeling" y no es auditable post-mortem.

Buy-and-hold pierde dinero en crypto por la estructura de **piernas parabólicas de 2-3 meses separadas por drawdowns 50-70%** (verificado empíricamente con HYPE Q3-Q4 2025: ATH 18-sept, fundamentales pico Q3, primer unlock 2 meses después del top → fundamentales **rezagan** al precio). El position manager debe operar sobre esa estructura, no contra ella.

## Proposed Solution

Sistema de tres componentes:

1. **Connectors (`src/crypto_insights/connectors/`)**: módulos async aislados por fuente, cada uno con su rate limiter y schema normalizado. Una falla aislada no tira el batch.
2. **Pipeline (`src/crypto_insights/pipeline/`)**: orquesta batch diario, persiste snapshots en SQLite, calcula derivadas (deltas, scores, estado por archetype).
3. **Dashboard (`streamlit_app.py`)**: lectura pull-only sobre SQLite, una pestaña por archetype, con badge "última actualización", drill-down por proyecto.

Decisiones arquitectónicas que vienen del brainstorm y se mantienen:

- **Dos capas separadas** (ADR 0001): Layer 2 = filtro de viabilidad (gating, daily refresh suave); Layer 1 = positioning (timing, evaluado cada batch).
- **Reglas explícitas por archetype** (Opción 1 del brainstorm). LLM-reasoner híbrido aplazado.
- **Dashboard pull, no push** (Opción B(i)). Sin telegram, sin email en MVP.
- **Watchlist curada manualmente** (Opción A(i)). Sin auto-discovery.

Decisiones técnicas nuevas (justificadas en research):

- **`uv` con src/ layout y `[dependency-groups]` PEP 735** para reproducibilidad sin Poetry.
- **SQLite WAL + yoyo-migrations** (DuckDB es anti-pattern para inserts diarios single-row; SQLite WAL permite Streamlit leer mientras batch escribe).
- **Streamlit + `st.connection("sql")` + `@st.cache_data(ttl="1h")`** con sentinel `batch_id` como cache key (el cache invalida automáticamente al ver un nuevo batch).
- **`aiolimiter` + `tenacity`** como capa transversal de rate limiting + retry con jitter.
- **Indicadores TA calculados a mano** (ATR Wilder, Bollinger Width, RVOL son <10 LoC cada uno; auditables, sin dependencia frágil).
- **Windows Task Scheduler** ejecuta `uv run crypto-insights batch-daily` (más Unix-philosophy que APScheduler para batch idempotente que reinicia limpio).

## Technical Approach

### Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                      WINDOWS TASK SCHEDULER                       │
│              uv run crypto-insights batch-daily                   │
└────────────────────────┬─────────────────────────────────────────┘
                         │ (1× día, idempotente por fecha)
                         ▼
┌──────────────────────────────────────────────────────────────────┐
│                          PIPELINE                                 │
│  ┌────────────┐    ┌────────────┐    ┌────────────────────────┐  │
│  │ load       │ →  │ fetch all  │ →  │ compute derived        │  │
│  │ watchlist  │    │ connectors │    │ (deltas, indicators,    │  │
│  │            │    │ (parallel) │    │  archetype scores)     │  │
│  └────────────┘    └────────────┘    └────────────────────────┘  │
│                          │                       │                │
│                          ▼                       ▼                │
│              ┌─────────────────────┐  ┌──────────────────────┐   │
│              │ raw_snapshots tbl   │  │ project_state tbl     │   │
│              │ (1 row per src/day) │  │ (1 row per project)   │   │
│              └─────────────────────┘  └──────────────────────┘   │
└──────────────────────┬────────┬─────────────────────────────────┘
                       │        │
                       ▼        ▼
                  ┌──────────────────┐
                  │ SQLite (WAL)     │
                  │ data/crypto.db   │
                  └────────┬─────────┘
                           │ (read-only via st.connection)
                           ▼
              ┌──────────────────────────┐
              │ STREAMLIT (local)        │
              │ streamlit_app.py         │
              │ - tab por archetype       │
              │ - drill-down por proyecto │
              │ - badge "hace X horas"   │
              └──────────────────────────┘
```

**Principio de aislamiento**: cada connector es un módulo independiente con interfaz `async def fetch(project: Project) -> SourceSnapshot`. La pipeline los lanza con `asyncio.gather(..., return_exceptions=True)` y persiste lo que llegue; lo que falle se loggea y se reintenta en el siguiente batch.

**Principio de idempotencia**: `batch-daily` con `--date YYYY-MM-DD` debe ser re-ejecutable sin duplicar filas (UPSERT por `(project_id, source, date)`).

### Stack confirmado

| Capa | Elección | Por qué |
|---|---|---|
| Lenguaje / runtime | Python 3.12+ | Type hints maduros, asyncio sólido |
| Project mgmt | **uv** + src/ layout | Lock reproducible, PEP 735 dep groups, sin Poetry |
| HTTP async | **httpx** | Único cliente async maduro con HTTP/2 y retry hooks |
| Rate limiting | **aiolimiter** (leaky bucket, 1 limiter/host) | Más estricto que token bucket para APIs sensibles a burst |
| Retry | **tenacity** con `wait_exponential_jitter` | Evita thundering herd cuando varios endpoints fallan |
| Storage | **SQLite WAL** + **yoyo-migrations** | 30 proyectos × 5 años × 10 signals ≈ 550k filas — SQLite sobra; WAL deja Streamlit leer durante batch |
| TA / matemáticas | **pandas** + **numpy** (indicadores a mano) | Auditable, sin opacidad, fórmulas simples |
| Dashboard | **Streamlit** + `st.connection("sql")` + `@st.cache_data` | Iteración rápida; cache con sentinel `batch_id` invalida al ver nuevo batch |
| Logging | **structlog** (JSON a archivo) | Queryable post-mortem cuando una fuente da rare error |
| Tests | **pytest** + **respx** (unit) + **vcr.py/pytest-recording** (integration) + **hypothesis** (acotado a indicadores) | VCR captura quirks reales de APIs |
| Lint / format | **ruff** (linter + formatter) | Una herramienta, configuración mínima |
| Type check | **mypy** strict en `connectors/` y `pipeline/`, suelto en `streamlit_app.py` | Beneficio mayor donde más fallan los tipos (parsing externo) |
| Scheduling | **Windows Task Scheduler** ejecuta `uv run crypto-insights batch-daily` | Stateless, OS-managed, sobrevive reboots |

### Estructura de directorios

```
crypto_insights/
├── pyproject.toml                       # uv + dep groups
├── uv.lock
├── streamlit_app.py                     # entry point dashboard
├── README.md
├── PLAN.md                              # documento vivo (existe)
├── data/
│   ├── watchlist.example.yaml           # template (existe, 26 proyectos hoy)
│   ├── watchlist.yaml                   # gitignored (real, 30 proyectos)
│   ├── crypto.db                        # SQLite (gitignored)
│   └── cassettes/                       # vcr fixtures (gitignored)
├── docs/
│   ├── brainstorms/                     # (existe)
│   ├── decisions/                       # ADRs (existe)
│   ├── feedback/                        # log diario (existe)
│   ├── learnings/                       # destilado (existe)
│   ├── plans/                           # este archivo (existe)
│   └── feedback/open-questions/         # NUEVO — preguntas abiertas del plan a Victor
├── migrations/                          # yoyo SQL files
│   ├── 0001-initial-schema.sql
│   ├── 0002-add-...
│   └── ...
├── src/crypto_insights/
│   ├── __init__.py
│   ├── cli.py                           # typer entry: batch-daily, init-db, etc.
│   ├── config.py                        # pydantic-settings, .env, paths
│   ├── models.py                        # dataclasses: Project, Snapshot, Signal
│   ├── archetypes.py                    # definición y reglas por archetype
│   ├── connectors/
│   │   ├── __init__.py
│   │   ├── base.py                      # AbstractConnector, RateLimiter wrapper
│   │   ├── binance.py                   # OHLCV
│   │   ├── coingecko.py                 # market data, fallback OHLC
│   │   ├── defillama.py                 # fees, TVL, volume
│   │   ├── defillama_unlocks.py         # /emissions endpoint
│   │   ├── hyperliquid.py               # funding/OI
│   │   ├── github.py                    # commits, contributors
│   │   ├── etherscan.py                 # ETH balances/tx (NO holders)
│   │   ├── helius.py                    # Solana top holders DAS
│   │   └── moralis.py                   # ETH top holders [PENDIENTE: ver Open Q1]
│   ├── pipeline/
│   │   ├── __init__.py
│   │   ├── batch.py                     # orquestador
│   │   ├── persist.py                   # UPSERT helpers
│   │   └── derived.py                   # cálculo de deltas, scores
│   ├── signals/
│   │   ├── __init__.py
│   │   ├── indicators.py                # ATR, BB Width, RVOL, range compression
│   │   ├── consolidation_breakout.py    # detector semanal (4 criterios)
│   │   ├── unlocks.py                   # hard constraint Layer 2
│   │   ├── smart_money.py               # delta top holders
│   │   ├── mindshare.py                 # [PENDIENTE: ver Open Q2]
│   │   ├── funding.py
│   │   └── netflows.py                  # [PENDIENTE: ver Open Q3]
│   ├── fusion/
│   │   ├── __init__.py
│   │   ├── layer2.py                    # filtro viabilidad
│   │   ├── layer1.py                    # positioning score
│   │   └── archetype_rules.py           # pesos hardcoded por archetype
│   └── dashboard/
│       ├── __init__.py
│       ├── components.py                # cards, tablas, sparklines
│       └── views.py                     # tabs por archetype
├── tests/
│   ├── unit/
│   │   ├── test_indicators.py           # hypothesis-based
│   │   ├── test_consolidation_breakout.py
│   │   ├── test_archetype_rules.py
│   │   └── connectors/                  # respx-based
│   ├── integration/
│   │   └── test_connectors_vcr.py       # vcr fixtures, replay
│   └── fixtures/
│       └── ohlcv_hype_2025.csv
└── .claude/
    └── settings.local.json              # (existe)
```

### Modelo de datos

```mermaid
erDiagram
    PROJECTS ||--o{ RAW_SNAPSHOTS : has
    PROJECTS ||--o{ DERIVED_SIGNALS : has
    PROJECTS ||--|| PROJECT_STATE : has
    PROJECTS ||--o{ PROJECT_STATE_HISTORY : has
    PROJECTS ||--o{ EVENTS : has
    BATCHES ||--o{ RAW_SNAPSHOTS : produces
    BATCHES ||--o{ DERIVED_SIGNALS : produces
    BATCHES ||--o{ PROJECT_STATE_HISTORY : produces

    PROJECTS {
        int id PK
        text symbol UK "UNIQUE; PK numérica para tolerar rebrand"
        text coingecko_id
        text archetype
        text chain
        text contract
        text notes
        timestamp added_at
    }
    BATCHES {
        text batch_id PK "YYYY-MM-DD"
        timestamp started_at
        timestamp heartbeat_at "actualizado cada ~30s durante run"
        timestamp finished_at
        text status "running|complete|partial|failed"
        json error_summary "{sources_failed: [{source, project, error}]}"
    }
    RAW_SNAPSHOTS {
        int id PK
        int project_id FK
        text source "binance|defillama|hyperliquid|..."
        text batch_id FK
        date snapshot_date
        json payload
        int payload_schema_version "default 1; bump al cambiar normalización"
        text connector_version "v0.1.0 git sha o semver"
        timestamp fetched_at
        UNIQUE "(project_id, source, snapshot_date)"
    }
    DERIVED_SIGNALS {
        int id PK
        int project_id FK
        text batch_id FK
        date signal_date
        text signal_name "atr_pct, rvol, holders_delta_7d, ..."
        real value
        text formula_version "v1; bump al cambiar fórmula del indicador"
        UNIQUE "(project_id, signal_name, signal_date, formula_version)"
    }
    PROJECT_STATE {
        int project_id PK FK
        text current_state "acumulacion|aceleracion|distribucion|colapso|reset|blocked|degraded|unknown"
        real composite_score "expuesto como columna real, no solo en JSON"
        text reason_code "UNLOCK_INMINENTE|DEV_ABANDONED|TVL_COLLAPSE|LISTING_RECENT|GAP_DATOS|NORMAL"
        json reason_data "estructurado: {unlock_pct, days_until, ...}"
        text reason_human "free-text para UI"
        text layer2_flag "green|amber|red"
        json layer1_scores
        int batches_in_state "hysteresis counter"
        text batch_id FK
        timestamp updated_at
    }
    PROJECT_STATE_HISTORY {
        int id PK
        int project_id FK
        text batch_id FK
        text state
        real composite_score
        text reason_code
        json reason_data
        text layer2_flag
        timestamp recorded_at
        UNIQUE "(project_id, batch_id)"
    }
    EVENTS {
        int id PK
        int project_id FK
        text event_type "unlock|listing|halving|fork|..."
        date event_date
        real magnitude_pct "si es unlock: % de circulating"
        text allocation_category "team|investors|ecosystem|foundation|public"
        real magnitude_weighted "magnitude_pct * category_weight"
        text source
        text external_event_id "deduplicador desde DeFiLlama"
        text notes
        UNIQUE "(project_id, event_type, event_date, external_event_id)"
    }
```

**Notas de schema (incluye fixes críticos del review)**:

- **`PRAGMA foreign_keys=ON`** debe ejecutarse en CADA conexión (default OFF en SQLite). Setear en `init-db`, en el connection wrapper de pipeline, y en el SQLAlchemy event listener de Streamlit (junto al PRAGMA WAL).
- **`PROJECTS.id` numérica** + `UNIQUE(symbol)`: tolera rebrand (MATIC→POL, FTM→S) sin perder histórico. Todas las FK son por `project_id` integer.
- **`RAW_SNAPSHOTS.payload` JSON crudo + `payload_schema_version`**: preservar lo que devuelve la fuente, normalizar al leer en `derived`. Bumpear `payload_schema_version` cuando cambia normalización; permite re-procesar histórico distinguiendo formatos.
- **`DERIVED_SIGNALS.formula_version`** en PK compuesta: re-correr batch tras cambiar fórmula NO sobrescribe el cálculo viejo. Reproducibilidad para backtest visual.
- **`PROJECT_STATE.reason_code` enum + `reason_data` JSON + `reason_human`**: estructurado para agente, free-text para humano. Sin esto, agent-native parity es imposible (free-text no es razonable por LLM). Lista enum cerrada (extensible vía migration).
- **`PROJECT_STATE.composite_score` columna real**: agente puede filtrar por umbral propio (ej. "borderline aceleración entre 0.4 y 0.6") sin parsear JSON.
- **`PROJECT_STATE.batches_in_state`** counter para hysteresis: requiere mín 2 batches en estado nuevo antes de transitar (anti-flapping). Reseteable.
- **`PROJECT_STATE_HISTORY` append-only desde día 1** (no future considerations): necesario para validación retrospectiva de Fase 4 ("¿qué decía el dashboard ayer?") y para mostrar "blocked desde día N" (Open Q4).
- **`BATCHES.heartbeat_at`** + `error_summary` JSON: detección de batches `running` huérfanos al iniciar nuevo (>2h sin heartbeat → marcar `failed`); error_summary estructurado para CLI consumption.
- **`EVENTS.allocation_category` + `magnitude_weighted`**: ponderación Messari (team 1.5×, investors 1.2×, ecosystem 0.7×, treasury 0.8×). Hard constraint usa `magnitude_weighted` cuando categoría disponible, fallback a `magnitude_pct` cuando no.
- **`EVENTS.external_event_id`** para deduplicar fetches (mismo cliff puede aparecer múltiples veces en re-runs si DeFiLlama incluye el id).

**Índices secundarios obligatorios** (faltaban en el plan original):

```sql
CREATE INDEX idx_derived_lookup ON derived_signals(project_id, signal_name, signal_date DESC);
CREATE INDEX idx_derived_batch ON derived_signals(batch_id);
CREATE INDEX idx_raw_lookup ON raw_snapshots(project_id, source, snapshot_date DESC);
CREATE INDEX idx_state_history_project ON project_state_history(project_id, recorded_at DESC);
CREATE INDEX idx_events_window ON events(event_date, event_type) WHERE event_date > date('now');
```

Sin esos, queries del dashboard (sparkline 12 weeks de signal X para proyecto Y) van a full-scan.

### Pipeline batch diario

Pseudo-flujo (`src/crypto_insights/pipeline/batch.py`) — **incorpora fixes críticos del review**:

```python
# pseudocódigo, no implementar aquí
async def run_batch(date: date) -> BatchResult:
    batch_id = date.isoformat()

    # Cleanup huérfanos: batches con status=running y heartbeat >2h → failed
    cleanup_orphan_batches(stale_threshold=timedelta(hours=2))
    register_batch_started(batch_id)

    projects = load_watchlist()
    connectors = build_connectors()  # con rate limiters por host

    # Fan-out con TaskGroup (Python 3.12+) — captura excepciones por task
    # NO usar gather(return_exceptions=True): silencia KeyboardInterrupt y CancelledError
    async def _safe_fetch(c, p) -> ConnectorResult:
        try:
            return ConnectorResult.ok(await c.fetch(p))
        except ConnectorError as e:
            log.warning("connector_failed", source=c.source, project=p.symbol, error=str(e))
            return ConnectorResult.failed(c.source, p, e)

    async with asyncio.TaskGroup() as tg:
        # Heartbeat task corriendo cada 30s en background
        tg.create_task(_heartbeat_loop(batch_id))
        tasks = [
            tg.create_task(_safe_fetch(c, p))
            for p in projects
            for c in connectors
            if c.supports_project(p)  # encapsulado en connector, no leak a pipeline
        ]
    results = [t.result() for t in tasks]

    # Persistir lo que llegó. UPSERT con COALESCE: NO sobrescribir datos buenos con NULL
    # SQL: INSERT ... ON CONFLICT DO UPDATE SET payload = COALESCE(excluded.payload, payload)
    for r in results:
        if r.is_ok:
            upsert_raw_snapshot_coalesce(r.snapshot, batch_id)

    # Computar derivadas y estado: per-project en transacción
    # Garantiza que si el proceso muere a mitad, el proyecto N+1 no queda con derived stale
    for project in projects:
        with conn.begin():  # transacción explícita per-project
            derived = compute_derived_signals(project, batch_id)
            persist_derived(derived)
            new_state = compute_project_state(project, batch_id)
            apply_state_with_hysteresis(project, new_state, batch_id)  # min 2 batches
            append_to_state_history(project, batch_id)

    # Marcar status final SOLO al terminar el último proyecto correctamente
    register_batch_finished(
        batch_id,
        status="complete" if all_sources_ok(results) else "partial",
        error_summary=summarize_failures(results)
    )
```

**Características clave**:

- **Idempotente por `batch_id`**: re-correrlo el mismo día sobrescribe (`UPSERT con COALESCE`), no duplica ni sobrescribe con NULLs.
- **Tolerante a fallos parciales**: una API caída no tira el batch; queda como gap en `RAW_SNAPSHOTS` y la fusión la trata según política de gap (estado `degraded` separado, ver Research Enhancements).
- **Detección de crashes abruptos**: `heartbeat_at` actualizado cada 30s permite que el siguiente batch detecte runs huérfanos (proceso muerto sin chance de actualizar `status='failed'`).
- **Consistencia per-project**: transacción wrapping `derived + state + history` por proyecto. Crash deja N proyectos consistentes y M no actualizados, nunca proyecto en estado intermedio.
- **Observabilidad estructurada**: `BATCHES.error_summary` JSON permite que CLI/dashboard muestre `{sources_failed: [{source: "helius", project: "GRASS", error: "rate_limit"}]}` y que un agente lo procese sin parsear texto.
- **State machine con hysteresis**: `apply_state_with_hysteresis` requiere mín 2 batches consecutivos en el nuevo estado antes de transitar. Anti-flapping en boundaries de score.

### Conectores por fuente — limits y fallbacks

Tabla de fuentes con limits 2026 (ver Sources al final). **Fallbacks marcados** son el orden de elección si la fuente primaria falla:

| Connector | Endpoint base | Auth | Free limit | Usado para | Fallback |
|---|---|---|---|---|---|
| `binance` | `api.binance.com/api/v3/klines` | No | 6000 weight/min IP | OHLCV diario completo histórico | `coingecko.ohlc` (degraded, daily candles solo) |
| `coingecko` | `api.coingecko.com/api/v3` | Demo header | 30 req/min, **10k req/MES** | Market cap, circulating supply, holders count público | — |
| `defillama` | `api.llama.fi`, `coins.llama.fi` | No | Sin cap documentado | Fees, TVL, volume por protocolo | — |
| `defillama_unlocks` | `api.llama.fi/emissions` | No | Sin cap documentado | Unlocks futuros (alimenta `EVENTS`) | Tokenomist scrape (frágil) |
| `hyperliquid` | `api.hyperliquid.xyz/info` (POST) | No | 1200 req/min REST | Funding, OI, mark price | Binance USDM funding (perp tokens listados) |
| `github` | `api.github.com` | PAT | 5000 req/h auth | Commits/contributors último 30/90d | — |
| `helius` | `mainnet.helius-rpc.com` (DAS) | API key free | 1M créditos/mes | Top holders SPL tokens (Solana) | Bitquery free GraphQL |
| `moralis` o `alchemy` | varía | API key free | Moralis ~25k CU/día; Alchemy 300M CU/mes | Top holders ERC20 (Ethereum/Base) | Etherscan UI scrape (frágil, ToS-borderline) |
| `etherscan_v2` | `api.etherscan.io/v2/api` | API key | 5 req/s, 100k/día | Tx counts, balances (NO holders) | — |
| _mindshare_ | **ABIERTO** — ver Open Q2 | — | — | Mindshare/social attention | — |
| _netflows_ | **ABIERTO** — ver Open Q3 | — | — | CEX netflows (BTC, ETH, stables) | — |

**Cambios respecto al brainstorm que requieren validación de Victor**:

1. El brainstorm asumía Etherscan/Solscan como fuente de top holders. **Etherscan free no expone top holders por contrato** (sale del UI; endpoint Pro Account API requiere paid). **Solscan free** lo expone con rate limit agresivo. Recomendación: Helius (Solana) + Moralis o Alchemy (ETH/Base). → Open Q1.
2. **Kaito no tiene free API en 2026**. Scrape directo bloqueado por Cloudflare. → Open Q2.
3. **CryptoQuant netflows requiere paid**. → Open Q3.

### Layer 2 — Filtro de viabilidad (con hard constraint de unlocks)

Layer 2 produce un flag `green / amber / red / blocked` por proyecto, refrescado cada batch. **No** decide timing (eso es Layer 1) — decide si el proyecto es elegible.

**Reglas (versión inicial, todas reweightables vía `learnings/archetype-rules.md`)**:

| Regla | Threshold inicial | Acción |
|---|---|---|
| **Unlock próximo (HARD CONSTRAINT)** — confirmado por Victor | Unlock ≥ **5%** del circulating supply en próximas **4-8 semanas** | `blocked` (override de cualquier signal de Layer 1) |
| Dev abandonado | <5 commits últimos 90 días Y <2 contributors activos | `red` (descartar como zombie) |
| TVL/Fees colapsando | TVL drop >70% desde ATH últimos 12m **y** fees -50% últimos 90d | `amber` (revisar manualmente si tesis sigue válida) |
| Listing reciente (post-TGE) | <6 meses desde TGE | `amber` automático (no aplican consolidation breakout ni mucho histórico) |
| Default | — | `green` |

**Detalles de la hard constraint de unlocks** (decisión del usuario, prioritaria — **REFINADO con research**):

- **Fuente primaria a verificar (ver Open Q11)**: DeFiLlama `/emissions` puede ser Pro-only ($300/mes). Fallback open: **Tokenomist.ai** (schema documentado, sin API formal — scrape semanal). Si Pro confirmado: scrape del HTML público de `defillama.com/unlocks` como Plan B.
- **Magnitud ponderada por categoría** (Messari best practice): `magnitude_weighted = magnitude_pct × category_weight`.
  - `team`: 1.5× (sell pressure esperada ≥70%)
  - `investors`: 1.2× (50-70%)
  - `treasury/foundation`: 0.8× (governance-dependent)
  - `ecosystem/community`: 0.7× (lower sell pressure)
  - `unknown`: 1.0× (fallback)
- **Suma de cliffs + vesting linear acumulado** dentro de la ventana 4-8w. Cambio respecto al planteamiento inicial: si hay un cliff de 3% + vesting linear que acumula 2.5% en la ventana = 5.5% ponderado → bloquea. Antes solo se evaluaban cliffs individuales.
- Ventana **4-8 semanas hacia adelante** desde la fecha del batch (validado empírico por Messari + IntoTheBlock para anticipación de descuento de mercado).
- **Cálculo de `% circulating`**: usa el `circulating_supply` actual del momento del cálculo (no proyectado), refrescado en cada batch desde CoinGecko `/coins/{id}` (campo `market_data.circulating_supply`).
- **`reason_code`** = `UNLOCK_INMINENTE`. **`reason_data`** = `{unlock_pct: 11.2, magnitude_weighted: 16.8, days_until: 35, event_date: "2026-06-15", category: "team"}`. **`reason_human`** = `"blocked: HYPE — unlock 11.2% (16.8% ponderado team) el 2026-06-15 (35 días)"`.

**Casos validados retrospectivamente** (research):

| Proyecto | Evento | Magnitud | Categoría | Activación esperada | Resultado |
|---|---|---|---|---|---|
| HYPE | Cliff 29-nov-2025 | 3.66% | team | 4-8w previas (Oct 1 → Nov 1) | precio cayó 42% en Oct ✓ |
| ARB | Cliff 16-mar-2024 | ~87% (gigante) | team+investors+DAO | siempre activado | mercado short positions ✓ |
| APT | Cliffs trimestrales | ~2%/mes | foundation+investors | cumulative ~6% en 3m | parcial ✓ |
| SUI | Cliff anual | 4-5% | foundation | activado | ✓ |

→ **Open Q4**: ¿qué hacer si proyecto en `blocked` pero ya tienes posición abierta? El MVP no gestiona posiciones; el dashboard debe simplemente avisar "blocked desde día N", la decisión de salida sigue siendo del usuario. Confirmar.

### Layer 1 — Positioning signals

Layer 1 calcula scores por signal y los fusiona por archetype (sección siguiente). Signals listadas:

#### Signal 1: Consolidation breakout (especificado por Victor)

Detector **semanal** sobre OHLCV diario (resampleado a weekly), aplica solo a archetypes con `consolidation_applies = True` (infra-pmf, tesis-macro, l1-maduro, defi-blue-chip — ver tabla del brainstorm).

**4 condiciones simultáneas** para emitir señal de breakout (todas requeridas, todas en weekly **cerradas** — ver look-ahead bias abajo):

1. **Compresión de rango**: `(max_high_6w - min_low_6w) / min_low_6w < threshold_pct`. Threshold inicial **15%** (ver Open Q5). **Ventana = 6 semanas** (decisión Q6: más sensible que 8w default; captura compresiones cortas típicas en crypto). **Refinamiento research**: complementar con **Bollinger Band Width(20w)** alcanzando mínimo histórico (cerca de bottom decile vs últimas 100w) — más estadísticamente robusto que ratio simple. Implementar AMBAS métricas; trigger requiere AMBAS por debajo de threshold.
2. **ATR contraction (Wilder, no SMA)**: `ATR_14w_Wilder / mediana(ATR_14w últimas 50w) < 0.7`. Wilder = RMA recursivo: `ATR_t = (ATR_{t-1} × 13 + TR_t) / 14`. Estándar de TradingView/thinkorswim para swing trading.
3. **Volumen secándose**: `mean(volume_last_4w) / mean(volume_baseline_20w) < 0.6`. **Refinamiento research**: complementar con **Chaikin Money Flow (CMF, 20w) > 0** (selling pressure se seca). CMF detecta mejor "volume drying up" porque pondera por close position en el rango. Implementar ambas; trigger requiere mean ratio < 0.6 Y CMF > 0.
4. **Breakout con RVOL > 1.5x**: en la semana corriente cerrada, `close > max(close_last_6w_excluding_current)` **Y** `volume_current_week / mean(volume_last_6w) > 1.5`.

**Filtro adicional anti-falso-positivo (research)**: **RSI(14w) < 50 durante la fase de compresión**. Evita breakouts desde sobrecalentamiento (que típicamente fallan). Si RSI ≥ 50 en las semanas de compresión, downgrade `consolidation_breakout` a 0.5 incluso si las 4 condiciones se cumplen.

Las 3 primeras condiciones son **estado de compresión**; la 4ª es el **trigger**. Detector emite `consolidation_breakout = True` solo cuando se da la combinación.

**Look-ahead bias (CRÍTICO)**: el detector debe operar SOLO sobre **velas weekly cerradas**. Convención implementación:
- Resamplear daily → weekly con `pd.resample("W-MON", label="left", closed="left")` (semana lunes-domingo, cierra domingo 23:59 UTC).
- En backtest y forward-test: `df = df[df.week_end < today]` antes de evaluar. Nunca evaluar la semana en curso.
- Usar `df.shift(1)` en producción para garantizar que el "current week" en condición 4 es la última cerrada.

**Validación de weekly bar**: descartar bars con <5 días de datos OHLCV no-nulos (`volume > 0`). Listings nuevos requieren ≥4 weeks de histórico antes de evaluar. Esto interactúa con `EVENTS.event_type='listing'` para excluir proyectos recién listados de la evaluación.

**Score derivado** (`signal_value` en `DERIVED_SIGNALS`):
- `0.0` si no hay compresión
- `0.5` si hay compresión pero no breakout (estado "ready")
- `1.0` si breakout confirmado en la semana corriente

→ **Open Q5**: thresholds (15%, 0.7, 0.6, 1.5x) son educated guesses iniciales. Recomendación: comenzar con esos valores y reweightear via `learnings/signal-performance.md` después de 4-8 semanas de feedback. Confirmar.

→ **Open Q6**: ventana de 8 semanas para "rango" — ¿es la correcta para swing trading 2-3 meses? Alternativas: 6w (más sensible), 12w (más selectivo). Recomendación: empezar 8w.

#### Signal 2: Smart money (delta filtrado de wallets EOA, **REFINADO con research**)

El signal NO es "delta top-50 raw" — eso incluye CEX hot wallets, DEX programs, bridges, vesting contracts y rompe la señal. Pipeline correcto en 5 pasos:

1. **Pull top 100 holders** (no 50; necesitas margen para filtrado). Helius (Solana DAS) o Alchemy/Moralis (EVM) según chain.
2. **Resolve owners (Solana específico)**: top accounts retornados por `getTokenLargestAccounts` son **token accounts (ATAs)**, no wallets. Para cada ATA, leer `owner` field. Excluir ATAs cuyo owner sea un **program ID** (Raydium AMM, Orca whirlpool, Jupiter, Kamino, Marinade) — son liquidity pools, no holders. Agregar por owner real, no por ATA address.
3. **Tagging contra repos curados** (descargados como CSV/JSON al inicializar):
   - `brianleect/etherscan-labels` — dump completo Etherscan label cloud (EVM)
   - `dawsbot/eth-labels` — dataset público mantenido
   - `tradezon/cex-list` — CEX hot wallets (incluye Solana)
   - Dune `labels.addresses` (descarga vía CSV API): bridges, DEX programs
   Excluir cualquier holder etiquetado: CEX, DEX, bridge, vesting, treasury del proyecto.
4. **Filtrado heurístico (EVM)** para holders no taggeados:
   - `eth_getCode(address) != "0x"` → contract → excluir por defecto (salvo whitelist de safes legítimos)
   - >500 tx/día sostenidas + ratio in/out ~1.0 + montos round (0.1, 1, 10 ETH) → "exchange-like" → excluir
   - Edad de wallet <180 días → excluir (filtro Nansen-style "smart money")
   - Top-1 holder si concentra >15% supply → excluir (típicamente team/treasury, rompe el signal)
5. **Cálculo del signal** sobre los ~30-50 supervivientes "EOA-like":
   ```
   smart_money_delta_7d = Σ(Δbalance_i × weight_i) / circulating_supply × 100
   ```
   donde `weight_i = 1` si EOA pasa los filtros, `0` si no.

**Threshold empírico (research)**: `|smart_money_delta_7d| > 2.5%` es la zona donde el signal supera ruido. <1% es ruido. >10% suele ser unlock/listing event (no signal genuino — cross-check con `EVENTS`).

**Cooldown de 48h**: no emitir signal nuevo si el anterior fue <48h. Anti-flapping en eventos puntuales.

**Casos validados** (research): HYPE 2024-2025 (whale acumulación >5% en 14d precedió breakout >$30); PEPE/POPCAT/BONK 2025 (Nansen Smart Money filter mostró acumulación 4+ semanas antes de runs); SOL Q4 2024 (outflows Binance + acumulación funds precedieron $140→$240).

**`data/excluded_addresses.yaml`** se popula desde repos arriba al inicializar; mantener un manual override file `data/excluded_addresses_manual.yaml` para casos descubiertos en feedback (`docs/feedback/`).

#### Signal 3: Funding rates

- Hyperliquid primaria. Fallback Binance USDM para tokens no listados en HL.
- `funding_zscore_30d` = z-score del funding actual contra distribución últimos 30 días.
- Funding extremo positivo (z > +2) → señal de distribución (mercado over-leveraged long).
- Funding extremo negativo (z < -2) → señal contrarian de acumulación (capitulation longs).

#### Signal 4: CEX netflows (PENDIENTE — ver Open Q3)

- Si se resuelve: outflows sostenidos = acumulación; inflows = distribución.

#### Signal 5: Mindshare (PENDIENTE — ver Open Q2)

- Si se resuelve: velocidad de cambio en attention vía Kaito o equivalente.

#### Signal 6: TVL trend (defi blue chips)

- DeFiLlama. `tvl_30d_change_pct`. Aplica solo a `defi-blue-chip`.

#### Signal 7: DEX volume / Stablecoin growth (l1-maduro)

- DeFiLlama. Aplica solo a `l1-maduro`.

### Fusión por archetype

Tabla de pesos inicial (refleja la del brainstorm). **Suma 1.0 dentro de cada archetype**. Los signals con peso 0 no se evalúan para ese archetype.

| Signal | memecoin-brand | infra-pmf | tesis-macro | l1-maduro | defi-blue-chip | post-tge |
|---|---|---|---|---|---|---|
| Consolidation breakout | 0.0 | 0.25 | 0.25 | 0.25 | 0.25 | 0.0 |
| Smart money delta | 0.40 | 0.20 | 0.20 | 0.20 | 0.20 | 0.30 |
| Funding z-score | 0.20 | 0.20 | 0.10 | 0.15 | 0.10 | 0.20 |
| Mindshare velocity | 0.40 | 0.10 | 0.20 | 0.05 | 0.05 | 0.50 |
| CEX netflows | 0.0 | 0.10 | 0.10 | 0.15 | 0.10 | 0.0 |
| TVL/Fees trend | 0.0 | 0.15 | 0.0 | 0.0 | 0.20 | 0.0 |
| Stablecoin/DEX growth | 0.0 | 0.0 | 0.0 | 0.20 | 0.0 | 0.0 |
| Holder growth | 0.0 | 0.0 | 0.15 | 0.0 | 0.10 | 0.0 |

**Output**: `PROJECT_STATE.layer1_scores` es JSON con cada signal, su valor normalizado y peso. `current_state` se calcula con función `state_from_scores()` que aplica reglas del tipo:

- `composite_score > 0.6` y consolidation_breakout=1.0 → `aceleracion`
- `composite_score > 0.3` con smart_money positivo y mindshare creciendo → `acumulacion`
- `composite_score < -0.3` con funding extremo positivo y smart_money negativo → `distribucion`
- `composite_score < -0.6` → `colapso`
- abs(composite_score) < 0.2 después de un colapso → `reset`
- override `blocked` si Layer 2 lo dice

→ **Open Q7**: thresholds de estado son tentativos. Necesario calibrar contra histórico (ZEC, HYPE, FARTCOIN) antes de usar para decisiones reales. Forma sugerida: en Fase 4 generar `derived_signals` retroactivos sobre 2024-2025 y validar visualmente.

### Streamlit dashboard

**Layout**:

```
┌─────────────────────────────────────────────────────────────────┐
│  Crypto Position Manager                                         │
│  Última actualización: hace 3h (batch 2026-05-10, 28/30 OK)     │
├─────────────────────────────────────────────────────────────────┤
│ [ infra-pmf ] [ tesis-macro ] [ l1-maduro ] [ defi-blue-chip ]  │
│ [ memecoin-brand ] [ post-tge ] [ blocked ⚠ ]                    │
├─────────────────────────────────────────────────────────────────┤
│  ┌────────┬──────┬──────┬─────┬──────┬─────────┬──────────┐    │
│  │Symbol  │State │Score │ATR% │Funds │Holders  │Próx unlock│    │
│  ├────────┼──────┼──────┼─────┼──────┼─────────┼──────────┤    │
│  │HYPE    │acel. │+0.72 │8.1% │+1.2σ │+0.4%/7d │ 78d 11%   │    │
│  │  ↳ click row → drill-down                                │    │
│  └────────┴──────┴──────┴─────┴──────┴─────────┴──────────┘    │
├─────────────────────────────────────────────────────────────────┤
│  Drill-down HYPE:                                                │
│  - sparkline OHLCV 12 semanas + zonas de consolidación marcadas │
│  - timeline eventos (unlocks, listings)                          │
│  - tabla raw_snapshots últimas 4 fetches                        │
│  - link a `docs/feedback/2026-05-10-1.md` (crear desde UI)      │
└─────────────────────────────────────────────────────────────────┘
```

**Detalles técnicos**:

- `st.connection("sql", url="sqlite:///data/crypto.db")` con WAL → reads no bloquean batch.
- `@st.cache_data(ttl="1h")` en queries pesadas, **con `batch_id` como argumento** → al detectar nuevo batch_id, miss automático.
- Badge "última actualización" lee `MAX(BATCHES.finished_at)`, cache TTL 60s.
- Pestaña `blocked ⚠` lista proyectos en hard-constraint con razón visible.
- Botón "Crear entrada de feedback" genera archivo en `docs/feedback/YYYY-MM-DD-N.md` con template precargado (proyecto, score, fecha) — facilita el loop de evolución.

→ **Open Q8**: ¿queremos sparklines inline (más visual, más coste de render) o solo tabla densa? Recomendación: tabla densa por defecto, sparklines en drill-down only.

### Agent Tools Contract (agent-native parity)

El plan original mencionaba "agent-native parity" en una línea sin desarrollar. **Esta sección define el contrato explícito**: cualquier acción del dashboard tiene equivalente CLI con output JSON estable, validado contra schema, listable vía `crypto-insights tools`. Sin esto, un futuro LLM-reasoner (Fase 5) requiere refactor del dashboard.

**12 tools MCP-style** (cada uno mapea 1:1 a un subcomando CLI con `--json`):

```
get_project_state(symbol: str)
  → {state, composite_score, layer1_scores, reason_code, reason_data,
     reason_human, layer2_flag, batches_in_state, batch_id, updated_at}

list_projects(filter?: {state?, archetype?, layer2_flag?, score_min?, score_max?})
  → [ProjectState]

get_signal_history(symbol: str, signal_name: str, days: int)
  → [{date, value, formula_version}]

get_upcoming_events(window_days: int, event_types?: [str], symbols?: [str])
  → [{symbol, event_type, event_date, magnitude_pct, magnitude_weighted,
      allocation_category, days_until}]

get_raw_snapshot(symbol: str, source: str, date: str)
  → {payload: json, payload_schema_version: int, fetched_at}

get_batch_status(batch_id: str | "latest")
  → {batch_id, status, started_at, finished_at, sources_ok: int,
     sources_failed: [{source, project, error}]}

list_archetypes()
  → [{name, signal_weights: {signal: weight}, applies_consolidation: bool}]

get_archetype_rules(archetype: str)
  → {weights, state_thresholds: {acumulacion, aceleracion, distribucion, colapso}}

create_feedback(symbols: [str], notes: str, signals_referenced?: [str])
  → {feedback_id, path}

list_feedback(since?: date, symbol?: str)
  → [{id, date, symbols, summary}]

list_open_questions()
  → [{id, status, doc_path, blocking_phase?}]

trigger_batch(date?: str, dry_run?: bool)
  → {batch_id, status}    # local-auth-required; read-only flag para preview
```

**Subcomandos CLI** que materializan los 12 tools:

```
crypto-insights state SYMBOL [--json]
crypto-insights list [--state X] [--archetype Y] [--score-min Z] [--json]
crypto-insights signal-history SYMBOL SIGNAL [--days 30] [--json]
crypto-insights events [--window 30d] [--type unlock] [--symbols HYPE,ZEC] [--json]
crypto-insights raw SYMBOL SOURCE DATE [--json]
crypto-insights batch-status [--latest|--id 2026-05-10] [--json]
crypto-insights archetypes [--json]
crypto-insights archetype-rules NAME [--json]
crypto-insights feedback create --symbols HYPE,ZEC --notes "..."
crypto-insights feedback list [--since 2026-05-01] [--symbol HYPE] [--json]
crypto-insights open-questions [--json]
crypto-insights batch-daily [--date YYYY-MM-DD] [--dry-run]

crypto-insights tools [--json]    # capability discovery — auto-generado de Typer
```

**Schemas**: definir en `src/crypto_insights/schemas/` (uno por output type) usando Pydantic v2. Fuente única de verdad para CLI output, dashboard rendering y futura tool registration MCP.

**Acceptance test crítico (en Fase 3)**: para cada widget Streamlit, verificar que consume el mismo CLI `--json` (no SQL inline). Garantiza paridad inmutable. Test concreto:

```python
def test_dashboard_uses_cli_json_only():
    # cada vista del dashboard llama a get_project_state(...) o list_projects(...)
    # NO debe haber sqlalchemy.text() ni raw SQL en streamlit_app.py o dashboard/views.py
    src = read_file("streamlit_app.py") + read_files("src/crypto_insights/dashboard/")
    assert "sa.text(" not in src
    assert "session.execute(" not in src
    # toda lectura va vía src/crypto_insights/api/ que es lo que CLI expone
```

### Implementation Phases

#### Fase 0 — Foundations (semana 1) ✅ COMPLETADA (2026-05-10)

**Objetivo**: repo ejecutable end-to-end con un solo proyecto y un solo connector.

- [x] `uv init --package crypto_insights`, `pyproject.toml` con dep groups
- [x] `ruff` + `mypy` + `pytest` configurados; pre-commit hook opcional
- [x] Schema SQLite inicial (`migrations/0001-initial-schema.sql`) — incluye además `events`, `derived_signals`, `project_state`, `project_state_history` para no fragmentar la migration
- [x] CLI esqueleto (`crypto-insights init-db`, `crypto-insights batch-daily --date YYYY-MM-DD`) + extras: `sync-watchlist`, `list`, `state`, `batch-status`, `tools` (capability discovery), `backup`
- [x] Watchlist loader desde `data/watchlist.yaml` (30 proyectos — añadidos SUI y STRK)
- [x] **Un connector funcional end-to-end**: Binance OHLCV con respx unit tests + JSON fixture
- [x] Tests: 16 verdes (binance × 4, watchlist × 6, persist × 6). Lint clean.

**Success criteria** ✅ `uv run crypto-insights batch-daily` ejecuta para 30 proyectos, deja 13 filas en `raw_snapshots` (los 13 listados en Binance Spot), idempotente, batch finished status `complete`.

**Estimación real**: ~4-5h en sesión asistida.

#### Fase 1 — Layer 2 (semana 2)

**Objetivo**: filtro de viabilidad funcional con la hard constraint de unlocks.

- [ ] Connector DeFiLlama (fees, TVL, volume) + tests respx.
- [ ] Connector DeFiLlama Unlocks → puebla `EVENTS`.
- [ ] Connector GitHub (commits últimos 30/90d, contributors).
- [ ] Migration 0002: tablas `events`, `derived_signals`, `project_state`.
- [ ] `signals/unlocks.py`: hard constraint 5%/4-8w.
- [ ] `fusion/layer2.py`: cálculo de `layer2_flag` y `current_state=blocked`.
- [ ] Output preliminar: `viability_report.md` (regenerable desde CLI) — antes del dashboard, validar lógica.

**Success criteria**: para los 30 proyectos, `crypto-insights viability` produce un report con flag green/amber/red/blocked y razones legibles. HYPE muestra blocked si hay unlock en próximas 4-8w.

**Estimación**: 12-16h.

#### Fase 2 — Layer 1 core (semanas 3-4)

**Objetivo**: signals de positioning principales operativos.

- [ ] Migración esquema para guardar OHLCV histórico completo (Binance da hasta 2017+, almacenar todo lo disponible).
- [ ] Backfill OHLCV diario completo histórico (script one-shot, respeta rate limits — ~30k requests para 30 proyectos × 8 años, planificar batched).
- [ ] `signals/indicators.py`: ATR Wilder, Bollinger Width, RVOL, range compression — con tests hypothesis (ATR ≥ 0, BB upper ≥ middle ≥ lower, etc).
- [ ] `signals/consolidation_breakout.py`: detector con los 4 criterios de Victor + tests con fixtures (datos sintéticos + datos reales HYPE 2025).
- [ ] Connectors `hyperliquid` y `helius` (Solana top holders) — primer signal de smart money.
- [ ] **Decidir y implementar conector ETH top holders** (resolución Open Q1).
- [ ] `signals/funding.py`, `signals/smart_money.py`.

**Success criteria**: para HYPE en histórico, el detector marca `consolidation_breakout=1.0` en semanas donde retrospectivamente hubo breakout. Falsos positivos identificados y documentados.

**Estimación**: 20-30h.

#### Fase 3 — Fusión + Dashboard (semana 5)

**Objetivo**: dashboard Streamlit con estado por proyecto.

- [ ] `fusion/archetype_rules.py` con tabla de pesos (la de arriba).
- [ ] `fusion/layer1.py`: composite score y `state_from_scores()`.
- [ ] `streamlit_app.py`: layout descrito, tabs por archetype, drill-down básico.
- [ ] Botón "Crear feedback" genera archivo en `docs/feedback/`.
- [ ] Setup Windows Task Scheduler ejecutando `uv run crypto-insights batch-daily` a las 9:00 UTC diario (mercado cierra/abre en ventana razonable).

**Success criteria**: Victor abre `streamlit run streamlit_app.py`, ve los 30 proyectos clasificados, identifica al menos 1 acumulación o 1 distribución detectada por la herramienta que no había visto manualmente.

**Estimación**: 12-16h.

#### Fase 4 — Iteración con feedback (semanas 6-8)

**Objetivo**: cerrar el loop de evolución descrito en `docs/feedback/README.md`.

- [ ] **Re-cómputo histórico**: aplicar reglas actuales sobre histórico 2024-2025 para validar visualmente que detectarían los moves conocidos (HYPE Q3 2025, ZEC nov-2025, FARTCOIN parabólica).
- [ ] Resolución de **Open Q2 (mindshare)** y **Open Q3 (netflows)** según lo aprendido en uso real.
- [ ] Primer ciclo de review semanal sintetizando `feedback/` → `learnings/`.
- [ ] Ajuste de pesos de `archetype_rules` basado en aciertos/errores documentados.
- [ ] Considerar Opción 3 híbrida (LLM-reasoner) si reglas duras dejan dinero sobre la mesa de forma sistemática.

**Success criteria**: al menos 4 entradas en `feedback/`, una en `learnings/signal-performance.md`, y un ADR 0002 si emergió un cambio estructural.

**Estimación**: ongoing.

#### Fase 5+ (post-MVP, fuera de scope)

Listado para no perderlo, no se implementa hasta validar MVP:

- Auto-discovery desde categorías CoinGecko (Opción A(ii) brainstorm).
- Alertas push (Telegram/email) — solo cuando se hayan validado al menos 3 trades cuya entrada o salida fue accionada por el dashboard.
- Backtest framework (vectorbt o backtesting.py).
- LLM-reasoner híbrido (Opción 3) — formato: GPT/Claude recibe el JSON de scores + contexto de archetype y emite veredict + razón en lenguaje natural.

## Alternative Approaches Considered

### Storage: ¿DuckDB en lugar de SQLite?

- **Considerado por**: queries analíticas cross-sectional (rankings por fecha, percentiles).
- **Rechazado porque**: DuckDB es 10× más lento que SQLite en inserts diarios single-row (verificado en research). Operación local con un proceso de batch escribiendo y Streamlit leyendo es justamente el escenario donde DuckDB sufre. WAL en SQLite resuelve el caso de Streamlit.
- **Patrón híbrido si en Fase 4 emerge necesidad analítica**: DuckDB attach `data.db` (TYPE SQLITE) — DuckDB lee SQLite directamente sin duplicar storage.

### Dashboard: CLI con rich vs markdown report vs Streamlit

- **Streamlit elegido por Victor**. Rationale a futuro: drill-down interactivo y refresh automático sin re-correr comando.
- **rich tables** descartado: no permite drill-down, repetir comando para refresh.
- **Markdown report regenerado**: aceptable como output intermedio en Fase 1 (`viability_report.md`), no como dashboard primary.

### Indicadores TA: pandas-ta vs a mano vs TA-Lib

- **A mano elegido**. ATR Wilder, BB Width, RVOL son <10 LoC cada uno. Auditable, sin opacidad sobre qué variante de media se usa.
- **pandas-ta** considerado: el original (twopirllc/pandas-ta) está stalled. **pandas-ta-classic** (fork mantenido por xgboosted, soporta NumPy 2) es viable si necesitamos >5 indicadores en el futuro.
- **TA-Lib** descartado para MVP: instalación nativa Windows pesada, beneficio de performance irrelevante para 30 proyectos.

### Scheduling: APScheduler vs Windows Task Scheduler vs schedule

- **Windows Task Scheduler elegido**. Stateless, OS-managed, sobrevive reboot/sleep del laptop, fácil debug post-mortem por logs en archivo.
- **APScheduler**: requeriría proceso Python siempre vivo. Anti-pattern para batch diario en laptop personal que se apaga.
- **schedule**: descartado, sin cron expressions ni persistencia.

### Top holders ETH: Etherscan vs Moralis vs Alchemy vs scraping

- **Etherscan free** descartado: el endpoint de top holders requiere paid (Pro Account API). Confirmado por research.
- **Moralis free** (~25k CU/día) o **Alchemy free** (300M CU/mes) son las opciones reales. → Open Q1.
- **Scraping del UI** considerado: ToS-borderline, frágil ante cambios de Cloudflare. Solo como último recurso manual.

## System-Wide Impact

### Interaction graph

```
Windows Task Scheduler (9:00 UTC daily)
  ↓ exec
uv run crypto-insights batch-daily
  ↓ imports
src/crypto_insights/cli.py → pipeline.batch.run_batch(date)
  ↓ for each (project, connector):
  ↓   await connector.fetch(project)
  ↓     → aiolimiter (per-host bucket) acquires permit
  ↓     → tenacity retry on 429/5xx with jitter
  ↓     → httpx.AsyncClient sends request
  ↓     → response normalized to SourceSnapshot dataclass
  ↓   upsert_raw_snapshot(snapshot, batch_id)
  ↓
  ↓ for each project:
  ↓   compute_derived_signals(project, batch_id) reads RAW_SNAPSHOTS
  ↓   compute_project_state(project, batch_id) reads DERIVED_SIGNALS
  ↓   upsert_project_state(state, batch_id)
  ↓
register_batch_finished(batch_id, status)

Streamlit (independent process, runs only when Victor opens it)
  ↓ st.connection("sql") → SQLite WAL read
  ↓ render tabs and drill-down
  ↓ user clicks "create feedback" → writes docs/feedback/YYYY-MM-DD-N.md
```

**Cadena no obvia**: una falla en `connector.fetch()` lanza excepción, `asyncio.gather(return_exceptions=True)` la captura como objeto, `pipeline.batch` la loggea pero **no aborta**. La derivada para ese proyecto se calcula con datos del último batch exitoso para esa fuente (gap-aware). Si el gap es >7 días para una fuente crítica (ej. funding), el cálculo del signal correspondiente devuelve `None` y la fusión penaliza el composite score (no inventa datos).

### Error & failure propagation

| Capa | Errores típicos | Quién los maneja | Behavior |
|---|---|---|---|
| HTTP transport | timeouts, 429, 5xx | tenacity (retry exp jitter, max 5) | Reintenta dentro del rate limit |
| Connector | parse error, schema change upstream | Connector wrapping | Loggea ERROR, levanta `ConnectorError(source, project)` |
| Pipeline | `ConnectorError` o `Exception` arbitraria | `asyncio.gather(return_exceptions=True)` | Loggea, anota en `BATCHES.error_summary`, continúa |
| Persistence | SQLite locked / disk full | Try/except en upsert | Loggea CRITICAL, marca batch `failed`, exit 1 (Task Scheduler email opcional) |
| Dashboard | DB no existe / vacía | Streamlit error component | "No batches yet — run `crypto-insights batch-daily` first" |

**Riesgo identificado**: si `tenacity` retrying lleva a exceder rate limit del host (ej. después de 429, retry en window aún no liberada), el aiolimiter asegura que la siguiente request del retry **espera** su permit antes de enviarse. Esto puede inflar la duración del batch significativamente si una fuente está caída. Mitigación: timeout global del batch (30 min); más allá de eso, el batch se marca `partial` y termina.

### State lifecycle risks

| Escenario | Riesgo | Mitigación |
|---|---|---|
| Batch crashea a mitad | `RAW_SNAPSHOTS` con datos parciales, `PROJECT_STATE` no actualizado | UPSERT por `(project, source, date)` permite re-correr; `BATCHES.status='running'` flag detecta crashes; al re-correr, idempotente |
| Re-correr batch del mismo día sobrescribe datos buenos | Pérdida de snapshot de fuente que ahora falla | UPSERT solo con datos no-NULL; mantener histórico opcional con `batch_id` discriminator (queries usan `MAX(batch_id) WHERE date = ...`) |
| Schema change upstream (DeFiLlama añade campo) | Parser falla, fila no se persiste | Persistir `payload` JSON crudo SIEMPRE; normalización fallida loguea WARN pero deja el raw |
| Dashboard lee mientras batch escribe | Datos inconsistentes | SQLite WAL: lecturas no bloquean escrituras; lector ve snapshot consistente del momento de iniciar la transacción |
| `EVENTS` (unlocks) duplicados al re-fetch | Hard constraint detecta unlock dos veces | UNIQUE en `(project, event_type, event_date)` |

### API surface parity

- Cualquier información mostrada en Streamlit debe ser obtenible vía CLI (ej. `crypto-insights state HYPE`, `crypto-insights blocked`). Esto es **agent-native parity**: si en el futuro un LLM agent quiere consultar el estado, debe poder sin abrir UI.
- Acción "crear feedback desde UI" tiene equivalente CLI: `crypto-insights feedback create --projects HYPE,ZEC --notes "..."`.

### Integration test scenarios (cross-layer, no mock-only)

1. **End-to-end batch con todos los connectors** sobre un proyecto fixture (HYPE), fixtures vcr grabados de un día real → verifica que `PROJECT_STATE` se popule con los campos esperados.
2. **Hard constraint de unlocks**: crear EVENTS sintéticos (1 unlock 6% en 35 días) → ejecutar fusión Layer 2 → verificar `current_state='blocked'` y reason correcto.
3. **Consolidation breakout sobre HYPE histórico real**: fixture OHLCV diario 2024-01 a 2025-04 → ejecutar detector → verificar que marca breakout en al menos 1 semana del periodo conocido.
4. **Fallo aislado de connector**: mock helius para que devuelva 500 → verificar que el batch completa, otros signals se computan, `BATCHES.status='partial'`, `error_summary` menciona helius.
5. **Re-run del mismo batch_id**: ejecutar batch dos veces para fecha=2026-05-10 → verificar que `RAW_SNAPSHOTS.count` no duplica, que último UPSERT gana.

## Acceptance Criteria

### Funcionales (qué hace el MVP)

- [ ] `uv sync` reproduce el entorno desde `uv.lock` sin errores.
- [ ] `crypto-insights init-db` aplica todas las migraciones yoyo.
- [ ] `crypto-insights batch-daily` corre sin errores fatales para los 30 proyectos.
- [ ] Batch es idempotente: re-ejecutarlo el mismo día no duplica filas.
- [ ] Fallo aislado de un connector NO tira el batch; otros connectors completan.
- [ ] `streamlit run streamlit_app.py` abre dashboard con tabs por archetype.
- [ ] Hard constraint de unlocks (≥5%, 4-8w) bloquea proyectos correctamente.
- [ ] Detector de consolidation breakout emite señales coherentes sobre HYPE 2025 histórico.
- [ ] Botón "crear feedback" genera archivo en `docs/feedback/` con template prellenado.

### No-funcionales

- [ ] **Performance**: batch completo para 30 proyectos termina en <10 min en condiciones normales (rate limits respetados, sin timeouts).
- [ ] **Rate limit compliance**: 0 errores 429 en logs en operación normal (medido sobre 1 semana de batches diarios).
- [ ] **Storage**: `data/crypto.db` <100 MB después de 30 días de batches diarios.
- [ ] **Reproducibilidad**: tests vcr replayean sin red.
- [ ] **Type safety**: `mypy --strict` pasa en `connectors/` y `pipeline/`.

### Quality gates

- [ ] Cobertura tests >70% en `signals/` y `pipeline/`. UI sin coverage requirement.
- [ ] `ruff check` y `ruff format` clean.
- [ ] README actualizado con setup, comandos CLI principales, cómo abrir dashboard.
- [ ] PLAN.md sincronizado con este documento (referenciar el plan).

## Success Metrics

**Métrica primaria del MVP**: ¿el feedback log se llena? Si Victor escribe ≥3 entradas de feedback / semana durante 4 semanas, el MVP cumple su rol (el dashboard genera observaciones procesables). Si después de 4 semanas hay <5 entradas totales, la herramienta no está aportando — pivot.

**Métrica secundaria (validación de signals)**: en feedback log, ratio `aciertos / total_observaciones_con_outcome ≥ 0.55` para los signals con weight >0.20 en algún archetype. Sub-0.55 → ese signal entra en revisión de pesos en `learnings/signal-performance.md`.

**Métrica de robustez operacional**: ratio `batches_completos / total_batches ≥ 0.90` durante un mes. Sub-0.90 → connector inestable identificado y reemplazado o degradado a `optional`.

## Dependencies & Prerequisites

### Software local

- Python 3.12+ instalado en Windows.
- `uv` instalado (`pip install uv` o instalador oficial Astral).
- SQLite 3.39+ (incluido con Windows Python 3.12).

### API keys necesarias (todas free tier)

- **Etherscan v2**: 1 key (multichain, cubre Ethereum + L2s).
- **CoinGecko Demo**: 1 key.
- **GitHub PAT**: scope `public_repo` (read-only).
- **Helius**: 1 key (para Solana top holders).
- **Moralis** o **Alchemy**: 1 key (para ETH top holders, dependiendo Open Q1).
- **(opcional) Santiment Sanbase**: 1 key si Open Q2 se resuelve usando Santiment.

Almacenadas en `.env` (gitignored), cargadas via `pydantic-settings`. Documentar en README cómo obtenerlas.

### Datos manuales

- `data/watchlist.yaml` con los **30** proyectos definitivos. Hoy hay 26 en `watchlist.example.yaml` — completar.
- `data/excluded_addresses.yaml` con direcciones a filtrar de top holders (CEX hot wallets, DEX programs). Construir empíricamente en Fase 2.

## Risk Analysis & Mitigation

| Riesgo | Probabilidad | Impacto | Mitigación |
|---|---|---|---|
| **Etherscan v2 cambia free tier 1-jul-2026** (ya anunciado) | Alta | Medio (no usamos top holders ahí, pero sí balances/tx) | Encapsular en connector aislado; switch a Alchemy/Moralis si breaks |
| **Kaito sin free API → gap de mindshare** | Confirmado | Alto (mindshare es signal clave en memecoin/post-tge) | Open Q2: decidir entre gap explícito, Santiment débil, o budget para Pro |
| **Top holders Solana/ETH free tiers limitados** | Media | Alto (smart money es señal central) | Helius free 1M CU/mes alcanza para 30 proyectos × 1 fetch/día; monitorizar y degradar a 1 fetch/semana si se agota |
| **Schema change upstream (DeFiLlama, Hyperliquid)** | Media | Bajo si payload se persiste raw | Persistir JSON crudo siempre; normalización separada y testeada por snapshot |
| **Cliffs de unlock pequeños múltiples no detectados** | Baja | Medio | Open Q4: documentar en learnings si aparece como patrón; ajustar regla agregada |
| **Pesos de archetype mal calibrados → falsa confianza** | Alta inicialmente | Alto si Victor toma trades con ellos sin validar | Fase 4 incluye validación retrospectiva sobre 2024-2025 antes de operar con dashboard |
| **Windows Task Scheduler silencioso si batch falla** | Media | Bajo | Configurar Task con "send email on failure" o log file watcher manual |
| **SQLite contention si se abre Streamlit durante batch largo** | Baja con WAL | Bajo | WAL configurado en `init-db`; documentar |
| **Dependencias rotas tras `uv sync` en 6 meses** | Media | Medio | `uv.lock` commiteado; pipeline CI opcional que prueba `uv sync` semanalmente |
| **Sobreajuste de pesos al feedback puntual de pocos trades** | Alta | Alto | Regla en `learnings/`: signal solo se reweighta tras 3+ casos del mismo patrón |

## Open Questions / Pending Feedback

Estas son las decisiones que **requieren input de Victor** antes o durante la implementación. Cada una se materializa como archivo en `docs/feedback/open-questions/` para no bloquear desarrollo del resto.

### Open Q1 — Top holders Ethereum/Base/Arbitrum

**Contexto**: Etherscan free **NO expone top holders por contrato**. Recomendación research: Moralis free (~25k CU/día) o Alchemy free (300M CU/mes). Bitquery (10k pts/mes) como fallback.

**Pregunta**: ¿Moralis, Alchemy, o ambos como redundancia? ¿Aceptable el ToS de scraping del UI Etherscan como fallback manual?

→ Decisión bloqueante para **Fase 2** (signal smart money en proyectos ETH/Base/Arbitrum: AAVE, PENDLE, ENA, SYRUP, RENDER, FXN, CHIP, VIRTUAL, VVV).

→ Documento: `docs/feedback/open-questions/2026-05-10-q1-eth-top-holders.md`

### Open Q2 — Mindshare sin Kaito gratis

**Contexto**: Kaito sin free API en 2026, scrape bloqueado por Cloudflare. Mindshare es un signal con peso alto (0.40) en memecoin-brand y 0.50 en post-tge.

**Pregunta**: tres opciones:
- **(a)** Dejar mindshare como gap explícito y compensar con peso más alto en holders/funding para esos archetypes (degrada calidad de signal).
- **(b)** Santiment Sanbase free (1000 calls/mes, métrica `social_volume` muy básica) — posible pero débil.
- **(c)** Budget mensual ($24-49) para LunarCrush Individual o Santiment Pro.

Recomendación: empezar con **(a)** y documentar el gap en feedback durante 4 semanas. Si los memecoin-brand y post-tge dan signals pobres, evaluar (c).

→ NO bloqueante para Fase 1-2, sí para Fase 3 (fusión).

→ Documento: `docs/feedback/open-questions/2026-05-10-q2-mindshare.md`

### Open Q3 — CEX netflows sin CryptoQuant

**Contexto**: CryptoQuant gratis solo en dashboard web; API requiere $29-99/mes. Glassnode no incluye netflows en free.

**Pregunta**: tres opciones:
- **(a)** Construir netflows desde Dune Analytics queries públicas (free, 2500 query executions/mes). Requiere identificar queries existentes y enchufar el endpoint CSV.
- **(b)** Usar DefiLlama stablecoin flows entre chains como proxy parcial (gratis).
- **(c)** Omitir netflows para MVP; añadir si Fase 4 muestra que es señal demandada.

Recomendación: **(c) para Fase 1-3** (peso bajo en la tabla de archetypes ya), evaluar (a) en Fase 4 si emerge como necesidad.

→ NO bloqueante.

→ Documento: `docs/feedback/open-questions/2026-05-10-q3-netflows.md`

### Open Q4 — Comportamiento ante `blocked` con posición abierta

**Contexto**: el MVP **no gestiona posiciones** (no sabe si Victor tiene HYPE en cartera). Si un proyecto entra en `blocked` por unlock inminente, ¿el dashboard solo informa o sugiere acción?

**Recomendación**: solo informar. `blocked` muestra fecha de inicio y razón ("blocked desde 2026-05-08 — unlock 11.2% el 2026-06-15"). Decisión de salir es del usuario.

→ Documento: `docs/feedback/open-questions/2026-05-10-q4-blocked-with-position.md`

### Open Q5 — Thresholds del consolidation breakout

**Contexto**: los 4 thresholds (rango <15%, ATR <70% baseline, volumen <60% baseline, breakout RVOL >1.5x) son educated guesses.

**Pregunta**: ¿empezar con esos valores y ajustar tras 4-8 semanas de feedback (recomendación), o calibrar primero contra histórico de HYPE/SOL/ZEC en Fase 2?

**Recomendación**: ambos — Fase 2 incluye validación retrospectiva sobre HYPE 2024-2025; Fase 4 ajusta basado en feedback real.

→ Documento: `docs/feedback/open-questions/2026-05-10-q5-breakout-thresholds.md`

### Open Q6 — Ventana de "rango" para compresión

**Contexto**: 8 semanas como ventana base. Alternativas: 6w (más sensible, más falsos positivos), 12w (más selectivo, menos breakouts capturados).

**Recomendación**: empezar 8w. Documentar en learnings si feedback muestra que perdemos breakouts importantes.

→ Documento: `docs/feedback/open-questions/2026-05-10-q6-range-window.md`

### Open Q7 — Calibración thresholds de estado

**Contexto**: thresholds de composite score para clasificar estado (`>0.6 → aceleracion`, etc) son tentativos. Necesitan validación contra histórico.

**Recomendación**: implementación Fase 3 con valores actuales; Fase 4 dedica una semana a backtest visual sobre 2024-2025.

→ NO bloqueante.

### Open Q8 — Dashboard: sparklines o tabla densa

**Contexto**: trade-off entre densidad informacional y coste de render Streamlit.

**Recomendación**: tabla densa por defecto, sparklines en drill-down only (clickeas un proyecto y se expande).

→ NO bloqueante.

### Open Q9 — Periodicidad del scan (confirmación)

**Contexto**: brainstorm + decisión Victor = daily batch. Brainstorm sugiere que daily es suficiente para weekly swing (señales no se mueven intra-día materialmente para horizonte semanas-meses).

**Recomendación**: daily fijo. Si en feedback emerge "habría visto X 6 horas antes con intra-day", evaluar 2× día (08:00 y 20:00 UTC).

→ NO bloqueante.

### Open Q11 — DeFiLlama Unlocks: free vs Pro-only (NUEVO)

**Contexto**: dos research agents independientes durante el deepen-plan dieron respuestas contradictorias sobre el endpoint `/emissions`. Uno afirmó "free, sin cap documentado". Otro afirmó "Pro-only, requiere $300/mes". El plan original asumía free.

**Pregunta**: ¿comprobamos en setup de Fase 1 (request real sin auth) y procedemos según resultado?

**Recomendación**: Sí. Si confirma Pro-only, fallback documentado:
- **Plan B**: scrape del HTML público de `defillama.com/unlocks/{protocol}` semanalmente (frágil ante cambios de UI).
- **Plan C**: Tokenomist.ai como primaria (schema documentado, sin API key formal).
- **Plan D**: presupuesto DeFiLlama Pro $300/mes — descartado para MVP.

→ Bloqueante para **Fase 1** (Layer 2 hard constraint).

→ Documento: `docs/feedback/open-questions/2026-05-10-q11-defillama-unlocks-access.md` (a crear).

### Open Q12 — Política de gap (signal=None) (NUEVO — detectado por architecture-strategist)

**Contexto**: el plan original no especifica qué hacer cuando una fuente cae >7d y el signal queda None. Tres opciones:
- (a) Renormalizar pesos sobre presentes → bias.
- (b) Tratar None como 0 → penaliza falsamente.
- (c) Estado `degraded` separado + renormalización con flag `has_gaps`.

**Recomendación**: (c) híbrido — renormalizar si <30% de pesos faltan + warning visible; estado `degraded` si ≥30%. Materializar como ADR 0005 antes de Fase 3.

→ Bloqueante para **Fase 3** (fusión + dashboard).

### Open Q13 — Matriz de transiciones de state machine (NUEVO)

**Contexto**: 6 estados definidos pero sin matriz de transiciones legales. Sin esto, oscilación posible en boundaries.

**Recomendación**: matriz en R4 + hysteresis 2-batches. Materializar como ADR 0005-bis.

→ Bloqueante para **Fase 3**.

### Open Q10 — Watchlist a 30 proyectos ✅ RESUELTA (2026-05-10)

**Decisión**: Añadidos **SUI** (l1-maduro, validador fuera del eje EVM/SOL) y **STRK** (post-tge, ZK-STARK L2 con cliffs pesados — caso ejemplo del archetype post-tge). Watchlist completa = 30.

→ Documento: `docs/feedback/open-questions/2026-05-10-q10-complete-watchlist.md`

## Future Considerations

Lo que NO está en MVP pero quedan ganchos arquitectónicos previstos:

- **Auto-discovery (Opción A(ii))**: añadir un connector `coingecko_categories` que liste tokens nuevos en categorías relevantes; pasarlos por Layer 2 automático y emitir candidatos para watchlist. Hook: el `cli` puede tener `crypto-insights discover --category ai-agents`.
- **Alertas push**: la separación pipeline/dashboard permite añadir un subscriber a cambios de `PROJECT_STATE` que dispara webhook. Hook: tabla `STATE_TRANSITIONS` (de qué a qué, cuándo) ya derivable de `PROJECT_STATE` histórico.
- **Backtest framework**: el modelo long-format de `DERIVED_SIGNALS` permite reconstruir el estado histórico que el dashboard habría mostrado. Backtest = simular trades sobre esa serie de estados.
- **LLM-reasoner híbrido (Opción 3)**: input al LLM = JSON snapshot de scores + contexto archetype + últimos 4 estados. Output = veredict + razonamiento. Comparar vs reglas duras; mantener ambos paralelos.
- **Multi-cuenta / multi-portfolio**: si Victor quiere separar tracking de "trading book" vs "watchlist solo observación". Schema actual no lo soporta; añadir tabla `WATCHLISTS` con `name` y `projects[]`.

## Documentation Plan

- [ ] **README.md** existente: añadir sección "Setup" con `uv sync`, configuración `.env`, primer batch.
- [ ] **PLAN.md** existente: actualizar para reflejar este documento (referenciarlo).
- [ ] **Crear `docs/decisions/0002-stack-tecnico.md`** documentando elecciones de uv, SQLite, Streamlit, etc.
- [ ] **Crear `docs/decisions/0003-unlocks-hard-constraint.md`** documentando regla 5%/4-8w (decisión explícita Victor).
- [ ] **Crear `docs/decisions/0004-consolidation-breakout-spec.md`** documentando los 4 criterios + thresholds iniciales.
- [ ] **Crear `docs/feedback/open-questions/`** con un archivo por cada Open Q listada arriba (template prellenado, espera respuesta de Victor).
- [ ] **Docstrings en connectors**: cada connector documenta endpoint, auth, rate limit conocido y schema esperado en su docstring de módulo.

## Research Enhancements (deepened 2026-05-10)

Esta sección consolida hallazgos de los 8 agents que profundizaron el plan. Los cambios estructurales ya se aplicaron inline (schema, pipeline, signals, agent tools); aquí queda lo que no encajaba en una sección concreta y los detalles técnicos de implementación que merecen estar a mano cuando se escriba código.

### R1 — Pipeline async (Python 3.12+ idioms)

**TaskGroup vs gather**: usar `asyncio.TaskGroup` con wrapper `_safe_fetch` que devuelve `ConnectorResult.ok` o `.failed` (ya en pseudocódigo del plan). El antipattern `gather(return_exceptions=True)` silencia `KeyboardInterrupt` y `CancelledError`, devuelve lista heterogénea (`Exception | Result`), y obliga a `isinstance` checks en consumidor.

**aiolimiter API**: `AsyncLimiter(max_rate, time_period)` se usa como context manager `async with limiter:`, NO como decorator. Parámetros: `.acquire(amount=1.0)`, `.has_capacity(amount=1.0)` para no bloquear.

**tenacity en async**: `@retry` decorator detecta automáticamente coroutines y delega a `AsyncRetrying`. NO necesitas `AsyncRetrying` separado. Sleeps son `asyncio.sleep`.

**Combinación correcta limiter + retry** (anti-doble-cuenta confirmado por kieran-python-reviewer):

```python
@retry(
    retry=retry_if_exception_type(httpx.HTTPStatusError),
    wait=wait_exponential_jitter(initial=1, max=30),
    stop=stop_after_attempt(5),
    before_sleep=_honor_retry_after,  # leer Retry-After header del 429
)
async def fetch_one(url: str) -> httpx.Response:
    async with limiter:        # limiter DENTRO de retry, deliberado
        resp = await client.get(url)
        resp.raise_for_status()
        return resp
```

Cada retry adquiere permit fresco — esto es deliberado: si el host está rate-limiting, debes esperar tu turno antes del próximo intento. Documentar invariante en `connectors/base.py`.

### R2 — Pydantic vs dataclasses (decisión por capa)

- **Pydantic v2** para todo lo que cruza un boundary externo: payloads de connectors (parsing JSON), config (.env via `pydantic-settings`), schemas de output CLI/agent tools. La validación at-the-edge ahorra debugging cuando una API mete `null` donde había `float`.
- **`@dataclass(frozen=True, slots=True)`** para tipos puros internos (Project, BatchResult, scores intermedios). Más rápido, sin overhead de validación en hot loops (30 proyectos × 10 signals × 365 días).
- **attrs**: descartar — Pydantic v2 + dataclasses cubren el espectro.

**Anti-pattern flagged**: NO usar `BaseModel` para todo. La sobrecarga de validación en el hot loop de derivadas suma.

**`from __future__ import annotations`**: en 3.12 ya no es necesario para PEP 563, pero **rompe Pydantic v2** si lo activas (string annotations no resueltas en runtime). Decisión explícita en pyproject: NO usarlo en módulos con Pydantic models, sí permitirlo en módulos puros.

### R3 — Política de gap (signal=None) — ADR 0005 propuesto

Tres semánticas posibles, mutuamente incompatibles, no especificadas en el plan original:

- (a) **Renormalizar pesos sobre signals presentes** → bias hacia signals supervivientes; un proyecto con solo 2 signals "vivos" puede dar score alto artificial.
- (b) **Tratar None como 0** → penaliza falsamente proyecto sano si fuente cae.
- (c) **Marcar `composite_score=None` y degradar estado a `degraded`** → más honesto, rompe la enumeración, pero da info accionable al usuario.

**Decisión recomendada (a aprobar como ADR 0005 antes de Fase 3)**:
- Si <30% de signals (por peso) están None → renormalizar (a) y emitir warning visible en dashboard.
- Si ≥30% de signals (por peso) están None → estado `degraded`, reason_code=`GAP_DATOS`, reason_data lista las fuentes faltantes. NO computar composite_score.
- Persistir flag `has_gaps` en `PROJECT_STATE` para que dashboard pueda mostrar badge "datos parciales".

### R4 — State machine + hysteresis (ADR 0005-bis propuesto)

El plan original lista 6 estados (`acumulación/aceleración/distribución/colapso/reset/blocked`) pero NO matriz de transiciones legales. Sin esto, dos batches consecutivos pueden producir oscilación `acumulación↔reset` en boundary de score.

**Matriz propuesta**:

```
                  → acumulación  aceleración  distribución  colapso  reset  blocked  degraded
  acumulación        ✓              ✓             ✓            -        -      ✓        ✓
  aceleración        ✓              ✓             ✓            -        -      ✓        ✓
  distribución       -              -             ✓            ✓        -      ✓        ✓
  colapso            -              -             -            ✓        ✓      ✓        ✓
  reset              ✓              -             -            -        ✓      ✓        ✓
  blocked (libre)    ✓              ✓             ✓            -        ✓      ✓        ✓
  degraded           ✓              ✓             ✓            ✓        ✓      ✓        ✓
```

Reglas:
- `colapso → reset`: requiere |composite_score| < 0.2 sostenido ≥4 batches.
- `blocked` libera automáticamente cuando el unlock pasa (event_date < today). Estado siguiente se recalcula desde scores.
- Toda transición no-`blocked` requiere **hysteresis: 2 batches consecutivos** en estado nuevo antes de transitar (campo `batches_in_state` en `PROJECT_STATE`).

### R5 — Validador weights ↔ fuentes disponibles (arranque)

**Riesgo silente**: `archetype_rules.py` define peso 0.40 a `smart_money` en memecoin-brand, pero si memecoin está en chain sin connector de holders, el peso queda huérfano y la renormalización (R3) lo absorbe sin warning.

**Mitigación**: validador en `crypto-insights init-db` (y al inicio de cada batch) que reporta:

```
WARN: Project FOOMEME (chain=ton, archetype=memecoin-brand) — signal smart_money
      pesa 0.40 pero no hay connector configurado para chain=ton.
      Score se renormalizará sobre signals disponibles.
```

Implementar como `validate_watchlist_coverage()` que cruza watchlist × archetype_rules × connectors disponibles.

### R6 — Migration safety con yoyo

- **Política forward-only documentada**: rollback raramente útil para single-dev; antes de cada migration, `crypto-insights backup` automático que copia `data/crypto.db` a `data/backups/crypto-YYYYMMDDHHMM.db`.
- **NOT NULL sin default**: yoyo aplica SQL crudo; si añades `ALTER TABLE projects ADD COLUMN tier TEXT NOT NULL` sobre tabla con filas, falla. Convención: toda columna NOT NULL nueva debe tener `DEFAULT` o ser nullable + backfill + migration follow-up.
- **SQLite versión mínima**: `init-db` debe verificar `sqlite_version() >= '3.35'` y fallar fast (DROP COLUMN no existe antes; algunos features de WAL distintos).
- **yoyo init**: `yoyo init --database sqlite:///data/crypto.db migrations` genera `yoyo.ini`. Programático (preferido para CLI custom):
  ```python
  from yoyo import read_migrations, get_backend
  backend = get_backend("sqlite:///data/crypto.db")
  with backend.lock():
      backend.apply_migrations(backend.to_apply(read_migrations("migrations")))
  ```

### R7 — Streamlit + SQLite WAL pattern (verificado)

Patrón verificado para activar WAL automáticamente al abrir cualquier conexión vía `st.connection`:

```python
# en streamlit_app.py, ANTES del primer st.connection
from sqlalchemy import event
from sqlalchemy.engine import Engine

@event.listens_for(Engine, "connect")
def _sqlite_pragma(dbapi_conn, _):
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA synchronous=NORMAL")
    cur.execute("PRAGMA busy_timeout=5000")
    cur.execute("PRAGMA foreign_keys=ON")  # CRÍTICO — default OFF
    cur.execute("PRAGMA wal_autocheckpoint=1000")
    cur.close()
```

**Configuración** en `.streamlit/secrets.toml`:
```toml
[connections.crypto_db]
url = "sqlite:///data/crypto.db"
```

**`@st.cache_data(ttl="1h")` con `batch_id` como invalidador**: confirmado que arg-hash invalida en miss automático cuando `batch_id` cambia. Para tipos no-hasheables (Pydantic, np.ndarray) usar `hash_funcs={Type: lambda x: ...}`. Prefijar `_arg` lo excluye del hash.

**`cache_data` vs `cache_resource`**: cache_data serializa (pickle) → para DataFrames, dicts, listas. cache_resource cachea por referencia → para conexiones DB, modelos ML, clientes HTTP. Compartido entre sesiones, NO thread-safe.

**Coherencia transversal de render**: para evitar que el dashboard vea `batch_id=N` en badge y `batch_id=N+1` en tabla si batch termina entre queries, leer `MAX(batch_id) WHERE status='complete'` UNA VEZ al inicio del render y pasarlo como filtro a TODAS las queries.

### R8 — uv + Streamlit invocation (verificado)

`[project.scripts]` solo sirve para entrypoints Python (`module:function`). Streamlit NO encaja directamente — `streamlit_app.py` no es función importable.

**Idiomático**: mantener `streamlit_app.py` en raíz e invocar `uv run streamlit run streamlit_app.py`. `uv run` garantiza lockfile sincronizado antes de ejecutar.

**Si quieres alias `crypto-ui`**: crea en `cli.py`:
```python
def ui():
    import sys
    from streamlit.web import cli as stcli
    sys.argv = ["streamlit", "run", "streamlit_app.py"]
    stcli.main()
```
Y registra en `pyproject.toml`:
```toml
[project.scripts]
crypto-insights = "crypto_insights.cli:main"
crypto-ui = "crypto_insights.cli:ui"
```

**`uv sync` semántica**:
- `uv sync` solo: project deps + grupo `dev` (special-case PEP 735).
- `uv sync --group dev`: project + dev solo.
- `uv sync --all-groups`: project + TODOS los grupos.
- `uv sync --no-dev`: project sin dev.
- Personalizar default vía `[tool.uv] default-groups = ["dev","test"]`.

### R9 — VCR header filtering (security)

**`pytest-recording` por defecto NO filtra headers `Authorization`/`X-API-KEY`**. Si grabas integration tests con keys reales en `.env`, los cassettes terminan con keys en disco.

**Configurar en `tests/conftest.py`**:
```python
@pytest.fixture(scope="module")
def vcr_config():
    return {
        "filter_headers": ["authorization", "x-api-key", "api-key"],
        "filter_query_parameters": ["api-key", "apikey"],  # Helius pone key en query
    }
```

### R10 — Logging structlog (kwargs, no f-strings)

El beneficio real de structlog se pierde si usas f-strings. Patrón correcto:

```python
# MAL: log.info(f"connector failed for {project.symbol}")
# BIEN:
log.warning("connector_failed", project=project.symbol, source=source, error=str(e))
```

Configurar `structlog.configure()` UNA VEZ en `cli.py` antes de cualquier import que loggee. NO en cada módulo.

### R11 — testing strategy (separación clara)

**respx + vcr.py NO mezclar en mismo test**. respx intercepta transport de httpx; vcr intercepta a nivel socket. Si activas ambos, vcr nunca ve el request.

Separar por carpeta:
- `tests/unit/connectors/` → respx (mocks deterministas, fixtures inline)
- `tests/integration/connectors/` → vcr (replay grabado, fixtures en `data/cassettes/`)

`tests/unit/signals/` con hypothesis para propiedades matemáticas:
- `ATR ≥ 0` siempre
- `BB upper ≥ middle ≥ lower`
- `RVOL` es ratio positivo
- consolidation_breakout requiere window ≥ 8 + 50 = 58 bars

### R12 — Scheduling: heartbeat para detección de crashes

Windows Task Scheduler ejecuta `uv run crypto-insights batch-daily` 9:00 UTC. Configuración Task:
- **Conditions**: "Wake the computer to run this task" (laptop)
- **Settings**: "If the task fails, restart every 30 minutes, max 3 attempts"
- **Actions**: redirigir stdout/stderr a `data/logs/batch-YYYYMMDD.log`
- **Email on failure** (opcional): configurar via Task → "Send an e-mail" trigger en evento Task Failed.

El batch debe actualizar `BATCHES.heartbeat_at` cada 30s en background task (ver pseudocódigo). Próximo batch detecta huérfanos: `WHERE status='running' AND heartbeat_at < datetime('now', '-2 hours')` → marcar `failed`.

### R13 — Sources de tagging para smart money (URLs concretas)

A descargar al inicio (Fase 2):
- https://github.com/brianleect/etherscan-labels (clone como submodule o curl raw)
- https://github.com/dawsbot/eth-labels
- https://github.com/tradezon/cex-list
- Dune query 3761086 ("CEX Wallet Addresses - Complete") — fork + descarga CSV vía API
- Solscan public names: scrape semanal de páginas conocidas
- Helius "How to Get Token Holders" doc + DAS API reference

Almacenar agregado en `data/labels/` (parquet o CSV), refrescar manual semanal o vía script.

### R14 — Conflicto DeFiLlama Unlocks (acción requerida)

Dos research independientes dieron respuestas contradictorias sobre si `/emissions` es free o Pro-only. **Acción**: en Fase 1, primer paso del connector: `curl -s https://api.llama.fi/emissions | jq '.[0]'` sin auth header.
- Si devuelve datos válidos → free, proceder con plan original.
- Si devuelve 401/403 o "upgrade to Pro" → activar Plan B (scrape HTML público) o Plan C (Tokenomist primaria).

Documentar resultado en `docs/feedback/open-questions/2026-05-10-q11-defillama-unlocks-access.md` (a crear).

### R15 — Anti-patterns Python específicos (ruff lint)

Añadir a `pyproject.toml` configuración:

```toml
[tool.ruff.lint]
select = [
    "E", "F", "W",  # base
    "I",            # isort
    "B",            # flake8-bugbear (B006: mutable default args, B008: function call in default)
    "ANN",          # flake8-annotations (require type hints)
    "ASYNC",        # async-specific antipatterns
    "PIE",          # misc improvements
    "RET",          # return statement issues
    "SIM",          # simplifications
]
ignore = ["ANN401"]  # permite Any cuando justificado

[tool.ruff.lint.per-file-ignores]
"streamlit_app.py" = ["ANN401"]
"tests/**/*" = ["ANN", "S101"]  # tests pueden usar Any y assert
```

### R16 — `applies_to` encapsulación (architecture-strategist)

Renombrar `applies_to(project)` → `supports_project(project) -> bool` y declarar el invariante en `connectors/base.py`:

```python
class Connector(Protocol):
    source: ClassVar[str]
    def supports_project(self, p: Project) -> bool:
        """Predicado puro basado en propiedad técnica del proyecto (chain, contract).
        NO debe consultar archetype (decisión de fusion, no de connector)."""
    async def fetch(self, p: Project) -> SourceSnapshot: ...
```

Esto cierra el leak potencial de "connector conoce el dominio archetype".

### R17 — `formula_version` workflow

Cuando cambias la fórmula de un indicador (ej. corriges ATR de SMA-based a Wilder):
1. Bumpear `FORMULA_VERSIONS["atr_pct"]` de `"v1"` a `"v2"`.
2. Re-correr backfill: `crypto-insights backfill-derived --signal atr_pct --formula-version v2 --from-date 2024-01-01`.
3. Los registros viejos `formula_version="v1"` quedan en DB (reproducibilidad de feedback histórico).
4. Las queries del dashboard usan `WHERE formula_version = (SELECT MAX(formula_version) FROM derived_signals WHERE signal_name=?)`.

### R18 — Fase 0 actualizada (incorpora todos los críticos)

Tras los hallazgos, Fase 0 (semana 1) suma:

- [ ] PRAGMA wrapper en connection helper (foreign_keys, WAL, busy_timeout, wal_autocheckpoint).
- [ ] Validación SQLite ≥ 3.35 al `init-db`.
- [ ] `data/backups/` directorio + `crypto-insights backup` CLI command.
- [ ] `crypto-insights tools --json` (capability discovery — auto desde Typer/argparse).
- [ ] Schemas Pydantic v2 en `src/crypto_insights/schemas/` para los 12 tools (al menos stubs).
- [ ] Test agent-native parity (placeholder: verifica que `streamlit_app.py` no tiene SQL inline).

### R19 — Validación retrospectiva (anti-look-ahead en backtest visual)

Para Fase 4 (backtest visual sobre 2024-2025), CRÍTICO no inyectar look-ahead:
- Cada `signal_date` se calcula con datos solo de fechas anteriores (`< signal_date`).
- Pagar el coste: para validar consolidation_breakout sobre HYPE 2024-04, computar el detector usando solo OHLCV del proyecto entre 2024-04 - 56 weeks y 2024-04 (no toda la serie).
- `formula_version` permite mantener la fórmula del momento (no re-aplicar la fórmula nueva sobre datos viejos = anachrónico).

---

## Sources & References

### Origin

- **Brainstorm document**: [`docs/brainstorms/2026-05-09-crypto-tracker-brainstorm.md`](../brainstorms/2026-05-09-crypto-tracker-brainstorm.md)
- **Decisiones carried-forward del brainstorm**:
  1. Modelo dos capas (positioning leads, fundamentals lag) — verificado con HYPE Q3-Q4 2025.
  2. Pesos por archetype con tabla concreta de la sección "Archetype-specific signal weighting".
  3. MVP scope: 30 proyectos curados + dashboard pull + reglas explícitas (Opciones A(i), B(i), 1).
  4. Hard constraint unlocks: ≥5% supply en 4-8 semanas → bloqueo Layer 2 (decisión adicional Victor en este turno).
  5. Consolidation breakout con 4 criterios explícitos (decisión adicional Victor en este turno).
- **ADR activo**: [`docs/decisions/0001-two-layer-signal-model.md`](../decisions/0001-two-layer-signal-model.md)

### Internal references

- Watchlist actual (26 proyectos): [`data/watchlist.example.yaml`](../../data/watchlist.example.yaml)
- Plan vivo del proyecto: [`PLAN.md`](../../PLAN.md)
- Feedback README (mecanismo de evolución): [`docs/feedback/README.md`](../feedback/README.md)

### External references — APIs y limits 2026

- [DeFiLlama API Docs](https://defillama.com/docs/api)
- [DeFiLlama Pro pricing](https://docs.llama.fi/pro-api)
- [Hyperliquid API docs](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint/perpetuals)
- [Binance Spot API limits](https://developers.binance.com/docs/binance-spot-api-docs/rest-api/limits)
- [CoinGecko free rate limit](https://support.coingecko.com/hc/en-us/articles/4538771776153-What-is-the-rate-limit-for-CoinGecko-API-public-plan)
- [Etherscan rate limits](https://docs.etherscan.io/resources/rate-limits)
- [Etherscan free tier 2026 changes (1 jul 2026)](https://info.etherscan.com/whats-changing-in-the-free-api-tier-coverage-and-why/)
- [Helius platform](https://www.helius.dev/)
- [GitHub REST rate limits](https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api)

### External references — Best practices

- [uv: Structure and files](https://docs.astral.sh/uv/concepts/projects/layout/)
- [uv: Configuring projects](https://docs.astral.sh/uv/concepts/projects/config/)
- [uv: Locking and syncing](https://docs.astral.sh/uv/concepts/projects/sync/)
- [uv: Managing dependencies (PEP 735)](https://docs.astral.sh/uv/concepts/projects/dependencies/)
- [PEP 735: Dependency Groups](https://peps.python.org/pep-0735/)
- [data-sloth/uv-streamlit-setup template](https://github.com/data-sloth/uv-streamlit-setup/)
- [encode/httpx discussion #2989: rate limiting in httpx](https://github.com/encode/httpx/discussions/2989)
- [aiolimiter docs](https://aiolimiter.readthedocs.io/)
- [tenacity README — async support](https://github.com/jd/tenacity)
- [DuckDB vs SQLite for analytics workloads](https://marending.dev/notes/sqlite-vs-duckdb/)
- [yoyo-migrations](https://ollycope.com/software/yoyo/latest/)
- [Streamlit SQLConnection](https://docs.streamlit.io/develop/api-reference/connections/st.connections.sqlconnection)
- [Streamlit caching overview](https://docs.streamlit.io/develop/concepts/architecture/caching)
- [Simon Willison — Enabling WAL mode](https://til.simonwillison.net/sqlite/enabling-wal-mode)
- [SQLAlchemy SQLite dialect](https://docs.sqlalchemy.org/en/20/dialects/sqlite.html)
- [pandas-ta-classic (active fork 2026)](https://pypi.org/project/pandas-ta-classic/)
- [RESPX docs](https://lundberg.github.io/respx/)
- [APScheduler vs schedule trade-offs](https://leapcell.io/blog/scheduling-tasks-in-python-apscheduler-versus-schedule)

### External references — TA & Smart Money (deepen-plan)

- [Macroption — ATR Calculation (Wilder)](https://www.macroption.com/atr-calculation/)
- [StockCharts — Bollinger Band Width](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-indicators/bollinger-bandwidth)
- [LuxAlgo — Bollinger Band Squeeze strategy](https://www.luxalgo.com/blog/bollinger-bands-strategy-squeeze-then-surge)
- [ChartSchool — Chaikin Money Flow (CMF)](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-indicators/chaikin-money-flow-cmf)
- [Marketcalls — Look-Ahead Bias](https://www.marketcalls.in/machine-learning/understanding-look-ahead-bias-and-how-to-avoid-it-in-trading-strategies.html)
- [CoinAPI — Crypto candles consistency](https://www.coinapi.io/blog/crypto-candles-not-matching-ohlcv-explained)
- [brianleect/etherscan-labels](https://github.com/brianleect/etherscan-labels)
- [dawsbot/eth-labels](https://github.com/dawsbot/eth-labels)
- [tradezon/cex-list](https://github.com/tradezon/cex-list)
- [Dune Labels overview](https://docs.dune.com/data-catalog/curated/labels/overview)
- [Dune CEX Wallet Addresses query (3761086)](https://dune.com/queries/3761086)
- [Helius — How to Get Token Holders on Solana](https://www.helius.dev/blog/how-to-get-token-holders-on-solana)
- [Sec3 — Understanding SPL Associated Token Account](https://sec3.dev/blog/solana-programs-part-2-understanding-spl-associated-token-account)
- [Glassnode — Coin Days Destroyed](https://docs.glassnode.com/guides-and-tutorials/metric-guides/coin-days-destroyed)
- [Nansen — Smart Money Indicators](https://www.nansen.ai/post/smart-money-indicators-key-metrics-for-cryptocurrency-accumulation-investor-behavior-analysis)

### External references — Tokenomics & Unlocks (deepen-plan)

- [DefiLlama API Docs](https://api-docs.defillama.com/)
- [Messari — Token Unlocks](https://messari.io/token-unlocks)
- [Tokenomist Token Allocations](https://tokenomist.ai/)
- [DefiLlama Unlocks Dashboard](https://defillama.com/unlocks)

### Empirical evidence (citado en brainstorm y mantiene relevancia)

- Electric Capital Developer Report 2024 — correlación dev↔precio ≈ cero/negativa en horizonte swing.
- HYPE Q3 2025 fees $354.94M ATH 18-sept-2025; Q4 2025 fees -19% pese a -30/50% precio; primer unlock grande 29-nov-2025 (2 meses post-top).
- Análisis de 12 bull runs históricos (SOL, ZEC, AAVE, SUI, HYPE, TAO, TIA, JUP, PEPE, WIF, POPCAT, FARTCOIN) — patrón consolidation breakout aplica al ~60% (excluye memecoins parabólicos y post-TGE recientes).

# Crypto Insights

Position manager para swing trading sobre 30 proyectos crypto curados. Dos capas de signals (positioning leads, fundamentals lag), pesos por archetype, evolución activa vía feedback.

**Estado actual**: MVP funcional con pipeline diario + dashboard Streamlit. Fases 0-3 completas; Fase 4 (iteración con feedback + calibración) en curso.

## Setup (Windows)

Requisitos: Python 3.12+, [uv](https://docs.astral.sh/uv/) (`pip install uv` o instalador oficial Astral).

```powershell
# 1. Instalar Python 3.12 vía uv (si no lo tienes ya)
uv python install 3.12

# 2. Sincronizar entorno reproducible desde uv.lock
uv sync --all-groups

# 3. Configurar API keys (recomendado para batch completo)
copy .env.example .env  # editar con tus keys

# 4. Crear DB + aplicar migraciones + cargar watchlist + events
uv run crypto-insights init-db
uv run crypto-insights sync-watchlist

# 5. (Opcional) Personalizar data/events.yaml con tus unlocks curados
#    El default es data/events.example.yaml que sirve como fallback.

# 6. Ejecutar batch diario para hoy
uv run crypto-insights batch-daily

# 7. Lanzar dashboard Streamlit (http://localhost:8501)
uv run crypto-ui
# o equivalente: uv run streamlit run streamlit_app.py
```

### API keys (.env)

Almacenadas en `.env` con prefijo `CI_` (gitignored). Documentar en `.env.example`:

```
CI_GITHUB_TOKEN=ghp_...           # recomendado — sin esto github connector se salta
CI_COINGECKO_API_KEY=...           # opcional
CI_HELIUS_API_KEY=...              # smart money Solana (top holders DAS)
CI_MORALIS_API_KEY=...             # smart money EVM (ERC20 owners)
CI_ETHERSCAN_API_KEY=...           # opcional (multichain v2)
CI_ALCHEMY_API_KEY=...             # reserva como fallback de Moralis (Open Q1)
```

Sin keys de Helius/Moralis el batch corre igual: el smart money signal queda como **gap aislado** (`ConnectorError` registrado en `BATCHES.error_summary`), no rompe el resto del pipeline.

### Programar el batch en Windows (Task Scheduler)

1. Abrir **Task Scheduler** → Create Basic Task.
2. **Trigger**: Daily, 09:00 UTC (`11:00` Europe/Madrid en horario CET, `10:00` CEST).
3. **Action**: Start a program.
   - Program: `C:\Users\<user>\Documentos\Develop\Crypto_insights\.venv\Scripts\python.exe`
   - Arguments: `-m crypto_insights.cli batch-daily`
   - Start in: `C:\Users\<user>\Documentos\Develop\Crypto_insights`
4. **Settings**:
   - Wake the computer to run this task ✓
   - If the task fails, restart every 30 minutes (max 3 attempts)
5. **Logs**: stdout/stderr van a `data/logs/batch-YYYYMMDD.log` automáticamente vía structlog (ver `src/crypto_insights/logging_config.py`).

## CLI

Todos los subcomandos exponen `--json` para consumo agente-friendly (agent-native parity). Discovery: `crypto-insights tools`.

```powershell
# Setup
crypto-insights init-db                   # apply migrations (yoyo)
crypto-insights backup                    # backup data/crypto.db
crypto-insights sync-watchlist            # UPSERT watchlist.yaml -> projects table

# Inspección
crypto-insights list [--archetype X]      # list loaded projects
crypto-insights state SYMBOL              # current state for a project
crypto-insights batch-status --latest     # status of last batch
crypto-insights tools                     # capability discovery (MCP-style)

# Pipeline diario
crypto-insights batch-daily [--date YYYY-MM-DD] [--dry-run]

# Reports
crypto-insights viability                 # genera data/viability_report.md (Layer 2)
crypto-insights validate-breakout SYMBOL [--start YYYY-MM-DD] [--end ...]
                                          # retrospective consolidation_breakout

# Backfill manual (al añadir proyecto o validar histórico)
crypto-insights backfill-ohlcv [--symbol X] [--start 2023-01-01] [--end ...]
```

### Pipeline (Fases 0-3 implementadas)

**Connectors activos** (6 conectores con `aiolimiter` + `tenacity` retry):

| Source | Uso | Auth |
|---|---|---|
| `binance` | OHLCV diario (batch + backfill) | ninguna |
| `defillama` | TVL, fees, protocol category | ninguna |
| `github` | commits/contributors 30d/90d (dev abandonado) | `CI_GITHUB_TOKEN` |
| `hyperliquid` | funding rates + OI (z-score 30d) | ninguna |
| `helius` | Solana SPL top holders (DAS getTokenAccounts) | `CI_HELIUS_API_KEY` |
| `moralis` | EVM ERC20 top holders | `CI_MORALIS_API_KEY` |

**Events manuales** (DeFiLlama `/emissions` es Pro-only — Q11): unlocks curados en `data/events.yaml`, sincronizados a tabla `events` al inicio de cada batch.

**Layer 2 (viability)** — hard constraint de unlocks ≥5% ponderado (4-8 semanas) + dev abandonado + TVL collapse + listing reciente. Override `current_state='blocked'` con `reason_code` + `reason_data` estructurados (agent-native).

**Layer 1 (positioning)** — composite score por archetype con pesos hardcoded (`fusion/archetype_rules.py`). Signals derived:
- `atr_pct_14d` (Wilder)
- `consolidation_breakout` (4 criterios + BBW bottom decile + CMF>0 + RSI<50, look-ahead protected)
- `tvl_change_30d_pct` (proxy 7d hasta integrar `/tvl` endpoint)
- `funding_zscore_30d`
- `smart_money_delta_7d` (pipeline 5 pasos sobre helius/moralis)

**Hysteresis**: 2 batches consecutivos en estado nuevo antes de transitar (anti-flapping, ADR 0006).

**Gap policy** (ADR 0005): si <30% peso falta → renormalizar + warning `has_gaps`. Si ≥30% falta → estado `degraded` con `reason_code=GAP_DATOS`.

## Estructura

```
.
├── PLAN.md                           # plan vivo del proyecto
├── pyproject.toml                    # uv project + dep groups (PEP 735)
├── migrations/                       # yoyo SQL (forward + rollback)
│   ├── 0001-initial-schema.sql
│   └── 0002-ohlcv-history-and-holders.sql
├── data/
│   ├── watchlist.example.yaml        # template (commiteable)
│   ├── watchlist.yaml                # tu watchlist real (gitignored)
│   ├── events.example.yaml           # unlocks/listings template
│   ├── events.yaml                   # tu events curados (gitignored)
│   ├── labels.example.yaml           # seed CEX/DEX/bridges (Sol/EVM)
│   ├── labels/excluded_addresses.yaml  # tus overrides (gitignored)
│   ├── crypto.db                     # SQLite WAL (gitignored)
│   ├── backups/                      # auto-backups (gitignored)
│   └── validation/                   # output de validate-breakout (gitignored)
├── docs/
│   ├── brainstorms/                  # discovery sessions
│   ├── decisions/                    # ADRs (0001-0006 activos)
│   ├── plans/                        # planes de implementación
│   ├── feedback/                     # log diario de uso del MVP
│   │   └── open-questions/           # Q1-Q13 abiertas/resueltas
│   ├── learnings/                    # destilado de patrones repetidos
│   │   └── signal-performance.md     # validaciones empíricas de signals
│   └── plans/                        # implementación
├── src/crypto_insights/
│   ├── cli.py                        # typer CLI
│   ├── config.py                     # pydantic-settings
│   ├── db.py                         # SQLite + PRAGMAs (WAL, FK ON)
│   ├── models.py                     # dataclasses internos
│   ├── archetypes.py                 # archetype metadata
│   ├── watchlist.py                  # YAML loader + UPSERT
│   ├── logging_config.py             # structlog
│   ├── connectors/                   # uno por fuente externa
│   │   ├── base.py                   # Protocol + retry/rate-limit infra
│   │   ├── binance.py                # OHLCV daily
│   │   ├── defillama.py              # TVL, fees
│   │   ├── events_manual.py          # data/events.yaml -> events table
│   │   ├── github.py                 # commits/contributors
│   │   ├── helius.py                 # Solana DAS top holders
│   │   ├── hyperliquid.py            # funding/OI + history 30d
│   │   └── moralis.py                # EVM ERC20 top holders
│   ├── pipeline/
│   │   ├── batch.py                  # TaskGroup orchestrator + heartbeat
│   │   ├── persist.py                # UPSERT con COALESCE
│   │   ├── derived.py                # raw -> derived signals
│   │   ├── backfill.py               # OHLCV histórico paginado
│   │   └── validate.py               # validación retrospectiva breakout
│   ├── signals/
│   │   ├── indicators.py             # ATR Wilder, BBW, CMF, RSI, RVOL, range
│   │   ├── consolidation_breakout.py # detector 4 criterios + filtros
│   │   ├── funding.py                # z-score 30d
│   │   ├── unlocks.py                # hard constraint Layer 2
│   │   └── smart_money.py            # pipeline 5 pasos EOA filter + delta
│   ├── fusion/
│   │   ├── archetype_rules.py        # tabla de pesos por archetype
│   │   ├── layer1.py                 # composite score + state_from_scores
│   │   └── layer2.py                 # viability flag + blocked override
│   └── dashboard/                    # streamlit tabs + drill-down
├── tests/
│   ├── unit/                         # respx-based, no live network (63 verdes)
│   │   ├── connectors/               # binance, helius, moralis
│   │   ├── test_indicators.py        # hypothesis property tests
│   │   ├── test_smart_money.py       # pipeline 5 pasos end-to-end
│   │   ├── test_unlocks_layer2.py
│   │   ├── test_backfill.py
│   │   └── ...
│   └── fixtures/                     # *.json
└── streamlit_app.py                  # dashboard local (port 8501)
```

## Cómo se evoluciona el proyecto

1. Brainstorm inicial en `docs/brainstorms/`. El más reciente define la arquitectura actual.
2. Cada decisión estructural documentada en `docs/decisions/` (ADR).
3. Cada sesión de uso del MVP genera entrada en `docs/feedback/`.
4. Patrones que se repiten ≥3 veces se consolidan en `docs/learnings/`.
5. Cambios al plan se reflejan en `PLAN.md` con referencia al ADR correspondiente.

## Estado actual

- **Fase 0 — Foundations**: ✅ completa. Repo ejecutable end-to-end, Binance OHLCV, CLI + agent-native parity.
- **Fase 1 — Layer 2 (viability)**: ✅ completa. Hard constraint unlocks 5% ponderado / 4-8w (Messari category weights). HYPE/STRK blocked en producción.
- **Fase 2 — Layer 1 (positioning signals)**: ✅ completa. Indicators (ATR/BBW/CMF/RSI/RVOL), consolidation breakout, funding z-score, smart money pipeline 5 pasos. Pipeline integra derived + Layer 2 en transacción per-project.
- **Fase 3 — Fusión + Dashboard**: ✅ completa. archetype_rules con pesos, composite score, state_from_scores con gap policy híbrida, Streamlit con tabs por archetype + tab blocked + drill-down.
- **Fase 4 — Iteración con feedback**: en curso.
  - ✅ Backfill OHLCV ejecutable (`crypto-insights backfill-ohlcv --start 2023-01-01`).
  - ✅ Validación retrospectiva breakout (`crypto-insights validate-breakout SYMBOL`).
  - ✅ Primera validación empírica (ZEC/SUI/AAVE 2024-2025) → `docs/learnings/signal-performance.md`: thresholds ADR 0004 demasiado estrictos para crypto; calibración propuesta.
  - ⏳ **Smart money con keys reales**: pendiente añadir `CI_HELIUS_API_KEY` y `CI_MORALIS_API_KEY` para activar los conectores (pipeline + tests están listos).
  - ⏳ HYPE breakout 2024-2025: requiere fuente OHLCV alternativa (no está en Binance Spot — opciones: Bybit klines, Hyperliquid native, Coinbase si listed).
  - ⏳ Open Q2 (mindshare), Q3 (netflows): decisiones de roadmap pendientes del usuario.
- **Plan detallado**: [`docs/plans/2026-05-10-feat-crypto-position-manager-mvp-plan.md`](docs/plans/2026-05-10-feat-crypto-position-manager-mvp-plan.md)
- **ADRs activos**:
  - [0001 — two-layer signal model](docs/decisions/0001-two-layer-signal-model.md)
  - [0002 — stack técnico](docs/decisions/0002-stack-tecnico.md)
  - [0003 — unlocks hard constraint](docs/decisions/0003-unlocks-hard-constraint.md)
  - [0004 — consolidation breakout spec](docs/decisions/0004-consolidation-breakout-spec.md)
  - [0005 — gap policy híbrida](docs/decisions/0005-gap-policy.md)
  - [0006 — state machine transitions + hysteresis](docs/decisions/0006-state-machine-transitions.md)

## Testing

```powershell
uv run pytest                    # 63 tests, ~40s
uv run pytest -m "not slow"      # skip slow tests
uv run ruff check .              # lint
uv run ruff format --check .     # format check
uv run mypy src/                 # strict on connectors/, signals/, pipeline/
```

## Validación retrospectiva (Fase 4)

Para validar visualmente que el detector marca breakouts conocidos sobre histórico:

```powershell
# 1. Backfill OHLCV histórico (necesita ≥56 weeks para indicadores baseline)
uv run crypto-insights backfill-ohlcv --symbol SUI --start 2023-01-01 --end 2025-12-31

# 2. Validar breakout retrospectivamente (look-ahead protected)
uv run crypto-insights validate-breakout SUI --start 2024-06-01 --end 2025-12-31

# Output: data/validation/SUI-breakout.md con tabla densa + highlights score > 0
```

Resultados acumulados se sintetizan en [`docs/learnings/signal-performance.md`](docs/learnings/signal-performance.md).

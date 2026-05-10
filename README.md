# Crypto Insights

Position manager para swing trading sobre 30 proyectos crypto curados. Dos capas de signals (positioning leads, fundamentals lag), pesos por archetype, evolución activa vía feedback.

## Setup (Windows)

Requisitos: Python 3.12+, [uv](https://docs.astral.sh/uv/) (`pip install uv` o instalador oficial Astral).

```powershell
# 1. Instalar Python 3.12 vía uv (si no lo tienes ya)
uv python install 3.12

# 2. Sincronizar entorno reproducible desde uv.lock
uv sync --all-groups

# 3. Configurar API keys opcionales (recomendado: GitHub PAT)
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
CI_ALCHEMY_API_KEY=...             # Open Q1 — pendiente para Fase 2 (smart money ETH)
CI_HELIUS_API_KEY=...              # pendiente para Fase 2 (smart money Solana)
CI_ETHERSCAN_API_KEY=...           # opcional (multichain v2)
```

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

Todos los subcomandos exponen `--json` para consumo agente-friendly (agent-native parity).

```powershell
crypto-insights init-db                   # apply migrations
crypto-insights backup                    # backup data/crypto.db
crypto-insights sync-watchlist            # UPSERT watchlist.yaml → projects table
crypto-insights list [--archetype X]      # list loaded projects
crypto-insights state SYMBOL              # current state for a project
crypto-insights batch-status --latest     # status of last batch
crypto-insights batch-daily [--date YYYY-MM-DD] [--dry-run]
crypto-insights tools                     # capability discovery
```

## Estructura

```
.
├── PLAN.md                           # plan vivo del proyecto
├── pyproject.toml                    # uv project + dep groups (PEP 735)
├── migrations/                       # yoyo SQL (forward + rollback)
├── data/
│   ├── watchlist.example.yaml        # template (commiteable)
│   ├── watchlist.yaml                # tu watchlist real (gitignored)
│   ├── crypto.db                     # SQLite WAL (gitignored)
│   └── backups/                      # auto-backups (gitignored)
├── docs/
│   ├── brainstorms/                  # discovery sessions
│   ├── decisions/                    # ADRs (0001-0006 activos)
│   ├── plans/                        # planes de implementación
│   ├── feedback/                     # log diario de uso del MVP
│   └── learnings/                    # destilado de patrones repetidos
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
│   │   └── binance.py                # OHLCV daily (Phase 0)
│   └── pipeline/
│       ├── batch.py                  # TaskGroup orchestrator
│       └── persist.py                # UPSERT helpers
├── tests/
│   ├── unit/                         # respx-based, no live network
│   ├── integration/                  # saved JSON fixtures
│   └── fixtures/                     # *.json
└── streamlit_app.py                  # dashboard (Phase 3, pendiente)
```

## Cómo se evoluciona el proyecto

1. Brainstorm inicial en `docs/brainstorms/`. El más reciente define la arquitectura actual.
2. Cada decisión estructural documentada en `docs/decisions/` (ADR).
3. Cada sesión de uso del MVP genera entrada en `docs/feedback/`.
4. Patrones que se repiten ≥3 veces se consolidan en `docs/learnings/`.
5. Cambios al plan se reflejan en `PLAN.md` con referencia al ADR correspondiente.

## Estado actual

- **Fase 0 — Foundations**: ✅ completa. Repo ejecutable end-to-end con Binance connector.
- **Fase 1 — Layer 2 (viability)**: pendiente.
- **Fase 2 — Layer 1 (positioning signals)**: pendiente.
- **Fase 3 — Fusión + Dashboard**: pendiente.
- **Plan detallado**: [`docs/plans/2026-05-10-feat-crypto-position-manager-mvp-plan.md`](docs/plans/2026-05-10-feat-crypto-position-manager-mvp-plan.md)
- **ADRs activos**: 0001 (two-layer model), 0002 (stack), 0003 (unlocks hard constraint), 0004 (consolidation breakout), 0005 (gap policy), 0006 (state machine)

## Testing

```powershell
uv run pytest                    # full suite
uv run pytest -m "not slow"      # skip slow tests
uv run ruff check .              # lint
uv run ruff format --check .     # format check
uv run mypy src/                 # strict on connectors/, signals/, pipeline/
```

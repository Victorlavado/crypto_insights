# Crypto Position Manager — Plan de implementación

Documento vivo. Refleja el estado actual del proyecto y se actualiza con cada cambio estructural (referencia ADRs en `docs/decisions/`).

## Visión

Position manager para swing trading sobre 30 proyectos crypto curados manualmente. Un dashboard pull (no push) con estado por proyecto: `acumulación / aceleración / distribución / colapso / reset`.

Brainstorm origen: [`docs/brainstorms/2026-05-09-crypto-tracker-brainstorm.md`](docs/brainstorms/2026-05-09-crypto-tracker-brainstorm.md)

**Plan detallado (deepened, decisiones cerradas)**: [`docs/plans/2026-05-10-feat-crypto-position-manager-mvp-plan.md`](docs/plans/2026-05-10-feat-crypto-position-manager-mvp-plan.md)

**ADRs activos** (decisiones estructurales materializadas):
- [ADR 0001 — Modelo dos capas](docs/decisions/0001-two-layer-signal-model.md)
- [ADR 0002 — Stack técnico (uv + SQLite WAL + Streamlit)](docs/decisions/0002-stack-tecnico.md)
- [ADR 0003 — Hard constraint unlocks (5%/4-8w + ponderación categorías)](docs/decisions/0003-unlocks-hard-constraint.md)
- [ADR 0004 — Consolidation breakout spec (4 criterios + look-ahead)](docs/decisions/0004-consolidation-breakout-spec.md)
- [ADR 0005 — Política de gap (signal=None)](docs/decisions/0005-gap-policy.md)
- [ADR 0006 — State machine + hysteresis](docs/decisions/0006-state-machine-transitions.md)

**Open questions**: 12 de 13 resueltas. Pendientes:
- **Q11** (Fase 1): verificación empírica DeFiLlama unlocks free vs Pro-only.
- **Q10 parcial**: 29 proyectos en watchlist (target 30 — añadir 1 cuando se confirme).

## Roadmap

### Fase 0 — Foundations ✅ COMPLETADA (2026-05-10)
- [x] Definir watchlist v1 (30 proyectos con archetype tag) → `data/watchlist.yaml`
- [x] Setup repo Python: `pyproject.toml`, ruff, mypy, pytest, .gitignore
- [x] SQLite schema completa: `projects`, `batches`, `raw_snapshots`, `derived_signals`, `project_state`, `project_state_history`, `events`
- [x] CLI: `init-db`, `sync-watchlist`, `list`, `state`, `batch-status`, `batch-daily`, `backup`, `tools`
- [x] Conector Binance OHLCV (15 proyectos válidos en Spot; resto en _NOT_ON_BINANCE_SPOT)
- [x] Pipeline batch con TaskGroup + heartbeat + cleanup huérfanos + UPSERT COALESCE
- [x] Tests: 16 verdes

### Fase 1 — Layer 2 / Filtro de viabilidad ✅ COMPLETADA (2026-05-10)
- [x] Conector DeFiLlama: TVL/category via /protocols (free)
- [x] Conector GitHub: commits 30/90d, contributors (requiere PAT)
- [x] Conector unlocks: **events_manual** YAML (Q11 resolved: DeFiLlama /emissions = Pro-only $300/mes)
- [x] signals/unlocks.py + fusion/layer2.py con hard constraint 5% ponderado / 4-8w
- [x] CLI `viability`: tabla densa + drill-down → `data/viability_report.md`
- [x] HYPE/STRK blocked confirmados con events.yaml curado

### Fase 2 — Layer 1 / Signals de positioning
- [ ] OHLCV semanal (Binance API o CoinGecko) + cálculo consolidation breakout
- [ ] Funding/OI: Hyperliquid API → fallback Binance
- [ ] Smart money: scrape semanal Etherscan/Solscan top 50 holders + delta
- [ ] CEX netflows como proxy complementario
- [ ] Mindshare: Kaito scrape o free tier

### Fase 3 — Fusión por archetype + Dashboard
- [ ] Reglas por archetype con pesos hardcoded (Opción 1 del brainstorm)
- [ ] Cálculo de estado por proyecto
- [ ] CLI dashboard: tabla con `rich` o markdown report regenerado
- [ ] Snapshot histórico para review semanal

### Fase 4 — Iteración con feedback
- [ ] Primer ciclo de review semanal con `docs/feedback/` activo
- [ ] Ajuste de pesos basado en aciertos/errores
- [ ] Considerar Opción 3 híbrida (LLM-reasoner) si reglas duras dejan dinero sobre la mesa

### Fase 5+ (post-MVP)
- [ ] Auto-discovery desde categorías CoinGecko (Opción A(ii))
- [ ] Alertas push (Telegram/email)
- [ ] Backtest framework
- [ ] LLM-reasoner híbrido para fusión contextual

## Mecanismo de evolución

```
USO DEL MVP
    ↓
docs/feedback/YYYY-MM-DD-N.md         (cada sesión, formato libre + template)
    ↓
[Review semanal]
    ↓
docs/learnings/*.md                   (patrones que se repiten 3+ veces)
    ↓
[Cambio estructural detectado]
    ↓
docs/decisions/NNNN-titulo.md         (ADR formal)
    ↓
PLAN.md + código actualizados
```

Reglas:
- Un signal que falla 3 veces consecutivas se reweighta o se elimina. Documentado en `learnings/signal-performance.md`.
- Un patrón que aparece 3+ veces en feedback entra en `learnings/pattern-library.md`.
- Cualquier cambio que afecte arquitectura (nuevo source, cambio de modelo, redefinición de archetype) requiere ADR.

## Stack técnico (confirmado en ADR 0002)

- **Lenguaje**: Python 3.12+
- **Project mgmt**: uv + src/ layout + `[dependency-groups]` PEP 735
- **HTTP**: httpx async + aiolimiter + tenacity
- **Storage**: SQLite WAL + yoyo-migrations
- **TA**: pandas + numpy (indicadores a mano)
- **Dashboard**: Streamlit + `st.connection("sql")` + `@st.cache_data`
- **CLI**: typer (re-evaluar argparse en Fase 3 si CLI <5 comandos)
- **Tests**: pytest + respx + JSON fixtures (no VCR) + hypothesis (acotado a indicadores)
- **Logging**: structlog (batch JSON) + logging stdlib (UI)
- **Scheduling**: Windows Task Scheduler (no APScheduler)

Detalles completos y rechazos justificados en [ADR 0002](docs/decisions/0002-stack-tecnico.md).

## Open questions resueltas

Todas las open questions del plan original tienen status registrado en [`docs/feedback/open-questions/README.md`](docs/feedback/open-questions/README.md):

- ✅ Daily batch a 9:00 UTC
- ✅ OHLCV histórico completo (Binance da hasta 2017+)
- ✅ Rate limiting con aiolimiter + tenacity
- ✅ Streamlit local con tabla densa + drill-down
- ✅ Top holders ETH: Alchemy primaria + Moralis fallback
- ✅ Mindshare: gap explícito (Kaito sin free tier 2026)
- ✅ Consolidation breakout: 4 criterios + ventana 6 weeks (Q6)
- ✅ Hard constraint unlocks: 5% ponderado/4-8w
- ✅ Gap policy híbrida (renormalizar <30%, degraded ≥30%)
- ✅ State machine: matriz + hysteresis 2-batches

**Pendiente verificación empírica (Q11)**: DeFiLlama `/emissions` free vs Pro-only — ejecutar en primer commit de Fase 1.

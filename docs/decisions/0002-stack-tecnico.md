# ADR 0002 — Stack técnico del MVP

**Fecha**: 2026-05-10
**Estado**: Aceptado
**Supersede**: —
**Origen**: [`docs/plans/2026-05-10-feat-crypto-position-manager-mvp-plan.md`](../plans/2026-05-10-feat-crypto-position-manager-mvp-plan.md) + research deepen-plan

## Contexto

El MVP requiere stack Python para pipeline batch diario + dashboard local. Hay múltiples opciones para cada capa (Poetry/uv, SQLite/DuckDB/Postgres, rich/Streamlit/Markdown, etc.). Decidir antes de Fase 0 evita re-trabajo.

## Decisión

| Capa | Elección | Alternativas descartadas | Razón |
|---|---|---|---|
| Runtime | Python 3.12+ | Python 3.11 | Type hints maduros, asyncio TaskGroup |
| Project mgmt | **uv** + src/ layout + `[dependency-groups]` PEP 735 | Poetry, hatch, rye, PDM | Lock reproducible, sin overhead Poetry, PEP 735 default 2026 |
| HTTP async | **httpx** | aiohttp, requests sync | Único cliente async maduro con HTTP/2 y retry hooks |
| Rate limiting | **aiolimiter** (leaky bucket per-host) | aiometer, asyncio-throttle | Más estricto que token bucket para APIs sensibles a burst |
| Retry | **tenacity** con `wait_exponential_jitter` | manual, backoff lib | Detecta async automáticamente, jitter evita thundering herd |
| Storage | **SQLite WAL** + **yoyo-migrations** | DuckDB, Postgres | DuckDB 10× lento en inserts diarios; Postgres overkill para 30 proyectos |
| TA | **pandas + numpy** (indicadores a mano) | pandas-ta, TA-Lib | Auditable; fórmulas <10 LoC c/u; pandas-ta original stalled |
| Dashboard | **Streamlit** + `st.connection("sql")` + `@st.cache_data` | rich/typer CLI, markdown, FastAPI custom | Iteración rápida, drill-down interactivo, decisión usuario |
| Logging | **structlog** (JSON archivo) batch + **logging** stdlib UI | loguru | Queryable post-mortem; loguru mejor para human-only |
| Tests | **pytest** + **respx** (unit) + **respx + JSON fixtures** (integration, sin VCR) + **hypothesis** (acotado a indicadores) | pytest-vcr | VCR cassettes envejecen y mienten — JSON fixtures manuales más estables |
| Lint | **ruff** (linter + formatter) | black + flake8 + isort | Una herramienta, configuración mínima |
| Type check | **mypy --strict** en `connectors/`, `pipeline/`, `signals/`; **mypy** suelto en `streamlit_app.py` | pyright | Strict donde más fallan los tipos (parsing externo + matemática) |
| Config | **pydantic-settings** + `.env` | python-dotenv plain, os.environ | Validación at-startup; 6+ env vars justifica |
| CLI | **typer** | argparse, click | Re-evaluar en Fase 3: si CLI <5 comandos, switch a argparse |
| Scheduling | **Windows Task Scheduler** ejecuta `uv run crypto-insights batch-daily` | APScheduler, schedule | Stateless, OS-managed, sobrevive reboots |

## Consecuencias

- **Positivas**: stack estándar 2026, no exótico; cada elección defendible con evidencia (research deepen-plan); reproducibilidad vía `uv.lock`.
- **Negativas**: dependency footprint moderado (~15 deps directas). Ningún componente es "zero-dep".
- **Riesgo**: SQLite single-writer puede ser cuello de botella si se escala >100 proyectos. Mitigación: arquitectura long-format permite migrar a Postgres con migration directa de schema.

## Rechazos justificados (research deepen-plan)

- **DuckDB**: 10× más lento que SQLite en inserts diarios single-row. Patrón híbrido (DuckDB attach SQLite) si en Fase 4 emergen queries analíticas pesadas.
- **TA-Lib**: instalación nativa Windows pesada; performance irrelevante para 30 proyectos.
- **VCR.py**: cassettes envejecen y mienten; respx + JSON fixtures manuales más estables.
- **APScheduler**: requiere proceso Python siempre vivo; anti-pattern para batch diario en laptop personal.
- **Poetry**: sin ventaja sobre uv en 2026; uv lock más rápido y `[dependency-groups]` es estándar PEP 735.

## Re-evaluación futura

- **Typer → argparse** si CLI termina con ~5 comandos en Fase 3.
- **structlog → logging stdlib** si los logs nunca se usan más allá de `tail -f`.
- **mypy strict** scope ampliado a `dashboard/` si emerge bugs de tipos.

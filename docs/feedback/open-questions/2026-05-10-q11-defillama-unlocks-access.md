---
question_id: Q11
date: 2026-05-10
plan: docs/plans/2026-05-10-feat-crypto-position-manager-mvp-plan.md
blocking: Fase 1 (Layer 2 hard constraint de unlocks)
status: RESOLVED (2026-05-10) — DefiLlama Pro confirmado, MVP arranca con manual events YAML
discovered_in: deepen-plan (research conflicto)
resolved_in: docs/plans/2026-05-10-feat-crypto-position-manager-mvp-plan.md (Fase 1)
---

# Q11 — DeFiLlama Unlocks: free vs Pro-only

## Contexto

Durante el `/deepen-plan`, dos research agents independientes dieron respuestas contradictorias sobre el endpoint `/emissions` de DeFiLlama. El plan original asumió free.

## Verificación empírica (2026-05-10)

```bash
$ curl -sS -w "HTTP %{http_code}\n" "https://api.llama.fi/emissions" --max-time 30
HTTP 402
Upgrade to the paid API plan at https://defillama.com/subscription
```

**Resultado: Pro-only confirmado** (HTTP 402 Payment Required).

Tokenomist.ai también explorado brevemente: `/api/projects` devuelve 404 con HTML genérico (Next.js SPA, no public REST API trivialmente descubrible).

## Decisión (2026-05-10)

Para el MVP, **manual events YAML** (`data/events.yaml`) como fuente primaria:

- Victor mantiene un YAML con los unlocks futuros de los 30 proyectos curados (~30-90 eventos para los próximos 12 meses).
- Schema alineado a ADR 0003 (allocation_category + magnitude_pct) y a la tabla EVENTS.
- Connector `events_manual` lee el YAML y hace UPSERT en `EVENTS` (dedupe por `(project, event_type, event_date, source='manual')`).
- Coste: ~30-45 min para popular inicialmente. Mantenimiento: ~5 min/semana al añadir eventos descubiertos en uso.

**Por qué esto antes de scraping**:

1. **Honestidad de datos**: Victor sabe qué unlocks le importan (top-5-by-magnitude por proyecto), no necesitamos todos los eventos del calendario.
2. **Foundation deuda baja**: scrape de DefiLlama HTML es ToS-borderline + frágil ante Next.js re-renders. Scrape de Tokenomist es scrape de SPA con datos en `__NEXT_DATA__` — viable pero requiere headless browser o reverse-engineering del payload JSON inline. Trabajo de ~3-4h con riesgo de breakage en 1-3 meses.
3. **MVP first, automation later**: si el feedback log muestra que Victor está perdiendo entradas por no haber añadido un unlock al YAML, ahí es cuando vale la pena automatizar.

## Plan de evolución (post-MVP)

Si Fase 4 muestra que la maintenance del YAML es bottleneck:

- **Plan B** (next): scrape de `defillama.com/unlocks` parseando `__NEXT_DATA__` JSON inline (Next.js público). Estable mientras Llama no cambie de SSG. Re-evaluar trimestralmente.
- **Plan D** (si emerge revenue): $300/mes Pro API.

## Acción inmediata para Fase 1

- [x] Verificar empíricamente — DONE 2026-05-10.
- [ ] Crear `data/events.example.yaml` con 3-5 ejemplos (HYPE, STRK, SUI) — Fase 1.
- [ ] Connector `events_manual.py` que lee YAML y popula EVENTS — Fase 1.
- [ ] Cerrar este Q.

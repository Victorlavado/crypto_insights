---
question_id: Q2
date: 2026-05-10
plan: docs/plans/2026-05-10-feat-crypto-position-manager-mvp-plan.md
blocking: Fase 3 (fusión por archetype — mindshare es signal con peso 0.40 en memecoin-brand y 0.50 en post-tge)
status: open
---

# Q2 — Mindshare sin Kaito gratis

## Contexto

El brainstorm asumía Kaito (scrape o free tier) como fuente principal de mindshare. Research 2026 confirma:

- **Kaito**: NO hay free tier API. Pro es paid (precios no públicos, enterprise). Scraping bloqueado por Cloudflare/JS-rendering, frágil + ToS-violation.
- **LunarCrush**: free tier discontinuado en 2024. Individual plan ~$24/mes mínimo.
- **Santiment Sanbase free**: 1000 calls/mes, métricas sociales básicas (`social_volume`, `social_dominance`) — mucho más débiles que Kaito mindshare score.

## Opciones

### (a) Gap explícito + redistribuir pesos
- Mindshare = NO disponible para MVP.
- Para `memecoin-brand`: redistribuir 0.40 a smart_money_delta (sube a 0.60) y holder_growth (sube a 0.10 si lo añadimos).
- Para `post-tge`: redistribuir 0.50 a smart_money_delta (sube a 0.60) y holder_growth.
- **Pro**: 0 coste, MVP arranca limpio.
- **Contra**: degrada calidad sustancialmente para los dos archetypes donde mindshare era central.

### (b) Santiment Sanbase free como proxy débil
- 1000 calls/mes / 30 proyectos / 30 días ≈ 1.1 fetches/proyecto/día — alcanza para daily batch.
- Métrica `social_volume` (menciones agregadas) o `social_dominance`.
- **Pro**: alguna señal mejor que ninguna.
- **Contra**: la métrica no es Kaito-equivalente; señales de attention agregada no capturan velocidad ni cambio de tono.

### (c) Budget mensual paid
- LunarCrush Individual ($24/mes) o Santiment Pro ($49/mes).
- **Pro**: signal de calidad real.
- **Contra**: coste recurrente para validar primero que el MVP da edge.

## Recomendación

**(a) para Fase 1-3 + (b) si Open Q3 también va por Santiment** (amortizamos el registro).

Después de **4 semanas de feedback**:
- Si feedback log para memecoin-brand y post-tge muestra que las decisiones se tomaron principalmente fuera de la herramienta (señales pobres), evaluar **(c)**.
- Si las decisiones funcionaron sin mindshare, mantener **(a)** indefinidamente.

## Acción esperada

Confirmar (a), (b) o (c). Si (c), confirmar provider y presupuesto aceptable.

---
question_id: Q13
date: 2026-05-10
plan: docs/plans/2026-05-10-feat-crypto-position-manager-mvp-plan.md
blocking: Fase 3 (fusión + dashboard)
status: open (recomendación con default razonable)
discovered_in: deepen-plan (architecture-strategist review)
---

# Q13 — Matriz de transiciones legales del state machine

## Contexto

El plan define 6 estados (`acumulación / aceleración / distribución / colapso / reset / blocked`) más los 2 nuevos `degraded / unknown` (Q12). Pero NO define qué transiciones son legales. Sin esto:

- Dos batches consecutivos pueden producir oscilación `acumulación↔reset` si el composite_score está cerca del boundary 0.2.
- ¿Puede pasarse de `colapso` directamente a `aceleración` saltando `reset`? Probablemente no realista.
- ¿`blocked` libera automáticamente cuando pasa el unlock?

## Matriz propuesta

```
                  → acumulación  aceleración  distribución  colapso  reset  blocked  degraded
acumulación          ✓              ✓             ✓            -        -      ✓        ✓
aceleración          ✓              ✓             ✓            -        -      ✓        ✓
distribución         -              -             ✓            ✓        -      ✓        ✓
colapso              -              -             -            ✓        ✓      ✓        ✓
reset                ✓              -             -            -        ✓      ✓        ✓
blocked              ✓              ✓             ✓            -        ✓      ✓        ✓
degraded             ✓              ✓             ✓            ✓        ✓      ✓        ✓
```

**Reglas adicionales**:
- `colapso → reset`: requiere `|composite_score| < 0.2` sostenido ≥4 batches.
- `blocked` libera automáticamente cuando todos los unlocks de la ventana 4-8w pasan (event_date < today).
- `degraded` libera al recuperarse las fuentes faltantes.
- **Hysteresis**: toda transición no-`blocked`/`degraded` requiere 2 batches consecutivos en estado nuevo antes de aplicarse. Campo `batches_in_state` en PROJECT_STATE.

## Materialización

ADR 0006 — State machine y transiciones. Antes de Fase 3.

## Acción esperada

Confirmar matriz o proponer cambios (ej. "permitir distribución → aceleración directo si hay reversal violento"). Confirmar hysteresis 2-batches.

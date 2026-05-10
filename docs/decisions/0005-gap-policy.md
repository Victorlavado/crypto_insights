# ADR 0005 — Política de gap en signals (signal=None)

**Fecha**: 2026-05-10
**Estado**: Aceptado
**Supersede**: —
**Origen**: detectado por architecture-strategist en deepen-plan; resuelto en Q12

## Contexto

Cuando una fuente externa (Hyperliquid, DeFiLlama, Helius, etc.) cae o devuelve error transient durante un batch, el connector puede dejar el signal correspondiente como `None`. Sin política explícita, hay tres semánticas incompatibles para la fusión:

- (a) Renormalizar pesos sobre signals presentes → bias hacia signals supervivientes.
- (b) Tratar None como 0 → penaliza falsamente proyecto sano si la fuente cae globalmente.
- (c) Estado `degraded` separado + renormalización condicional → más honesto, rompe enumeración.

## Decisión

**Política híbrida basada en porcentaje de peso faltante**:

```
peso_faltante = SUM(peso[signal] for signal in archetype_signals if signal_value IS NULL)

if peso_faltante < 0.30 (i.e., <30% del peso total):
    composite_score = SUM(peso_norm × value) where peso_norm = peso / (1 - peso_faltante)
    has_gaps = True
    state se calcula normalmente; dashboard muestra warning visible "scores parciales: faltan X, Y"

elif peso_faltante >= 0.30:
    composite_score = NULL
    current_state = "degraded"
    reason_code = "GAP_DATOS"
    reason_data = {missing_signals: ["funding", "mindshare"], total_weight_missing: 0.45}
    has_gaps = True
```

## Schema implications

`PROJECT_STATE` añade columnas:
- `has_gaps BOOLEAN NOT NULL DEFAULT 0` — flag para badge visual incluso si <30%.
- `current_state` enum incluye `degraded`.
- `reason_code` enum incluye `GAP_DATOS`.

## Liberación de `degraded`

`degraded` libera automáticamente cuando las fuentes faltantes vuelven (signal_value IS NOT NULL en próximo batch). Estado siguiente se calcula desde scores normalmente.

## Excepción: fuente caída sostenida >7 días

Si una fuente lleva ≥7 batches consecutivos devolviendo NULL para todos los proyectos, registrar `WARN: fuente X caída desde fecha Y` en log y enviar email opcional vía Task Scheduler. Posible decisión: marcar fuente como `optional=False` temporalmente para no inflar `peso_faltante` artificialmente.

## Consecuencias

- **Positivas**: cuantifica honestamente la fiabilidad del score; previene "score alto fantasma" cuando faltan signals importantes; agente puede filtrar `WHERE has_gaps = 0` para decisiones críticas.
- **Negativas**: añade un estado más al state machine (`degraded`); requiere lógica condicional en fusion.
- **Riesgo**: threshold 30% es educated guess. Recalibrable basado en feedback (ej: si "degraded" aparece demasiado, subir a 40%; si signals importantes se ocultan en renormalización, bajar a 20%).

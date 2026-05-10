# ADR 0006 — State machine: matriz de transiciones + hysteresis

**Fecha**: 2026-05-10
**Estado**: Aceptado
**Supersede**: —
**Origen**: detectado por architecture-strategist en deepen-plan; resuelto en Q13

## Contexto

El plan define 8 estados posibles para `PROJECT_STATE.current_state`:

- `acumulación`, `aceleración`, `distribución`, `colapso`, `reset` (estados normales)
- `blocked` (override Layer 2, hard constraint)
- `degraded` (gap policy, ADR 0005)
- `unknown` (estado inicial sin batches aún)

Sin matriz de transiciones legales, dos batches consecutivos pueden producir oscilación `acumulación↔reset` cerca del boundary 0.2 del composite_score, o transiciones no realistas (ej. `colapso → aceleración` directo).

## Decisión

### Matriz de transiciones legales

```
                  → acumulación  aceleración  distribución  colapso  reset  blocked  degraded
acumulación          ✓              ✓             ✓            -        -      ✓        ✓
aceleración          ✓              ✓             ✓            -        -      ✓        ✓
distribución         -              -             ✓            ✓        -      ✓        ✓
colapso              -              -             -            ✓        ✓      ✓        ✓
reset                ✓              -             -            -        ✓      ✓        ✓
blocked              ✓              ✓             ✓            -        ✓      ✓        ✓
degraded             ✓              ✓             ✓            ✓        ✓      ✓        ✓
unknown              ✓              ✓             ✓            ✓        ✓      ✓        ✓
```

### Reglas adicionales

1. **`colapso → reset`**: requiere `|composite_score| < 0.2` sostenido **≥4 batches** (no solo 2). Refleja período de digestión post-drawdown.
2. **`reset → aceleración`**: BLOQUEADO. De reset hay que pasar por `acumulación` primero. Anti-FOMO sobre el primer pump.
3. **`distribución → acumulación`**: BLOQUEADO. Para volver a acumular hay que pasar por `colapso → reset → acumulación`. Refleja estructura empírica crypto: piernas separadas por drawdowns 50-70%, no reversiones limpias.
4. **`blocked` libera automáticamente** cuando todos los unlocks de la ventana 4-8w pasan (event_date < today). Estado siguiente se recalcula desde scores normalmente.
5. **`degraded` libera automáticamente** cuando las fuentes faltantes vuelven (peso_faltante < 30%, ver ADR 0005).
6. **Hysteresis**: toda transición no-`blocked`/`degraded` requiere **2 batches consecutivos** en el estado nuevo antes de aplicarse. Campo `batches_in_state` en `PROJECT_STATE` cuenta días en estado actual; cuando un nuevo estado-candidato emerge, se trackea aparte y solo se aplica al 2º batch consecutivo.

### Pseudocódigo

```python
def apply_state_with_hysteresis(project, computed_state, batch_id, conn):
    current = get_current_state(project)
    if computed_state == current.state:
        increment_batches_in_state(project, batch_id)
        return

    if not is_legal_transition(current.state, computed_state):
        log.warning("illegal_transition_blocked",
                    project=project.symbol,
                    from_=current.state, to=computed_state)
        return  # mantener estado actual

    # estados sin hysteresis: blocked, degraded (override inmediato)
    if computed_state in ("blocked", "degraded"):
        transition_to(project, computed_state, batch_id, batches_in_state=1)
        return

    # hysteresis: requiere candidato sostenido 2 batches
    pending = get_pending_state(project)
    if pending and pending.state == computed_state and pending.batch_id != batch_id:
        # 2º batch consecutivo: aplicar transición
        transition_to(project, computed_state, batch_id, batches_in_state=1)
        clear_pending_state(project)
    else:
        # 1er batch del candidato: registrar pending
        set_pending_state(project, computed_state, batch_id)
```

## Schema implications

`PROJECT_STATE` añade:
- `batches_in_state INT NOT NULL DEFAULT 1` — contador de batches en estado actual.
- `pending_state TEXT NULL` — estado-candidato detectado en último batch (NULL si current==computed).
- `pending_state_batch_id TEXT NULL` — batch_id del primer detect del pending.

## Casos prácticos

### HYPE 2025 (legal en matriz)

```
sept 2025  → aceleración (composite +0.7, breakout)
mid-oct    → distribución (smart money distribuyendo, funding extremo)
late-oct   → blocked (unlock 11.2% en ventana 4-8w)
dec 2025   → blocked liberado → distribución (scores siguen bajistas)
ene 2026   → colapso (drop 50%)
feb-mar    → reset (consolidación lateral, |score|<0.2 sostenido)
mar 2026   → acumulación (smart money empieza a comprar)
abr 2026   → aceleración (breakout nuevo)
```

### Caso bloqueado por matriz: SOL Q3 2025 hipotético

`distribución → aceleración` directo (rebote violento sin pasar por colapso) está bloqueado. El sistema mantendría `distribución` esperando un cambio canónico. Trade-off aceptado: **menos false positives en bear traps, a coste de perder algunos rebotes violentos**.

## Consecuencias

- **Positivas**: cero ruido en boundaries (anti-flapping); transiciones reflejan estructura empírica crypto; estado actual auditable post-mortem.
- **Negativas**: 1 día de retraso en transiciones reales (hysteresis); puede perder algunos reversals violentos `distribución → aceleración`.
- **Riesgo**: si en feedback se documenta un reversal-violento perdido por la matriz 3+ veces, abrir ADR para añadir transición `distribución → aceleración` con condición especial (ej. `composite_score > 0.5` en un solo batch).

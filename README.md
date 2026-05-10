# Crypto Insights

Position manager para swing trading sobre proyectos crypto curados. Dos capas de signals (positioning leads, fundamentals lag), pesos por archetype, evolución activa vía feedback.

## Estructura

```
.
├── PLAN.md                           # plan vivo del proyecto
├── data/
│   ├── watchlist.example.yaml        # template de los 30 proyectos curados
│   └── watchlist.yaml                # tu watchlist real (no commitear si tiene info sensible)
├── docs/
│   ├── brainstorms/                  # discovery sessions (input al plan)
│   ├── decisions/                    # ADRs — cambios estructurales
│   ├── feedback/                     # log diario de uso del MVP
│   └── learnings/                    # destilado de patrones que se repiten
└── src/                              # código (a implementar)
```

## Cómo se evoluciona el proyecto

1. Brainstorm inicial vivido en `docs/brainstorms/`. El más reciente define la arquitectura actual.
2. Cada decisión estructural documentada en `docs/decisions/` (ADR).
3. Cada sesión de uso del MVP genera entrada en `docs/feedback/`.
4. Patrones que se repiten ≥3 veces se consolidan en `docs/learnings/`.
5. Cambios al plan se reflejan en `PLAN.md` con referencia al ADR correspondiente.

## Estado actual

- **Fase 0 — Foundations**: en curso. Ver [PLAN.md](PLAN.md).
- **Brainstorm origen**: [`docs/brainstorms/2026-05-09-crypto-tracker-brainstorm.md`](docs/brainstorms/2026-05-09-crypto-tracker-brainstorm.md)
- **ADR activo**: [`docs/decisions/0001-two-layer-signal-model.md`](docs/decisions/0001-two-layer-signal-model.md)

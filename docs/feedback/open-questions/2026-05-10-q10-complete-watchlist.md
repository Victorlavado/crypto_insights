---
question_id: Q10
date: 2026-05-10
plan: docs/plans/2026-05-10-feat-crypto-position-manager-mvp-plan.md
blocking: Fase 0 (loader necesita el archivo final)
status: open
---

# Q10 — Completar watchlist a 30 proyectos

## Contexto

`data/watchlist.example.yaml` tiene actualmente **26 proyectos** con thesis y archetype. Faltan 4 para llegar a 30 (decisión MVP del brainstorm: A(i) = 30 proyectos curados).

Watchlist actual:
HYPE, ZEC, PENGU, NEAR, TAO, VIRTUAL, VVV, AKT, GRASS, RENDER, elizaOS, MEGA, MON, BTC, SYRUP, FXN, HNT, JUP, CHIP, AAVE, PENDLE, FARTCOIN, ENA, PUMP, TON.

(Nota: cuenta 25 en el archivo + algún otro intermedio que pueda haber pasado por alto. Ver `data/watchlist.example.yaml` autoritativo.)

## Candidatos sugeridos (de proyectos mencionados en brainstorm o relevantes)

Por archetype faltante / sub-representado:

- **`l1-maduro`** (solo BTC, NEAR, TON listados): SOL, ETH, SUI, AVAX.
- **`memecoin-brand`** (solo PENGU, FARTCOIN listados): WIF, POPCAT, PEPE, DOGE.
- **`tesis-macro` AI** (bien representado: TAO, VIRTUAL, VVV, GRASS, RENDER, elizaOS, AKT, HNT, CHIP): no añadir más, ya hay sobrepeso.
- **`defi-blue-chip`** (SYRUP, JUP, AAVE, PENDLE, ENA): MORPHO, MAKER, UNI, LDO.
- **`post-tge`** (MEGA, MON): variar — algún post-TGE caliente reciente.

## Recomendación

**4 candidatos para discusión**:
1. **SOL** (l1-maduro) — referente para signals L1; sirve como benchmark.
2. **WIF** o **POPCAT** (memecoin-brand) — más representación memecoin para validar archetype.
3. **MORPHO** o **LDO** (defi-blue-chip) — diversifica blue-chips fuera de lending puro.
4. **El cuarto: a tu elección** — proyecto específico que estás vigilando ahora mismo.

## Acción esperada

Listar los 4 (o más) que quieres añadir, y confirmar el archetype de cada uno. Crearé `data/watchlist.yaml` definitivo en Fase 0.

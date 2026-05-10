---
question_id: Q1
date: 2026-05-10
plan: docs/plans/2026-05-10-feat-crypto-position-manager-mvp-plan.md
blocking: Fase 2 (signal smart money en proyectos ETH/Base/Arbitrum)
status: open
---

# Q1 — Top holders Ethereum/Base/Arbitrum

## Contexto

El brainstorm asumía Etherscan/Solscan como fuentes primarias de top holders por contrato. Research 2026 confirma que **Etherscan free NO expone el endpoint de top holders** — está detrás del Pro Account API ($199/mes mínimo).

Lista de proyectos en watchlist afectados (chain ETH/Base/Arbitrum): AAVE, PENDLE, ENA, SYRUP, RENDER, FXN, CHIP, VIRTUAL, VVV.

## Opciones

### (a) Moralis free (~25k Compute Units/día)
- **Endpoint**: `/erc20/{address}/owners`
- **Cubre**: Ethereum, Base, Polygon, Arbitrum, BSC, Optimism, Avalanche.
- **Pro**: free tier funcional sin tarjeta.
- **Contra**: 25k CU/día puede agotarse si se hacen muchas refreshes (1 fetch top-100 holders típicamente cuesta 10-50 CU).

### (b) Alchemy free (300M CU/mes)
- **Endpoint**: `getOwnersForToken`
- **Cubre**: Ethereum, Polygon, Arbitrum, Optimism, Base.
- **Pro**: cuota generosa, marca consolidada.
- **Contra**: requiere registro con email, slightly more friction inicial.

### (c) Bitquery GraphQL free (10k pts/mes)
- **Pro**: queries muy flexibles vía GraphQL.
- **Contra**: cuota baja, riesgo de agotar con polling regular.

### (d) Scraping del UI Etherscan
- **Pro**: gratis, datos ricos.
- **Contra**: ToS-borderline, frágil ante cambios Cloudflare, requiere headless browser.

## Recomendación

**Alchemy (b) como primaria + Moralis (a) como fallback**. Alchemy da mejor cuota mensual (300M CU >> 25k/día × 30 días), Moralis cubre Polygon/BSC si en el futuro la watchlist se expande.

Implementación: connector `chain_holders.py` con interfaz unificada y elección de provider via env var.

## Acción esperada

Confirmar Alchemy o sugerir alternativa. Si Alchemy: necesitaré API key cuando llegue Fase 2.

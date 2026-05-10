---
date: 2026-05-09
topic: crypto-position-manager-mvp
status: complete
next: planning
---

# Crypto Position Manager — Brainstorm

## Qué estamos construyendo

Una herramienta para identificar, monitorizar y gestionar posiciones swing-trade (semanas a meses) sobre proyectos crypto curados manualmente. Se enfoca en **timing de entrada/hold/salida** sobre una watchlist de ~30 proyectos del propio usuario, no en descubrimiento masivo desde categorías de CoinGecko.

El usuario opera como swing trader. Sus mejores trades históricos provienen de combinar narrativa + reflexividad (FARTCOIN, HYPE, ZEC). Las tendencias en crypto se manifiestan como **piernas de 2-3 meses parabólicos separadas por drawdowns del 50-70%**, no como tendencias monotónicas largas. Buy-and-hold se come vivo a quien ignora esta estructura.

## Por qué este enfoque

### Decisión 1 — Filtrar por dev activity como descarte negativo, NO como señal positiva

Datos: Electric Capital 2024 muestra correlación dev↔precio prácticamente cero o negativa en horizontes swing. Los proyectos con más dev activity (Cardano, Polkadot, ETH 2025) underperformaron. Los grandes ganadores recientes fueron narrativa pura (memecoins, AI agents) o infra con PMF reflexivo (HYPE).

→ Dev activity solo sirve como filtro de zombies (descartar proyectos abandonados), no como predictor de retorno.

### Decisión 2 — Modelo de dos capas (positioning leads, fundamentals lag)

Verificación empírica con HYPE: precio hizo ATH 18-sept-2025. Q3 fees ($354.94M) en máximos. Q4 fees solo cayeron -19%. Primer unlock grande el 29-nov-2025, **2 meses después del top**. Conclusión: en crypto, fundamentales y unlocks son indicadores **rezagados**. Las señales que avisaron del top fueron mindshare, funding y smart wallets.

**Layer 2 (fundamentales)** = filtro de viabilidad, daily refresh, decide si un proyecto entra en watchlist.
**Layer 1 (positioning)** = position manager, time entries/exits sobre la watchlist.

### Decisión 3 — Archetype-specific signal weighting

No todos los proyectos pesan los signals igual. Análisis empírico de 12 bull runs históricos (SOL, ZEC, AAVE, SUI, HYPE, TAO, TIA, JUP, PEPE, WIF, POPCAT, FARTCOIN) muestra que el patrón "consolidation breakout" aplica al ~60% de los casos — específicamente proyectos establecidos con ≥6 meses de historia. NO aplica a memecoins parabólicos ni post-TGE recientes.

| Archetype | Layer 2 | Layer 1 dominante | Consolidation breakout |
|---|---|---|---|
| `memecoin-brand` (PENGU, FART) | Skip | Mindshare, holder growth, funding | No aplica |
| `infra-pmf` (HYPE) | Estricto | Todos por igual | Aplica desde pierna 2 |
| `tesis-macro` (ZEC) | Suave | Mindshare, supply on-chain, smart wallets | Aplica |
| `l1-maduro` (SOL, ETH) | Estricto | Stablecoin growth, DEX volume, smart wallets | Aplica |
| `defi-blue-chip` (AAVE, LINK) | Estricto | TVL trend, smart wallets, funding | Aplica |
| `post-tge` (<6 meses) | N/A | Mindshare velocity, holder growth | No aplica |

### Decisión 4 — MVP es A(i) + B(i): 30 proyectos curados, dashboard pull

No hacer auto-discovery desde CoinGecko en MVP. No alertas push. Foco en validar la calidad de los signals con un loop de feedback corto. Si los signals dan edge sobre 30 proyectos, escalar luego.

## Decisiones clave

- **Smart money**: scrape semanal de top holders vía Etherscan/Solscan + cálculo de delta. Skip Nansen/Arkham por coste. CEX netflows como proxy complementario gratis.
- **Funding rates**: Hyperliquid API como fuente primaria, Binance/Bybit como fallback para tokens no listados en HL.
- **Consolidation breakout**: detección semanal con compresión de rango + ATR contraction + volumen secándose + breakout con RVOL > 1.5x.
- **Off-chain brand signals**: fuera de scope. Mindshare (Kaito, scrape CT) actúa como su downstream proxy.
- **Tokenomics**: unlock dates como hard constraint en Layer 2 — bloquea entrada si hay unlock ≥5% de supply en próximas 4-8 semanas.
- **Modelo de fusión de signals**: reglas explícitas por archetype (Opción 1). LLM-reasoner híbrido (Opción 3) como evolución posterior.

## Stack de datos (todo gratis o casi)

| Categoría | Fuente |
|---|---|
| OHLCV semanal | Binance, CoinGecko free tier |
| Funding/OI | Hyperliquid API → Binance/Bybit fallback |
| Fees/TVL/Volume | DeFiLlama free API |
| Smart money | Etherscan/Solscan top holders + diff semanal |
| CEX netflows | CryptoQuant free tier / on-chain directo |
| Mindshare | Kaito (scrape o free tier) + Twitter API minimal |
| Unlocks | DeFiLlama Unlocks + Tokenomist.ai web |
| Dev activity | GitHub API (commits, contributors último mes) |

## Open Questions para la fase de plan

- Periodicidad del scan: ¿daily batch suficiente o necesitamos intra-day para alguno de los signals? (preliminar: daily suficiente para weekly swing).
- Storage: SQLite vs DuckDB vs Postgres local — para 30 proyectos con snapshots históricos, SQLite probablemente sobra.
- UI: ¿CLI con tabla bonita (rich/textual), web local (Streamlit/FastAPI+vanilla), o markdown report generado? Trade-off entre velocidad de iteración y experiencia.
- Backtest: ¿necesitamos un backtest framework desde MVP o solo forward-test con feedback log?

## Next steps

→ `/workflows:plan` para implementación detallada
→ Mecanismo de feedback en `docs/feedback/` activo desde día 1
→ ADRs en `docs/decisions/` para cualquier cambio estructural

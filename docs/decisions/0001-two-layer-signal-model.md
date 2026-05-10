# ADR 0001 — Modelo de dos capas para signals

**Fecha**: 2026-05-09
**Estado**: Aceptado
**Supersede**: —

## Contexto

Inicialmente se propuso usar dev activity como filtro principal para identificar proyectos con potencial de inversión. Análisis empírico (Electric Capital 2024 + casos HYPE/ZEC/SOL) muestra que:

1. La correlación dev activity ↔ retorno de precio es ~cero o negativa en horizontes de swing.
2. En crypto, las señales de positioning (smart money, mindshare, funding) **lideran** al precio.
3. Las señales fundamentales (fees, revenue, TVL) **rezagan** al precio en semanas o meses.

Caso clave: HYPE hizo ATH el 18-sept-2025. Q3 fees en máximos ($354.94M). Q4 fees solo cayeron -19% pese a una caída de precio del 30-50%. Primer unlock grande el 29-nov-2025, dos meses después del top.

## Decisión

Adoptar un modelo de dos capas con responsabilidades separadas:

- **Layer 2 (Viabilidad / Filtro)**: dev activity, fees/TVL trend, catalizadores estructurales. Decide si un proyecto entra en watchlist. NO sirve para timing.
- **Layer 1 (Positioning / Position Manager)**: smart wallets, mindshare, funding/OI, distancia a unlocks, estructura técnica (consolidation breakout). Time entries, holds, exits.

Las sensibilidades de Layer 1 se modulan por **archetype** (memecoin-brand, infra-pmf, tesis-macro, l1-maduro, defi-blue-chip, post-tge).

## Consecuencias

- **Positivas**: el position manager generaliza por contexto, no aplica un catálogo plano. Refleja la causalidad real del mercado.
- **Negativas**: requiere clasificación explícita de archetype por proyecto. Inicialmente manual.
- **Riesgo**: si los archetypes están mal calibrados, los pesos de signals son arbitrarios. Mitigación: review periódico vía feedback log.

## Alternativas consideradas

1. **Single-layer fundamental scoring**: rechazado por evidencia empírica de lag.
2. **LLM-reasoner end-to-end**: aplazado a fase 2 (Opción 3 híbrida del brainstorm). MVP usa reglas explícitas por archetype.

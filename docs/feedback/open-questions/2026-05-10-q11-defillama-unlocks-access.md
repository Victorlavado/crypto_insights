---
question_id: Q11
date: 2026-05-10
plan: docs/plans/2026-05-10-feat-crypto-position-manager-mvp-plan.md
blocking: Fase 1 (Layer 2 hard constraint de unlocks)
status: open (acción: verificar empíricamente en Fase 1)
discovered_in: deepen-plan (research conflicto)
---

# Q11 — DeFiLlama Unlocks: free vs Pro-only

## Contexto

Durante el `/deepen-plan`, dos research agents independientes dieron respuestas contradictorias sobre el endpoint `/emissions` de DeFiLlama:

- **Research APIs general**: "Sin API key. Free tier real, sin límite documentado para uso normal. El endpoint de unlocks (`/emissions`) está en el free tier público."
- **Research específico de unlocks**: "DeFiLlama aloja `/api/emissions` como endpoint Pro-only. No hay diferencia entre singular `/emission/{protocol}` y plural; ambos requieren suscripción Pro."

El plan original asumió free.

## Acción inmediata (no esperar respuesta humana)

Verificar empíricamente en setup de Fase 1, primer paso del connector. Comando:

```bash
curl -s -w "\n%{http_code}\n" "https://api.llama.fi/emissions" | head -50
```

Posibles resultados:
- **HTTP 200 + JSON con datos**: free, plan original procede.
- **HTTP 401/403 / `{"error":"upgrade required"}`**: Pro-only, activar fallback.
- **Otro endpoint distinto**: investigar exact path (`/api/emissions`, `/protocols/{slug}/emissions`, etc).

## Plan de fallback

### Plan B — scrape HTML público
- URL: `https://defillama.com/unlocks/{protocol}`
- Requiere parsing HTML (BeautifulSoup) + tolerancia a cambios de UI.
- Frágil — DefiLlama re-rendea con Next.js (datos en `__NEXT_DATA__` JSON inline, scrapeable estable).
- Coste: ~1 hora setup + risk de breakage.

### Plan C — Tokenomist.ai como primaria
- URL: `https://tokenomist.ai/{protocol}`
- Sin API formal pero schema documentado (categorías, fechas, magnitudes).
- Igual que Plan B requiere scrape, pero documenta su schema.
- Probable más estable que DefiLlama HTML scraping.

### Plan D — DefiLlama Pro
- $300/mes. **Descartado para MVP** salvo justificación fuerte.

## Recomendación

1. Ejecutar verificación en primer commit de Fase 1.
2. Si free → registrar resultado y cerrar este Q.
3. Si Pro → activar Plan C (Tokenomist) como primaria + Plan B (DefiLlama scrape) como cross-check semanal.

## Acción esperada de Victor

Aprobación implícita de la verificación + decisión de fallback (B vs C) si Pro-only.

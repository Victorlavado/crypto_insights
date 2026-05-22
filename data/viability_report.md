# Viability Report — Layer 2

Generado: 2026-05-10 19:20:22
Batch ref: 2026-05-10

Layer 2 evalúa viabilidad (no timing). Estados:
- **blocked**: hard constraint activada (override Layer 1)
- **red** flag: descartar como zombie / dev abandonado
- **amber** flag: revisar manualmente (listing reciente, TVL collapse)
- **green** flag: viable, Layer 1 decide timing

## Resumen

| Symbol | Archetype | State | Flag | Razón |
|---|---|---|---|---|
| HYPE | infra-pmf | blocked | red | blocked: HYPE — unlock 5.2% ponderado próximas 8w (nearest 2026-06-29, dominante team) |
| MEGA | post-tge | unknown | amber | MEGA: listing/TGE hace 56d (<180d) — no aplica histórico |
| AAVE | defi-blue-chip | unknown | green | — |
| AKT | tesis-macro | unknown | green | — |
| BTC | l1-maduro | unknown | green | — |
| CHIP | tesis-macro | unknown | green | — |
| ENA | defi-blue-chip | unknown | green | — |
| FARTCOIN | memecoin-brand | unknown | green | — |
| FXN | tesis-macro | unknown | green | — |
| GRASS | tesis-macro | unknown | green | — |
| HNT | tesis-macro | unknown | green | — |
| JUP | defi-blue-chip | unknown | green | — |
| MON | post-tge | unknown | green | — |
| MORPHO | defi-blue-chip | unknown | green | — |
| NEAR | l1-maduro | unknown | green | — |
| PENDLE | defi-blue-chip | unknown | green | — |
| PENGU | memecoin-brand | unknown | green | — |
| PEPE | memecoin-brand | unknown | green | — |
| PUMP | infra-pmf | unknown | green | — |
| RENDER | tesis-macro | unknown | green | — |
| SPX6900 | memecoin-brand | unknown | green | — |
| STRK | post-tge | unknown | green | — |
| SUI | l1-maduro | unknown | green | — |
| SYRUP | defi-blue-chip | unknown | green | — |
| TAO | tesis-macro | unknown | green | — |
| TON | l1-maduro | unknown | green | — |
| VIRTUAL | tesis-macro | unknown | green | — |
| VVV | tesis-macro | unknown | green | — |
| ZEC | tesis-macro | unknown | green | — |
| elizaOS | tesis-macro | unknown | green | — |

## Detalle de proyectos bloqueados / amber

### HYPE  (infra-pmf, hyperliquid)

- **State**: `blocked` (flag `red`)
- **Reason code**: `UNLOCK_INMINENTE`
- **Razón**: blocked: HYPE — unlock 5.2% ponderado próximas 8w (nearest 2026-06-29, dominante team)
- **Reason data**:
  ```json
  {
    "total_pct": 3.5,
    "total_weighted": 5.25,
    "events": [
      {
        "event_date": "2026-06-29",
        "magnitude_pct": 3.5,
        "magnitude_weighted": 5.25,
        "category": "team"
      }
    ],
    "window_days_from": 28,
    "window_days_to": 56,
    "nearest_event_date": "2026-06-29",
    "days_until_nearest": 50,
    "threshold_pct": 5.0
  }
  ```

### MEGA  (post-tge, Megaeth (ethereum))

- **State**: `unknown` (flag `amber`)
- **Reason code**: `LISTING_RECENT`
- **Razón**: MEGA: listing/TGE hace 56d (<180d) — no aplica histórico
- **Reason data**:
  ```json
  {
    "listing_date": "2026-03-15",
    "days_since": 56,
    "threshold_days": 180
  }
  ```

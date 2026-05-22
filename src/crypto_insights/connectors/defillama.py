"""DeFiLlama connector: TVL, fees, volume vía `/protocols` (free).

Q11 resolved 2026-05-10: `/emissions` es Pro-only (HTTP 402 sin auth).
Para unlocks → connector events_manual (YAML curated).
Para TVL/category → este connector, endpoint público.

Estrategia: una sola request `/protocols` por batch (7000+ protocolos cargados
una vez), luego in-memory lookup por symbol. Más eficiente que 1 request por
proyecto.

supports_project: aplica solo a proyectos con `coingecko_id` (proxy de
"protocol-shaped"). Excluye L1s puros como BTC/SUI/SOL donde el TVL/fees
del proyecto NO mide al token.
"""

from __future__ import annotations

from datetime import date
from typing import Any, ClassVar

import httpx
from aiolimiter import AsyncLimiter
from tenacity import retry

from ..logging_config import get_logger
from ..models import Project, SourceSnapshot
from .base import DEFAULT_RETRY_KWARGS, ConnectorError, honor_retry_after

log = get_logger(__name__)

DEFILLAMA_BASE = "https://api.llama.fi"

# Símbolos cuyo TVL NO es informativo (L1s, memecoins). El connector skipa
# evaluar amber/red para estos; el batch sigue sin warning.
_NOT_PROTOCOL_SHAPED: frozenset[str] = frozenset(
    {"BTC", "ZEC", "PEPE", "FARTCOIN", "SPX6900", "PENGU"}
)


class DeFiLlamaConnector:
    """Pull protocol-level TVL/fees data desde el endpoint público /protocols.

    El connector cachea la respuesta entera (7000+ protocolos) en el primer
    request del batch; los siguientes `fetch()` son lookups in-memory.
    """

    source: ClassVar[str] = "defillama"

    def __init__(self, client: httpx.AsyncClient, *, rate_per_minute: int = 60) -> None:
        self._client = client
        self.limiter = AsyncLimiter(rate_per_minute, time_period=60)
        self._cache: list[dict[str, Any]] | None = None

    def supports_project(self, project: Project) -> bool:
        return project.symbol not in _NOT_PROTOCOL_SHAPED

    @retry(**DEFAULT_RETRY_KWARGS, before_sleep=honor_retry_after)
    async def _fetch_all_protocols(self) -> list[dict[str, Any]]:
        async with self.limiter:
            resp = await self._client.get(f"{DEFILLAMA_BASE}/protocols")
            resp.raise_for_status()
            return resp.json()  # type: ignore[no-any-return]

    async def _ensure_cache(self) -> list[dict[str, Any]]:
        if self._cache is None:
            self._cache = await self._fetch_all_protocols()
            log.info("defillama_protocols_loaded", count=len(self._cache))
        return self._cache

    def _find_protocol(
        self, all_protocols: list[dict[str, Any]], project: Project
    ) -> dict[str, Any] | None:
        """Match por (en orden de preferencia): coingecko_id → gecko_id, symbol → symbol.

        Hay duplicados (Maple + MapleDeFi + Maple RWA todos con symbol SYRUP);
        cuando hay múltiples, preferimos el de mayor TVL (más probable que sea
        el principal).
        """
        if project.coingecko_id:
            matches = [p for p in all_protocols if p.get("gecko_id") == project.coingecko_id]
            if matches:
                return max(matches, key=lambda p: p.get("tvl") or 0)
        matches = [
            p for p in all_protocols if (p.get("symbol") or "").upper() == project.symbol.upper()
        ]
        if matches:
            return max(matches, key=lambda p: p.get("tvl") or 0)
        return None

    async def fetch(self, project: Project, *, target_date: date) -> SourceSnapshot:
        assert project.id is not None
        all_protocols = await self._ensure_cache()
        match = self._find_protocol(all_protocols, project)
        if match is None:
            raise ConnectorError(
                self.source, project.symbol, "no matching protocol in DeFiLlama /protocols"
            )

        payload: dict[str, Any] = {
            "slug": match.get("slug"),
            "name": match.get("name"),
            "category": match.get("category"),
            "chains": match.get("chains"),
            "tvl_usd": match.get("tvl"),
            "change_1d_pct": match.get("change_1d"),
            "change_7d_pct": match.get("change_7d"),
            "change_1h_pct": match.get("change_1h"),
            "mcap_usd": match.get("mcap"),
            "symbol": match.get("symbol"),
            "gecko_id": match.get("gecko_id"),
        }
        log.info(
            "defillama_fetch_ok",
            project=project.symbol,
            slug=payload["slug"],
            tvl_usd=payload["tvl_usd"],
        )
        return SourceSnapshot(
            project_id=project.id,
            source=self.source,
            snapshot_date=target_date,
            payload=payload,
        )

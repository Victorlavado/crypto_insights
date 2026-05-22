"""Binance OHLCV connector.

Endpoint: GET /api/v3/klines
Auth: none
Rate limit (free): 6000 weight/min IP. Cada llamada klines = 1-2 weight según
el `limit`. Conservador: 200 req/min usando AsyncLimiter(200, 60).

Devuelve OHLCV diario para el símbolo del proyecto. La normalización a Project
asume `symbol` directo en pair USDT (HYPE → HYPEUSDT). Para proyectos no
listados en Binance (BTC nativo, MEGA pre-listing, etc.), supports_project
devuelve False y el batch los salta.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any, ClassVar

import httpx
from aiolimiter import AsyncLimiter
from tenacity import retry

from ..logging_config import get_logger
from ..models import Project, SourceSnapshot
from .base import DEFAULT_RETRY_KWARGS, ConnectorError, honor_retry_after

log = get_logger(__name__)

BINANCE_BASE_URL = "https://api.binance.com"

# Símbolos que NO están en Binance Spot (no listed o native chain).
# Se mantienen aquí en lugar de en supports_project porque la fuente de verdad es
# "qué expone Binance", no una propiedad estructural del proyecto.
_NOT_ON_BINANCE_SPOT: frozenset[str] = frozenset(
    {
        "MEGA",  # post-tge muy reciente
        "MON",  # post-tge muy reciente
        "elizaOS",  # solana memecoin/agent
        "VVV",  # base
        "AKT",  # cosmos
        "GRASS",  # not on binance spot
        "HNT",  # solana
        "CHIP",  # arbitrum
        "FXN",  # ethereum
        "VIRTUAL",  # base
        "MORPHO",  # ethereum DeFi token
        "SPX6900",  # ethereum memecoin
        "SYRUP",  # ethereum DeFi token
        "PUMP",  # solana
        "STRK",  # not on binance spot
        "HYPE",  # native Hyperliquid — usar perp connector cuando llegue Fase 2
        "FARTCOIN",  # solana memecoin no listada en binance spot
    }
)


class BinanceConnector:
    """Connector para OHLCV diario de Binance.

    Configurable: pair_quote default "USDT" — algunos proyectos liquidan vs
    USDC o BTC. Se override desde el constructor si hace falta.
    """

    source: ClassVar[str] = "binance"

    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        pair_quote: str = "USDT",
        rate_per_minute: int = 200,
    ) -> None:
        self._client = client
        self._pair_quote = pair_quote
        # AsyncLimiter es leaky bucket; rate_per_minute permisos por minuto.
        self.limiter = AsyncLimiter(rate_per_minute, time_period=60)

    def supports_project(self, project: Project) -> bool:
        """Heurística: si el símbolo no está en la blacklist y la quote es estándar.

        NO consulta archetype (R16). Política simple: probar y dejar que el
        404 nos diga si no está listado — pero pre-filtramos casos conocidos
        para no quemar rate limit.
        """
        return project.symbol not in _NOT_ON_BINANCE_SPOT

    def _symbol_for_binance(self, project: Project) -> str:
        return f"{project.symbol}{self._pair_quote}"

    @retry(**DEFAULT_RETRY_KWARGS, before_sleep=honor_retry_after)
    async def _fetch_klines(
        self, symbol: str, *, start_ms: int, end_ms: int, limit: int
    ) -> list[list[Any]]:
        """Llama klines endpoint. Levanta HTTPStatusError en 4xx/5xx (tenacity retry-eligible).

        Limiter DENTRO de retry (R1): cada retry adquiere permit fresco.
        """
        async with self.limiter:
            resp = await self._client.get(
                f"{BINANCE_BASE_URL}/api/v3/klines",
                params={
                    "symbol": symbol,
                    "interval": "1d",
                    "startTime": start_ms,
                    "endTime": end_ms,
                    "limit": limit,
                },
            )
            resp.raise_for_status()
            return resp.json()  # type: ignore[no-any-return]

    async def fetch(self, project: Project, *, target_date: date) -> SourceSnapshot:
        """Trae las últimas ~400 daily candles que terminan en target_date inclusive.

        400 días = ~57 semanas; suficiente para indicadores semanales sobre
        ventana de 50w + buffer. Backfill histórico completo se hace con
        script separado (Fase 2).
        """
        assert project.id is not None, "Project must be persisted before fetching"

        symbol = self._symbol_for_binance(project)
        end_dt = datetime.combine(target_date, datetime.min.time(), tzinfo=UTC) + timedelta(days=1)
        start_dt = end_dt - timedelta(days=400)
        end_ms = int(end_dt.timestamp() * 1000) - 1
        start_ms = int(start_dt.timestamp() * 1000)

        try:
            raw = await self._fetch_klines(symbol, start_ms=start_ms, end_ms=end_ms, limit=400)
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 400 and "Invalid symbol" in e.response.text:
                raise ConnectorError(
                    self.source, project.symbol, f"Binance does not list {symbol}"
                ) from e
            raise ConnectorError(
                self.source,
                project.symbol,
                f"HTTP {e.response.status_code}: {e.response.text[:200]}",
            ) from e
        except httpx.HTTPError as e:
            raise ConnectorError(self.source, project.symbol, f"Network: {e}") from e

        candles = [_parse_candle(row) for row in raw]
        if not candles:
            raise ConnectorError(self.source, project.symbol, f"Empty response for {symbol}")

        payload: dict[str, Any] = {
            "symbol": symbol,
            "interval": "1d",
            "candles": candles,
            "candle_count": len(candles),
            "first_open_time": candles[0]["open_time"],
            "last_close_time": candles[-1]["close_time"],
        }

        log.info(
            "binance_fetch_ok",
            project=project.symbol,
            symbol=symbol,
            candles=len(candles),
        )

        return SourceSnapshot(
            project_id=project.id,
            source=self.source,
            snapshot_date=target_date,
            payload=payload,
        )


def _parse_candle(row: list[Any]) -> dict[str, Any]:
    """Klines schema (Binance): [openTime, open, high, low, close, volume, closeTime, quoteVolume, trades, ...]."""
    return {
        "open_time": int(row[0]),
        "open": float(row[1]),
        "high": float(row[2]),
        "low": float(row[3]),
        "close": float(row[4]),
        "volume": float(row[5]),
        "close_time": int(row[6]),
        "quote_volume": float(row[7]),
        "trades": int(row[8]),
    }

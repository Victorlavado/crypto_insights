"""Hyperliquid connector: funding rates + open interest + mark price.

Endpoint: POST /info  body={"type": "metaAndAssetCtxs"}
Auth: none
Rate limit: 1200 req/min REST

Una sola request por batch trae snapshot completo del universe (~200 perps).
Lookup in-memory por nombre del proyecto. Para proyectos no listados en HL,
supports_project devuelve False.

Histórico de funding: GET /info {"type":"fundingHistory", "coin":"...",
"startTime":...} — usado por signals/funding.py para calcular z-score 30d.
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

HL_BASE = "https://api.hyperliquid.xyz"

# Coin name mapping cuando difiere de project.symbol. Por defecto se usa symbol
# directo. Vacío al inicio; populamos cuando descubramos discrepancias.
_SYMBOL_OVERRIDES: dict[str, str] = {
    "PUMP": "PUMP",
    # ZEC, SUI, STRK, etc. coinciden directo.
}


class HyperliquidConnector:
    """Connector para funding/OI desde Hyperliquid perps."""

    source: ClassVar[str] = "hyperliquid"

    def __init__(self, client: httpx.AsyncClient, *, rate_per_minute: int = 200) -> None:
        self._client = client
        self.limiter = AsyncLimiter(rate_per_minute, time_period=60)
        self._snapshot: dict[str, dict[str, Any]] | None = None

    def supports_project(self, project: Project) -> bool:
        # Sin haber cargado el snapshot todavía no sabemos qué coins lista HL.
        # Devolvemos True y dejamos que fetch() falle limpio si no está.
        return True

    @retry(**DEFAULT_RETRY_KWARGS, before_sleep=honor_retry_after)
    async def _fetch_universe_snapshot(self) -> dict[str, dict[str, Any]]:
        async with self.limiter:
            resp = await self._client.post(
                f"{HL_BASE}/info",
                json={"type": "metaAndAssetCtxs"},
            )
            resp.raise_for_status()
            data = resp.json()

        if not (isinstance(data, list) and len(data) == 2):
            raise ConnectorError(
                self.source, "<universe>", f"unexpected response shape: {type(data).__name__}"
            )

        meta, asset_ctxs = data
        universe = meta.get("universe", [])
        out: dict[str, dict[str, Any]] = {}
        for i, asset in enumerate(universe):
            if asset.get("isDelisted"):
                continue
            name = asset.get("name")
            ctx = asset_ctxs[i] if i < len(asset_ctxs) else {}
            out[name] = {
                "name": name,
                "max_leverage": asset.get("maxLeverage"),
                "funding": _safe_float(ctx.get("funding")),
                "open_interest": _safe_float(ctx.get("openInterest")),
                "mark_px": _safe_float(ctx.get("markPx")),
                "oracle_px": _safe_float(ctx.get("oraclePx")),
                "premium": _safe_float(ctx.get("premium")),
                "day_ntl_vlm": _safe_float(ctx.get("dayNtlVlm")),
            }
        return out

    async def _ensure_snapshot(self) -> dict[str, dict[str, Any]]:
        if self._snapshot is None:
            self._snapshot = await self._fetch_universe_snapshot()
            log.info("hyperliquid_universe_loaded", coins=len(self._snapshot))
        return self._snapshot

    def _coin_for(self, project: Project) -> str:
        return _SYMBOL_OVERRIDES.get(project.symbol, project.symbol)

    @retry(**DEFAULT_RETRY_KWARGS, before_sleep=honor_retry_after)
    async def _fetch_funding_history(self, coin: str, *, start_ms: int) -> list[dict[str, Any]]:
        async with self.limiter:
            resp = await self._client.post(
                f"{HL_BASE}/info",
                json={"type": "fundingHistory", "coin": coin, "startTime": start_ms},
            )
            resp.raise_for_status()
            data = resp.json()
            return data if isinstance(data, list) else []

    async def fetch(self, project: Project, *, target_date: date) -> SourceSnapshot:
        assert project.id is not None
        coin = self._coin_for(project)
        universe = await self._ensure_snapshot()

        if coin not in universe:
            raise ConnectorError(
                self.source, project.symbol, f"coin {coin} not listed on Hyperliquid"
            )

        current = universe[coin]

        # Funding history últimos 30 días para z-score
        end_dt = datetime.combine(target_date, datetime.min.time(), tzinfo=UTC)
        start_ms = int((end_dt - timedelta(days=30)).timestamp() * 1000)
        history = await self._fetch_funding_history(coin, start_ms=start_ms)
        funding_values = [_safe_float(h.get("fundingRate")) for h in history]
        funding_values = [v for v in funding_values if v is not None]

        payload = {
            "coin": coin,
            "funding_current": current["funding"],
            "open_interest": current["open_interest"],
            "mark_px": current["mark_px"],
            "premium": current["premium"],
            "day_ntl_vlm": current["day_ntl_vlm"],
            "funding_history_30d": funding_values,
            "funding_history_count": len(funding_values),
        }
        log.info(
            "hyperliquid_fetch_ok",
            project=project.symbol,
            coin=coin,
            funding=current["funding"],
            oi=current["open_interest"],
        )
        return SourceSnapshot(
            project_id=project.id,
            source=self.source,
            snapshot_date=target_date,
            payload=payload,
        )


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None

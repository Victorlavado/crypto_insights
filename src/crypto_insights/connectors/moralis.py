"""Moralis connector: EVM ERC20 top holders.

Endpoint: GET deep-index.moralis.io/api/v2.2/erc20/{token_address}/owners
Params:   chain=eth|base|arbitrum, limit=100, order=DESC
Auth:     X-API-Key header

Devuelve owners ordenados por balance descendiente con `is_contract` flag
nativo (Moralis hace `eth_getCode` server-side). Eliminamos paso 4 del 5-step
pipeline para EVM (heurística contract-vs-EOA) — Moralis lo da resuelto.

Rate limit (free): ~25k Compute Units/día. Cada owners request = ~3 CU. Para
12 proyectos EVM × 1 fetch/día = ~36 CU/día. Margen >100×.

Open Q1 resuelta: Moralis sobre Alchemy. Justificación: Alchemy NO tiene
endpoint nativo de ERC20 top holders ranked by balance — habría que agregar
desde getTokenTransfers, lo que añade complejidad sin valor. Moralis lo
expone directamente. Si en Fase 4 emerge necesidad de redundancia, añadir
alchemy.py como fallback.

`supports_project`: chain en {ethereum, base, arbitrum} con contract 0x... y NO native.
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

MORALIS_BASE = "https://deep-index.moralis.io/api/v2.2"

# Map chain del watchlist → param chain de Moralis. Reconoce strings con paréntesis
# como "arbitrum (ethereum)" extrayendo el primer token.
_MORALIS_CHAIN_MAP: dict[str, str] = {
    "ethereum": "eth",
    "base": "base",
    "arbitrum": "arbitrum",
}


def _normalize_chain(chain: str) -> str | None:
    """Devuelve el chain canónico de Moralis o None si no soportado.

    Acepta variantes como 'arbitrum (ethereum)' → 'arbitrum'.
    """
    if not chain:
        return None
    head = chain.lower().strip().split(" ", 1)[0].split("(", 1)[0].strip()
    return _MORALIS_CHAIN_MAP.get(head)


class MoralisConnector:
    """Connector para EVM top holders via Moralis Web3 Data API."""

    source: ClassVar[str] = "moralis"

    def __init__(
        self,
        client: httpx.AsyncClient,
        api_key: str | None,
        *,
        rate_per_minute: int = 60,
        top_n: int = 100,
    ) -> None:
        self._client = client
        self._api_key = api_key
        self._top_n = top_n
        self.limiter = AsyncLimiter(rate_per_minute, time_period=60)

    def supports_project(self, project: Project) -> bool:
        if not project.chain or not project.contract:
            return False
        if project.contract.lower() in ("native", ""):
            return False
        if not project.contract.startswith("0x"):
            return False
        return _normalize_chain(project.chain) is not None

    @retry(**DEFAULT_RETRY_KWARGS, before_sleep=honor_retry_after)
    async def _fetch_owners(self, token: str, chain: str) -> dict[str, Any]:
        if not self._api_key:
            raise ConnectorError(
                self.source, token, "Moralis API key not configured (CI_MORALIS_API_KEY)"
            )
        async with self.limiter:
            resp = await self._client.get(
                f"{MORALIS_BASE}/erc20/{token}/owners",
                params={"chain": chain, "limit": self._top_n, "order": "DESC"},
                headers={"X-API-Key": self._api_key, "Accept": "application/json"},
            )
            resp.raise_for_status()
            return resp.json()  # type: ignore[no-any-return]

    async def fetch(self, project: Project, *, target_date: date) -> SourceSnapshot:
        assert project.id is not None
        assert project.contract is not None
        assert project.chain is not None

        chain = _normalize_chain(project.chain)
        if chain is None:
            raise ConnectorError(
                self.source, project.symbol, f"chain {project.chain} not supported"
            )

        try:
            raw = await self._fetch_owners(project.contract, chain)
        except httpx.HTTPStatusError as e:
            raise ConnectorError(
                self.source,
                project.symbol,
                f"HTTP {e.response.status_code}: {e.response.text[:200]}",
            ) from e
        except httpx.HTTPError as e:
            raise ConnectorError(self.source, project.symbol, f"Network: {e}") from e

        result = raw.get("result", []) or []
        if not result:
            raise ConnectorError(
                self.source,
                project.symbol,
                f"empty holders for token {project.contract} chain {chain}",
            )

        holders = []
        for rank, row in enumerate(result, start=1):
            balance = _parse_balance(row.get("balance"), row.get("balance_formatted"))
            owner = row.get("owner_address")
            if not owner or balance is None:
                continue
            holders.append(
                {
                    "owner": owner,
                    "balance": balance,
                    "rank": rank,
                    "is_contract": bool(row.get("is_contract", False)),
                    "usd_value": _safe_float(row.get("usd_value")),
                    "percent_supply": _safe_float(row.get("percentage_relative_to_total_supply")),
                }
            )

        payload: dict[str, Any] = {
            "token_address": project.contract,
            "chain": chain,
            "holders": holders,
            "holder_count": len(holders),
        }

        log.info(
            "moralis_fetch_ok",
            project=project.symbol,
            chain=chain,
            token=project.contract,
            holders=len(holders),
        )

        return SourceSnapshot(
            project_id=project.id,
            source=self.source,
            snapshot_date=target_date,
            payload=payload,
        )


def _parse_balance(raw_balance: Any, formatted: Any) -> float | None:
    """Prefiere balance_formatted (ya con decimals aplicados) si está disponible."""
    if formatted is not None:
        try:
            return float(formatted)
        except (TypeError, ValueError):
            pass
    if raw_balance is not None:
        try:
            return float(raw_balance)
        except (TypeError, ValueError):
            return None
    return None


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None

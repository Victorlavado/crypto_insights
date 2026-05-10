"""Helius connector: Solana SPL token top holders.

Endpoint: POST mainnet.helius-rpc.com/?api-key=KEY
Method:   getTokenAccounts  (Helius DAS extension)
Params:   {"mint": "<SPL mint>", "page": N, "limit": 100, "displayOptions": {"showZeroBalance": false}}

Devuelve owners ya resueltos (no ATAs raw): `owner` field es la wallet, no la
associated token account. Esto elimina el paso 2 del 5-step pipeline original
(resolución ATA → owner) — Helius DAS lo hace internamente.

Rate limit (free tier): 1M créditos/mes, 10 req/s. 30 proyectos × 1 fetch/día =
~900/mes con 1 página por proyecto. Margen amplio.

`supports_project`: chain=solana con contract no nativo. Excluye SOL nativo
(no es SPL), HYPE (no es Solana), MEGA (no es Solana). El filtrado de program
accounts (Raydium, Orca, Jupiter pools) lo hace signals/smart_money.py contra
la lista de excluded_addresses.yaml — no aquí.
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

HELIUS_BASE = "https://mainnet.helius-rpc.com"


class HeliusConnector:
    """Connector para Solana SPL top holders via Helius DAS getTokenAccounts.

    El connector NO clasifica holders (EOA vs program). Solo trae raw + flag
    booleano `frozen` que es metadata útil. La clasificación es responsabilidad
    de signals/smart_money.py contra la lista curada de excluded_addresses.
    """

    source: ClassVar[str] = "helius"

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
        """Solo SPL tokens en Solana. Native SOL excluido (no mint estándar)."""
        if project.chain is None:
            return False
        chain = project.chain.lower().strip()
        if chain != "solana":
            return False
        return bool(project.contract) and project.contract.lower() not in ("native", "")

    @retry(**DEFAULT_RETRY_KWARGS, before_sleep=honor_retry_after)
    async def _fetch_token_accounts(self, mint: str, *, page: int = 1) -> dict[str, Any]:
        if not self._api_key:
            raise ConnectorError(
                self.source, mint, "Helius API key not configured (CI_HELIUS_API_KEY)"
            )
        async with self.limiter:
            resp = await self._client.post(
                f"{HELIUS_BASE}/?api-key={self._api_key}",
                json={
                    "jsonrpc": "2.0",
                    "id": "crypto-insights",
                    "method": "getTokenAccounts",
                    "params": {
                        "mint": mint,
                        "page": page,
                        "limit": self._top_n,
                        "displayOptions": {"showZeroBalance": False},
                    },
                },
            )
            resp.raise_for_status()
            return resp.json()  # type: ignore[no-any-return]

    async def fetch(self, project: Project, *, target_date: date) -> SourceSnapshot:
        assert project.id is not None
        assert project.contract is not None

        try:
            raw = await self._fetch_token_accounts(project.contract, page=1)
        except httpx.HTTPStatusError as e:
            raise ConnectorError(
                self.source,
                project.symbol,
                f"HTTP {e.response.status_code}: {e.response.text[:200]}",
            ) from e
        except httpx.HTTPError as e:
            raise ConnectorError(self.source, project.symbol, f"Network: {e}") from e

        result = raw.get("result", {})
        token_accounts = result.get("token_accounts", []) or []
        if not token_accounts:
            raise ConnectorError(
                self.source, project.symbol, f"empty holders for mint {project.contract}"
            )

        # Aggregamos por owner (un wallet puede tener múltiples ATAs del mismo mint).
        owner_totals: dict[str, float] = {}
        owner_meta: dict[str, dict[str, Any]] = {}
        for acct in token_accounts:
            owner = acct.get("owner")
            amount = _safe_amount(acct.get("amount"))
            if not owner or amount is None:
                continue
            owner_totals[owner] = owner_totals.get(owner, 0.0) + amount
            if owner not in owner_meta:
                owner_meta[owner] = {
                    "first_ata": acct.get("address"),
                    "frozen": bool(acct.get("frozen", False)),
                }

        sorted_holders = sorted(owner_totals.items(), key=lambda kv: kv[1], reverse=True)
        holders = [
            {
                "owner": owner,
                "balance": balance,
                "rank": rank,
                "ata": owner_meta[owner]["first_ata"],
                "frozen": owner_meta[owner]["frozen"],
            }
            for rank, (owner, balance) in enumerate(sorted_holders, start=1)
        ]

        payload: dict[str, Any] = {
            "mint": project.contract,
            "page": result.get("page", 1),
            "total_accounts": result.get("total", len(token_accounts)),
            "holders": holders,
            "holder_count": len(holders),
        }

        log.info(
            "helius_fetch_ok",
            project=project.symbol,
            mint=project.contract,
            holders=len(holders),
        )

        return SourceSnapshot(
            project_id=project.id,
            source=self.source,
            snapshot_date=target_date,
            payload=payload,
        )


def _safe_amount(value: Any) -> float | None:
    """Helius devuelve `amount` como int (raw token units) o string. Normalizamos a float."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None

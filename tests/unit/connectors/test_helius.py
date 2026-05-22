"""Helius connector tests con respx."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import httpx
import pytest
import respx

from crypto_insights.connectors.base import ConnectorError, build_http_client
from crypto_insights.connectors.helius import HeliusConnector
from crypto_insights.models import Archetype, Project


@pytest.fixture
def solana_project() -> Project:
    return Project(
        id=10,
        symbol="FARTCOIN",
        archetype=Archetype.MEMECOIN_BRAND,
        coingecko_id="fartcoin",
        chain="solana",
        contract="9BB6NFEcjBCtnNLFko2FqVQBq8HHM13kCyYcdQbgpump",
    )


@pytest.fixture
def eth_project() -> Project:
    return Project(
        id=11,
        symbol="AAVE",
        archetype=Archetype.DEFI_BLUE_CHIP,
        coingecko_id="aave",
        chain="ethereum",
        contract="0x7fc66500c84a76ad7e9c93437bfc5ac33e2ddae9",
    )


@pytest.fixture
def native_sol_project() -> Project:
    return Project(
        id=12,
        symbol="SOL",
        archetype=Archetype.L1_MADURO,
        coingecko_id="solana",
        chain="solana",
        contract="native",
    )


@pytest.fixture
def helius_fixture(fixtures_dir: Path) -> dict:
    return json.loads((fixtures_dir / "helius_token_accounts.json").read_text())


def test_supports_only_solana_with_contract(
    solana_project: Project, eth_project: Project, native_sol_project: Project
) -> None:
    client = httpx.AsyncClient()
    conn = HeliusConnector(client, api_key="test-key")
    assert conn.supports_project(solana_project)
    assert not conn.supports_project(eth_project)
    assert not conn.supports_project(native_sol_project)


async def test_fetch_aggregates_owners_and_sorts_desc(
    solana_project: Project, helius_fixture: dict
) -> None:
    async with build_http_client() as client:
        connector = HeliusConnector(client, api_key="test-key")
        with respx.mock(base_url="https://mainnet.helius-rpc.com") as mock:
            mock.post("/").respond(200, json=helius_fixture)
            snap = await connector.fetch(solana_project, target_date=date(2026, 5, 10))

    payload = snap.payload
    assert payload["mint"] == solana_project.contract
    assert payload["holder_count"] == 4  # 5 ATAs → 4 owners (WhaleEOA aggregates 2 ATAs)

    holders = payload["holders"]
    # WhaleEOA: 500B + 100B = 600B → rank 1
    assert holders[0]["owner"] == "WhaleEOA111111111111111111111111111111111111"
    assert holders[0]["balance"] == pytest.approx(6.0e14)
    assert holders[0]["rank"] == 1
    # RaydiumPool: 300B → rank 2
    assert holders[1]["owner"] == "RaydiumPool2222222222222222222222222222222222"
    assert holders[1]["rank"] == 2


async def test_fetch_raises_on_empty_holders(solana_project: Project) -> None:
    async with build_http_client() as client:
        connector = HeliusConnector(client, api_key="test-key")
        empty = {"jsonrpc": "2.0", "id": "test", "result": {"token_accounts": []}}
        with respx.mock(base_url="https://mainnet.helius-rpc.com") as mock:
            mock.post("/").respond(200, json=empty)
            with pytest.raises(ConnectorError) as ei:
                await connector.fetch(solana_project, target_date=date(2026, 5, 10))
    assert "empty holders" in str(ei.value)


async def test_fetch_raises_without_api_key(solana_project: Project) -> None:
    async with build_http_client() as client:
        connector = HeliusConnector(client, api_key=None)
        with pytest.raises(ConnectorError) as ei:
            await connector.fetch(solana_project, target_date=date(2026, 5, 10))
    assert "API key not configured" in str(ei.value)

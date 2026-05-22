"""Moralis connector tests con respx."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import httpx
import pytest
import respx

from crypto_insights.connectors.base import ConnectorError, build_http_client
from crypto_insights.connectors.moralis import MoralisConnector, _normalize_chain
from crypto_insights.models import Archetype, Project


@pytest.fixture
def aave_project() -> Project:
    return Project(
        id=20,
        symbol="AAVE",
        archetype=Archetype.DEFI_BLUE_CHIP,
        coingecko_id="aave",
        chain="ethereum",
        contract="0x7fc66500c84a76ad7e9c93437bfc5ac33e2ddae9",
    )


@pytest.fixture
def arbitrum_project() -> Project:
    return Project(
        id=21,
        symbol="CHIP",
        archetype=Archetype.TESIS_MACRO,
        coingecko_id="chip-2",
        chain="arbitrum (ethereum)",
        contract="0x0c1c1c109fe34733fca54b82d7b46b75cfb71f6e",
    )


@pytest.fixture
def solana_project() -> Project:
    return Project(
        id=22,
        symbol="PENGU",
        archetype=Archetype.MEMECOIN_BRAND,
        coingecko_id="pudgy-penguins",
        chain="solana",
        contract="2zMMhcVQEXDtdE6vsFS7S7D5oUodfJHE8vd1gnBouauv",
    )


@pytest.fixture
def moralis_fixture(fixtures_dir: Path) -> dict:
    return json.loads((fixtures_dir / "moralis_owners.json").read_text())


def test_normalize_chain() -> None:
    assert _normalize_chain("ethereum") == "eth"
    assert _normalize_chain("base") == "base"
    assert _normalize_chain("arbitrum (ethereum)") == "arbitrum"
    assert _normalize_chain("solana") is None
    assert _normalize_chain("ton") is None
    assert _normalize_chain("") is None


def test_supports_evm_with_contract(
    aave_project: Project, arbitrum_project: Project, solana_project: Project
) -> None:
    client = httpx.AsyncClient()
    conn = MoralisConnector(client, api_key="test-key")
    assert conn.supports_project(aave_project)
    assert conn.supports_project(arbitrum_project)
    assert not conn.supports_project(solana_project)


async def test_fetch_parses_owners_with_is_contract(
    aave_project: Project, moralis_fixture: dict
) -> None:
    async with build_http_client() as client:
        connector = MoralisConnector(client, api_key="test-key")
        with respx.mock(base_url="https://deep-index.moralis.io") as mock:
            mock.get("/api/v2.2/erc20/" + aave_project.contract + "/owners").respond(
                200, json=moralis_fixture
            )
            snap = await connector.fetch(aave_project, target_date=date(2026, 5, 10))

    holders = snap.payload["holders"]
    assert snap.payload["chain"] == "eth"
    assert len(holders) == 5

    # First holder is the whale EOA
    assert holders[0]["balance"] == pytest.approx(5000.0)
    assert holders[0]["is_contract"] is False
    assert holders[0]["rank"] == 1
    # Second is Aave pool contract
    assert holders[1]["is_contract"] is True
    assert holders[1]["rank"] == 2


async def test_fetch_raises_without_api_key(aave_project: Project) -> None:
    async with build_http_client() as client:
        connector = MoralisConnector(client, api_key=None)
        with pytest.raises(ConnectorError) as ei:
            await connector.fetch(aave_project, target_date=date(2026, 5, 10))
    assert "API key not configured" in str(ei.value)


async def test_fetch_raises_on_empty_owners(aave_project: Project) -> None:
    async with build_http_client() as client:
        connector = MoralisConnector(client, api_key="test-key")
        with respx.mock(base_url="https://deep-index.moralis.io") as mock:
            mock.get("/api/v2.2/erc20/" + aave_project.contract + "/owners").respond(
                200, json={"result": []}
            )
            with pytest.raises(ConnectorError) as ei:
                await connector.fetch(aave_project, target_date=date(2026, 5, 10))
    assert "empty holders" in str(ei.value)

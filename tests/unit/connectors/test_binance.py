"""Binance connector tests con respx (no live network)."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import httpx
import pytest
import respx

from crypto_insights.connectors.base import ConnectorError, build_http_client
from crypto_insights.connectors.binance import BinanceConnector
from crypto_insights.models import Archetype, Project


@pytest.fixture
def listed_project() -> Project:
    """Proyecto que Binance Spot lista (BTC). Para tests positivos."""
    return Project(
        id=1,
        symbol="BTC",
        archetype=Archetype.L1_MADURO,
        coingecko_id="bitcoin",
        chain="bitcoin",
        contract="native",
    )


@pytest.fixture
def unlisted_project() -> Project:
    """Proyecto NO listado en Binance Spot (MEGA, post-TGE muy reciente)."""
    return Project(
        id=2,
        symbol="MEGA",
        archetype=Archetype.POST_TGE,
        coingecko_id="megaeth",
        chain="megaeth",
        contract="0x28b7e77f82b25b95953825f1e3ea0e36c1c29861",
    )


@pytest.fixture
def klines_fixture(fixtures_dir: Path) -> list:
    return json.loads((fixtures_dir / "binance_hype_klines.json").read_text())


def test_supports_project_filters_unlisted(
    listed_project: Project, unlisted_project: Project
) -> None:
    client = httpx.AsyncClient()  # not awaited; just for ctor
    conn = BinanceConnector(client)
    assert conn.supports_project(listed_project)
    assert not conn.supports_project(unlisted_project)


async def test_fetch_returns_normalized_snapshot(
    listed_project: Project, klines_fixture: list
) -> None:
    async with build_http_client() as client:
        connector = BinanceConnector(client)
        with respx.mock(base_url="https://api.binance.com") as mock:
            mock.get("/api/v3/klines").respond(200, json=klines_fixture)
            snap = await connector.fetch(listed_project, target_date=date(2026, 5, 10))

    assert snap.source == "binance"
    assert snap.project_id == 1
    assert snap.snapshot_date == date(2026, 5, 10)
    assert snap.payload["symbol"] == "BTCUSDT"
    assert snap.payload["interval"] == "1d"
    assert snap.payload["candle_count"] == 5
    first = snap.payload["candles"][0]
    assert first["open"] == 30.05
    assert first["close"] == 30.95
    assert first["volume"] == 1234567.89
    assert first["trades"] == 45234


async def test_fetch_raises_connector_error_on_invalid_symbol(listed_project: Project) -> None:
    async with build_http_client() as client:
        connector = BinanceConnector(client)
        with respx.mock(base_url="https://api.binance.com") as mock:
            mock.get("/api/v3/klines").respond(400, json={"code": -1121, "msg": "Invalid symbol."})
            with pytest.raises(ConnectorError) as ei:
                await connector.fetch(listed_project, target_date=date(2026, 5, 10))
    assert "does not list" in str(ei.value)


async def test_fetch_raises_connector_error_on_empty_response(listed_project: Project) -> None:
    async with build_http_client() as client:
        connector = BinanceConnector(client)
        with respx.mock(base_url="https://api.binance.com") as mock:
            mock.get("/api/v3/klines").respond(200, json=[])
            with pytest.raises(ConnectorError) as ei:
                await connector.fetch(listed_project, target_date=date(2026, 5, 10))
    assert "Empty" in str(ei.value)

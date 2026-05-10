"""Backfill OHLCV tests: paginación + idempotencia."""

from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path

import pytest
import respx

from crypto_insights import db as db_mod
from crypto_insights.connectors.base import build_http_client
from crypto_insights.models import Archetype, Project
from crypto_insights.pipeline.backfill import backfill_project_ohlcv


@pytest.fixture
def temp_db(tmp_path: Path) -> sqlite3.Connection:
    db_path = tmp_path / "test.db"
    db_mod.apply_migrations(
        db_path=db_path, migrations_dir=Path(__file__).resolve().parents[2] / "migrations"
    )
    conn = db_mod.connect(db_path=db_path)
    conn.execute(
        """INSERT INTO projects (id, symbol, archetype, chain)
           VALUES (1, 'BTC', 'l1-maduro', 'bitcoin')"""
    )
    yield conn
    conn.close()


@pytest.fixture
def btc_project() -> Project:
    return Project(
        id=1,
        symbol="BTC",
        archetype=Archetype.L1_MADURO,
        coingecko_id="bitcoin",
        chain="bitcoin",
        contract="native",
    )


def _candle(open_time_ms: int, *, close: float = 50000.0) -> list:
    """Binance kline row format."""
    return [
        open_time_ms,
        "49500.00",
        "50500.00",
        "49000.00",
        f"{close}",
        "1000.0",
        open_time_ms + 86_400_000 - 1,
        "50000000.0",
        50000,
        "500.0",
        "25000000.0",
        "0",
    ]


async def test_backfill_persists_single_page(
    temp_db: sqlite3.Connection, btc_project: Project
) -> None:
    """Single page (3 candles) → 3 filas en ohlcv_daily."""
    candles = [
        _candle(1704067200000, close=42000.0),  # 2024-01-01
        _candle(1704153600000, close=43000.0),  # 2024-01-02
        _candle(1704240000000, close=44000.0),  # 2024-01-03
    ]
    async with build_http_client() as client:
        with respx.mock(base_url="https://api.binance.com") as mock:
            # Primera request devuelve 3 candles, segunda (siguiente cursor) vacío
            route = mock.get("/api/v3/klines")
            route.side_effect = [
                respx.MockResponse(200, json=candles),
                respx.MockResponse(200, json=[]),
            ]
            written = await backfill_project_ohlcv(
                client,
                temp_db,
                btc_project,
                start_date=date(2024, 1, 1),
                end_date=date(2024, 1, 3),
            )

    assert written == 3
    rows = temp_db.execute(
        "SELECT candle_date, close FROM ohlcv_daily WHERE project_id=1 ORDER BY candle_date"
    ).fetchall()
    assert len(rows) == 3
    assert rows[0]["candle_date"] == "2024-01-01"
    assert rows[2]["close"] == pytest.approx(44000.0)


async def test_backfill_is_idempotent(temp_db: sqlite3.Connection, btc_project: Project) -> None:
    """Re-correr backfill mismo rango → UPSERT, no duplica filas."""
    candles = [
        _candle(1704067200000, close=42000.0),
        _candle(1704153600000, close=43000.0),
    ]
    async with build_http_client() as client:
        with respx.mock(base_url="https://api.binance.com") as mock:
            mock.get("/api/v3/klines").mock(
                side_effect=lambda req: respx.MockResponse(200, json=candles)
            )
            await backfill_project_ohlcv(
                client,
                temp_db,
                btc_project,
                start_date=date(2024, 1, 1),
                end_date=date(2024, 1, 2),
            )
            # Re-run identical
            await backfill_project_ohlcv(
                client,
                temp_db,
                btc_project,
                start_date=date(2024, 1, 1),
                end_date=date(2024, 1, 2),
            )

    count_row = temp_db.execute(
        "SELECT COUNT(*) AS n FROM ohlcv_daily WHERE project_id=1"
    ).fetchone()
    assert count_row["n"] == 2  # NO duplicado

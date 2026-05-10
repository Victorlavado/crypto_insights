"""OHLCV backfill: pagina Binance klines y persiste a ohlcv_daily.

Binance klines retorna max 1000 candles por request. 1d interval × 1000 = ~2.74
años por request. Pagina por ventanas hacia atrás hasta cubrir [start_date, end_date].

Idempotente: UPSERT por (project_id, candle_date). Re-correr el mismo rango
no duplica filas. Tolerante a fallos parciales: si una página falla, se loggea
y se continúa con la siguiente (las restantes quedan como gap, re-correr el
script las completa).

NO se ejecuta en cada batch — se invoca manualmente vía CLI cuando hace falta
extender histórico (e.g., al añadir un proyecto nuevo o re-procesar formula_version).
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx

from ..connectors.base import ConnectorError, build_http_client
from ..connectors.binance import BINANCE_BASE_URL, BinanceConnector
from ..logging_config import get_logger
from ..models import Project
from .persist import upsert_ohlcv_candles

log = get_logger(__name__)

PAGE_LIMIT = 1000  # max candles por request Binance


async def _fetch_page(
    client: httpx.AsyncClient,
    symbol: str,
    *,
    start_ms: int,
    end_ms: int,
) -> list[list[Any]]:
    """Single page fetch sin retry — confiamos en el connector wrapper para retries."""
    resp = await client.get(
        f"{BINANCE_BASE_URL}/api/v3/klines",
        params={
            "symbol": symbol,
            "interval": "1d",
            "startTime": start_ms,
            "endTime": end_ms,
            "limit": PAGE_LIMIT,
        },
    )
    resp.raise_for_status()
    return resp.json()  # type: ignore[no-any-return]


async def backfill_project_ohlcv(
    client: httpx.AsyncClient,
    conn: sqlite3.Connection,
    project: Project,
    *,
    start_date: date,
    end_date: date,
    pair_quote: str = "USDT",
) -> int:
    """Backfill rango [start_date, end_date] para project. Devuelve candles persistidos.

    Pagina hacia adelante en bloques de PAGE_LIMIT días. Cada bloque se persiste
    inmediatamente (no se acumula en memoria — útil si el backfill es grande).
    """
    assert project.id is not None
    symbol = f"{project.symbol}{pair_quote}"

    cursor_start = datetime.combine(start_date, datetime.min.time(), tzinfo=UTC)
    end_dt = datetime.combine(end_date, datetime.min.time(), tzinfo=UTC) + timedelta(days=1)
    total_written = 0

    while cursor_start < end_dt:
        page_end = min(cursor_start + timedelta(days=PAGE_LIMIT), end_dt)
        start_ms = int(cursor_start.timestamp() * 1000)
        end_ms = int(page_end.timestamp() * 1000) - 1

        try:
            raw = await _fetch_page(client, symbol, start_ms=start_ms, end_ms=end_ms)
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 400 and "Invalid symbol" in e.response.text:
                raise ConnectorError(
                    "binance", project.symbol, f"Binance does not list {symbol}"
                ) from e
            log.error(
                "backfill_page_failed",
                project=project.symbol,
                start=cursor_start.date().isoformat(),
                error=str(e),
            )
            break  # rompe el loop pero no levanta — el caller decide si re-intentar

        if not raw:
            log.info(
                "backfill_page_empty",
                project=project.symbol,
                start=cursor_start.date().isoformat(),
            )
            break

        candles = [_parse(row) for row in raw]
        written = upsert_ohlcv_candles(conn, project.id, candles)
        total_written += written
        conn.commit()  # flush por página para minimizar rollback en caso de crash

        log.info(
            "backfill_page_ok",
            project=project.symbol,
            page_start=cursor_start.date().isoformat(),
            candles=written,
        )

        # Avanzar cursor al día siguiente de la última candle recibida
        last_open_ms = int(raw[-1][0])
        last_open = datetime.fromtimestamp(last_open_ms / 1000, tz=UTC)
        next_start = last_open + timedelta(days=1)
        if next_start <= cursor_start:
            # No avance — evita loop infinito si la API devuelve mismas candles
            break
        cursor_start = next_start

    log.info(
        "backfill_project_done",
        project=project.symbol,
        candles_total=total_written,
        start=start_date.isoformat(),
        end=end_date.isoformat(),
    )
    return total_written


def _parse(row: list[Any]) -> dict[str, Any]:
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


async def backfill_all_binance_projects(
    conn: sqlite3.Connection,
    projects: Iterable[Project],
    *,
    start_date: date,
    end_date: date,
) -> dict[str, int]:
    """Itera proyectos backfill-eligible (los que pasan supports_project del Binance connector).

    Devuelve {symbol: candles_written}. Errores aislados por proyecto no
    rompen el loop (mismo principio que el batch diario).
    """
    out: dict[str, int] = {}
    async with build_http_client() as client:
        connector = BinanceConnector(client)  # solo para reusar supports_project
        for project in projects:
            if not connector.supports_project(project):
                continue
            try:
                n = await backfill_project_ohlcv(
                    client, conn, project, start_date=start_date, end_date=end_date
                )
                out[project.symbol] = n
            except ConnectorError as e:
                log.warning("backfill_project_skipped", project=project.symbol, error=str(e))
                out[project.symbol] = 0
    return out

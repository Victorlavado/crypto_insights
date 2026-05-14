"""OHLCV backfill: pagina Binance klines o Hyperliquid candles y persiste a ohlcv_daily.

Binance klines retorna max 1000 candles por request. 1d interval × 1000 = ~2.74
años por request. Hyperliquid `candleSnapshot` retorna max ~5000 candles por
request — paginamos en bloques de 1000 días igual que Binance para mantener
simetría.

Idempotente: UPSERT por (project_id, candle_date). Re-correr el mismo rango
no duplica filas. Tolerante a fallos parciales: si una página falla, se loggea
y se continúa con la siguiente (las restantes quedan como gap, re-correr el
script las completa).

NO se ejecuta en cada batch — se invoca manualmente vía CLI cuando hace falta
extender histórico (e.g., al añadir un proyecto nuevo o re-procesar formula_version,
o validar visualmente un breakout sobre histórico).

Source matters porque:
- Binance Spot lista BTC, ETH, AAVE, SUI, ZEC, etc. — fuente preferida para
  esos proyectos (longest history, deepest liquidity).
- Hyperliquid lista HYPE, FARTCOIN, PUMP, etc. como perps nativos — única
  fuente OHLCV pública para los que no están en Spot mayores.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx

from ..connectors.base import ConnectorError, build_http_client
from ..connectors.binance import BINANCE_BASE_URL, BinanceConnector
from ..connectors.hyperliquid import HL_BASE
from ..logging_config import get_logger
from ..models import Project
from .persist import upsert_ohlcv_candles

log = get_logger(__name__)

PAGE_LIMIT = 1000  # max candles por request Binance
HL_PAGE_LIMIT = 1000  # ventana en días por request Hyperliquid (server cap ~5000)


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


# ─────────────────────────────────────────────────────────────────────────────
# Hyperliquid backfill
# ─────────────────────────────────────────────────────────────────────────────


async def _fetch_hyperliquid_page(
    client: httpx.AsyncClient,
    coin: str,
    *,
    start_ms: int,
    end_ms: int,
) -> list[dict[str, Any]]:
    """Single page fetch contra Hyperliquid `candleSnapshot`.

    Body schema:
        {"type":"candleSnapshot","req":{"coin":..., "interval":"1d",
         "startTime":..., "endTime":...}}

    Response: list of {t, T, s, i, o, h, l, c, v, n} con strings para OHLCV
    y ints para t/T (ms).
    """
    resp = await client.post(
        f"{HL_BASE}/info",
        json={
            "type": "candleSnapshot",
            "req": {
                "coin": coin,
                "interval": "1d",
                "startTime": start_ms,
                "endTime": end_ms,
            },
        },
    )
    resp.raise_for_status()
    data = resp.json()
    return data if isinstance(data, list) else []


def _parse_hyperliquid_candle(row: dict[str, Any]) -> dict[str, Any]:
    """Normaliza al schema interno que comparte ohlcv_daily con Binance.

    quote_volume no está en HL response (no es spot); dejamos None.
    """
    return {
        "open_time": int(row["t"]),
        "open": float(row["o"]),
        "high": float(row["h"]),
        "low": float(row["l"]),
        "close": float(row["c"]),
        "volume": float(row["v"]),
        "close_time": int(row["T"]),
        "quote_volume": None,
        "trades": int(row.get("n", 0)),
    }


async def backfill_project_ohlcv_hyperliquid(
    client: httpx.AsyncClient,
    conn: sqlite3.Connection,
    project: Project,
    *,
    start_date: date,
    end_date: date,
    coin: str | None = None,
) -> int:
    """Backfill desde Hyperliquid perps. Mismo patrón que Binance, distinta fuente.

    `coin` permite override del símbolo Hyperliquid si difiere de project.symbol
    (raro; HYPE/FARTCOIN coinciden). Persiste a ohlcv_daily con source='hyperliquid'
    para que queries downstream sepan distinguir spot vs perp.
    """
    assert project.id is not None
    hl_coin = coin or project.symbol

    cursor_start = datetime.combine(start_date, datetime.min.time(), tzinfo=UTC)
    end_dt = datetime.combine(end_date, datetime.min.time(), tzinfo=UTC) + timedelta(days=1)
    total_written = 0

    while cursor_start < end_dt:
        page_end = min(cursor_start + timedelta(days=HL_PAGE_LIMIT), end_dt)
        start_ms = int(cursor_start.timestamp() * 1000)
        end_ms = int(page_end.timestamp() * 1000) - 1

        try:
            raw = await _fetch_hyperliquid_page(client, hl_coin, start_ms=start_ms, end_ms=end_ms)
        except httpx.HTTPStatusError as e:
            log.error(
                "backfill_hl_page_failed",
                project=project.symbol,
                coin=hl_coin,
                start=cursor_start.date().isoformat(),
                error=str(e),
            )
            break

        if not raw:
            log.info(
                "backfill_hl_page_empty",
                project=project.symbol,
                coin=hl_coin,
                start=cursor_start.date().isoformat(),
            )
            # HL puede devolver vacío antes del listing date — avanzar la ventana
            # un PAGE para no quedar en bucle. Si listing es muy posterior al
            # start_date, se acabará alcanzando.
            cursor_start = page_end
            continue

        candles = [_parse_hyperliquid_candle(row) for row in raw]
        written = upsert_ohlcv_candles(conn, project.id, candles, source="hyperliquid")
        total_written += written
        conn.commit()

        log.info(
            "backfill_hl_page_ok",
            project=project.symbol,
            coin=hl_coin,
            page_start=cursor_start.date().isoformat(),
            candles=written,
        )

        last_open_ms = int(raw[-1]["t"])
        last_open = datetime.fromtimestamp(last_open_ms / 1000, tz=UTC)
        next_start = last_open + timedelta(days=1)
        if next_start <= cursor_start:
            break
        cursor_start = next_start

    log.info(
        "backfill_hl_project_done",
        project=project.symbol,
        coin=hl_coin,
        candles_total=total_written,
        start=start_date.isoformat(),
        end=end_date.isoformat(),
    )
    return total_written


async def backfill_all_hyperliquid_projects(
    conn: sqlite3.Connection,
    projects: Iterable[Project],
    *,
    start_date: date,
    end_date: date,
) -> dict[str, int]:
    """Backfill desde Hyperliquid. NO usa supports_project del connector existente
    (ese gestiona funding/OI, no candles); cualquier coin listado en HL responde.

    Si HL no lista el coin, devuelve lista vacía y registramos 0 candles.
    """
    out: dict[str, int] = {}
    async with build_http_client() as client:
        for project in projects:
            try:
                n = await backfill_project_ohlcv_hyperliquid(
                    client, conn, project, start_date=start_date, end_date=end_date
                )
                out[project.symbol] = n
            except ConnectorError as e:
                log.warning("backfill_hl_project_skipped", project=project.symbol, error=str(e))
                out[project.symbol] = 0
    return out

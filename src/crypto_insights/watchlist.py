"""Watchlist loader.

Lee data/watchlist.yaml (real, gitignored) o fallback a watchlist.example.yaml.
UPSERT por symbol en projects para tolerar re-runs y rebrands (id estable).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import yaml

from .config import get_settings
from .logging_config import get_logger
from .models import Archetype, Project

log = get_logger(__name__)

_VALID_ARCHETYPES = {a.value for a in Archetype}


def _contract_field(value: object, *, symbol: str) -> str | None:
    """Coerce contract field to canonical string form.

    YAML 1.1 (used by PyYAML by default) parses unquoted 0x-hex as an int when all
    digits are hex. SQLite stores int but the data is logically a string address;
    coerce back to lowercase 0x-prefixed hex so downstream code never sees an int.
    All other string fields just pass through str().
    """
    if value is None:
        return None
    if isinstance(value, int) and not isinstance(value, bool):
        # Heuristic: pad to 40 hex chars (EVM address) or 64 (Starknet/long).
        return f"0x{value:040x}" if value.bit_length() <= 160 else f"0x{value:064x}"
    return str(value)


def _str_or_none(value: object) -> str | None:
    if value is None:
        return None
    return str(value)


def _resolve_path() -> Path:
    settings = get_settings()
    if settings.watchlist_path.exists():
        return settings.watchlist_path
    if settings.watchlist_fallback.exists():
        log.warning(
            "watchlist_using_fallback",
            real=str(settings.watchlist_path),
            fallback=str(settings.watchlist_fallback),
        )
        return settings.watchlist_fallback
    raise FileNotFoundError(
        f"Neither {settings.watchlist_path} nor {settings.watchlist_fallback} exists."
    )


def load_watchlist_file(path: Path | None = None) -> list[Project]:
    """Parsea YAML a lista de Project (id=None hasta persistir).

    Valida archetype contra enum cerrado para evitar typos silenciosos.
    """
    if path is None:
        path = _resolve_path()

    with path.open(encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    if not isinstance(raw, dict) or "projects" not in raw:
        raise ValueError(f"{path}: expected top-level dict with 'projects' key")

    items = raw["projects"]
    if not isinstance(items, list):
        raise ValueError(f"{path}: 'projects' must be a list")

    projects: list[Project] = []
    seen_symbols: set[str] = set()
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            raise ValueError(f"{path}: project #{i} is not a mapping")
        symbol = item.get("symbol")
        archetype_raw = item.get("archetype")
        if not symbol:
            raise ValueError(f"{path}: project #{i} missing 'symbol'")
        if archetype_raw not in _VALID_ARCHETYPES:
            raise ValueError(
                f"{path}: project {symbol!r} has invalid archetype {archetype_raw!r}. "
                f"Valid: {sorted(_VALID_ARCHETYPES)}"
            )
        if symbol in seen_symbols:
            raise ValueError(f"{path}: duplicate symbol {symbol!r}")
        seen_symbols.add(symbol)

        # Defensive: YAML 1.1 (PyYAML default) parses unquoted 0x-hex as int — see _contract_field.
        projects.append(
            Project(
                id=None,
                symbol=str(symbol),
                archetype=Archetype(archetype_raw),
                coingecko_id=_str_or_none(item.get("coingecko_id")),
                chain=_str_or_none(item.get("chain")),
                contract=_contract_field(item.get("contract"), symbol=str(symbol)),
                notes=_str_or_none(item.get("notes")),
            )
        )
    return projects


def sync_watchlist(conn: sqlite3.Connection, path: Path | None = None) -> list[Project]:
    """UPSERT watchlist a la tabla projects. Retorna lista con ids poblados.

    Idempotente: re-correrlo no duplica, actualiza notes/archetype si cambiaron.
    Mantiene id estable por symbol (necesario para FK).
    """
    parsed = load_watchlist_file(path)
    out: list[Project] = []

    for p in parsed:
        # UPSERT con preservación de id (autoincrement). ON CONFLICT(symbol).
        conn.execute(
            """
            INSERT INTO projects (symbol, coingecko_id, archetype, chain, contract, notes)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(symbol) DO UPDATE SET
                coingecko_id = excluded.coingecko_id,
                archetype    = excluded.archetype,
                chain        = excluded.chain,
                contract     = excluded.contract,
                notes        = excluded.notes
            """,
            (p.symbol, p.coingecko_id, p.archetype.value, p.chain, p.contract, p.notes),
        )
        row = conn.execute(
            "SELECT id FROM projects WHERE symbol = ?",
            (p.symbol,),
        ).fetchone()
        out.append(
            Project(
                id=row[0] if not isinstance(row, sqlite3.Row) else row["id"],
                symbol=p.symbol,
                archetype=p.archetype,
                coingecko_id=p.coingecko_id,
                chain=p.chain,
                contract=p.contract,
                notes=p.notes,
            )
        )
    log.info("watchlist_synced", count=len(out))
    return out


def list_projects(conn: sqlite3.Connection) -> list[Project]:
    """Lee proyectos persistidos. Útil después de sync_watchlist."""
    rows = conn.execute(
        "SELECT id, symbol, coingecko_id, archetype, chain, contract, notes FROM projects "
        "ORDER BY symbol"
    ).fetchall()
    return [
        Project(
            id=r["id"],
            symbol=r["symbol"],
            archetype=Archetype(r["archetype"]),
            coingecko_id=r["coingecko_id"],
            chain=r["chain"],
            contract=r["contract"],
            notes=r["notes"],
        )
        for r in rows
    ]

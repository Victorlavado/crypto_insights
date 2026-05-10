"""Watchlist loader tests."""

from __future__ import annotations

import sqlite3
import textwrap
from pathlib import Path

import pytest

from crypto_insights.db import apply_migrations, connect
from crypto_insights.models import Archetype
from crypto_insights.watchlist import (
    _contract_field,
    load_watchlist_file,
    sync_watchlist,
)


def test_contract_field_reconstructs_evm_hex_from_int() -> None:
    """YAML 1.1 parses 0x0000...0001 as int(1). Loader must rehydrate as 40-char hex."""
    assert _contract_field(0x44FF8620B8CA30902395A7BD3F2407E1A091BF73, symbol="VIRTUAL").startswith(
        "0x"
    )
    out = _contract_field(0x44FF8620B8CA30902395A7BD3F2407E1A091BF73, symbol="VIRTUAL")
    assert out is not None and len(out) == 42  # 0x + 40 hex chars
    assert out == "0x44ff8620b8ca30902395a7bd3f2407e1a091bf73"


def test_contract_field_reconstructs_long_hex_starknet() -> None:
    """Starknet addresses can be 32 bytes — loader pads to 64 hex chars."""
    value = int("0x04718f5a0fc34cc1af16a1cdee98ffb20c31f5cd61d6ab07201858f4287c938d", 16)
    out = _contract_field(value, symbol="STRK")
    assert out is not None and len(out) == 66  # 0x + 64 hex chars
    assert out == "0x04718f5a0fc34cc1af16a1cdee98ffb20c31f5cd61d6ab07201858f4287c938d"


def test_contract_field_passes_through_strings() -> None:
    """Base58 (Solana) and 'native' must pass through unchanged."""
    assert _contract_field("native", symbol="HYPE") == "native"
    assert (
        _contract_field("2zMMhcVQEXDtdE6vsFS7S7D5oUodfJHE8vd1gnBouauv", symbol="PENGU")
        == "2zMMhcVQEXDtdE6vsFS7S7D5oUodfJHE8vd1gnBouauv"
    )
    assert _contract_field(None, symbol="X") is None


def test_load_watchlist_validates_archetype(tmp_path: Path) -> None:
    bad = tmp_path / "watchlist.yaml"
    bad.write_text(
        textwrap.dedent(
            """
            projects:
              - symbol: FOO
                archetype: not-a-real-archetype
            """
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="invalid archetype"):
        load_watchlist_file(bad)


def test_load_watchlist_rejects_duplicates(tmp_path: Path) -> None:
    dup = tmp_path / "watchlist.yaml"
    dup.write_text(
        textwrap.dedent(
            """
            projects:
              - symbol: BTC
                archetype: l1-maduro
              - symbol: BTC
                archetype: l1-maduro
            """
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="duplicate symbol"):
        load_watchlist_file(dup)


def test_sync_watchlist_is_idempotent(tmp_path: Path) -> None:
    yaml_path = tmp_path / "watchlist.yaml"
    yaml_path.write_text(
        textwrap.dedent(
            """
            projects:
              - symbol: BTC
                archetype: l1-maduro
                coingecko_id: bitcoin
              - symbol: SOL
                archetype: l1-maduro
                coingecko_id: solana
            """
        ),
        encoding="utf-8",
    )
    db = tmp_path / "test.db"
    apply_migrations(db_path=db)
    with sqlite3.connect(db) as raw_conn:
        raw_conn.execute("PRAGMA foreign_keys=ON")
    with connect(db) as conn:
        first = sync_watchlist(conn, path=yaml_path)
        second = sync_watchlist(conn, path=yaml_path)

    assert [p.symbol for p in first] == ["BTC", "SOL"]
    assert [p.id for p in first] == [p.id for p in second]  # ids stable
    assert all(p.archetype == Archetype.L1_MADURO for p in first)

"""Smart money signal tests — pipeline 5 pasos."""

from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path

import pytest

from crypto_insights import db as db_mod
from crypto_insights.models import Archetype, Project
from crypto_insights.signals.smart_money import (
    HolderRecord,
    compute_smart_money_delta,
    filter_holders,
    load_excluded_addresses,
    persist_holders_snapshot,
    run_smart_money_pipeline,
)


@pytest.fixture
def excluded_sample() -> dict[str, dict[str, str]]:
    """Set de excluded mínimo para tests."""
    return {
        "solana": {
            "RaydiumPool2222222222222222222222222222222222": "dex",
            "BinanceHotWallet5333333333333333333333333333": "cex",
        },
        "ethereum": {
            "0xbinancehotwallet001111111111111111111111": "cex",
            "0xaavepoolcontract000000000000000000000000": "dex",
        },
    }


def test_load_excluded_addresses_normalizes_evm_lowercase(tmp_path: Path) -> None:
    yaml_text = """
ethereum:
  cex:
    - address: "0x28C6c06298d514Db089934071355E5743bf21d60"
      name: Binance 14
solana:
  cex:
    - address: "5tzFkiKscXHK5ZXCGbXZxdw7gTjjD1mBwuoFbhUvuAi9"
      name: Binance (Sol)
"""
    path = tmp_path / "ex.yaml"
    path.write_text(yaml_text)
    excluded = load_excluded_addresses(path)
    # EVM normalized to lowercase
    assert "0x28c6c06298d514db089934071355e5743bf21d60" in excluded["ethereum"]
    # Solana base58 preserved
    assert "5tzFkiKscXHK5ZXCGbXZxdw7gTjjD1mBwuoFbhUvuAi9" in excluded["solana"]


def test_filter_holders_excludes_tagged(
    excluded_sample: dict[str, dict[str, str]],
) -> None:
    holders = [
        {"owner": "WhaleEOA111111111111111111111111111111111111", "balance": 1000.0, "rank": 1},
        {"owner": "RaydiumPool2222222222222222222222222222222222", "balance": 800.0, "rank": 2},
        {"owner": "SecondEOA22222222222222222222222222222222222", "balance": 500.0, "rank": 3},
        {"owner": "BinanceHotWallet5333333333333333333333333333", "balance": 200.0, "rank": 4},
    ]
    records = filter_holders(holders, chain="solana", excluded=excluded_sample)
    by_owner = {r.owner: r for r in records}
    assert by_owner["RaydiumPool2222222222222222222222222222222222"].label == "dex"
    assert not by_owner["RaydiumPool2222222222222222222222222222222222"].included
    assert by_owner["BinanceHotWallet5333333333333333333333333333"].label == "cex"
    assert by_owner["WhaleEOA111111111111111111111111111111111111"].included
    assert by_owner["WhaleEOA111111111111111111111111111111111111"].label is None


def test_filter_holders_excludes_contracts() -> None:
    holders = [
        {"owner": "0xpool", "balance": 100.0, "rank": 1, "is_contract": True},
        {"owner": "0xeoa", "balance": 50.0, "rank": 2, "is_contract": False},
    ]
    records = filter_holders(holders, chain="ethereum", excluded={})
    by_owner = {r.owner: r for r in records}
    assert not by_owner["0xpool"].included
    assert by_owner["0xpool"].label == "contract"
    assert by_owner["0xeoa"].included


def test_filter_holders_flags_concentration_for_top1() -> None:
    """Top-1 con >50% del top-100 observado → excluido (likely treasury)."""
    holders = [
        {"owner": "treasury", "balance": 1000.0, "rank": 1},
        # otros holders pequeños — treasury concentra >50% del top-100 visible
        *[{"owner": f"eoa{i}", "balance": 5.0, "rank": i + 1} for i in range(1, 20)],
    ]
    records = filter_holders(holders, chain="solana", excluded={})
    by_owner = {r.owner: r for r in records}
    assert not by_owner["treasury"].included
    assert by_owner["treasury"].label == "concentrated"
    assert by_owner["eoa1"].included


def test_compute_delta_positive_when_eoas_accumulate() -> None:
    """EOA gana balance → delta positivo. Programs excluidos no afectan."""
    prior = [
        HolderRecord("eoa1", 100.0, 1, False, False, None, included=True),
        HolderRecord("eoa2", 50.0, 2, False, False, None, included=True),
        HolderRecord("pool", 500.0, 3, True, False, "dex", included=False),
    ]
    current = [
        HolderRecord("eoa1", 150.0, 1, False, False, None, included=True),  # +50
        HolderRecord("eoa2", 60.0, 2, False, False, None, included=True),  # +10
        HolderRecord("pool", 400.0, 3, True, False, "dex", included=False),  # excluded
    ]
    delta = compute_smart_money_delta(current, prior)
    assert delta is not None
    # Delta sum = +60 sobre denominator max(included_curr=210, included_prior=150) = 210
    # → ≈ 28.5%
    assert delta == pytest.approx((60 / 210) * 100, rel=0.01)


def test_compute_delta_returns_none_without_prior() -> None:
    current = [HolderRecord("eoa", 100.0, 1, False, False, None, included=True)]
    assert compute_smart_money_delta(current, []) is None
    assert compute_smart_money_delta([], current) is None


def test_compute_delta_uses_total_supply_when_given() -> None:
    prior = [HolderRecord("eoa", 100.0, 1, False, False, None, included=True)]
    current = [HolderRecord("eoa", 200.0, 1, False, False, None, included=True)]
    delta = compute_smart_money_delta(current, prior, total_supply_units=10000.0)
    # +100 / 10000 = 1%
    assert delta == pytest.approx(1.0)


@pytest.fixture
def temp_db(tmp_path: Path) -> sqlite3.Connection:
    """DB en disco con schema completo aplicado."""
    db_path = tmp_path / "test.db"
    db_mod.apply_migrations(
        db_path=db_path, migrations_dir=Path(__file__).resolve().parents[2] / "migrations"
    )
    conn = db_mod.connect(db_path=db_path)
    # Crear batch + proyecto
    conn.execute(
        "INSERT INTO batches (batch_id, started_at, status) VALUES ('2026-05-10', datetime('now'), 'running')"
    )
    conn.execute(
        "INSERT INTO batches (batch_id, started_at, status) VALUES ('2026-05-03', datetime('now'), 'complete')"
    )
    conn.execute(
        """
        INSERT INTO projects (id, symbol, archetype, chain, contract)
        VALUES (1, 'TEST', 'memecoin-brand', 'solana', 'mint123')
        """
    )
    yield conn
    conn.close()


def test_run_pipeline_persists_and_returns_none_first_run(
    temp_db: sqlite3.Connection,
) -> None:
    project = Project(
        id=1,
        symbol="TEST",
        archetype=Archetype.MEMECOIN_BRAND,
        chain="solana",
        contract="mint123",
    )
    holders = [
        {"owner": "eoa1", "balance": 1000.0, "rank": 1},
        {"owner": "eoa2", "balance": 500.0, "rank": 2},
    ]
    delta = run_smart_money_pipeline(
        temp_db,
        project,
        batch_id="2026-05-10",
        snapshot_date=date(2026, 5, 10),
        holders_payload=holders,
        source="helius",
        excluded={},
    )
    assert delta is None  # No prior snapshot
    persisted = temp_db.execute(
        "SELECT COUNT(*) AS n FROM holders_snapshots WHERE project_id=1"
    ).fetchone()
    assert persisted["n"] == 2


def test_run_pipeline_computes_delta_with_prior(
    temp_db: sqlite3.Connection,
) -> None:
    project = Project(
        id=1,
        symbol="TEST",
        archetype=Archetype.MEMECOIN_BRAND,
        chain="solana",
        contract="mint123",
    )
    # Plant prior snapshot at 2026-05-03 con 5 holders distribuidos (no concentration)
    prior_holders = [
        HolderRecord(f"eoa{i}", 100.0, i, False, False, None, included=True) for i in range(1, 6)
    ]
    persist_holders_snapshot(
        temp_db,
        project_id=1,
        batch_id="2026-05-03",
        snapshot_date=date(2026, 5, 3),
        source="helius",
        records=prior_holders,
    )
    # Current snapshot: EOAs acumulan +20 cada uno
    holders = [{"owner": f"eoa{i}", "balance": 120.0, "rank": i} for i in range(1, 6)]
    delta = run_smart_money_pipeline(
        temp_db,
        project,
        batch_id="2026-05-10",
        snapshot_date=date(2026, 5, 10),
        holders_payload=holders,
        source="helius",
        excluded={},
    )
    assert delta is not None
    # delta_sum = +100, denom = max(600, 500) = 600 → ~16.7%
    assert delta == pytest.approx((100 / 600) * 100, rel=0.01)

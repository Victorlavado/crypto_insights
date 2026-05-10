-- 0002-ohlcv-history-and-holders.sql
-- Phase 2 follow-up: historical OHLCV storage + top holders snapshots.
--
-- WHY ohlcv_daily:
--   raw_snapshots holds the *latest* Binance fetch (400 candles). For backtest /
--   look-back over many years we need a separate table indexed by date so we can
--   query "give me 2024 OHLCV for HYPE" without re-fetching from Binance.
--
-- WHY holders_snapshots (separate from raw_snapshots):
--   Top holders is a list-of-rows payload that grows linearly. Keeping it as raw
--   JSON in raw_snapshots works for indicators but is awkward when computing
--   per-address delta vs prior batch. A dedicated table lets us index by
--   (project, snapshot_date, owner_address) and run set-difference queries.
--
-- Plan conventions:
--   - UPSERT idempotent by primary key.
--   - PRAGMA foreign_keys=ON applies at connection level (see db.py).

CREATE TABLE ohlcv_daily (
    project_id       INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    candle_date      TEXT NOT NULL,
    open             REAL NOT NULL,
    high             REAL NOT NULL,
    low              REAL NOT NULL,
    close            REAL NOT NULL,
    volume           REAL NOT NULL,
    quote_volume     REAL,
    trades           INTEGER,
    source           TEXT NOT NULL DEFAULT 'binance',
    inserted_at      TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (project_id, candle_date)
);

CREATE INDEX idx_ohlcv_date ON ohlcv_daily (candle_date);

CREATE TABLE holders_snapshots (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id        INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    batch_id          TEXT NOT NULL REFERENCES batches(batch_id) ON DELETE CASCADE,
    snapshot_date     TEXT NOT NULL,
    source            TEXT NOT NULL,                     -- helius|alchemy|moralis
    owner_address     TEXT NOT NULL,                     -- already resolved (ATA -> owner)
    balance           REAL NOT NULL,
    rank              INTEGER NOT NULL,                  -- 1-based position by balance desc
    is_contract       INTEGER NOT NULL DEFAULT 0,        -- 0/1; EVM eth_getCode != "0x"
    is_program        INTEGER NOT NULL DEFAULT 0,        -- 0/1; Solana program-owned ATA
    label             TEXT,                              -- 'cex'|'dex'|'bridge'|'vesting'|null
    fetched_at        TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (project_id, snapshot_date, owner_address, source)
);

CREATE INDEX idx_holders_lookup ON holders_snapshots (project_id, snapshot_date DESC);
CREATE INDEX idx_holders_batch ON holders_snapshots (batch_id);

-- Rollback in 0002-ohlcv-history-and-holders.rollback.sql

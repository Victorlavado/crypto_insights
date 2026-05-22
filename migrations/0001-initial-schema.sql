-- 0001-initial-schema.sql
-- Initial schema for Crypto Position Manager MVP.
-- Covers Phase 0 (projects, batches, raw_snapshots) + Phase 1 (events, derived_signals,
-- project_state, project_state_history). Applied as a single migration to keep the ERD
-- consistent; future extensions go in subsequent migrations.
--
-- Plan conventions:
--   - PRAGMA foreign_keys=ON must be enabled on EACH connection (default OFF in SQLite).
--     This migration does NOT manage that -- the connection wrapper in src/crypto_insights/db.py does.
--   - PROJECTS.id numeric + UNIQUE(symbol) tolerates rebrands without losing history.
--   - RAW_SNAPSHOTS.payload stores raw JSON + payload_schema_version for upstream evolution.
--   - DERIVED_SIGNALS.formula_version in UNIQUE allows backfill re-runs without overwriting old computations.
--   - PROJECT_STATE_HISTORY append-only from day 1 (ADR 0006).
--   - BATCHES.heartbeat_at + orphan cleanup is handled by pipeline.

CREATE TABLE projects (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol          TEXT NOT NULL UNIQUE,
    coingecko_id    TEXT,
    archetype       TEXT NOT NULL,
    chain           TEXT,
    contract        TEXT,
    notes           TEXT,
    added_at        TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE batches (
    batch_id        TEXT PRIMARY KEY,                 -- YYYY-MM-DD
    started_at      TEXT NOT NULL DEFAULT (datetime('now')),
    heartbeat_at    TEXT,                             -- updated every ~30s during run
    finished_at     TEXT,
    status          TEXT NOT NULL DEFAULT 'running',  -- running|complete|partial|failed
    error_summary   TEXT,                             -- JSON: {sources_failed: [{source, project, error}]}
    CHECK (status IN ('running', 'complete', 'partial', 'failed'))
);

CREATE TABLE raw_snapshots (
    id                       INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id               INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    source                   TEXT NOT NULL,
    batch_id                 TEXT NOT NULL REFERENCES batches(batch_id) ON DELETE CASCADE,
    snapshot_date            TEXT NOT NULL,
    payload                  TEXT,                                          -- raw JSON from connector
    payload_schema_version   INTEGER NOT NULL DEFAULT 1,
    connector_version        TEXT NOT NULL DEFAULT 'v0.1.0',
    fetched_at               TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (project_id, source, snapshot_date)
);

CREATE TABLE derived_signals (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id        INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    batch_id          TEXT NOT NULL REFERENCES batches(batch_id) ON DELETE CASCADE,
    signal_date       TEXT NOT NULL,
    signal_name       TEXT NOT NULL,                              -- atr_pct, rvol, holders_delta_7d, ...
    value             REAL,                                       -- nullable: signal may be N/A
    formula_version   TEXT NOT NULL DEFAULT 'v1',
    UNIQUE (project_id, signal_name, signal_date, formula_version)
);

CREATE TABLE project_state (
    project_id        INTEGER PRIMARY KEY REFERENCES projects(id) ON DELETE CASCADE,
    current_state     TEXT NOT NULL,                              -- see CHECK
    composite_score   REAL,                                       -- nullable when state=degraded
    reason_code       TEXT NOT NULL DEFAULT 'NORMAL',
    reason_data       TEXT,                                       -- structured JSON
    reason_human      TEXT,
    layer2_flag       TEXT NOT NULL DEFAULT 'green',              -- green|amber|red
    layer1_scores     TEXT,                                       -- JSON: {signal: {value, weight}}
    has_gaps          INTEGER NOT NULL DEFAULT 0,                 -- 0/1 boolean
    batches_in_state  INTEGER NOT NULL DEFAULT 1,                 -- hysteresis counter (ADR 0006)
    batch_id          TEXT NOT NULL REFERENCES batches(batch_id),
    updated_at        TEXT NOT NULL DEFAULT (datetime('now')),
    CHECK (current_state IN ('acumulacion','aceleracion','distribucion','colapso','reset','blocked','degraded','unknown')),
    CHECK (layer2_flag IN ('green','amber','red'))
);

-- Append-only from day 1 (ADR 0006). Enables 'blocked since day N' + retrospective validation.
CREATE TABLE project_state_history (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id        INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    batch_id          TEXT NOT NULL REFERENCES batches(batch_id) ON DELETE CASCADE,
    state             TEXT NOT NULL,
    composite_score   REAL,
    reason_code       TEXT NOT NULL,
    reason_data       TEXT,
    layer2_flag       TEXT NOT NULL,
    has_gaps          INTEGER NOT NULL DEFAULT 0,
    recorded_at       TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (project_id, batch_id),
    CHECK (state IN ('acumulacion','aceleracion','distribucion','colapso','reset','blocked','degraded','unknown'))
);

CREATE TABLE events (
    id                     INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id             INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    event_type             TEXT NOT NULL,                                  -- unlock|listing|halving|fork|...
    event_date             TEXT NOT NULL,
    magnitude_pct          REAL,                                           -- if unlock: % of circulating
    allocation_category    TEXT,                                           -- team|investors|ecosystem|foundation|public|unknown
    magnitude_weighted     REAL,                                           -- magnitude_pct * category_weight
    source                 TEXT NOT NULL,                                  -- defillama|tokenomist|manual|...
    external_event_id      TEXT,                                           -- upstream dedup key
    notes                  TEXT,
    created_at             TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Partial unique index: when external_event_id is present use that; otherwise fallback to manual quad.
CREATE UNIQUE INDEX idx_events_external_dedup
    ON events (project_id, event_type, event_date, external_event_id)
    WHERE external_event_id IS NOT NULL;

CREATE UNIQUE INDEX idx_events_manual_dedup
    ON events (project_id, event_type, event_date, source)
    WHERE external_event_id IS NULL;

-- Mandatory secondary indexes (without these dashboard queries do full scans).
CREATE INDEX idx_derived_lookup ON derived_signals (project_id, signal_name, signal_date DESC);
CREATE INDEX idx_derived_batch ON derived_signals (batch_id);
CREATE INDEX idx_raw_lookup ON raw_snapshots (project_id, source, snapshot_date DESC);
CREATE INDEX idx_raw_batch ON raw_snapshots (batch_id);
CREATE INDEX idx_state_history_project ON project_state_history (project_id, recorded_at DESC);
CREATE INDEX idx_state_history_batch ON project_state_history (batch_id);
CREATE INDEX idx_events_window ON events (event_date, event_type);
CREATE INDEX idx_batches_status ON batches (status, started_at DESC);
-- Rollback in 0001-initial-schema.rollback.sql

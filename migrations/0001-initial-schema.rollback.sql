-- Rollback for 0001-initial-schema.sql
DROP INDEX IF EXISTS idx_batches_status;
DROP INDEX IF EXISTS idx_events_window;
DROP INDEX IF EXISTS idx_state_history_batch;
DROP INDEX IF EXISTS idx_state_history_project;
DROP INDEX IF EXISTS idx_raw_batch;
DROP INDEX IF EXISTS idx_raw_lookup;
DROP INDEX IF EXISTS idx_derived_batch;
DROP INDEX IF EXISTS idx_derived_lookup;
DROP INDEX IF EXISTS idx_events_manual_dedup;
DROP INDEX IF EXISTS idx_events_external_dedup;
DROP TABLE IF EXISTS events;
DROP TABLE IF EXISTS project_state_history;
DROP TABLE IF EXISTS project_state;
DROP TABLE IF EXISTS derived_signals;
DROP TABLE IF EXISTS raw_snapshots;
DROP TABLE IF EXISTS batches;
DROP TABLE IF EXISTS projects;

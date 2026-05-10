-- Rollback for 0002-ohlcv-history-and-holders.sql
DROP INDEX IF EXISTS idx_holders_batch;
DROP INDEX IF EXISTS idx_holders_lookup;
DROP TABLE IF EXISTS holders_snapshots;
DROP INDEX IF EXISTS idx_ohlcv_date;
DROP TABLE IF EXISTS ohlcv_daily;

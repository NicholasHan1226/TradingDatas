# SharedSignals/cron

This directory contains thin cron wrappers for SharedSignals production jobs.

- Scripts must `cd` to the SharedSignals root before running Python.
- Scripts may source root `.env` for local configuration, but must not contain secrets.
- Use `flock` locks under `logs/locks/` to avoid overlapping runs.
- Write stdout/stderr to `logs/cron/`.
- Keep business logic in the main SharedSignals modules; cron scripts should only orchestrate.

## Active production groups

- `collectors.sh`: Tushare P0-P6 tiered collection.
- `crypto_collect.sh` and `pm_collect.sh`: 5-minute Crypto and Polymarket collection.
- `cn_futures_5min.sh` and `cn_futures_daily.sh`: China futures intraday and settlement data.
- `duckdb_sync.sh`: SQLite read model to DuckDB mirror sync.
- `patrol.sh`, `health_sla.sh`, `watchdog.sh`: health checks and bounded self-heal loop.
- `capability_scan.sh`: API capability registry refresh.

## Environment surface

- `PATROL_SCORE_THRESHOLD` controls whether `patrol.sh` triggers `heal.py`.
- `PATROL_*` variables tune patrol thresholds without code changes.
- `WATCHDOG_INPUT_DIR` is the shared drop directory for `health_sla` and cross-system health JSON.
- `WATCHDOG_EXTERNAL_REPORT_MAX_AGE_MIN` controls how long watchdog trusts external reports.
- `SHAREDSIGNALS_HEALTH_SLA_TIMEOUT` controls the per-table freshness SLA wrapper timeout.

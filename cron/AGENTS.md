# SharedSignals/cron

This directory contains retained legacy compatibility cron wrappers and a
repository schedule inventory. It is not the onboarding path for the target
provider-neutral data service.

- Scripts must `cd` to the SharedSignals root before running Python.
- Scripts may source root `.env` for local configuration, but must not contain secrets.
- Use `flock` locks under `logs/locks/` to avoid overlapping runs.
- Every cron job that reads or writes the read model must source `maintenance_lock.sh` and acquire the shared maintenance lock. Deploy/rollback holds the exclusive side, so cron must skip rather than access SQLite during snapshot or restore.
- Write stdout/stderr to `logs/cron/`.
- Keep business logic in the main SharedSignals modules; cron scripts should only orchestrate.

## Legacy compatibility schedule inventory

New datasets must not be onboarded by adding a tier, `--only-api` entry,
dataset-specific wrapper, or cron branch here. Target scheduling is derived from
the provider-neutral registry and uses the generic provider runner; these
wrappers remain only until their consumers are migrated and no-use/rollback
evidence permits retirement.

- `cron/crontab.txt` is the repository target template only. It does not prove
  that the root `crontab.txt` snapshot or the production live crontab changed.
- `collectors.sh`: no-argument and `--all` runs are limited to domestic Beta
  tiers P0, P1, P3, P4, and P6. P7 low-frequency bars remain handled by
  `tushare_low_frequency_collect.sh`. Default P4 execution passes an explicit
  `--only-api` allowlist for `cn_cpi`, `cn_pmi`, `cn_m`, `cn_ppi`, `shibor`,
  `shibor_lpr`, `cn_gdp`, `sf_month`, `index_dailybasic`, and `repo_daily`;
  foreign APIs retained in the P4 config are not part of the default run.
- `tushare_events_collect.sh`: Tushare news/announcement/report event lane; it runs selected P6 event APIs only and must not be replaced by high-frequency full P6 collection.
- `tushare_low_frequency_collect.sh`: Tushare P7 weekly/monthly lane; it runs low-frequency bars only and must not be folded into daily P6 collection.
- `cn_futures_5min.sh` and `cn_futures_daily.sh`: China futures intraday and settlement data.
- `external_api_probe.sh`: every 5 minutes verifies the public hostname reaches the SharedSignals authentication gate; it does not need or store a consumer token by default. Production runs this read-only probe from root because the SSH relay key is root-only; the live root crontab supplies `SHAREDSIGNALS_EXTERNAL_PROBE_SSH_TARGET` and `SHAREDSIGNALS_EXTERNAL_PROBE_SSH_KEY`, while the repository cron manifest remains a standard command entry for coverage checks.
- `health_sla.sh`, `source_governance_monitor.sh`, and `capability_scan.sh` are
  temporarily retained read-only governance/capability checks in the target.

## Retained but unscheduled compatibility wrappers

- `collectors.sh --tier P2_financial_daily` and
  `collectors.sh --tier P5_hk_us_daily` remain recognized for explicit
  compatibility use, but both tiers are absent from no-argument, `--all`, and
  target schedule execution. P2 remains incident-paused and retains its bounded
  timeout, provider-call, admitted-row, deadline, and low-priority runner gates.
- `crypto_collect.sh`, `pm_collect.sh`, `opening_gate.sh`,
  `green_gate_report.sh`, `patrol.sh`, `watchdog.sh`, and
  `proxy_relay_health.sh` remain repository wrappers but have no active entry in
  the domestic Beta target template. Their presence is not evidence of live
  scheduling or production state.
- P2, `duckdb_sync.sh`, `sqlite_maintenance.sh`, and
  `sw2021_reference_collect.sh` remain disabled/commented pending their existing
  gates. P2 is supported only for explicit compatibility execution; it is not a
  default tier or active target-template job.
- `duckdb_sync.sh` remains the SQLite-to-DuckDB analytics mirror wrapper. It is
  not the trading read path; before any future scheduling, its single-snapshot,
  reconciliation, load-test, and maintenance-lock boundaries still apply.

## Environment surface

- `PATROL_SCORE_THRESHOLD` and `PATROL_*` remain compatibility settings for the
  unscheduled patrol wrapper.
- `WATCHDOG_INPUT_DIR` and `WATCHDOG_EXTERNAL_REPORT_MAX_AGE_MIN` remain
  compatibility settings for retained health/watchdog wrappers.
- `SHAREDSIGNALS_HEALTH_SLA_TIMEOUT` controls the per-table freshness SLA wrapper timeout.

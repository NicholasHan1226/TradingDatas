# DuckDB consistent-source sync runbook

## Purpose and boundary

SQLite is the authoritative SharedSignals read model. DuckDB is a rebuildable
analytics mirror and is not a trading-hot read path. A mirror sync must never
claim green from tables read at different SQLite source points.

Collectors and `cron/duckdb_sync.sh` intentionally hold the same maintenance
**shared** lock so collectors are not skipped for the whole DuckDB job. The
DuckDB worker therefore uses SQLite's native backup API to create one source
snapshot before opening the DuckDB mirror. All table scans and reconciliation
in that run use the snapshot path.

This workflow does not migrate SQLite, restore data, alter collector cadence or
change API/PIT semantics.

## Runtime paths and limits

- authority: `/opt/investment/SharedSignals/runtime/read_model/marketdata.sqlite`
- mirror: `/opt/investment/SharedSignals/data/marketdata.duckdb`
- temporary snapshot directory: authority parent + `.duckdb_sync_snapshots/`
- directory/file mode: `0700` / `0600`
- default preflight: available bytes must be at least
  `max(main file bytes, page_count * page_size) + 5 GiB`, so committed WAL pages
  are included
- projected filesystem usage after snapshot must remain at or below 90%
- native backup deadline: 240 seconds
- outer cron timeout: 600 seconds

Optional overrides:

- `SHAREDSIGNALS_DUCKDB_SNAPSHOT_DIR`
- `SHAREDSIGNALS_DUCKDB_SNAPSHOT_RESERVE_BYTES`
- `SHAREDSIGNALS_DUCKDB_SNAPSHOT_TIMEOUT`
- `SHAREDSIGNALS_DUCKDB_SNAPSHOT_MAX_FS_USAGE_PCT`
- `SHAREDSIGNALS_DUCKDB_SNAPSHOT_STALE_SECONDS`

Do not lower the reserve or enlarge the timeout in production without a fresh
disk and duration benchmark. The outer timeout must still leave time for sync,
reconcile and `finally` cleanup.

The 5 GiB reserve is not a standalone approval condition. The logical SQLite
size, projected filesystem percentage, DuckDB work filesystem and concurrent
writer state must all pass. If live usage is already at or above the 90% patrol
stop threshold, do not run a snapshot benchmark merely to measure it.

## Fail-closed sequence

1. Reject a missing, non-regular or symlink authority.
2. Prepare only the dedicated snapshot directory. While the production wrapper
   holds its single-instance lock, remove only old regular files with the fixed
   `duckdb-sync-` prefix that are older than two outer 600-second timeouts.
   Fresh files, symlinks and unrelated files are never removed.
3. Read SQLite logical page size/count, then check free space, projected usage
   ceiling and any distinct DuckDB work filesystem before creating the snapshot
   file or opening DuckDB.
4. Create a unique 0600 temp file and run `sqlite3.Connection.backup()` with an
   internal deadline.
5. Lightly validate schema visibility and all 16 required tables, then atomically
   rename the temp file to the run snapshot.
6. Construct the sync adapter with the snapshot as its SQLite path. Sync and
   reconciliation must use that same path.
7. Remove exactly the snapshot inode in `finally`. Cleanup refusal or failure
   makes the run red.

Do not replace this with retries against live SQLite and do not make the whole
job take the exclusive maintenance lock.

## Artifact contract

`logs/watchdog_inputs/duckdb_sync.json` is the atomic latest projection and
`logs/duckdb_merge.jsonl` is append-only history. A successful run resets
`consecutive_failure_count` to zero but retains `last_failure_at` and bounded
`recent_failures`.

Snapshot evidence includes:

- `snapshot_id`, bytes, inode, mode, uid/gid and elapsed seconds;
- authority inode/size/mtime and WAL/SHM state before and after backup;
- available/required/source/reserve bytes;
- logical source bytes, WAL bytes, projected usage and work filesystems;
- stale cleanup, lightweight validation and final snapshot cleanup;
- structured `error_class`, including space, permission, timeout, backup,
  validation, sync, reconciliation and cleanup failures.

## Production acceptance

Before enabling this path, re-run safe-release preflight and verify the exact
production database/mirror paths, runtime user, disk, cron and rollback point.
The current canonical `deploy.sh` always runs `storage/migrate.py`; it is not a
code-only deploy entry. When schema migration is outside the authorization, stop
before deployment rather than manually pulling around the script.

After an authorized deployment, one single-instance run must prove:

- total snapshot + sync + reconcile + cleanup under 480 seconds;
- 16/16 tables `status=ok` and event identity mismatch/invalid counts zero;
- three empty industry tables remain legal 0/0 when no promoted data exists;
- no snapshot temp/final residual;
- no collector row loss across the snapshot interval;
- `/source_status` has no red DuckDB check;
- TradingAgent remains sim-only and both 50,000 CNY authorities are unchanged.

## 2026-07-13 emergency stop

At 19:08 CST, after an instance restart, P2 and sample-ops were no longer
running, but the authority had reached 19.10GB and the original root filesystem
was still about 96% used with only about 4.7GB available. The attached 500GB
`/dev/nvme1n1` had no filesystem, UUID, mount or fstab entry; it provided no
usable capacity. The old DuckDB cron remained installed, production still used
the old runtime, `/health` was degraded, and the old malformed mirror remained.
This is a hard preflight stop. Do not run this helper, the old DuckDB sync,
migration, backup or deploy. Do not format, mount, migrate, delete, change cron
or alter storage paths without explicit authorization and a rollback
assessment. The evidence inventory and prepared, unexecuted recovery plan are
recorded in
[resource_pressure_2026-07-13.md](resource_pressure_2026-07-13.md).

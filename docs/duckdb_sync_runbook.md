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

- canonical authority: `/opt/investment/SharedSignals/runtime/read_model/marketdata.sqlite`
- physical authority root: `/opt/investment-data/SharedSignals/runtime/read_model`
- data filesystem UUID: `3f7cbf99-b15e-4c54-94cc-a57e38412874`
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
The local candidate provides `deploy.sh --code-only` and
`rollback.sh --code-only`; both source `deploy/runtime_paths.sh`, require the
data/bind mounts and service guard, refuse tracked dirty state, and explicitly
skip schema migration, SQLite snapshot/restore and database replacement. This
entry is not production-available until its commit is merged, pushed and
deployed through a fresh bootstrap review; do not manually pull around it.
For the first production adoption only, fetch the remote without moving the
release checkout, create a clean detached worktree at the fetched
`origin/main`, and invoke that candidate's
`deploy.sh --code-only --bootstrap-from-candidate`. The candidate must remain a
separate clean tracked tree and equal the freshly fetched remote commit both at
preflight and immediately before the release checkout's ff-only move. The same
mount/service guard, exclusive locks, rollback tag, full tests and database
mutation exclusions still apply. Remove the detached bootstrap worktree only
after deployment and rollback evidence are archived; never substitute a manual
pull.

After an authorized deployment, one single-instance run must prove:

- total snapshot + sync + reconcile + cleanup under 480 seconds;
- 16/16 tables `status=ok` and event identity mismatch/invalid counts zero;
- three empty industry tables remain legal 0/0 when no promoted data exists;
- no snapshot temp/final residual;
- no collector row loss across the snapshot interval;
- `/source_status` has no red DuckDB check;
- TradingAgent remains sim-only and both 50,000 CNY authorities are unchanged.

## 2026-07-13 storage epoch follow-up

The authorized storage writer completed the ext4/fstab/bind migration and first
new-disk write at 20:07. Root/data free space is now adequate, but capacity alone
does not clear the DuckDB P0: the old mirror remains malformed, `/source_status`
is red, and DuckDB sync stays commented. The root underlay is stale after run
`e5a1fd619a6e` and is not a rollback authority. Preserve the mount guard and all
migration evidence described in
[resource_pressure_2026-07-13.md](resource_pressure_2026-07-13.md).

P2 and DuckDB sync plus the two TradingAgent A-share sample-ops schedules remain
inactive. Restore only the single DuckDB job after the code-only path contract,
snapshot implementation, rollback tag and single-instance preflight pass; do
not restore P2 or sample-ops as a side effect.

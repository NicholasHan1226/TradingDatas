# 2026-07-13 production resource-pressure gate

> Status: capacity stop mitigated; incident and release gates remain open. The
> storage migration below was completed by the authorized sole production
> writer. This repository update is local-only and authorizes no new production
> deployment, heavy-cron restore, database migration, sync or snapshot run.

## Storage epoch outcome (writer handoff)

- `/dev/nvme1n1` is ext4, UUID
  `3f7cbf99-b15e-4c54-94cc-a57e38412874`, mounted at
  `/opt/investment-data` through fstab.
- Physical paths are
  `/opt/investment-data/SharedSignals/runtime/read_model`,
  `/opt/investment-data/SharedSignals/backups` and
  `/opt/investment-data/runtime-backups`; three canonical bind mounts retain
  the old consumer paths. The API mount guard is
  `/etc/systemd/system/sharedsignals-api.service.d/20-finance-data-mount.conf`.
- At the handoff readback the root filesystem was 57% used with 41GB free and
  the data filesystem was 12% used with 433GB free. SS/MG/TA/relay were active;
  local 8082/8080/8787 returned HTTP 200. Liveness is not source/sample green.
- The migration evidence root is
  `/opt/investment-data/migration-evidence/storage-migration-20260713T192703+0800`;
  cron evidence is
  `/opt/investment/SharedSignals/logs/cron/storage-migration-20260713T192703+0800`;
  fstab backup is
  `/etc/fstab.before-finance-data-20260713T193012+0800`.
- At `20:02:53–20:03:06` the exclusive lock was released about 13 seconds too
  early and immediately reacquired. DB and underlay size/mtime did not change;
  no collector or write was observed. Production `summary.json` does not record
  this near-miss, so this section is the canonical incident supplement.
- First write run `e5a1fd619a6e` at 20:07 promoted the new-disk DB to authority.
  `read_model.root-predata-20260713T1956` is stale evidence/controlled-rollback
  material and must never be directly switched back after that write.
- Only two old-root duplicate backup/runtime-backup groups with double-SHA
  proof were released. Old read model files, databases, Journals, ledgers,
  history, migration evidence and empty staging directories remain preserved.
- Four heavy schedules remain inactive: P2 financial, DuckDB sync and two
  TradingAgent A-share sample-ops jobs. Do not restore them as a group. Current
  source status remains red (`market_pm_prices` stale plus `cb_issue` identity),
  and current A-share/CNFutures sample evidence remains non-green as recorded in
  `STATUS.md`.

## Fresh boundary

Read-only evidence at `2026-07-13T18:47:41+08:00`:

| Item | Evidence |
|---|---:|
| Root filesystem | 105,286,258,688 bytes total; 92,500,004,864 used; 8,273,600,512 available; 92% |
| SQLite authority | 15,796,649,984 bytes; `marketgraph:marketgraph`; mode 0644 |
| Production DuckDB | 7,541,895,168 bytes; `marketgraph:marketgraph`; mode 0644 |
| P2 wrapper | PID 174946, running since about 18:30 |
| P2 worker | PID 175096, about 10% CPU, RSS about 207MiB |
| P2 cumulative I/O | `write_bytes=34,906,140,672`; `read_bytes=754,782,208` |
| A-share sample ops | PID 162806, single-core CPU about 99%, RSS about 1.07GiB; separate TradingAgent process |

The authority grew from 8,492,072,960 bytes at 18:13 to 15,796,649,984 bytes
at 18:47 while P2 was active, then reached 15,977,668,608 bytes in a second
read-only stat at `18:48:03+08:00`. Memory, swap, inode use and recent OOM
evidence do not indicate the current bottleneck; root-disk capacity and IO
pressure do.

A single follow-up readback at `2026-07-13T18:51:27+08:00` showed further
deterioration: root usage reached 94% with 6,816,092,160 bytes available and the
SQLite authority reached 17,252,536,320 bytes. PIDs 174946/175093/175096 were
still active; no SQLite WAL or SHM file was present, and the DuckDB size remained
7,541,895,168 bytes. No repeated polling or production write followed.

The delegated read-only audit at `2026-07-13T18:57:30+08:00` showed a critical
98% root-filesystem level with only 2,209,431,552 bytes available. The SQLite
authority had reached 18,500,161,536 bytes, P2 worker PID 175096 was still
writing, and A-share sample-ops PID 162806 remained single-core saturated. This
supersedes the earlier wait-only threshold: no further production probe or
mutation is authorized until Nicholas explicitly approves a bounded stop or
disk expansion plan.

Read-only acceptance at `2026-07-13T19:08:00+08:00` through `19:09:00+08:00`
after an instance restart established a different but still blocked boundary:

- the instance had 4 vCPU, about 15GiB RAM, load 0.27 and healthy memory;
- P2 PID 175096 and A-share sample-ops PID 162806 were no longer running;
- the original root filesystem remained about 96% used with about 4.7GB free;
- SQLite was 19.10GB and DuckDB was 7.54GB, both still on the original root;
- the attached 500GB `/dev/nvme1n1` had no FSTYPE or UUID according to
  `lsblk`, `blkid` and read-only `wipefs -n`, no active mount in `findmnt`, and
  no fstab entry;
- the old DuckDB cron still existed at 19:17, production still ran the old code,
  `/health` was degraded, and the old malformed DuckDB evidence remained.

The restart stopped the observed hot processes but did not complete expansion,
repair the mirror or disable the scheduled old sync. No formatting, mounting,
migration, deletion, cron change or deployment is authorized.

## Exact large-file preservation inventory

The following list was collected with metadata-only `find/stat`. Full hashes of
large files were deliberately not recomputed under IO pressure.

| Size bytes | Owner/mode | Path | Preservation class |
|---:|---|---|---|
| about 19.10GB | marketgraph:marketgraph 0644 at the last exact owner/mode readback | `/opt/investment/SharedSignals/runtime/read_model/marketdata.sqlite` | Live authority at 19:08. Never delete, copy, restore or replace during this gate. |
| 7,541,895,168 | marketgraph:marketgraph 0644 | `/opt/investment/SharedSignals/data/marketdata.duckdb` | Live derived mirror. Preserve until replacement and rollback are proven. |
| 10,579,881,984 | marketgraph:marketgraph 0664 | `/opt/investment/SharedSignals/backups/duckdb/marketdata_pre_incremental_20260710_150600.duckdb` | Pre-incremental rollback evidence. No adjacent hash was found in the small-manifest scan; preserve pending lineage review. |
| 7,371,132,928 | root:root 0644 | `/opt/investment/SharedSignals/backups/marketdata_20260711_002519.sqlite` | SQLite deploy rollback snapshot. Preserve; a pre-deploy HEAD file exists, but no separate SHA file was found. |
| 7,371,137,024 | root:root 0644 | `/opt/investment/SharedSignals/backups/marketdata_20260711_004753.sqlite` | SQLite deploy rollback snapshot. Preserve; a pre-deploy HEAD file exists, but no separate SHA file was found. |
| 7,694,077,952 | root:root 0644 | `/opt/investment/SharedSignals/backups/marketdata_20260712_192313.sqlite` | Newest known SQLite rollback snapshot. Preserve first; adjacent SHA256 and readback evidence exist. |
| 6,459,502,592 | root:root 0644 | `/opt/investment/runtime-backups/finance-p0-20260713T105024+0800/marketdata.duckdb` | Finance P0 runtime rollback evidence. Preserve with its SHA/evidence manifests. |
| 4,337,426,432 | marketgraph:marketgraph 0644 | `/opt/investment/SharedSignals/runtime/read_model/backups/marketdata_corrupt_20260710T062151Z.sqlite` | Quarantined incident evidence, not an approved recovery source. Preserve until incident closure and explicit deletion approval. |

Associated small evidence that must stay with its large file includes:

- `marketdata_20260712_192313.sqlite.sha256`
- `marketdata_20260712_192313.sqlite.sha256.readback`
- all matching `pre_deploy_head_*` records
- `finance-p0-20260713T105024+0800/duckdb.sha256`
- `finance-p0-20260713T105024+0800/evidence.sha256`
- the matching pre/post-permission SHA manifests

No file in this inventory is approved for deletion. Older SQLite/DuckDB copies
are only candidates for a future, explicit retention decision after ownership,
lineage, readable rollback and required-retention evidence are verified.

## Current release stop

- keep P2, DuckDB sync and both TradingAgent A-share sample-ops schedules
  inactive; do not run a snapshot benchmark, schema migration or backup merely
  because capacity is now available;
- do not reformat/remount the data device, change fstab/binds, remove the mount
  guard, switch to the stale root underlay or delete retained evidence;
- keep TradingAgent sim-only and do not treat storage, service liveness or HTTP
  200 as source/sample green;
- code-only deploy remains local-only until commit/push and a fresh production
  preflight prove clean checkout, mounts, guard, locks and rollback tag.

The consistent-snapshot feature remains disabled until the local path contract
and code-only release entry are integrated, then a single authorized pilot
proves 16/16 reconcile, identity mismatch zero, no residual snapshot and no
collector loss. P2 requires a separate bounded-run pilot and must not be restored
as part of DuckDB recovery.

## Historical pre-migration recovery plan — superseded, do not execute

This section preserves the plan that preceded the completed storage epoch. It
must not be replayed against the new authority. Any future mutation requires a
fresh preflight against the 20:07 epoch and must preserve the new-disk DB.

1. **Re-identify the device.** Re-read cloud attachment identity, size,
   serial/model, `lsblk`, `blkid`, `wipefs -n`, `findmnt` and fstab. Do not rely
   on the transient name `/dev/nvme1n1` alone. Abort if identity differs, any
   signature appears, or the device is mounted/used by another system.
2. **Preserve small control evidence.** Export the production HEAD/status,
   systemd unit, exact crontab, fstab, mount table, database inode/size/mtime,
   existing SHA manifests and the large-file inventory. Do not create another
   large backup or recompute full large-file hashes on the constrained root.
3. **Establish a bounded writer freeze.** Verify the production wrapper version
   actually uses `read_model_maintenance.lock`, then hold its exclusive side so
   project cron jobs skip. Confirm P2, sample-ops, DuckDB sync and all SQLite
   writers are absent. Do not rewrite the whole crontab. Stop the read-only API
   only for the final path switch, not for the entire copy window.
4. **Prepare storage only after authorization.** Create the approved filesystem,
   mount it at a dedicated SharedSignals data mount by UUID, set restrictive
   ownership/modes, and add a fail-closed mount check. A missing mount must stop
   service/cron; it must never fall back to an empty directory on the root disk.
5. **Close the path-contract blocker before cutover.** `runtime_paths.py`, cron
   wrappers and systemd can consume `.env` path overrides, but the current
   `deploy.sh` and `rollback.sh` do not load that same file. Implement and test a
   single path contract plus mount guard locally before changing production.
   Directly editing `.env` now would make rollback target the wrong authority.
6. **Copy the SQLite authority without promotion.** With writers frozen, inspect
   WAL/SHM state and use the native SQLite backup API to write a temporary file
   directly on the new filesystem; do not raw-copy an active database. Flush it,
   validate owner/mode, read-only SQLite health, required tables, canonical
   counts and lineage, then atomically promote it on the new filesystem. Keep
   the root copy untouched. The malformed DuckDB is derived evidence: preserve
   it but do not promote it as the new active mirror or use it to reconstruct
   SQLite.
7. **Use a two-stage cutover.** First point only the API/read path at the new
   SQLite while writers remain frozen; verify mount identity, process
   environment, inode/device, internal API, freshness and lineage. Before the
   first new write, rollback is path-config restoration to the untouched root
   copy. After the first new write, the root copy is stale: rollback must keep
   the new storage authority and roll back code only, never silently switch to
   the old database.
8. **Resume in layers.** Enable one bounded collector only after the read-only
   phase passes, verify the write lands on the new device and remains
   append-safe, then restore schedules through the project-managed cron path.
   Rebuild DuckDB later from one consistent SQLite snapshot; require 16/16,
   identity mismatch zero, no residual snapshot and `/source_status` without
   DuckDB red before calling the mirror recovered.
9. **Retain the old root copy.** Do not delete the old SQLite, DuckDB, backups or
   incident evidence during cutover. Root-space reclamation is a separate,
   explicit retention decision after the new authority survives the approved
   observation window and rollback evidence is readable.
10. **Fix the cause after capacity is stable.** Profile P2 write amplification
    and unbounded rotation, enforce bounded/idempotent writes, and move heavy
    P2/sample projection work away from opening gates. Capacity expansion alone
    does not close the defect.

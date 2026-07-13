# 2026-07-13 production resource-pressure gate

> Status: active release blocker. This document records read-only evidence and
> preservation decisions. It authorizes no process termination, backup deletion,
> database write, migration, sync, snapshot benchmark or deployment.

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

## Exact large-file preservation inventory

The following list was collected with metadata-only `find/stat`. Full hashes of
large files were deliberately not recomputed under IO pressure.

| Size bytes | Owner/mode | Path | Preservation class |
|---:|---|---|---|
| 17,252,536,320 | marketgraph:marketgraph 0644 | `/opt/investment/SharedSignals/runtime/read_model/marketdata.sqlite` | Live authority at 18:51. Never delete, copy, restore or replace during this gate. |
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

## Release stop and next safe readback

Until the active P2 process has exited naturally:

- do not kill it or start a second writer;
- do not run SQLite/DuckDB integrity scans, snapshot benchmarks, mirror sync,
  migration, deploy or backup;
- do not modify cron or delete logs/backups;
- keep TradingAgent sim-only and do not treat service health as data health.

After P2 exits, the next step is one read-only readback of process exit state,
`df`, authority/WAL/SHM size and mtime, DuckDB size, and relevant cron/log tail.
Only then may an expansion or explicitly authorized bounded-retention plan be
designed. The consistent-snapshot feature remains disabled until projected
filesystem usage is at most 90% and all code-only deployment gates pass.

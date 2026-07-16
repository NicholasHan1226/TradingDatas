# SharedSignals SQLite Authority Recovery Runbook

> Scope: authoritative `marketdata.sqlite` used by the external data platform.
> This runbook is documentation only; it does not authorize production mutation.

## Authority rule

SQLite facts plus transaction-scoped ingest receipts are authority. DuckDB,
flat JSON, CSV/NDJSON/Parquet, dashboards, API cache and consumer copies are not
authoritative recovery sources.

DuckDB may be inspected as forensic evidence, but it must never automatically
overwrite or reconstruct the SQLite authority. If no verified SQLite backup is
available, recovery is a separately approved rebuild from upstream providers
with new receipts, not a mirror promotion.

## Stop conditions

Fail closed and request operator approval when any of these is true:

- canonical DB path, owner, mode, mount or parent identity is unknown;
- collector/API/maintenance processes cannot be quiesced cooperatively;
- current DB, WAL/SHM, locks or backup evidence cannot be sealed read-only;
- available backup lacks SHA256, SQLite integrity proof or receipt/fact checks;
- restore would require schema migration, destructive cleanup or provider write;
- free space cannot hold current evidence, candidate restore and rollback copy;
- production checkout or service ownership is dirty/unknown.

Do not create an empty database at the canonical path and do not let reader/API
fall back to live provider or old files.

## Evidence capture

Before any restore:

1. record UTC/local time, host, operator, service/cron state and incident reason;
2. capture canonical path resolution, mount, owner/mode, inode, size and mtime;
3. copy current DB, WAL, SHM and lock identities to a new immutable evidence dir;
4. hash every captured file and fsync files/directories;
5. record current Git/prod/runtime versions and API fail-closed response;
6. do not delete or rename historical evidence.

## Approved recovery source order

1. latest verified SQLite native-backup snapshot whose source authority, time,
   SHA256, schema version, `quick_check`/`integrity_check`, and receipt/fact
   consistency are recorded;
2. an older verified SQLite snapshot plus bounded upstream replay into a separate
   candidate DB, with new truthful receipts for every replay attempt;
3. full rebuild from providers into a new candidate DB under a separately
   approved migration/rebuild plan.

Never use an unverified file merely because it opens or has a recent mtime.

## Candidate validation

Validation happens at a non-canonical temporary path under exclusive maintenance:

```text
open candidate read/write only for recovery validation
→ PRAGMA quick_check / integrity_check as required
→ verify required schema and indexes
→ validate registry bindings
→ validate receipt envelope/schema/attempt ordering
→ prove success receipts match committed fact transactions
→ prove failed/empty receipts remain distinguishable
→ run representative read-only queries and metadata projection
→ seal candidate SHA256/inode/size/mtime
```

A candidate with missing/unknown receipt schema, inconsistent counts, fabricated
success, unresolved tenant data exposure or unbounded replay is rejected.

## Atomic replacement

Production replacement requires explicit Nicholas/operator authorization and a
fresh safe-release preflight.

1. acquire the documented exclusive maintenance lock;
2. revalidate canonical parent/lock/current identities immediately before change;
3. preserve the current canonical DB as rollback evidence;
4. place the validated candidate on the same filesystem with restrictive owner/mode;
5. fsync candidate, atomically replace canonical DB, then fsync parent directory;
6. if any post-replace fsync/binding/readback fails, restore the previous verified
   canonical file and prove its bytes/identity before releasing the lock;
7. never delete WAL/SHM blindly—follow SQLite close/checkpoint state and evidence.

## Post-recovery readback

While still controlled, separately verify:

- canonical file hash/identity and SQLite integrity;
- registry + receipt runtime projection;
- `success/empty/unobserved/paused/failed/stale` semantics;
- representative domestic datasets through the read-only API;
- no provider/file fallback and no new empty DB;
- service/runtime versions and resource pressure;
- next real collector attempt writes facts and receipts atomically.

API HTTP 200 alone is insufficient. Keep the platform degraded/paused until the
required datasets, metadata lineage, and next collection receipt are proven.

## Rollback

Rollback uses only the sealed pre-recovery SQLite authority copy and the same
atomic protocol. A rollback never rewinds Git, deletes newer evidence, promotes
DuckDB, changes schema, installs cron or triggers provider collection implicitly.

Archive the recovery manifest, hashes, commands, JUnit/probe results, final state
and unresolved gaps. Update `STATUS.md` only with current verified facts; move
incident chronology to `docs/status_history_2026-07.md`.

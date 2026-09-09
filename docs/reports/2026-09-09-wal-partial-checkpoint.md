# WAL partial-checkpoint timestamp false rejection — 2026-09-09

## Scope and evidence

This dated incident report records a local synthetic reproduction and the minimal
reader fix. The current operations entry remains [OPERATIONS.md](../OPERATIONS.md);
production recovery and release acceptance are recorded separately in STATUS.md.
No production database, payload, token, or collection claim is included here.

The former sidecar gate rejected `mx_frame > n_backfill` when the main database
mtime exceeded WAL mtime. Standard SQLite can create exactly this valid state:
create two tables in WAL mode, disable automatic checkpoints, write table A,
pin a read transaction, write table B, then execute a PASSIVE checkpoint. Separate
pages allow the older frame to reach the main database while the newer frame
remains in WAL. The synthetic run returned `(0, 2, 1)`; SQLite integrity checking
returned `ok`, the old reader retained its old view, and a new read-only connection
saw the new row. The original gate rejected the same files. No timestamp or file
bytes were changed to obtain the reproduction.

SQLite documents that checkpoints stop at frames needed by an active reader and
record progress in the WAL index: [WAL concurrency](https://www.sqlite.org/wal.html#concurrency)
and [wal_checkpoint](https://www.sqlite.org/pragma.html#pragma_wal_checkpoint).
The production symptom does not by itself prove that every production file is
healthy; recovery must independently verify the retained database and receipts.

## Frozen change and threat boundary

Remove only the mtime-based stale-sidecar inference. Retain regular-file and
parent identity binding, complete sidecar-set checks, main/WAL page-size and mode
checks, matching SHM headers, WAL/SHM salts, committed-frame length, backfill
bounds, schema checks, the shared authority lock, and double-connection epoch
verification. No schema migration, cross-request cache, provider call, or alternate
data authority is introduced. Timestamps are not a WAL authenticity proof.

The existing tests cover clean TRUNCATE checkpoint acceptance and rejection of an
empty WAL with a nonempty SHM epoch. A repository test search found no dedicated
mtime-stale-sidecar test. The new regression exercises a natural partial checkpoint
and additionally confirms a modified WAL salt still fails closed. This does not
claim a comprehensive new malicious database threat model; existing structural,
receipt, path-binding, and schema tests remain mandatory.

## Verification and stop line

Targeted command: `uv run --python 3.12 --with-requirements requirements.txt python -m pytest -q tests/test_receipt_projection.py`.
Local verification: **240 passed in 370.87 seconds**. The natural partial-checkpoint
regression plus the existing empty-WAL acceptance and malformed-SHM rejection
checks also passed independently (3 passed). After removing one existing unused
local assignment while retaining its receipt-insertion call, that affected cache
test and the new regression passed again (2 passed). Ruff passed for both touched
Python files, and `git diff --check` passed. Mainline,
release, production snapshot, authenticated API latency, scheduler planning, and
new receipt checks are separate integration acceptance steps owned by the main
change. Rollback is the prior immutable release; do not remove WAL/SHM to mask a
reader failure.

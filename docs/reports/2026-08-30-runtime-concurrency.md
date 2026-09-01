# Crypto catalog concurrency follow-up — 2026-08-30

## Observed problem

PR #402 merged as `4bb6fe82aa904b40ada8f263b877b43e747b58e9`; exact-main CI
33316157610 passed all four fast shards. Crypto deployed that immutable release
and WAL at 22:36 CST. All 240 catalog rows and six query data/selected metadata
summaries matched during paused-writer readback. Seven original timers resumed.
Actual TradingAgent credentials read the fixed catalog/query endpoints. Later
spot, book-ticker and funding receipts advanced for all 40 frozen symbols.

This did not fix concurrent catalog latency. Single authenticated catalog was
7.111 seconds; observations at 22:41 and 22:46 timed out at 15 seconds. A bounded
two-reader diagnostic timed out both requests at 35 seconds. That diagnostic
timeout is not a relaxed acceptance threshold. Existing TradingAgent observation
clients were visible on this API; no TradingAgent timer or workflow was changed.

A current-process-equivalent cold/hot diagnostic had 20,610/20,611 validation
cache entries, with only one new full validation on the hot pass. Ordinary
receipt arrival did not clear that cache. The hot profiled path still made 200
source-specific sibling scans and about 484,000 Python candidate callbacks.
Concurrent SQLite-to-Python callbacks are the candidate contention mechanism;
the gate's performance must still be verified through the actual HTTP runtime.

## Frozen implementation boundary

One process-local reentrant lock covers only the UTF-8 candidate UDF lifetime:
register callback, execute/fetch candidate SQL, unregister callback, release.
Other requests can still authenticate, open their own verified snapshots and
perform ordinary SQLite reads. The gate is not an HTTP-wide lock and does not
change authentication, concurrency grants, caches, SQL predicates, scan budgets,
raw malformed-candidate retention, exact execution parsing or non-UTF-8 fallback.
No provider, dataset, schema, timer, credential or route is added.

The gate is acquired after the caller has opened its SQLite authority snapshot.
The callback only matches bytes and acquires no authority or validation-cache
lock. Raw classification happens after the gate exits. Registration, SQL and
cleanup failures must release the gate; recursive same-thread use must not
deadlock. Lock fairness and unbounded-reader latency are not promised.

## Evidence and release acceptance

An ephemeral gate in an independent Crypto-UID read-only process returned the
same complete 240-row response on one verified snapshot. Cold baseline was
9.615 seconds, gated hot pass 6.110 seconds; two warm gated reads took
12.973 and 14.124 seconds. These are diagnostic timings, not HTTP/auth evidence.

Required checks: real two-connection thread exclusion, nested lookup, exception
cleanup and existing receipt malformed-row/budget tests; independent candidate
review; exact-head and merged-main CI. Production must separately verify the
immutable release and actual API PID/cwd, paused-writer catalog and six-query
equivalence, then **two simultaneous authenticated catalog reads each below
15 seconds**, followed by natural collection and consumer readback.

The next maintenance window preserves WAL throughout. Pause only the original
seven Crypto timers, drain active collectors without killing them, hold the
two original collector locks, verify WAL via read-only snapshot/header, switch
only the release/API, then restore timer states. Rollback is `4bb6fe8` with WAL,
not `15f463e`; this window must contain no journal-mode setter or checkpoint.
If postcommit timer restoration fails, retain the verified target and pause
timers instead of rolling underneath a newly started writer.

Short-SLA event refresh remains default zero pending current QuickSync daily
quota evidence. This change does not enable that option or alter A-share core.
Long-term latency, all cadences, historical completeness and global stable
health remain separate claims. Operational evidence is retained outside Git
under `work/runtime-reliability-20260830/`; final runtime outcomes belong in the
PR readback record and the owner-facing execution report.

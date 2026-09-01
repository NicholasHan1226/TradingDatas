# Catalog process isolation candidate

## Problem and evidence

PR #404 / main `0f5f0daf01ebde3d978e302d4f605b940779beb3` passed code CI but failed
production acceptance: two authenticated catalog requests both exceeded 15 seconds.
The maintenance rolled back to `4bb6fe82aa904b40ada8f263b877b43e747b58e9`, preserved WAL,
verified the same 240 catalog entries and six query samples, and restored all seven
original timers. The rejected target is not a successful production deployment.

At 00:18 CST, exact physical-release imports in a short read-only process measured
catalog cold/warm at 9.461/5.920 seconds and two threads at 11.576/11.290 seconds.
A 50-second passive API sample found an existing worker in all 51 samples. Adding
six real `QueryService.execute` calls in the same diagnostic process reproduced
catalog latency of 24.752/25.314 seconds, with complete fresh snapshot validation.

A separate bounded experiment retained two catalog child processes while the parent
executed queries: cold catalogs 12.217/12.896 seconds, warm 6.612/7.490 seconds,
and ten queries 1.279–3.233 seconds. Each catalog had 240 rows; query samples were
ready, quality valid and lineage complete. Children were reaped. These timings
exclude interpreter/import/bootstrap time and are **not authenticated HTTP proof**.
They justify a candidate, not production activation or continuous health.

## Frozen candidate

- `TRADINGDATAS_CATALOG_WORKERS` defaults to `0`; only exact `0`, `1`, `2` are valid.
- Persistent `spawn` workers remain in the original API unit/UID. No new service,
  port, credential, provider call, database write or collector change.
- The parent retains authentication, scope/category checks and all user limits.
  Only bounded parsed request primitives cross the worker boundary, never bearer
  tokens, account dictionaries or signer key bytes. The JSON job envelope is limited
  to 1 MiB and responses to the existing registry response-byte budget.
- Each worker performs an entire `CatalogService.list_datasets` with a new verified
  SQLite snapshot. Registry, code, canonical DB path and signer identity must match.
- At most one running task per worker and no waiting backlog. Overload or broken
  worker is existing 503; no automatic replay or inline fallback. A disconnected
  client does not release capacity while its task is still computing.
- All workers complete bounded identity bootstrap before the HTTP listener opens.
  Bootstrap does not load data facts. Normal shutdown waits for real task completion;
  only newly owned, pre-listener bootstrap children may be terminated on init failure.

## Verification and release boundary

The API integration first reproduced three failures on unchanged code, then passed
authentication-before-execution, capacity error isolation and client-timeout tenant
claim tests. Six API integration/lifecycle cases passed in 8.30 seconds; the full
HTTP module passed all 177 tests in 300.14 seconds. The executor module passed
55 tests in 56.01 seconds, including real spawn/bootstrap, cross-process cursor,
fresh SQLite authority, worker death/reaping and admission retained until completion.
Both new module files are Ruff-clean; existing API/test lint findings are unchanged.
Independent review and CI remain required. No deployment or production performance
success is claimed by this document.

Release requires exact candidate/main CI, immutable staging, cold and warm mixed
load plus two authenticated catalog requests below the unchanged 15-second gate,
and query/data/receipt readback. Record original worker configuration with the
rollback release; restore both if acceptance fails. Preserve original timers,
locks, WAL, all facts/receipts and external market-list bytes. A-share pre-window
clock correction and the unenabled holder refresh option remain separate changes.

Local evidence for this run is in the task's `work/runtime-reliability-20260830/`
directory; full payloads, credentials, databases and receipt artifacts are not
committed. Re-run commands and operator configuration are in `docs/OPERATIONS.md`.

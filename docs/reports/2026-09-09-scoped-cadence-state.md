# Scoped cadence state — frozen contract, 2026-09-09

## Problem and scope

A cadence selector currently reaches planning only after all registry receipt
histories and active dataset facts have been loaded. Local query spying against
the current registry observed 192 history selections, 154 fact queries, and seven
payload-hydrated dependencies. These synthetic counts are not production timing.

This independent change passes the existing selection into the read-only state
loader. `selected_dataset_ids=None` retains the prior complete-state behavior.
An explicit selection reads active selected datasets, their selected calendar
inputs, and recursively required active resumable dataset-field fanout sources.
The complete registry remains the authority for per-dataset receipt validation.
Unknown selection/dependency identities fail closed. No planning order, skipped
result, attempt identity, cadence, clock, executable scope, or budget changes.

## Threat boundary and acceptance

Keep verified SQLite snapshot/schema/path checks and the existing receipt helper;
do not invent a filtered registry, suppress selected/dependency invalid receipts,
or introduce provider calls, writes, migration, or cross-request cache. Existing
unattributed-source health semantics remain unchanged. Missing dependency facts
must produce the same planner result as a full-state load; invalid dependency
facts/receipts must retain the existing refusal/skip behavior.

Acceptance: trace unrelated receipt/fact SQL absence; compare complete planned
runs and skips from scoped versus full loads of the same synthetic database;
cover calendar and resumable fanout dependencies, missing/invalid dependencies,
None compatibility, and execute=False without provider calls or data writes.
Run the provider-native schedule suite, touched Python lint, and diff checks.
Production latency, receipt progress, deployment, and API readback remain separate.
The operations entry remains [OPERATIONS.md](../OPERATIONS.md); this is a dated
candidate report, not a second current runtime authority.

## Local implementation and verification

The scheduler passes its existing selection and calendars for active selected
cadences. The loader walks resumable dataset-field dependencies with a visited
set and reuses `validated_receipt_history_for_dataset` with the full registry;
`None` still invokes the former all-dataset helper. Facts and hydrated fanout
inputs use the same resulting dependency set. Planning itself is unchanged.

The schedule suite completed **175 passed in 236.79 seconds**. During that run,
fanout source coverage was expanded from missing-only to valid/missing/invalid;
the final seven scoped cases plus two existing tests touched by lint cleanup
then completed **9 passed in 17.32 seconds** (177 tests currently collected).
All three touched Python files pass Ruff and `git diff --check` passes.
The lint cleanup removes a constant-true dead assertion referencing an undefined
name and an unused local binding, preserving the latter's actual helper call.

The tests compare complete plan/skip values on the same database, retain invalid
calendar/fanout authority results, observe only selected/dependency receipt and
fact SQL, verify the complete registry reaches receipt validation, reject unknown
identities, and prove dry-run does not call the executor/provider or change DB
bytes. The minute selector reads four registered histories: rt_min, rt_min_daily,
security_master, and trade_calendar. These are local correctness/query-scope
results; no production timing improvement or new receipt success is claimed.

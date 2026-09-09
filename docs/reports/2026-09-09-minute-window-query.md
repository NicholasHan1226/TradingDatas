# Minute-window query and receipt validation fingerprint

Base: 684c94802c78ade2317f147e9f1e43e33dc1427a. Scope is query/API read semantics;
no registry/schema/index/activation/provider/service changes. Existing old
worktrees remain archived and untouched.

## Proven mismatch

rt_min_daily major 3 declares append_only identity [ts_code,time],
windowed_unique_primary_key with date_field=time and start_time/end_time, local
second precision, max_span_days=1; snapshot_field is null. Its ingestion validates
unique identities, requested fanout membership and start <= event time <= end.
Several minute timestamps may legitimately occur in one response. The maximum
validated timestamp becomes data_through, not a requirement that every row equals
that maximum. rt_min instead declares unique_primary_key_snapshot/time and
requires a homogeneous snapshot; its current stricter rules remain unchanged.

The baseline reader selects the snapshot path for all session_minute datasets
with null partition/as_of/range, rejecting rt_min_daily both at proof formatting
and explicit time=eq detection. Merely removing those guards would be unsafe.

## Owner-frozen read contract

Recognize two structural minute families by the existing active provider binding:
1. Existing homogeneous snapshot policy: preserve exact event==data_through and
   current slot receipt selection unchanged.
2. Finite windowed unique-key policy: require declared time/date_field, required
   start/end window keys and supported datetime format, nonempty identity and
   matching registered provider. Reuse normalize_request_window and
   decode_request_window_value, normalize timezone before comparisons.

For family 2 proof rows require window_start <= event <= receipt.data_through
<= window_end and receipt.data_through <= finished_at <= read clock.
Receipt data_through/finished_at themselves retain existing validated authority.
Do not advertise homogeneous snapshot or full-market/full-session completeness.
Keep per-page single execution/window/config/data_through, row own receipt,
failed/incomplete cohort exclusion, request/cursor budgets and invalid-evidence
fail-closed behavior.

For exact time=eq in family 2, find validated success cohorts in the same active
provider/config whose declared finite request window contains that slot and whose
validated data_through >= slot. Filter actual facts by time=eq and permitted own
receipt IDs. Do not borrow latest receipt authority, equate slot with batch max,
or synthesize a result when no eligible receipt exists. Past schema 1/2 and
foreign/old active config authority remain excluded as before. Multiple overlap
executions remain valid row candidates, but opt-in pages spanning collection
sequences retain the existing rejection.

Compatibility: no payload/schema/registry migration. Some previously always-503
rt_min_daily exact-time/proof requests become supported under their actual
windowed contract. Existing default no-proof output and rt_min snapshot semantics
must stay unchanged. Historical receipts with missing/invalid windows remain
unavailable; no rebind or data rewrite. This is read capability, not new collection
completeness or freshness evidence.

## Implementation and validation

Two separately reviewable file groups implement the frozen contract:

- Semantic: `query_service.py`, `tests/test_minute_window_query.py`, and the
  corresponding `docs/API.md` contract. No registry/schema migration.
- Performance: `storage/receipt_projection.py` and
  `tests/test_projection_binding_fingerprints.py`. Each local validation pass
  within a projection computes complete binding-content fingerprints once.
  Object identity is only a temporary lookup key; the memo key still contains
  full raw receipt content and complete binding content digests. A new pass
  recomputes binding content. Existing scan scope, cache lifecycle, validation,
  clock checks and authority remain unchanged.

Semantic tests cover multi-timestamp proof parity, exact earlier-than-through
slots, pagination, invalid/out-of-window/future/after-through row time, invalid
windows, active config mismatch, no eligible slot and mixed execution rejection.
The existing native-query suite retains snapshot, config/provider, cursor and
optional-proof checks. Before the performance change, these passed 92 tests.
Targeted receipt memo/binding tests passed 26 tests (216 deselected), including
new equal-instance, changed-binding, changed-raw and per-pass fingerprint tests.
Ruff checks passed for all four implementation/test files. Combined semantic/native-query/fingerprint validation passed 94 tests in
79.52 seconds after both code groups. Independent review found no P0/P1 within
the frozen scope and independently passed all 16 new tests. `git diff --check`
passed. Production latency and live data acceptance remain separate below.

## Observed production profile and remaining acceptance

One owner-authorized no-payload cProfile ran as the actual tradingdatas user,
against physical release 684c94802c78ade2317f147e9f1e43e33dc1427a and the normal
verified database, with bytecode disabled. Trusted manifest verification passed
before and after; no provider calls, database writes or service changes occurred.
Safe JSON: task artifact `TradingDatas-execution/minute-profile-684-safe.json`.
The request was default rt_min schema2, limit5, proof=false, with explicit valid
read access. Fresh-process profiled wall time was 26.303 seconds, 5 rows and a
next page. cProfile adds overhead and no cache eviction was performed.

- Dataset runtime projection: 17.477 seconds cumulative.
- Receipt memo validation: 28,485 calls, 15.363 seconds cumulative.
- Dataclass repr wrapper: 227,841 calls, 6.138 seconds cumulative.
- SQLite execute: 41 calls, 8.348 seconds self time. No SQL-level attribution was
  captured, so this does not identify a specific index or query defect.

The measured large-binding repr path motivated the bounded fingerprint change.
Synthetic tests prove repeated binding rendering is removed and invalidation is
preserved; they do not prove production latency improvement. Candidate live
latency and real rt_min_daily exact-slot/proof acceptance remain owner-run release
checks. No completeness/freshness promotion follows from this patch. Rollback is
reverting the two code groups; no storage migration or data rewrite is required.

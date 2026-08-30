# Catalog receipt execution boundary repair

Baseline: `5526cff6a6cd636255e08b36eabd44e77a4b71c1`.
Candidate branch: `codex/catalog-receipt-cohort-boundary-20260830`.
Status: local implementation and failure regressions; no production mutation by
this task. Provider observations below came from a read-only verified snapshot
under the existing service user, not a new provider call.

## Diagnosed defect

At 2026-08-30 08:28 UTC, the production global-news dataset had 6,526 individually
valid receipts, no complete-history execution failures and no future timestamps.
Its dataset-scoped projection was success at receipt
`receipt:21f0bd78d079e570d33f43c26b8cae659b48747f475e7f345588dd414ade563b`,
finished 08:24:54.630972Z, with data_through 08:17:19.829773Z.

In the same snapshot, the catalog's recent-100 selection failed with
`receipt_execution_inconsistent`, represented by
`receipt:cdf6dc1f7d0953b1e2a2073068e184f70d569d1468d3ddc0beb11128681f2ff2`.
Execution `9fa7e11a-907b-406d-882a-0a8342c87e93:schedule-plan:000000000013`
has three valid historical provider-error calls with identical request identity:

| Physical call / retry | Recent 100 | Receipt |
| --- | --- | --- |
| 0 / 0 | omitted | receipt:70601d107c57afe69fdec85ba8d8a14cd9c255172da44898d20d1486f9355654 |
| 1 / 1 | selected | receipt:3ec7608c75db2d09543c6dab99e18688a2637cc876f15b2d6ea9e54e41cb5abd |
| 2 / 2 | selected | receipt:cdf6dc1f7d0953b1e2a2073068e184f70d569d1468d3ddc0beb11128681f2ff2 |

The existing validator correctly rejects retries 1/1 and 2/2 without retry zero.
The selection, not that check, was wrong. Read-only limits 101 through 105 all
recovered the actual latest success without changing data. This was neither
real historical loss nor changed retry identity nor the earlier future-filter
ordering bug. Another timer run can move the cutoff and temporarily hide the
symptom, but cannot guarantee that the next cutoff will not split another group.

The separate domestic-news failure was real: 1,725 valid receipts and a latest
three-call execution with transport_error on all retries, zero rows and no
watermark. It is outside this patch. Later real provider success may naturally
restore that dataset; no success is manufactured here.

## Frozen general repair

Keep the 100-row per-source seed selection. For every full source window,
validate individual seed rows and derive **all** recognizable valid execution
IDs, at most 100 per source. Reuse the existing source-constrained execution
sibling lookup in the same SQLite snapshot. Do not infer which execution is
complete from started_at/finished_at: executions can interleave, outside siblings
can have inconsistent start contexts, and text timestamps with different UTC
offsets do not sort by actual time. The initial proposed timestamp cutoff was
rejected during independent design review for these reasons before release.

All original seeds remain, including invalid rows. Add sibling rows without
discarding malformed material; deduplicate exact returned row tuples only after
accounting for read cost. The existing 400,000 global row budget covers seed
reads and every extra raw row, including repeated seeds and rows later removed
by exact execution selection. Each lookup uses remaining-budget LIMIT+1 and
fails closed before returning a partial result on exhaustion. No full-history
fallback, new table/index, higher budget or new authority exists.

Run the existing attempt/execution/retry/variant validation over the expanded
union before future-time filtering. Explicitly completed physical executions
must start at call zero, so truly missing earlier logical calls cannot pass as
a merely truncated suffix. The ordinary validator's default suffix behavior
and row-query callers are unchanged. Catalog and interface/runtime projections
receive the same expanded evidence and complete-execution IDs.

This replaces the catalog-window assumption in the historical
`2026-08-25-catalog-projection-performance.md`; it does not rewrite that report.
A valid execution larger than 100 calls is completed and accepted within budget,
not mistaken for missing authority. The lookup may inspect a source's history
to match existing execution IDs; it is not claimed to use an execution index.
The caller's SQLite work budget remains intact. Real candidate readback must
verify catalog latency against the existing HTTP budget before release.

Scope: `storage/receipt_projection.py`, `tests/test_receipt_projection.py`, and
this report. The parent separately owns STATUS and release records. No registry,
schema, ingest, API route, database contents, activation, timer or quota changes.

## Verification and frozen files

The initial real-SQLite regression failed with catalog=failed while the full
dataset projection was success; two true missing-retry controls remained failed.
After implementation, 14 new tests passed in 11.23 seconds. Independent review
reran the same 14 successfully in 11.25 seconds, with no new P0/P1 identified.
Coverage includes:

- exact recent-100 retry truncation and dataset/interface agreement;
- actual missing first retry and internal gaps;
- invalid original seeds and invalid fetched siblings;
- multiple interleaved executions and inconsistent outside-sibling contexts;
- differing timestamp offsets and future checks after complete validation;
- registered variants and a valid 128-physical-call execution;
- zero-prefix enforcement after full lookup;
- cross-source shared raw-read accounting: 402 raw reads versus a 202-row union,
  with a 401-row budget rejected and 402 accepted.

Reproduce the focused checks with:

```sh
uv run --python 3.12 --with-requirements requirements.txt pytest -q tests/test_receipt_projection.py -k catalog_complet
```

Before the performance follow-up below, the adjacent provider-native query suite
passed 64 tests in 53.20 seconds with two workers. The complete receipt-projection
suite passed 149 tests in 150.58 seconds; independent review passed the same 149
in 149.98 seconds. Those results apply to the earlier correctness candidate,
not automatically to the performance follow-up.
Changed storage-file Ruff and `git diff --check` passed. Checking the complete
test file also reports the pre-existing unused `first_receipt` local at baseline
line 904 (F841), confirmed in HEAD; this unrelated code was not changed.

## Performance follow-up before release

The candidate's real-database correctness preflight agreed with complete news
history in the same snapshot. However, the actual API-style validation cache
still measured 18.629 seconds cold and 15.648 seconds warm against the consumer's
15-second timeout. The 55 sibling lookups consumed approximately 14.8–15.1
seconds: the original predicate repeated up to 200 `instr(notes, fragment)`
searches for each source row. This is a release-blocking performance defect;
the earlier candidate CI does not cover the follow-up head.

For UTF-8 databases, replace only that literal prefilter with a connection-local
SQLite function using a compiled union of escaped literal byte strings. SQL
passes `CAST(notes AS BLOB)` so malformed UTF-8 TEXT, invalid BLOB bytes and NUL
characters do not trigger Python text decoding before selection. Every pattern
is escaped; no caller-supplied regex syntax is evaluated. Non-UTF-8 databases
retain the original SQL predicate because casting TEXT uses the database's
encoding. No JSON extraction or JSON-valid filter is used: duplicate keys,
nested keys and malformed siblings must continue to reach the exact validator.

Each lookup registers a private UUID-named callback on its existing connection,
closes its cursor and unregisters the callback in `finally`, including SQLite
interrupts. No callback or pattern is cached across connections. Original source
constraints, fragments, LIMIT+1, raw-row budget accounting and all downstream
classifiers and exact parsers remain unchanged. The source history still needs
to be scanned; this change reduces repeated string searches without claiming
an execution index or an unbounded scan exemption.

The follow-up focused run passed 20 tests in 12.14 seconds: the 14 existing
boundary regressions plus six new cases. Three cases compare raw candidate IDs
against the original SQL for 48 synthetic values under UTF-8, UTF-16le and
UTF-16be. They include duplicate/nested/malformed material, Unicode,
quotes/backslashes, near prefixes, BLOB/NUL/invalid UTF-8 TEXT, null and numbers.
Three cases prove callback removal after success, budget failure and SQLite
interruption. These are synthetic database checks, not provider observations.
The full 155-test projection suite plus 64 adjacent query tests are running at
this follow-up freeze. Real snapshot raw-candidate equivalence, cold/warm latency,
fresh independent review and new exact-head CI remain required release checks.

Follow-up frozen SHA256:

- `storage/receipt_projection.py`:
  `e78637530fb7189534a60b5ad24d3b10396fccfbef1a71166e7a63238f5b9374`
- `tests/test_receipt_projection.py`:
  `819ad4e88590d9795bbbd072012db27df4e6e7bb2126132255ef4846d8f3a185`

No commit, push, provider request or production write was performed by this
task. Exact-head CI, independent final review, bounded real-database candidate
preflight, safe release and authenticated readback remain parent-owned gates.

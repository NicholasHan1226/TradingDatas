# SW2021 Task 4 P1/P2 Fix Report

Date: 2026-07-11

Scope: `collectors/tushare/sw2021_reference.py` and its focused tests only. No generic API mapping, production token, database, schedule, deployment, or push was used.

## Result

- `index_classify` now uses explicit `limit=50` / `offset` pagination, stops only after a short or empty page, and has a hard 100-page bound.
- Provider exceptions, non-list pages, oversized pages, repeated pages, and a full 100-page run all fail closed with a `CandidateCollectionError`; exact-full pages require a following page before collection can terminate.
- Candidate validation still requires exactly 31 L1 partitions and now also requires all three taxonomy levels with valid parent closure.
- The normalized taxonomy is now checked before the first membership request: anything other than exactly 31 valid unique L1 nodes, duplicate taxonomy identities, missing levels, or a broken L1/L2/L3 parent chain raises `invalid_taxonomy_candidate` with zero membership calls.
- Membership validation resolves the row's L1/L2/L3 taxonomy nodes and requires `L2.parent_industry_code == L1.industry_code` and `L3.parent_industry_code == L2.industry_code`.
- Same-key/same-symbol/same-assignment rows are deterministically deduplicated across the complete candidate, including rows smuggled across provider partitions; accepted candidates therefore have one unique membership key per row.
- `partition_counts` now preserves the raw count returned by every actual L1 provider request, including `0` and the existing `-1` fetch-failure sentinel; it is never reconstructed from declared `l1_code` values or deduplicated rows.
- Candidates separately retain per-request post-deduplication counts, per-declared-L1 counts, and immutable `(requested_l1, declared_l1, symbol)` scope-mismatch evidence. Validation reconciles both count maps and their totals against the final candidate rows.
- Every provider response row must declare the same `l1_code` as its requested partition. A row returned by the `L1-01` request while declaring `L1-02` is rejected as `partition_scope_mismatch`; it cannot make an empty `L1-02` request appear complete.
- Every requested L1 partition must have a raw source count greater than zero and below 2,000. The new empty-`L1-02` counterexample preserves the zero and is rejected as `empty_partition`, including when another response smuggles an `L1-02` row.
- Different assignments for the same symbol remain present and reject as `conflicting_current_assignment`; `validate_candidate` independently rejects every repeated key as `duplicate_membership_key` for defense in depth.
- Every taxonomy row is reconstructed from canonical `raw_json` and checked against candidate `snapshot_id` / `started_at`, `SW` / `SW2021`, provider, normalized content, and `taxonomy_node_key`.
- Every membership row is reconstructed from canonical `raw_json` and checked against candidate `snapshot_id` / `started_at`, `Ashare`, provider, normalized content, and the SW2021-derived `membership_key`.
- `API_TO_TABLE_MAP["index_classify"]` and `API_TO_TABLE_MAP["index_member_all"]` remain unchanged and are covered by the focused suite.

## TDD Evidence

RED:

```text
2 failed, 47 passed in 0.17s

Failures proved that the candidate had no independent deduplicated/declared
partition counts and that an L1-02 row returned by the L1-01 request caused
the raw L1-01 source count to be reconstructed incorrectly as 4 instead of 5.
```

GREEN:

```text
./.venv/bin/python3 -m pytest tests/test_sw2021_reference.py tests/test_capability_coverage.py -q
74 passed in 0.34s

./.venv/bin/python3 -m pytest -q
459 passed, 17 warnings in 17.51s
```

The 17 warnings are the pre-existing test-environment warning that `SHAREDSIGNALS_TOKEN_SALT` is empty; no real token was introduced for this task.

## Residual Boundary

This task constructs and validates an in-memory candidate only. It does not write or promote a snapshot, install a schedule, use provider credentials, modify production state, or push a branch.

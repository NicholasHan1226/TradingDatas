# SW2021 Task 4 P1/P2 Fix Report

Date: 2026-07-11

Scope: `collectors/tushare/sw2021_reference.py` and its focused tests only. No generic API mapping, production token, database, schedule, deployment, or push was used.

## Result

- `index_classify` now uses explicit `limit=50` / `offset` pagination, stops only after a short or empty page, and has a hard 100-page bound.
- Provider exceptions, non-list pages, oversized pages, repeated pages, and a full 100-page run all fail closed with a `CandidateCollectionError`; exact-full pages require a following page before collection can terminate.
- Candidate validation still requires exactly 31 L1 partitions and now also requires all three taxonomy levels with valid parent closure.
- Membership validation resolves the row's L1/L2/L3 taxonomy nodes and requires `L2.parent_industry_code == L1.industry_code` and `L3.parent_industry_code == L2.industry_code`.
- Same-symbol/same-assignment rows are deterministically deduplicated before candidate construction, producing one stable `membership_key`; different assignments remain present and reject as `conflicting_current_assignment`.
- Every taxonomy row is reconstructed from canonical `raw_json` and checked against candidate `snapshot_id` / `started_at`, `SW` / `SW2021`, provider, normalized content, and `taxonomy_node_key`.
- Every membership row is reconstructed from canonical `raw_json` and checked against candidate `snapshot_id` / `started_at`, `Ashare`, provider, normalized content, and the SW2021-derived `membership_key`.
- `API_TO_TABLE_MAP["index_classify"]` and `API_TO_TABLE_MAP["index_member_all"]` remain unchanged and are covered by the focused suite.

## TDD Evidence

RED:

```text
ImportError: cannot import name 'TAXONOMY_PAGE_SIZE'
1 error during collection
```

GREEN:

```text
./.venv/bin/python3 -m pytest tests/test_sw2021_reference.py tests/test_capability_coverage.py -q
63 passed in 0.32s

./.venv/bin/python3 -m pytest -q
448 passed, 17 warnings in 17.44s
```

The 17 warnings are the pre-existing test-environment warning that `SHAREDSIGNALS_TOKEN_SALT` is empty; no real token was introduced for this task.

## Residual Boundary

This task constructs and validates an in-memory candidate only. It does not write or promote a snapshot, install a schedule, use provider credentials, modify production state, or push a branch.

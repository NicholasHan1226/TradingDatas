# Sector Flow Facts v2 Handoff

## Current state

- Worktree: `/Users/nicholashan/Projects/Finance/.worktrees/sharedsignals-sector-flow-v2`
- Branch: `codex/sharedsignals-sector-flow-v2`
- Base: SharedSignals `main` at `ccff5c8f2e2891361c3adae911f8ad0bb199a85d`
- Delivery state: uncommitted local shadow implementation
- GitHub main: unchanged
- Production files/runtime/API/route/database: unchanged and unverified for this capability

## Scope delivered

- canonical SQLite/DuckDB schema for three v2 snapshot tables;
- authoritative mirror classification for exact stale-row reconciliation;
- DB-first read-only module with PIT `available_at` selection;
- exact separation of `official_eod` and `intraday_proxy`;
- canonical SHA-256 binding across the snapshot, industry, and constituent tables;
- fail-closed PIT, count, coverage, and SW2021 taxonomy/membership validation;
- exact runtime states `success/empty/unobserved/paused/failed`;
- `success` requires full industry and constituent coverage;
- constituents cannot reference an industry absent from the same sector-flow snapshot;
- pinned SW2021 completion, promotion, taxonomy, and membership timestamps must all predate sector availability in one timezone-aware order;
- pinned SW2021 taxonomy children must be `SW/SW2021`, memberships must be `Ashare`, and header taxonomy/membership/distinct-symbol counts must match all child rows;
- published headers must identify exactly v2/A-share with a non-empty source run ID across latest, PIT, and pinned reads;
- non-finite industry or constituent money facts fail closed without leaking canonical-JSON exceptions;
- versioned HTTP routes and dedicated least-privilege auth scope;
- degraded-empty and runtime-status semantics;
- tests and this independent contract/handoff documentation.

No writer, collector, provider adapter, cron, capability activation, migration execution, deploy, token update, or scoring logic is included.

## Protected parallel scope

The concurrent opening P0 v2 lane owns opening-gate and existing 5-minute hot paths. This worktree does not modify:

- `tools/opening_gate.py` or `tests/test_opening_gate.py`;
- opening-gate API behavior;
- Tushare P0 or current 5-minute collectors/cron;
- root `STATUS.md`, `API_CONTRACT.md`, or `README.md`.

If this candidate is later integrated, shared documentation should be updated only after resolving concurrent P0 edits and after deciding whether the local shadow contract is accepted.

## Verification commands

The worktree uses its own Python 3.12 `.venv` because the main checkout `.venv` points to Apple Python 3.9 and cannot import `datetime.UTC` used by existing SW2021 code.

```bash
./.venv/bin/python -m pytest -q tests/test_sector_flow_v2_schema.py
./.venv/bin/python -m pytest -q tests/test_sector_flow_v2_reader.py
./.venv/bin/python -m pytest -q tests/test_sector_flow_v2_api.py
./.venv/bin/python -m pytest -q \
  tests/test_migrate.py tests/test_duckdb_schema_migration.py \
  tests/test_storage_adapter.py tests/test_auth_security.py \
  tests/test_api_server_edge.py
./.venv/bin/python -m pytest -q
git diff --check
```

## Integration prerequisites

1. Review the schema and route names as a new v2 product contract.
2. Rebase or replay only after the opening P0 v2 lane has settled shared API/auth files.
3. Design and separately approve a writer with atomic publication and SW2021 pinning.
4. Make that writer compute the canonical source hash only after all three table payloads are final.
5. Add a provider pilot proving source authority, PIT timestamps, units, and coverage formulas.
6. Obtain explicit schema-migration and production authorization.
7. Run SQLite/DuckDB migration and reconciliation in a controlled maintenance lane.
8. Update shared `API_CONTRACT.md`, `STATUS.md`, capability registry, external-agent config, and live `/capabilities` only when activation is real.
9. Verify local files, GitHub main, production files, production runtime, authenticated HTTP, external route, and real data rows as separate layers.

## Rollback

No commit or external state exists. To abandon the candidate, first preserve any desired diff, then remove the worktree through the SharedSignals main checkout:

```bash
git -C /Users/nicholashan/Projects/Finance/SharedSignals worktree remove \
  /Users/nicholashan/Projects/Finance/.worktrees/sharedsignals-sector-flow-v2
git -C /Users/nicholashan/Projects/Finance/SharedSignals branch -D \
  codex/sharedsignals-sector-flow-v2
```

Those commands are documentation only and were not run.

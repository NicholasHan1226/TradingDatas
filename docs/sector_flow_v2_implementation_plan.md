# Sector Flow Facts v2 Implementation Plan

> **Execution mode:** Inline in the isolated `codex/sharedsignals-sector-flow-v2` worktree. No commits, pushes, deploys, provider calls, cron changes, opening-gate changes, or P0/5-minute collector changes are allowed.

**Goal:** Add a versioned, DB-first, read-only sector capital-flow fact surface with PIT timestamps, source and coverage evidence, separate official close and intraday-proxy semantics, industry and constituent snapshots, and honest runtime status.

**Architecture:** New SQLite/DuckDB contract tables hold immutable snapshot headers, sector facts, and constituent facts bound by one canonical source hash. A focused `sector_flow_v2.py` reader resolves only published v2/A-share snapshots, validates finite facts, PIT/count/coverage/SW2021 child/header lineage and the five-state runtime contract, and returns fail-closed wrappers without provider or file fallback. Three `/v2/sector-flow/*` routes expose snapshot status, sector facts, and constituent facts under a dedicated least-privilege scope.

**Tech Stack:** Python 3.12, SQLite, DuckDB schema contract, stdlib HTTP server, pytest.

---

### Task 1: Storage contract

**Files:**
- Modify: `storage/schema_contract.py`
- Test: `tests/test_sector_flow_v2_schema.py`

- [ ] Add failing tests proving the three v2 tables, keys, PIT/source/coverage/source-hash fields, and official/proxy discriminator exist in both SQLite and DuckDB renderings.
- [ ] Run `./.venv/bin/python -m pytest -q tests/test_sector_flow_v2_schema.py` and confirm the tables are missing.
- [ ] Add `market_sector_flow_snapshots_v2`, `market_sector_flow_industries_v2`, and `market_sector_flow_constituents_v2` to the canonical schema contract with lookup indexes.
- [ ] Re-run the schema test and `tests/test_migrate.py tests/test_duckdb_schema_migration.py`.

### Task 2: DB-first read contract

**Files:**
- Create: `sector_flow_v2.py`
- Test: `tests/test_sector_flow_v2_reader.py`

- [ ] Add failing tests for latest published resolution, explicit snapshot pinning, `official_eod` versus `intraday_proxy` isolation, v2/A-share/run identity, canonical hash tampering and non-finite values, strict sector and cross-snapshot SW2021 PIT, SW child identity/header counts, count/coverage/SW2021 lineage, full-coverage `success`, same-snapshot constituent-to-industry closure, five-state runtime semantics, constituent filtering, and degraded empty behavior for missing tables or unpublished snapshots.
- [ ] Run the reader tests and confirm import/function failures.
- [ ] Implement read-only SQLite queries with short timeout, strict enum validation, bounded limits, no provider/file fallback, and wrappers compatible with `api_response.aggregate_metadata`.
- [ ] Re-run the reader tests and `git diff --check`.

### Task 3: Versioned HTTP and least privilege

**Files:**
- Modify: `api_server.py`
- Modify: `auth.py`
- Test: `tests/test_sector_flow_v2_api.py`
- Test: `tests/test_auth_security.py`

- [ ] Add failing tests for `/v2/sector-flow/snapshot`, `/v2/sector-flow/industries`, and `/v2/sector-flow/constituents`, parameter validation, runtime-status semantics, and exact `sector_flow_v2` scope isolation.
- [ ] Run the tests and confirm unknown-route/scope failures.
- [ ] Wire the focused reader into the three routes without changing opening-gate or existing market-data routes.
- [ ] Add only the three exact paths to a dedicated scope and approved read composites.
- [ ] Re-run API/auth tests and `git diff --check`.

### Task 4: Contract and handoff documentation

**Files:**
- Create: `docs/sector_flow_v2_contract.md`
- Create: `docs/sector_flow_v2_handoff.md`

- [ ] Document table and HTTP schemas, v2/A-share/run identity, finite money facts, PIT meanings (`effective_at`, `available_at`, `collected_at`), SW child/header lineage, coverage formulas, official/proxy separation, published-state gating, degraded reasons, and explicit non-goals including no scoring.
- [ ] Document local-only status, files changed, test commands, operational prerequisites, rollback by deleting the uncommitted worktree, and all unverified production/runtime items.
- [ ] Confirm no changes to `STATUS.md`, `API_CONTRACT.md`, `README.md`, opening-gate, cron, or P0 collectors.

### Task 5: Verification and precise diff

- [ ] Run all new tests plus affected migration, DuckDB, auth, and API suites.
- [ ] Run the full local pytest suite under the Python 3.12 worktree venv.
- [ ] Run `git diff --check`, `git status --short`, `git diff --stat`, and inspect every changed hunk.
- [ ] Produce a handoff with exact paths, diff summary, test counts, baseline caveat, and explicit local/GitHub/production/runtime separation.

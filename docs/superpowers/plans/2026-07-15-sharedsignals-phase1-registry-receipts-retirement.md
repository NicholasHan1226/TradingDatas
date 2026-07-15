# SharedSignals Phase 1 Registry, Receipts, and Repository Retirement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Retire the first safe set of out-of-scope repository artifacts, establish one provider-neutral dataset registry, and make SQLite transaction receipts the authoritative record of Tushare ingestion without changing the public API, database schema, or production runtime.

**Architecture:** The registry becomes the sole declarative authority for dataset identity, provider binding, storage mapping, entitlement, cadence, and freshness policy. Existing hard-coded Tushare lists remain temporary compatibility views derived from that registry. Ingest data and a versioned receipt commit in the same SQLite transaction; terminal empty or failed attempts receive receipt-only transactions. Flat JSON runtime files remain optional rebuildable projections and are never authoritative.

**Tech Stack:** Python 3.12, SQLite, PyYAML, pytest, Bash, Git

## Global Constraints

- Work from an isolated Git worktree created from SharedSignals local `main` after this plan is committed.
- Do not stage or delete `.codegraphcontext/`.
- Do not touch production, live cron, systemd, nginx, databases, secrets, external routes, real email, TradingAgent, or MarketGraph.
- Do not create or run a database migration. Reuse the existing `market_ingest_runs.notes` column for the versioned receipt payload.
- Do not delete historical data, evidence, old worktrees, or the structurally rejected flat-file-authority candidate. Those are cleaned only after the replacement is integrated and rollback evidence exists.
- SharedSignals contains factual data only. No opening gate, candidate selection, prediction, score, capital, position, risk, order, fill, or trading decision may be introduced.
- Phase 1 does not add `GET /v1/catalog`, `POST /v1/query`, invite-account authentication, quota, billing, or production scheduling. Those are separate plans after receipt authority is accepted.
- Tushare provider errors, entitlement errors, rate limits, validation failures, storage failures, and resource-budget failures must never be represented as legitimate empty results.
- A configured or mapped provider API is not automatically entitled, active, fresh, or externally usable.
- Every task uses TDD: write the failing test, run it and confirm the expected failure, implement the smallest change, rerun targeted tests, then commit only the exact task files.
- Never use `git add .`; stage exact paths only.

## Later implementation plans

This plan intentionally stops at the data-platform foundation. The following plans must be written and reviewed separately:

1. **Phase 2 — Query service:** `GET /v1/catalog`, `POST /v1/query`, metadata projection, signed keyset pagination, and legacy `/tushare` compatibility.
2. **Phase 3 — Entitlement and collection:** full domestic Tushare catalog, permission probing, registry-driven scheduler, throttled backfill, and cadence verification.
3. **Phase 4 — Invite-only Beta access:** tenant credentials, dataset/field/lookback policy, persistent quota and usage ledger, revocation, and operational runbooks.
4. **Phase 5 — Production retirement and release:** fresh live inventory, rollback capture, code-only release, retired job removal, API readback, and stability observation.

---

## Task 1: Capture the Phase 1 baseline and remove five obsolete documents

**Files:**

- Delete: `docs/opening_gate_5min_gate_v2_handoff.md`
- Delete: `docs/sector_flow_v2_handoff.md`
- Delete: `docs/sector_flow_v2_implementation_plan.md`
- Delete: `docs/superpowers/plans/2026-07-11-capital-growth-data-foundation.md`
- Delete: `docs/superpowers/reports/2026-07-11-sw2021-task4-fix-report.md`

**Interfaces:** None. This is a Git-only documentation retirement; Git history is the rollback path.

- [ ] **Step 1: Verify the worktree and references before deletion**

  Run:

  ```bash
  git status --short --branch
  git rev-parse HEAD
  rg -n 'opening_gate_5min_gate_v2_handoff|sector_flow_v2_handoff|sector_flow_v2_implementation_plan|2026-07-11-capital-growth-data-foundation|2026-07-11-sw2021-task4-fix-report' \
    --glob '!docs/superpowers/specs/2026-07-15-sharedsignals-external-data-platform-beta-design.md' .
  ```

  Expected: only mutual references inside the five files, or no references. Stop if code, tests, active documentation navigation, or deployment tooling references any file.

- [ ] **Step 2: Delete only the verified files**

  ```bash
  git rm -- \
    docs/opening_gate_5min_gate_v2_handoff.md \
    docs/sector_flow_v2_handoff.md \
    docs/sector_flow_v2_implementation_plan.md \
    docs/superpowers/plans/2026-07-11-capital-growth-data-foundation.md \
    docs/superpowers/reports/2026-07-11-sw2021-task4-fix-report.md
  ```

- [ ] **Step 3: Verify the exact deletion**

  ```bash
  git diff --cached --name-status
  git diff --cached --check
  ```

  Expected: exactly five `D` entries and no other staged path.

- [ ] **Step 4: Commit the retirement**

  ```bash
  git commit -m "docs: remove obsolete handoff and candidate artifacts"
  ```

---

## Task 2: Remove the unused impact-relation helper

**Files:**

- Modify: `collectors/tushare/tushare_common.py`
- Test: `tests/test_tushare_common.py`
- Test: `tests/test_tushare_sync_daily.py`

**Interfaces:** Remove private symbols `_IMPACT_RELATION_LOGGER` and `filter_impact_relations`. No public API changes.

- [ ] **Step 1: Prove the symbols are unused**

  ```bash
  rg -n 'filter_impact_relations|_IMPACT_RELATION_LOGGER' \
    collectors tests tools api_server.py reader.py
  ```

  Expected: definitions only. Stop if any runtime caller exists.

- [ ] **Step 2: Run the targeted baseline**

  ```bash
  ./.venv/bin/python3 -m pytest -q \
    tests/test_tushare_common.py \
    tests/test_tushare_sync_daily.py
  ```

  Expected: pass before deletion.

- [ ] **Step 3: Remove the helper and its now-unused import**

  Delete `filter_impact_relations()`, `_IMPACT_RELATION_LOGGER`, and the `logging` import only if no other code in the file uses it.

- [ ] **Step 4: Verify behavior and static quality**

  ```bash
  rg -n 'filter_impact_relations|_IMPACT_RELATION_LOGGER' \
    collectors tests tools api_server.py reader.py && exit 1 || true
  ./.venv/bin/python3 -m pytest -q \
    tests/test_tushare_common.py \
    tests/test_tushare_sync_daily.py
  ./.venv/bin/python3 -m compileall -q collectors/tushare/tushare_common.py
  ./.venv/bin/ruff check collectors/tushare/tushare_common.py tests/test_tushare_common.py
  git diff --check
  ```

- [ ] **Step 5: Commit only the helper deletion**

  ```bash
  git add -- collectors/tushare/tushare_common.py
  git diff --cached --name-status
  git commit -m "refactor: remove unused impact relation filter"
  ```

---

## Task 3: Narrow the repository cron template to the domestic Beta scope

**Files:**

- Modify: `cron/crontab.txt`
- Modify: `cron/collectors.sh`
- Modify: `tests/test_capability_coverage.py`
- Modify: `tests/test_tushare_sync_daily.py`
- Modify: `cron/AGENTS.md`
- Modify: `STATUS.md`

**Interfaces:**

```bash
SUPPORTED_TIERS=(P0_trading_5min P1_eod_daily P2_financial_daily P3_reference_daily P4_macro_daily P5_hk_us_daily P6_other_daily)
DEFAULT_TIERS=(P0_trading_5min P1_eod_daily P3_reference_daily P4_macro_daily P6_other_daily)
P4_DOMESTIC_APIS=cn_cpi,cn_pmi,cn_m,cn_ppi,shibor,shibor_lpr,cn_gdp,sf_month,index_dailybasic,repo_daily
```

No-argument and `--all` execution use `DEFAULT_TIERS`. Explicit
`--tier P2_financial_daily` and `--tier P5_hk_us_daily` remain recognized for
future horizontal compatibility, but neither is scheduled or run by default.
Default P4 execution must pass the exact `P4_DOMESTIC_APIS` value through
`--only-api`; the config may retain foreign P4 interfaces for future capability,
but default domestic Beta execution must not call them.

- [ ] **Step 1: Add failing schedule-scope assertions**

  In `tests/test_capability_coverage.py`, parse only non-empty, non-comment lines from `cron/crontab.txt` and assert that active commands exclude:

  ```python
  FORBIDDEN_ACTIVE_TOKENS = (
      "P5_hk_us_daily",
      "crypto_collect",
      "pm_collect",
      "opening_gate",
      "green_gate_report",
      "patrol.sh",
      "watchdog.sh",
      "proxy_relay_health",
      "duckdb_sync",
  )
  ```

  In `tests/test_tushare_sync_daily.py`, add assertions that default and `--all`
  tier resolution exclude P2 and P5 while explicit validation accepts both.
  Execute the wrapper hermetically and assert that the default P4 invocation
  passes `--only-api` with exactly `P4_DOMESTIC_APIS` and resolves only those ten
  APIs from the existing config.

- [ ] **Step 2: Run the new tests and confirm they fail**

  ```bash
  ./.venv/bin/python3 -m pytest -q \
    tests/test_capability_coverage.py \
    tests/test_tushare_sync_daily.py
  ```

  Expected: fail because the existing target template/default tier list still
  activates P5 and other retired jobs, P2 is not separated as explicit-only,
  and default P4 has no domestic `--only-api` filter.

- [ ] **Step 3: Change the target template and collector defaults**

  Remove active P5, crypto, prediction-market, opening-gate, real-email, patrol, watchdog, and proxy-relay commands from `cron/crontab.txt`. Keep domestic Tushare, CN futures, events, external API probe, and temporarily the read-only governance/capability checks. Leave P2, DuckDB, SQLite maintenance, and SW2021 commented.

  Split `SUPPORTED_TIERS` and `DEFAULT_TIERS` in `cron/collectors.sh`. Keep P2
  and P5 supported for explicit compatibility but exclude both from defaults.
  For P4, append `--only-api` with exactly `P4_DOMESTIC_APIS`; do not edit the
  provider config because the excluded foreign interfaces are retained for
  future horizontal capability. Do not edit the root `crontab.txt`, live
  crontab, other wrappers, systemd, or production.

- [ ] **Step 4: Update operational scope documentation**

  In `cron/AGENTS.md`, distinguish active domestic target-template jobs from retained-but-unscheduled compatibility wrappers. In `STATUS.md`, record that only the repository target template changed and that the root snapshot and production live schedule remain unchanged and unverified.

- [ ] **Step 5: Verify the template and regression set**

  ```bash
  bash -n cron/collectors.sh
  ./.venv/bin/python3 -m pytest -q \
    tests/test_capability_coverage.py \
    tests/test_tushare_sync_daily.py \
    tests/test_deploy_scripts_safety.py \
    tests/test_source_expansion_priority.py \
    tests/test_source_governance_monitor.py
  ./.venv/bin/ruff check \
    tests/test_capability_coverage.py \
    tests/test_tushare_sync_daily.py
  awk 'NF && $1 !~ /^#/' cron/crontab.txt | \
    rg 'P5_hk_us_daily|crypto_collect|pm_collect|opening_gate|green_gate_report|patrol\.sh|watchdog\.sh|proxy_relay_health|duckdb_sync' \
    && exit 1 || true
  git diff --check
  ```

- [ ] **Step 6: Commit the repository schedule target**

  ```bash
  git add -- \
    cron/crontab.txt \
    cron/collectors.sh \
    tests/test_capability_coverage.py \
    tests/test_tushare_sync_daily.py \
    cron/AGENTS.md \
    STATUS.md
  git diff --cached --name-status
  git commit -m "chore: narrow repository cron template to domestic beta"
  ```

---

## Task 4: Create the provider-neutral dataset registry loader

**Files:**

- Create: `dataset_registry.py`
- Create: `config/dataset_registry.yaml`
- Create: `tests/test_dataset_registry.py`

**Interfaces:**

```python
@dataclass(frozen=True)
class DatasetField:
    name: str
    logical_type: str
    nullable: bool
    selectable: bool
    filterable: bool
    sortable: bool


@dataclass(frozen=True)
class FixedFieldFilter:
    field: str
    allowed_values: tuple[str, ...]


@dataclass(frozen=True)
class ReadModelAdapter:
    adapter_version: str
    primary_table: str
    fixed_field_filters: tuple[FixedFieldFilter, ...]


@dataclass(frozen=True)
class ProviderBinding:
    provider: str
    api_name: str
    adapter_version: str
    read_discriminator_value: str
    entitlement_state: str
    activation_state: str
    target_tables: tuple[str, ...]


@dataclass(frozen=True)
class DatasetDefinition:
    dataset_id: str
    aliases: tuple[str, ...]
    domain: str
    market: str
    entity_type: str
    data_classification: str
    schema_version: str
    fields: tuple[DatasetField, ...]
    primary_key: tuple[str, ...]
    default_projection: tuple[str, ...]
    cadence_class: str
    timezone: str
    freshness_sla_seconds: int
    max_page_size: int
    max_lookback_days: int | None
    point_in_time: str
    backfill_policy: str
    empty_data_policy: str
    required_scope: str
    quota_class: str
    provider_bindings: tuple[ProviderBinding, ...]
    read_model_adapter: ReadModelAdapter


class DatasetRegistry:
    def resolve(self, name: str) -> DatasetDefinition: ...
    def provider_binding(self, dataset_id: str, provider: str) -> ProviderBinding: ...
    def compatibility_api_names(self, provider: str) -> frozenset[str]: ...
    def compatibility_table_map(self, provider: str) -> dict[str, str]: ...
    def active_for_cadence(self, cadence_class: str) -> tuple[DatasetDefinition, ...]: ...


def load_dataset_registry(path: Path = DATASET_REGISTRY_PATH) -> DatasetRegistry: ...
```

- [ ] **Step 1: Write loader validation tests first**

  Add tests that reject duplicate dataset IDs, aliases, providers, provider API ownership, fields, primary keys, default-projection entries, and read discriminator values; cross-dataset ownership of the same read discriminator on the same primary table; invalid field/policy/state/data-classification enums and booleans; unknown or non-selectable projected fields; non-positive SLA/page limits; non-null non-positive lookbacks; incomplete ingest/read adapters even while a binding is paused or its entitlement is unknown; unknown or duplicate fixed-filter fields; provider filter values that do not exactly match binding-owned read discriminator values; read tables absent from provider target tables; active bindings without active entitlement; any selectable/filterable/sortable capability on internal `raw_json`/`source_file` fields; and unknown keys at every registry level. Add positive tests for `cn.equity.daily`, `tushare.daily`, the `objective_factual` classification, schema types/nullability, immutable nested contracts, compatibility-table derivation, reuse of a discriminator on a different physical table, and the entitlement-plus-activation cadence gate.

- [ ] **Step 2: Confirm the tests fail because the loader does not exist**

  ```bash
  ./.venv/bin/python3 -m pytest -q tests/test_dataset_registry.py
  ```

  Expected: import or file-not-found failure.

- [ ] **Step 3: Implement the immutable loader and validation**

  Use `yaml.safe_load`, reject unknown keys at root/dataset/field/binding/read-adapter/filter levels, normalize lists to tuples of frozen dataclasses, and validate field types and capabilities, primary/default projections, dataset-level page/lookback policy, policy/state/data-classification enums, provider API ownership, read-table membership, fixed field filters, and active-entitlement coupling. Require every binding, including paused or unknown-entitlement bindings, to declare non-empty adapter version, target tables, and a unique read discriminator value. Require the read adapter's fixed `provider` filter `allowed_values` to equal exactly the set of binding-owned discriminator values, so missing and ghost values fail closed. Build global read ownership keyed by `(read_model_adapter.primary_table, ProviderBinding.read_discriminator_value)` and reject that key when two dataset IDs claim it; the same discriminator remains valid on different physical tables. Each fixed field has a non-empty, duplicate-free `allowed_values` tuple: one value compiles to equality and multiple values compile to bounded membership, without accepting arbitrary operators or SQL. Derive compatibility table maps from the dataset read-model adapter, not an ingest binding. Do not read runtime state from YAML and do not import TradingAgent or MarketGraph.

- [ ] **Step 4: Add the first representative registry entries**

  Add `cn.equity.daily`, `cn.market.trade_calendar`, and `cn.event.major_news`. Include stable aliases, typed fields, default/filter/sort/select policy, the `objective_factual` data classification, provider ingest bindings, schema version, primary key, cadence, SLA, point-in-time mode, `provider_limited` backfill, `allowed` empty-data policy, and a read-model adapter. Keep unverified entitlement as `unknown` and activation as `paused`; each binding owns a unique `read_discriminator_value`, and each representative shared table starts with the exactly matching fixed discriminator `provider=tushare_<api_name>`. A future second provider adds a binding and extends that field's `allowed_values` with the binding-owned discriminator without adding a route, adapter type, arbitrary operator, or SQL. `raw_json` and `source_file` are never selectable, filterable, or sortable.

- [ ] **Step 5: Verify the loader**

  ```bash
  ./.venv/bin/python3 -m pytest -q tests/test_dataset_registry.py
  ./.venv/bin/ruff check dataset_registry.py tests/test_dataset_registry.py
  ./.venv/bin/python3 -m compileall -q dataset_registry.py
  git diff --check
  ```

- [ ] **Step 6: Commit the registry kernel**

  ```bash
  git add -- dataset_registry.py config/dataset_registry.yaml tests/test_dataset_registry.py
  git diff --cached --name-status
  git commit -m "feat: add provider-neutral dataset registry"
  ```

---

## Task 5: Import the existing Tushare compatibility surface into the registry

**Files:**

- Modify: `config/dataset_registry.yaml`
- Modify: `dataset_registry.py`
- Modify: `storage/read_model_store.py`
- Modify: `api_server.py`
- Modify: `tools/interface_runtime_ledger.py`
- Modify: `tests/test_dataset_registry.py`
- Modify: `tests/test_capability_coverage.py`
- Modify: `tests/test_interface_runtime_ledger.py`

**Interfaces:**

```python
TUSHARE_API_TO_TABLE_MAP = load_dataset_registry().compatibility_table_map("tushare")
TUSHARE_ALLOWED_API_NAMES = load_dataset_registry().compatibility_api_names("tushare")
```

The temporary legacy constants `API_TO_TABLE_MAP` and `ALLOWED_TUSHARE_APIS` remain import-compatible aliases of these derived values.

- [x] **Step 1: Write failing single-authority tests**

  Assert that the registry-derived Tushare API set and table map equal the current 114-entry compatibility surface, including independent `rt_fut_min`. Assert that current domestic bindings are `unknown` plus `paused`, while Phase 1 HK, US, global, crypto, prediction-market, and explicitly cross-border bindings are `excluded` plus `paused`; this task marks no binding active or entitled. If a domestic binding is activated by a future entitlement task, its cadence, SLA, primary key, entitlement evidence, adapter version, and read table must already form a complete contract.

- [x] **Step 2: Confirm the tests fail with the representative-only registry**

  ```bash
  ./.venv/bin/python3 -m pytest -q \
    tests/test_dataset_registry.py \
    tests/test_capability_coverage.py \
    tests/test_interface_runtime_ledger.py
  ```

- [x] **Step 3: Import and classify the 114 compatibility bindings**

  Build stable provider-neutral dataset IDs. Preserve the current Tushare API name as an alias and provider binding. Use strict, immutable `schema_profiles` inside the same registry YAML to reuse typed fields, primary keys, default projections, and bounded query policy; the loader materializes every `DatasetDefinition` and rejects unknown profiles, profile-version mismatches, inline overrides, and unknown profile keys. Do not add a generator or second manifest. Do not mark a dataset active merely because it was configured.

- [x] **Step 4: Derive compatibility constants from the registry**

  Replace hand-maintained lists in `storage/read_model_store.py`, `api_server.py`, and `tools/interface_runtime_ledger.py` with registry-derived immutable values while preserving public names and existing behavior.

- [x] **Step 5: Verify parity and imports**

  ```bash
  ./.venv/bin/python3 -m pytest -q \
    tests/test_dataset_registry.py \
    tests/test_capability_coverage.py \
    tests/test_interface_runtime_ledger.py \
    tests/test_read_model_store.py \
    tests/test_api_server_edge.py
  ./.venv/bin/ruff check \
    dataset_registry.py storage/read_model_store.py api_server.py \
    tools/interface_runtime_ledger.py tests/test_dataset_registry.py \
    tests/test_capability_coverage.py tests/test_interface_runtime_ledger.py
  ./.venv/bin/python3 -m compileall -q \
    dataset_registry.py storage/read_model_store.py api_server.py \
    tools/interface_runtime_ledger.py
  git diff --check
  ```

- [x] **Step 6: Commit the compatibility import**

  ```bash
  git add -- \
    config/dataset_registry.yaml \
    dataset_registry.py \
    storage/read_model_store.py \
    api_server.py \
    tools/interface_runtime_ledger.py \
    tests/test_dataset_registry.py \
    tests/test_capability_coverage.py \
    tests/test_interface_runtime_ledger.py
  git diff --cached --name-status
  git commit -m "refactor: derive Tushare compatibility from dataset registry"
  ```

---

## Task 6: Preserve provider call outcomes before row conversion

**Files:**

- Modify: `collectors/tushare/collector.py`
- Modify: `collectors/tushare/tushare_common.py`
- Modify: `tests/test_tushare_common.py`
- Modify: `tests/test_tushare_sync_daily.py`

**Interfaces:**

```python
@dataclass(frozen=True)
class ProviderCallOutcome:
    state: Literal["success", "empty", "failed"]
    rows: tuple[dict[str, Any], ...]
    provider_code: int | str | None
    error_code: str | None
    error_message: str | None
```

```python
def tushare_rows_outcome(
    api_name: str,
    token: str,
    *,
    params: Mapping[str, Any] | None = None,
    fields: str = "",
) -> ProviderCallOutcome: ...
```

- [ ] **Step 1: Write failing provider-error and empty-result tests**

  Test that a Tushare non-zero provider code becomes `failed`, a valid zero-row response becomes `empty`, and a valid response becomes `success`. Confirm that error code/message survive row conversion. Test entitlement denial and rate-limit errors separately.

- [ ] **Step 2: Run the tests and observe the existing ambiguity**

  ```bash
  ./.venv/bin/python3 -m pytest -q \
    tests/test_tushare_common.py \
    tests/test_tushare_sync_daily.py
  ```

  Expected: new tests fail because existing non-strict conversion can collapse failures into empty rows.

- [ ] **Step 3: Implement the typed outcome on the strict provider path**

  Preserve the existing compatibility functions, but route `sync_daily` through a strict outcome that keeps provider code and error classification. Do not perform request-time fallback and do not invent a successful empty outcome after an exception.

- [ ] **Step 4: Verify provider truth preservation**

  ```bash
  ./.venv/bin/python3 -m pytest -q \
    tests/test_tushare_common.py \
    tests/test_tushare_sync_daily.py
  ./.venv/bin/ruff check \
    collectors/tushare/collector.py \
    collectors/tushare/tushare_common.py \
    tests/test_tushare_common.py \
    tests/test_tushare_sync_daily.py
  ./.venv/bin/python3 -m compileall -q \
    collectors/tushare/collector.py \
    collectors/tushare/tushare_common.py
  git diff --check
  ```

- [ ] **Step 5: Commit the explicit outcome model**

  ```bash
  git add -- \
    collectors/tushare/collector.py \
    collectors/tushare/tushare_common.py \
    tests/test_tushare_common.py \
    tests/test_tushare_sync_daily.py
  git diff --cached --name-status
  git commit -m "fix: preserve Tushare provider outcomes"
  ```

---

## Task 7: Add versioned ingest receipt types and serialization

**Files:**

- Create: `storage/ingest_receipts.py`
- Create: `tests/test_ingest_receipts.py`

**Interfaces:**

```python
RECEIPT_SCHEMA_VERSION = "sharedsignals.ingest_receipt.v1"


@dataclass(frozen=True)
class IngestContext:
    attempt_id: str
    dataset_id: str
    provider: str
    provider_api: str
    request_window: Mapping[str, str]
    config_hash: str
    adapter_version: str
    started_at: str
    data_through: str | None


@dataclass(frozen=True)
class IngestCounts:
    returned: int
    validated: int
    inserted: int | None
    updated: int | None
    unchanged: int | None
    rejected: int
    committed: int
    count_semantics: str


@dataclass(frozen=True)
class IngestResult:
    status: str
    counts: IngestCounts
    receipt_ids: tuple[str, ...]
    errors: tuple[str, ...]


def make_receipt_id(context: IngestContext, target_table: str | None, transaction_index: int) -> str: ...


def insert_ingest_receipt(
    conn: sqlite3.Connection,
    *,
    context: IngestContext,
    target_table: str | None,
    transaction_index: int,
    status: str,
    counts: IngestCounts,
    errors: Sequence[str],
    payload_fingerprint: str,
) -> str: ...


def write_terminal_receipt(
    db_path: Path,
    *,
    context: IngestContext,
    status: str,
    errors: Sequence[str],
) -> IngestResult: ...
```

- [ ] **Step 1: Write serialization and ID tests**

  Test deterministic receipt IDs from `attempt_id + table + transaction_index`, unique IDs for same-day reruns with different attempt IDs, strict count validation, canonical JSON notes, known schema version, absence of secrets, and plain `INSERT` duplicate rejection.

- [ ] **Step 2: Confirm the new tests fail**

  ```bash
  ./.venv/bin/python3 -m pytest -q tests/test_ingest_receipts.py
  ```

- [ ] **Step 3: Implement receipt serialization using the existing table**

  Insert into existing `market_ingest_runs` columns. Store provider-neutral structured data in `notes` as canonical JSON. `insert_ingest_receipt()` must never call `commit()` or `rollback()`; its caller owns the transaction.

- [ ] **Step 4: Verify receipt integrity**

  ```bash
  ./.venv/bin/python3 -m pytest -q tests/test_ingest_receipts.py
  ./.venv/bin/ruff check storage/ingest_receipts.py tests/test_ingest_receipts.py
  ./.venv/bin/python3 -m compileall -q storage/ingest_receipts.py
  git diff --check
  ```

- [ ] **Step 5: Commit the receipt model**

  ```bash
  git add -- storage/ingest_receipts.py tests/test_ingest_receipts.py
  git diff --cached --name-status
  git commit -m "feat: add versioned SQLite ingest receipts"
  ```

---

## Task 8: Commit data and success receipts in the same SQLite transaction

**Files:**

- Modify: `storage/read_model_store.py`
- Modify: `storage/ingest_receipts.py`
- Modify: `tests/test_read_model_store.py`
- Modify: `tests/test_ingest_receipts.py`
- Create: `tests/test_tushare_receipt_integration.py`

**Interfaces:**

```python
def ingest_rows_with_receipts(
    db_path: Path,
    table: str,
    rows: Sequence[Mapping[str, Any]],
    *,
    context: IngestContext,
    source_name: str | None = None,
    max_transaction_rows: int | None = None,
) -> IngestResult: ...
```

The existing `ingest_rows_to_sqlite(...) -> int` remains available for non-Tushare compatibility callers.

- [ ] **Step 1: Write atomicity and chunking tests**

  Add tests for:

  - two data rows plus one success receipt committed together;
  - forced receipt-insert failure rolls back all data from that transaction;
  - five rows with `max_transaction_rows=2` create three independent receipts for 2/2/1 rows;
  - a later chunk failure does not invent a success receipt for the failed chunk;
  - event replay reports `unchanged` honestly;
  - generic upsert uses `None` plus explicit `count_semantics` when inserted/updated/unchanged cannot be proven.

- [ ] **Step 2: Run the tests and confirm they fail**

  ```bash
  ./.venv/bin/python3 -m pytest -q \
    tests/test_ingest_receipts.py \
    tests/test_tushare_receipt_integration.py \
    tests/test_read_model_store.py
  ```

- [ ] **Step 3: Implement one receipt per real transaction**

  Each chunk must execute:

  ```python
  conn.execute("BEGIN IMMEDIATE")
  # write and verify this chunk's data
  insert_ingest_receipt(conn, ...)
  conn.commit()
  ```

  On any exception, call `rollback()` and return or raise a structured failure. Never use `INSERT OR REPLACE` for receipts.

- [ ] **Step 4: Verify atomicity and compatibility**

  ```bash
  ./.venv/bin/python3 -m pytest -q \
    tests/test_ingest_receipts.py \
    tests/test_tushare_receipt_integration.py \
    tests/test_read_model_store.py \
    tests/test_migrate.py
  ./.venv/bin/ruff check \
    storage/read_model_store.py storage/ingest_receipts.py \
    tests/test_read_model_store.py tests/test_ingest_receipts.py \
    tests/test_tushare_receipt_integration.py
  ./.venv/bin/python3 -m compileall -q \
    storage/read_model_store.py storage/ingest_receipts.py
  git diff --check
  ```

- [ ] **Step 5: Commit the atomic ingestion path**

  ```bash
  git add -- \
    storage/read_model_store.py \
    storage/ingest_receipts.py \
    tests/test_read_model_store.py \
    tests/test_ingest_receipts.py \
    tests/test_tushare_receipt_integration.py
  git diff --cached --name-status
  git commit -m "feat: commit data and receipts atomically"
  ```

---

## Task 9: Wire Tushare synchronization to registry identity and terminal receipts

**Files:**

- Modify: `collectors/tushare/sync_daily.py`
- Modify: `storage/ingest_receipts.py`
- Modify: `tests/test_tushare_sync_daily.py`
- Modify: `tests/test_tushare_receipt_integration.py`

**Interfaces:**

```python
def build_ingest_context(
    *,
    registry: DatasetRegistry,
    api_name: str,
    tier: str,
    trade_date: str,
    start_date: str,
    end_date: str,
    source_name: str,
    attempt_id: str,
    config_hash: str,
) -> IngestContext: ...
```

- [ ] **Step 1: Write failing integration tests for every terminal state**

  Test successful data, legitimate empty, provider failure, entitlement denial, rate limit, resource-budget rejection, unmapped API, and validation rejection. Assert:

  - success appears only after validated data transaction commits;
  - validation rejection never records success/ok;
  - every failed attempt writes a failed receipt when the DB is available;
  - same-day reruns produce unique attempt IDs;
  - a missing config file yields a structured config error and never uses the empty-file SHA256 as a valid config hash;
  - missing adapter version or dataset mapping cannot create a success receipt.

- [ ] **Step 2: Run the tests and confirm the current path fails**

  ```bash
  ./.venv/bin/python3 -m pytest -q \
    tests/test_tushare_sync_daily.py \
    tests/test_tushare_receipt_integration.py
  ```

- [ ] **Step 3: Build one registry-backed context per provider attempt**

  Generate a run namespace once, then a unique UUID-based attempt ID for each API call/window. Resolve dataset ID, binding, adapter version, table, cadence, and entitlement from the registry. Hash the actual config bytes only after verifying the file exists and is a regular file.

- [ ] **Step 4: Record terminal outcomes honestly**

  Route success through `ingest_rows_with_receipts()`. Route empty and failures through `write_terminal_receipt()`. Preserve structured error codes such as `provider_error`, `permission_denied`, `rate_limited`, `validation_failed`, `resource_budget`, `unmapped_dataset`, and `storage_failed`.

- [ ] **Step 5: Verify the sync path and regression set**

  ```bash
  ./.venv/bin/python3 -m pytest -q \
    tests/test_tushare_sync_daily.py \
    tests/test_tushare_receipt_integration.py \
    tests/test_ingest_receipts.py \
    tests/test_read_model_store.py \
    tests/test_capability_coverage.py
  ./.venv/bin/ruff check \
    collectors/tushare/sync_daily.py storage/ingest_receipts.py \
    tests/test_tushare_sync_daily.py tests/test_tushare_receipt_integration.py
  ./.venv/bin/python3 -m compileall -q \
    collectors/tushare/sync_daily.py storage/ingest_receipts.py
  git diff --check
  ```

- [ ] **Step 6: Commit the registry-backed sync**

  ```bash
  git add -- \
    collectors/tushare/sync_daily.py \
    storage/ingest_receipts.py \
    tests/test_tushare_sync_daily.py \
    tests/test_tushare_receipt_integration.py
  git diff --cached --name-status
  git commit -m "feat: record authoritative Tushare ingest receipts"
  ```

---

## Task 10: Project runtime state from SQLite receipts and demote flat JSON to cache

**Files:**

- Create: `storage/receipt_projection.py`
- Modify: `tools/interface_runtime_ledger.py`
- Modify: `reader.py`
- Modify: `tests/test_interface_runtime_ledger.py`
- Create: `tests/test_receipt_projection.py`

**Interfaces:**

```python
RuntimeState = Literal["success", "empty", "unobserved", "paused", "failed", "stale"]


@dataclass(frozen=True)
class DatasetRuntimeProjection:
    dataset_id: str
    state: RuntimeState
    degraded: bool
    data_through: str | None
    observed_at: str | None
    receipt_id: str | None
    reasons: tuple[str, ...]


def project_dataset_runtime(
    conn: sqlite3.Connection,
    dataset: DatasetDefinition,
    *,
    now: datetime,
) -> DatasetRuntimeProjection: ...


def rebuild_interface_runtime_cache(
    db_path: Path,
    registry: DatasetRegistry,
    output_path: Path,
    *,
    now: datetime,
) -> None: ...
```

- [ ] **Step 1: Write runtime-state projection tests**

  Cover all six states. Assert that old rows remain queryable but the latest failed receipt makes the dataset degraded; stale is computed against wall-clock and registry SLA; paused comes from registry activation state; unobserved means no recognized receipt; unknown receipt schema fails closed. Delete the flat JSON cache and assert an identical projection can be rebuilt from SQLite.

- [ ] **Step 2: Confirm the tests fail before the projector exists**

  ```bash
  ./.venv/bin/python3 -m pytest -q \
    tests/test_receipt_projection.py \
    tests/test_interface_runtime_ledger.py
  ```

- [ ] **Step 3: Implement DB-first projection and atomic cache rebuild**

  Read only recognized receipt schema versions. Derive summary counts from per-dataset projections; never trust a stored summary over underlying entries. Write the cache with temp file, file fsync, replace, and directory fsync, but treat cache-write failure as an operational error rather than data-authority loss.

- [ ] **Step 4: Keep legacy readers compatible without file authority**

  `tools/interface_runtime_ledger.py` may expose existing functions, but they must call the DB projector or read a cache that is verifiably derived from the current DB watermark. No provider/file fallback is allowed in a public read path.

- [ ] **Step 5: Verify runtime semantics**

  ```bash
  ./.venv/bin/python3 -m pytest -q \
    tests/test_receipt_projection.py \
    tests/test_interface_runtime_ledger.py \
    tests/test_reader.py
  ./.venv/bin/ruff check \
    storage/receipt_projection.py tools/interface_runtime_ledger.py reader.py \
    tests/test_receipt_projection.py tests/test_interface_runtime_ledger.py
  ./.venv/bin/python3 -m compileall -q \
    storage/receipt_projection.py tools/interface_runtime_ledger.py reader.py
  git diff --check
  ```

- [ ] **Step 6: Commit the DB-first runtime projection**

  ```bash
  git add -- \
    storage/receipt_projection.py \
    tools/interface_runtime_ledger.py \
    reader.py \
    tests/test_interface_runtime_ledger.py \
    tests/test_receipt_projection.py
  git diff --cached --name-status
  git commit -m "refactor: project source runtime from SQLite receipts"
  ```

---

## Task 11: Rewrite the minimum active documentation for the new platform boundary

**Files:**

- Modify: `AGENTS.md`
- Modify: `README.md`
- Modify: `STATUS.md`
- Modify: `docs/AGENTS.md`
- Modify: `docs/data_source_onboarding.md`
- Modify: `docs/market_capability_matrix.md`
- Modify: `docs/sqlite_recovery_runbook.md`
- Create: `docs/dataset_registry.md`
- Create: `docs/ingest_receipts.md`

**Interfaces:** Documentation only; it must describe the code already accepted in Tasks 4–10 and must not claim `/v1/catalog`, `/v1/query`, Beta accounts, production release, or full Tushare activation are complete.

- [ ] **Step 1: Add a documentation contract test**

  Extend an existing documentation test or add `tests/test_data_platform_docs.py` to assert:

  - SharedSignals is an independent external multi-source data platform;
  - it excludes trading decisions and cross-system business imports;
  - the registry and SQLite receipts are named as authorities;
  - flat JSON is a rebuildable cache;
  - public v1 API and Beta access are labeled as later phases until implemented;
  - no active navigation points to the five deleted documents.

- [ ] **Step 2: Confirm the current documentation fails the new contract**

  ```bash
  ./.venv/bin/python3 -m pytest -q tests/test_data_platform_docs.py
  ```

- [ ] **Step 3: Rewrite the minimum active documents**

  Keep durable facts in `AGENTS.md` and operational/current facts in `STATUS.md`. Document registry entry fields, provider onboarding without new public routes, receipt transaction semantics, recovery, cache rebuild, and Phase 1 limitations. Do not copy temporary test counts into long-lived architecture docs.

- [ ] **Step 4: Verify links, claims, and formatting**

  ```bash
  ./.venv/bin/python3 -m pytest -q tests/test_data_platform_docs.py
  rg -n 'opening_gate_5min_gate_v2_handoff|sector_flow_v2_handoff|sector_flow_v2_implementation_plan|2026-07-11-capital-growth-data-foundation|2026-07-11-sw2021-task4-fix-report' \
    AGENTS.md README.md STATUS.md docs cron collectors tests && exit 1 || true
  git diff --check
  ```

- [ ] **Step 5: Commit the documentation alignment**

  ```bash
  git add -- \
    AGENTS.md README.md STATUS.md docs/AGENTS.md \
    docs/data_source_onboarding.md docs/market_capability_matrix.md \
    docs/sqlite_recovery_runbook.md docs/dataset_registry.md \
    docs/ingest_receipts.md tests/test_data_platform_docs.py
  git diff --cached --name-status
  git commit -m "docs: align SharedSignals with external data platform boundary"
  ```

---

## Task 12: Run the full Phase 1 verification and freeze the candidate

**Files:**

- Create outside the repository: a candidate manifest and JUnit evidence under `/private/tmp`
- Modify repository files only if a verified defect is found; any fix must return to the relevant task's TDD loop and receive a new commit.

**Interfaces:** The handoff manifest records base/head commits, exact tracked files, per-file SHA256, aggregate SHA256, test commands, JUnit SHA256, documentation status, forbidden-action attestation, and rollback instructions.

- [ ] **Step 1: Verify Git scope and history**

  ```bash
  git status --short --branch
  git log --oneline --decorate origin/main..HEAD
  git diff --name-status origin/main..HEAD
  git diff --check origin/main..HEAD
  ```

  Expected: only the planned repository changes plus the two approved design commits; `.codegraphcontext/` remains untracked and unstaged.

- [ ] **Step 2: Run the focused Phase 1 matrix with JUnit**

  ```bash
  EVIDENCE_DIR="$(mktemp -d /private/tmp/sharedsignals-phase1.XXXXXX)"
  ./.venv/bin/python3 -m pytest -q \
    --junitxml="$EVIDENCE_DIR/phase1-focused.xml" \
    tests/test_dataset_registry.py \
    tests/test_ingest_receipts.py \
    tests/test_tushare_receipt_integration.py \
    tests/test_receipt_projection.py \
    tests/test_read_model_store.py \
    tests/test_tushare_sync_daily.py \
    tests/test_capability_coverage.py \
    tests/test_migrate.py \
    tests/test_interface_runtime_ledger.py \
    tests/test_tushare_common.py \
    tests/test_reader.py \
    tests/test_api_server_edge.py \
    tests/test_data_platform_docs.py
  ```

  Expected: zero failures and zero errors.

- [ ] **Step 3: Run the complete repository suite**

  ```bash
  ./.venv/bin/python3 -m pytest -q \
    --junitxml="$EVIDENCE_DIR/full.xml"
  ```

  Expected: zero failures and zero errors. Any skip must be enumerated and justified in the manifest.

- [ ] **Step 4: Run static and syntax checks**

  ```bash
  ./.venv/bin/ruff check \
    dataset_registry.py \
    storage/ingest_receipts.py \
    storage/receipt_projection.py \
    storage/read_model_store.py \
    collectors/tushare/collector.py \
    collectors/tushare/tushare_common.py \
    collectors/tushare/sync_daily.py \
    tools/interface_runtime_ledger.py \
    api_server.py reader.py tests
  ./.venv/bin/python3 -m compileall -q \
    dataset_registry.py storage collectors/tushare tools \
    api_server.py reader.py
  bash -n cron/collectors.sh
  git diff --check origin/main..HEAD
  ```

- [ ] **Step 5: Generate and verify the candidate manifest**

  Record exact file sizes and SHA256 values, aggregate them deterministically, hash both JUnit files, and state explicitly:

  - no production, cron, systemd, nginx, DB migration, provider write, email, or trading action occurred;
  - the legacy flat-file worktree and historical data remain intact;
  - Phase 2 API and Beta access are not yet implemented;
  - production remains unchanged and unverified.

- [ ] **Step 6: Request a fresh independent read-only review**

  The reviewer must construct a clean overlay from the recorded base, reproduce registry validation, provider error-vs-empty behavior, transaction atomicity, failed-receipt paths, chunk receipts, runtime-state projection, cache rebuild, scope boundaries, tests, documentation, and fingerprints. Any P0 or P1 finding fails the candidate and returns it to the responsible task.

- [ ] **Step 7: Integrate only after fresh PASS**

  The sole integrator independently audits the diff, stages exact files, commits only if needed, fast-forwards or rebases without rewriting history, pushes to the intended remote branch, and verifies GitHub readback. Production release is explicitly out of scope for Phase 1 and requires the later safe-release plan.

---

## Phase 1 acceptance criteria

- The five verified obsolete documents and the unused impact helper are removed from the repository with Git rollback available.
- The repository target schedule excludes P5, crypto, prediction markets, opening gate, real email, patrol/watchdog, proxy relay, and DuckDB, while production remains untouched.
- P2 and P5 remain explicit supported compatibility tiers but are absent from
  defaults and active target scheduling; default P4 passes the exact ten-API
  domestic allowlist while foreign P4 config entries remain available for
  future horizontal capability.
- One provider-neutral registry is the sole declarative authority for the current Tushare compatibility surface.
- Phase 1 domestic/excluded/locked classifications are explicit and truthful; configured does not imply active.
- Provider failures cannot collapse into empty results.
- Each successful data transaction has exactly one same-transaction recognized receipt; rollback cannot leave a success receipt or committed rows.
- Empty and failed attempts are independently distinguishable in SQLite.
- Same-day reruns have unique attempt IDs; config and adapter identity are mandatory for success.
- Runtime states `success`, `empty`, `unobserved`, `paused`, `failed`, and `stale` are derived from registry plus SQLite receipts.
- Removing flat JSON runtime cache does not lose authority; it can be rebuilt consistently from SQLite.
- No SharedSignals trading/research-control responsibility is introduced.
- Focused and full repository tests, Ruff, compile checks, Bash syntax, documentation checks, fingerprints, and independent fresh review all pass.
- No production or external write is claimed or performed in this phase.

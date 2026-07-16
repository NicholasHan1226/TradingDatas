# SharedSignals Phase 2 Catalog and Query Service Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Checkboxes are the reproducible execution checklist, not current-state authority; accepted commits, reviews, and remaining work belong only in `STATUS.md`.

**Goal:** Implement the fixed provider-neutral `GET /v1/catalog` and `POST /v1/query` data plane, bind every response to one verified SQLite facts-and-receipts snapshot, add signed keyset pagination, and migrate `/tushare` plus the single-dataset `/reference?table=stock_master` compatibility endpoint to the same query service without changing the database schema or production runtime. The migration makes the legacy reads bounded cursor surfaces and keeps production release blocked until every known 5,000/6,000-row consumer has moved to explicit cursor exhaustion.

**Architecture:** `DatasetRegistry` remains the catalog and query-policy authority. `CatalogService` combines registry definitions with one `project_registry_runtime()` result from a verified read-only SQLite snapshot. `QueryService` validates a provider-neutral request, compiles only registry-approved identifiers and operators, reads rows and the dataset runtime projection inside the same `open_verified_read_model_snapshot()` context, and returns a stable V1 envelope. `SignedCursorCodec` binds catalog version, dataset/schema, normalized query, access policy, receipt watermark, sort tuple, and expiry. Legacy adapters translate old request parameters into the same `QueryRequest`; they do not retain SQL, file, cache, or provider fallbacks.

**Tech Stack:** Python 3.12, SQLite, PyYAML, `http.server`, dataclasses, HMAC-SHA256, pytest, Ruff, Git

## Global Constraints

- Start from SharedSignals local `main` after the Phase 1 checkpoint `032c208dcd3b727e6ffdd14bc04fde5dbd5314a7` and this plan/status-sync commit are present. Record the actual base SHA before creating the isolated worktree.
- Do not push, deploy, restart services, modify production, enable cron, call Tushare, send email, migrate a database, or perform an irreversible action.
- Do not stage, delete, or move `.codegraphcontext/`, databases, data, receipts, logs, history, evidence, or retained rollback worktrees.
- Public data routes remain exactly `GET /v1/catalog` and `POST /v1/query`. Existing endpoints are compatibility surfaces, not templates for new routes.
- The V1 and migrated compatibility page limit remains `1..500`. A legacy request above 500 returns HTTP 413; it is never clamped, silently truncated, or expanded into hidden multi-page aggregation. Existing 5,000/6,000-row consumers are migration blockers, not reasons to weaken the registry/query-service resource contract.
- SharedSignals remains factual data infrastructure only. Do not add opening gates, predictions, candidate selection, strategy scores, capital, positions, risk, orders, fills, or trading decisions.
- Initial activation remains domestic China. Prediction-market, crypto, Hong Kong, US, and other excluded datasets may remain catalog evidence but must not become tenant-visible active query lanes in this phase.
- SQLite is read-only in catalog/query request paths. Missing database, unsafe binding, missing table/column, malformed receipt, or inconsistent metadata fails closed; no request-time provider, file, sibling-database, or stale-response fallback is allowed.
- Phase 2 does not implement provider collection schedules, entitlement probes, backfill, tenant key issuance, billing, persistent quota, usage ledgers, external gateway changes, or production retirement. Those remain Phases 3–5.
- Use TDD for every behavior: write RED, run the exact failing test, implement the smallest change, rerun the focused test, and stage exact paths only. Never use `git add .`.
- A local PASS proves only the isolated candidate. Local main, origin/GitHub, production checkout, production runtime, external route, and real dataset queries require separate later evidence.

## Frozen public contract

### Query request

```json
{
  "dataset_id": "cn.equity.daily",
  "schema_major": 1,
  "fields": ["symbol", "trade_date", "close"],
  "filters": {
    "symbol": "600519.SH",
    "trade_date": {"between": ["20260701", "20260716"]}
  },
  "as_of": null,
  "order": ["trade_date:desc", "symbol:asc"],
  "limit": 100,
  "cursor": null
}
```

- `dataset_id` and positive integer `schema_major` are required.
- `fields` is an optional duplicate-free list. Empty or omitted means the registry default projection.
- `filters` is an object keyed by registry fields. A scalar means `eq`; an operator object contains exactly one of `eq`, `in`, `gte`, `lte`, or `between`.
- `order` is optional. Each term is exactly `field:asc` or `field:desc`; omission uses the registry primary-key order. Missing primary-key terms and the internal SQLite row identity are appended only as hidden deterministic tie-breakers.
- `limit` is a native positive integer no greater than the effective registry page limit. Boolean, float, numeric string, zero, and negative values are invalid.
- `cursor` is an opaque signed token. It is never accepted as an offset.
- Duplicate JSON keys, non-finite numbers, unknown root fields, SQL/table/provider/credential fields, and arbitrary expressions are rejected.

### Query response

```json
{
  "api_version": "v1",
  "catalog_version": "v1-a1b2c3d4e5f60708",
  "request_id": "123e4567-e89b-42d3-a456-426614174000",
  "dataset_id": "cn.equity.daily",
  "schema_version": "1.0.0",
  "data": [],
  "next_cursor": null,
  "metadata": {
    "state": "ready",
    "runtime_state": "success",
    "degraded": false,
    "freshness": {"state": "fresh", "stale": false, "sla_seconds": 259200},
    "quality": {"state": "valid", "valid": true, "evidence": []},
    "lineage": {
      "state": "complete",
      "complete": true,
      "provider_neutral": true,
      "authority": "sqlite_ingest_receipts",
      "dataset_id": "cn.equity.daily",
      "providers": ["tushare"]
    },
    "receipt_id": "4a9ef4bfdd9f4f8e8a2f4a146b09c1a3",
    "data_through": "2026-07-16T00:00:00+08:00",
    "observed_at": "2026-07-16T15:35:00+08:00",
    "requested_as_of": null,
    "resolved_as_of": null,
    "reasons": []
  }
}
```

- `metadata.runtime_state` preserves the exact registry/receipt state: `success`, `empty`, `unobserved`, `paused`, `failed`, or `stale`.
- `metadata.state` is `ready` only for complete non-degraded `success` evidence; otherwise it is the exact impaired runtime state. This keeps the objective state visible while matching the already frozen consumer envelope.
- `freshness`, `quality`, and `lineage` are always non-empty objects. Healthy data must include non-null receipt, data-through, observed-at, and complete provider-neutral lineage.
- Date-only receipt `data_through` values are normalized to aware local-midnight timestamps using the registry timezone. Unparseable public timestamps degrade/fail closed; they are not invented.
- Failed or stale datasets may return last-known rows only with `degraded=true`, explicit reasons, and the latest attempt watermark. Empty, unobserved, and paused datasets return `data=[]`.
- HTTP 200 never means the dataset is healthy.

### Catalog response

```json
{
  "api_version": "v1",
  "catalog_version": "v1-a1b2c3d4e5f60708",
  "request_id": "123e4567-e89b-42d3-a456-426614174000",
  "data": [],
  "next_cursor": null
}
```

Each visible dataset row exposes only provider-neutral identity, aliases, domain, market, entity type, classification, schema version/fields, default fields, filter/sort capabilities, cadence, timezone, SLA, effective limits, point-in-time support, required scope, quota class, entitlement/activation summary, runtime state, data-through, observed-at, receipt ID, degraded flag, and reasons. It never exposes table names, database paths, SQL, adapter internals, credentials, provider tokens, or excluded datasets the access context cannot discover.

### Access context for Phase 2

Phase 2 reuses the current authenticated account only as an injected access context:

```python
@dataclass(frozen=True)
class QueryAccessContext:
    tenant_id: str
    scopes: tuple[str, ...]
    allowed_dataset_ids: tuple[str, ...]
    policy_id: str
```

`policy_id` is a canonical SHA-256 of tenant ID, normalized scopes, and normalized request-local `allowed_dataset_ids`. Catalog visibility and query permission require the registry `required_scope`, an existing aggregate `external_read`, `read`, `full`, or `*` grant, or an exact request-local dataset grant created by a compatibility adapter. The dataset grant cannot authorize catalog discovery or another dataset. For direct queries, a known and initial-release-eligible dataset that is omitted from the catalog only because the caller lacks its query scope returns 403; an unknown, excluded, or structurally undiscoverable dataset returns 404. Phase 4 replaces this minimal policy with persistent dataset/field/lookback restrictions, quota, revocation, and usage accounting without changing the V1 routes or request envelope.

## Threat model and acceptance freeze

In scope:

- malformed/duplicate/oversized JSON and type confusion;
- SQL identifier or expression injection;
- non-selectable/filterable/sortable fields and unsupported operators;
- page/lookback/resource-budget overruns;
- unsigned, tampered, expired, cross-dataset, cross-schema, cross-query, cross-policy, and cross-receipt cursors;
- duplicate/missing rows across equal sort values and nullable fields;
- database/table/column/receipt/binding drift and WAL snapshot mismatch;
- HTTP 200 carrying stale, failed, empty, paused, or unobserved data;
- legacy endpoint divergence or request-time provider/file fallback;
- cooperative reader/writer races and accidental local-process faults.

Out of scope for Phase 2:

- malicious same-UID processes;
- gateway/DNS/TLS deployment;
- public signup, key issuance, billing, persistent quotas, abuse automation, and tenant administration;
- provider scheduling and production collection;
- database schema migration or physical storage redesign.

Only a deterministic, in-scope P0/P1 affecting data correctness, access isolation, pagination correctness, or service availability may fail a frozen candidate. Two successive structural P1 rounds stop patch stacking and require an architecture decision. Contract-external hardening is P2/backlog.

---

## Task 0: Record the accepted Phase 1 baseline and create the Phase 2 worktree

**Files:**

- Modify: `STATUS.md`
- Add: `docs/superpowers/plans/2026-07-16-sharedsignals-phase2-query-service.md`

**Interfaces:** Documentation/Git only. No runtime behavior.

- [ ] **Step 1: Verify the accepted Phase 1 checkpoint**

  ```bash
  git status --short --branch
  git rev-parse HEAD
  git rev-parse origin/main
  git diff --cached --name-status
  ```

  Expected before this plan commit: local `main` at `032c208dcd3b727e6ffdd14bc04fde5dbd5314a7`, tracked/index clean, only `.codegraphcontext/` untracked, and origin still `d913d32c`.

- [ ] **Step 2: Update only current-state facts in `STATUS.md`**

  Record that Phase 1 is accepted and fast-forwarded to local main, origin/GitHub/production remain unchanged, and Phase 2 is the next isolated candidate. Remove the stale “Phase 1 candidate to local main” item. Do not add test numbers to `AGENTS.md` or the design specification.

- [ ] **Step 3: Validate and commit the plan/status pair**

  ```bash
  rg -n 'TODO|TBD|coming soon|032c208|/v1/catalog|/v1/query' \
    docs/superpowers/plans/2026-07-16-sharedsignals-phase2-query-service.md STATUS.md
  git diff --check
  git add -- STATUS.md docs/superpowers/plans/2026-07-16-sharedsignals-phase2-query-service.md
  git diff --cached --name-status
  git commit -m "docs: freeze Phase 2 query service plan"
  ```

  Expected: exactly two documentation files in the commit.

- [ ] **Step 4: Create one isolated implementation worktree**

  ```bash
  BASE_SHA=$(git rev-parse HEAD)
  git worktree add \
    /Users/nicholashan/Projects/Finance/.worktrees/sharedsignals-phase2-query-service \
    -b codex/sharedsignals-phase2-query-service "$BASE_SHA"
  git -C /Users/nicholashan/Projects/Finance/.worktrees/sharedsignals-phase2-query-service \
    status --short --branch
  ```

  Expected: clean isolated worktree at the plan commit. Stop if the path/branch already exists with unknown work.

## Task 1: Freeze the registry-backed V1 query contract

**Files:**

- Add: `query_contract.py`
- Modify: `dataset_registry.py`
- Modify: `config/dataset_registry.yaml`
- Modify: `tests/test_dataset_registry.py`
- Add: `tests/test_query_contract.py`
- Modify: `API_CONTRACT.md`
- Add: `docs/query_service.md`
- Modify: `docs/AGENTS.md`

**Interfaces:**

```python
@dataclass(frozen=True)
class QueryAccessContext:
    tenant_id: str
    scopes: tuple[str, ...]
    allowed_dataset_ids: tuple[str, ...]
    policy_id: str

@dataclass(frozen=True)
class QueryRequest:
    dataset_id: str
    schema_major: int
    fields: tuple[str, ...]
    filters: Mapping[str, object]
    as_of: str | None
    order: tuple[str, ...] | None
    limit: int
    cursor: str | None

@dataclass(frozen=True)
class QueryExecutionOptions:
    latest_partition: bool = False
    any_of_eq_filters: tuple[tuple[str, object], ...] = ()

def parse_query_request(payload: object) -> QueryRequest: ...
def public_catalog_version(registry: DatasetRegistry) -> str: ...
```

Registry additions:

```yaml
query_defaults:
  max_request_bytes: 65536
  max_response_bytes: 4194304
  max_page_size: 500
  max_lookback_days: 36500
  max_selected_fields: 100
  max_filter_terms: 16
  max_in_values: 100
  max_order_terms: 8
  max_catalog_search_chars: 128
  cursor_ttl_seconds: 900
  sqlite_progress_steps: 1000000
```

Each schema profile adds explicit nullable `as_of_field`, `as_of_format`, `range_field`, and `partition_field` values. `null` means that capability is unsupported. An `as_of_field` must be declared, selectable, filterable, sortable, and use a declared format of `yyyymmdd` or `rfc3339`; Phase 2 semantics are always `field <= normalized_cutoff`. `range_field` is the registry-owned field used by legacy `start_date/end_date` translation. `partition_field` is used only by an internal compatibility execution option and must be a declared filterable/sortable field. Effective max page/lookback values come from the profile override or registry defaults. Filter operators are derived deterministically from registry `filterable` and `logical_type`: `eq/in` for every filterable field and `gte/lte/between` for ordered text/integer/float fields.

- [ ] **Step 1: Write RED registry tests**

  Add tests that reject:

  ```python
  def test_registry_rejects_unknown_or_invalid_query_defaults(...): ...
  def test_registry_rejects_as_of_field_not_in_schema(...): ...
  def test_registry_rejects_non_filterable_as_of_field(...): ...
  def test_public_catalog_version_changes_with_public_contract_only(...): ...
  def test_public_catalog_version_never_exposes_storage_mapping(...): ...
  ```

  Run:

  ```bash
  uv run --python 3.12 --with-requirements requirements.txt python -m pytest -q \
    tests/test_dataset_registry.py
  ```

  Expected: fail because query defaults, `as_of_field`, and catalog version do not exist.

- [ ] **Step 2: Write RED request-contract tests**

  Cover the TA-compatible request shape and exact failures, including field/filter/`in`/order budgets and native-type checks:

  ```python
  @pytest.mark.parametrize("payload", [
      {"dataset_id": "cn.equity.daily", "schema_major": True},
      {"dataset_id": "cn.equity.daily", "schema_major": 1, "limit": "100"},
      {"dataset_id": "cn.equity.daily", "schema_major": 1, "fields": ["close", "close"]},
      {"dataset_id": "cn.equity.daily", "schema_major": 1, "order": []},
      {"dataset_id": "cn.equity.daily", "schema_major": 1, "sql": "select 1"},
  ])
  def test_query_request_rejects_noncanonical_payload(payload): ...

  def test_query_request_accepts_scalar_and_operator_filters(): ...
  def test_query_request_hash_is_key_order_independent(): ...
  def test_access_policy_hash_binds_tenant_scopes_and_exact_dataset_grants(): ...
  ```

  Run and confirm RED:

  ```bash
  uv run --python 3.12 --with-requirements requirements.txt python -m pytest -q \
    tests/test_query_contract.py
  ```

- [ ] **Step 3: Implement strict canonical parsing**

  Use native-type checks (`type(value) is int`, not `isinstance(value, int)`) and reject unknown root keys. Canonicalize only after validation:

  ```python
  _REQUEST_KEYS = frozenset(
      {"dataset_id", "schema_major", "fields", "filters", "as_of", "order", "limit", "cursor"}
  )

  def _native_positive_int(value: object, name: str) -> int:
      if type(value) is not int or value <= 0:
          raise QueryValidationError(f"{name} must be a positive integer")
      return value
  ```

  Parsing must preserve `order=None` when omitted, because the registry—not the caller—owns the default order.

  The normalized query hash excludes the cursor token itself and binds the resolved dataset/schema, effective projection, canonical filters/order/as-of, and all internal execution options. Semantically identical object-key ordering produces the same hash; any result-affecting difference produces another hash.

- [ ] **Step 4: Implement registry query defaults, as-of semantics, and derived catalog version**

  `public_catalog_version()` serializes only provider-neutral public definitions using canonical JSON and returns `v1-` plus at least the first 16 SHA-256 hex characters. It must change when dataset identity/schema/query policy/cadence/SLA/access policy changes, but not expose or depend on absolute paths, credentials, or runtime receipts.

  Set profile `as_of_field`, `as_of_format`, `range_field`, and `partition_field` explicitly only where the stored canonical encoding supports correct comparison. Use `null` for ambiguous or unsupported schemas; do not invent an as-of, date-range, or latest-partition mapping in service code.

  A public `as_of` value must be a timezone-aware RFC3339 timestamp. Normalize it in the dataset timezone, encode it according to `as_of_format`, and apply `as_of_field <= cutoff`. `requested_as_of` echoes the canonical aware request; `resolved_as_of` is the canonical aware cutoff actually applied. Both are null when the request omits `as_of`. Invalid or naive timestamps and unsupported datasets return 400. The normalized query and cursor bind both values. If the caller also filters `as_of_field`, the stricter upper bound wins and is reported as `resolved_as_of`.

  `QueryExecutionOptions.latest_partition` is not a public JSON field. The public parser rejects it. A compatibility adapter may set it only when the registry declares `partition_field`; `QueryService` resolves `MAX(partition_field)` and applies the equality filter inside the same verified SQLite snapshot. The option and resolved partition participate in the normalized query hash and cursor binding.

  `QueryExecutionOptions.any_of_eq_filters` is also compatibility-only. It supports at most four registry-declared filterable fields with equality values, is compiled as one parenthesized OR group after the mandatory fixed dataset filters, and participates in authorization, budgets, normalized query hash, and cursor binding. The public JSON parser cannot set it. This preserves relationship endpoint symbol matching without adding arbitrary public expressions.

- [ ] **Step 5: Freeze the normative API examples**

  Update `API_CONTRACT.md` and add `docs/query_service.md` with the exact request/response shapes above, filter/operator grammar, order grammar, state mapping, cursor invalidation, error codes, and Phase 2 access limitations. Link the new document from `docs/AGENTS.md`.

- [ ] **Step 6: Verify and commit Task 1**

  ```bash
  uv run --python 3.12 --with-requirements requirements.txt python -m pytest -q \
    tests/test_dataset_registry.py tests/test_query_contract.py tests/test_data_platform_docs.py
  uv run --python 3.12 --with-requirements requirements.txt ruff check \
    dataset_registry.py query_contract.py tests/test_dataset_registry.py tests/test_query_contract.py
  uv run --python 3.12 python -m compileall -q dataset_registry.py query_contract.py
  git diff --check
  git add -- \
    query_contract.py dataset_registry.py config/dataset_registry.yaml \
    tests/test_dataset_registry.py tests/test_query_contract.py \
    API_CONTRACT.md docs/query_service.md docs/AGENTS.md
  git diff --cached --name-status
  git commit -m "feat: freeze provider-neutral query contract"
  ```

## Task 2: Implement signed, policy- and snapshot-bound keyset cursors

**Files:**

- Add: `query_cursor.py`
- Add: `tests/test_query_cursor.py`
- Modify: `docs/query_service.md`

**Interfaces:**

```python
class InvalidCursor(ValueError): ...
class CursorMismatch(ValueError): ...

@dataclass(frozen=True)
class CursorClaims:
    kind: str
    catalog_version: str
    dataset_id: str | None
    schema_major: int | None
    query_hash: str
    policy_id: str
    receipt_watermark: str
    sort_key: tuple[object, ...]
    expires_at: int

class SignedCursorCodec:
    def encode(self, claims: CursorClaims) -> str: ...
    def decode(self, token: str, *, expected: CursorExpectation, now: datetime) -> CursorClaims: ...
```

- [ ] **Step 1: Write RED cursor tests**

  Cover canonical round-trip, tampering, truncation, wrong key, expiry, non-native timestamps, cross-kind, cross-catalog, cross-dataset, cross-schema, cross-query, cross-policy, and cross-receipt reuse. The token is integrity-protected, not encrypted: claims may contain the effective keyset sort tuple, including the hidden SQLite rowid tie-breaker, because that value is not an authorization boundary or secret. Claims must never contain any other hidden row payload, internal path, SQL, credential, or provider token. The response `data` never exposes `__ss_rowid`.

  ```python
  def test_cursor_rejects_cross_snapshot_reuse(codec, claims):
      token = codec.encode(claims)
      with pytest.raises(CursorMismatch, match="receipt watermark"):
          codec.decode(token, expected=replace(expectation, receipt_watermark="new"), now=NOW)
  ```

  Run and confirm RED:

  ```bash
  uv run --python 3.12 --with-requirements requirements.txt python -m pytest -q \
    tests/test_query_cursor.py
  ```

- [ ] **Step 2: Implement a versioned HMAC token**

  Use canonical JSON and HMAC-SHA256:

  ```python
  payload = json.dumps(claims_dict, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
  signature = hmac.new(secret, payload, hashlib.sha256).digest()
  token = f"{b64url(payload)}.{b64url(signature)}"
  ```

  `SignedCursorCodec.from_env()` requires `SHAREDSIGNALS_CURSOR_SIGNING_KEY` of at least 32 UTF-8 bytes. No committed/default secret is allowed. Missing/weak configuration raises a service-unavailable error only when V1/legacy query service is invoked; it must not break unrelated process startup.

- [ ] **Step 3: Map invalid versus mismatch semantics**

  Malformed, invalid signature, unsupported version, and expired tokens map to HTTP 400. A valid token bound to another catalog/dataset/schema/query/policy/receipt maps to HTTP 409.

- [ ] **Step 4: Verify and commit Task 2**

  ```bash
  uv run --python 3.12 --with-requirements requirements.txt python -m pytest -q \
    tests/test_query_cursor.py tests/test_query_contract.py
  uv run --python 3.12 --with-requirements requirements.txt ruff check \
    query_cursor.py tests/test_query_cursor.py
  uv run --python 3.12 python -m compileall -q query_cursor.py
  git diff --check
  git add -- query_cursor.py tests/test_query_cursor.py docs/query_service.md
  git diff --cached --name-status
  git commit -m "feat: add signed query cursors"
  ```

## Task 3: Build `CatalogService` from registry plus one SQLite runtime snapshot

**Files:**

- Add: `catalog_service.py`
- Add: `tests/test_catalog_service.py`

**Interfaces:**

```python
class CatalogService:
    def list_datasets(
        self,
        *,
        access: QueryAccessContext,
        filters: CatalogFilters,
        limit: int,
        cursor: str | None,
        now: datetime,
        request_id: str,
    ) -> dict[str, object]: ...
```

- [ ] **Step 1: Write RED catalog visibility and projection tests**

  Build a temporary SQLite fixture with registry receipts and assert:

  - filters are limited to `market`, `domain`, `cadence`, `state`, `q`, `cursor`, and `limit`, with `q` bounded by `max_catalog_search_chars`;
  - datasets outside the access scopes are absent, not redacted rows;
  - excluded first-release markets are absent;
  - locked/unknown/paused domestic datasets remain discoverable with honest availability;
  - success/empty/unobserved/paused/failed/stale remain distinguishable;
  - storage table, path, SQL, adapter version, token, and raw receipt payload never appear;
  - page 1/page 2 have no duplicates or gaps;
  - a receipt/runtime change invalidates the prior cursor with `CursorMismatch`;
  - one service call invokes `project_registry_runtime()` once in one verified snapshot;
  - datasets that cannot satisfy the generic rowid/query contract are honestly marked non-queryable instead of advertising an unusable lane.

- [ ] **Step 2: Implement tenant-visible rows and the catalog watermark**

  Sort visible definitions by `dataset_id`. Compute the catalog receipt watermark from canonical sorted tuples of `(dataset_id, state, receipt_id, data_through, observed_at)` returned by that same projection. Sign a cursor containing the last dataset ID only when more rows exist.

- [ ] **Step 3: Keep catalog data provider-neutral**

  Provider names may appear only as objective lineage names. Internal `primary_table`, fixed provider discriminators, adapter versions, DB paths, and provider API credentials must not be serialized.

- [ ] **Step 4: Verify and commit Task 3**

  ```bash
  SHAREDSIGNALS_CURSOR_SIGNING_KEY='phase2-test-signing-key-32-bytes-minimum' \
  uv run --python 3.12 --with-requirements requirements.txt python -m pytest -q \
    tests/test_catalog_service.py tests/test_receipt_projection.py tests/test_dataset_registry.py
  uv run --python 3.12 --with-requirements requirements.txt ruff check \
    catalog_service.py tests/test_catalog_service.py
  uv run --python 3.12 python -m compileall -q catalog_service.py
  git diff --check
  git add -- catalog_service.py tests/test_catalog_service.py
  git diff --cached --name-status
  git commit -m "feat: expose the provider-neutral catalog service"
  ```

## Task 4: Build the bounded single-snapshot `QueryService`

**Files:**

- Add: `query_service.py`
- Add: `tests/test_query_service.py`
- Modify: `storage/receipt_projection.py`
- Modify: `tests/test_receipt_projection.py`

**Interfaces:**

```python
class QueryService:
    def execute(
        self,
        request: QueryRequest,
        *,
        access: QueryAccessContext,
        now: datetime,
        request_id: str,
        options: QueryExecutionOptions = QueryExecutionOptions(),
    ) -> dict[str, object]: ...
```

- [ ] **Step 1: Write RED authorization and query-policy tests**

  Assert 404 for an unknown, excluded, or structurally undiscoverable dataset; assert 403 for a known and initial-release-eligible dataset that is omitted from the catalog only because the caller lacks its required query scope. Assert 400 for schema-major mismatch, nonselectable fields, nonfilterable fields, invalid operator/type, invalid order, unsupported/naive as-of, and reversed between bounds. Assert 413 for selected-field/filter/`in`/order/page/lookback budgets. Assert raw SQL/table/provider/token fields cannot reach SQLite.

  Add supported-as-of positive tests for `yyyymmdd` and `rfc3339` profiles: cross-timezone normalization into the registry timezone, inclusive `<=` behavior, canonical `requested_as_of` and `resolved_as_of`, stricter explicit upper-bound precedence, and exclusion of rows beyond the resolved cutoff.

- [ ] **Step 2: Write RED same-snapshot metadata tests**

  In one WAL fixture, update facts and receipts between controlled connection points. Assert each response is either old-facts+old-receipt or new-facts+new-receipt, never mixed. Assert missing/invalid receipt does not become healthy because rows exist.

  Include these state cases:

  ```python
  @pytest.mark.parametrize(
      ("runtime_state", "top_state", "degraded", "returns_rows"),
      [
          ("success", "ready", False, True),
          ("empty", "empty", False, False),
          ("unobserved", "unobserved", True, False),
          ("paused", "paused", True, False),
          ("failed", "failed", True, True),
          ("stale", "stale", True, True),
      ],
  )
  def test_query_state_matrix(...): ...
  ```

  A failed dataset returns rows only when the projection proves prior successful data through a non-null watermark; otherwise it returns an empty degraded response.

- [ ] **Step 3: Write RED keyset pagination tests**

  Cover equal timestamps/symbols, nullable sort fields, ascending/descending terms, hidden primary-key/rowid tie-breakers, page-size `limit + 1`, no duplicates/gaps, cursor query mismatch, cursor policy mismatch, and cursor receipt mismatch.

  Also cover internal latest-partition execution: the `MAX(partition_field)` resolution and row query occur on the same connection/snapshot, explicit caller filters and fixed registry filters constrain the maximum, the public JSON parser cannot request the option, and the resolved partition is bound into the cursor/query hash. Cover the compatibility-only `any_of_eq_filters` group with registry field validation, placeholder binding, maximum four terms, fixed-filter precedence, and cursor/query-hash binding. A cursor created with one requested/resolved as-of pair must fail with `CursorMismatch` when reused under another pair.

- [ ] **Step 4: Compile only registry-owned SQL**

  Validate the table through `PRAGMA table_list`, validate columns through `PRAGMA table_xinfo`, and require an ordinary rowid table for the Phase 2 generic engine. Identifiers are selected only from validated registry fields; values always use placeholders. Always apply registry-owned fixed field filters and provider discriminator values before caller filters so datasets sharing one physical table cannot leak rows across provider or dataset boundaries.

  Effective order is:

  ```python
  explicit_or_primary_key_order
  + missing_primary_key_terms
  + ("__ss_rowid:asc",)
  ```

  Use a null-rank expression so nullable fields sort deterministically with nulls last. Cursor claims store null markers and values; `__ss_rowid` is never returned in `data`.

- [ ] **Step 5: Enforce resource and time bounds**

  Apply registry field/filter/list/order/page/lookback limits before opening SQLite. Install a SQLite progress handler using the registry step budget and translate interruption to service-unavailable/capacity error. Fetch at most `limit + 1` rows. Reject explicit range requests that exceed the effective lookback policy. Serialize with `allow_nan=False`, reject/degrade non-finite stored values instead of emitting invalid JSON, and enforce `max_response_bytes` before writing an HTTP response.

- [ ] **Step 6: Return complete metadata from the same snapshot**

  Reuse `project_dataset_runtime(conn, dataset, now=..., registry=...)` on the same connection. Add only the minimal public helper in `storage/receipt_projection.py` if necessary to expose the exact receipt/provider validation evidence; do not add a JSON authority, second connection, or second scan.

  Convert public evidence as follows:

  ```python
  top_state = "ready" if projection.state == "success" and not projection.degraded else projection.state
  freshness_state = "fresh" if projection.state == "success" else projection.state
  quality_state = "valid" if projection.state in {"success", "empty"} else "degraded"
  ```

  Lineage must include `state`, `complete`, `provider_neutral`, authority, dataset ID, providers, and receipt watermark. Healthy responses require all source proof; otherwise fail closed.

- [ ] **Step 7: Verify and commit Task 4**

  ```bash
  SHAREDSIGNALS_CURSOR_SIGNING_KEY='phase2-test-signing-key-32-bytes-minimum' \
  uv run --python 3.12 --with-requirements requirements.txt python -m pytest -q \
    tests/test_query_service.py tests/test_query_cursor.py \
    tests/test_receipt_projection.py tests/test_read_model_store.py
  uv run --python 3.12 --with-requirements requirements.txt ruff check \
    query_service.py storage/receipt_projection.py \
    tests/test_query_service.py tests/test_receipt_projection.py
  uv run --python 3.12 python -m compileall -q query_service.py storage/receipt_projection.py
  git diff --check
  git add -- \
    query_service.py storage/receipt_projection.py \
    tests/test_query_service.py tests/test_receipt_projection.py
  git diff --cached --name-status
  git commit -m "feat: add bounded single-snapshot queries"
  ```

## Task 5: Expose the two fixed HTTP routes without weakening authorization

**Files:**

- Add: `data_plane_runtime.py`
- Modify: `api_server.py`
- Modify: `auth.py`
- Add: `tests/test_v1_api.py`
- Modify: `tests/test_api_server_edge.py`
- Modify: `tests/test_auth_security.py`
- Modify: `docs/query_service.md`

**Interfaces:**

```python
def build_data_plane_services() -> tuple[CatalogService, QueryService]: ...
def parse_json_body(raw: bytes, *, max_bytes: int) -> object: ...
```

- [ ] **Step 1: Write RED HTTP body and route-set tests**

  Prove that:

  - the only new public data routes are `GET /v1/catalog` and `POST /v1/query`;
  - `POST /v1/query` accepts only `application/json` with optional UTF-8 charset, requires one valid bounded `Content-Length`, rejects transfer encoding, enforces the registry byte limit before JSON decoding, rejects duplicate keys and non-finite numbers, and does not log or echo the raw body;
  - `GET /v1/catalog` accepts only its fixed filter set and parses `limit` only from canonical ASCII decimal text (`1` through the effective maximum); signs, whitespace, decimals, exponent notation, leading zeroes, and booleans are invalid;
  - adding a registry dataset or provider does not add another route;
  - `do_POST()` no longer discards the V1 body;
  - V1 routes bypass the legacy path+params response cache and request deduplication.

  Run and confirm RED:

  ```bash
  SHAREDSIGNALS_CURSOR_SIGNING_KEY='phase2-test-signing-key-32-bytes-minimum' \
  uv run --python 3.12 --with-requirements requirements.txt python -m pytest -q \
    tests/test_v1_api.py tests/test_api_server_edge.py
  ```

- [ ] **Step 2: Write RED authentication and error-envelope tests**

  Use the real auth middleware, not the full-access test double. Cover 401 for missing/invalid credentials, 403 for missing dataset scope, and tenant-bound `QueryAccessContext` construction. Assert that the handler passes the authenticated account into catalog/query dispatch and never shares V1 cache entries across different policy IDs.

  Freeze this error mapping:

  | HTTP | Condition |
  |---|---|
  | 400 | malformed body, invalid request, invalid signature, expired cursor |
  | 401 | unauthenticated |
  | 403 | direct query for a known and initial-release-eligible dataset that is omitted from the catalog only because its required query scope is missing; Phase 4 later adds field/lookback tenant policy |
  | 404 | unknown, excluded, or structurally undiscoverable dataset |
  | 409 | valid cursor bound to another catalog/query/policy/receipt |
  | 413 | body, selected-field/filter/list/order/page/lookback, or result budget exceeded |
  | 429 | existing rate or concurrency limit exceeded |
  | 503 | missing read model/signing key or SQLite capacity interruption |
  | 500 | unexpected internal failure with no path, SQL, stack trace, or secret disclosure |

- [ ] **Step 3: Implement lazy data-plane construction**

  Build registry, verified read-model binding, and cursor codec only when a V1 or migrated compatibility request is invoked. A missing signing key must make those routes return 503 without preventing unrelated health/process startup.

  `parse_json_body()` must use `json.loads(..., object_pairs_hook=...)`, reject duplicate keys recursively, and reject `NaN`, `Infinity`, and `-Infinity`. Do not accept form data or query-string fallbacks for `POST /v1/query`.

- [ ] **Step 4: Pass the authenticated account into dispatch**

  Convert the current account to the minimal Phase 2 access context. Add endpoint scopes for `/v1/catalog` and `/v1/query`, then let the registry required scope decide dataset visibility and query permission. A known and initial-release-eligible dataset remains absent from the catalog when its required query scope is missing, but a direct query to that dataset returns 403; an unknown, excluded, or structurally undiscoverable dataset returns 404. Preserve legacy compatibility explicitly: an authenticated request entering through `/tushare` with the existing `tushare` scope receives one request-local `allowed_dataset_ids=(resolved_dataset_id,)` grant; a `fundamentals`-scoped request entering through `/reference?table=stock_master` receives only `cn.equity.security_master`. Each `policy_id` binds the exact grant, and neither request can discover the catalog or query another dataset. Add real-auth regressions for both legacy-only credentials. Do not implement Phase 4 keys, billing, persistent quotas, revocation, or field-level tenant policy here.

  Freeze the V1 error envelope as:

  ```json
  {
    "api_version": "v1",
    "request_id": "123e4567-e89b-42d3-a456-426614174000",
    "error": {"code": "invalid_request", "message": "request is invalid", "retryable": false}
  }
  ```

  Error messages are bounded public text and never contain a stack trace, SQL, database path, credential, raw request body, or internal exception representation.

- [ ] **Step 5: Verify and commit Task 5**

  ```bash
  SHAREDSIGNALS_CURSOR_SIGNING_KEY='phase2-test-signing-key-32-bytes-minimum' \
  uv run --python 3.12 --with-requirements requirements.txt python -m pytest -q \
    tests/test_v1_api.py tests/test_api_server_edge.py tests/test_auth_security.py \
    tests/test_catalog_service.py tests/test_query_service.py
  uv run --python 3.12 --with-requirements requirements.txt ruff check \
    data_plane_runtime.py api_server.py auth.py \
    tests/test_v1_api.py tests/test_api_server_edge.py tests/test_auth_security.py
  uv run --python 3.12 python -m compileall -q \
    data_plane_runtime.py api_server.py auth.py
  git diff --check
  git add -- \
    data_plane_runtime.py api_server.py auth.py \
    tests/test_v1_api.py tests/test_api_server_edge.py tests/test_auth_security.py \
    docs/query_service.md
  git diff --cached --name-status
  git commit -m "feat: expose the fixed V1 data routes"
  ```

## Task 6: Migrate `/tushare` and `stock_master` reference reads to pure compatibility adapters

**Files:**

- Add: `legacy_query_compat.py`
- Add: `tests/test_legacy_query_compat.py`
- Modify: `data_plane_runtime.py`
- Modify: `api_server.py`
- Modify: `reader.py`
- Modify: `tests/test_reader.py`
- Modify: `tests/test_api_server_edge.py`
- Modify: `tools/health_check.py`
- Modify: `tools/capability_scan.py`
- Modify: `tests/test_capability_scan.py`
- Modify: `API_CONTRACT.md`
- Modify: `docs/query_service.md`
- Modify: `docs/external_agent_api_prompt.md`
- Modify: `docs/market_capability_matrix.md`

**Interfaces:**

```python
@dataclass(frozen=True)
class LegacyQueryInvocation:
    request: QueryRequest
    options: QueryExecutionOptions

class LegacyQueryCompat:
    def tushare_request(self, params: Mapping[str, str]) -> LegacyQueryInvocation: ...
    def stock_master_request(self, params: Mapping[str, str]) -> LegacyQueryInvocation: ...
    def legacy_envelope(self, query_envelope: Mapping[str, object]) -> dict[str, object]: ...

@dataclass(frozen=True)
class DataPlaneRuntime:
    registry: DatasetRegistry
    cursor_codec: SignedCursorCodec
    catalog: CatalogService
    query: QueryService
    legacy: LegacyQueryCompat
    services: tuple[CatalogService, QueryService]
```

- [ ] **Step 1: Freeze the compatibility behavior matrix**

  Capture current response/error semantics and the explicitly approved correctness changes for:

  - `/tushare?api_name=daily` with symbol/date filters, internal latest-partition behavior, order, and limit;
  - `/tushare` success, empty, unobserved, paused, failed, and stale receipt states;
  - one representative alias for every registry schema profile: `daily`, `weekly`, `stock_basic`, `daily_basic`, `broker_recommend`, `news`, `concept_detail`, and `fund_portfolio`;
  - one parameterized contract test over every imported `tushare.*` alias proving it resolves exactly one active registry definition or returns its honest locked/excluded state, uses only declared fields/options, and never falls back to the old API-to-table map;
  - relationship subject/object OR semantics, asset/provider alias isolation, each profile's canonical date field, fixed registry filters, and default projection;
  - `/reference?table=stock_master` mapping only to `cn.equity.security_master`, with default/maximum limit 500, signed cursor, deterministic order, receipt metadata, and no CSV/file fallback;
  - `stock_master` success, empty, unobserved, paused, failed, and stale receipt behavior;
  - multi-row metadata retaining runtime state, data-through, observed-at, quality evidence, and receipt lineage;
  - every one of the 114 `tushare.*` aliases resolving to exactly one registry definition or returning its honest excluded/locked state;
  - strict canonical `limit` parsing in the range 1..500, signed cursor continuation, and HTTP 413 for every value above 500;
  - two-tenant requests proving the migrated routes bypass the legacy response cache whose key omits tenant/policy state.

  Preserve relationship subject/object OR matching through `any_of_eq_filters`. Deliberately stop mixing `tushare_stock_company` rows into either the `tushare.stock_basic` alias or `stock_master`: both resolve only `cn.equity.security_master` and its registry fixed provider discriminator. These corrections must be documented and tested; they are not silent parity claims. The matrix is not permission to retain the legacy SQL implementation.

- [ ] **Step 2: Write RED no-independent-reader tests**

  Monkeypatch `_query_tushare_rows`, `_sqlite_rows`, `_connect_sqlite_ro`, request-time provider functions, and file fallbacks to raise if the migrated routes touch them. Assert both routes still work by calling the same `QueryService` instance and therefore use the same snapshot, cursor, metadata, authorization, and resource policy.

  Add RED tests that the lazy runtime publishes one immutable `DataPlaneRuntime`: registry, cursor codec, catalog, query, legacy adapter, and the backward-compatible `(CatalogService, QueryService)` tuple are constructed once and shared by `api_server.py` and `reader.py`. Resetting the test runtime invalidates the complete bundle under one lock; partial construction is never published.

  Add RED tests that `/tushare` and only `/reference?table=stock_master` bypass the old response cache. A cursor or envelope produced for one tenant/policy must never be returned to another tenant. Other legacy endpoints retain their existing cache behavior in this task.

  Run and confirm RED:

  ```bash
  SHAREDSIGNALS_CURSOR_SIGNING_KEY='phase2-test-signing-key-32-bytes-minimum' \
  uv run --python 3.12 --with-requirements requirements.txt python -m pytest -q \
    tests/test_legacy_query_compat.py tests/test_reader.py tests/test_api_server_edge.py
  ```

- [ ] **Step 3: Implement translation only**

  The compatibility module may normalize aliases, legacy parameter names, schema-profile symbol fields, registry `range_field`, date formats, limits, legacy error codes, and the old envelope shape. Relationship symbol matching uses the bounded `any_of_eq_filters` option. It may not contain SQL, table names, database paths, provider calls, file reads, independent cursors, or independent metadata aggregation.

  Implement `build_data_plane_runtime()` as the sole lazy constructor and keep `build_data_plane_services()` as a backward-compatible view that returns the same tuple identity on every call. Neither the API server nor reader may reload the registry, access private `QueryService` attributes, or construct another cursor/query service.

  `/tushare` resolves `tushare.<api_name>` through the registry. The compatibility scope grant never overrides registry exclusion or the initial domestic-market visibility rule. When a legacy API omits its date window and its registry profile declares `partition_field`, the adapter sets `QueryExecutionOptions.latest_partition=True`; resolution stays inside `QueryService` and the same verified snapshot. The adapter cannot invent a partition field or run a separate `MAX()` connection.

  `/reference?table=stock_master` maps to `cn.equity.security_master` and the registry default projection. Any other legacy reference table remains unchanged in this phase and must not be mislabeled as migrated. Missing data or receipt authority remains explicit degraded/empty data; no CSV or file fallback is allowed.

  Keep `/market_data`, `/events`, `/is_trading_day`, non-`stock_master` reference tables, and SW2021 routes unchanged in this task. Their provider ownership, canonical-field, or composite-query gaps are recorded for later compatibility migration; do not pretend that they already use V1. In particular, `trade_cal` must first gain a canonical queryable calendar-date mapping and backfill before `/is_trading_day` can leave its legacy implementation.

- [ ] **Step 4: Remove the migrated independent SQL path**

  Make `reader.get_tushare()` and the `stock_master` branch of `reader.get_reference()` compatibility wrappers over the same lazily constructed service from `data_plane_runtime.py`. Tests may inject the runtime through an explicit private dependency hook. Keep the callable names and parameter names, but change the legacy default and maximum page size to 500 and expose the signed continuation cursor in the existing response metadata; values above 500 fail explicitly. Delete or retire `_query_tushare_rows`, the migrated `stock_master` direct-SQL branch, and only the now-unreachable migrated SQL helpers after import/call-site tests prove they have no remaining consumer. Never construct a second query engine or hide pagination inside the adapter.

  Update SharedSignals' health/capability smoke calls and migration documents so they request at most one 500-row page and never claim that one response is a complete stock universe. Replace the 6,000/10,000 compatibility promise with the cursor contract. These tools are health probes only; they must not aggregate a universe or become another query engine.

- [ ] **Step 5: Verify and commit Task 6**

  ```bash
  SHAREDSIGNALS_CURSOR_SIGNING_KEY='phase2-test-signing-key-32-bytes-minimum' \
  uv run --python 3.12 --with-requirements requirements.txt python -m pytest -q \
    tests/test_legacy_query_compat.py tests/test_reader.py tests/test_api_server_edge.py \
    tests/test_v1_api.py tests/test_query_service.py tests/test_capability_scan.py
  uv run --python 3.12 --with-requirements requirements.txt ruff check \
    data_plane_runtime.py legacy_query_compat.py api_server.py reader.py \
    tools/health_check.py tools/capability_scan.py \
    tests/test_legacy_query_compat.py tests/test_reader.py tests/test_api_server_edge.py \
    tests/test_capability_scan.py
  uv run --python 3.12 python -m compileall -q \
    data_plane_runtime.py legacy_query_compat.py api_server.py reader.py \
    tools/health_check.py tools/capability_scan.py
  git diff --check
  git add -- \
    data_plane_runtime.py legacy_query_compat.py api_server.py reader.py \
    tools/health_check.py tools/capability_scan.py \
    tests/test_legacy_query_compat.py tests/test_reader.py tests/test_api_server_edge.py \
    tests/test_capability_scan.py API_CONTRACT.md docs/query_service.md \
    docs/external_agent_api_prompt.md docs/market_capability_matrix.md
  git diff --cached --name-status
  git commit -m "refactor: route legacy data reads through V1"
  ```

  A local Task 6 PASS does not authorize production release. TradingAgent's 5,000-row `/tushare` reader and every MarketGraph/SharedSignals consumer that assumes a non-paged `stock_master` response must first migrate to V1 signed-cursor exhaustion and preserve per-page metadata. Until those cross-repository tests pass, the release gate remains NO-GO.

## Task 7: Freeze the consumer contract and anti-drift documentation

**Files:**

- Add: `tests/fixtures/sharedsignals_v1_query_contract.json`
- Add: `tests/test_v1_contract_fixture.py`
- Modify: `README.md`
- Modify: `API_CONTRACT.md`
- Modify: `docs/query_service.md`
- Modify: `docs/data_source_onboarding.md`
- Add: `docs/data_contract.md`
- Modify: `STATUS.md`
- Modify: `tests/test_data_platform_docs.py`

- [ ] **Step 1: Add a provider-neutral contract fixture**

  Store one exact catalog row, one healthy query response, and one degraded query response using only V1 public fields. The fixture is the handoff artifact for TradingAgent and other consumers; SharedSignals tests validate it locally without importing TradingAgent or MarketGraph code.

- [ ] **Step 2: Add anti-drift tests**

  Prove that core docs and the fixture agree on:

  - exactly two target public data routes;
  - provider-neutral dataset IDs and independent dataset schema versions;
  - one SQLite snapshot for rows plus metadata;
  - non-empty freshness, quality, and lineage metadata;
  - no strategy/opening/capital/position/risk/order/fill responsibility in SharedSignals;
  - no new route when a provider or dataset is added;
  - legacy routes are compatibility adapters, not a second query engine;
  - local PASS, local main, origin/GitHub, production runtime, external route, and real dataset evidence remain separate.

- [ ] **Step 3: Update current truth and consumer handoff**

  `STATUS.md` records exact local candidate commits/tests and clearly says origin/GitHub/production/external route/real datasets are unchanged. `docs/data_contract.md` gives TradingAgent the exact request and response envelope, state mapping, cursor semantics, and the rule that consumers must fail closed or down-weight from per-dataset metadata instead of relying on HTTP 200 or a global source flag.

  `docs/data_source_onboarding.md` must state that provider onboarding completes the full existing chain: registry and schema, entitlement/activation evidence, storage mapping, canonical normalization/validation/deduplication, facts plus receipt in the same SQLite transaction, query/metadata contract, focused and full tests, and current documentation. These changes still do not add a public API route.

- [ ] **Step 4: Verify and commit Task 7**

  ```bash
  uv run --python 3.12 --with-requirements requirements.txt python -m pytest -q \
    tests/test_v1_contract_fixture.py tests/test_data_platform_docs.py
  uv run --python 3.12 --with-requirements requirements.txt ruff check \
    tests/test_v1_contract_fixture.py tests/test_data_platform_docs.py
  uv run --python 3.12 python -m json.tool \
    tests/fixtures/sharedsignals_v1_query_contract.json >/dev/null
  git diff --check
  git add -- \
    tests/fixtures/sharedsignals_v1_query_contract.json tests/test_v1_contract_fixture.py \
    README.md API_CONTRACT.md docs/query_service.md docs/data_source_onboarding.md \
    docs/data_contract.md STATUS.md tests/test_data_platform_docs.py
  git diff --cached --name-status
  git commit -m "docs: freeze the V1 consumer contract"
  ```

## Task 8: Run final verification, independent review, and local-main integration

**Files:**

- Modify only if verification finds an in-scope defect in a file already owned by Tasks 1–7.
- Evidence output: a fresh directory under `/private/tmp/` containing JUnit XML, manifest, file hashes, test logs, and review reports.

- [ ] **Step 1: Run the focused union from final bytes**

  ```bash
  SHAREDSIGNALS_CURSOR_SIGNING_KEY='phase2-test-signing-key-32-bytes-minimum' \
  uv run --python 3.12 --with-requirements requirements.txt python -m pytest -q \
    tests/test_query_contract.py tests/test_query_cursor.py \
    tests/test_catalog_service.py tests/test_query_service.py \
    tests/test_v1_api.py tests/test_legacy_query_compat.py \
    tests/test_dataset_registry.py tests/test_receipt_projection.py \
    tests/test_read_model_store.py tests/test_reader.py \
    tests/test_api_server_edge.py tests/test_auth_security.py \
    tests/test_v1_contract_fixture.py tests/test_data_platform_docs.py
  ```

- [ ] **Step 2: Run the complete Python 3.12 suite and static gates**

  ```bash
  SHAREDSIGNALS_CURSOR_SIGNING_KEY='phase2-test-signing-key-32-bytes-minimum' \
  uv run --python 3.12 --with-requirements requirements.txt python -m pytest -q \
    --junitxml=/private/tmp/sharedsignals-phase2-full-junit.xml
  uv run --python 3.12 --with-requirements requirements.txt ruff check \
    query_contract.py query_cursor.py catalog_service.py query_service.py \
    data_plane_runtime.py legacy_query_compat.py dataset_registry.py \
    storage/receipt_projection.py api_server.py auth.py reader.py \
    tests/test_query_contract.py tests/test_query_cursor.py \
    tests/test_catalog_service.py tests/test_query_service.py \
    tests/test_v1_api.py tests/test_legacy_query_compat.py \
    tests/test_v1_contract_fixture.py tests/test_data_platform_docs.py
  uv run --python 3.12 python -m compileall -q .
  git diff --check
  ```

  Record any unrelated pre-existing lint exception explicitly; do not silently widen the lint scope or claim a gate that was not run.

- [ ] **Step 3: Run the adversarial acceptance matrix**

  Re-run from a clean overlay:

  - malformed/duplicate/oversized JSON, invalid content length/transfer encoding, and native-type confusion;
  - SQL/table/provider/credential injection attempts;
  - fixed-filter/provider-discriminator bypass across datasets sharing one physical table;
  - field/operator/order/lookback/page budget violations;
  - supported as-of timezone normalization, both storage encodings, explicit-bound precedence, and cross-as-of cursor rejection;
  - signed-cursor tamper/expiry/cross-dataset/schema/query/policy/receipt reuse;
  - equal/nullable keyset pagination without duplicate or missing rows;
  - missing/drifted DB/table/column/receipt/binding and interrupted SQLite capacity;
  - non-finite stored values and response-byte budget overflow without invalid JSON or partial HTTP output;
  - all six runtime states with honest HTTP 200 degraded metadata;
  - no provider/file fallback and no independent SQL in migrated legacy routes;
  - exact public route set and no excluded-market activation;
  - no SharedSignals import/callback/shared DB with TradingAgent or MarketGraph.

- [ ] **Step 4: Freeze exact candidate evidence**

  Produce:

  - base and head SHAs, commit list, tracked/untracked/staged status;
  - exact changed-file manifest and per-file SHA-256;
  - full diff SHA-256 and aggregate content SHA-256;
  - JUnit/test/static logs and their SHA-256 values;
  - documentation/current-state readback;
  - explicit non-actions: no push, production, cron, provider call, DB migration, email, or trading.

- [ ] **Step 5: Require independent clean-overlay review**

  The reviewer must return both spec-compliance and code-quality verdicts. Any reproducible in-scope P0/P1 returns to the owning task and invalidates the freeze. P2/backlog findings are recorded in `STATUS.md` and do not silently expand Phase 2.

- [ ] **Step 6: Integrate only to local main**

  After final PASS, independently audit the exact diff and then fast-forward the isolated branch into local `main`. Read back local `main`, rerun the focused contract smoke, and verify tracked/index clean with `.codegraphcontext/` untouched. Do not push or deploy in this plan.

## Parallelization and ownership

- Task 1 owns the public contract, registry policy, and `docs/query_service.md`; Task 2 starts only after Task 1 review is clean, so their shared documentation path remains single-writer.
- Tasks 3 and 4 are separate serial implementation commits after Tasks 1–2; both consume the same registry/cursor interfaces and must not invent alternatives. Read-only review preparation may run in parallel, but implementation writers may not.
- Task 5 begins only after Tasks 3–4 are reviewed. Task 6 begins after Task 5 because it must reuse the live QueryService construction and authenticated context.
- Task 7 begins after Task 6 because it owns the final `API_CONTRACT.md`, `docs/query_service.md`, fixture, and `STATUS.md` wording. Read-only consumer checks may run in parallel; document writers may not.
- Task 8 is serial and belongs to the primary integrator plus fresh independent reviewers.

## Stop, rollback, and handoff rules

- Stop immediately for unknown worktree ownership, unexpected staged files, DB/schema migration, provider/network requirement, secret exposure, production dependency, or a second structural P1 round in the same task.
- Rollback at this stage is Git-only: the Phase 2 branch/worktree can be retained or removed after evidence is sealed because no database or production state is changed. Do not remove the accepted Phase 1 branch/worktree until local-main and rollback evidence are both verified.
- A successful Phase 2 handoff contains exact commits, files, tests, hashes, consumer fixture, remaining legacy migration inventory, and the explicit statement that origin/GitHub/production/external route/real datasets are still unverified.
- Phase 3 may start only after the local V1 query contract is accepted. Phase 4 remains the owner of real tenant credentials, field/lookback policy, persistent quota, usage accounting, and gateway Beta validation.

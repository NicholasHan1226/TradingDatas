# SharedSignals Stock Basic and Daily Provider Contracts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `stock_basic` and `daily` to the provider-native target registry through the same Tushare adapter, SQLite fact/receipt authority, and fixed V1 catalog/query API already proven by `trade_cal`.

**Architecture:** Extend the existing declarative response-completeness contract with two provider-neutral strategies: a unique-primary-key current snapshot and a unique-primary-key single-date partition. The compiler, runtime registry, and generic ingest validator interpret those strategies; the two Tushare datasets are then pure contract-bundle/config entries. No dataset-specific collector, table, route, query branch, scheduler, TradingAgent rule, or MarketGraph rule is allowed.

**Tech Stack:** Python 3.12, dataclasses, PyYAML, SQLite, pytest, Ruff.

## Global Constraints

- Base is exact SharedSignals GitHub commit `4d3da591f85989441a552d181eb7a139541948d8`.
- Public data routes remain exactly `GET /v1/catalog` and `POST /v1/query`.
- Tushare remains one generic `api_name + params + fields -> fields/items` transport.
- `stock_basic` maps to `cn.equity.security_master`; `daily` maps to `cn.equity.daily`.
- `stock_basic` initial request is all exchanges with `list_status=L`; no consumer board filter belongs in SharedSignals.
- `daily` uses one explicit `trade_date` partition per attempt; legal empty remains an explicit `empty` receipt, never fake success.
- A response at the documented provider row cap is fail-closed as possibly truncated.
- Provider-native payload remains lossless; field manifests control discovery/query, not field rewriting.
- Both ordinary Tushare bindings keep `requested_fields: []`; the generic
  collector/transport must preserve `None` and omit the `fields` key from the
  actual Tushare HTTP JSON so unknown provider fields remain observable.
- No schema migration, production write, service/cron/nginx change, external route, secret, real email, broker, or trading action.
- Industry classification/membership, `sw_daily`, Beta gateway/auth, and production release are outside this candidate.

---

### Task 1: Generalize request-window and response-completeness contracts

**Files:**
- Modify: `tests/test_compile_provider_native_registry.py`
- Modify: `tests/test_provider_native_registry.py`
- Modify: `dataset_registry.py`
- Modify: `tools/compile_provider_native_registry.py`

**Interfaces:**
- Consumes: existing `RequestWindowPolicy`, `ResponseCompletenessPolicy`, upstream YAML contract, and generated provider-native registry.
- Produces: strategy names `unique_primary_key_snapshot` and `single_partition_unique_primary_key`; optional `partition_field` and `request_partition_key`; common `fixed_field_matches` and `reject_at_row_limit`.

- [ ] **Step 1: Write compiler and registry RED tests**

Add tests that construct these exact policy shapes and initially fail because the current parser only accepts `one_row_per_calendar_date`:

```python
snapshot = {
    "strategy": "unique_primary_key_snapshot",
    "fixed_field_matches": {},
    "reject_at_row_limit": True,
}
partition = {
    "strategy": "single_partition_unique_primary_key",
    "partition_field": "trade_date",
    "request_partition_key": "trade_date",
    "fixed_field_matches": {},
    "reject_at_row_limit": True,
}
```

Assert all of the following:

```python
assert snapshot_binding.request_window_policy is None
assert snapshot_binding.response_completeness.strategy == "unique_primary_key_snapshot"
assert snapshot_binding.response_completeness.reject_at_row_limit is True
assert partition_binding.request_window_policy.range_start_key == "trade_date"
assert partition_binding.request_window_policy.range_end_key == "trade_date"
assert partition_binding.response_completeness.partition_field == "trade_date"
assert partition_binding.response_completeness.request_partition_key == "trade_date"
```

Also add negative tests for unsupported strategy, wrong/missing strategy keys,
snapshot with a window, partition without its single-key window, partition field
absent from the primary key, `reject_at_row_limit` not boolean, and an explicit
non-empty `requested_fields` projection omitting a primary-key/fixed/partition
field. Add report tests proving a snapshot renders
`request_window_fields: []`, while the existing calendar and new partition
contracts retain their declared window fields.

- [ ] **Step 2: Run the new parser/compiler tests and verify RED**

Run:

```bash
uv run --python 3.12 --with-requirements requirements.txt \
  python -m pytest -q \
  tests/test_compile_provider_native_registry.py \
  tests/test_provider_native_registry.py
```

Expected: failures that name unsupported completeness strategies, same start/end request-window keys, and unknown strategy-specific keys.

- [ ] **Step 3: Implement the minimal generic contract model**

Change `ResponseCompletenessPolicy` to expose these exact fields:

```python
@dataclass(frozen=True)
class ResponseCompletenessPolicy:
    strategy: str
    fixed_field_matches: Mapping[str, str]
    reject_at_row_limit: bool
    date_field: str | None = None
    request_start_key: str | None = None
    request_end_key: str | None = None
    partition_field: str | None = None
    request_partition_key: str | None = None
```

Make compiler and runtime parsing strategy-aware:

- `one_row_per_calendar_date` requires the existing date/start/end keys;
- `unique_primary_key_snapshot` requires no request-window policy and no date/partition keys;
- `single_partition_unique_primary_key` requires one `yyyymmdd` request key with `range_start_key == range_end_key == request_partition_key`, `max_span_days=1`, and `partition_field` equal to the dataset `as_of/range/partition` field;
- every strategy derives uniqueness from the dataset primary key rather than repeating keys in YAML;
- fixed row fields and all primary-key/partition fields must be declared;
  identity and partition fields remain non-null in the registry contract, but
  runtime payload drift is handled by the existing degraded identity fallback;
  when `requested_fields` is explicitly non-empty, it must include every
  primary-key/fixed/partition field;
- a single-key window may use the same start/end key only when there is exactly one required key and `max_span_days=1`; range windows retain the old distinct-key rule.

Update compiler report rendering at the same time: a binding with no request
window must emit `request_window_fields: []` instead of indexing a missing
mapping. Preserve the existing totals key `converted_datasets`; do not introduce
a renamed report key.

Keep the checked-in `trade_cal` behavior unchanged except for an explicit `reject_at_row_limit: false` in its contract.

- [ ] **Step 4: Run parser/compiler tests and verify GREEN**

Run the Step 2 command. Expected: all selected tests pass.

- [ ] **Step 5: Run static checks for Task 1**

```bash
uv run --python 3.12 --with-requirements requirements.txt \
  ruff check dataset_registry.py tools/compile_provider_native_registry.py \
  tests/test_compile_provider_native_registry.py tests/test_provider_native_registry.py
uv run --python 3.12 python -m compileall -q \
  dataset_registry.py tools/compile_provider_native_registry.py
git diff --check
```

Expected: all commands exit 0.

---

### Task 2: Validate snapshot and single-partition responses before SQLite writes

**Files:**
- Modify: `tests/test_collect_provider_dataset.py`
- Modify: `tests/test_provider_dataset_rows.py`
- Modify: `collectors/tushare/provider_native_ingest.py`
- Modify: `storage/provider_dataset_rows.py`

**Interfaces:**
- Consumes: `DatasetDefinition.primary_key`, the strategy-aware `ResponseCompletenessPolicy`, resolved provider params, and `max_rows_per_attempt`.
- Produces: `_validate_response_completeness(dataset, binding, rows, request_window, resolved_params)` that fails before fact writes and yields only a failed terminal receipt.

- [ ] **Step 1: Write ingest RED tests**

Add real-code tests with these exact names:

- `test_snapshot_accepts_unique_primary_keys_below_provider_cap`;
- `test_snapshot_rejects_duplicate_primary_key_before_storage`;
- `test_snapshot_preserves_unusable_key_degraded_payload_fallback`;
- `test_snapshot_rejects_exact_provider_row_cap_before_storage`;
- `test_partition_accepts_unique_rows_matching_requested_date`;
- `test_partition_rejects_wrong_or_invalid_trade_date_before_storage`;
- `test_partition_rejects_duplicate_primary_key_before_storage`;
- `test_partition_preserves_unusable_nonpartition_key_degraded_fallback`;
- `test_partition_rejects_exact_provider_row_cap_before_storage`;
- `test_partition_empty_is_recorded_empty_when_policy_allows`.

Every rejection test must assert:

```python
assert code == runner.EXIT_VALIDATION
assert output["state"] == "validation"
assert output["error_codes"] == ["validation_failed"]
assert provider_fact_count(db_path) == 0
assert success_receipt_count(db_path) == 0
```

- [ ] **Step 2: Run the new ingest tests and verify RED**

Run the new exact test nodes. Expected: failures because the strategies are unsupported and empty-with-completeness is currently forced to failed.

- [ ] **Step 3: Implement the minimal generic validators**

Use one helper to inspect the dataset primary-key tuple without coercion. It
detects duplicates only when every key component is a usable stable scalar.
Missing, null, blank, unhashable, or type-drifted non-partition identity values
must not become a new admission failure: they continue into the existing
provider-native writer, which assigns tagged payload-hash identity and degraded
quality. A missing, malformed, or wrong partition field remains a batch-level
completeness failure because it cannot prove the requested partition. Then
dispatch:

```python
if policy.strategy == "one_row_per_calendar_date":
    _validate_calendar_dates(
        policy,
        rows,
        request_window=request_window,
        resolved_params=resolved_params,
    )
elif policy.strategy == "unique_primary_key_snapshot":
    _validate_unique_primary_keys(dataset, rows)
elif policy.strategy == "single_partition_unique_primary_key":
    _validate_single_partition(
        dataset,
        policy,
        rows,
        resolved_params=resolved_params,
    )
else:
    raise ValueError("provider response completeness strategy is unsupported")
```

Before dispatch, apply common fixed-field matching and:

```python
if policy.reject_at_row_limit and len(rows) >= binding.max_rows_per_attempt:
    raise ValueError("provider response reached the declared row limit")
```

For a provider `empty` outcome, use only `dataset.empty_data_policy` to select `empty` versus `validation_failed`; the presence of a completeness policy must not itself turn an allowed empty into success or failure. Transport/provider failures remain `failed`.

Extend `_config_hash` in the same task. Its canonical payload must include every
response-completeness field, including explicit `None` values and the boolean:
`strategy`, `date_field`, `request_start_key`, `request_end_key`,
`partition_field`, `request_partition_key`, `fixed_field_matches`, and
`reject_at_row_limit`. Parameterize the hash test so changing any one behavioral
field changes the hash, and verify success, empty, and failed receipts carry the
expected config hash and honest `data_through`.

Complete the already-approved degraded identity contract in the generic SQLite
writer: a blank text primary-key component is unusable, yields a `payload:` row
key, and records `snapshot_key_fallback:blank:<field>`. Preserve the existing
fallback behavior and issue names for missing, null, non-scalar, and type-mismatch
keys. Add direct writer tests plus the two ingest tests above; do not add a
dataset ID or API-name branch.

- [ ] **Step 4: Run ingest tests and verify GREEN**

Run:

```bash
uv run --python 3.12 --with-requirements requirements.txt \
  python -m pytest -q tests/test_collect_provider_dataset.py
```

Expected: all tests pass, including the unchanged `trade_cal` matrix.

- [ ] **Step 5: Run static checks for Task 2**

```bash
uv run --python 3.12 --with-requirements requirements.txt \
  ruff check collectors/tushare/provider_native_ingest.py \
  storage/provider_dataset_rows.py tests/test_collect_provider_dataset.py \
  tests/test_provider_dataset_rows.py
uv run --python 3.12 python -m compileall -q \
  collectors/tushare/provider_native_ingest.py storage/provider_dataset_rows.py
git diff --check
```

Expected: all commands exit 0.

---

### Task 3: Add official `stock_basic` and `daily` contracts and regenerate target registry

**Files:**
- Modify: `collectors/tushare/collector.py`
- Modify: `collectors/tushare/tushare_common.py`
- Modify: `config/tushare_upstream_contracts.v1.yaml`
- Regenerate: `config/provider_native_dataset_registry.yaml`
- Modify: `tests/test_compile_provider_native_registry.py`
- Modify: `tests/test_provider_native_zero_code.py`
- Modify: `tests/test_tushare_common.py`
- Modify: `tests/test_tushare_sync_daily.py`
- Modify: `tests/test_v1_api.py`
- Modify: `tests/test_query_service.py`
- Modify: `docs/dataset_registry.md`

**Interfaces:**
- Consumes: official Tushare markdown contracts `25.md` and `27.md`, the compiler, and the two generic strategies from Tasks 1–2.
- Produces: three resolved target datasets (`trade_cal`, `stock_basic`, `daily`) and 111 typed unresolved legacy entries that remain absent from the target.

- [ ] **Step 1: Write bundle/target RED tests**

Assert exact mappings and no dataset-specific implementation:

```python
assert target.ids() == (
    "cn.equity.daily",
    "cn.equity.security_master",
    "cn.market.trade_calendar",
)
assert report["totals"]["converted_datasets"] == 3
assert report["totals"]["unresolved_datasets"] == 111
assert target.resolve("tushare.stock_basic").dataset_id == "cn.equity.security_master"
assert target.resolve("tushare.daily").dataset_id == "cn.equity.daily"
```

Assert both generated bindings have `requested_fields == ()`; the snapshot
report row has `request_window_fields == []`; the daily report row has
`request_window_fields == ["trade_date"]`; and two independent compilations
produce byte-identical target and report files. Prove absence of dataset-specific
implementation with an exact changed-path/write-domain gate, not a repository-wide
name scan that would match pre-existing legacy compatibility code.

Before adding contracts, write transport RED tests proving:

- `TushareCollector.collect_outcome(..., fields=None)` passes `None` through
  `_call_tushare` without converting it to an empty string;
- `tushare_rows_outcome(..., fields=None)` and an explicitly empty string both
  omit the `fields` key from actual request JSON;
- an explicit non-empty projection still sends exactly that `fields` value.

- [ ] **Step 2: Run bundle/target tests and verify RED**

Run:

```bash
uv run --python 3.12 --with-requirements requirements.txt \
  python -m pytest -q \
  tests/test_compile_provider_native_registry.py \
  tests/test_provider_native_zero_code.py
```

Expected: resolved count remains 1 and the two datasets are absent.

- [ ] **Step 3: Add the two official declarative contracts**

Use these immutable official sources:

```yaml
stock_basic:
  source_document_url: https://tushare.pro/wctapi/documents/25.md
  source_document_sha256: 4882535fae578462818619025ed61ad0634c5091cd75a63ebef0e84bc6285e96
daily:
  source_document_url: https://tushare.pro/wctapi/documents/27.md
  source_document_sha256: e31ee01b411925e0400ba3cd5bed9c38f39d38dd2bede51261d4aa24e81c3879
```

`stock_basic` contract:

- request template `{list_status: L}` with no request-window policy;
- `requested_fields: []`; define all 17 documented fields in the manifest but
  do not send an upstream field projection;
- primary key `[ts_code]`; no response fixed-field match, because the ordinary
  default envelope does not guarantee `list_status` is returned;
- `current_snapshot`, `daily_reference`, `empty_data_policy=forbidden`;
- `unique_primary_key_snapshot`, exact-limit rejection, row cap 6000.

`daily` contract:

- request template `{trade_date: "${window.trade_date}"}`;
- one-key `yyyymmdd` window with start=end=`trade_date`, max span 1;
- `requested_fields: []`; define all 13 documented fields in the manifest,
  including nullable `ah_vol/ah_amount`, without an upstream projection;
- primary key `[ts_code, trade_date]` and `trade_date` as as-of/range/partition;
- `current_snapshot`, `postclose_daily`, `empty_data_policy=allowed`;
- `single_partition_unique_primary_key`, exact partition match, exact-limit rejection, row cap 6000.

Run the compiler twice to temporary outputs and prove byte identity before replacing the checked-in target through the repository's compiler command. Never hand-edit generated target YAML.

Freeze these complete contract values so implementers do not infer them:

- both entries use `schema_version: 2.0.0`, `point_in_time:
  current_snapshot`, `backfill_policy: provider_limited`, `required_scope:
  market_data`, `quota_class: beta_standard`, `reviewed_type_overrides: []`,
  and budgets `{max_rows_per_attempt: 6000,
  max_payload_bytes_per_row: 65536, max_batch_bytes: 16777216,
  max_nesting_depth: 16}`;
- every declared field is selectable, filterable, and sortable;
- `stock_basic` fields in official order are `ts_code`, `symbol`, `name`,
  `area`, `industry`, `fullname`, `enname`, `cnspell`, `market`, `exchange`,
  `curr_type`, `list_status`, `list_date`, `delist_date`, `is_hs`, `act_name`,
  `act_ent_type`; each has declared source type `str` and logical type `text`;
  only `ts_code` is non-null; default projection is `ts_code,symbol,name,area,
  industry,cnspell,market,list_date,act_name,act_ent_type`; `as_of_field`,
  `as_of_format`, `range_field`, and `partition_field` are null;
- `daily` fields in official order are `ts_code:text`, `trade_date:text`, then
  `open:float`, `high:float`, `low:float`, `close:float`, `pre_close:float`,
  `change:float`, `pct_chg:float`, `vol:float`, `amount:float`, `ah_vol:float`,
  `ah_amount:float`; declared source types are respectively `str`, `str`, then
  `float`; only `ts_code` and `trade_date` are non-null; default projection
  excludes the two optional after-hours fields; `as_of_field`, `range_field`,
  and `partition_field` are `trade_date`, with `as_of_format: yyyymmdd`.

These strategies prove provider-contract structural completeness only: identity
uniqueness, requested partition agreement, and the documented cap boundary.
They do not independently prove that a response below 6000 rows contains every
security in the market.

Implement the transport fix generically: `_call_tushare` and its lazy strict
call accept `str | None`; `collect_outcome` passes the value through unchanged;
and `tushare_rows_outcome` builds the request mapping without a `fields` member
when the value is `None` or `""`. Do not change the legacy `tushare_data`/
`tushare_rows` compatibility API, and do not introduce an `api_name` branch.

- [ ] **Step 4: Update registry documentation**

Document the two new generic strategies, degraded payload-hash identity
preservation, the exact-limit truncation rule, legal empty behavior, structural
completeness limitation, and the fact that adding these datasets did not add a
route, table, or dataset-specific collector. State that industry fan-out and
production activation remain separate work.

Parameterize the existing zero-code vertical-slice test for both new generic
strategies. Feed raw Tushare-style `fields/items` envelopes and prove, without a
provider-specific branch:

- generic adapter to SQLite facts plus receipt to `POST /v1/query`;
- unknown upstream fields remain stored and query metadata is degraded rather
  than being dropped;
- snapshot uses no request window and daily sends one `trade_date` partition;
- success, allowed empty, and failed states retain honest receipt metadata;
- query never calls the provider and never falls back to legacy tables/files;
- the only public data routes remain `GET /v1/catalog` and `POST /v1/query`.

- [ ] **Step 5: Run Task 3 tests and verify GREEN**

Run the Step 2 command plus:

```bash
uv run --python 3.12 --with-requirements requirements.txt \
  python -m pytest -q tests/test_tushare_common.py \
  tests/test_tushare_sync_daily.py tests/test_v1_api.py \
  tests/test_query_service.py
```

Expected: all tests pass; target has exactly 3 datasets; 111 unresolved datasets do not appear in target.

---

### Task 4: Freeze and independently review the candidate

**Files:**
- Verify all files changed by Tasks 1–3.
- Do not update `STATUS.md` until a fresh reviewer returns PASS.

**Interfaces:**
- Consumes: final candidate bytes.
- Produces: exact file manifest, diff/aggregate SHA-256, test evidence, and a clean-overlay reviewer decision.

- [ ] **Step 1: Run the full final matrix**

```bash
uv run --python 3.12 --with-requirements requirements.txt python -m pytest -q
uv run --python 3.12 --with-requirements requirements.txt \
  ruff check dataset_registry.py tools/compile_provider_native_registry.py \
  collectors/tushare/provider_native_ingest.py collectors/tushare/collector.py \
  collectors/tushare/tushare_common.py storage/provider_dataset_rows.py \
  tests/test_compile_provider_native_registry.py \
  tests/test_provider_native_registry.py \
  tests/test_collect_provider_dataset.py \
  tests/test_provider_dataset_rows.py tests/test_provider_native_zero_code.py \
  tests/test_tushare_common.py tests/test_tushare_sync_daily.py
uv run --python 3.12 python -m compileall -q \
  dataset_registry.py tools/compile_provider_native_registry.py \
  collectors/tushare/provider_native_ingest.py collectors/tushare/collector.py \
  collectors/tushare/tushare_common.py storage/provider_dataset_rows.py
git diff --check
```

Expected: full suite and all static checks pass.

- [ ] **Step 2: Prove determinism and scope**

Compile target/report twice and compare bytes. Verify the default legacy registry SHA remains `d6f58ff1934ee568d8b774ea283b51d67a915bdc66f9bb8c964624524d4d64a5`; only the target registry changes. Verify no changes under API routing, storage schema/migrations, scheduler/cron, auth, TradingAgent, or MarketGraph.

- [ ] **Step 3: Freeze exact bytes and open a fresh clean-overlay review**

The reviewer must validate official field provenance, all three completeness
strategies, snapshot/partition failure cases, config-hash lineage, 3 converted
versus 111 unresolved, lossless payload and degraded identity fallback, the two
parameterized zero-code vertical slices, no legacy fallback, no special-case
code, no secret, and no production action. Review language must call this
structural completeness rather than proof of whole-market cardinality. Any
reproducible P0/P1 fails the candidate; P2 is backlog.

- [ ] **Step 4: Integrate only after PASS**

After PASS, the primary agent independently checks the exact diff, stages explicit files only, commits normally, fast-forwards `main`, pushes, and reads back local/origin/live GitHub. A separate doc-only status update records the result. Production and external Beta remain NO-GO until their own release gates pass.

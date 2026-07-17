# SharedSignals Provider-native Generic Slice Implementation Plan

**Date:** 2026-07-17
**Status:** approved for local TDD; production DDL/migration is not authorized
**Base:** `ab8f32e637c418f0c5b850eb06192103d48330e7`
**Goal:** prove that an ordinary Tushare dataset can be added through registry/config only and traverse provider → SQLite facts + receipt → `/v1/query` without dataset-specific code.

## 1. Frozen boundary

This slice adds one generic provider-native path. It does not activate a real provider, change production SQLite, edit cron, add an API route, migrate an existing dataset, or remove a compatibility table.

The following invariants are blocking:

- every provider key/value, including unknown fields, is preserved in canonical `payload_json`;
- technical metadata never rewrites the payload;
- declared type/schema mismatches are stored and marked as quality issues rather than dropped;
- only invalid or oversized JSON, approved resource-budget breaches, or damaged technical envelopes are hard admission failures;
- successful facts and their receipt commit in the same SQLite transaction;
- the reader never calls a provider and never creates a missing table;
- client input cannot supply a table name, SQL expression, or JSON path;
- collection starts from `dataset_id + request_window`; API name, parameters,
  requested provider fields, and ingest budgets are resolved from registry/config;
- existing typed datasets retain their current behavior.

## 2. Exact implementation scope

Production code:

1. `dataset_registry.py`
2. `storage/provider_dataset_rows.py` (new)
3. `collectors/tushare/provider_native_ingest.py` (new)
4. `query_service.py`
5. `catalog_service.py`

Tests:

6. `tests/test_provider_native_registry.py` (new)
7. `tests/test_provider_dataset_rows.py` (new)
8. `tests/test_provider_native_query.py` (new)
9. `tests/test_provider_native_zero_code.py` (new)

Core documents owned by the main task:

10. `AGENTS.md`
11. `README.md`
12. `STATUS.md`
13. `docs/data_source_onboarding.md`
14. `docs/dataset_registry.md`
15. `docs/query_service.md`
16. `docs/superpowers/specs/2026-07-15-sharedsignals-external-data-platform-beta-design.md`
17. this plan

Out of scope: `api_server.py`, auth, existing production registry entries, `storage/schema_contract.py`, legacy typed writers, cron, provider network, production, DuckDB, TA/MG, and any data deletion.

## 3. Registry contract

Extend `ReadModelAdapter` with:

```python
storage_kind: str = "typed_columns"
row_key_strategy: str | None = None
```

Allowed combinations:

- legacy default: `typed_columns`, existing primary table and fixed filters;
- generic: `provider_native_rows`, `primary_table=provider_dataset_rows`, and `row_key_strategy` equal to `primary_key` or `payload_hash`.

For generic datasets, existing dataset fields are the queryable provider-native manifest. `primary_key`, `as_of_field`, and `partition_field` reference provider-native fields. The manifest is not an ingest projection: unknown keys remain in `payload_json`.

Extend a generic `ProviderBinding` with a frozen provider-request contract:

```python
request_template: Mapping[str, str]
requested_fields: tuple[str, ...]
max_rows_per_attempt: int
max_payload_bytes_per_row: int
max_batch_bytes: int
max_nesting_depth: int
```

Template values are either approved literal strings or the exact placeholder
`${window.<safe_key>}`; safe keys match the registry identifier grammar and the
runtime window must contain exactly the referenced keys with bounded public
string values. The collector receives only `dataset_id` and
`request_window`; it must resolve `api_name`, params, fields, and budgets from
the registry. Existing typed bindings may omit this contract; every generic
binding must declare it. Registry field names use the frozen provider-field
identifier grammar, so neither registry nor client input can inject a JSON path.

## 4. Temporary SQLite candidate

The module may expose the following DDL as a test/migration candidate, but runtime code must not execute it automatically:

```sql
CREATE TABLE provider_dataset_rows (
    dataset_id          TEXT NOT NULL,
    provider            TEXT NOT NULL,
    schema_major        INTEGER NOT NULL CHECK (schema_major >= 1),
    ingested_schema_version TEXT NOT NULL,
    row_key             TEXT NOT NULL,
    observed_at         TEXT,
    partition_value     TEXT,
    payload_json        TEXT NOT NULL
                        CHECK (json_valid(payload_json)
                               AND json_type(payload_json) = 'object'),
    payload_hash        TEXT NOT NULL,
    quality_state       TEXT NOT NULL CHECK (quality_state IN ('valid', 'degraded')),
    quality_issues_json TEXT NOT NULL DEFAULT '[]'
                        CHECK (json_valid(quality_issues_json)
                               AND json_type(quality_issues_json) = 'array'),
    collected_at        TEXT NOT NULL,
    receipt_id          TEXT NOT NULL,
    revision            INTEGER NOT NULL CHECK (revision >= 1),
    PRIMARY KEY (dataset_id, provider, schema_major, row_key)
);
```

Bounded indexes cover `(dataset_id, provider, schema_major, partition_value, row_key)`, `(dataset_id, provider, schema_major, observed_at, row_key)`, `(dataset_id, provider, schema_major, quality_state)`, and `receipt_id`. Minor schema updates remain visible within the compatible major; responses report the current registry schema version while `ingested_schema_version` preserves row lineage.

The production table, indexes, backfill, parity, cutover, and rollback require a separate additive migration plan and safe-release approval.

## 5. Generic writer

`storage/provider_dataset_rows.py` owns the table constant, row preparation, and transactional writer.

Preparation:

- canonical JSON uses UTF-8, sorted keys, compact separators, and rejects NaN/Infinity or non-JSON values;
- a response matching the existing credential/provider-token leakage contract is a damaged security envelope and fails closed before fact, log, or API exposure; legitimate future business fields with credential-like names require a separate security contract and cannot weaken this generic onboarding path;
- registry budgets bound row count, per-row bytes, total batch bytes, and nesting depth before any write;
- `payload_hash` is SHA-256 of the exact canonical payload bytes;
- `current_snapshot` requires the `primary_key` strategy; it hashes a tagged canonical list of the declared key names and their unmodified values;
- when a snapshot key is missing, null, non-scalar, or otherwise unusable, use a tagged payload-hash fallback and record a deterministic quality issue;
- `append_only` requires the payload-hash strategy and never updates an existing fact;
- unsupported point-in-time/strategy combinations fail registry loading;
- `observed_at` and `partition_value` are copied into separate technical columns when present, otherwise null;
- missing/unknown/type-mismatched declared fields add deterministic issue codes without changing payload.

Write behavior per real chunk transaction:

- new key: insert with revision 1;
- same key and same payload hash: unchanged, do not mutate the fact row;
- `current_snapshot` stable key and changed payload across attempts: update payload/technical metadata/receipt and increment revision;
- two rows in one provider attempt with the same stable snapshot key but different payloads are a damaged technical envelope: prevalidation rejects the entire attempt and writes no success receipt; it must never silently keep the last row;
- `append_only` never updates; identical payload hashes are unchanged and distinct payloads get distinct row keys;
- insert/update/unchanged counts conserve provider rows;
- compute deterministic receipt identity before fact writes, write facts and success receipt in the same transaction, and roll back both on any failure;
- empty/failed calls use the existing terminal-receipt path.

The implementation reuses `IngestContext`, `IngestCounts`, `make_receipt_id`, `insert_ingest_receipt_with_evidence`, `write_terminal_receipt`, and `IngestResult`. It must not call the typed `_factor_rows`, `_canonical_row`, or `API_TO_TABLE_MAP` path.

## 6. Tushare provider-level ingest

`collectors/tushare/provider_native_ingest.py` accepts only `dataset_id`, a validated request window, registry, collector, database path, caller-generated `attempt_id`, and `started_at`. It resolves the binding request template, API name, fields, budgets, adapter version, canonical config hash, and data-through rule from trusted registry/config, then constructs `IngestContext` internally before invoking `TushareCollector.collect_outcome`. For a successful non-empty result, `data_through` is the validated maximum raw value of `as_of_field`, otherwise `partition_field`, otherwise the collection timestamp when the dataset declares no provider data-time field; empty/failed terminal attempts use null. It never guesses from API names or request parameter names. The caller cannot supply or override dataset/provider/API/adapter/config hash/data-through lineage. Any invalid or mismatched input fails before provider call and before SQLite write. It then routes:

- `success` → generic writer;
- `empty` → empty terminal receipt;
- `failed` → structured failed terminal receipt.

Tests inject a raw Tushare `fields/items` HTTP envelope below the collector boundary, not a prebuilt `ProviderCallOutcome`; the existing strict provider parser must construct the outcome. No test or implementation performs a real network call. Ordinary datasets add no `if api_name` branch.

## 7. Generic query/catalog branch

For `typed_columns`, existing SQL remains unchanged.

For `provider_native_rows`:

- every statement qualifies and adds immutable technical-column predicates for `dataset_id`, provider, and schema major; payload keys with the same names cannot affect isolation;
- filter/order/as-of/partition expressions are compiled only from registry-declared safe field names to bounded, type-guarded JSON expressions;
- SELECT reads internal `payload_json`, `provider`, `row_key`, and quality evidence, strictly parses JSON in Python, then projects requested provider fields. It never uses SQLite `json_extract` for response projection, so large integers are preserved and a missing key remains different from explicit JSON `null`;
- JSON paths are generated internally after registry validation and never accepted from the request;
- responses flatten selected provider-native fields and never expose `payload_json`, technical row keys, receipt IDs, or table names;
- a requested missing provider key is omitted from that response row; an explicit JSON null is returned as `field: null`;
- `eq null` and the null arm of `in` use `json_type(path) = 'null'`; missing keys use `json_type(path) IS NULL` internally and never match explicit-null filters;
- the writer records field-specific quality issues for integers outside SQLite's exact signed-64-bit domain. Before filter/order/as-of/partition, the reader checks those issues and deterministically fails closed if the operation touches such a field; SELECT projection still returns the original Python integer exactly;
- filtering or sorting any field whose stored values violate the declared query type fails closed rather than silently coercing or omitting rows;
- generic keyset pagination appends signed `provider + row_key` as the stable tie-breaker and never uses SQLite `rowid`;
- current validation, scopes, quotas, SQLite snapshot, response budget, receipt metadata, and fail-closed behavior remain in force;
- an indexed dataset-wide quality check plus page row issues produce truthful `metadata.quality`; top-level `degraded` is runtime-degraded OR dataset-quality-degraded, while `runtime_state` remains receipt-derived. Row values are never rewritten.

Catalog queryability checks the fixed generic technical columns and SQLite JSON capability instead of requiring every provider field to be a physical column.

## 8. TDD and acceptance order

1. Registry RED/GREEN: generic provider request template/fields/budgets; valid storage and point-in-time combinations; invalid key references and malicious field names fail closed; legacy registry unchanged.
2. Storage RED/GREEN: unknown fields, large integers, missing versus null, and type mismatch are stored losslessly; budgets; missing-key fallback; duplicate-key conflict; append-only versus snapshot; insert/update/unchanged; dataset/provider/schema-major isolation; receipt rollback; missing table fail closed.
3. Provider RED/GREEN: start from `dataset_id + request_window + attempt_id + started_at`; inject a raw strict `fields/items` transport envelope; prove internally constructed receipt lineage, resolved API/params/fields and success/empty/failed; forged/mismatched lineage cannot be supplied and invalid inputs cause zero provider call, zero fact, and zero success receipt.
4. Query RED/GREEN: lossless Python projection, missing/null selection and filters, explicit-null-only `eq null`/`in null`, large integer selection plus `2**63` filter/order fail-closed negatives, type-guarded filter/order/as-of/partition, stable provider+row-key cursor, tenant scope, cross-dataset isolation, forged technical payload keys, SQL/JSON-path injection rejection, and dataset/page quality evidence.
5. Zero-code E2E: add only a synthetic registry/config entry, call generic ingest with `dataset_id + request_window`, inject the raw transport envelope, and prove facts + receipt + real `/v1/query` response without dataset-specific collector/storage/query/API/test branches.
6. Regression: focused tests, existing registry/receipt/query/catalog/V1/auth suites, Python 3.12 full suite, Ruff, compile, YAML parse, docs checks, and `git diff --check`.
7. Fresh clean-overlay review: exact files and hashes, deterministic adversarial cases, P0/P1=0.

## 9. Parallel ownership

- Writer A: registry + generic storage/ingest + their focused tests.
- Writer B: generic query/catalog + query-focused tests.
- Main task: documents, zero-code end-to-end test, integration, full regression, and reviewer handoff.

No writer may commit, push, deploy, modify production, create a real schema, or expand the frozen file scope without returning to the main task.

## 10. Stop and rollback

Stop implementation if the slice needs dataset-specific Python, a public route, a provider call at query time, a production schema change, or a TA/MG dependency. Return to architecture rather than adding exceptions.

Local rollback is removal of the uncommitted slice or its isolated commit. Production rollback is not part of this slice because production activation is forbidden.

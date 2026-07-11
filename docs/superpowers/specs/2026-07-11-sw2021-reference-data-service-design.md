# SW2021 Reference Data Service Design

**Date:** 2026-07-11
**Status:** proposed for implementation
**Owner:** SharedSignals
**Consumers:** MarketGraph first; TradingAgent only through later explicit contracts

## 1. Goal

Build a versioned, source-traceable SW2021 reference-data service in SharedSignals so consumers can retrieve one complete, internally consistent current industry taxonomy and stock-membership snapshot through HTTP APIs.

The service fixes the current production defect where one unpartitioned Tushare `index_member_all` call stops at 2,000 rows and covers only 10 of 31 SW2021 level-one industries. It also removes the need for MarketGraph to infer SW2021 from `stock_basic.industry`, parse a mixed-purpose relationship table, or read a sibling database.

This is factual reference data. SharedSignals must not calculate industry strength, alpha, trade direction, portfolio weights, or execution permission.

## 2. Non-goals

- Do not change TradingAgent queues, capital, strategies, accounts, callbacks, cron ownership, or execution permissions.
- Do not make SW2021 classification itself a trading signal.
- Do not let MarketGraph or TradingAgent call Tushare directly.
- Do not replace MarketGraph's `chain_id` / `segment_id` industrial-chain axis.
- Do not delete or rewrite existing `market_assets` or `market_relationships` data during the initial rollout.
- Do not automatically change formal MarketGraph enterprise relations after the new taxonomy becomes available.
- Do not make the three systems share a database or filesystem as a production contract.

## 3. Verified baseline

Production evidence on 2026-07-11 established:

- `index_classify` contains 642 rows and exposes hierarchy fields in `raw_json`.
- the current `index_member_all` read model contains exactly 2,000 rows and 2,000 unique stocks;
- those rows cover only 10 level-one industries;
- all 2,000 rows have `is_new=Y` and no `out_date`;
- controlled provider reads using `l1_code=<SW L1 index code>` plus `is_new=Y` returned complete bounded partitions for both `801010.SI` and `801780.SI`;
- MarketGraph production currently generates a Tushare `stock_basic.industry` fallback and leaves every SW L1/L2/L3 code empty.

The existing generic tables preserve useful audit material but cannot express an atomic, promoted current industry snapshot.

## 4. Ownership and system boundaries

### SharedSignals

Owns provider collection, normalization, snapshot validation, persistence, freshness, lineage, read APIs, authentication, rate limits, and degraded responses.

### MarketGraph

Consumes only the SharedSignals HTTP contract. It maps the promoted SW2021 snapshot into research objects, industry/enterprise relations, event propagation, portfolio risk clusters, and review outputs. It continues to own its separate industrial-chain axis and never gains execution authority.

### TradingAgent

Receives no direct behavioral change in this rollout. A later, separately tested contract may let it consume MarketGraph industry-risk or event-propagation context. TradingAgent remains the only owner of signal, portfolio, capital, account, and execution decisions.

## 5. Storage model

The migration is additive. Three new SQLite/DuckDB-mirrored tables are introduced.

All three tables must be registered in `storage/schema_contract.py`, created through the existing migration renderer, and classified as authoritative SQLite snapshots for DuckDB mirroring in `storage/storage_adapter.py`. "Authoritative" here means DuckDB mirrors the complete SQLite table, including snapshot history and mutable promotion status; it does not mean a collector may delete prior snapshots.

### 5.1 `market_industry_snapshots`

One row represents one collection and validation attempt.

| Column | Type | Meaning |
| --- | --- | --- |
| `snapshot_id` | text PK | Immutable run identifier |
| `taxonomy_system` | text | `SW` |
| `taxonomy_version` | text | `SW2021` |
| `provider` | text | `tushare` |
| `started_at` | text | UTC start time |
| `completed_at` | text | UTC completion time |
| `status` | text | `collecting`, `candidate`, `promoted`, `superseded`, or `rejected` |
| `expected_partition_count` | integer | Expected L1 count, currently 31 |
| `successful_partition_count` | integer | Successfully collected L1 partitions |
| `taxonomy_row_count` | integer | Normalized taxonomy nodes |
| `membership_row_count` | integer | Normalized current membership rows |
| `unique_symbol_count` | integer | Distinct member stocks |
| `active_universe_count` | integer | Eligible A-share universe at collection time |
| `coverage_ratio` | float | Unique members divided by eligible universe |
| `validation_errors_json` | text | Machine-readable rejection reasons |
| `source_run_id` | text | Collector/runtime audit correlation ID |
| `promoted_at` | text | UTC promotion time, null unless promoted |

Only one snapshot per `(taxonomy_system, taxonomy_version)` may have `status=promoted`. A successful replacement changes the previous promoted row to `superseded` in the same transaction. The current snapshot is the single promoted row, never merely the latest started run.

### 5.2 `market_industry_taxonomy`

One row represents one taxonomy node inside a snapshot.

| Column | Type | Meaning |
| --- | --- | --- |
| `taxonomy_node_key` | text PK | Hash of snapshot, version, level, and index code |
| `snapshot_id` | text | Owning promoted/candidate snapshot |
| `taxonomy_system` | text | `SW` |
| `taxonomy_version` | text | `SW2021` |
| `level` | text | `L1`, `L2`, or `L3` |
| `index_code` | text | Tradable/reference index code such as `801010.SI` |
| `industry_code` | text | Provider hierarchy code such as `110000` |
| `industry_name` | text | Canonical provider name |
| `parent_industry_code` | text | Provider parent hierarchy code |
| `is_published` | text | Provider `is_pub` value, preserved rather than inferred |
| `provider` | text | `tushare_index_classify` |
| `collected_at` | text | UTC collection time |
| `raw_json` | text | Original provider row |

Indexes cover `(snapshot_id, level, index_code)`, `(snapshot_id, industry_code)`, and `(snapshot_id, parent_industry_code)`.

All nodes required by a promoted membership snapshot must be retained, including provider nodes whose `is_pub` value is false. Publication state is evidence, not a reason to silently remove a referenced hierarchy node.

### 5.3 `market_industry_memberships`

One row represents one stock's current SW2021 L1/L2/L3 assignment inside a snapshot.

| Column | Type | Meaning |
| --- | --- | --- |
| `membership_key` | text PK | Hash of snapshot, version, and stock symbol |
| `snapshot_id` | text | Owning candidate/promoted snapshot |
| `market` | text | `Ashare` |
| `symbol` | text | Tushare stock code |
| `name` | text | Provider stock name |
| `l1_code`, `l1_name` | text | SW2021 L1 index code and name |
| `l2_code`, `l2_name` | text | SW2021 L2 index code and name |
| `l3_code`, `l3_name` | text | SW2021 L3 index code and name |
| `in_date` | text | Provider membership start date |
| `out_date` | text | Provider membership end date, normally null for current rows |
| `is_current` | text | Normalized from provider `is_new=Y` |
| `provider` | text | `tushare_index_member_all` |
| `collected_at` | text | UTC collection time |
| `raw_json` | text | Original provider row |

Indexes cover `(snapshot_id, symbol)`, `(snapshot_id, l1_code)`, `(snapshot_id, l2_code)`, and `(snapshot_id, l3_code)`.

Conflicting current assignments for the same stock reject the snapshot. They are not resolved by last-write-wins.

## 6. Collection and promotion flow

1. Create a new snapshot row with `status=collecting`.
2. Collect `index_classify` and normalize the full hierarchy.
3. Identify exactly 31 valid L1 partition codes from the taxonomy input.
4. Call `index_member_all(l1_code=<code>, is_new=Y)` once for each L1 using the complete provider field list.
5. Accumulate all partitions in memory or a transaction-local staging structure; do not publish partition results individually.
6. Normalize and deduplicate by stock symbol.
7. Validate the candidate snapshot.
8. Under the existing exclusive read-model write lock, use one database transaction to insert snapshot taxonomy and memberships, change the prior promoted snapshot to `superseded`, and mark the candidate `promoted`.
9. Commit the transaction before any reader can expose the snapshot. Existing reader cache generation follows the SQLite file mtime through `_maybe_invalidate`; the collector must not call the global `/cache/invalidate` endpoint.

Provider rows may continue to populate the existing generic tables for backward compatibility, but the new service reads only the dedicated tables. The snapshot collector uses a dedicated normalization and transactional writer; it does not change `API_TO_TABLE_MAP` and does not route the dedicated writes through the generic `index_classify -> market_assets` or `index_member_all -> market_relationships` mapping.

## 7. Promotion gates

A candidate snapshot is promoted only if all gates pass:

- exactly 31 expected L1 partitions and 31 successful partitions;
- no provider call failure or silent row-limit hit;
- every membership has non-empty symbol, name, L1/L2/L3 code, and L1/L2/L3 name;
- every referenced L1/L2/L3 code resolves to a taxonomy node in the same snapshot;
- no stock has conflicting current assignments;
- every row has `is_new=Y` and empty `out_date`;
- the eligible A-share reference universe is non-zero and is read from `market_assets` rows with `market=Ashare`, `provider=tushare_stock_basic`, `asset_type=stock`, a valid Shanghai/Shenzhen/Beijing stock symbol, a non-empty name, and no `退` marker in the name;
- unique-symbol coverage is at least 90% of that eligible A-share reference universe;
- row counts remain within configurable lower/upper anomaly bounds;
- SQLite writes are non-zero and the transaction commits successfully.

Failures mark the snapshot `rejected` with structured reasons. The previously promoted snapshot remains current. No incomplete candidate becomes visible to consumers.

The 90% threshold is a minimum safety gate, not proof that missing stocks are harmless. API metadata must expose exact numerator, denominator, and missing count.

## 8. HTTP API

The new query shape and independent snapshot SLA justify dedicated endpoints rather than overloading generic `/tushare`.

### `GET /industry/snapshot`

Returns current promoted snapshot metadata, counts, coverage, freshness, and lineage.

### `GET /industry/taxonomy`

Parameters: `snapshot_id` (optional, defaults to current), `level`, `parent_industry_code`, `index_code`, `limit`, `cursor`.

### `GET /industry/memberships`

Parameters: `snapshot_id` (optional, defaults to current), `symbol`, `l1_code`, `l2_code`, `l3_code`, `limit`, `cursor`.

Both list endpoints use stable keyset pagination. Default page size is 500 and maximum page size is 1,000. Responses include `snapshot_id`, `next_cursor`, exact row-count metadata, freshness, lineage, and degraded reasons.

The cursor is an opaque URL-safe encoding of `(snapshot_id, last_sort_key)`. Taxonomy pages sort by `(level, index_code, taxonomy_node_key)` and membership pages sort by `(symbol, membership_key)`. A cursor whose snapshot does not match the request is rejected. Cursor support is intentionally local to these endpoints; existing limit-only endpoints are unchanged.

No endpoint calls Tushare at request time. Missing promoted snapshots, invalid cursors, read timeouts, or unavailable tables return `data: []` with explicit degraded metadata.

### Authentication

Add a least-privilege `industry_reference` scope covering the three endpoints. Include it in approved internal/read/external-read composites, without granting cache invalidation or other operations. Separate service-account tokens are expected for MarketGraph and future TradingAgent consumers; one shared universal token is prohibited.

Implementation must register the three exact paths in `auth.py`, add the scope to the documented composites, and add corresponding route branches in `api_server.py`. The reader boundary consists of `get_industry_snapshot()`, `get_industry_taxonomy()`, and `get_industry_memberships()`, each using the existing safe-public/degraded wrapper and bounded cache conventions.

The legacy `/industry?ts_code=` endpoint continues to expose its existing `stock_basic.sector` semantics until a separately versioned deprecation is completed. It must not be relabeled as SW2021.

## 9. MarketGraph consumer

MarketGraph adds one HTTP client boundary that:

1. reads `/industry/snapshot`;
2. requires `status=promoted`, `taxonomy_system=SW`, and `taxonomy_version=SW2021`;
3. downloads taxonomy and membership pages while pinning the same `snapshot_id`;
4. rejects cursor loops, duplicate/conflicting stocks, partial pages, unresolved hierarchy codes, or snapshot changes;
5. preserves the last verified local outputs if the API is degraded;
6. maps the result into MarketGraph-owned internal artifacts `data/industry_taxonomy.csv` and `data/association/stock_industry_map.csv`; these files remain inside MarketGraph and are not a SharedSignals production bridge;
7. preserves `chain_id`, `chain_name`, `segment_id`, and `segment_name` from MarketGraph's own chain seed;
8. records SharedSignals URL, snapshot ID, taxonomy version, coverage, and retrieval time in its generation summary.

MarketGraph must not read SharedSignals SQLite or use `stock_basic.industry` as an SW2021 fallback. If no promoted snapshot exists, it may continue to expose the existing clearly labelled fallback artifact, but it must not overwrite a previously verified SW2021 artifact with fallback data.

After the base tables are verified, MarketGraph regenerates only `entities.csv` and `entity_index.csv`. Enterprise-relation verification runs in dry-run mode. Formal enterprise facts are not changed in this rollout.

## 10. TradingAgent impact

There is no direct TradingAgent data-path or execution change in the initial release. The service creates a future-safe factual foundation for MarketGraph industry-risk, event-propagation, and concentration outputs.

Any later TradingAgent integration must consume a versioned MarketGraph research API, not these SharedSignals tables directly for trade decisions. It requires separate OOS/simulation evidence and cannot relax existing capital or execution gates.

## 11. Migration and rollout

1. Add schema contracts and migrations for the three tables in SharedSignals.
2. Add collector normalization and snapshot validation tests before implementation.
3. Add reader/API/auth/cursor tests.
4. Deploy additive schema code without scheduling the new collector.
5. Run one production candidate collection manually and inspect its 31-partition, taxonomy, membership, and coverage evidence.
6. Promote only if every gate passes.
7. Verify all three endpoints locally and through the approved token-authenticated route.
8. Add the scheduled daily reference job with overlap protection.
9. Observe at least one scheduled refresh and rollback behavior.
10. Implement the MarketGraph consumer and regenerate its two base tables plus entity indexes.
11. Keep TradingAgent unchanged.

## 12. Rollback and retention

Rollback is additive and non-destructive:

- disable the new scheduled collector;
- mark its source/runtime state `disabled_by_operator` so patrol reports the intentional rollback state and heal does not restart it;
- revert consumers to the previous promoted snapshot or existing fallback artifacts;
- keep the three tables and rejected/promoted audit rows intact;
- revert code by normal fast-forward/revert procedures;
- do not delete existing generic-table rows or databases.

Snapshot retention is not part of the first production migration. A later maintenance change may retain a bounded history after proving backup, restore, and audit requirements. It must not delete the current or immediately previous promoted snapshot.

## 13. Testing and acceptance

### SharedSignals

- schema parity tests for SQLite and DuckDB;
- authoritative-mirror classification tests for all three tables;
- collector RED/GREEN tests for 31-way partitioning;
- rejection tests for missing partitions, 2,000-row truncation, conflicting symbols, unresolved hierarchy codes, low coverage, and write failure;
- atomic promotion and previous-snapshot preservation tests;
- API filtering, pagination, cursor, auth-scope, degraded-empty, lineage, and cache invalidation tests;
- capability/source-status documentation tests;
- patrol/heal tests for active, rejected, stale, and `disabled_by_operator` collector states;
- production pilot proving 31/31 partitions, zero conflicts, hierarchy closure, and at least 90% active-universe coverage.

### MarketGraph

- pinned-snapshot pagination tests;
- fail-closed and last-verified-output preservation tests;
- exact field-mapping and taxonomy-ID tests;
- chain/segment preservation tests;
- entity/entity-index regeneration tests;
- enterprise verification dry-run diff review;
- checkpoint classification showing the SW2021 base tables are no longer unverified fallback.

### Cross-system

- contract fixture shared by producer and consumer tests;
- token-authenticated smoke from MarketGraph to SharedSignals;
- no sibling SQLite/file reads in the production consumer;
- no TradingAgent queue, capital, account, cron, or execution diff.

## 14. Future server separation

This design advances, but does not alone complete, three-server separation. The target architecture requires:

- one owned database and versioned API per system;
- per-service scoped credentials rather than a universal token;
- TLS/service routing, timeouts, retries, circuit breakers, and degraded responses;
- contract tests and observable request lineage;
- removal of remaining TradingAgent production reads from MarketGraph filesystem paths;
- audited API, outbox, or queue contracts for any future cross-system writes.

SharedSignals remains the factual data plane, MarketGraph the research/risk plane, and TradingAgent the decision/execution plane.

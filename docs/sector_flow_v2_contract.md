# Sector Flow Facts v2 Contract

## Status and boundary

This is a shadow-only, local contract. It adds no collector, provider call, cron, production migration, deployment, or TradingAgent scoring behavior.

SharedSignals stores and serves provider facts. It does not calculate ranks, alpha, trading scores, buy/sell direction, position weights, or execution triggers.

## Fact kinds

The contract requires one explicit fact kind unless a caller pins a published `snapshot_id`:

- `official_eod`: official or provider-designated post-close data. It must not be presented as intraday data.
- `intraday_proxy`: a provider proxy available during the session. It must not be presented as official close data.

The reader never blends the two kinds and never falls back from one to the other.

## PIT timestamps

Every snapshot contains three distinct timestamps:

- `effective_at`: when the represented market fact applies.
- `available_at`: earliest time the fact was available to a consumer. PIT queries use this field.
- `collected_at`: when SharedSignals persisted the provider payload.

`as_of` resolution selects only `status=published` rows whose `available_at <= as_of`. It orders eligible rows by `effective_at`, then `available_at`, then `snapshot_id`. An explicit snapshot is also subject to `status=published`; collecting or rejected rows are not readable.

## Storage contract

### `market_sector_flow_snapshots_v2`

One immutable header per published or in-progress snapshot. The primary key is `snapshot_id`.

The header records:

- contract identity: `schema_version`, `fact_kind`, `market`, `trade_date`;
- PIT lineage: `effective_at`, `available_at`, `collected_at`;
- source lineage: `provider`, `source_run_id`, `industry_snapshot_id`;
- content binding: one canonical `source_hash` repeated across the header and every child row;
- publication state: `status`;
- coverage counts and ratios for industries and constituents;
- `runtime_status` and `runtime_reason`;
- raw provider/run evidence in `raw_json`.

The referenced `industry_snapshot_id` is the SW2021 taxonomy/membership snapshot used to define industry and constituent membership. This contract does not mutate the SW2021 tables.

A readable v2 header must have exactly `schema_version=2`, `market=Ashare`, a valid `fact_kind`, and a non-empty `source_run_id`. These persisted identity checks apply equally to latest, `as_of`, and explicitly pinned snapshot reads.

### `market_sector_flow_industries_v2`

Primary key: `(snapshot_id, industry_code)`.

Rows contain provider facts for `gross_inflow`, `gross_outflow`, `net_inflow`, `turnover_amount`, constituent counts, and coverage. They repeat `effective_at`, `available_at`, and `provider` so exported rows remain self-describing.

### `market_sector_flow_constituents_v2`

Primary key: `(snapshot_id, industry_code, symbol)`.

Rows contain provider facts for the constituent contribution to the pinned industry snapshot. A symbol can appear under multiple industry codes only when the pinned membership snapshot allows it.

Every constituent `industry_code` must first exist in `market_sector_flow_industries_v2` for the same `snapshot_id`. A valid SW2021 membership alone cannot introduce an industry that is absent from the sector-flow snapshot.

### Canonical source hash

`source_hash` has the form `sha256:<64 lowercase hex characters>`. The digest input is canonical UTF-8 JSON with sorted object keys and compact separators:

- `snapshot`: every persisted snapshot-header field except `source_hash`;
- `industries`: every persisted industry row except `source_hash`, ordered by `industry_code`;
- `constituents`: every persisted constituent row except `source_hash`, ordered by `(industry_code, symbol)`.

The same digest must appear in all three tables. The reader reloads the complete unfiltered snapshot, recomputes the digest, and compares it before applying endpoint filters. Header or child-row tampering therefore fails closed instead of returning a partial apparently healthy result. The digest is exposed in response lineage.

Canonical JSON never admits `NaN`, positive infinity, or negative infinity. Canonicalization normalizes such input to `SnapshotContractError`; the reader returns degraded-empty instead of leaking a JSON `ValueError`. Every persisted industry and constituent money field (`gross_inflow`, `gross_outflow`, `net_inflow`, and `turnover_amount`) must be numeric and finite.

All three tables are authoritative SQLite snapshot tables and are reconciled into the DuckDB mirror without retaining stale primary keys.

## HTTP surface

All routes are GET-only and use the dedicated `sector_flow_v2` auth scope:

- `/v2/sector-flow/snapshot`
- `/v2/sector-flow/industries`
- `/v2/sector-flow/constituents`

`external_read` and `read` include this scope. Status-only, health-only, events, and existing macro scopes do not.

Common parameters:

- `fact_kind`: `official_eod` or `intraday_proxy`; required unless `snapshot_id` is supplied.
- `snapshot_id`: pins one published snapshot.
- `as_of`: ISO-8601 PIT boundary applied to `available_at`.

Industry parameters: `industry_code`, `limit` (default 500, maximum 1,000).

Constituent parameters: `industry_code` or `symbol` (at least one required), plus `limit`.

## Runtime-state semantics

`status` and `runtime_status` answer different questions. `runtime_status` has exactly five values:

- `status=published` means the immutable snapshot passed its writer-side publication gate and may be read.
- `success`: runtime completed with valid evidence; `runtime_reason` must be empty, both header coverage ratios must equal `1.0`, and API metadata is not degraded.
- `empty`: runtime completed with zero observed industry and constituent rows; a non-empty reason is required and API metadata is degraded.
- `unobserved`: no qualifying runtime observation exists; a non-empty reason is required and API metadata is degraded.
- `paused`: operator or incident control paused runtime production; a non-empty reason is required and API metadata is degraded.
- `failed`: runtime attempted and failed; a non-empty reason is required and API metadata is degraded.

Legacy or invented values such as `active` and `degraded` are invalid and cause fail-closed output.

Coverage is evidence, not a score. A published partial-coverage snapshot can be returned only with its real coverage and degraded runtime state. Missing database, missing tables, no eligible published snapshot, or empty facts return `data: []` with `metadata.degraded=true`, a reason, and `fallback=none`.

Before returning data, the reader also requires timezone-aware timestamps with `effective_at <= available_at <= collected_at`, `trade_date` bound to the effective date, finite money facts, finite coverage ratios within `[0,1]`, exact ratio/count agreement, `observed <= expected`, observed counts equal to persisted child-row counts, every constituent code present in the same snapshot's industry rows, and a promoted/superseded SW2021 snapshot whose taxonomy and memberships contain every referenced industry and constituent.

Cross-snapshot PIT is fail-closed. The pinned SW2021 snapshot and all of its taxonomy/membership rows must satisfy `SW started_at <= child collected_at <= SW completed_at <= SW promoted_at <= sector available_at`. Every timestamp in that chain must be present and timezone-aware for both `promoted` and `superseded` snapshots. Missing, naive, future, or conflicting timestamps invalidate the sector snapshot. Request `as_of` is never used to repair or substitute any SW2021 timestamp.

SW child/header lineage is also fail-closed. Every taxonomy child under the pinned snapshot must identify `taxonomy_system=SW` and `taxonomy_version=SW2021`; every membership child must identify `market=Ashare`. Header `taxonomy_row_count` and `membership_row_count` must equal the complete child-row counts, and `unique_symbol_count` must equal the distinct membership-symbol count. A wrong child identity or any count mismatch invalidates the sector snapshot even when its three-table source hash is self-consistent.

## Writer acceptance contract (not implemented in this lane)

A future writer must, in one controlled transaction:

1. Pin an existing published SW2021 industry snapshot.
2. Validate v2/A-share identity, fact kind, finite facts, and all PIT/source fields.
3. Write header and exact child rows.
4. Recompute observed counts and coverage from persisted rows.
5. Compute the canonical three-table `source_hash` only after the complete content is fixed.
6. Publish only after counts, SW2021 child/header identity, sector PIT, cross-snapshot SW2021 PIT, runtime state, finite facts, and hash all validate.
7. Keep official close and intraday proxy runs in separate snapshot IDs.

Until that writer, provider pilot, migration authorization, and runtime evidence exist, this surface is code-level shadow capability only.

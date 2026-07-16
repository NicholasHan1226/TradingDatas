# SharedSignals Provider and Dataset Onboarding

Last updated: 2026-07-16

## Purpose

This is the mandatory vertical-slice checklist for adding a provider or dataset to the **independent external multi-source financial data platform**. It applies to Tushare and future announcements, news, research, policy, interaction, and objective public-opinion sources.

Onboarding extends the provider-neutral dataset registry and fixed query service. **It never adds a public route per provider or dataset.**
Completing provider or dataset onboarding does not add a public route; both discovery and reads
continue through `GET /v1/catalog` and `POST /v1/query`.

## Existing-chain completion gate

Onboarding is complete only when one vertical slice proves every existing-chain step:

1. registry and schema declare the provider-neutral identity and canonical version;
2. entitlement and activation evidence is recorded without treating configuration as proof;
3. storage mapping is registry-owned and queryable without exposing internal tables;
4. normalization, validation, and deduplication preserve truthful provider outcomes;
5. facts and the success receipt commit in the same SQLite transaction;
6. the query and metadata contract returns non-empty freshness, quality, and lineage;
7. focused and full tests pass for the frozen scope;
8. current documentation records the boundary, evidence, rollback, and unverified layers.

This chain reuses the fixed public data plane. A provider-specific alias or legacy adapter may only
call the same QueryService; it cannot introduce another query engine, provider live fallback, or
file fallback.

## Initial release boundary

- Initial activation is limited to domestic China datasets and actual current-account entitlements.
- Prediction markets, cryptocurrency, Hong Kong, United States, and other excluded markets stay `excluded` or `paused`; historical rows are not deleted.
- Planned/configured/allowlisted does not mean entitled, observed, fresh, queryable, scheduled, or externally available.
- A request-time reader/API may never call a provider or fall back to CSV/NDJSON/Parquet/old directories.

## Required registry declaration

Every dataset must declare in `config/dataset_registry.yaml`:

| Field | Requirement |
| --- | --- |
| `dataset_id` | Stable provider-neutral identity such as `cn.equity.daily`. |
| `aliases` | Compatibility names such as `tushare.daily`; aliases are not public routes. |
| `domain`, `market`, `entity_type` | Objective-data classification. |
| `schema_version` | Versioned canonical fields, types, primary key, default projection. |
| `query_policy` | Selectable/filterable/sortable fields, bounded operators, page/lookback limits, PIT mode. |
| `provider_bindings` | Provider API, adapter version, storage mapping, provider-specific request rules. |
| `entitlement_state` | `active`, `locked`, `unknown`, `excluded`, or `retired`, based on evidence. |
| `cadence` | Registry cadence class, timezone, SLA, backfill policy, overlap key. |
| `empty_policy` | Whether empty is legitimate for the requested window. |
| `beta_policy` | Tenant scope, field/lookback limits, quota class, discoverability. |

The registry is authority. Do not recreate parallel allowlists in API routes, docs, cron tiers, or consumer repositories.

## Required provider adapter

The adapter must:

1. preserve provider success/error/permission/rate-limit outcomes before row conversion;
2. normalize to the canonical schema without losing raw provider payload needed for lineage;
3. validate identity, timestamps, numeric finiteness, required fields, and request window;
4. distinguish returned, validated, inserted, updated, unchanged, rejected, and committed counts;
5. enforce provider rate/concurrency limits and bounded retry;
6. expose a version that is bound into every ingest receipt;
7. contain no TradingAgent/MarketGraph import, callback, candidate, position, risk, or strategy logic.

## SQLite fact and receipt gate

- Non-empty successful data and its success receipt commit in the same SQLite transaction.
- A rollback leaves neither committed data from that transaction nor a success receipt.
- Each real chunk transaction receives its own receipt.
- Legitimate empty, provider failure, permission denial, throttling, validation failure, resource-budget rejection, and storage failure write terminal receipts when SQLite is available.
- `attempt_id` is unique per provider call/window; receipt IDs are deterministic within the attempt and cannot collide across reruns.
- SQLite facts + transaction-scoped ingest receipts are the only runtime authority. Flat JSON is optional rebuildable cache.

## Query/API gate

Every active dataset must be reachable through:

- `GET /v1/catalog` for discovery and current availability;
- `POST /v1/query` for bounded registry-compiled reads.

The query path must:

- validate `dataset_id`, `schema_major`, fields, filters, ordering, lookback and page size against the registry;
- use keyset pagination and bind cursor to tenant policy, query, schema/catalog version and receipt watermark;
- read data and receipt/runtime evidence from the same SQLite snapshot;
- return truthful `success`, `empty`, `unobserved`, `paused`, `failed` or `stale` metadata;
- keep receipt/time/provider lineage nullable when evidence does not exist; never fabricate them for client compatibility.

`/tushare` and other legacy endpoints may map provider parameters to a standard QueryRequest, but may not keep independent SQL or live-provider behavior.

## Scheduling gate

Cadence comes from the registry, not a growing set of handwritten tiers.

- Probe current entitlement before scheduling; `locked` is not retried as a continuous failure.
- Prevent overlapping work for the same dataset/window.
- Current-session collection has priority over backfill.
- Backfill has separate rate, row, time and storage budgets.
- Every attempt writes a receipt, including empty and failure.
- Schedule installation is a production mutation and requires a separate safe-release plan, live inventory, rollback and operator authorization.

## Beta access gate

Before an external tenant can discover/query a dataset, prove:

- isolated tenant credential and revocation;
- dataset/field/lookback policy;
- rate and concurrency limits;
- persistent quota and usage event without secrets/raw SQL;
- error sanitization and audit request ID;
- cross-tenant denial and cursor-policy binding.

No public signup, automated billing, automatic tier upgrade, scope expansion or admin mutation is part of invite-only Beta.

## Acceptance checklist

A dataset is complete only when all are true:

1. registry declaration and alias resolve deterministically;
2. provider adapter preserves outcome and passes schema/identity validation;
3. facts + receipts satisfy transaction atomicity and rerun idempotency;
4. empty/failure/paused/unobserved/stale are distinguishable from success;
5. catalog discovery and query return the same canonical schema and truthful metadata;
6. cadence, SLA, rate limit, backfill and entitlement behavior are tested;
7. tenant policy and usage governance are tested when externally visible;
8. docs describe the dataset without adding routes or trading semantics;
9. dry-run/pilot, rollback and production readback are separately evidenced;
10. no provider/file/other-system fallback exists in reader/API consumers.

## Acceptance Freeze

Freeze product scope, authority, interface, threat model, exact files, P0/P1 cases and stop line before implementation. After freeze, only deterministic in-scope P0/P1 defects block. Contract-external hardening becomes backlog. Two successive structural P1 rounds require architecture review instead of more patch stacking.

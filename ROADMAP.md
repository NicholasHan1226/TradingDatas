# SharedSignals Development Roadmap

## Current execution priority

SharedSignals remains a Tushare-like independent multi-source financial data platform.

The current provider-native production lane proves only three datasets:
`trade_cal`, `stock_basic`, and `daily`. The legacy 114-name inventory is a
migration input, not the full Tushare capability baseline. The versioned upstream
baseline is the pinned official capability index described in
[ADR-0009](docs/adr/ADR-0009-tushare-capability-cadence-retirement.md); its current
snapshot contains 239 unique API names, each of which must receive an explicit
scope/entitlement classification before any activation claim.

The implementation order is fixed:

1. Provider-native dataset bulk expansion
2. Internal consumer service (TradingAgent / MarketGraph)
3. Internal production stabilization
4. External Beta service

## Phase 1 — Provider-native bulk expansion

Goal:

Convert existing upstream capabilities into the generic provider-native pipeline.

Priorities:

- Generate a versioned capability snapshot from the pinned official Tushare source
- Classify every upstream API as in-scope, locked, unknown, excluded, retired, or non-data operation
- Complete reviewed upstream contracts for entitled domestic read datasets
- Expand registry-driven dataset definitions in bounded cadence batches
- Reuse generic adapter, ingest, receipt, storage and query pipeline
- Avoid dataset-specific collectors, tables and routes
- Implement the four generic request shapes and eight generic cadence classes in ADR-0009
- Derive missing partitions and bounded backfill from SQLite facts/receipts rather than latest-receipt time

Acceptance:

- New normal datasets can onboard through registry/config only
- No new public API route is required
- Provider data, receipt and metadata are queryable through the common data plane
- Every pinned upstream API has an explicit classification; no static count is used as runtime proof
- Every activated dataset has reviewed availability/cadence, entitlement, real receipt, query readback and observed timer evidence
- `trade_cal` has bounded history plus a future horizon, and `daily` catches up every missing trading partition

## Phase 2 — Internal service

Consumers:

- TradingAgent
- MarketGraph
- Internal research tools

Priorities:

- Stable catalog/query access
- Freshness and quality metadata
- Internal authentication
- Consumer contract validation
- Monitoring and recovery

## Phase 3 — Internal production

Priorities:

- Production backfill
- Data parity validation
- Consumer migration
- Runtime monitoring
- Backup and rollback verification
- Stop legacy writes, observe no-use, and retire approved old code, dependencies, docs, cron and units

Legacy data, facts, receipts, journals, audit evidence and rollback artifacts are
not deleted as part of code retirement.

## Phase 4 — External Beta

Only after internal service is stable:

- External tenant access
- Quota and entitlement
- External onboarding
- Public documentation
- External SLA

External productization must not delay completion of internal data service capability.

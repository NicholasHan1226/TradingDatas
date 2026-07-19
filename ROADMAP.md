# SharedSignals Development Roadmap

## Current execution priority

SharedSignals remains a Tushare-like independent multi-source financial data platform.

The implementation order is fixed:

1. Provider-native dataset bulk expansion
2. Internal consumer service (TradingAgent / MarketGraph)
3. Internal production stabilization
4. External Beta service

## Phase 1 — Provider-native bulk expansion

Goal:

Convert existing upstream capabilities into the generic provider-native pipeline.

Priorities:

- Complete upstream contract bundles
- Expand registry-driven dataset definitions
- Reduce unresolved datasets
- Reuse generic adapter, ingest, receipt, storage and query pipeline
- Avoid dataset-specific collectors, tables and routes

Acceptance:

- New normal datasets can onboard through registry/config only
- No new public API route is required
- Provider data, receipt and metadata are queryable through the common data plane

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

## Phase 4 — External Beta

Only after internal service is stable:

- External tenant access
- Quota and entitlement
- External onboarding
- Public documentation
- External SLA

External productization must not delay completion of internal data service capability.

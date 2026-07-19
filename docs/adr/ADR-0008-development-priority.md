# ADR-0008: SharedSignals Development Priority

## Status

Accepted

## Decision

SharedSignals development priority is changed to an internal-first sequence.

The approved order is:

```
Provider-native bulk expansion
        ↓
Internal consumer service
        ↓
Internal production stabilization
        ↓
External Beta service
```

## Context

SharedSignals is a Tushare-like financial data platform. Its first purpose is to provide stable, unified, high-quality financial data access for internal systems.

External service capabilities are valuable but should not delay the core data platform required by TradingAgent and MarketGraph.

## Non-goals before internal completion

The following are postponed:

- External tenant onboarding
- Commercial packaging
- Billing and usage products
- Public Beta launch
- External SLA commitments
- Customer-facing product expansion

## Implementation principles

- Keep provider-neutral contracts.
- Continue registry-driven onboarding.
- Do not create dataset-specific collectors for normal providers.
- Do not add trading, prediction or portfolio logic into SharedSignals.
- Keep TradingAgent and MarketGraph responsible for downstream intelligence.

## Phase exit criteria

Before external Beta begins:

- Core datasets are available through the common data plane.
- Internal consumers successfully use SharedSignals.
- Production migration and rollback procedures are verified.
- Data freshness, quality and lineage are observable.

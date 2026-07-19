# ADR-0009: Tushare Capability, Cadence, and Legacy Retirement

## Status

Accepted

## Context

The provider-native production lane currently proves three datasets only:

- `cn.market.trade_calendar` / `trade_cal`;
- `cn.equity.security_master` / `stock_basic`;
- `cn.equity.daily` / `daily`.

The legacy registry contains 114 Tushare API names, but that inventory is not a
complete upstream capability catalog and is not runtime evidence. At the pinned
official Tushare Skills source commit
`5e12b31d09123e262c5fb38564e80c26d05cb830`, the reviewed index contains 239
unique API names. That count is a versioned source snapshot, not a timeless
promise that Tushare will always expose exactly 239 APIs.

The legacy scheduler also groups APIs into historical tiers. Those tiers were
not systematically calibrated to each upstream publication time, entitlement,
request shape, correction window, or backfill requirement. A configured cron,
allowlist entry, HTTP 200 response, or `114/114` label cannot prove collection,
freshness, or queryability.

## Decision

### 1. Capability authority

SharedSignals will maintain one generated, versioned capability snapshot from a
pinned official Tushare source. Each upstream API is classified independently as
one of:

- `in_scope`: read-only domestic-market data eligible for contract review;
- `locked`: relevant but unavailable to the configured account;
- `unknown`: entitlement or contract evidence is incomplete;
- `excluded`: outside the approved market/product scope;
- `retired`: replaced or removed upstream with a recorded successor or reason;
- `non_data_operation`: write/account-management behavior that is not an ingest
  dataset.

The current 114-name legacy inventory remains a migration input only. It cannot
define upstream completeness, target activation, cadence, or public catalog
visibility.

### 2. Zero-code ordinary Tushare onboarding

All ordinary Tushare datasets use the same transport:

```text
api_name + params + fields -> fields/items
```

Adding a dataset may add or change reviewed registry/config entries, but must not
add a dataset-specific collector, business table, scheduler branch, query
compiler, fixture branch, or public route. The fixed data plane remains:

- `GET /v1/catalog`;
- `POST /v1/query`.

Only a real transport/authentication/pagination difference may add a
provider-level adapter.

### 3. Generic request shapes

The scheduler and runner support four declarative orchestration shapes exactly
once:

1. `snapshot_or_date_range`;
2. `entity_fanout`;
3. `dimension_fanout`;
4. `event_or_intraday_window`.

Dataset contracts declare request variants, window fields, fan-out sources,
pagination, budgets, and completeness policies. They do not add API-name
conditionals to Python code.

### 4. Cadence and backfill authority

Every activated dataset binds a reviewed upstream availability statement to one
of these generic cadence classes:

- `session_minute`;
- `postclose_daily`;
- `daily_reference`;
- `weekly`;
- `monthly`;
- `quarterly_reporting`;
- `event`;
- `on_demand`.

The contract also declares, when applicable:

- `availability_after_local`;
- `calendar_dataset_id`;
- `incremental_mode`;
- `correction_overlap_days` or `correction_overlap_bars`;
- `backfill_start_policy` and `backfill_chunk_span`;
- `future_horizon_days`;
- `rate_budget_class`;
- `request_variants`.

The scheduler derives missing partitions from registry plus SQLite facts and
receipts. It does not treat the most recent receipt timestamp as proof that all
partitions are present. Current-session work has priority over bounded backfill.
Retries are classified and bounded; throttling honors provider/account budgets
and deterministic jitter rather than creating a simultaneous request spike.

For the current three datasets:

- `daily` after 16:30 Asia/Shanghai is an acceptable post-close start time;
- `stock_basic` is a reference snapshot and must cover approved list-status
  variants rather than only silently treating `L` as the complete universe;
- `trade_cal` requires an initial bounded historical backfill and a future
  horizon; the current seven-day rolling window is not complete coverage.

### 5. Activation and evidence

The generated capability snapshot may catalog an API without activating it.
Activation requires a reviewed provider contract, entitlement evidence, a
bounded real canary, SQLite fact/receipt evidence, catalog/query readback, and
an observed cadence. External Beta additionally requires written upstream
redistribution authorization; payment, points, or token validity are not that
authorization.

### 6. Legacy retirement

Legacy code, dependencies, documents, cron jobs, units, routes, and local
worktrees are removed only in this order:

```text
provider-native replacement PASS
-> migrate every known consumer
-> stop legacy writes
-> observe no-use
-> prove rollback
-> delete approved code/dependencies/docs/runtime surfaces
```

Production databases, facts, receipts, journals, audit evidence, and rollback
artifacts are retained under the applicable data-retention policy; code
retirement does not authorize data deletion. A live writer or consumer blocks
deletion even if a replacement service is healthy.

## Consequences

- “Full Tushare integration” means every API in the pinned capability snapshot
  has an explicit classification, and every entitled in-scope read dataset has
  a reviewed contract, activation evidence, and truthful runtime state. It does
  not mean that all 239 APIs are blindly scheduled.
- Ordinary expansion is bulk registry/config work, not 239 independent software
  projects.
- Frequencies are evidence-backed per dataset and implemented through reusable
  cadence classes.
- The legacy 8082 lane, old SQLite, old cron, and migration documents remain
  protected while current consumers or writers exist, then are deleted through
  the recorded retirement gate.

## Non-goals

- Rebuilding or scraping data already supplied by Tushare.
- Activating Hong Kong, United States, cryptocurrency, prediction-market, or
  provider write/account-management APIs in the domestic first phase.
- Adding trading, prediction, portfolio, opening-gate, or risk semantics to
  SharedSignals.
- Enabling production timers before a fresh collector credential and observed
  one-shot readback are available.

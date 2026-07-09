# Tushare Activation Backlog

Last updated: 2026-07-09

SharedSignals currently has 115 Tushare names in the HTTP read allowlist. Of those, 114 are configured in production collection tiers and `rt_fut_min` is an independent 5-minute futures collector option. 0 planned interfaces remain in the activation backlog.

This ledger exists so interfaces stay managed scientifically: by market, module, read-model shape, and cadence. Do not treat an interface as 5-minute trading data merely because it is allowlisted or scheduled.

## Activation Rules

Every activation must prove:

1. The API has a market/module owner and a consumer purpose.
2. The collector writes non-empty provider rows into SQLite read model incrementally.
3. The read-model mapping is correct for the data shape.
4. The HTTP surface is available through `/tushare` or a business endpoint.
5. Empty, stale, entitlement, provider error, and SQLite-write-zero states are marked degraded or failed.
6. The cadence matches the data latency and does not compete with 5-minute trading reads.
7. Tests cover capability plan, mapping, API visibility, and at least one representative ingestion path.

## Batch Plan

Completed:

| Batch | APIs | Market/module | Read model | Cadence | Status |
| --- | --- | --- | --- | --- | --- |
| B1 relationship/reference | `ths_member`, `dc_member`, `index_member`, `index_member_all` | A-share themes and index membership | `market_relationships` | daily_reference | Scheduled in P3 reference lane |
| B2 daily supporting bars | `ths_daily`, `dc_daily`, `opt_daily`, `fut_holding` | A-share themes, options, futures | `market_bars_daily` / `market_factors` | daily_reference / postclose_daily / futures_settlement_daily | Scheduled in P3/P6 daily lanes |
| B3 financial/reporting details | `fina_audit`, `fina_mainbz`, `fund_portfolio` | A-share filings and fund holdings | `market_factors` for financial factors; `market_fund_portfolio` for fund holding details | daily_reporting_window / reporting_window | Scheduled in P2/P6 reporting lanes |
| B4 adjustments/reference enhancements | `bak_basic`, `fund_adj`, `cyq_perf`, `cyq_chips` | A-share reference, fund NAV support, chips | `market_factors` | daily_reference / postclose_daily / daily_nav | Scheduled in P1/P3/P6 supporting lanes |
| B5 hotness pilot | `ths_hot` | A-share theme/hotness | `market_factors` | intraday_or_daily_pilot | Scheduled in P3 daily pilot lane; do not promote to 5-minute until provider limits and consumer need are proven |

## Frequency Decisions

| Data class | Planned cadence | Trading interpretation |
| --- | --- | --- |
| Theme/index membership | Daily reference | Used for grouping and exposure; not a price signal. |
| Theme/sector daily bars | Post-close daily | Used for EOD cross-section; not 5-minute data. B2 is scheduled. |
| Options daily bars | Post-close daily | Used for derivatives context; not live order-book data. B2 is scheduled. |
| Futures holdings | Settlement daily | Used for positioning context; not execution input. B2 is scheduled. |
| Financial audit/main business/fund portfolio | Reporting window | Used for fundamentals; stale by nature compared with market bars. Scheduled but not intraday. |
| Chips/hotness | Post-close daily / daily pilot | May help event/risk context, but must not starve P0 5-minute collection. |

## Current Planned Interfaces

| API | Market/module | Cadence | Activation note |
| --- | --- | --- | --- |
| None | None | None | 0 planned remain after B5 activation. New interfaces must go through this checklist before scheduling. |

## Promotion Checklist

Before moving an API from `planned` to `scheduled`, update:

- `collectors/tushare/config.yaml`
- `storage/read_model_store.py`
- `config/tushare_capability_plan.yaml`
- `docs/market_capability_matrix.md`
- `API_CONTRACT.md`
- `STATUS.md`
- Coverage and ingestion tests
- Production cron only when the collector smoke proves rows written and API rows returned

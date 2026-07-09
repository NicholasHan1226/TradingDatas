# Tushare Activation Backlog

Last updated: 2026-07-09

SharedSignals currently has 115 Tushare names in the HTTP read allowlist. Of those, 106 are configured in production collection tiers, `rt_fut_min` is an independent 5-minute futures collector option, and 8 planned interfaces remain in the activation backlog.

This backlog exists so remaining interfaces are used scientifically: by market, module, read-model shape, and cadence. Do not mark an interface scheduled merely because it is allowlisted.

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

Remaining:

| Batch | APIs | Market/module | Target read model | Cadence | Why this order |
| --- | --- | --- | --- | --- | --- |
| B3 financial/reporting details | `fina_audit`, `fina_mainbz`, `fund_portfolio` | A-share filings and fund holdings | `market_factors` with report-period keys and raw row lineage | daily_reporting_window / reporting_window | These are reporting-window datasets and need per-symbol or per-period sharding proof. |
| B4 adjustments/reference enhancements | `bak_basic`, `fund_adj`, `cyq_perf`, `cyq_chips` | A-share reference, fund NAV support, chips | `market_assets` or `market_factors` after pilot field inspection | daily_reference / postclose_daily | Field shapes need a small pilot before final table mapping. |
| B5 hotness pilot | `ths_hot` | A-share theme/hotness | likely `market_events` or `market_factors`; final shape must be proven | intraday_or_daily_pilot | Hotness may be useful intraday, but frequency must be proven against provider limits, dedup, and API latency first. |

## Frequency Decisions

| Data class | Planned cadence | Trading interpretation |
| --- | --- | --- |
| Theme/index membership | Daily reference | Used for grouping and exposure; not a price signal. |
| Theme/sector daily bars | Post-close daily | Used for EOD cross-section; not 5-minute data. B2 is scheduled. |
| Options daily bars | Post-close daily | Used for derivatives context; not live order-book data. B2 is scheduled. |
| Futures holdings | Settlement daily | Used for positioning context; not execution input. B2 is scheduled. |
| Financial audit/main business/fund portfolio | Reporting window | Used for fundamentals; stale by nature compared with market bars. |
| Chips/hotness | Pilot first | May help event/risk context, but must not starve P0 5-minute collection. |

## Current Planned Interfaces

| API | Market/module | Cadence | Activation note |
| --- | --- | --- | --- |
| `cyq_perf` | A-share flow/depth/reference | postclose_daily | Pilot field shape before factor mapping. |
| `cyq_chips` | A-share flow/depth/reference | postclose_daily | Pilot field shape and volume before scheduling. |
| `fina_audit` | A-share fundamentals | daily_reporting_window | Financial-period factor rows; verify per-symbol query shape. |
| `fina_mainbz` | A-share fundamentals | daily_reporting_window | Main-business breakdown needs raw lineage and period keys. |
| `bak_basic` | A-share reference | daily_reference | Reference enrichment; verify provider rows are non-empty. |
| `ths_hot` | A-share hotness | intraday_or_daily_pilot | Pilot cadence before high-frequency use. |
| `fund_adj` | Funds | daily_nav | NAV adjustment support; map after field proof. |
| `fund_portfolio` | Funds | reporting_window | Fund holdings/reporting-period dataset. |

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

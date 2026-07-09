# SharedSignals Market Capability Matrix

Last updated: 2026-07-09

This document is the market-facing capability and cadence guide for SharedSignals. It complements the internal Tushare P0-P6 tier config and prevents external consumers from treating every allowlisted provider API as an active production feed.

## Current Decision

SharedSignals should be managed by market and data-latency need, not by provider name alone.

- `collectors/tushare/config.yaml` is the active Tushare collection plan: 83 configured interfaces.
- `api_server.py` `ALLOWED_TUSHARE_APIS` is the read allowlist: 115 names.
- `config/tushare_capability_plan.yaml` is the market/module management plan for all 115 allowlisted names.
- HTTP API is the consumer surface: external agents, MarketGraph, and TradingAgent must read SharedSignals API/read-model outputs, not provider APIs or local files.
- A capability is production-ready only when it has provider collection, read-model mapping, HTTP/API visibility, freshness expectations, rate protection, and degraded/empty semantics.

## Market Matrix

| Market / lane | Active sources | Active HTTP/read surface | Current cadence | Freshness expectation | Status |
| --- | --- | --- | --- | --- | --- |
| A-share intraday | Tushare `stk_mins`, `rt_min` | `/realtime_5min`, `/market_data?freq=5m`, `/tushare` | Trading window every 5 minutes | Trading-session latest bar; fail closed outside usable data | Active |
| A-share daily/technical | Tushare `daily`, `stk_factor`, `stk_factor_pro`, `daily_basic`, `adj_factor` | `/market_data`, `/tushare` | Post-close daily | Latest trading day after EOD collection | Active |
| A-share flow/depth/events-derived data | Tushare `moneyflow`, `moneyflow_hsgt`, `margin`, `margin_detail`, `top_list`, `limit_list`, `limit_list_d`, `limit_step`, `stk_auction`, `stk_limit`, `block_trade` | `/capital_flow`, `/events`, `/tushare` | Post-close daily | Latest trading day or latest collected event row | Active, not buy/sell logic |
| A-share fundamentals/reference | Tushare `fina_indicator`, financial statements, holders, pledge, company, concept, index membership, calendar | `/fundamentals`, `/reference`, `/industry`, `/tushare` | Daily/reference windows | Latest available reporting/reference snapshot | Active |
| China futures daily | Tushare `fut_basic`, `fut_daily` | `/market_data`, `/tushare` | Daily settlement window | Latest futures trading day after settlement | Active |
| China futures intraday | AkShare/Sina default; Tushare `rt_fut_min` only when explicitly enabled | `/realtime_5min?market=Futures`, `/realtime_5min?market=CNFutures` | Day/night sessions every 5 minutes | 10 minute default freshness during active session | Active |
| Crypto | Binance ticker and 1d klines | `/crypto`, `/market_data?market=Crypto` | Ticker every 5 minutes; daily klines hourly | Intraday <= 30 minutes | Active |
| Polymarket | Polymarket markets/prices | `/pm_markets`, `/pm_prices` | Every 5 minutes | Prices <= 30 minutes | Active |
| US/HK | Tushare `us_daily`, `us_basic`, `hk_daily`, `hk_basic`, HK financials | `/market_data`, `/reference`, `/tushare` | Daily around local close windows | Latest effective trading day | Active but daily |
| Macro/global | Tushare macro, rates, FX, global indices, repo | `/macro`, `/market_data`, `/tushare` | Daily / low-frequency | Latest expected macro period or trading day | Active, not intraday |
| ETF/fund/convertible bond | Tushare `etf_basic`, `fund_basic`, `fund_daily`, `fund_nav`, `cb_daily` | `/reference`, `/market_data`, `/tushare` | Daily | Latest trading day or latest fund NAV date | Active as support data |
| News/announcements/reports | Tushare `news`, `major_news`, `cctv_news`, `anns_d`, `report_rc` | `/events`, `/sentiment`, `/tushare` | P6 daily plus dedicated pilot wrapper available | Latest collected event row; high-frequency requires pilot proof | Active event lane pilot |
| RSS/RSSHub/Tavily/DeepSeek | Retired/deferred | None as production collector | None | Not applicable | Disabled until re-designed as SharedSignals collectors |

## Why Not Use Every Tushare Interface

Using every Tushare interface by default is not a good operating model.

- Some interfaces are irrelevant to the current trading/research lanes and would add noise without a consumer.
- Some are low-frequency by nature, such as fundamentals, macro, holders, funds, and reference data. Polling them every few minutes wastes quota and database capacity.
- Some interfaces require special parameters, entitlement, exchange calendar logic, or per-market timing. They should not be enabled until read-model mapping and degraded behavior are proven.
- Some allowlisted names exist for compatibility or future expansion. Allowlisting means "safe to query from the read model when data exists", not "scheduled in production".
- Opening every interface increases provider pressure, SQLite write contention, health noise, and API confusion during market hours.

New provider interfaces should be promoted only after this checklist is satisfied:

1. Market owner and consumer are identified.
2. Collection cadence is justified by data latency and business use.
3. Read-model table mapping exists.
4. HTTP/API read path is available or intentionally delegated.
5. Empty, delayed, entitlement, and provider-error states return degraded/fail-closed semantics.
6. Rate/concurrency protection is documented.
7. Capability coverage tests are updated.

## Frequency Policy

| Data class | Recommended cadence | Reason |
| --- | --- | --- |
| Trading-session prices | 5 minutes or faster only when a proven collector supports it | Trading decisions need fresh bars, but collection must not block other lanes |
| Prediction market / crypto prices | 5 minutes | 24/7 market freshness is useful and current collectors support it |
| Daily market bars | Post-close daily | Intraday polling does not improve final EOD data |
| Fundamentals and financial statements | Daily or after reporting windows | Provider data updates by filing/reporting cycle |
| Macro and rates | Daily / low-frequency | Most series do not update intraday |
| Reference data | Daily or slower | Symbols, concepts, calendars, and metadata rarely need intraday refresh |
| News and announcements | Separate event lane; not mixed into P6 daily if trading/event risk depends on it | Event freshness has different dedup, source, and alert requirements |
| DuckDB mirror | Hourly or slower | Analytics mirror must not compete with 5-minute trading reads |

## News And Announcement Lane

News and announcements should become an independent functional lane inside SharedSignals if they are used for trading risk, event monitoring, or external-agent research. The repository now includes `cron/tushare_events_collect.sh`, which runs selected P6 event APIs only and avoids high-frequency execution of the whole P6 miscellaneous tier.

This should not become a separate repository and should not generate trading decisions. It should stay in SharedSignals as an event collection and normalization lane.

Recommended design:

- Keep output in `market_events`.
- Keep source-specific collectors under a clear event lane, for example `collectors/events/` or a dedicated `P_event_*` schedule.
- Separate event cadences from P6 miscellaneous daily jobs.
- Track `event_hash`, provider, event type, market, symbol, event time, collected time, source URL, and degraded reasons.
- Use source-aware dedup and source priority.
- Add event-specific freshness checks to `health_sla` without letting research-only event staleness restart the whole API.
- Keep classification, sentiment, impact scoring, and trade decisions outside SharedSignals unless they are explicitly defined as read-only metadata.

Suggested event cadences for evaluation:

| Event type | Candidate cadence | Notes |
| --- | --- | --- |
| Exchange/company announcements | 10-30 minutes during pre-open, lunch, post-close, and evening disclosure windows | Highest priority event lane if announcements affect risk or order blocking |
| General market news | 15-60 minutes if provider supports incremental pulls | Do not use high frequency until provider limits and dedup are verified |
| CCTV/major scheduled news | Hourly or daily | Often not a 5-minute trading signal |
| Research reports | Daily or several times per day | Usually research context, not immediate execution input |

The pilot wrapper defaults to `anns_d,news,major_news,cctv_news,report_rc` with a 2-day lookback. It can be narrowed through `SHAREDSIGNALS_EVENT_APIS` and `SHAREDSIGNALS_EVENT_LOOKBACK_DAYS`.

Before increasing event frequency, run a small live pilot:

1. Pick one source, such as announcements.
2. Collect into `market_events` only.
3. Prove dedup ratio, rows written, provider latency, database write cost, and API read latency.
4. Add a freshness SLA that reports degraded without triggering trade execution.
5. Only then connect TradingAgent or MarketGraph consumers.

## External Agent Rule

External agents should receive this simplified rule:

Use SharedSignals HTTP API by market and endpoint. Do not infer that all Tushare allowlisted names are production-fresh. Always check `metadata.degraded`, `degraded_reasons`, row timestamps, and market-specific freshness expectations.

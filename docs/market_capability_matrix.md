# SharedSignals Market Capability Matrix

Last updated: 2026-07-09

This document is the market-facing capability and cadence guide for SharedSignals. It complements the internal Tushare P0-P7 tier config and prevents external consumers from treating every allowlisted provider API as an active production feed.

## Current Decision

SharedSignals should be managed by market and data-latency need, not by provider name alone.

- `collectors/tushare/config.yaml` is the active Tushare collection plan: 114 configured interfaces.
- `api_server.py` `ALLOWED_TUSHARE_APIS` is the read allowlist: 115 names.
- `config/tushare_capability_plan.yaml` is the market/module management plan for all 115 allowlisted names.
- `docs/tushare_activation_backlog.md` is the activation ledger; 0 planned interfaces remain after B5 activation.
- `/agent_config` and `config/external_agent_api_config.json` expose the external-agent integration contract and frequency labels.
- HTTP API is the consumer surface: external agents, MarketGraph, and TradingAgent must read SharedSignals API outputs, not provider APIs, local files, SQLite files, or sibling repo internals.
- SharedSignals supports minute/5-minute trading data inputs, but not millisecond HFT, order matching, order placement, funds, accounts, or execution receipts.
- A capability is production-ready only when it has provider collection, read-model mapping, HTTP/API visibility, freshness expectations, rate protection, and degraded/empty semantics.

## Market Matrix

| Market / lane | Active sources | Active HTTP/read surface | Current cadence | Freshness expectation | Status |
| --- | --- | --- | --- | --- | --- |
| A-share intraday | Tushare `stk_mins`, `rt_min` | `/realtime_5min`, `/market_data?freq=5m`, `/tushare` | Trading window every 5 minutes | Trading-session latest bar; fail closed outside usable data | Active |
| A-share daily/technical | Tushare `daily`, `stk_factor`, `stk_factor_pro`, `daily_basic`, `adj_factor` | `/market_data`, `/tushare` | Post-close daily | Latest trading day after EOD collection | Active |
| A-share flow/depth/events-derived data | Tushare `moneyflow`, `moneyflow_hsgt`, `margin`, `margin_detail`, `top_list`, `limit_list`, `limit_list_d`, `limit_step`, `stk_auction`, `stk_limit`, `block_trade`, `cyq_perf`, `cyq_chips` | `/capital_flow`, `/events`, `/tushare` | Post-close daily | Latest trading day or latest collected event row | Active, not buy/sell logic |
| A-share fundamentals/reference | Tushare `fina_indicator`, financial statements, holders, pledge, company, concept, index membership, calendar, `fina_audit`, `fina_mainbz`, `bak_basic` | `/fundamentals`, `/reference`, `/industry`, `/tushare` | Daily/reference/reporting windows | Latest available reporting/reference snapshot | Active |
| A-share theme/index relationships | Tushare `ths_member`, `dc_member`, `index_member`, `index_member_all` | `/tushare` | Daily reference | Latest collected membership snapshot | Active relationship lane |
| A-share theme/index daily bars | Tushare `ths_daily`, `dc_daily` | `/tushare` | Daily reference / post-close daily | Latest collected theme/index EOD row | Active daily support lane |
| A-share hotness pilot | Tushare `ths_hot` | `/tushare` | Daily pilot | Latest collected hotness/rank factor row | Active support lane, not 5-minute data |
| China futures daily | Tushare `fut_basic`, `fut_daily` | `/market_data`, `/tushare` | Daily settlement window | Latest futures trading day after settlement | Active |
| China futures intraday | AkShare/Sina default; Tushare `rt_fut_min` only when explicitly enabled | `/realtime_5min?market=Futures`, `/realtime_5min?market=CNFutures` | Day/night sessions every 5 minutes | 10 minute default freshness during active session | Active |
| Crypto | Binance ticker and 1d klines | `/crypto`, `/market_data?market=Crypto` | Ticker every 30 minutes; daily klines every 6 hours | Intraday <= 45 minutes | Active, reduced hot-path load |
| Polymarket | Polymarket markets/prices | `/pm_markets`, `/pm_prices` | Every 30 minutes | Prices <= 45 minutes | Active, reduced hot-path load |
| US/HK | Tushare `us_daily`, `us_basic`, `hk_daily`, `hk_basic`, HK financials | `/market_data`, `/reference`, `/tushare` | Daily around local close windows | Latest effective trading day | Active but daily |
| Macro/global | Tushare macro, rates, FX, global indices, repo | `/macro`, `/market_data`, `/tushare` | Daily / low-frequency | Latest expected macro period or trading day | Active, not intraday |
| ETF/fund/convertible bond/options | Tushare `etf_basic`, `fund_basic`, `fund_daily`, `fund_nav`, `fund_adj`, `fund_portfolio`, `fund_share`, `fund_div`, `cb_daily`, `cb_basic`, `cb_issue`, `opt_basic`, `opt_daily` | `/reference`, `/market_data`, `/tushare` | Daily / reporting windows | Latest trading day or latest fund/NAV/reference/reporting date | Active as support data |
| Low-frequency A-share/index bars | Tushare `weekly`, `monthly`, `index_weekly`, `index_monthly` | `/tushare` | P7 weekly low-frequency lane | Latest weekly/monthly period | Active low-frequency lane |
| News/announcements/reports | Tushare `news`, `major_news`, `cctv_news`, `anns_d`, `report_rc` | `/events`, `/sentiment`, `/tushare` | 30-minute full event lane; 15-minute supplemental pilot for `news,major_news` only | Latest collected event row; monitor dedup and provider latency | Active event lane |
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
| Prediction market / crypto prices | 30 minutes by default | Useful for research and slower trading workflows, but should not compete with A-share/Futures 5-minute write paths on the current server |
| Daily market bars | Post-close daily | Intraday polling does not improve final EOD data |
| Fundamentals and financial statements | Daily or after reporting windows | Provider data updates by filing/reporting cycle |
| Macro and rates | Daily / low-frequency | Most series do not update intraday |
| Reference data | Daily or slower | Symbols, concepts, calendars, and metadata rarely need intraday refresh |
| News and announcements | Separate event lane; not mixed into P6 daily if trading/event risk depends on it | Event freshness has different dedup, source, and alert requirements |
| DuckDB mirror | Hourly or slower | Analytics mirror must not compete with 5-minute trading reads |

## Server Load Policy

The current production host can support the active SharedSignals cadence when hot paths are separated. It should not run every source at 5-minute frequency.

- Keep A-share P0 and China futures intraday on 5-minute schedules because they feed minute-level trading workflows.
- Keep Crypto and Polymarket on 30-minute schedules unless a stronger storage/write-queue layer is introduced.
- Keep DuckDB mirror and capability scan outside 09:00-15:59 China trading hours.
- Run patrol and health SLA on staggered minutes so they do not start on the same minute as market-data writers.
- New data sources must declare market, cadence, freshness SLA, write path, API endpoint, degraded behavior, and expected write cost before production scheduling.

## News And Announcement Lane

News and announcements are an independent functional lane inside SharedSignals for trading risk, event monitoring, and external-agent research. The repository includes `cron/tushare_events_collect.sh`, which runs selected P6 event APIs only and avoids high-frequency execution of the whole P6 miscellaneous tier.

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

The event wrapper defaults to `anns_d,news,major_news,cctv_news,report_rc` with a 2-day lookback. It can be narrowed through `SHAREDSIGNALS_EVENT_APIS` and `SHAREDSIGNALS_EVENT_LOOKBACK_DAYS`. `news` and `major_news` require full datetime bounds, while announcements and reports continue to use `YYYYMMDD` date bounds.

Low-frequency bars are a separate lane. `P7_low_frequency` is run by `cron/tushare_low_frequency_collect.sh` and defaults to `weekly,monthly,index_weekly,index_monthly`. Keep these out of daily P6 so weekly/monthly all-market pulls do not run every night.

Completed planned-to-scheduled activation:

| Lane | APIs | Cadence |
| --- | --- | --- |
| A-share events / post-close | `suspend_d` | Post-close daily |
| A-share reference | `namechange`, `ths_index`, `dc_index`, `index_classify` | Daily reference |
| Funds / convertible bonds / options support | `fund_share`, `fund_div`, `cb_basic`, `cb_issue`, `opt_basic` | Daily reference or daily reporting |
| Futures reference | `ft_limit` | Daily reference |
| Low-frequency bars | `weekly`, `monthly`, `index_weekly`, `index_monthly` | Weekly wrapper, with monthly rows included for refresh |
| Relationship/reference | `ths_member`, `dc_member`, `index_member`, `index_member_all` | Daily reference |
| Daily supporting bars / holdings | `ths_daily`, `dc_daily`, `opt_daily`, `fut_holding` | Daily reference / post-close / settlement daily |
| Final factor/reporting support | `bak_basic`, `cyq_perf`, `cyq_chips`, `fina_audit`, `fina_mainbz`, `fund_adj`, `ths_hot` as factors; `fund_portfolio` as fund holding details | Daily reference / post-close / reporting windows / daily pilot |

No planned Tushare APIs remain. Future new interfaces must still prove read-model mapping, non-empty or properly degraded provider behavior, HTTP visibility, cadence fit, and rate protection before scheduling.

Before increasing event frequency, run a small live pilot:

1. Pick one source, such as announcements.
2. Collect into `market_events` only.
3. Prove dedup ratio, rows written, provider latency, database write cost, and API read latency.
4. Add a freshness SLA that reports degraded without triggering trade execution.
5. Only then connect TradingAgent or MarketGraph consumers.

## External Agent Rule

External agents should receive this simplified rule:

Use SharedSignals HTTP API by market and endpoint. Do not infer that all Tushare allowlisted names are production-fresh. Always check `metadata.degraded`, `degraded_reasons`, row timestamps, and market-specific freshness expectations.

Operational handoff:

- Copy-paste prompt: `docs/external_agent_api_prompt.md`
- Machine-readable config: `GET /agent_config`
- Remaining Tushare activation plan: `docs/tushare_activation_backlog.md`
- Event lane guide: `docs/event_lane.md`
- New source onboarding checklist: `docs/data_source_onboarding.md`

`GET /agent_config` lists the full 21 HTTP paths as discoverable integration surface: health/config/cache paths, business data paths, delegated association/impact projections, and `/tushare`. External agents should still prefer the business endpoint that matches their market and cadence, then fall back to `/tushare` only for native Tushare-shaped read-model output.

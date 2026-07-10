# SharedSignals Market Capability Matrix

Last updated: 2026-07-10

This document is the market-facing capability and cadence guide for SharedSignals. It complements the internal Tushare P0-P7 tier config and prevents external consumers from treating every allowlisted provider API as an active production feed.

## Current Decision

SharedSignals should be managed by market and data-latency need, not by provider name alone.

- `collectors/tushare/config.yaml` is the active Tushare collection plan: 113 configured interfaces.
- `api_server.py` `ALLOWED_TUSHARE_APIS` is the read allowlist: 114 names.
- `config/tushare_capability_plan.yaml` is the market/module management plan for all 114 allowlisted names.
- `docs/tushare_activation_backlog.md` is the activation ledger; 0 planned interfaces remain after B5 activation.
- `/agent_config` and `config/external_agent_api_config.json` expose the external-agent integration contract and frequency labels.
- HTTP API is the consumer surface: external agents, MarketGraph, and TradingAgent must read SharedSignals API outputs, not provider APIs, local files, SQLite files, or sibling repo internals.
- SharedSignals supports minute/5-minute trading data inputs, but not millisecond HFT, order matching, order placement, funds, accounts, or execution receipts.
- A capability is production-ready only when it has provider collection, read-model mapping, HTTP/API visibility, freshness expectations, rate protection, and degraded/empty semantics.

## Market Matrix

| Market / lane | Active sources | Active HTTP/read surface | Current cadence | Freshness expectation | Status |
| --- | --- | --- | --- | --- | --- |
| A-share intraday | Tushare `rt_min` | `/realtime_5min`, `/market_data?freq=5m`, `/tushare` | Trading window every 5 minutes; complete active universe in chunks of at most 300 symbols; retry only failed batches after request-level retries | Fresh-symbol coverage >= 80% during continuous trading; 15:05 gate accepts the provider's last available 14:45 label as an intraday snapshot only; official close comes from EOD daily data | Active |
| A-share daily/technical | Tushare `daily`, `stk_factor`, `stk_factor_pro`, `daily_basic`, `adj_factor` | `/market_data`, `/tushare` | Post-close daily | Latest trading day after EOD collection | Active |
| A-share flow/depth/events-derived data | Tushare `moneyflow`, `moneyflow_hsgt`, `margin`, `margin_detail`, `top_list`, `limit_list`, `limit_list_d`, `limit_step`, `stk_auction`, `stk_limit`, `block_trade`, `cyq_perf`, `cyq_chips` | `/capital_flow` reads moneyflow/northbound/margin factors, `/events` reads event lane, `/tushare` for native dimensions | Post-close daily | Latest trading day or latest collected event row | Active, not buy/sell logic |
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
| News/announcements/reports | Tushare `news`, `major_news`, `cctv_news`, `anns_d`, `report_rc` | `/events` and `/tushare` read raw event rows; `/sentiment` derives from configured sentiment event types in `reference/sentiment_event_types.yaml` | 30-minute full event lane; 15-minute supplemental pilot for `news,major_news` only | Latest collected event row; monitor dedup and provider latency | Active event lane |
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

- Keep A-share P0 and China futures intraday on 5-minute schedules because they feed minute-level trading workflows. A-share P0 must batch the complete active universe and must not restore rotating subsets.
- Keep Crypto and Polymarket on 30-minute schedules unless a stronger storage/write-queue layer is introduced.
- Keep DuckDB mirror and capability scan outside 09:00-15:59 China trading hours.
- Run patrol and health SLA on staggered minutes so they do not start on the same minute as market-data writers.
- New data sources must declare market, cadence, freshness SLA, write path, API endpoint, degraded behavior, and expected write cost before production scheduling.

## Horizontal Expansion Queue

SharedSignals is ready to add new sources horizontally, but new sources are not active merely because they appear in a plan. The active planning file is `config/source_expansion_priority.yaml`; every item in it is `planned` and `production_ready: false` until its collector, read-model mapping, API surface, SLA, rate limit, degraded behavior, tests, and pilot evidence are complete.

| Batch | Market / lane | Candidate sources | Default cadence | Current status |
| --- | --- | --- | --- | --- |
| `B1_event_risk_official_sources` | A-share/US event risk | Official exchange announcements, SEC EDGAR filings/company facts | 10-30 minute disclosure-window pilot for announcements; 30-60 minute pilot for filings | Planned only; SEC EDGAR has a manual pilot collector, not scheduled |
| `B2_macro_official_sources` | Global/US macro and rates | FRED-style macro/rates series, official Treasury yield curve | Daily or provider release schedule | Planned only; low write cost and useful redundancy |
| `B3_market_redundancy_and_altdata` | Crypto and prediction markets | Secondary crypto exchange, secondary prediction-market/archive source | 30 minutes or slower by default | Planned only; activate after hot paths stay stable |

Horizontal expansion must stay DB-first and API-first: collectors may call providers, but readers, external agents, MarketGraph, and TradingAgent must not bypass SharedSignals or read provider/local files directly.

## Module And API Catalog

The module/API planning source is `config/api_module_catalog.yaml`. Use it before adding a collector or a public endpoint.

| Module family | Default API surface | Endpoint policy |
| --- | --- | --- |
| Intraday prices | `/realtime_5min`, `/market_data`, `/tushare` | Reuse hot-path endpoints; no new 5-minute endpoint without write-pressure proof. |
| Daily/reference/fundamentals | `/market_data`, `/reference`, `/industry`, `/fundamentals`, `/capital_flow`, `/tushare` | Reuse read-model tables and endpoint filters before adding any provider-shaped API. |
| Events/disclosures/filings | `/events`, `/sentiment`, `/fundamentals`, `/tushare` | Add sources into `market_events` or `market_factors`; only add an endpoint for a new query shape. |
| Macro/rates/FX | `/macro`, `/market_data`, `/tushare` | Degrade by series and reuse `/macro` unless a series family needs a distinct SLA/auth contract. |
| Crypto and prediction markets | `/crypto`, `/market_data`, `/pm_markets`, `/pm_prices` | Secondary providers enrich or cross-check existing surfaces; lineage must identify the source. |
| Delegated research projections | `/associations`, `/impacts` | Keep as read-only synced projections; empty/degraded is valid when upstream research has not published. |

New endpoints are allowed only when existing surfaces cannot express the data without ambiguous parameters, mixed freshness semantics, or incorrect auth/rate-limit behavior.

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

`GET /agent_config` lists the full 23 HTTP paths as discoverable integration surface: health/config/cache paths, `/source_status` source governance status, `/opening_gate` session readiness, business data paths, delegated association/impact projections, and `/tushare`. External agents should still prefer the business endpoint that matches their market and cadence, then fall back to `/tushare` only for native Tushare-shaped read-model output.

# SharedSignals Data Source Onboarding

Last updated: 2026-07-09

## Purpose

This is the minimum governance checklist for adding a new data source or expanding an existing source in SharedSignals.

SharedSignals should scale by market, module, cadence, read-model mapping, and API contract. It should not restore the old generic `collectors/registry.yaml`, CSV/NDJSON staging bridge, provider fallback, or sibling-repo file reads.

The first horizontal expansion queue is tracked in `config/source_expansion_priority.yaml`. Entries in that file are planned-only candidates until their collector, direct SQLite write path, API/read-model exposure, freshness SLA, rate limit, degraded behavior, and tests pass the acceptance gate below.

Before adding a source, map it to `config/api_module_catalog.yaml`. The catalog defines the canonical module, target read-model tables, reusable HTTP surfaces, cadence class, and the narrow conditions for adding a new endpoint.

## 新增数据源原则

新增数据源必须先进入能力计划和 read-model/API 契约，再进入生产调度。没有直接入库、API 可读、频率声明、降级语义和覆盖测试的源，只能保持 `planned` 或实验状态。

## Required Fields

Every new source or dataset must declare:

| Field | Meaning |
| --- | --- |
| `source_id` | Stable internal source id, such as `tushare_news` or `binance_ticker`. |
| `provider` | External provider or upstream system. |
| `market` | Canonical market, such as `Ashare`, `Futures`, `Crypto`, `PredictionMarkets`, `US`, `HK`, `Global`, `Events`. |
| `module` | Functional lane, such as `ashare_intraday`, `event_news_announcements_reports`, `macro`, or `funds_etf_options`. |
| `api_name_or_dataset` | Provider API name or dataset name. |
| `activation_mode` | `scheduled`, `independent`, `event_lane`, or `planned`. |
| `cadence_class` | Collection cadence label, such as `trading_session_5min`, `30min_crypto`, `30min_active_window`, `postclose_daily`, or `weekly_reference`. |
| `freshness_sla` | Maximum expected age or trading-day lag. |
| `target_tables` | SQLite read-model table(s) written. |
| `write_path` | Collector/script that writes read-model rows. |
| `rate_limit` | Provider rate/concurrency guard. |
| `degraded_behavior` | Empty, stale, entitlement, provider error, and timeout behavior. |
| `http_surface` | API/reader endpoint or explicit reason it is internal-only. |
| `owner_consumer` | Current consumer, such as MarketGraph, TradingAgent, external agent, or internal health. |
| `expected_write_cost` | Expected row volume/write pressure and hot-path risk. |

## Required Artifacts

Production-ready means all of these exist or are explicitly marked not applicable:

| Artifact | Required result |
| --- | --- |
| Collector config | Provider params, frequency, rate guard, timeout, retry, fields. |
| Capability plan row | Market/module/cadence/activation mode are registered. |
| Read-model mapping | Rows write directly to SQLite read model; no CSV-only success. |
| HTTP/API visibility | Consumer can read through SharedSignals API/reader or sees explicit degraded semantics. |
| Cron wrapper | Scheduled jobs use flock, logs, timeout, env loading, and clear ownership. |
| Health/SLA rule | Freshness and missing/empty behavior are observable. |
| Tests | Coverage proves config, mapping, API visibility, frequency, and no retired fallback. |
| Docs | Market matrix, API contract, and external-agent config are updated when consumer-facing. |

## Module And API Planning

Use this decision order for every new source:

1. Choose the closest `module` in `config/api_module_catalog.yaml`.
2. Confirm the source can write one of that module's canonical read-model tables.
3. Reuse the module's default HTTP surface unless the dataset has a genuinely new query shape, auth scope, freshness/SLA contract, pagination model, or rate limit.
4. Add a new API endpoint only after the new surface is documented in `API_CONTRACT.md`, `/agent_config`, capability tests, auth scope checks, and consumer-facing prompt/docs.

This keeps horizontal data expansion broad while keeping the public API stable and understandable.

## Priority Queue

New external sources should be promoted in this order unless a production incident changes the business priority:

| Batch | Focus | Production rule |
| --- | --- | --- |
| `B1_event_risk_official_sources` | Official event, filing, and disclosure coverage. | Pilot first, write only to read-model tables, and observe 1-2 trading days before scheduled mode. |
| `B2_macro_official_sources` | Official macro, rates, and low-frequency redundancy. | Daily pilot first; stale macro series must degrade by source, not block price feeds. |
| `B3_market_redundancy_and_altdata` | Crypto and prediction-market redundancy or alternative data. | Keep 30-minute or slower by default; no 5-minute mode without hot-path write-pressure proof. |

Do not install any planned candidate into production cron until it has passed the full gate. Planned source ids are documentation and work-order targets, not active data feeds.

## Lightweight Registry Pattern

Do not create a new central registry unless the existing files become unmaintainable. The current lightweight registry is the combination of:

- `collectors/<source>/config.yaml`,
- `config/<source>_capability_plan.yaml` or the existing source capability plan,
- `storage/read_model_store.py` table mapping,
- `api_server.py` endpoint/allowlist,
- `config/external_agent_api_config.json` when externally consumable,
- `docs/market_capability_matrix.md`,
- `tests/test_capability_coverage.py` or a source-specific coverage test.

This keeps governance explicit without rebuilding the retired generic registry/orchestrator layer.

## Acceptance Gate

A dataset is not production-ready until it can:

1. collect provider rows with rate protection,
2. validate/deduplicate rows,
3. write non-empty provider rows into SQLite read-model tables,
4. expose DB-first reader/API output or intentional degraded behavior,
5. report freshness and collection status,
6. pass coverage tests,
7. document cadence and external-agent usage,
8. fail closed without calling providers, CSV, NDJSON, SQLite files, old directories, or sibling repo internals from consumer systems.

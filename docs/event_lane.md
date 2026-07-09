# SharedSignals Event Lane

Last updated: 2026-07-09

## Purpose

The event lane is the SharedSignals module for news, announcements, research reports, and other event-style market inputs. It collects and normalizes provider rows into SQLite `market_events`, then exposes them through `/events`, `/sentiment`, and `/tushare`.

It does not classify trades, generate signals, score impact, place orders, or write execution decisions. MarketGraph and TradingAgent may consume the read-model output, but they must not bypass SharedSignals to call event providers or old RSS directories.

## Active Sources

| Source | API names | Collection path | Output |
| --- | --- | --- | --- |
| Tushare event APIs | `news`, `major_news`, `cctv_news`, `anns_d`, `report_rc` | `cron/tushare_events_collect.sh` with `--only-api` | `market_events` |
| RSS/RSSHub | retired/deferred | none | none |
| Tavily/DeepSeek event input | disabled/deferred | none | none |

`cron/tushare_events_collect.sh` deliberately runs a selected subset of `P6_other_daily`. It does not run the whole P6 miscellaneous tier every 30 minutes.

## Cadence

The active production event lane runs every 30 minutes from 08:00 to 23:59 Monday through Saturday. A supplemental pilot runs only `news,major_news` at minute 15 and 45 in the same active window. This cadence is a collection window for event freshness, not a 5-minute price feed.

| Event type | Current cadence | Operating note |
| --- | --- | --- |
| `news` | 30-minute full lane + 15-minute supplemental pilot | Useful for market event monitoring and external-agent research. |
| `major_news` | 30-minute full lane + 15-minute supplemental pilot | Same lane as general news. |
| `cctv_news` | 30-minute active window in the current wrapper | Candidate for future broadcast-window optimization after production observation. |
| `anns_d` | 30-minute active window in the current wrapper | Announcement rows may arrive in batches; do not treat as intraday price data. |
| `report_rc` | 30-minute active window in the current wrapper | Research-report context; not immediate execution input. |

Before expanding the pilot, prove provider latency, dedup ratio, SQLite write cost, API read latency, and freshness SLA behavior on one source first. Do not increase `anns_d`, `report_rc`, or `cctv_news` without separate evidence.

## Consumer Rules

Consumers must:

1. Read `/health`, `/agent_config`, and `/source_status` before using event rows.
2. Read `/events` for news, announcements, reports, and event rows.
3. Treat `/sentiment` as a derived event projection that may be degraded or empty until a sentiment source is explicitly enabled.
4. Check `metadata.degraded`, `metadata.degraded_reasons`, `metadata.freshness`, row `event_time`, row `collected_at`, and `provenance.source_id`.
5. Fail closed when events are stale, empty, or degraded.

Consumers must not:

1. Call Tushare, RSSHub, Tavily, DeepSeek, CSV, NDJSON, SQLite files, old RSS directories, or sibling repo internals directly.
2. Treat an event row as 5-minute tradable price data.
3. Use SharedSignals event rows alone to generate orders.

## Onboarding More Event Sources

New event providers must follow `docs/data_source_onboarding.md`. At minimum they need:

- a source id and provider id,
- a market/module assignment,
- a cadence and freshness SLA,
- direct SQLite read-model writes into `market_events` or a documented projection table,
- source-aware dedup keys,
- HTTP/API visibility or explicit degraded behavior,
- capability coverage tests,
- rollback and disable instructions.

Do not restore `collectors/registry.yaml`, old RSS collectors, file staging bridges, or CSV-only success paths.

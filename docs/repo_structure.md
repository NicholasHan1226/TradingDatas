# Three-Repo Architecture

## Overview

The finance system is split into three independent Git repositories. They are
versioned, deployed, and operated independently.

Cross-system data flow is intentionally narrow:

```
SharedSignals
  collects provider data and writes SQLite/DuckDB read models
      |
      | HTTP API / read-model contract
      v
MarketGraph                       TradingAgent
research graph and evidence       trading decisions, queues, simulated ledgers
```

No repository may import another repository's internal modules as a production
dependency. SharedSignals is the only external market-data collection owner.
MarketGraph and TradingAgent consume its API/read model and fail closed when
data is missing.

## Repositories

| Repository | Role |
| --- | --- |
| SharedSignals | Shared collection, validation, direct database writes, API/read-model output |
| MarketGraph | Research graph, macro/cross-market evidence, read-only interfaces |
| TradingAgent | Trading decisions, signal queues, simulated/shadow ledgers, notifications |

## SharedSignals

SharedSignals owns external data ingestion. Its collectors validate provider
rows, write them directly into the SQLite read model, mirror analytical data to
DuckDB when configured, and expose the result through HTTP/API and read-model
contracts.

It does not make trading decisions, run strategies, write TradingAgent queues,
or maintain MarketGraph research facts.

Current production collectors include:

- Tushare tiers for A-share, futures, HK/US daily, funds, ETF, macro, news,
  announcements, research and reference data.
- Binance public-market collection for Crypto.
- Polymarket market and price collection.
- CN futures 5-minute collection.

CSV/NDJSON files are not a production read fallback. They may exist only as
bounded tests, explicit historical migration material, or local audit fixtures.
Production success means rows reached the read model and can be returned through
SharedSignals API/read-model access.

## MarketGraph

MarketGraph owns long-horizon research, event/impact relationships,
cross-market context, readiness, attribution, and read-only research interfaces.

It reads SharedSignals API/read-model outputs for market data. It must not
restore independent Tushare, Eastmoney, Binance, Polymarket, RSS, Tavily, or
Firecrawl provider collection paths. New provider coverage belongs in
SharedSignals first, then MarketGraph consumes the resulting API/read model.

MarketGraph does not trigger execution, Hermes, broker APIs, simulated fills, or
real-money workflows.

## TradingAgent

TradingAgent owns strategy evaluation, signal queues, simulated/shadow ledgers,
daily/weekly review, notifications, and future controlled real-broker
integration.

It reads SharedSignals data through its shared data facade, backed by the
SharedSignals API in production. SQLite read-model access is allowed only for
explicit local tests or emergency diagnostics with the documented switches.

TradingAgent reads MarketGraph through public research APIs/read models when it
needs research evidence. It must not depend on MarketGraph internal provider
collectors or use MarketGraph as a market-data source.

## Operating Rules

1. SharedSignals is the only provider collection owner.
2. MarketGraph is read-only research and evidence; it never executes trades.
3. TradingAgent owns trading decisions, simulated/shadow accounting and queues.
4. Cross-system reads use HTTP APIs or documented read-model contracts.
5. Missing data fails closed; old CSV, NDJSON, sibling repo paths and desktop
   folders are not production fallbacks.
6. Each repository is committed, pushed, deployed and verified independently.

## Production Layout

| Repository | Main server `8.138.181.177` | Notes |
| --- | --- | --- |
| SharedSignals | `/opt/investment/SharedSignals` | Data collection, read model, API |
| MarketGraph | `/opt/investment/MarketGraph` | Research API and read-only runtime |
| TradingAgent | `/opt/investment/tradingagent` | Sim/shadow trading runtime and front API |

Mac Mini/Hermes is a reserved A-share GUI execution bridge owned by
TradingAgent, not a SharedSignals or MarketGraph responsibility.

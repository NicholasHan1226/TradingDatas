# Binance Spot public-data canary

This is an isolated, non-production TradingDatas canary. It does not change
the CN/Tushare registry, SQLite authority, 18082 service, release, or timer.
It is selected only with `TRADINGDATAS_CANARY_MODE=binance_spot_v1`; arbitrary
registry-path overrides remain rejected.

The public data plane is unchanged: `GET /v1/catalog` and `POST /v1/query`.
There is no Binance-specific route and consumers must not connect to Binance
or the canary SQLite directly. The provider adapter permits only unauthenticated
Spot `klines` and `exchangeInfo` reads from `https://data-api.binance.vision`.
It contains no API key, account, Testnet, order, or retry/fallback-to-trading
surface.

## Frozen v1 datasets

- `crypto.spot.binance.btcusdt.5m`
- `crypto.spot.binance.ethusdt.5m`
- `crypto.spot.binance.btcusdt.rules`
- `crypto.spot.binance.ethusdt.rules`

The bar datasets accept only their named symbol, `5m`, and a caller-supplied
UTC RFC3339 open-time range. One physical request is bounded to three days and
at most 1,000 rows; the 30-day backfill is therefore ten or more separately
receipted bounded windows, never a fabricated historical observation. Bars
whose close time has not occurred are discarded. Identity is `[symbol,
open_time]`; `open_time` and `close_time` are UTC, and the raw millisecond
timestamps are retained. OHLC, base volume and quote volume are text so a
consumer can apply `Decimal` rather than binary float.

Rules are read from the actual `exchangeInfo` response and expose symbol/status,
base/quote asset, `PRICE_FILTER.tickSize`, `LOT_SIZE.stepSize`/`minQty`, and
`MIN_NOTIONAL` or `NOTIONAL.minNotional`. They are factual constraints for a
downstream simulator, not permission to trade.

## Evidence and shutdown

The canary has its own database and evidence root below a caller-created
private runtime root, for example `/private/tmp/td-crypto-canary-v3`; it must
not use `/opt/investment-data/tradingdatas`. There is intentionally no canary
systemd unit or timer. Stopping it is therefore simply ending the one-shot
process; no persistent task is enabled, and no shared timer requires changing.

Freshness is calculated from the actual closed bar and receipt observation
time. A successful HTTP response, catalog item, historical backfill, or
receipt alone is not evidence of real-time usability. TradingAgent Crypto may
consume only a recorded `ready/fresh/valid/non-degraded` query envelope through
the standard API, and remains `REAL_TRADING_ENABLED=false` / delayed-paper.

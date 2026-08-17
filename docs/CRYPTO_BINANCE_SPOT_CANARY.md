# Binance Spot public-data canary

This is an isolated, non-trading Crypto runtime. It does not change
the CN/Tushare registry, SQLite authority, 18082 service, release, or timer.
It is selected only with `TRADINGDATAS_CANARY_MODE=binance_spot_v1`; arbitrary
registry-path overrides remain rejected.

The public data plane is unchanged: `GET /v1/catalog` and `POST /v1/query`.
There is no Binance-specific route and consumers must not connect to Binance
or the canary SQLite directly. The provider adapter permits only unauthenticated
Spot `klines` and `exchangeInfo` reads from `https://data-api.binance.vision`.
It contains no API key, account, Testnet, order, or retry/fallback-to-trading
surface.

## Frozen v1 cohort

The versioned source of truth is
`config/crypto_binance_spot_universe.v1.yaml`. It freezes forty established,
liquid USDT Spot symbols with at least 180 days of public 5m history:
BTCUSDT, ETHUSDT, SOLUSDT, XRPUSDT, BNBUSDT, DOGEUSDT, ADAUSDT, TRXUSDT,
LINKUSDT, AVAXUSDT, BCHUSDT, LTCUSDT, DOTUSDT, NEARUSDT, SUIUSDT, APTUSDT,
UNIUSDT, ATOMUSDT, XLMUSDT, HBARUSDT, ETCUSDT, FILUSDT, INJUSDT, ARBUSDT,
OPUSDT, AAVEUSDT, GRTUSDT, TIAUSDT, SEIUSDT, ONDOUSDT, LDOUSDT, CRVUSDT,
ENAUSDT, WLDUSDT, STRKUSDT, JUPUSDT, PYTHUSDT, FETUSDT, RENDERUSDT and
POLUSDT. BTCUSDT and ETHUSDT remain first as the rollback baseline. The deterministic registry compiler emits one `.5m` and one
`.rules` dataset per symbol into the single pinned canary registry
`config/crypto_binance_canary_registry.v1.yaml`; runtime collection cannot
add a symbol that is absent from the compiled registry. The same registry and
universe also cover the USDⓈ-M perpetual funding-rate and open-interest
candidate cohort documented in `CRYPTO_BINANCE_USDM_CANARY.md`.

The bar datasets accept only their named symbol, `5m`, and a caller-supplied
UTC RFC3339 open-time range. One physical request is bounded to three days and
at most 1,000 rows; the frozen 180-day backfill is sixty separately receipted
bounded windows per symbol, never a fabricated historical observation. Its
`observed_at` is collection time rather than historical PIT. Bars
whose close time has not occurred are discarded. Identity is `[symbol,
open_time]`; `open_time` and `close_time` are UTC, and the raw millisecond
timestamps are retained. OHLC, base volume and quote volume are text so a
consumer can apply `Decimal` rather than binary float.

## Consumer terminal-window profile

The frozen provider-neutral profile for a delayed-paper consumer is option A:
`symbol eq`, an `open_time between [window_start, latest_open]` RFC3339 UTC
window, `as_of`, the ten default bar fields, deterministic
`symbol:asc,open_time:desc`, and `limit=13`. `open_time` is explicitly
filterable with `between` in catalog. The query layer canonicalizes RFC3339
input to the provider-row UTC millisecond representation before comparison, so
an exactly thirteen-bar inclusive window returns 13 rows and terminal
`next_cursor=null`; it does not hide a cursor from a broader result set.
`window_start` must equal `latest_open - 60 minutes` for this profile.

Rules are read from the actual `exchangeInfo` response and expose symbol/status,
base/quote asset, `PRICE_FILTER.tickSize`, `LOT_SIZE.stepSize`/`minQty`, and
`MIN_NOTIONAL` or `NOTIONAL.minNotional`. They are factual constraints for a
downstream simulator, not permission to trade.

## Current quote snapshot candidate

The optional `.book_ticker` contract reads Binance public `bookTicker` for the
same frozen forty symbols. It exposes only `symbol`, `bid_price`, `bid_qty`,
`ask_price`, and `ask_qty` as a current, receipt-bound snapshot. The upstream
response has no provider event timestamp, so its time authority is the
collection receipt's actual observation interval. It is not historical L1,
order-book depth, a replayable market-time series, or execution evidence.
It has no backfill. The source tree provides a dedicated
`tradingdatas-crypto-binance-book-ticker.timer` for five-minute collection;
installation and enablement remain a separate immutable-release decision.
Runtime effectiveness requires fresh unit, receipt and authenticated `18083`
readback recorded in `STATUS.md`. Each collection keeps only the latest
receipt-bound snapshot per symbol.

## Evidence and shutdown

Candidate proof uses its own database and evidence root below a caller-created
private runtime root, for example `/private/tmp/td-crypto-canary-v3`; it must
not use `/opt/investment-data/tradingdatas`. The production-isolated runtime,
if promoted, continues to use only the dedicated Crypto unit, timer and data
root documented in `CRYPTO_LOOPBACK_RUNTIME.md`; it never shares the A-share
database or timer.

Freshness is calculated from the actual closed bar and receipt observation
time. A successful HTTP response, catalog item, historical backfill, or
receipt alone is not evidence of real-time usability. TradingAgent Crypto may
consume only a recorded `ready/fresh/valid/non-degraded` query envelope through
the standard API, and remains `REAL_TRADING_ENABLED=false` / delayed-paper.

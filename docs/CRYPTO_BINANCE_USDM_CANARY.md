# Binance USDⓈ-M public-data canary

This is an isolated, non-trading Crypto runtime slice. It extends the same
isolated Crypto runtime documented in `CRYPTO_LOOPBACK_RUNTIME.md`; it does
not change the CN/Tushare registry, SQLite authority, 18082 service, release,
or timer, and it shares the pinned `TRADINGDATAS_CANARY_MODE=binance_spot_v1`
canary registry with the Spot cohort. `binance_spot_v1` remains the frozen
environment identity of that single registry, which now spans both the Spot
and the USDⓈ-M perpetual public slices; a separate perp registry could never
be served by the one isolated loopback API.

The public data plane is unchanged: `GET /v1/catalog` and `POST /v1/query`.
There is no Binance-specific route and consumers must not connect to Binance
or the canary SQLite directly. The provider adapter permits only
unauthenticated USDⓈ-M `fundingRate` and `openInterestHist` history reads
from `https://fapi.binance.com` — a different transport host from the Spot
`data-api.binance.vision`, which is why it is a separate provider-level
adapter (`binance_usdm`). It contains no API key, account, Testnet, order, or
retry/fallback-to-trading surface.

## Frozen v1 cohort

The symbol set reuses the same versioned universe contract as the Spot
cohort, `config/crypto_binance_spot_universe.v1.yaml`: BTCUSDT, ETHUSDT,
SOLUSDT, XRPUSDT, BNBUSDT, DOGEUSDT, ADAUSDT, TRXUSDT, LINKUSDT and
AVAXUSDT. The deterministic registry compiler emits one `.funding_rate` and
one `.open_interest` dataset per symbol as
`crypto.perp.binance.<symbol>.<kind>`; runtime collection cannot add a symbol
that is absent from the compiled registry.

Both datasets are append-only history series with provider event timestamps,
not current snapshots. Identity is `[symbol, funding_time]` for funding rate
and `[symbol, timestamp]` for open interest; both are UTC and the raw
millisecond timestamps are retained. Rates and quantities are text so a
consumer can apply `Decimal` rather than binary float. Re-observed identical
rows keep their first receipt and collection provenance, so overlapping
polling windows are idempotent.

The funding-rate dataset accepts only its named symbol and a caller-supplied
UTC RFC3339 window bounded to thirty days; one physical request is capped at
1,000 rows. The open-interest dataset accepts only its named symbol, period
`5m`, and a UTC RFC3339 window bounded to one day; one physical request is
capped at 500 rows. Rows outside the requested window or carrying a provider
timestamp in the future are discarded.

## Candidate cadence and gate status

The candidate runner `tools/run_binance_usdm_canary.py` accepts no provider,
symbol, field, or registry path input. Per run it collects, for every frozen
symbol, one trailing 48-hour funding-rate window ending at the latest
realized eight-hour funding boundary (deduplication covers the overlap; a new
funding row appears only every eight hours) and the two latest closed
five-minute open-interest boundaries. It shares
`/run/tradingdatas-crypto/collect.lock` with the Spot collector so writers on
the same isolated SQLite stay serial; its timer is staggered two minutes
after the Spot bar timer. A lock-busy or provider failure is an honest failed
run retried by the next timer tick; the funding window self-heals, while a
missed open-interest interval stays a gap until a bounded replay is
explicitly approved.

These twenty datasets are **contract_ready candidates only**. The unit pair
`tradingdatas-crypto-binance-usdm-collect.{service,timer}` ships in the
repository but the timer must stay disabled until an isolated production
review completes a real provider → SQLite receipt → authenticated
catalog/query readback (`observed`) and then continuous-cadence evidence
(`stable`); only then may the timer be enabled. A successful compile, test
run, catalog entry, or plan-mode output is not evidence of upstream
availability or production readiness. Bounded historical backfill is a
separate one-shot decision and is not part of this candidate.

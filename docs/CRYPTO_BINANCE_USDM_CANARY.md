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

## Metrics-dump open-interest degradation source

`fapi.binance.com` is unreachable from the production host (SNI-level TLS
reset, recorded in `STATUS.md` on 2026-08-16), while the public dump host
`https://data.binance.vision` stays reachable.  With owner approval, open
interest therefore has a second provider binding, `binance_usdm_dump`, on the
**same** forty `crypto.perp.binance.<symbol>.open_interest` datasets: the dump's
daily `metrics` zip carries the same 5-minute open-interest facts as
`openInterestHist`, so the dataset identity, schema, primary key and
append-only payload-hash idempotency are unchanged and only the transport
differs (batch file download instead of a REST JSON API, which is why it is a
separate provider-level adapter, `collectors/binance/oi_dump_collector.py`).
The original `binance_usdm` open-interest binding stays in the registry as
`activation_state: paused` so exactly one binding is active; if the fapi
transport is ever restored, reactivating it is a deliberate registry decision,
not an automatic fallback.

Funding rate has no dump (404 on the dump host), so it now rides the
owner-approved Singapore relay: `sg-relay-tunnel.service` maintains an SSH
L4 tunnel exposing a loopback SOCKS5 endpoint (`127.0.0.1:17890`) on the
production host.  The `binance_usdm_relay` provider (`transport profile
binance-usdm-via-sg-relay.v1`) speaks plain SOCKS5 CONNECT to that loopback
endpoint and then negotiates TLS end-to-end with `fapi.binance.com` — SNI,
Host and certificate verification are unchanged, so the relay can only drop
traffic, never read or modify it.  There is deliberately no direct-egress
fallback and no relay fallback to direct. All forty `funding_rate` bindings
moved to this provider with `activation_state: active`. The USDM timer may
collect them in the isolated, budget-bounded observation runtime; every
dataset remains `contract_ready`, `observed`, or `stable` only according to
its own receipt and authenticated API evidence.

The dump binding downloads
`data/futures/um/daily/metrics/<SYMBOL>/<SYMBOL>-metrics-YYYY-MM-DD.zip`, whose
single CSV member holds one row per five-minute grid label of the UTC day
(`create_time` from `00:00:00` to `23:55:00`, 288 rows, unordered).  The
adapter pins the dump origin, rejects redirects, verifies the zip member name,
the exact eight-column header, the complete 288-row grid and the symbol, and
maps each row onto the existing open-interest schema.  The dump-only long/short
ratio columns are validated for shape but are not part of this dataset's
schema; the raw daily zip remains publicly re-downloadable.

The candidate runner `tools/run_binance_oi_dump_canary.py` accepts no
provider, symbol, field, or registry path input.  Daily publication lags the
UTC day close by hours (observed: the 2026-08-15 zip was still 404 at
03:05-03:45 UTC on 2026-08-16 while 2026-08-14 was available), so a run never
assumes the latest closed day is published.  Within a bounded seven-day
lookback it tries, per symbol, the newest missing day first and **falls
through to older missing days on `provider_error`** (an unpublished daily
zip), collecting the newest day that is published and not yet in the store;
a HEAD publication probe (`probe_published`) runs before any ingest attempt,
so the expected publication lag never writes failed receipts that would flip
the dataset runtime state to `failed` for hours.  Coverage is derived from
SQLite facts joined to validated success receipts, never from run history,
so a late publication is picked up by a later tick and cannot cause a
permanent day skip.  A symbol whose whole lookback window
is already ingested is skipped without a provider call and reported
`unchanged`.  If only the newest day is missing and its zip is still
unpublished, the dataset is reported `pending_publication` and the run
succeeds; if older missing days also fail, that is an outage and the run
fails honestly.  Contract or validation drift is never treated as
publication lag and stops the run fail closed.  It shares `/opt/investment-data/tradingdatas-crypto/collect.lock` with
the Spot and USDM collectors, records a terminal receipt per attempt, and
makes one immediate retry on a provider error; with the whole lookback
exhausted by provider errors the outcome follows the
`pending_publication`/honest-failure rule above.  The unit pair
`tradingdatas-crypto-binance-oi-dump-collect.{service,timer}` fires every two
hours at minute 37 (`*-*-* 00/2:37:00`), staggered off the five-minute
Spot/USDM timers that share the same lock, so a publication lag of hours is
absorbed the same day. Like the USDM pair, this timer may run only as an
isolated, budget-bounded observation collector; it neither proves
`observed`/`stable` nor authorizes any non-data action.

Bounded historical backfill is a separate one-shot operation approved by the
owner to align open interest with the bar history: `--backfill-days 198` (any
other value is rejected) walks the frozen horizon day by day, oldest first —
with the latest closed UTC day 2026-08-15 the 198 windows start at
2026-01-30.  Each day is one bounded batch of the frozen forty symbols taken
under the shared lock, and the lock is released between days (re-acquired by
waiting, not by failing) so the five-minute collectors interleave instead of
starving; an individual five-minute slot may still see a lock-busy failure
during the operation, which is the existing documented self-healing noise.
Already-ingested days are skipped via the same receipt-validated store
derivation, so an interrupted or rerun backfill resumes without duplicate
work, and every collected day still writes its own receipt-bound facts.
Running it in a low-traffic window remains the operator's choice; it is never
triggered by a timer.

While the fapi binding is paused,
`tools/run_binance_usdm_canary.py` can no longer execute its open-interest
half (its funding-rate half is unchanged); that is accepted because the dump
runner is the open-interest collection path under the degradation plan.

## Premium-index dump: funding-pressure proxy

The same dump host also publishes daily `premiumIndexKlines` zips, and the
frozen cohort therefore has a third dataset family,
`crypto.perp.binance.<symbol>.premium_index`, backed by a single
`binance_usdm_dump` binding (`api_name` prefix `premiumIndexKlinesDump_`) on
the same adapter (`collectors/binance/oi_dump_collector.py`) and the same
transport profile — only the dump path, member naming, and row parser differ,
so no new provider-level adapter was added.

**Boundary:** the premium index is **not** the funding rate.  Binance derives
each funding rate from the interest rate and this premium-index series through
a clamped formula; the premium index is the main observable driver of funding
pressure and is collected here strictly as a proxy input for that pressure.
Funding rate itself has no dump; it is collected separately through the
owner-approved SG relay described above.  Consumers must not treat a
premium-index row as a realized or predicted funding rate.

The binding downloads
`data/futures/um/daily/premiumIndexKlines/<SYMBOL>/5m/<SYMBOL>-5m-YYYY-MM-DD.zip`
(verified live on 2026-08-16: the interval is a mandatory path segment, the
single CSV member is `<SYMBOL>-5m-<date>.csv`, and the 288 rows cover the full
UTC day on the five-minute grid).  Rows carry millisecond `open_time`/
`close_time` plus premium-index OHLC values; the kline `volume`/`count`/
taker columns are structurally constant for an index series and are validated
for shape but excluded from the dataset schema, exactly like the dump-only
long/short columns of the metrics zip.  Identity is `[symbol, open_time]`,
values stay text, and payload-hash idempotency matches the other append-only
canary series.

The candidate runner `tools/run_binance_premium_dump_canary.py` accepts no
provider, symbol, field, or registry path input and reuses the
open-interest dump runner's shared implementation verbatim: closed-UTC-day
window, bounded seven-day lookback with per-symbol newest-missing-day-first
selection, the HEAD publication probe (`probe_premium_index_published`) with
`pending_publication` semantics, receipt-validated store-derived coverage,
honest failure on contract drift or multi-day outage, and the frozen one-shot
`--backfill-days 198` horizon (same 2026-01-30 alignment as open interest)
with per-day batches that release the shared
`/opt/investment-data/tradingdatas-crypto/collect.lock` between days; per
(day, symbol) an unpublished zip is skipped without a receipt and a provider
error after a positive probe is recorded without aborting the horizon, while
non-provider failures still stop the run fail closed.  The unit pair
`tradingdatas-crypto-binance-premium-dump-collect.{service,timer}` fires every
two hours at minute 53 on odd hours (`*-*-* 01/2:53:00`), staggered off both
the five-minute timers and the `00/2:37:00` open-interest dump timer. Like the
USDM and OI-dump pairs, this timer may run only for isolated, budget-bounded
observation accumulation; it does not independently prove `observed` or
`stable`.

## Frozen v1 cohort

The symbol set reuses the same versioned universe contract as the Spot
cohort, `config/crypto_binance_spot_universe.v1.yaml`: BTCUSDT, ETHUSDT,
SOLUSDT, XRPUSDT, BNBUSDT, DOGEUSDT, ADAUSDT, TRXUSDT, LINKUSDT, AVAXUSDT,
BCHUSDT, LTCUSDT, DOTUSDT, NEARUSDT, SUIUSDT, APTUSDT, UNIUSDT, ATOMUSDT,
XLMUSDT, HBARUSDT, ETCUSDT, FILUSDT, INJUSDT, ARBUSDT, OPUSDT, AAVEUSDT,
GRTUSDT, TIAUSDT, SEIUSDT, ONDOUSDT, LDOUSDT, CRVUSDT, ENAUSDT, WLDUSDT,
STRKUSDT, JUPUSDT, PYTHUSDT, FETUSDT, RENDERUSDT and POLUSDT. The
deterministic registry compiler emits one `.funding_rate`, one
`.open_interest` and one `.premium_index` dataset per symbol as
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
timestamp in the future are discarded.  This paragraph describes the paused
`binance_usdm` binding; the active `binance_usdm_dump` binding and its daily
window contract are defined in the metrics-dump section below.

## Candidate cadence and gate status

The candidate runner `tools/run_binance_usdm_canary.py` accepts no provider,
symbol, field, or registry path input. Per run it collects, for every frozen
symbol, one trailing 48-hour funding-rate window ending at the observed UTC
millisecond (deduplication covers overlap; no eight-hour event cadence is assumed).
Fractional-second events are retained up to that inclusive bound; future events
remain excluded by the collector. This changes only the request window, not the
v1 payload, mark-price contract or append-only identity. It also collects the two latest closed
five-minute open-interest boundaries. It shares
`/opt/investment-data/tradingdatas-crypto/collect.lock` with the Spot collector so writers on
the same isolated SQLite stay serial; its timer is staggered two minutes
after the Spot bar timer. A lock-busy or provider failure is an honest failed
run retried by the next timer tick; the funding window self-heals, while a
missed open-interest interval stays a gap until a bounded replay is
explicitly approved.

These eighty datasets begin as **contract_ready candidates**. The unit pair
`tradingdatas-crypto-binance-usdm-collect.{service,timer}` may be enabled for
isolated, budget-bounded observation collection after its release, service,
rollback and API-auth boundary have been checked. Timer enablement only
accumulates receipt-bound evidence: a dataset becomes `observed` after a real
provider → SQLite receipt → authenticated catalog/query readback, and becomes
`stable` only after continuous-cadence evidence and applicable consumer
readback. A successful compile, test run, catalog entry, plan-mode output or
enabled timer is not evidence of upstream availability or stable production.
Bounded historical backfill is a separate one-shot decision and is not part of
this candidate.

# Crypto funding settlement contract handoff — 2026-08-30

Status: **proposal only; no collector run, production change, merge, or release**.

## Purpose and boundary

This handoff records the minimum safe path for the research-only carry consumer
to obtain an actual USD-M perpetual funding settlement rate and its traceable
settlement mark price.  It does not add a public route, dataset ID, provider
call, trading capability, schedule inference, or a claim of live availability.

The present public data surface remains `GET /v1/catalog` and `POST /v1/query`.
Any future data must be consumed through that surface after the normal
contract/release/receipt process.

## A. Funding settlement mark price and millisecond window

### Verified upstream semantics

Binance USD-M Futures Funding Rate History returns `symbol`, `fundingRate`,
`fundingTime`, and `markPrice`.  Its official field definition says that
`markPrice` is the mark price associated with the particular funding-fee
charge.  `startTime` and `endTime` are inclusive millisecond timestamps.

This establishes a source-level association between an event's funding rate and
mark price.  It does not by itself authorize a TradingDatas contract change or
prove historical coverage/receipt quality.

### Current implementation evidence

Existing BTCUSDT and ETHUSDT funding datasets expose only `symbol`,
`funding_time_ms`, `funding_time`, and `funding_rate`:

- `collectors/binance/usdm_collector.py` validates and projects only those
  fields, so it intentionally drops upstream `markPrice`.
- `config/crypto_binance_canary_registry.v1.yaml` declares the same v1 shape,
  append-only PIT model, and payload-hash identity.
- `tools/run_binance_usdm_canary.py` snaps the funding query end to an
  eight-hour boundary.  A valid event such as `16:00:00.002Z` is later than an
  `16:00:00.000Z` end and is excluded by the collector's inclusive bound.

Therefore the existing eight-hour planner is not a valid completeness rule.  A
future planner must retain event milliseconds and use an observed, current UTC
end bound; it must not force a funding cadence or turn a delayed event into an
hour-aligned event.

### Contract-owner decision required before implementation

Adding `mark_price` directly to the current schema is unsafe without an
identity/migration decision.  For append-only datasets,
`storage/provider_dataset_rows.py` uses a payload hash as the row identity.
Re-reading an existing settlement with the newly retained mark price changes
that payload and can create a second logical settlement row under the current
schema major.

The TradingDatas data-contract owner must choose and document one of these
paths before code is written:

1. a new schema major with an explicit historical-coverage/backfill and query
   transition plan;
2. a reviewed migration/dual-read plan that preserves exactly one logical
   settlement per `(symbol, funding_time)` while retaining PIT provenance; or
3. a separately approved contract identity, including its public dataset ID,
   rather than reusing the existing dataset.

This document deliberately does not choose any of those paths.

### Minimum candidate files after that decision

Only the following files are expected for the A candidate, subject to the
chosen identity plan:

- `collectors/binance/usdm_collector.py`
- `tools/run_binance_usdm_canary.py`
- `config/crypto_binance_canary_registry.v1.yaml`
- `tools/compile_crypto_binance_canary_registry.py` (only if the approved
  registry generation requires it)
- `tests/test_binance_usdm_canary.py`
- the identity/migration tests adjacent to `storage/provider_dataset_rows.py`
- `docs/CRYPTO_BINANCE_USDM_CANARY.md` and this handoff's successor decision
  record

The minimum tests are:

1. normalize and retain the source `markPrice` only after the selected schema
   contract accepts it;
2. retain an event whose `fundingTime` is `...00.002Z` when it is before the
   actual observed query end, and exclude it when it is after that end;
3. prove the window no longer assumes eight-hour cadence;
4. prove a re-observation of the same logical settlement follows the approved
   identity/migration rule and cannot duplicate it; and
5. preserve UTC, source receipt/lineage, quality, and consumer query readback
   requirements.

## B. Actual perpetual-trade and mark-price 5-minute OHLCV

The official USD-M API provides both symbol klines and mark-price klines with
5-minute intervals.  That demonstrates source capability, not an accepted
TradingDatas contract.  The registry/compiler currently has no contract kind
for actual USD-M perpetual trade OHLCV or mark-price OHLCV; the existing spot
OHLCV and perpetual premium-index OHLC are not substitutes.

The owner must freeze, separately for BTCUSDT and ETHUSDT, the instrument
identity (`symbol` versus continuous `PERPETUAL`), trade/mark semantics, row
primary key, source binding/entitlement, coverage and freshness acceptance,
and whether the common compiler scope may expand beyond this two-symbol
request.  Until then, B is `data_unavailable`.

## C. Funding settlement schedule and interval changes

Funding Info can report `fundingIntervalHours` for symbols with adjusted
funding parameters, but the official endpoint is not a historical,
independently effective-dated schedule feed.  No approved historical schedule
source was found in the current collector/registry.  The cadence therefore
must not be inferred as eight hours or reconstructed from observed events.

C remains `data_unavailable` until the owner accepts an independent historical
schedule source, its effective-time semantics, and completeness/lineage tests.

## Required next owner action

The TradingDatas data-contract owner (with Datas PM as the public-contract
authority) should issue one bounded decision covering A's identity/migration
path and B/C source contracts.  An implementation agent may then prepare the
listed isolated-worktree candidate and tests; release/receipt/consumer
acceptance remains a separate later stage.

## Official source references

- Binance USD-M Futures Market Data: Funding Rate History, Funding Info, and
  Klines/Mark Price Klines:
  <https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/market-data>

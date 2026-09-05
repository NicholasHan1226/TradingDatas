# Crypto loopback runtime

The internal runtime is deployed from its own immutable release. The server
readback on 2026-08-22 resolved `current` to
`d711414bec41356724dd2bdbeaf4601459ff2778`; a later release must be verified
from the server pointer rather than inferred from this document. It does not
change the A-share API at `127.0.0.1:18082`, any Tushare timer, any A-share
SQLite file, or any trading authority.

Crypto is internal-only. This runtime is excluded from public product coverage,
packages, purchase previews, service counts and public onboarding schedules.
This boundary does not stop existing isolated collection or delete stored data.

## Fixed isolation contract

| Surface | Runtime value |
| --- | --- |
| API listener | `127.0.0.1:18083` only |
| API service account | `tradingdatas-crypto:tradingdatas-crypto` |
| API private files | `/etc/tradingdatas-crypto/api_tokens.json`, `token_salt`, and `cursor_signing_key`, each owned by `tradingdatas-crypto`, mode `0600` |
| immutable release root | `/opt/investment/releases/tradingdatas-crypto/current` |
| API data store | `/opt/investment-data/tradingdatas-crypto/read_model/provider_native.sqlite` |
| API unit | `tradingdatas-crypto-v1-internal.service` |
| collector unit | `tradingdatas-crypto-binance-collect.service` |
| timer | `tradingdatas-crypto-binance-collect.timer` at `*-*-* *:0/5:00`; isolated 5-minute close-aligned collection. Enablement is a separate release decision |
| backup collector unit | `tradingdatas-crypto-binance-collect-retry.service`, same `latest_closed_window` with `--backup-wake` |
| backup timer | `tradingdatas-crypto-binance-collect-retry.timer` at `*-*-* *:1/5:00` (close+60s). It writes the same just-closed bar if the primary oneshot never started; a held `collect.lock` exits `skipped_lock_held` so a still-running primary is not queued again |
| book-ticker unit | `tradingdatas-crypto-binance-book-ticker.service` |
| book-ticker timer | `tradingdatas-crypto-binance-book-ticker.timer` at `*-*-* *:3/5:10`; this is the in-repo production deconflict slot, not `*:0/5:40`. Enablement is a separate release decision |
| rule unit | `tradingdatas-crypto-binance-rules.service` |
| rule timer | `tradingdatas-crypto-binance-rules.timer`, daily public-rule refresh |
| USDM candidate unit | `tradingdatas-crypto-binance-usdm-collect.service` |
| USDM candidate timer | `tradingdatas-crypto-binance-usdm-collect.timer` at `*-*-* *:2/5:00`, one calendar second family after the bar backup; it may run as an isolated, budget-bounded observation timer, but does not by itself make any dataset `observed` or `stable` |
| OI dump candidate unit | `tradingdatas-crypto-binance-oi-dump-collect.service` |
| OI dump candidate timer | `tradingdatas-crypto-binance-oi-dump-collect.timer`, every two hours at minute 37 (`*-*-* 00/2:37:00`) staggered off the five-minute timers; it may run only for isolated receipt accumulation and remains subject to the same dataset-local quality gates |
| premium-index dump candidate unit | `tradingdatas-crypto-binance-premium-dump-collect.service` |
| premium-index dump candidate timer | `tradingdatas-crypto-binance-premium-dump-collect.timer`, every two hours at minute 53 on odd hours (`*-*-* 01/2:53:00`) staggered off the five-minute timers and the OI dump timer; it may run only for isolated receipt accumulation and remains subject to the same dataset-local quality gates |
| lock | `/opt/investment-data/tradingdatas-crypto/collect.lock`; closed-5m primary wait is 300s in this tree, backup-wake wait is 0s. That is the in-repo contract only, not a production-effectiveness claim |

The API uses the ordinary authenticated `GET /v1/catalog` and `POST /v1/query`
surface with the pinned `TRADINGDATAS_CANARY_MODE=binance_spot_v1` registry.
There is no Binance route, no localhost auth bypass, no public ingress, no API
key, account, Testnet, order, or TradingAgent direct provider access.
No mutable `/etc` environment file is loaded: listener, registry mode, release
root and SQLite path come only from the immutable release profile. The
cursor HMAC key is read only from the dedicated private file named above; it is
never stored as a plaintext environment value, committed, logged, or shared
with the A-share API. The
TradingAgent consumer token leaf is separate at
`/run/secrets/tradingagent/tradingdatas-crypto-read.token`; it is never the API
hash registry, salt, or a provider credential.

## Collector behavior and current proof

The timer passed candidate review and server preflight before it was enabled.
The current isolated production runtime collects the frozen forty-symbol cohort
through the existing provider-native receipt path, using already-closed 5m
bars per run. Its `observed_at` is the actual collection time. BTCUSDT and
ETHUSDT remain the smaller rollback baseline; they are not a claim that the
running cohort is limited to two symbols.

For a terminal `provider_error` on one bar dataset, the collector records that
failed receipt and makes exactly one immediate retry for that same requested
closed-bar window. It never retries configuration, validation, or legal-empty
outcomes, never substitutes another provider or bar, and a second failure
leaves the dataset failed. This bounded recovery is only to preserve honest
observation continuity during a brief public transport interruption; it does
not relax the API metadata or TradingAgent evidence gate.

The expansion contract freezes forty symbols in
`config/crypto_binance_spot_universe.v1.yaml` and compiles two hundred and
forty datasets into the single pinned canary registry: one bar, one
public-rule and one current book-ticker snapshot dataset per symbol for the
Spot cohort, plus one funding-rate, one open-interest and one premium-index
dataset per symbol for the USDⓈ-M perpetual candidate cohort documented in
`CRYPTO_BINANCE_USDM_CANARY.md`. The source tree provides a dedicated
`tradingdatas-crypto-binance-book-ticker.timer` at `*-*-* *:3/5:10` for five-minute collection;
installation, enablement and runtime effectiveness remain separate release
gates and do not change the enabled bar or rules timers. Every book-ticker
collection keeps only the latest receipt-bound snapshot per symbol; it is not
a replayable history. The USDⓈ-M candidate shares this data root, SQLite,
release and loopback API, and its collector takes the same `collect.lock` so
writers stay serial. Its timer may run for bounded, isolated observation
accumulation; timer enablement never promotes a dataset, relaxes its
receipt/API checks, or grants any authority beyond data collection. Promotion
to `stable` still requires each promoted dataset's independent authenticated
catalog/query readback and continuous cadence evidence. A symbol failure is
isolated and must not be hidden by another symbol's healthy envelope. Bounded
180-day backfill remains a separate one-shot operation and is never
real-time/PIT evidence.

On 2026-08-02, authenticated formal `18083` readback verified two adjacent
completed 5m windows for all forty bar datasets. Every dataset returned a
terminal page with unique bar identities and `ready/success/fresh/valid`,
`degraded=false`, plus a receipt and complete lineage. This is runtime evidence
for the frozen cohort only; it does not authorize orders, accounts, or a
runtime expansion beyond the versioned universe contract.

The same production SQLite read model already contains at least the frozen
180-day historical horizon for every bar dataset. On that date each had 52,957
unique 5m identities from 2026-01-30 through the current bar, and a bounded
historical formal query for 2026-02-03 returned terminal, receipt-bound,
complete-lineage data for all forty. Do not rerun the frozen backfill merely to
recreate this coverage: it is research/observation data, never proof of
historical availability or real-time freshness.

An explicit query `as_of` also bounds receipt authority: bar rows and envelope
metadata can use only complete success receipts whose collection interval is at
or before the requested cutoff and whose data watermark is at or before the
resolved cutoff. A later collection is excluded even when its bar timestamps
are historical; if no matching receipt exists, the query fails closed.
For the fixed RFC3339 `open_time between` window, eligible success receipts
must also overlap the collection interval from the requested lower bound to the
explicit cutoff. This keeps the lineage cohort bounded as receipt history grows.
The BTC/ETH rolling as-of read also recognizes the immediately preceding
`partition_field=null` receipt hash after `open_time` became the declared
partition field. Before an active-hash success exists at the requested cutoff,
the bounded historical envelope is rebuilt from that predecessor cohort. This
compatibility is historical-lineage-only: current projection health still
requires the active hash, and all provider/request/row contracts remain
unchanged.
Omitting `as_of` retains the current projection.

For append-only bars, an identical row re-observed in the next overlapping
collector window keeps its first receipt and collection provenance. The later
transaction still records an exact success receipt with unchanged counts.
Instrument rules remain current-snapshot data and continue to refresh their
receipt provenance. No existing fact or receipt is migrated in place.

## Provisioning and rollback

Before enabling either unit on a new host, create the dedicated service account, immutable
Crypto release root and data directory, initialise the dedicated SQLite schema,
create only the three API hash/salt/cursor files with the exact owner/mode
above, and atomically install a distinct TA read token leaf without printing
it. Verify no
listener exists on `18083`, the A-share release pointer and units are unchanged,
and the Crypto release pointer resolves only below
`/opt/investment/releases/tradingdatas-crypto`. The first proof must include
authenticated catalog/query readback, receipt lineage, freshness, an explicit
timer state readback before activation or observation continuation, and A-share
isolation readback.

Rollback is: disable and stop
`tradingdatas-crypto-binance-collect.timer`,
`tradingdatas-crypto-binance-collect-retry.timer` if installed, and
`tradingdatas-crypto-binance-rules.timer` — and
`tradingdatas-crypto-binance-usdm-collect.timer` as well if it has been
enabled after its candidate gate — then stop
`tradingdatas-crypto-v1-internal.service`. Do not delete Crypto facts
or receipts, and do not stop, reload, reconfigure, or restart A-share units.

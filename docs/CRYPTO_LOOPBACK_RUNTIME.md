# Crypto loopback runtime

The internal runtime is deployed from immutable release
`24298b22f0bbd4a5746514dac96c92e59b8f3011`. It does not change the A-share
API at `127.0.0.1:18082`, any Tushare timer, any A-share SQLite file, or any
trading authority.

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
| timer | `tradingdatas-crypto-binance-collect.timer`, enabled for isolated 5-minute collection |
| rule unit | `tradingdatas-crypto-binance-rules.service` |
| rule timer | `tradingdatas-crypto-binance-rules.timer`, daily public-rule refresh |
| lock | `/run/tradingdatas-crypto/collect.lock` |

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
The current isolated production runtime collects the frozen ten-symbol cohort
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

The expansion contract freezes ten symbols in
`config/crypto_binance_spot_universe.v1.yaml` and compiles thirty datasets:
one bar, one public-rule and one current book-ticker snapshot dataset per
symbol. The book-ticker cohort completed its isolated provider-to-API review
on 2026-08-15 (ten success receipts plus authenticated `18083` readback
returning `ready/success/fresh/valid`, `degraded=false` for every dataset) and
is now collected every five minutes by its own dedicated
`tradingdatas-crypto-binance-book-ticker.timer`; it does not change the
enabled bar or rules timers. Every collection keeps only the latest
receipt-bound snapshot per symbol; it is not a replayable history. A symbol
failure is isolated and must not be hidden by another symbol's healthy
envelope. Bounded 180-day backfill remains a separate one-shot operation and
is never real-time/PIT evidence.

On 2026-08-02, authenticated formal `18083` readback verified two adjacent
completed 5m windows for all ten bar datasets. Every dataset returned a
terminal page with unique bar identities and `ready/success/fresh/valid`,
`degraded=false`, plus a receipt and complete lineage. This is runtime evidence
for the frozen cohort only; it does not authorize orders, accounts, or a
runtime expansion beyond the versioned universe contract.

The same production SQLite read model already contains at least the frozen
180-day historical horizon for every bar dataset. On that date each had 52,957
unique 5m identities from 2026-01-30 through the current bar, and a bounded
historical formal query for 2026-02-03 returned terminal, receipt-bound,
complete-lineage data for all ten. Do not rerun the frozen backfill merely to
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
authenticated catalog/query readback, receipt lineage, freshness, a
disabled-timer readback before activation, and A-share isolation readback.

Rollback is: disable and stop both
`tradingdatas-crypto-binance-collect.timer` and
`tradingdatas-crypto-binance-rules.timer`, then stop
`tradingdatas-crypto-v1-internal.service`. Do not delete Crypto facts
or receipts, and do not stop, reload, reconfigure, or restart A-share units.

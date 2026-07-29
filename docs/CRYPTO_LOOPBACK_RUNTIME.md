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
The current production baseline collects BTCUSDT and ETHUSDT through the
existing provider-native receipt path, using two adjacent already-closed 5m
bars per run. Its `observed_at` is the actual collection time.

The expansion contract freezes ten symbols in
`config/crypto_binance_spot_universe.v1.yaml` and compiles twenty datasets:
one bar and one public-rule dataset per symbol. Promotion requires all ten bar
datasets and all ten rule datasets to pass independent authenticated
catalog/query readback. A symbol failure is isolated and must not be hidden by
another symbol's healthy envelope. Bounded 180-day backfill remains a separate
one-shot operation and is never real-time/PIT evidence.

An explicit query `as_of` also bounds receipt authority: bar rows and envelope
metadata can use only complete success receipts whose collection interval is at
or before the requested cutoff and whose data watermark is at or before the
resolved cutoff. A later collection is excluded even when its bar timestamps
are historical; if no matching receipt exists, the query fails closed.
Omitting `as_of` retains the current projection.

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

# Crypto loopback candidate runtime

This is a candidate deployment contract, not a production deployment. It is
based on TradingDatas main `62d76f8` and the merged Binance Spot public-data
contracts. It does not change the A-share API at `127.0.0.1:18082`, any
Tushare timer, any A-share SQLite file, or any trading authority.

## Fixed isolation contract

| Surface | Candidate value |
| --- | --- |
| API listener | `127.0.0.1:18083` only |
| API service account | `tradingdatas-crypto:tradingdatas-crypto` |
| API token files | `/etc/tradingdatas-crypto/api_tokens.json` and `token_salt`, each owned by `tradingdatas-crypto`, mode `0600` |
| API data store | `/opt/investment-data/tradingdatas-crypto/read_model/provider_native.sqlite` |
| API unit | `tradingdatas-crypto-v1-internal.service` |
| collector unit | `tradingdatas-crypto-binance-collect.service` |
| timer | `tradingdatas-crypto-binance-collect.timer`, disabled by default |
| lock | `/run/tradingdatas-crypto/collect.lock` |

The API uses the ordinary authenticated `GET /v1/catalog` and `POST /v1/query`
surface with the pinned `TRADINGDATAS_CANARY_MODE=binance_spot_v1` registry.
There is no Binance route, no localhost auth bypass, no public ingress, no API
key, account, Testnet, order, or TradingAgent direct provider access.

## Collector behavior

The timer may only run after candidate review and explicit server preflight. It
collects BTCUSDT and ETHUSDT through the existing provider-native receipt path,
using two adjacent already-closed 5m bars per run. Its `observed_at` is the
actual collection time. Bounded historical backfill remains a separate
one-shot operation and is never real-time/PIT evidence.

## Candidate preflight and rollback

Before enabling either unit, create the dedicated service account and data
directory, initialise the dedicated SQLite schema, create only the two token
hash/salt files with the exact owner/mode above, and verify no listener exists
on `18083`. The first proof must include authenticated catalog/query readback,
receipt lineage, freshness, and a disabled-timer readback.

Rollback is: `systemctl disable --now tradingdatas-crypto-binance-collect.timer`,
then stop `tradingdatas-crypto-v1-internal.service`. Do not delete Crypto facts
or receipts, and do not stop, reload, reconfigure, or restart A-share units.

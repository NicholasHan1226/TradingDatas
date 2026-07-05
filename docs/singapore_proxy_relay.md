# Singapore Proxy Relay

SharedSignals can prefer a Singapore relay for overseas-only collectors and fall
back to the MarketGraph main server local Clash/Mihomo proxy. This is only for
PM/Crypto style external-market access. Tushare/A-share collection must not use
this route.

Current state:

- Main server: `8.138.181.177`
- Singapore node: `47.82.153.58`
- Current production default: local Clash/Mihomo `http://127.0.0.1:7890`
- Prepared priority variables:
  - `POLYMARKET_HTTP_PROXIES`
  - `BINANCE_HTTP_PROXIES`

Target production value after the Singapore relay is verified:

```bash
POLYMARKET_HTTP_PROXIES=http://47.82.153.58:18888,http://127.0.0.1:7890
BINANCE_HTTP_PROXIES=http://47.82.153.58:18888,http://127.0.0.1:7890
```

## Install Relay

After SSH access to the Singapore server is available, run on that server:

```bash
cd /opt/investment/SharedSignals
bash deploy/install_singapore_proxy_relay.sh
bash deploy/install_singapore_proxy_relay.sh --apply
```

The relay uses `tinyproxy`, allows only `8.138.181.177` by default, and listens
on `18888` unless `SINGAPORE_RELAY_PORT` is set.

## Configure Main Server

Run on the MarketGraph main server:

```bash
cd /opt/investment/SharedSignals
bash deploy/configure_overseas_proxy_priority.sh --relay-url http://47.82.153.58:18888
bash deploy/configure_overseas_proxy_priority.sh --relay-url http://47.82.153.58:18888 --apply
```

The script verifies the relay before writing `.env`, backs up `.env`, then runs
PM dry-run and Crypto ticker collection. If verification fails, it exits without
changing `.env`.

Rollback:

```bash
cp /opt/investment/SharedSignals/.env.bak.<timestamp> /opt/investment/SharedSignals/.env
systemctl restart sharedsignals-api 2>/dev/null || true
```

Validation:

```bash
cd /opt/investment/SharedSignals
cron/pm_collect.sh
cron/crypto_collect.sh
python3 tools/watchdog.py --once --dry-run --no-email
```

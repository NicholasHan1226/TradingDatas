# Singapore Proxy Relay

SharedSignals can prefer a Singapore relay for overseas-only collectors and fall
back to the MarketGraph main server local Clash/Mihomo proxy. This is only for
PM/Crypto style external-market access. Tushare/A-share collection must not use
this route.

Current state:

- Main server: `8.138.181.177`
- Singapore node: `47.82.153.58`
- Production relay path: main-server localhost `http://127.0.0.1:18889`
  forwards over SSH to Singapore localhost `http://127.0.0.1:18888`.
- Fallback path: main-server local Clash/Mihomo `http://127.0.0.1:7890`
- Priority variables:
  - `POLYMARKET_HTTP_PROXIES`
  - `BINANCE_HTTP_PROXIES`

Production value:

```bash
POLYMARKET_HTTP_PROXIES=http://127.0.0.1:18889,http://127.0.0.1:7890
BINANCE_HTTP_PROXIES=http://127.0.0.1:18889,http://127.0.0.1:7890
```

The relay must not expose a public proxy port. Singapore `tinyproxy` listens on
`127.0.0.1:18888` only; the MarketGraph main server reaches it through the
systemd-managed SSH tunnel.

## Install Relay

After SSH access to the Singapore server is available, run on that server:

```bash
cd /opt/investment/SharedSignals
bash deploy/install_singapore_proxy_relay.sh
bash deploy/install_singapore_proxy_relay.sh --apply
```

The relay uses `tinyproxy`, allows only `8.138.181.177` by default, and listens
on `18888` unless `SINGAPORE_RELAY_PORT` is set.

Production hardening:

```bash
sed -i 's/^Listen .*/Listen 127.0.0.1/' /etc/tinyproxy/tinyproxy.conf
systemctl restart tinyproxy
```

Verify:

```bash
ss -ltnp | grep 18888
systemctl is-active tinyproxy
```

The listen address must be `127.0.0.1:18888`, not `0.0.0.0:18888`.

## SSH Tunnel

Run on the MarketGraph main server after a dedicated key has been installed in
Singapore `authorized_keys`:

```bash
cat >/etc/systemd/system/sharedsignals-sg-relay-tunnel.service <<'EOF'
[Unit]
Description=SharedSignals Singapore proxy relay tunnel
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=/usr/bin/ssh -N -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 -o ServerAliveCountMax=3 -o StrictHostKeyChecking=accept-new -i /root/.ssh/sharedsignals_sg_relay_ed25519 -L 127.0.0.1:18889:127.0.0.1:18888 root@47.82.153.58
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable --now sharedsignals-sg-relay-tunnel.service
```

Verify:

```bash
systemctl is-active sharedsignals-sg-relay-tunnel.service
ss -ltnp | grep 18889
curl -fsS --max-time 20 --proxy http://127.0.0.1:18889 https://api.ipify.org
```

The IP check should return `47.82.153.58`.

## Configure Main Server

Run on the MarketGraph main server:

```bash
cd /opt/investment/SharedSignals
bash deploy/configure_overseas_proxy_priority.sh --relay-url http://127.0.0.1:18889
bash deploy/configure_overseas_proxy_priority.sh --relay-url http://127.0.0.1:18889 --apply
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

## 2026-07-05 Production Verification

- Main server tunnel service:
  `sharedsignals-sg-relay-tunnel.service` active and listening on
  `127.0.0.1:18889`.
- Singapore relay: `tinyproxy` active and listening on `127.0.0.1:18888` only.
- Tunnel egress check through `http://127.0.0.1:18889` returned
  `47.82.153.58`.
- `.env` on the main server uses:
  `http://127.0.0.1:18889,http://127.0.0.1:7890` for PM and Binance.
- PM real run: 100 markets and 200 prices collected successfully.
- Crypto real run: 9 intraday rows collected and bridged successfully.
- Watchdog dry run: score 100; API health, DB freshness, collector status,
  disk and memory all `ok`.

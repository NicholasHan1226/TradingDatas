#!/usr/bin/env bash
# Install a restricted HTTP proxy relay on the Singapore node.
#
# Run this on the Singapore server as root after SSH access is available.
# It exposes only an HTTP proxy port and allows only the MarketGraph main
# server IP by default.
set -euo pipefail

PORT="${SINGAPORE_RELAY_PORT:-18888}"
ALLOW_IP="${SINGAPORE_RELAY_ALLOW_IP:-8.138.181.177}"
CONFIG="/etc/tinyproxy/tinyproxy.conf"
BACKUP_DIR="/opt/sharedsignals-relay/backups"

if [[ "${1:-}" != "--apply" ]]; then
  cat <<EOF
dry-run: would install/configure tinyproxy relay
  listen_port=${PORT}
  allow_ip=${ALLOW_IP}
  config=${CONFIG}

Run as root on the Singapore server:
  SINGAPORE_RELAY_PORT=${PORT} SINGAPORE_RELAY_ALLOW_IP=${ALLOW_IP} $0 --apply
EOF
  exit 0
fi

if [[ "$(id -u)" -ne 0 ]]; then
  echo "must run as root" >&2
  exit 2
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y tinyproxy curl

mkdir -p "${BACKUP_DIR}"
if [[ -f "${CONFIG}" ]]; then
  cp "${CONFIG}" "${BACKUP_DIR}/tinyproxy.conf.$(date -u +%Y%m%dT%H%M%SZ)"
fi

cat > "${CONFIG}" <<EOF
User tinyproxy
Group tinyproxy
Port ${PORT}
Listen 0.0.0.0
Timeout 30
DefaultErrorFile "/usr/share/tinyproxy/default.html"
StatFile "/usr/share/tinyproxy/stats.html"
LogFile "/var/log/tinyproxy/tinyproxy.log"
LogLevel Info
PidFile "/run/tinyproxy/tinyproxy.pid"
MaxClients 100
MinSpareServers 5
MaxSpareServers 20
StartServers 10
MaxRequestsPerChild 0
Allow 127.0.0.1
Allow ${ALLOW_IP}
ConnectPort 443
ConnectPort 563
EOF

systemctl enable tinyproxy
systemctl restart tinyproxy

if command -v ufw >/dev/null 2>&1 && ufw status | grep -q "Status: active"; then
  ufw allow from "${ALLOW_IP}" to any port "${PORT}" proto tcp
fi

systemctl --no-pager --full status tinyproxy | sed -n '1,18p'
ss -ltnp | grep ":${PORT}" || {
  echo "tinyproxy did not listen on ${PORT}" >&2
  exit 1
}

echo "OK singapore relay installed on port ${PORT}; allowed source ${ALLOW_IP}"

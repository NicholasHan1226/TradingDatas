#!/usr/bin/env bash
# Configure SharedSignals overseas collectors to prefer a verified Singapore
# relay and fall back to local Clash/Mihomo.
set -euo pipefail

ROOT="${SHAREDSIGNALS_ROOT:-/opt/investment/SharedSignals}"
ENV_FILE="${SHAREDSIGNALS_ENV_FILE:-${ROOT}/.env}"
PYTHON_BIN="${SHAREDSIGNALS_VENV_PYTHON:-/opt/sharedsignals/venv/bin/python3}"
LOCAL_PROXY="${LOCAL_PROXY_URL:-http://127.0.0.1:7890}"
RELAY_URL=""
APPLY=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --relay-url)
      RELAY_URL="${2:-}"
      shift 2
      ;;
    --env-file)
      ENV_FILE="${2:-}"
      shift 2
      ;;
    --apply)
      APPLY=1
      shift
      ;;
    *)
      echo "unknown argument: $1" >&2
      exit 2
      ;;
  esac
done

if [[ -z "${RELAY_URL}" ]]; then
  echo "missing --relay-url, for example http://127.0.0.1:18889" >&2
  exit 2
fi

if ! curl -fsS --proxy "${RELAY_URL}" --max-time 12 https://api.ipify.org >/dev/null; then
  echo "relay smoke failed: ${RELAY_URL}" >&2
  exit 1
fi

PROXY_LIST="${RELAY_URL},${LOCAL_PROXY}"
echo "verified relay; desired proxy priority: ${PROXY_LIST}"

if [[ "${APPLY}" != "1" ]]; then
  cat <<EOF
dry-run: would update ${ENV_FILE}
  POLYMARKET_HTTP_PROXIES=${PROXY_LIST}
  BINANCE_HTTP_PROXIES=${PROXY_LIST}

Run with --apply after review.
EOF
  exit 0
fi

mkdir -p "$(dirname "${ENV_FILE}")"
touch "${ENV_FILE}"
cp "${ENV_FILE}" "${ENV_FILE}.bak.$(date -u +%Y%m%dT%H%M%SZ)"

"${PYTHON_BIN}" - "${ENV_FILE}" "${PROXY_LIST}" <<'PY'
from __future__ import annotations

import sys
from pathlib import Path

env_file = Path(sys.argv[1])
proxy_list = sys.argv[2]
updates = {
    "POLYMARKET_HTTP_PROXIES": proxy_list,
    "BINANCE_HTTP_PROXIES": proxy_list,
}

lines = env_file.read_text(encoding="utf-8").splitlines()
seen: set[str] = set()
out: list[str] = []
for line in lines:
    key = line.split("=", 1)[0].strip() if "=" in line and not line.lstrip().startswith("#") else ""
    if key in updates:
        out.append(f"{key}={updates[key]}")
        seen.add(key)
    else:
        out.append(line)
if out and out[-1].strip():
    out.append("")
for key, value in updates.items():
    if key not in seen:
        out.append(f"{key}={value}")
env_file.write_text("\n".join(out) + "\n", encoding="utf-8")
PY

cd "${ROOT}"
set -a
# shellcheck disable=SC1090
source "${ENV_FILE}"
set +a
"${PYTHON_BIN}" collectors/polymarket_collect.py --limit 3 --dry-run
"${PYTHON_BIN}" - <<'PY'
import os

from collectors.crypto.binance import CryptoCollector

result = CryptoCollector(proxy=os.getenv("BINANCE_HTTP_PROXIES", "")).health_check()
if result.get("status") != "available":
    raise SystemExit(f"binance health failed: {result}")
print(f"binance health ok: {result.get('message', '')}")
PY

echo "OK overseas proxy priority applied and collectors verified"

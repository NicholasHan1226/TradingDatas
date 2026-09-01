#!/bin/bash
# Read-only collector health patrol. Appends one verdict block per run to
# /var/log/tradingdatas-collector-watch.log. Never mutates collector state.
# Exit 0 when verdict=OK, 1 when any [ALERT] line was produced.
set -uo pipefail
LOG=/var/log/tradingdatas-collector-watch.log
UNITS="tradingdatas-crypto-binance-collect tradingdatas-crypto-binance-book-ticker tradingdatas-crypto-binance-usdm-collect tradingdatas-crypto-binance-oi-dump-collect tradingdatas-crypto-binance-premium-dump-collect tradingdatas-crypto-binance-rules tradingdatas-provider-native-collect"
TS=$(date "+%F %T")
OUT=""
VERDICT="OK"

for U in $UNITS; do
  # "state" appears both compact ("state":"x") and spaced ('"state": "x"',
  # default json.dumps) across collector log lines — tolerate both.
  J=$(journalctl -u "$U" --since "-24 hours" --no-pager -o cat 2>/dev/null | grep -oE "\"state\": ?\"(success|unchanged|empty|failed)\"")
  OK=$(printf "%s\n" "$J" | grep -cE "success|unchanged|empty")
  FAIL=$(printf "%s\n" "$J" | grep -c "failed")
  # Recent-window escalation: an outage in progress (all rounds failing for
  # the last hour) must ALERT even while older successes pad the 24h window.
  R=$(journalctl -u "$U" --since "-60 minutes" --no-pager -o cat 2>/dev/null | grep -oE "\"state\": ?\"(success|unchanged|empty|failed)\"")
  ROK=$(printf "%s\n" "$R" | grep -cE "success|unchanged|empty")
  RFAIL=$(printf "%s\n" "$R" | grep -c "failed")
  if [ "$ROK" -eq 0 ] && [ "$RFAIL" -ge 3 ]; then
    OUT+="[ALERT] $U recent1h_fail=$RFAIL recent1h_ok=$ROK window24h_ok=$OK window24h_fail=$FAIL
"
    VERDICT="ALERT"
  elif [ "$OK" -eq 0 ] && [ "$FAIL" -ge 2 ]; then
    OUT+="[ALERT] $U ok=$OK fail=$FAIL window=24h
"
    VERDICT="ALERT"
  elif [ "$FAIL" -ge 3 ]; then
    OUT+="[WARN] $U ok=$OK fail=$FAIL window=24h
"
  elif [ "$OK" -eq 0 ] && [ "$FAIL" -eq 0 ]; then
    # Silent unit: only alarm when its enabled timer also shows no next fire
    # (the monday-* trap). High-frequency timers may show NEXT="-" as a
    # display quirk while firing fine, so silence is required to alarm.
    STALE=0
    if systemctl is-enabled "$U.timer" >/dev/null 2>&1; then
      NEXT=$(systemctl list-timers "$U.timer" --no-pager --no-legend 2>/dev/null | awk "{print \$1}")
      [ -z "$NEXT" ] || [ "$NEXT" = "-" ] && STALE=1
    fi
    if [ "$STALE" -eq 1 ]; then
      OUT+="[ALERT] $U silent-24h-and-timer-stale
"
      VERDICT="ALERT"
    else
      OUT+="[INFO] $U no-rounds-in-24h
"
    fi
  else
    OUT+="[OK] $U ok=$OK fail=$FAIL
"
  fi
done

# Polymarket capture health is a diagnostic only, not SQLite/API authority.
# Failed receipt files must not refresh the age of the last successful capture.
PM_DIR=/opt/investment-data/tradingdatas-crypto/polymarket
if [ -d "$PM_DIR/captures" ] || [ -d "$PM_DIR/receipts" ]; then
  PM_OUT=$(python3 - "$PM_DIR" <<'PYPM'
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

root = Path(sys.argv[1])
now = datetime.now(timezone.utc)
observations = {}
latest_success = None
invalid = 0
for directory in ("captures", "receipts"):
    for path in (root / directory).glob("*.json"):
        try:
            data = json.loads(path.read_text())
            receipt = data.get("receipt", data)
            stamp = datetime.fromisoformat(receipt["observed_at"].replace("Z", "+00:00"))
            state = receipt["state"]
            identity = receipt["capture_id"]
            if stamp.tzinfo is None or stamp > now or state not in {"success", "failed"}:
                raise ValueError("invalid receipt")
            prior = observations.get(identity)
            # Conflicting duplicate receipts are never resolved as success.
            if prior is not None and prior != (stamp, state):
                raise ValueError("conflicting capture identity")
            observations[identity] = (stamp, state)
            if directory == "captures" and state == "success":
                snapshots = data["snapshot_records"]
                markets = data["market_records"]
                if (not snapshots or not markets
                        or len(snapshots) != receipt["snapshot_count"]
                        or len(markets) != receipt["market_count"]):
                    raise ValueError("capture rows are missing")
                latest_success = stamp if latest_success is None else max(latest_success, stamp)
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            invalid += 1
recent = sorted(observations.values(), reverse=True)[:6]
failed = sum(state == "failed" for _, state in recent)
age = None if latest_success is None else (now - latest_success).total_seconds() / 3600
if invalid or age is None or age > 26:
    reason = "invalid-receipts" if invalid else "no-successful-capture" if age is None else "last-success-over-26h"
    print(f"[ALERT] polymarket-snapshot reason={reason} invalid={invalid} last_success_age_h={age} failed_in_last_6={failed}")
    sys.exit(1)
if failed >= 4:
    print(f"[WARN] polymarket-snapshot last_success_age_h={age:.1f} failed_in_last_6={failed}")
else:
    print(f"[OK] polymarket-snapshot last_success_age_h={age:.1f} failed_in_last_6={failed}")
PYPM
  )
  PM_STATUS=$?
  OUT+="$PM_OUT
"
  if [ "$PM_STATUS" -ne 0 ]; then
    VERDICT="ALERT"
    if [ -z "$PM_OUT" ]; then OUT+="[ALERT] polymarket-snapshot inspection-error
"; fi
  elif [[ "$PM_OUT" == "[WARN]"* ]] && [ "$VERDICT" = "OK" ]; then
    VERDICT="WARN"
  fi
fi

# 四十币滚动评估账本新鲜度（每日 05:37 产出；>26h 无新条目告警）
RE_DIR=/var/lib/tradingagent/crypto-40-symbol-rolling-eval
if [ -d "$RE_DIR" ]; then
  RE_LATEST=$(ls -t "$RE_DIR"/entry-*.json 2>/dev/null | head -1 || true)
  if [ -z "$RE_LATEST" ]; then
    OUT+="[ALERT] rolling-eval no-entries dir=$RE_DIR
"
    VERDICT="ALERT"
  else
    RE_AGE_H=$(( ($(date +%s) - $(stat -c %Y "$RE_LATEST")) / 3600 ))
    if [ "$RE_AGE_H" -gt 26 ]; then
      OUT+="[ALERT] rolling-eval last_entry_age_h=$RE_AGE_H (>26h) entry=$(basename "$RE_LATEST")
"
      VERDICT="ALERT"
    else
      OUT+="[OK] rolling-eval latest=$(basename "$RE_LATEST") age_h=$RE_AGE_H
"
    fi
  fi
else
  OUT+="[ALERT] rolling-eval ledger-dir-missing dir=$RE_DIR
"
  VERDICT="ALERT"
fi

for PLANE in "18082 ashare" "18083 crypto"; do
  PORT=${PLANE%% *}
  NAME=${PLANE##* }
  ANON=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 "http://127.0.0.1:$PORT/v1/catalog" || true)
  if [ "$ANON" != "401" ]; then
    OUT+="[ALERT] api-$NAME anon=$ANON expected-401
"
    VERDICT="ALERT"
  else
    OUT+="[OK] api-$NAME anon=401
"
  fi
done

{
  echo "== $TS verdict=$VERDICT"
  printf "%s" "$OUT"
} >> "$LOG"

if [ "$VERDICT" = "ALERT" ]; then exit 1; fi
exit 0

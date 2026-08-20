#!/usr/bin/env python3
"""Report TradingDatas collection health and send webhook alerts.

Read-only: queries the fixed admin API collection status endpoint and
summarizes datasets that are active but failing, stale, or degraded.
Optionally posts the summary to a generic webhook (DingTalk / WeCom text
message compatible).

Usage:
  python3 tools/report_health_alerts.py \
      --api-url http://127.0.0.1:18082 --token <admin-token> \
      [--webhook https://oapi.dingtalk.com/robot/send?access_token=...] \
      [--format dingtalk|generic] [--always] [--dry-run]

Exit codes: 0 healthy, 1 alerts found (and delivered or dry-run), 2 tool error.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request

_UNHEALTHY_RUNTIME_STATES = frozenset({"failed", "stale"})


def _fetch_collection_status(api_url: str, token: str) -> dict:
    url = api_url.rstrip("/") + "/admin/api/collection/status"
    req = urllib.request.Request(url, headers={
        "Authorization": "Bearer " + token,
        "Accept": "application/json",
    })
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _collect_issues(status: dict) -> list[dict]:
    issues = []
    for d in status.get("datasets", []):
        if d.get("activation") != "active":
            continue
        runtime = d.get("runtime_state", "")
        if runtime in _UNHEALTHY_RUNTIME_STATES:
            issues.append({
                "dataset_id": d.get("dataset_id", "?"),
                "kind": runtime,
                "detail": f"runtime_state={runtime}",
            })
    return issues


def _format_text(status: dict, issues: list[dict]) -> str:
    total = status.get("total", 0)
    active = status.get("active", 0)
    paused = status.get("paused", 0)
    lines = [
        f"TradingDatas collection health: {len(issues)} issue(s)",
        f"datasets total={total} active={active} paused={paused}",
    ]
    for issue in issues[:30]:
        lines.append(f"- {issue['dataset_id']}: {issue['detail']}")
    if len(issues) > 30:
        lines.append(f"... and {len(issues) - 30} more")
    return "\n".join(lines)


def _send_webhook(webhook: str, text: str, fmt: str) -> None:
    if fmt == "dingtalk":
        payload = {"msgtype": "text", "text": {"content": text}}
    else:
        payload = {"text": text}
    req = urllib.request.Request(
        webhook,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        resp.read()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-url", default=os.environ.get(
        "TRADINGDATAS_API_URL", "http://127.0.0.1:18082"))
    parser.add_argument("--token", default=os.environ.get("TRADINGDATAS_ADMIN_TOKEN", ""))
    parser.add_argument("--webhook", default=os.environ.get("TRADINGDATAS_ALERT_WEBHOOK", ""))
    parser.add_argument("--format", choices=["dingtalk", "generic"], default="dingtalk")
    parser.add_argument("--always", action="store_true",
                        help="send webhook even when healthy")
    parser.add_argument("--dry-run", action="store_true",
                        help="print payload without sending")
    args = parser.parse_args()

    if not args.token:
        print("error: admin token required (--token or TRADINGDATAS_ADMIN_TOKEN)",
              file=sys.stderr)
        return 2

    try:
        status = _fetch_collection_status(args.api_url, args.token)
    except Exception as exc:
        print(f"error: failed to fetch collection status: {exc}", file=sys.stderr)
        return 2

    issues = _collect_issues(status)
    text = _format_text(status, issues)
    print(text)

    should_send = bool(args.webhook) and (bool(issues) or args.always)
    if args.dry_run:
        if should_send:
            print(f"[dry-run] would POST to {args.webhook}: {text!r}")
        return 1 if issues else 0

    if should_send:
        try:
            _send_webhook(args.webhook, text, args.format)
            print(f"alert delivered to webhook ({args.format})")
        except Exception as exc:
            print(f"error: webhook delivery failed: {exc}", file=sys.stderr)
            return 2
    return 1 if issues else 0


if __name__ == "__main__":
    sys.exit(main())

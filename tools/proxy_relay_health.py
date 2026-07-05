#!/usr/bin/env python3
"""Health report for the overseas proxy relay used by PM/Crypto collectors."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any


DEFAULT_LOCAL_FALLBACK = "http://127.0.0.1:7890"
DEFAULT_EXPECTED_IP = "47.82.153.58"
DEFAULT_SERVICE = "sharedsignals-sg-relay-tunnel.service"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _split_proxies(value: str | None) -> list[str]:
    return [item.strip() for item in (value or "").split(",") if item.strip()]


def _select_relay_url() -> str:
    explicit = os.getenv("PROXY_RELAY_HEALTH_URL")
    if explicit:
        return explicit.strip()
    local_fallback = os.getenv("PROXY_RELAY_LOCAL_FALLBACK", DEFAULT_LOCAL_FALLBACK).strip()
    for env_name in ("POLYMARKET_HTTP_PROXIES", "BINANCE_HTTP_PROXIES"):
        for proxy in _split_proxies(os.getenv(env_name)):
            if proxy != local_fallback:
                return proxy
    return ""


def _check_systemd_service(service: str) -> dict[str, Any]:
    if os.getenv("PROXY_RELAY_CHECK_SYSTEMD", "1") not in {"1", "true", "TRUE", "yes", "YES"}:
        return {"name": "systemd_service", "status": "skipped", "service": service}
    if not service:
        return {"name": "systemd_service", "status": "skipped", "reason": "service_not_configured"}
    if shutil.which("systemctl") is None:
        return {"name": "systemd_service", "status": "skipped", "reason": "systemctl_not_available"}
    try:
        proc = subprocess.run(
            ["systemctl", "is-active", service],
            check=False,
            capture_output=True,
            text=True,
            timeout=8,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {"name": "systemd_service", "status": "critical", "service": service, "error": str(exc)}
    state = (proc.stdout or proc.stderr or "").strip()
    return {
        "name": "systemd_service",
        "status": "ok" if proc.returncode == 0 and state == "active" else "critical",
        "service": service,
        "state": state,
    }


def _fetch_egress_ip(proxy_url: str, timeout: float) -> dict[str, Any]:
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({"http": proxy_url, "https": proxy_url})
    )
    req = urllib.request.Request("https://api.ipify.org", headers={"Accept": "text/plain"})
    started = time.time()
    try:
        with opener.open(req, timeout=timeout) as resp:
            body = resp.read(128).decode("utf-8", errors="replace").strip()
        return {
            "name": "egress_ip",
            "status": "ok",
            "egress_ip": body,
            "elapsed_ms": round((time.time() - started) * 1000, 1),
        }
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return {"name": "egress_ip", "status": "critical", "error": str(exc)}


def check_proxy_relay() -> dict[str, Any]:
    relay_url = _select_relay_url()
    expected_ip = os.getenv("PROXY_RELAY_EXPECTED_IP", DEFAULT_EXPECTED_IP).strip()
    service = os.getenv("PROXY_RELAY_SYSTEMD_SERVICE", DEFAULT_SERVICE).strip()
    timeout = float(os.getenv("PROXY_RELAY_HEALTH_TIMEOUT", "12"))
    checked_at = utc_now()

    if not relay_url:
        return {
            "status": "degraded",
            "component": "singapore_proxy_relay",
            "checked_at": checked_at,
            "reason": "relay_url_not_configured",
            "checks": [],
        }

    checks = [_check_systemd_service(service), _fetch_egress_ip(relay_url, timeout)]
    egress_ip = next((item.get("egress_ip") for item in checks if item.get("name") == "egress_ip"), "")
    if expected_ip and egress_ip and egress_ip != expected_ip:
        checks.append(
            {
                "name": "expected_egress_ip",
                "status": "critical",
                "expected": expected_ip,
                "actual": egress_ip,
            }
        )
    elif expected_ip and egress_ip:
        checks.append({"name": "expected_egress_ip", "status": "ok", "expected": expected_ip, "actual": egress_ip})

    blocking = [item for item in checks if item.get("status") == "critical"]
    skipped = [item for item in checks if item.get("status") == "skipped"]
    status = "critical" if blocking else "ok"
    return {
        "status": status,
        "component": "singapore_proxy_relay",
        "checked_at": checked_at,
        "relay_url": relay_url,
        "expected_egress_ip": expected_ip,
        "egress_ip": egress_ip,
        "summary": {"critical": len(blocking), "skipped": len(skipped)},
        "checks": checks,
    }


def main() -> None:
    print(json.dumps(check_proxy_relay(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # pragma: no cover - last-resort cron-friendly output
        print(
            json.dumps(
                {
                    "status": "critical",
                    "component": "singapore_proxy_relay",
                    "checked_at": utc_now(),
                    "reason": f"{exc.__class__.__name__}: {exc}",
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        sys.exit(1)

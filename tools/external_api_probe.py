#!/usr/bin/env python3
"""Probe the public SharedSignals route without embedding consumer credentials."""

from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


ROOT = Path(os.environ.get("SHAREDSIGNALS_ROOT", Path(__file__).resolve().parents[1]))
DEFAULT_URL = "https://signals.tradingagent.cc/health"
DEFAULT_OUTPUT_PATH = ROOT / "logs" / "watchdog_inputs" / "external_api_probe.json"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def evaluate_probe(*, http_status: int | None, token_configured: bool, error: str = "") -> tuple[str, str]:
    expected = 200 if token_configured else 401
    if error:
        return "red", error
    if http_status == expected:
        return "green", "authenticated health response" if token_configured else "public route reached authentication gate"
    return "red", f"unexpected HTTP status {http_status}; expected {expected}"


def run_probe(url: str, *, token: str = "", timeout: float = 12.0) -> dict[str, Any]:
    headers = {"Accept": "application/json", "User-Agent": "SharedSignals-External-Probe/1.0"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(url, headers=headers)
    started = time.monotonic()
    http_status: int | None = None
    error = ""
    try:
        with urlopen(request, timeout=timeout) as response:
            http_status = int(response.status)
            response.read(1024)
    except HTTPError as exc:
        http_status = int(exc.code)
        exc.read(1024)
    except (URLError, TimeoutError, OSError) as exc:
        error = f"{type(exc).__name__}: {exc}"

    status, message = evaluate_probe(
        http_status=http_status,
        token_configured=bool(token),
        error=error,
    )
    return {
        "status": status,
        "checked_at": utc_now_iso(),
        "url": url,
        "http_status": http_status,
        "token_configured": bool(token),
        "latency_ms": round((time.monotonic() - started) * 1000, 1),
        "message": message,
    }


def write_report(report: dict[str, Any], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_suffix(f".{os.getpid()}.tmp")
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(output_path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=os.environ.get("SHAREDSIGNALS_EXTERNAL_URL", DEFAULT_URL))
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--timeout", type=float, default=12.0)
    args = parser.parse_args()
    report = run_probe(
        args.url,
        token=os.environ.get("SHAREDSIGNALS_EXTERNAL_PROBE_TOKEN", "").strip(),
        timeout=args.timeout,
    )
    write_report(report, args.output)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report["status"] == "green" else 1


if __name__ == "__main__":
    raise SystemExit(main())

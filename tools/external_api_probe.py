#!/usr/bin/env python3
"""Probe the public SharedSignals route without embedding consumer credentials."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
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


def _run_ssh_probe(
    url: str,
    *,
    token: str,
    timeout: float,
    ssh_target: str,
    ssh_key: str,
) -> tuple[int | None, str]:
    command = [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=8",
        "-o",
        "StrictHostKeyChecking=accept-new",
    ]
    if ssh_key:
        command.extend(["-i", ssh_key])
    command.extend([ssh_target, "curl", "-sS", "--max-time", str(max(1, int(timeout))), "-o", "/dev/null", "-w", "%{http_code}"])
    if token:
        command.extend(["-H", f"Authorization: Bearer {token}"])
    command.append(url)
    try:
        completed = subprocess.run(command, capture_output=True, text=True, timeout=timeout + 10, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return None, f"{type(exc).__name__}: {exc}"
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "ssh probe failed").strip()
        return None, f"ssh probe exited {completed.returncode}: {detail}"
    try:
        return int((completed.stdout or "").strip()[-3:]), ""
    except ValueError:
        return None, f"ssh probe returned invalid HTTP status: {completed.stdout!r}"


def run_probe(
    url: str,
    *,
    token: str = "",
    timeout: float = 12.0,
    ssh_target: str = "",
    ssh_key: str = "",
) -> dict[str, Any]:
    headers = {"Accept": "application/json", "User-Agent": "SharedSignals-External-Probe/1.0"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(url, headers=headers)
    started = time.monotonic()
    http_status: int | None = None
    error = ""
    if ssh_target:
        http_status, error = _run_ssh_probe(
            url,
            token=token,
            timeout=timeout,
            ssh_target=ssh_target,
            ssh_key=ssh_key,
        )
    else:
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
        "vantage": f"ssh:{ssh_target}" if ssh_target else "local",
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
    parser.add_argument("--ssh-target", default=os.environ.get("SHAREDSIGNALS_EXTERNAL_PROBE_SSH_TARGET", ""))
    parser.add_argument("--ssh-key", default=os.environ.get("SHAREDSIGNALS_EXTERNAL_PROBE_SSH_KEY", ""))
    args = parser.parse_args()
    report = run_probe(
        args.url,
        token=os.environ.get("SHAREDSIGNALS_EXTERNAL_PROBE_TOKEN", "").strip(),
        timeout=args.timeout,
        ssh_target=args.ssh_target.strip(),
        ssh_key=args.ssh_key.strip(),
    )
    write_report(report, args.output)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report["status"] == "green" else 1


if __name__ == "__main__":
    raise SystemExit(main())

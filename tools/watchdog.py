#!/usr/bin/env python3
"""SharedSignals watchdog for unattended operation.

This is a cron-friendly watchdog: one invocation runs checks, records state,
triggers bounded self-heal/restart actions, and exits. ``cron/watchdog.sh`` is
expected to run it every five minutes with flock.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(os.environ.get("SHAREDSIGNALS_ROOT", Path(__file__).resolve().parents[1]))
RUNTIME_ROOT = Path(os.environ.get("MARKETGRAPH_RUNTIME_ROOT", "/opt/investment/MarketGraphRuntime"))
LOG_DIR = ROOT / "logs"
WATCHDOG_LOG = Path(os.environ.get("WATCHDOG_LOG", LOG_DIR / "watchdog.jsonl"))
WATCHDOG_STATE = Path(os.environ.get("WATCHDOG_STATE", LOG_DIR / "watchdog_state.json"))
WATCHDOG_HALT_FILE = Path(os.environ.get("WATCHDOG_HALT_FILE", LOG_DIR / "WATCHDOG_HALT.json"))
WATCHDOG_INPUT_DIR = Path(os.environ.get("WATCHDOG_INPUT_DIR", LOG_DIR / "watchdog_inputs"))
AUTO_RESTART_SCRIPT = Path(os.environ.get("WATCHDOG_AUTO_RESTART_SCRIPT", ROOT / "tools" / "auto_restart.sh"))
HEAL_SCRIPT = ROOT / "heal.py"

DEFAULT_API_URL = os.environ.get(
    "SHAREDSIGNALS_API_HEALTH_URL",
    f"http://127.0.0.1:{os.environ.get('SHAREDSIGNALS_API_PORT', '8082')}/health",
)
DEFAULT_DB_PATH = Path(
    os.environ.get("WATCHDOG_DB_PATH", RUNTIME_ROOT / "read_model" / "marketdata.sqlite")
)

WEIGHTS = {
    "api_health": 30,
    "db_freshness": 25,
    "collector_status": 20,
    "disk": 15,
    "memory": 10,
    "external_health_sla": 0,
}

HEAL_THRESHOLD = int(os.environ.get("WATCHDOG_HEAL_THRESHOLD", "60"))
CRITICAL_THRESHOLD = int(os.environ.get("WATCHDOG_CRITICAL_THRESHOLD", "30"))
ZERO_HALT_COUNT = int(os.environ.get("WATCHDOG_ZERO_HALT_COUNT", "3"))
RESTART_FAILURE_HALT_COUNT = int(os.environ.get("WATCHDOG_RESTART_FAILURE_HALT_COUNT", "3"))

SOC_EMAIL = os.environ.get("WATCHDOG_SOC_EMAIL", "soc@coze.email")
TRADING_EMAIL = os.environ.get("WATCHDOG_TRADING_EMAIL", "tradingadviser@coze.email")
COLLECTOR_FAILURE_PATTERNS = (
    ("Traceback", r"\bTraceback\b"),
    ("ModuleNotFoundError", r"\bModuleNotFoundError\b"),
    ("ERROR", r"\bERROR\b"),
    ("FAILED", r"\bFAILED\b"),
    ("SQLITE_BRIDGE_ERRORS", r"\bSQLITE_BRIDGE_ERRORS\b"),
    ("bridge_failures", r"\bbridge_failures=([1-9][0-9]*)\b"),
    ("database is locked", r"database is locked"),
)
COLLECTOR_FAILURE_RE = re.compile(
    "|".join(f"(?P<P{idx}>{pattern})" for idx, (_label, pattern) in enumerate(COLLECTOR_FAILURE_PATTERNS)),
    re.IGNORECASE,
)
COLLECTOR_LOG_EXCLUDE = {"watchdog.log"}
CRON_RUN_START_RE = re.compile(r"^\[[^\]]+\] START ", re.MULTILINE)
CRON_RUN_OK_RE = re.compile(r"^\[[^\]]+\] OK ", re.MULTILINE)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
        return default if number != number else number
    except (TypeError, ValueError):
        return default


def _load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def check_api_health(api_url: str = DEFAULT_API_URL, timeout: float = 8.0) -> dict[str, Any]:
    started = time.time()
    try:
        req = urllib.request.Request(api_url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read(65536).decode("utf-8", errors="replace")
            status_code = getattr(resp, "status", 200)
        elapsed_ms = round((time.time() - started) * 1000, 1)
        payload: Any = {}
        try:
            payload = json.loads(body) if body else {}
        except json.JSONDecodeError:
            payload = {"raw": body[:200]}
        ok = 200 <= int(status_code) < 300 and (
            not isinstance(payload, dict)
            or str(payload.get("status", "ok")).lower() in {"ok", "healthy", "degraded"}
        )
        return {
            "name": "api_health",
            "status": "ok" if ok else "critical",
            "score_factor": 1.0 if ok else 0.0,
            "url": api_url,
            "status_code": status_code,
            "elapsed_ms": elapsed_ms,
            "payload_status": payload.get("status") if isinstance(payload, dict) else None,
            "alert": not ok,
        }
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return {
            "name": "api_health",
            "status": "critical",
            "score_factor": 0.0,
            "url": api_url,
            "error": str(exc),
            "alert": True,
        }


def _parse_trade_date(value: Any) -> datetime | None:
    raw = str(value or "").strip()
    digits = "".join(ch for ch in raw if ch.isdigit())
    candidates = [digits[:8], raw[:10]]
    for item in candidates:
        for fmt in ("%Y%m%d", "%Y-%m-%d"):
            try:
                return datetime.strptime(item, fmt).replace(tzinfo=timezone.utc)
            except ValueError:
                continue
    return None


def check_db_freshness(
    db_path: Path = DEFAULT_DB_PATH,
    max_age_days: int | None = None,
) -> dict[str, Any]:
    max_days = max_age_days if max_age_days is not None else int(os.environ.get("WATCHDOG_DB_MAX_AGE_DAYS", "2"))
    if not db_path.exists():
        return {
            "name": "db_freshness",
            "status": "critical",
            "score_factor": 0.0,
            "db_path": str(db_path),
            "latest_trade_date": None,
            "alert": True,
            "reason": "database_not_found",
        }
    latest: str | None = None
    try:
        conn = sqlite3.connect(str(db_path), timeout=5)
        try:
            queries = [
                "SELECT MAX(trade_date) FROM market_bars_daily",
                "SELECT MAX(trade_date) FROM market_bars_intraday",
                "SELECT MAX(event_time) FROM market_events",
            ]
            for sql in queries:
                try:
                    row = conn.execute(sql).fetchone()
                except sqlite3.OperationalError:
                    continue
                value = str(row[0]) if row and row[0] else ""
                if value and (latest is None or value > latest):
                    latest = value
        finally:
            conn.close()
    except sqlite3.Error as exc:
        return {
            "name": "db_freshness",
            "status": "critical",
            "score_factor": 0.0,
            "db_path": str(db_path),
            "error": str(exc),
            "alert": True,
        }
    parsed = _parse_trade_date(latest)
    if parsed is None:
        return {
            "name": "db_freshness",
            "status": "critical",
            "score_factor": 0.0,
            "db_path": str(db_path),
            "latest_trade_date": latest,
            "alert": True,
            "reason": "no_parseable_trade_date",
        }
    age_days = max(0.0, (datetime.now(timezone.utc) - parsed).total_seconds() / 86400.0)
    if age_days <= max_days:
        status, factor = "ok", 1.0
    elif age_days <= max_days * 2:
        status, factor = "degraded", 0.5
    else:
        status, factor = "critical", 0.0
    return {
        "name": "db_freshness",
        "status": status,
        "score_factor": factor,
        "db_path": str(db_path),
        "latest_trade_date": latest,
        "age_days": round(age_days, 2),
        "max_age_days": max_days,
        "alert": status != "ok",
    }


def check_collector_status(
    log_dir: Path | None = None,
    max_age_minutes: int | None = None,
) -> dict[str, Any]:
    directory = log_dir or Path(os.environ.get("WATCHDOG_COLLECTOR_LOG_DIR", ROOT / "logs" / "cron"))
    max_age = max_age_minutes if max_age_minutes is not None else int(os.environ.get("WATCHDOG_COLLECTOR_LOG_MAX_AGE_MIN", "15"))
    if not directory.exists():
        return {
            "name": "collector_status",
            "status": "degraded",
            "score_factor": 0.5,
            "log_dir": str(directory),
            "alert": True,
            "reason": "log_dir_not_found",
        }
    exclude_names = {
        name.strip()
        for name in os.environ.get("WATCHDOG_COLLECTOR_LOG_EXCLUDE", ",".join(sorted(COLLECTOR_LOG_EXCLUDE))).split(",")
        if name.strip()
    }
    files = [path for path in directory.glob("*.log") if path.is_file() and path.name not in exclude_names]
    if not files:
        return {
            "name": "collector_status",
            "status": "degraded",
            "score_factor": 0.5,
            "log_dir": str(directory),
            "alert": True,
            "reason": "no_log_files",
        }
    now = time.time()
    newest = max(files, key=lambda item: item.stat().st_mtime)
    age_minutes = max(0.0, (now - newest.stat().st_mtime) / 60.0)
    if age_minutes <= max_age:
        status, factor = "ok", 1.0
    elif age_minutes <= max_age * 4:
        status, factor = "degraded", 0.5
    else:
        status, factor = "critical", 0.0
    recent_failures = _scan_recent_collector_failures(files, now=now, max_age_minutes=max_age)
    if recent_failures:
        status, factor = "critical", 0.0
    return {
        "name": "collector_status",
        "status": status,
        "score_factor": factor,
        "log_dir": str(directory),
        "latest_log": str(newest),
        "age_minutes": round(age_minutes, 2),
        "max_age_minutes": max_age,
        "alert": status != "ok",
        "failure_patterns": recent_failures,
    }


def _scan_recent_collector_failures(
    files: list[Path],
    *,
    now: float,
    max_age_minutes: int,
) -> list[dict[str, Any]]:
    scan_bytes = int(os.environ.get("WATCHDOG_COLLECTOR_LOG_SCAN_BYTES", "65536"))
    scan_limit = int(os.environ.get("WATCHDOG_COLLECTOR_LOG_SCAN_LIMIT", "10"))
    candidates: list[tuple[Path, float, float]] = []
    for path in files:
        try:
            mtime = path.stat().st_mtime
        except OSError:
            continue
        age_minutes = max(0.0, (now - mtime) / 60.0)
        if age_minutes <= max_age_minutes:
            candidates.append((path, mtime, age_minutes))
    recent_files = sorted(candidates, key=lambda item: item[1], reverse=True)[:scan_limit]
    failures: list[dict[str, Any]] = []
    for path, _, age_minutes in recent_files:
        try:
            with path.open("rb") as handle:
                handle.seek(0, os.SEEK_END)
                size = handle.tell()
                handle.seek(max(0, size - scan_bytes))
                text = handle.read(scan_bytes).decode("utf-8", errors="replace")
        except OSError:
            continue
        text_to_scan = _latest_cron_run_segment(text)
        matches = _collector_failure_labels(text_to_scan)
        if matches:
            failures.append(
                {
                    "log": str(path),
                    "patterns": matches,
                    "age_minutes": round(age_minutes, 2),
                }
            )
    return failures


def _collector_failure_labels(text: str) -> list[str]:
    labels = set()
    for match in COLLECTOR_FAILURE_RE.finditer(text):
        for idx, (label, _pattern) in enumerate(COLLECTOR_FAILURE_PATTERNS):
            if match.group(f"P{idx}") is not None:
                labels.add(label)
                break
    return sorted(labels)


def _latest_cron_run_segment(text: str) -> str:
    """Return the latest cron run block so recovered older errors do not keep alerting."""
    starts = list(CRON_RUN_START_RE.finditer(text))
    if not starts:
        return text
    segment = text[starts[-1].start() :]
    ok_matches = list(CRON_RUN_OK_RE.finditer(segment))
    failure_matches = list(COLLECTOR_FAILURE_RE.finditer(segment))
    if ok_matches and (not failure_matches or ok_matches[-1].start() > failure_matches[-1].start()):
        return ""
    return segment


def check_disk(root: Path = ROOT) -> dict[str, Any]:
    warn = _safe_float(os.environ.get("WATCHDOG_DISK_WARN_PCT"), 80.0)
    critical = _safe_float(os.environ.get("WATCHDOG_DISK_CRITICAL_PCT"), 90.0)
    usage = shutil.disk_usage(str(root))
    pct = round((usage.used / usage.total) * 100.0, 1)
    if pct >= critical:
        status, factor = "critical", 0.0
    elif pct >= warn:
        status, factor = "degraded", 0.5
    else:
        status, factor = "ok", 1.0
    return {
        "name": "disk",
        "status": status,
        "score_factor": factor,
        "used_pct": pct,
        "free_gb": round(usage.free / (1024 ** 3), 2),
        "warn_pct": warn,
        "critical_pct": critical,
        "alert": status != "ok",
    }


def _memory_usage_pct() -> float | None:
    meminfo = Path("/proc/meminfo")
    if meminfo.exists():
        values: dict[str, float] = {}
        for line in meminfo.read_text(encoding="utf-8").splitlines():
            key, _, rest = line.partition(":")
            parts = rest.strip().split()
            if parts:
                values[key] = _safe_float(parts[0]) * 1024
        total = values.get("MemTotal")
        available = values.get("MemAvailable")
        if total and available is not None:
            return round((1.0 - available / total) * 100.0, 1)
    if hasattr(os, "sysconf"):
        try:
            pages = float(os.sysconf("SC_PHYS_PAGES"))
            available = float(os.sysconf("SC_AVPHYS_PAGES"))
            page_size = float(os.sysconf("SC_PAGE_SIZE"))
            total = pages * page_size
            free = available * page_size
            if total > 0:
                return round((1.0 - free / total) * 100.0, 1)
        except (OSError, ValueError):
            return None
    return None


def check_memory() -> dict[str, Any]:
    warn = _safe_float(os.environ.get("WATCHDOG_MEMORY_WARN_PCT"), 85.0)
    critical = _safe_float(os.environ.get("WATCHDOG_MEMORY_CRITICAL_PCT"), 95.0)
    pct = _memory_usage_pct()
    if pct is None:
        return {
            "name": "memory",
            "status": "ok",
            "score_factor": 1.0,
            "used_pct": None,
            "alert": False,
            "reason": "memory_probe_unavailable",
        }
    if pct >= critical:
        status, factor = "critical", 0.0
    elif pct >= warn:
        status, factor = "degraded", 0.5
    else:
        status, factor = "ok", 1.0
    return {
        "name": "memory",
        "status": status,
        "score_factor": factor,
        "used_pct": pct,
        "warn_pct": warn,
        "critical_pct": critical,
        "alert": status != "ok",
    }


def load_external_reports(input_dir: Path = WATCHDOG_INPUT_DIR) -> list[dict[str, Any]]:
    reports: list[dict[str, Any]] = []
    if not input_dir.exists():
        return reports
    max_age_minutes = int(os.environ.get("WATCHDOG_EXTERNAL_REPORT_MAX_AGE_MIN", "15"))
    now = time.time()
    for path in sorted(input_dir.glob("*.json")):
        payload = _load_json(path)
        if not payload:
            continue
        age_minutes = max(0.0, (now - path.stat().st_mtime) / 60.0)
        payload["_path"] = str(path)
        payload["_age_minutes"] = round(age_minutes, 2)
        payload["_stale"] = age_minutes > max_age_minutes
        reports.append(payload)
    return reports


def _external_report_penalty(external_reports: list[dict[str, Any]] | None) -> int:
    penalty = 0
    for report in external_reports or []:
        if report.get("_stale"):
            continue
        status = str(report.get("status", "")).lower()
        if status == "critical":
            penalty += 15
        elif status == "degraded":
            penalty += 5
    return penalty


def compute_health_score(checks: list[dict[str, Any]], external_reports: list[dict[str, Any]] | None = None) -> int:
    score = 0.0
    for check in checks:
        weight = WEIGHTS.get(str(check.get("name")), 0)
        factor = max(0.0, min(1.0, _safe_float(check.get("score_factor"), 0.0)))
        score += weight * factor
    score -= _external_report_penalty(external_reports)
    return int(round(max(0.0, min(100.0, score))))


def run_all_checks() -> tuple[list[dict[str, Any]], list[dict[str, Any]], int]:
    checks = [
        check_api_health(),
        check_db_freshness(),
        check_collector_status(),
        check_disk(),
        check_memory(),
    ]
    external_reports = load_external_reports()
    return checks, external_reports, compute_health_score(checks, external_reports)


def _patrol_like_result(checks: list[dict[str, Any]], score: int) -> dict[str, Any]:
    mapped_checks = []
    for check in checks:
        name = str(check.get("name"))
        if name == "db_freshness":
            mapped_checks.append(
                {
                    "name": "data_freshness",
                    "status": "ok" if check.get("status") == "ok" else "stale",
                    "alert": bool(check.get("alert")),
                    "days_behind": check.get("age_days"),
                    "latest_date": check.get("latest_trade_date"),
                }
            )
        elif name == "disk":
            mapped_checks.append(
                {
                    "name": "disk_usage",
                    "status": "ok" if check.get("status") == "ok" else "warn",
                    "alert": bool(check.get("alert")),
                    "value": check.get("used_pct"),
                    "threshold": check.get("warn_pct"),
                    "stop_threshold": check.get("critical_pct"),
                }
            )
    return {"checks": mapped_checks, "overall_score": score, "score_pct": score, "patrol_at": utc_now()}


def run_heal(checks: list[dict[str, Any]], score: int, *, dry_run: bool = False) -> dict[str, Any]:
    if dry_run:
        return {"action": "heal", "status": "dry_run"}
    if not HEAL_SCRIPT.exists():
        return {"action": "heal", "status": "skipped", "reason": "heal_script_missing"}
    payload_path = LOG_DIR / "watchdog_last_patrol_like.json"
    _write_json(payload_path, _patrol_like_result(checks, score))
    try:
        result = subprocess.run(
            [sys.executable, str(HEAL_SCRIPT), "--patrol-result", str(payload_path)],
            cwd=str(ROOT),
            env={**os.environ, "PYTHONPATH": str(ROOT)},
            capture_output=True,
            text=True,
            timeout=300,
        )
        return {
            "action": "heal",
            "status": "ok" if result.returncode == 0 else "failed",
            "returncode": result.returncode,
            "stdout": result.stdout[-1000:],
            "stderr": result.stderr[-1000:],
        }
    except subprocess.TimeoutExpired:
        return {"action": "heal", "status": "failed", "reason": "timeout"}
    except OSError as exc:
        return {"action": "heal", "status": "failed", "reason": str(exc)}


def run_auto_restart(*, dry_run: bool = False) -> dict[str, Any]:
    if dry_run:
        return {"action": "auto_restart", "status": "dry_run"}
    if not AUTO_RESTART_SCRIPT.exists():
        return {"action": "auto_restart", "status": "failed", "reason": "auto_restart_script_missing"}
    try:
        result = subprocess.run(
            [str(AUTO_RESTART_SCRIPT)],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=180,
            env={**os.environ, "SHAREDSIGNALS_ROOT": str(ROOT)},
        )
        return {
            "action": "auto_restart",
            "status": "ok" if result.returncode == 0 else "failed",
            "returncode": result.returncode,
            "stdout": result.stdout[-1000:],
            "stderr": result.stderr[-1000:],
        }
    except subprocess.TimeoutExpired:
        return {"action": "auto_restart", "status": "failed", "reason": "timeout"}
    except OSError as exc:
        return {"action": "auto_restart", "status": "failed", "reason": str(exc)}


def send_email(to: str, subject: str, html_body: str, *, no_email: bool = False) -> dict[str, Any]:
    if no_email or os.environ.get("WATCHDOG_EMAIL_DISABLED") == "1":
        return {"status": "skipped", "reason": "email_disabled", "to": to, "subject": subject}
    try:
        if str(ROOT) not in sys.path:
            sys.path.insert(0, str(ROOT))
        from tools.email_sender import send_email as send_sharedsignals_email  # noqa: WPS433

        return send_sharedsignals_email(to=to, subject=subject, html_body=html_body, channel="system")
    except Exception as exc:  # noqa: BLE001
        return {"status": "failed", "error": str(exc), "to": to, "subject": subject}


def render_emergency(payload: dict[str, Any]) -> str:
    try:
        if str(ROOT) not in sys.path:
            sys.path.insert(0, str(ROOT))
        from tools.email_templates.emergency_alert import render  # noqa: WPS433

        return render(payload)
    except Exception:
        return "<html><body><pre>" + json.dumps(payload, ensure_ascii=False, indent=2) + "</pre></body></html>"


def write_halt_file(reason: str, details: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "halted_at": utc_now(),
        "reason": reason,
        "details": details,
        "owner_action": "manual_review_required_before_collectors_or_simulation_resume",
    }
    _write_json(WATCHDOG_HALT_FILE, payload)
    return {"action": "write_halt_file", "status": "ok", "path": str(WATCHDOG_HALT_FILE), "reason": reason}


def update_state(
    state: dict[str, Any],
    *,
    score: int,
    actions: list[dict[str, Any]],
) -> tuple[dict[str, Any], bool]:
    previous_score = int(state.get("last_score", 100))
    previous_auto_action = bool(state.get("last_auto_action"))
    recovered = previous_auto_action and score > previous_score
    zero_count = int(state.get("zero_score_count", 0))
    restart_failures = int(state.get("restart_failure_count", 0))
    if score == 0:
        zero_count += 1
    else:
        zero_count = 0
    if any(action.get("action") == "auto_restart" and action.get("status") == "failed" for action in actions):
        restart_failures += 1
    elif any(action.get("action") == "auto_restart" and action.get("status") == "ok" for action in actions):
        restart_failures = 0
    new_state = {
        "updated_at": utc_now(),
        "last_score": score,
        "previous_score": previous_score,
        "zero_score_count": zero_count,
        "restart_failure_count": restart_failures,
        "last_auto_action": any(action.get("action") in {"heal", "auto_restart"} for action in actions),
        "last_actions": actions,
    }
    return new_state, recovered


def watchdog_once(*, dry_run: bool = False, no_email: bool = False) -> dict[str, Any]:
    checks, external_reports, score = run_all_checks()
    state = _load_json(WATCHDOG_STATE)
    actions: list[dict[str, Any]] = []

    if score < HEAL_THRESHOLD:
        actions.append(run_heal(checks, score, dry_run=dry_run))

    if score < CRITICAL_THRESHOLD:
        critical_payload = {
            "severity": "critical",
            "reason": "SharedSignals watchdog score below critical threshold",
            "detected_at": utc_now(),
            "details": {"score": score, "checks": checks},
            "affected_components": [{"component": c["name"], "status": c["status"], "detail": c.get("error") or c.get("reason", "")} for c in checks if c.get("alert")],
            "actions": [{"action": "attempt_auto_restart", "status": "started", "owner": "watchdog"}],
            "human_required": False,
        }
        actions.append({"action": "critical_score", "status": "auto_restart_attempt", "score": score})
        restart_result = run_auto_restart(dry_run=dry_run)
        actions.append(restart_result)
        if restart_result.get("status") == "ok":
            actions.append({"action": "level1_log_only", "status": "auto_restart_succeeded"})
        else:
            actions.append(
                {
                    "action": "level2_restart_failed_email",
                    "recipient": SOC_EMAIL,
                    "dispatch": send_email(
                        SOC_EMAIL,
                        "[SharedSignals] auto_restart failed",
                        render_emergency({**critical_payload, "reason": "auto_restart failed", "human_required": True}),
                        no_email=no_email,
                    ),
                }
            )

    projected_state, recovered = update_state(state, score=score, actions=actions)

    if projected_state["restart_failure_count"] >= RESTART_FAILURE_HALT_COUNT:
        halt = write_halt_file("auto_restart_failed_three_times", {"score": score, "actions": actions})
        actions.append(halt)
        actions.append(
            {
                "action": "level3_trading_email",
                "recipient": TRADING_EMAIL,
                "dispatch": send_email(
                    TRADING_EMAIL,
                    "[SharedSignals] persistent watchdog failure, halt written",
                    render_emergency(
                        {
                            "severity": "critical",
                            "reason": "auto_restart failed three consecutive times",
                            "details": {"score": score, "halt_file": halt.get("path")},
                            "human_required": True,
                        }
                    ),
                    no_email=no_email,
                ),
            }
        )

    if projected_state["zero_score_count"] >= ZERO_HALT_COUNT:
        halt = write_halt_file("dead_man_switch_three_zero_scores", {"score": score, "checks": checks})
        actions.append(halt)
        actions.append(
            {
                "action": "level4_dead_man_email",
                "recipient": SOC_EMAIL,
                "dispatch": send_email(
                    SOC_EMAIL,
                    "[EMERGENCY] SharedSignals dead man switch triggered",
                    render_emergency(
                        {
                            "severity": "critical",
                            "reason": "dead man switch triggered after three 0-score checks",
                            "details": {"score": score, "halt_file": halt.get("path")},
                            "human_required": True,
                        }
                    ),
                    no_email=no_email,
                ),
            }
        )

    new_state, recovered = update_state(state, score=score, actions=actions)
    _write_json(WATCHDOG_STATE, new_state)
    if recovered:
        actions.append({"action": "auto_recovered", "status": "ok", "previous_score": state.get("last_score"), "score": score})

    record = {
        "timestamp": utc_now(),
        "score": score,
        "checks": checks,
        "external_reports": external_reports,
        "actions_taken": actions,
        "recovered": recovered,
        "halt_file": str(WATCHDOG_HALT_FILE) if WATCHDOG_HALT_FILE.exists() else "",
    }
    append_jsonl(WATCHDOG_LOG, record)
    return record


def main() -> None:
    parser = argparse.ArgumentParser(description="SharedSignals watchdog closed-loop monitor")
    parser.add_argument("--once", action="store_true", default=True, help="Run one watchdog cycle")
    parser.add_argument("--loop", action="store_true", help="Run forever, sleeping every interval")
    parser.add_argument("--interval-seconds", type=int, default=300)
    parser.add_argument("--dry-run", action="store_true", help="Do not run heal/restart side effects")
    parser.add_argument("--no-email", action="store_true", help="Do not send emails")
    args = parser.parse_args()

    if args.loop:
        while True:
            print(json.dumps(watchdog_once(dry_run=args.dry_run, no_email=args.no_email), ensure_ascii=False))
            time.sleep(max(1, args.interval_seconds))
    else:
        print(json.dumps(watchdog_once(dry_run=args.dry_run, no_email=args.no_email), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

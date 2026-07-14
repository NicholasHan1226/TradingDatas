#!/usr/bin/env python3
"""Lightweight session gates for production market-data readiness."""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import time as time_module
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from runtime_paths import marketdata_sqlite_path, sharedsignals_root

CN_TZ = timezone(timedelta(hours=8))
MAX_FUTURE_SKEW = timedelta(seconds=5)
PHASES = {
    "preopen": {"label": "preopen", "needs_sample": False},
    "morning_first_sample": {"label": "morning_first_sample", "needs_sample": True, "start": time(9, 25)},
    "afternoon_resume": {"label": "afternoon_resume", "needs_sample": True, "start": time(12, 55)},
    "close_check": {"label": "close_check", "needs_sample": True, "start": time(14, 45)},
}


def _cn_now(now: datetime) -> datetime:
    if now.tzinfo is None:
        return now.replace(tzinfo=timezone.utc).astimezone(CN_TZ)
    return now.astimezone(CN_TZ)


def _date_key(value: Any) -> str:
    text = str(value or "").strip().replace("-", "").replace("/", "")
    return text[:8] if len(text) >= 8 else ""


def _bar_minutes(value: Any) -> int | None:
    text = str(value or "").strip()
    clock_matches = re.findall(r"(?:^|[T\s])(\d{1,2}):(\d{2})(?::\d{2})?", text)
    if clock_matches:
        hour, minute = (int(part) for part in clock_matches[-1])
        return hour * 60 + minute if hour <= 23 and minute <= 59 else None

    digits = "".join(ch for ch in text if ch.isdigit())
    if len(digits) >= 14:
        digits = digits[-6:-2]
    elif len(digits) == 6:
        digits = digits[:4]
    elif len(digits) >= 4:
        digits = digits[-4:]
    else:
        return None
    try:
        hour, minute = int(digits[:2]), int(digits[2:4])
    except ValueError:
        return None
    if hour > 23 or minute > 59:
        return None
    return hour * 60 + minute


def _parse_dt(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def _bar_datetime(row: dict[str, Any]) -> datetime | None:
    day_key = _date_key(row.get("trade_date"))
    text = str(row.get("bar_time") or "").strip()
    if not day_key or not text:
        return None

    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        parsed = None
    if parsed is not None:
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            if parsed.strftime("%Y%m%d") != day_key:
                return None
            return parsed.replace(tzinfo=CN_TZ)
        market_time = parsed.astimezone(CN_TZ)
        return parsed if market_time.strftime("%Y%m%d") == day_key else None

    minutes = _bar_minutes(text)
    if minutes is None:
        return None
    digits = "".join(ch for ch in text if ch.isdigit())
    if len(digits) >= 12 and digits[:8] != day_key:
        return None
    try:
        day = datetime.strptime(day_key, "%Y%m%d")
    except ValueError:
        return None
    return day.replace(hour=minutes // 60, minute=minutes % 60, tzinfo=CN_TZ)


def _sample_rows(rows: list[dict[str, Any]], *, day_key: str, phase_start: time | None, now: datetime) -> list[dict[str, Any]]:
    if now.tzinfo is None or now.utcoffset() is None:
        return []
    now_utc = now.astimezone(timezone.utc)
    upper_bound = now_utc + MAX_FUTURE_SKEW
    cutoff = now_utc - timedelta(minutes=20)
    selected = []
    for row in rows:
        if str(row.get("market") or "").strip().lower() != "ashare":
            continue
        if _date_key(row.get("trade_date")) != day_key:
            continue
        bar_at = _bar_datetime(row)
        if bar_at is None or bar_at.astimezone(timezone.utc) > upper_bound:
            continue
        if phase_start is not None and bar_at.astimezone(CN_TZ).time() < phase_start:
            continue
        collected = _parse_dt(row.get("collected_at"))
        if collected is None or collected < cutoff or collected > upper_bound:
            continue
        selected.append(row)
    return selected


def evaluate_phase(
    phase: str,
    *,
    now: datetime,
    db_ready: bool,
    health_sla_ready: bool,
    intraday_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    if phase not in PHASES:
        raise ValueError(f"unsupported opening gate phase: {phase}")
    cn_now = _cn_now(now)
    spec = PHASES[phase]
    checks: dict[str, Any] = {
        "database_readable": {"status": "green" if db_ready else "red"},
        "health_sla_artifact": {"status": "green" if health_sla_ready else "yellow"},
    }
    failures: list[str] = []
    if not db_ready:
        failures.append("SQLite read model is not readable")
    if not health_sla_ready:
        failures.append("health_sla artifact is missing or stale")

    if spec["needs_sample"]:
        samples = _sample_rows(
            intraday_rows,
            day_key=cn_now.strftime("%Y%m%d"),
            phase_start=spec["start"],
            now=now,
        )
        checks["a_share_intraday"] = {
            "status": "green" if samples else "red",
            "sample_count": len(samples),
            "trade_date": cn_now.strftime("%Y%m%d"),
            "minimum_bar_time": spec["start"].strftime("%H:%M"),
        }
        if phase == "close_check":
            checks["a_share_intraday"]["price_semantics"] = "last_available_rt_min_not_official_close"
        if not samples:
            failures.append("Ashare 5-minute sample has not arrived for the current phase")

    status = "red" if any(item["status"] == "red" for item in checks.values()) else ("yellow" if failures else "green")
    return {
        "status": status,
        "gate": "open" if status == "green" else "closed",
        "phase": phase,
        "checked_at": now.astimezone(timezone.utc).isoformat(),
        "market_timezone": "Asia/Shanghai",
        "checks": checks,
        "action_required": "; ".join(failures) if failures else "none",
    }


def _health_sla_ready(path: Path, now: datetime) -> bool:
    try:
        age = now.astimezone(timezone.utc).timestamp() - path.stat().st_mtime
        if age > 30 * 60 or age < -60:
            return False
        payload = json.loads(path.read_text(encoding="utf-8"))
        summary = payload.get("summary", {}) if isinstance(payload, dict) else {}
        return not bool(summary.get("critical"))
    except (OSError, ValueError, TypeError):
        return False


def collect_gate(phase: str, *, now: datetime | None = None, db_path: Path | None = None, artifact_path: Path | None = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    db_path = db_path or marketdata_sqlite_path()
    artifact_path = artifact_path or (Path(os.environ.get("WATCHDOG_INPUT_DIR", sharedsignals_root() / "logs" / "watchdog_inputs")) / "health_sla.json")
    rows: list[dict[str, Any]] = []
    db_ready = False
    error = None
    try:
        day_start = _cn_now(now).replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc).isoformat()
        with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=3) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA query_only = ON")
            conn.execute("SELECT 1").fetchone()
            rows = [dict(row) for row in conn.execute(
                "SELECT market, symbol, trade_date, bar_time, collected_at "
                "FROM market_bars_intraday "
                "WHERE market = 'Ashare' AND collected_at >= ? "
                "ORDER BY collected_at DESC LIMIT 500",
                (day_start,),
            )]
            db_ready = True
    except (OSError, sqlite3.Error) as exc:
        error = str(exc)
    result = evaluate_phase(
        phase,
        now=now,
        db_ready=db_ready,
        health_sla_ready=_health_sla_ready(artifact_path, now),
        intraday_rows=rows,
    )
    result["database"] = str(db_path)
    result["health_sla_artifact"] = str(artifact_path)
    result["query_rows"] = len(rows)
    if error:
        result["database_error"] = error
    return result


def _sample_missing_is_only_failure(result: dict[str, Any]) -> bool:
    checks = result.get("checks", {})
    sample = checks.get("a_share_intraday", {})
    return (
        checks.get("database_readable", {}).get("status") == "green"
        and checks.get("health_sla_artifact", {}).get("status") == "green"
        and sample.get("status") == "red"
    )


def collect_gate_with_retry(
    phase: str,
    *,
    db_path: Path | None = None,
    artifact_path: Path | None = None,
    retry_interval_seconds: float = 5.0,
    retry_window_seconds: float = 20.0,
    now_fn: Callable[[], datetime] | None = None,
    monotonic_fn: Callable[[], float] = time_module.monotonic,
    sleep_fn: Callable[[float], None] = time_module.sleep,
) -> dict[str, Any]:
    """Re-read only when a healthy P0 lane may still be committing its phase bar."""
    if retry_interval_seconds <= 0 or retry_window_seconds < 0:
        raise ValueError("opening gate retry interval must be positive and window non-negative")

    now_fn = now_fn or (lambda: datetime.now(timezone.utc))
    started = monotonic_fn()
    attempts = 0
    result: dict[str, Any]
    while True:
        attempts += 1
        result = collect_gate(phase, now=now_fn(), db_path=db_path, artifact_path=artifact_path)
        if result["status"] == "green":
            reason = "sample_arrived_within_retry_window" if attempts > 1 else "not_needed"
            break
        if not _sample_missing_is_only_failure(result):
            reason = "ineligible_failure"
            break
        elapsed = monotonic_fn() - started
        remaining = retry_window_seconds - elapsed
        if remaining < retry_interval_seconds:
            reason = "sample_retry_window_exhausted"
            break
        sleep_fn(retry_interval_seconds)

    result["attempt_count"] = attempts
    result["retry"] = {
        "interval_seconds": retry_interval_seconds,
        "window_seconds": retry_window_seconds,
        "elapsed_seconds": max(0.0, monotonic_fn() - started),
        "reason": reason,
    }
    return result


def output_path() -> Path:
    return Path(os.environ.get("WATCHDOG_INPUT_DIR", sharedsignals_root() / "logs" / "watchdog_inputs")) / "opening_gate.json"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=sorted(PHASES), required=True)
    args = parser.parse_args()
    result = collect_gate_with_retry(
        args.phase,
        retry_interval_seconds=float(os.environ.get("SHAREDSIGNALS_OPENING_GATE_RETRY_INTERVAL", "5")),
        retry_window_seconds=float(os.environ.get("SHAREDSIGNALS_OPENING_GATE_RETRY_WINDOW", "20")),
    )
    target = output_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_suffix(f".{os.getpid()}.tmp")
    temp.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(target)
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["status"] == "green" else 1


if __name__ == "__main__":
    raise SystemExit(main())

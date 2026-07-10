#!/usr/bin/env python3
"""Lightweight session gates for production market-data readiness."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any

from runtime_paths import marketdata_sqlite_path, runtime_root, sharedsignals_root

CN_TZ = timezone(timedelta(hours=8))
PHASES = {
    "preopen": {"label": "preopen", "needs_sample": False},
    "morning_first_sample": {"label": "morning_first_sample", "needs_sample": True, "start": time(9, 25)},
    "afternoon_resume": {"label": "afternoon_resume", "needs_sample": True, "start": time(12, 55)},
    "close_check": {"label": "close_check", "needs_sample": True, "start": time(14, 55)},
}


def _cn_now(now: datetime) -> datetime:
    if now.tzinfo is None:
        return now.replace(tzinfo=timezone.utc).astimezone(CN_TZ)
    return now.astimezone(CN_TZ)


def _date_key(value: Any) -> str:
    text = str(value or "").strip().replace("-", "").replace("/", "")
    return text[:8] if len(text) >= 8 else ""


def _bar_minutes(value: Any) -> int | None:
    digits = "".join(ch for ch in str(value or "") if ch.isdigit())
    if len(digits) >= 12:
        digits = digits[-4:]
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
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


def _sample_rows(rows: list[dict[str, Any]], *, day_key: str, phase_start: time | None, now: datetime) -> list[dict[str, Any]]:
    cutoff = now.astimezone(timezone.utc) - timedelta(minutes=20)
    selected = []
    for row in rows:
        if str(row.get("market") or "").strip().lower() != "ashare":
            continue
        if _date_key(row.get("trade_date")) != day_key:
            continue
        bar_minutes = _bar_minutes(row.get("bar_time"))
        if phase_start is not None and (bar_minutes is None or bar_minutes < phase_start.hour * 60 + phase_start.minute):
            continue
        collected = _parse_dt(row.get("collected_at"))
        if collected is None or collected < cutoff:
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
    artifact_path = artifact_path or (Path(os.environ.get("WATCHDOG_INPUT_DIR", runtime_root() / "logs" / "watchdog_inputs")) / "health_sla.json")
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


def output_path() -> Path:
    return Path(os.environ.get("WATCHDOG_INPUT_DIR", runtime_root() / "logs" / "watchdog_inputs")) / "opening_gate.json"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=sorted(PHASES), required=True)
    args = parser.parse_args()
    result = collect_gate(args.phase)
    target = output_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_suffix(f".{os.getpid()}.tmp")
    temp.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(target)
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["status"] == "green" else 1


if __name__ == "__main__":
    raise SystemExit(main())

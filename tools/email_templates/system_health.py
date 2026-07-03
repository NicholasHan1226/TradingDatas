#!/usr/bin/env python3
"""SharedSignals system health email template."""

from __future__ import annotations

from . import _badge, _chart_grid, _donut_chart, _html, _progress_bars_chart, _records, _section, _summary, _table, wrap_html


def _status_bucket(status: object) -> str:
    normalized = str(status or "").lower()
    if any(word in normalized for word in ("critical", "fatal", "failed", "error", "alert", "stale")):
        return "alert"
    if any(word in normalized for word in ("degraded", "late", "warn", "breach", "watch")):
        return "degraded"
    if any(word in normalized for word in ("ok", "healthy", "pass", "fresh", "success", "normal")):
        return "ok"
    return "degraded"


def _health_pct(records: list[dict], status_key: str = "status") -> float:
    if not records:
        return 0.0
    ok_count = sum(1 for item in records if _status_bucket(item.get(status_key, item.get("health"))) == "ok")
    return ok_count * 100 / len(records)


def render(data: dict) -> str:
    overall = data.get("overall_status") or data.get("status") or "unknown"
    score = data.get("overall_score", data.get("score", "--"))
    sources = _records(data.get("source_health") or data.get("sources"), "source")
    freshness = _records(data.get("data_freshness") or data.get("freshness"), "dataset")
    db = data.get("db_integrity") or data.get("sqlite_health") or {}
    disk = data.get("disk_usage") or {}
    heal = _records(data.get("heal_actions") or data.get("heal_status"), "action")

    stale_count = sum(1 for item in sources + freshness if str(item.get("status", "")).lower() in {"stale", "late", "failed"})
    disk_pct = disk.get("used_pct", disk.get("usage_pct", disk.get("percent", "--")))
    status_items = (
        [{"status": item.get("status", item.get("health"))} for item in sources]
        + [{"status": item.get("status")} for item in freshness]
        + [{"status": db.get("status", "--")}, {"status": disk.get("status", "ok")}]
    )
    breakdown = {"ok": 0, "degraded": 0, "alert": 0}
    for item in status_items:
        breakdown[_status_bucket(item.get("status"))] += 1
    disk_used = 0.0
    try:
        disk_used = float(str(disk_pct).replace("%", ""))
    except (TypeError, ValueError):
        disk_used = 0.0
    chart_html = _chart_grid([
        _donut_chart(
            "Health status breakdown",
            [
                {"label": "ok", "value": breakdown["ok"], "color": "#22c55e"},
                {"label": "degraded", "value": breakdown["degraded"], "color": "#f59e0b"},
                {"label": "alert", "value": breakdown["alert"], "color": "#ef4444"},
            ],
            center_label="checks",
            chart_id="health-status",
        ),
        _progress_bars_chart(
            "Check progress",
            [
                {"label": "source_health", "percent": _health_pct(sources), "status": "ok" if _health_pct(sources) >= 80 else "degraded"},
                {"label": "data_freshness", "percent": _health_pct(freshness), "status": "ok" if _health_pct(freshness) >= 80 else "degraded"},
                {"label": "DB integrity", "percent": 100 if _status_bucket(db.get("status")) == "ok" else 35, "status": db.get("status", "unknown")},
                {"label": "disk", "percent": max(0, 100 - disk_used), "status": disk.get("status", "ok")},
            ],
        ),
    ])

    summary_html = _summary([
        {"label": "Overall", "value": overall, "status": overall, "detail": f"score={score}"},
        {"label": "Stale items", "value": stale_count, "detail": "sources + datasets"},
        {"label": "DB integrity", "value": db.get("status", "--"), "status": db.get("status", "--")},
        {"label": "Disk usage", "value": disk_pct, "detail": disk.get("path", disk.get("mount", ""))},
    ])

    source_rows = []
    for item in sources:
        status = item.get("status", item.get("health", "--"))
        source_rows.append([
            _html(item.get("source")),
            _badge(status),
            _html(item.get("last_success") or item.get("last_seen") or item.get("last_update")),
            _html(item.get("freshness") or item.get("age") or item.get("lag")),
            _html(item.get("note") or item.get("alert")),
        ])

    freshness_rows = []
    for item in freshness:
        status = item.get("status", "--")
        freshness_rows.append([
            _html(item.get("dataset")),
            _badge(status),
            _html(item.get("latest") or item.get("actual")),
            _html(item.get("expected") or item.get("threshold")),
            _html(item.get("age") or item.get("lag")),
        ])

    integrity_rows = [
        ["SQLite", _badge(db.get("status", "--")), _html(db.get("latest_check") or db.get("checked_at")), _html(db.get("details") or db.get("error"))],
        ["WAL", _html(db.get("wal_size", "--")), _html(db.get("wal_threshold", "--")), _html(db.get("wal_action", ""))],
        ["Disk", _html(disk_pct), _html(disk.get("threshold", "--")), _html(disk.get("free") or disk.get("free_gb"))],
    ]

    heal_rows = []
    for item in heal:
        status = item.get("status", "--")
        heal_rows.append([
            _html(item.get("action")),
            _badge(status),
            _html(item.get("started_at") or item.get("updated_at")),
            _html(item.get("result") or item.get("next_step")),
        ])

    body = (
        _section("Summary", summary_html)
        + _section("Health Charts", chart_html)
        + _section("Source Health", _table(["Source", "Status", "Last OK", "Freshness", "Note"], source_rows))
        + _section("Data Freshness", _table(["Dataset", "Status", "Actual", "Expected", "Age"], freshness_rows))
        + _section("Integrity And Capacity", _table(["Check", "Current", "Expected", "Detail"], integrity_rows))
        + _section("Heal Actions", _table(["Action", "Status", "Time", "Result"], heal_rows))
    )
    return wrap_html("SharedSignals System Health", "Patrol and heal status", "SharedSignals", body)

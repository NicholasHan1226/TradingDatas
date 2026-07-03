#!/usr/bin/env python3
"""SharedSignals stale data alert email template."""

from __future__ import annotations

from . import _badge, _chart_grid, _grouped_bar_chart, _html, _records, _section, _sparkline_chart, _summary, _table, wrap_html


def _age_value(item: dict, *keys: str) -> object:
    for key in keys:
        if item.get(key) not in (None, ""):
            return item.get(key)
    return 0


def render(data: dict) -> str:
    sources = _records(data.get("stale_sources") or data.get("sources"), "source")
    severity = data.get("severity", "stale")
    max_age = data.get("max_age") or data.get("oldest_age") or "--"
    window = data.get("window") or data.get("checked_at") or "--"

    summary_html = _summary([
        {"label": "Severity", "value": severity, "status": severity, "detail": "freshness alert"},
        {"label": "Stale sources", "value": len(sources), "detail": f"window={window}"},
        {"label": "Max age", "value": max_age, "detail": data.get("max_age_source", "")},
        {"label": "Action", "value": data.get("action_required", "review"), "status": data.get("action_required", "review")},
    ])
    chart_rows = []
    for item in sources:
        chart_rows.append({
            "source": item.get("source"),
            "expected": _age_value(item, "expected_age", "expected_minutes", "threshold_minutes", "threshold", "expected"),
            "actual": _age_value(item, "actual_age", "age_minutes", "lag_minutes", "age", "lag", "actual"),
            "trend": item.get("trend") or item.get("history") or item.get("age_history"),
        })
    chart_html = _chart_grid([
        _grouped_bar_chart("Expected vs actual source age", chart_rows, "source"),
        _sparkline_chart("Stale source age trend", chart_rows, "source"),
    ])

    stale_rows = []
    for item in sources:
        status = item.get("status", "stale")
        stale_rows.append([
            _html(item.get("source")),
            _badge(status),
            _html(item.get("expected") or item.get("expected_time") or item.get("threshold")),
            _html(item.get("actual") or item.get("latest") or item.get("last_seen")),
            _html(item.get("age") or item.get("lag") or item.get("age_minutes")),
        ])

    recovery = _records(data.get("recovery") or data.get("next_checks"), "step")
    recovery_rows = []
    for item in recovery:
        recovery_rows.append([
            _html(item.get("step")),
            _badge(item.get("status", "pending")),
            _html(item.get("owner", "SharedSignals")),
            _html(item.get("eta") or item.get("next_run")),
        ])

    body = (
        _section("Summary", summary_html)
        + _section("Freshness Charts", chart_html)
        + _section("Stale Data", _table(["Source", "Status", "Expected", "Actual", "Age"], stale_rows))
        + _section("Recovery", _table(["Step", "Status", "Owner", "ETA"], recovery_rows))
    )
    return wrap_html("SharedSignals Data Freshness Alert", "Stale source detail", "SharedSignals", body)

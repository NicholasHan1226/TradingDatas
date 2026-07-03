#!/usr/bin/env python3
"""SharedSignals emergency alert email template."""

from __future__ import annotations

from . import _badge, _chart_grid, _html, _records, _section, _severity_indicator_chart, _summary, _table, _timeline_bars_chart, wrap_html


def render(data: dict) -> str:
    severity = data.get("severity", "critical")
    reason = data.get("reason") or data.get("title") or "--"
    components = _records(data.get("components") or data.get("affected_components"), "component")
    actions = _records(data.get("actions") or data.get("action_required"), "action")
    history = _records(data.get("alert_history") or data.get("history") or data.get("timeline"), "time")

    summary_html = _summary([
        {"label": "Severity", "value": severity, "status": severity, "detail": data.get("alert_id", "")},
        {"label": "Reason", "value": reason, "detail": data.get("detected_at", "")},
        {"label": "Affected", "value": len(components), "detail": "components"},
        {"label": "Human action", "value": data.get("human_required", True), "status": "critical" if data.get("human_required", True) else "ok"},
    ])
    chart_html = _chart_grid([
        _severity_indicator_chart("Severity indicator", severity, data.get("alert_id") or reason),
        _timeline_bars_chart("Alert history timeline", history or components, label_key="time"),
    ])

    detail_rows = [
        ["Reason", _html(reason)],
        ["Details", _html(data.get("details") or data.get("description"))],
        ["Impact", _html(data.get("impact"))],
        ["Runbook", _html(data.get("runbook") or data.get("runbook_path"))],
    ]

    component_rows = []
    for item in components:
        status = item.get("status", "critical")
        component_rows.append([
            _html(item.get("component")),
            _badge(status),
            _html(item.get("detail") or item.get("error")),
            _html(item.get("since") or item.get("last_ok")),
        ])

    action_rows = []
    for item in actions:
        status = item.get("status", "required")
        action_rows.append([
            _html(item.get("action")),
            _badge(status),
            _html(item.get("owner", "operator")),
            _html(item.get("deadline") or item.get("eta")),
        ])

    body = (
        _section("Summary", summary_html)
        + _section("Emergency Charts", chart_html)
        + _section("Issue Detail", _table(["Field", "Value"], detail_rows))
        + _section("Affected Components", _table(["Component", "Status", "Detail", "Since"], component_rows))
        + _section("Action Required", _table(["Action", "Status", "Owner", "Deadline"], action_rows))
    )
    return wrap_html("SharedSignals Emergency Alert", "Critical operational issue", "SharedSignals", body)

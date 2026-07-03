#!/usr/bin/env python3
"""SharedSignals collection error email template."""

from __future__ import annotations

from . import _badge, _chart_grid, _donut_chart, _format_pct, _horizontal_bar_chart, _html, _number, _records, _section, _summary, _table, wrap_html


def render(data: dict) -> str:
    api_name = data.get("api_name") or data.get("source") or data.get("collector") or "--"
    error_count = data.get("error_count", 0)
    failure_rate = data.get("failure_rate", "--")
    failures = _records(data.get("failures") or data.get("errors"), "api")
    affected = _records(data.get("affected_outputs") or data.get("affected_tables"), "output")
    failure_total = sum(_number(item.get("error_count", item.get("count", 0))) for item in failures) or _number(error_count)
    total_count = data.get("total_count") or data.get("request_count") or data.get("attempt_count") or 0
    success_count = data.get("success_count")
    if success_count is None:
        try:
            success_count = max(0.0, _number(total_count) - failure_total)
        except (TypeError, ValueError):
            success_count = 0.0

    summary_html = _summary([
        {"label": "API", "value": api_name, "detail": data.get("provider", "")},
        {"label": "Errors", "value": error_count, "status": "error" if error_count else "ok"},
        {"label": "Failure rate", "value": _format_pct(failure_rate), "detail": data.get("window", "")},
        {"label": "Status", "value": data.get("status", "failed"), "status": data.get("status", "failed")},
    ])
    chart_html = _chart_grid([
        _horizontal_bar_chart("Failure counts per API", failures, label_key="api", value_key="error_count", color="#ef4444"),
        _donut_chart(
            "Success / failure ratio",
            [
                {"label": "success", "value": success_count, "color": "#22c55e"},
                {"label": "failure", "value": failure_total, "color": "#ef4444"},
            ],
            center_label="attempts",
            chart_id="collection-ratio",
        ),
    ])

    failure_rows = []
    for item in failures:
        status = item.get("status", item.get("severity", "failed"))
        failure_rows.append([
            _html(item.get("api")),
            _html(item.get("error_count", item.get("count", "--"))),
            _html(_format_pct(item.get("failure_rate", item.get("rate", "--")))),
            _badge(status),
            _html(item.get("last_error") or item.get("message")),
        ])

    affected_rows = []
    for item in affected:
        affected_rows.append([
            _html(item.get("output")),
            _html(item.get("rows_expected") or item.get("expected")),
            _html(item.get("rows_actual") or item.get("actual")),
            _badge(item.get("status", "degraded")),
        ])

    action_rows = []
    for item in _records(data.get("actions") or data.get("next_actions"), "action"):
        action_rows.append([
            _html(item.get("action")),
            _badge(item.get("status", "pending")),
            _html(item.get("owner", "SharedSignals")),
            _html(item.get("eta") or item.get("deadline")),
        ])

    body = (
        _section("Summary", summary_html)
        + _section("Failure Charts", chart_html)
        + _section("Collection Failures", _table(["API", "Errors", "Failure Rate", "Status", "Last Error"], failure_rows))
        + _section("Affected Outputs", _table(["Output", "Expected", "Actual", "Status"], affected_rows))
        + _section("Next Actions", _table(["Action", "Status", "Owner", "ETA"], action_rows))
    )
    return wrap_html("SharedSignals Collection Error", "Collector failure summary", "SharedSignals", body)

#!/usr/bin/env python3
"""SharedSignals HTML email template utilities."""

from __future__ import annotations

from datetime import datetime
from html import escape
import math
import re
from typing import Any


CHANNELS = {
    "system": {
        "from": "notice@tradingagent.cc",
        "to": "soc@coze.email",
        "label": "system",
    },
}

TEMPLATE_CHANNELS = {
    "system_health": "system",
    "data_freshness_alert": "system",
    "collection_error": "system",
    "emergency_alert": "system",
}


def _css() -> str:
    return """
    <style>
      body { font-family: -apple-system, BlinkMacSystemFont, 'PingFang SC', 'Microsoft YaHei', Arial, sans-serif; margin: 0; padding: 20px; background: #f5f5f5; color: #333; }
      .container { max-width: 680px; margin: 0 auto; background: #fff; border-radius: 8px; overflow: hidden; border: 1px solid #e8e8e8; }
      .header { background: #1a1a2e; color: #fff; padding: 20px 24px; }
      .header h1 { margin: 0; font-size: 18px; line-height: 1.35; font-weight: 600; letter-spacing: 0; }
      .header .meta { font-size: 12px; color: #b7bac8; margin-top: 5px; }
      .body { padding: 24px; }
      .section { margin-bottom: 20px; }
      .section-title { font-size: 14px; line-height: 1.4; font-weight: 600; color: #333; border-left: 3px solid #4a6cf7; padding-left: 8px; margin-bottom: 10px; }
      .summary-grid { display: table; width: 100%; border-spacing: 0 8px; margin-bottom: 16px; }
      .summary-row { display: table-row; }
      .summary-box { display: table-cell; width: 50%; background: #f8f9fa; border-radius: 6px; padding: 12px 14px; border: 1px solid #eceff3; }
      .summary-gap { display: table-cell; width: 8px; }
      .label { font-size: 12px; color: #888; line-height: 1.35; }
      .value { font-size: 20px; font-weight: 700; color: #333; line-height: 1.3; margin-top: 2px; }
      .detail { font-size: 12px; color: #888; line-height: 1.4; margin-top: 4px; }
      table { width: 100%; border-collapse: collapse; font-size: 13px; }
      th { background: #f8f9fa; text-align: left; padding: 8px 10px; color: #666; font-weight: 500; border-bottom: 1px solid #e0e0e0; }
      td { padding: 8px 10px; border-bottom: 1px solid #f0f0f0; color: #333; vertical-align: top; }
      .badge { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 12px; font-weight: 600; line-height: 1.4; white-space: nowrap; }
      .badge.positive { background: #eafaf1; color: #1e7e48; }
      .badge.negative { background: #fff3cd; color: #856404; }
      .badge.neutral { background: #f0f0f0; color: #666; }
      .badge.critical { background: #fde8e8; color: #c0392b; }
      .meter { width: 90px; height: 6px; background: #edf0f3; border-radius: 999px; overflow: hidden; display: inline-block; vertical-align: middle; margin-right: 6px; }
      .meter-fill { height: 6px; background: #4a6cf7; border-radius: 999px; display: block; }
      .chart-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; margin-bottom: 16px; }
      .chart-figure { margin: 0; padding: 12px; background: #1a1a2e; border-radius: 8px; color: #f8fafc; overflow: hidden; border: 1px solid #2e3356; }
      .chart-figure svg { display: block; width: 100%; height: auto; margin: 0 auto; }
      .chart-figure.chart-small svg { max-width: 200px; }
      .chart-figure.chart-wide { grid-column: 1 / -1; }
      .chart-figure.chart-wide svg { max-width: 600px; }
      .chart-figure figcaption { margin-top: 8px; color: #c8cce0; font-size: 12px; line-height: 1.4; text-align: center; }
      .pulse-ring { animation: pulse-alert 1.45s ease-out infinite; transform-origin: center; }
      @keyframes pulse-alert {
        0% { opacity: 0.85; }
        70% { opacity: 0.12; }
        100% { opacity: 0; }
      }
      .empty { background: #f8f9fa; border-radius: 6px; padding: 12px 14px; color: #888; font-size: 13px; }
      .footer { padding: 16px 24px; background: #f8f9fa; font-size: 11px; color: #999; text-align: center; line-height: 1.5; }
      @media only screen and (max-width: 520px) {
        body { padding: 12px; }
        .body { padding: 18px; }
        .summary-box, .summary-gap, .summary-row, .summary-grid { display: block; width: auto; }
        .summary-gap { height: 8px; }
        .chart-grid { display: block; }
        .chart-figure { margin-bottom: 12px; }
        .chart-figure.chart-wide { grid-column: auto; }
        th, td { padding: 7px 8px; }
      }
    </style>
    """


def _text(value: Any, default: str = "--") -> str:
    if value is None:
        return default
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, (list, tuple, set)):
        if not value:
            return default
        return ", ".join(_text(item, default) for item in value)
    if isinstance(value, dict):
        if not value:
            return default
        return ", ".join(f"{key}={_text(val, default)}" for key, val in value.items())
    value_str = str(value)
    return value_str if value_str else default


def _html(value: Any, default: str = "--") -> str:
    return escape(_text(value, default))


def _records(value: Any, name_key: str = "name") -> list[dict[str, Any]]:
    if value is None:
        return []
    if isinstance(value, dict):
        rows: list[dict[str, Any]] = []
        for key, item in value.items():
            if isinstance(item, dict):
                row = {name_key: key}
                row.update(item)
            else:
                row = {name_key: key, "value": item}
            rows.append(row)
        return rows
    if isinstance(value, list):
        return [item if isinstance(item, dict) else {name_key: item} for item in value]
    return [{name_key: value}]


def _status_class(status: Any) -> str:
    normalized = _text(status, "").lower()
    if any(word in normalized for word in ("critical", "fatal", "halt", "emergency", "p0")):
        return "critical"
    if any(word in normalized for word in ("fail", "error", "stale", "degraded", "late", "warn", "breach")):
        return "negative"
    if any(word in normalized for word in ("ok", "healthy", "pass", "fresh", "sent", "resolved", "success", "normal")):
        return "positive"
    return "neutral"


def _badge(label: Any, status: Any | None = None) -> str:
    label_text = _html(label)
    return f'<span class="badge {_status_class(status if status is not None else label)}">{label_text}</span>'


def _format_pct(value: Any, decimals: int = 1) -> str:
    if value is None or value == "":
        return "--"
    try:
        number = float(value)
    except (TypeError, ValueError):
        text = _text(value)
        return text if text.endswith("%") else text
    if abs(number) <= 1:
        number *= 100
    return f"{number:.{decimals}f}%"


def _meter(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return _html(value)
    width = number * 100 if abs(number) <= 1 else number
    width = max(0.0, min(width, 100.0))
    return f'<span class="meter"><span class="meter-fill" style="width:{width:.1f}%"></span></span>{width:.1f}%'


def _number(value: Any, default: float = 0.0) -> float:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, (int, float)):
        return float(value)
    match = re.search(r"-?\d+(?:\.\d+)?", str(value).replace(",", ""))
    if not match:
        return default
    try:
        return float(match.group(0))
    except ValueError:
        return default


def _clamp(value: float, minimum: float = 0.0, maximum: float = 100.0) -> float:
    return max(minimum, min(maximum, value))


def _percent_value(value: Any, default: float = 0.0) -> float:
    number = _number(value, default)
    if abs(number) <= 1 and "%" not in str(value):
        number *= 100
    return _clamp(number)


def _status_score(status: Any) -> float:
    status_text = _text(status, "").lower()
    if any(word in status_text for word in ("critical", "fatal", "halt", "emergency", "failed", "error", "alert")):
        return 18.0
    if any(word in status_text for word in ("stale", "late", "degraded", "warn", "breach")):
        return 48.0
    if any(word in status_text for word in ("pending", "watch", "review")):
        return 65.0
    if any(word in status_text for word in ("ok", "healthy", "pass", "fresh", "resolved", "success", "normal")):
        return 100.0
    return 50.0


def _row_percent(row: dict[str, Any], keys: tuple[str, ...] = ("percent", "pct", "score", "value", "coverage", "confidence")) -> float:
    for key in keys:
        if key in row and row.get(key) not in (None, ""):
            return _percent_value(row.get(key))
    return _status_score(row.get("status", row.get("health", row.get("severity", ""))))


def _chart_figure(caption: str, svg: str, wide: bool = False, small: bool = False) -> str:
    classes = ["chart-figure"]
    if wide:
        classes.append("chart-wide")
    if small:
        classes.append("chart-small")
    return f"""
    <figure class="{' '.join(classes)}">
      {svg}
      <figcaption>{_html(caption)}</figcaption>
    </figure>
    """


def _chart_grid(figures: list[str]) -> str:
    if not figures:
        return '<div class="empty">No chart data</div>'
    return f'<div class="chart-grid">{"".join(figures)}</div>'


def _donut_chart(caption: str, segments: list[dict[str, Any]], center_label: str = "total", chart_id: str = "donut") -> str:
    colors = ["#22c55e", "#f59e0b", "#ef4444", "#4a6cf7", "#a78bfa"]
    values = [_number(segment.get("value")) for segment in segments]
    total = sum(value for value in values if value > 0)
    size = 180
    radius = 58
    circumference = 2 * math.pi * radius
    circles = []
    offset = 0.0
    for idx, segment in enumerate(segments):
        value = max(0.0, _number(segment.get("value")))
        length = 0.0 if total <= 0 else circumference * value / total
        color = segment.get("color") or colors[idx % len(colors)]
        circles.append(
            f'<circle cx="90" cy="90" r="{radius}" fill="none" stroke="{_html(color)}" stroke-width="20" '
            f'stroke-dasharray="{length:.2f} {circumference - length:.2f}" stroke-dashoffset="{-offset:.2f}" '
            'stroke-linecap="round" transform="rotate(-90 90 90)" />'
        )
        offset += length
    legend_items = []
    for idx, segment in enumerate(segments[:4]):
        label = _html(segment.get("label", f"S{idx + 1}"))
        value = max(0.0, _number(segment.get("value")))
        pct = 0.0 if total <= 0 else value * 100 / total
        color = segment.get("color") or colors[idx % len(colors)]
        legend_items.append(
            f'<g transform="translate(12 {18 + idx * 16})"><rect width="8" height="8" rx="2" fill="{_html(color)}"/>'
            f'<text x="14" y="8" fill="#dce1f7" font-size="10">{label} {pct:.0f}%</text></g>'
        )
    center_value = "--" if total <= 0 else f"{total:.0f}"
    svg = f"""
    <svg role="img" aria-label="{_html(caption)}" viewBox="0 0 180 180" width="180" height="180" xmlns="http://www.w3.org/2000/svg">
      <defs>
        <radialGradient id="{_html(chart_id)}-core" cx="50%" cy="50%" r="50%">
          <stop offset="0%" stop-color="#293056"/>
          <stop offset="100%" stop-color="#1a1a2e"/>
        </radialGradient>
      </defs>
      <rect width="180" height="180" rx="12" fill="#1a1a2e"/>
      <circle cx="90" cy="90" r="{radius}" fill="none" stroke="#34395f" stroke-width="20"/>
      {''.join(circles)}
      <circle cx="90" cy="90" r="40" fill="url(#{_html(chart_id)}-core)"/>
      <text x="90" y="86" fill="#ffffff" font-size="22" font-weight="700" text-anchor="middle">{_html(center_value)}</text>
      <text x="90" y="104" fill="#aeb4d4" font-size="10" text-anchor="middle">{_html(center_label)}</text>
      {''.join(legend_items)}
    </svg>
    """
    return _chart_figure(caption, svg, small=True)


def _progress_bars_chart(caption: str, rows: list[dict[str, Any]], label_key: str = "label", value_keys: tuple[str, ...] = ("percent", "score", "value")) -> str:
    visible = rows[:6]
    if not visible:
        return _chart_figure(caption, '<svg viewBox="0 0 600 80" width="600" height="80" xmlns="http://www.w3.org/2000/svg"><rect width="600" height="80" rx="12" fill="#1a1a2e"/><text x="300" y="44" fill="#aeb4d4" text-anchor="middle" font-size="13">No data</text></svg>', wide=True)
    height = min(200, 34 + len(visible) * 26)
    bars = []
    for idx, row in enumerate(visible):
        y = 26 + idx * 26
        pct = _row_percent(row, value_keys)
        color = row.get("color") or ("#22c55e" if pct >= 80 else "#f59e0b" if pct >= 50 else "#ef4444")
        label = _html(row.get(label_key) or row.get("name") or row.get("source") or row.get("domain") or f"Item {idx + 1}")
        bars.append(
            f'<text x="16" y="{y + 9}" fill="#dce1f7" font-size="11">{label}</text>'
            f'<rect x="155" y="{y}" width="360" height="12" rx="6" fill="#303554"/>'
            f'<rect x="155" y="{y}" width="{360 * pct / 100:.1f}" height="12" rx="6" fill="{_html(color)}"/>'
            f'<text x="530" y="{y + 10}" fill="#c8cce0" font-size="11">{pct:.0f}%</text>'
        )
    svg = f"""
    <svg role="img" aria-label="{_html(caption)}" viewBox="0 0 600 {height}" width="600" height="{height}" xmlns="http://www.w3.org/2000/svg">
      <defs>
        <linearGradient id="bar-grad" x1="0" x2="1">
          <stop offset="0%" stop-color="#4a6cf7"/>
          <stop offset="100%" stop-color="#22c55e"/>
        </linearGradient>
      </defs>
      <rect width="600" height="{height}" rx="12" fill="#1a1a2e"/>
      {''.join(bars)}
    </svg>
    """
    return _chart_figure(caption, svg, wide=True)


def _grouped_bar_chart(caption: str, rows: list[dict[str, Any]], label_key: str, expected_key: str = "expected", actual_key: str = "actual") -> str:
    visible = rows[:6]
    values = [_number(row.get(expected_key)) for row in visible] + [_number(row.get(actual_key)) for row in visible]
    max_value = max(values + [1.0])
    height = min(200, 36 + len(visible) * 25)
    items = []
    for idx, row in enumerate(visible):
        y = 28 + idx * 25
        expected = max(0.0, _number(row.get(expected_key)))
        actual = max(0.0, _number(row.get(actual_key)))
        expected_w = 180 * expected / max_value
        actual_w = 180 * actual / max_value
        actual_color = "#ef4444" if actual > expected else "#22c55e"
        label = _html(row.get(label_key) or row.get("source") or row.get("name") or f"Item {idx + 1}")
        items.append(
            f'<text x="16" y="{y + 11}" fill="#dce1f7" font-size="10">{label}</text>'
            f'<rect x="150" y="{y}" width="{expected_w:.1f}" height="8" rx="4" fill="#4a6cf7"/>'
            f'<rect x="150" y="{y + 11}" width="{actual_w:.1f}" height="8" rx="4" fill="{actual_color}"/>'
            f'<text x="344" y="{y + 8}" fill="#aeb4d4" font-size="9">exp {expected:g}</text>'
            f'<text x="344" y="{y + 19}" fill="#aeb4d4" font-size="9">act {actual:g}</text>'
        )
    svg = f"""
    <svg role="img" aria-label="{_html(caption)}" viewBox="0 0 600 {height}" width="600" height="{height}" xmlns="http://www.w3.org/2000/svg">
      <rect width="600" height="{height}" rx="12" fill="#1a1a2e"/>
      <text x="16" y="17" fill="#c8cce0" font-size="11">Expected vs actual age</text>
      <circle cx="430" cy="13" r="4" fill="#4a6cf7"/><text x="440" y="17" fill="#c8cce0" font-size="10">expected</text>
      <circle cx="506" cy="13" r="4" fill="#ef4444"/><text x="516" y="17" fill="#c8cce0" font-size="10">actual</text>
      {''.join(items)}
    </svg>
    """
    return _chart_figure(caption, svg, wide=True)


def _sparkline_chart(caption: str, rows: list[dict[str, Any]], label_key: str = "source") -> str:
    visible = rows[:5]
    height = min(200, 28 + len(visible) * 32)
    items = []
    for idx, row in enumerate(visible):
        raw_trend = row.get("trend") or row.get("history") or row.get("ages") or row.get("age_history")
        if not isinstance(raw_trend, (list, tuple)) or not raw_trend:
            raw_trend = [row.get("expected", row.get("threshold", 0)), row.get("actual", row.get("age", row.get("age_minutes", 0)))]
        trend = [_number(point) for point in raw_trend][:12]
        if len(trend) == 1:
            trend = [trend[0], trend[0]]
        max_value = max(trend + [1.0])
        min_value = min(trend + [0.0])
        span = max(max_value - min_value, 1.0)
        x0 = 150
        width = 390
        y0 = 26 + idx * 32
        points = []
        for point_idx, value in enumerate(trend):
            x = x0 + (width * point_idx / max(1, len(trend) - 1))
            y = y0 + 20 - ((value - min_value) / span * 20)
            points.append(f"{x:.1f},{y:.1f}")
        label = _html(row.get(label_key) or row.get("name") or f"Item {idx + 1}")
        items.append(
            f'<text x="16" y="{y0 + 15}" fill="#dce1f7" font-size="10">{label}</text>'
            f'<polyline points="{" ".join(points)}" fill="none" stroke="#4a6cf7" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/>'
            f'<circle cx="{points[-1].split(",")[0]}" cy="{points[-1].split(",")[1]}" r="3" fill="#f59e0b"/>'
            f'<text x="550" y="{y0 + 15}" fill="#c8cce0" font-size="10">{trend[-1]:g}</text>'
        )
    svg = f"""
    <svg role="img" aria-label="{_html(caption)}" viewBox="0 0 600 {height}" width="600" height="{height}" xmlns="http://www.w3.org/2000/svg">
      <rect width="600" height="{height}" rx="12" fill="#1a1a2e"/>
      <text x="16" y="17" fill="#c8cce0" font-size="11">Staleness trend</text>
      {''.join(items)}
    </svg>
    """
    return _chart_figure(caption, svg, wide=True)


def _horizontal_bar_chart(caption: str, rows: list[dict[str, Any]], label_key: str = "label", value_key: str = "count", color: str = "#4a6cf7") -> str:
    visible = rows[:6]
    max_value = max([_number(row.get(value_key, row.get("value"))) for row in visible] + [1.0])
    height = min(200, 30 + len(visible) * 25)
    items = []
    for idx, row in enumerate(visible):
        value = max(0.0, _number(row.get(value_key, row.get("value"))))
        y = 24 + idx * 25
        label = _html(row.get(label_key) or row.get("api") or row.get("event_type") or row.get("category") or row.get("name") or f"Item {idx + 1}")
        items.append(
            f'<text x="16" y="{y + 10}" fill="#dce1f7" font-size="10">{label}</text>'
            f'<rect x="150" y="{y}" width="360" height="12" rx="6" fill="#303554"/>'
            f'<rect x="150" y="{y}" width="{360 * value / max_value:.1f}" height="12" rx="6" fill="{_html(row.get("color") or color)}"/>'
            f'<text x="524" y="{y + 10}" fill="#c8cce0" font-size="10">{value:g}</text>'
        )
    svg = f"""
    <svg role="img" aria-label="{_html(caption)}" viewBox="0 0 600 {height}" width="600" height="{height}" xmlns="http://www.w3.org/2000/svg">
      <rect width="600" height="{height}" rx="12" fill="#1a1a2e"/>
      {''.join(items)}
    </svg>
    """
    return _chart_figure(caption, svg, wide=True)


def _severity_indicator_chart(caption: str, severity: Any, label: Any = "") -> str:
    severity_text = _text(severity, "critical")
    color = "#ef4444" if _status_class(severity_text) == "critical" else "#f59e0b" if _status_class(severity_text) == "negative" else "#22c55e"
    svg = f"""
    <svg role="img" aria-label="{_html(caption)}" viewBox="0 0 180 180" width="180" height="180" xmlns="http://www.w3.org/2000/svg">
      <defs>
        <radialGradient id="severity-core" cx="50%" cy="50%" r="50%">
          <stop offset="0%" stop-color="{_html(color)}" stop-opacity="0.9"/>
          <stop offset="100%" stop-color="#1a1a2e" stop-opacity="0.2"/>
        </radialGradient>
      </defs>
      <rect width="180" height="180" rx="12" fill="#1a1a2e"/>
      <circle class="pulse-ring" cx="90" cy="82" r="58" fill="none" stroke="{_html(color)}" stroke-width="12"/>
      <circle cx="90" cy="82" r="42" fill="url(#severity-core)" stroke="{_html(color)}" stroke-width="3"/>
      <text x="90" y="78" fill="#ffffff" font-size="15" font-weight="700" text-anchor="middle">{_html(severity_text).upper()}</text>
      <text x="90" y="100" fill="#dce1f7" font-size="10" text-anchor="middle">{_html(label)}</text>
      <text x="90" y="148" fill="#aeb4d4" font-size="10" text-anchor="middle">human review gate</text>
    </svg>
    """
    return _chart_figure(caption, svg, small=True)


def _timeline_bars_chart(caption: str, rows: list[dict[str, Any]], label_key: str = "time") -> str:
    visible = rows[:6]
    height = min(200, 34 + len(visible) * 25)
    items = []
    for idx, row in enumerate(visible):
        y = 26 + idx * 25
        duration = max(1.0, _number(row.get("duration", row.get("count", row.get("value", 1)))))
        width = _clamp(duration * 18, 18, 360)
        status = row.get("severity", row.get("status", "watch"))
        color = "#ef4444" if _status_class(status) == "critical" else "#f59e0b" if _status_class(status) == "negative" else "#4a6cf7"
        label = _html(row.get(label_key) or row.get("detected_at") or row.get("event") or f"T{idx + 1}")
        items.append(
            f'<text x="16" y="{y + 10}" fill="#dce1f7" font-size="10">{label}</text>'
            f'<rect x="150" y="{y}" width="{width:.1f}" height="12" rx="6" fill="{color}"/>'
            f'<text x="{160 + width:.1f}" y="{y + 10}" fill="#c8cce0" font-size="10">{_html(status)}</text>'
        )
    svg = f"""
    <svg role="img" aria-label="{_html(caption)}" viewBox="0 0 600 {height}" width="600" height="{height}" xmlns="http://www.w3.org/2000/svg">
      <rect width="600" height="{height}" rx="12" fill="#1a1a2e"/>
      <text x="16" y="17" fill="#c8cce0" font-size="11">Alert history</text>
      {''.join(items)}
    </svg>
    """
    return _chart_figure(caption, svg, wide=True)


def _stacked_bar_chart(caption: str, segments: list[dict[str, Any]]) -> str:
    total = sum(max(0.0, _number(segment.get("value"))) for segment in segments)
    x = 42.0
    parts = []
    for segment in segments:
        value = max(0.0, _number(segment.get("value")))
        width = 0.0 if total <= 0 else 500 * value / total
        color = segment.get("color", "#4a6cf7")
        label = _html(segment.get("label", "segment"))
        parts.append(
            f'<rect x="{x:.1f}" y="70" width="{width:.1f}" height="40" rx="6" fill="{_html(color)}"/>'
            f'<text x="{x + max(width / 2, 12):.1f}" y="94" fill="#fff" font-size="11" text-anchor="middle">{label} {value:g}</text>'
        )
        x += width
    svg = f"""
    <svg role="img" aria-label="{_html(caption)}" viewBox="0 0 600 160" width="600" height="160" xmlns="http://www.w3.org/2000/svg">
      <defs>
        <linearGradient id="stack-bg" x1="0" x2="1"><stop offset="0%" stop-color="#293056"/><stop offset="100%" stop-color="#1a1a2e"/></linearGradient>
      </defs>
      <rect width="600" height="160" rx="12" fill="#1a1a2e"/>
      <rect x="42" y="70" width="500" height="40" rx="6" fill="url(#stack-bg)"/>
      {''.join(parts)}
      <text x="42" y="45" fill="#dce1f7" font-size="13">Total {total:g}</text>
    </svg>
    """
    return _chart_figure(caption, svg, wide=True)


def _regime_point(regime: Any, growth: Any = None, inflation: Any = None) -> tuple[float, float]:
    text = _text(regime, "").lower()
    growth_text = _text(growth, "").lower() or text
    inflation_text = _text(inflation, "").lower() or text
    growth_up = "growth_up" in text or "growth up" in growth_text or growth_text in {"up", "higher", "rise", "rising"}
    growth_down = "growth_down" in text or "growth down" in growth_text or growth_text in {"down", "lower", "fall", "falling"}
    inflation_up = "infl_up" in text or "inflation_up" in text or "inflation up" in inflation_text or inflation_text in {"up", "higher", "rise", "rising"}
    inflation_down = "infl_down" in text or "inflation_down" in text or "inflation down" in inflation_text or inflation_text in {"down", "lower", "fall", "falling"}
    x = 135.0 if inflation_up else 45.0 if inflation_down else 90.0
    y = 45.0 if growth_up else 135.0 if growth_down else 90.0
    return x, y


def _compass_regime_chart(caption: str, previous_regime: Any, new_regime: Any, growth: Any = None, inflation: Any = None) -> str:
    start_x, start_y = _regime_point(previous_regime)
    end_x, end_y = _regime_point(new_regime, growth, inflation)
    svg = f"""
    <svg role="img" aria-label="{_html(caption)}" viewBox="0 0 180 180" width="180" height="180" xmlns="http://www.w3.org/2000/svg">
      <defs>
        <marker id="regime-arrow" markerWidth="8" markerHeight="8" refX="6" refY="3" orient="auto"><path d="M0,0 L0,6 L7,3 z" fill="#f59e0b"/></marker>
      </defs>
      <rect width="180" height="180" rx="12" fill="#1a1a2e"/>
      <line x1="90" y1="20" x2="90" y2="160" stroke="#41476f" stroke-width="1"/>
      <line x1="20" y1="90" x2="160" y2="90" stroke="#41476f" stroke-width="1"/>
      <text x="90" y="18" fill="#dce1f7" font-size="10" text-anchor="middle">Growth up</text>
      <text x="90" y="172" fill="#dce1f7" font-size="10" text-anchor="middle">Growth down</text>
      <text x="20" y="84" fill="#dce1f7" font-size="9">Infl down</text>
      <text x="126" y="84" fill="#dce1f7" font-size="9">Infl up</text>
      <rect x="24" y="24" width="56" height="56" rx="8" fill="#22365d" opacity="0.75"/>
      <rect x="100" y="24" width="56" height="56" rx="8" fill="#4c2d51" opacity="0.75"/>
      <rect x="24" y="100" width="56" height="56" rx="8" fill="#294b45" opacity="0.75"/>
      <rect x="100" y="100" width="56" height="56" rx="8" fill="#5c342d" opacity="0.75"/>
      <circle cx="{start_x:.1f}" cy="{start_y:.1f}" r="5" fill="#aeb4d4"/>
      <line x1="{start_x:.1f}" y1="{start_y:.1f}" x2="{end_x:.1f}" y2="{end_y:.1f}" stroke="#f59e0b" stroke-width="4" marker-end="url(#regime-arrow)"/>
      <circle cx="{end_x:.1f}" cy="{end_y:.1f}" r="7" fill="#f59e0b" stroke="#fff" stroke-width="2"/>
    </svg>
    """
    return _chart_figure(caption, svg, small=True)


def _radial_relationship_chart(caption: str, center_label: Any, rows: list[dict[str, Any]], label_key: str = "target") -> str:
    visible = rows[:8]
    node_bits = []
    edge_bits = []
    center_x = 100.0
    center_y = 100.0
    radius = 70.0
    for idx, row in enumerate(visible):
        angle = (2 * math.pi * idx / max(1, len(visible))) - math.pi / 2
        x = center_x + math.cos(angle) * radius
        y = center_y + math.sin(angle) * radius
        pct = _row_percent(row, ("confidence", "score", "weight", "value"))
        color = "#22c55e" if pct >= 75 else "#f59e0b" if pct >= 45 else "#ef4444"
        label = _html(row.get(label_key) or row.get("name") or f"T{idx + 1}")
        short_label = label[:12]
        edge_bits.append(f'<line x1="{center_x}" y1="{center_y}" x2="{x:.1f}" y2="{y:.1f}" stroke="{color}" stroke-width="{1.2 + pct / 35:.1f}" opacity="0.72"/>')
        node_bits.append(
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{5 + pct / 25:.1f}" fill="{color}" stroke="#fff" stroke-width="1"/>'
            f'<text x="{x:.1f}" y="{y + 18:.1f}" fill="#dce1f7" font-size="8" text-anchor="middle">{short_label}</text>'
        )
    svg = f"""
    <svg role="img" aria-label="{_html(caption)}" viewBox="0 0 200 200" width="200" height="200" xmlns="http://www.w3.org/2000/svg">
      <defs>
        <radialGradient id="radial-center" cx="50%" cy="50%" r="50%"><stop offset="0%" stop-color="#4a6cf7"/><stop offset="100%" stop-color="#1a1a2e"/></radialGradient>
      </defs>
      <rect width="200" height="200" rx="12" fill="#1a1a2e"/>
      {''.join(edge_bits)}
      <circle cx="{center_x}" cy="{center_y}" r="28" fill="url(#radial-center)" stroke="#dce1f7" stroke-width="1.5"/>
      <text x="{center_x}" y="{center_y - 2}" fill="#fff" font-size="10" font-weight="700" text-anchor="middle">Trigger</text>
      <text x="{center_x}" y="{center_y + 12}" fill="#dce1f7" font-size="8" text-anchor="middle">{_html(center_label)[:14]}</text>
      {''.join(node_bits)}
    </svg>
    """
    return _chart_figure(caption, svg, small=True)


def _radar_chart(caption: str, rows: list[dict[str, Any]], label_key: str = "domain", value_key: str = "coverage") -> str:
    visible = rows[:6]
    if len(visible) < 3:
        visible = visible + [{"domain": f"D{idx + 1}", "coverage": 0} for idx in range(3 - len(visible))]
    center = 90.0
    max_radius = 58.0
    rings = []
    for step in (0.33, 0.66, 1.0):
        points = []
        for idx in range(len(visible)):
            angle = (2 * math.pi * idx / len(visible)) - math.pi / 2
            points.append(f"{center + math.cos(angle) * max_radius * step:.1f},{center + math.sin(angle) * max_radius * step:.1f}")
        rings.append(f'<polygon points="{" ".join(points)}" fill="none" stroke="#3a416a" stroke-width="1"/>')
    value_points = []
    labels = []
    for idx, row in enumerate(visible):
        angle = (2 * math.pi * idx / len(visible)) - math.pi / 2
        pct = _row_percent(row, (value_key, "score", "coverage", "value")) / 100
        value_points.append(f"{center + math.cos(angle) * max_radius * pct:.1f},{center + math.sin(angle) * max_radius * pct:.1f}")
        lx = center + math.cos(angle) * (max_radius + 18)
        ly = center + math.sin(angle) * (max_radius + 18)
        labels.append(f'<text x="{lx:.1f}" y="{ly:.1f}" fill="#dce1f7" font-size="8" text-anchor="middle">{_html(row.get(label_key) or row.get("name"))[:11]}</text>')
    svg = f"""
    <svg role="img" aria-label="{_html(caption)}" viewBox="0 0 180 180" width="180" height="180" xmlns="http://www.w3.org/2000/svg">
      <defs>
        <linearGradient id="radar-fill" x1="0" x2="1"><stop offset="0%" stop-color="#4a6cf7" stop-opacity="0.72"/><stop offset="100%" stop-color="#22c55e" stop-opacity="0.48"/></linearGradient>
      </defs>
      <rect width="180" height="180" rx="12" fill="#1a1a2e"/>
      {''.join(rings)}
      <polygon points="{' '.join(value_points)}" fill="url(#radar-fill)" stroke="#75e0a7" stroke-width="2"/>
      {''.join(labels)}
    </svg>
    """
    return _chart_figure(caption, svg, small=True)


def _metric(label: str, value: Any, detail: Any = "", status: Any | None = None) -> str:
    rendered_value = _badge(value, status) if status is not None else _html(value)
    detail_html = f'<div class="detail">{_html(detail)}</div>' if detail else ""
    return f"""
    <div class="summary-box">
      <div class="label">{_html(label)}</div>
      <div class="value">{rendered_value}</div>
      {detail_html}
    </div>
    """


def _summary(metrics: list[dict[str, Any]]) -> str:
    cells: list[str] = []
    for metric in metrics:
        cells.append(_metric(metric.get("label", ""), metric.get("value", ""), metric.get("detail", ""), metric.get("status")))
    rows = ""
    for idx in range(0, len(cells), 2):
        right = cells[idx + 1] if idx + 1 < len(cells) else '<div class="summary-box"></div>'
        rows += f'<div class="summary-row">{cells[idx]}<div class="summary-gap"></div>{right}</div>'
    return f'<div class="summary-grid">{rows}</div>'


def _table(headers: list[str], rows: list[list[Any]]) -> str:
    if not rows:
        return '<div class="empty">No data</div>'
    header_html = "".join(f"<th>{_html(header)}</th>" for header in headers)
    rows_html = ""
    for row in rows:
        rows_html += "<tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>"
    return f"""
    <table>
      <thead><tr>{header_html}</tr></thead>
      <tbody>{rows_html}</tbody>
    </table>
    """


def _section(title: str, content: str) -> str:
    return f"""
    <div class="section">
      <div class="section-title">{_html(title)}</div>
      {content}
    </div>
    """


def _header(title: str, subtitle: str) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    return f"""
    <div class="header">
      <h1>{_html(title)}</h1>
      <div class="meta">{_html(subtitle)} | {now}</div>
    </div>
    """


def _footer(system_name: str) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    return f"""
    <div class="footer">
      Auto-generated at {now}. System: {_html(system_name)}. Channel: system alerts to soc@coze.email.<br>
      Data-only operational notice. No trading instruction is implied.
    </div>
    """


def wrap_html(title: str, subtitle: str, system_name: str, body_content: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  {_css()}
</head>
<body>
  <div class="container">
    {_header(title, subtitle)}
    <div class="body">
      {body_content}
    </div>
    {_footer(system_name)}
  </div>
</body>
</html>
"""


def get_channel(template_name: str) -> dict[str, str]:
    channel_key = TEMPLATE_CHANNELS.get(template_name, "system")
    return CHANNELS[channel_key]

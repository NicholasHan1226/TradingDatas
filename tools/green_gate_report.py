#!/usr/bin/env python3
"""Send the SharedSignals operator Green Gate report.

The report is intentionally sourced from the same governance checks that power
``/source_status`` so daily email, API status, and operator handoff stay aligned.
"""
from __future__ import annotations

import argparse
import html
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(os.environ.get("SHAREDSIGNALS_ROOT", Path(__file__).resolve().parents[1]))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import patrol
from tools import source_governance_monitor

DEFAULT_TO = os.getenv("SHAREDSIGNALS_GREEN_GATE_TO") or os.getenv("EMAIL_TO_SYSTEM") or os.getenv("EMAIL_SYSTEM_TO") or "soc@coze.email"
DEFAULT_OUTPUT_PATH = Path("logs/watchdog_inputs/green_gate_report.json")
DEFAULT_BODY_OUTPUT_PATH = Path("logs/watchdog_inputs/green_gate_report.html")

STATUS_RANK = {"green": 0, "yellow": 1, "red": 2}


def _utc_date() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _normalize_check_status(status: str) -> str:
    if status in {"green", "ok"}:
        return "green"
    if status in {"yellow", "warn", "warning", "degrade", "stale"}:
        return "yellow"
    return "red"


def _worst_status(statuses: list[str]) -> str:
    worst = "green"
    for status in statuses:
        normalized = _normalize_check_status(status)
        if STATUS_RANK[normalized] > STATUS_RANK[worst]:
            worst = normalized
    return worst


def _green_gate_checks(governance_report: dict[str, Any], artifact_guard: dict[str, Any]) -> list[dict[str, Any]]:
    checks = [
        check
        for check in governance_report.get("checks", [])
        if isinstance(check, dict)
    ]
    artifact_status = _normalize_check_status(str(artifact_guard.get("status") or "red"))
    checks.append(
        {
            "name": "data_artifact_guard",
            "status": artifact_status,
            "message": "no retired CSV/NDJSON/Parquet/DB artifacts found"
            if artifact_status == "green"
            else "retired file artifacts require cleanup",
            "evidence": {
                "value": artifact_guard.get("value"),
                "threshold": artifact_guard.get("threshold"),
                "offenders": artifact_guard.get("offenders", []),
                "truncated": artifact_guard.get("truncated", False),
            },
        }
    )
    return checks


def _render_html(payload: dict[str, Any]) -> str:
    report = payload["source_governance"]
    summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
    checks = payload["checks"]
    non_green = [check for check in checks if check.get("status") != "green"]
    status = payload["status"]
    status_label = status.upper()

    if status == "green":
        conclusion = "SharedSignals Green Gate OK: source/API/frequency/module/storage guards are aligned."
        risk = "No direct blocker for API consumers."
        next_step = "Keep the current cadence; expand only through planned source onboarding."
    elif status == "yellow":
        conclusion = "SharedSignals Green Gate needs review: consumers may read existing API, but do not expand cadence or new sources first."
        risk = "There are degraded checks that should be cleared before expansion."
        next_step = "Review yellow items, then rerun the Green Gate report."
    else:
        conclusion = "SharedSignals Green Gate is blocked: downstream trading/research gates should treat this as fail-closed."
        risk = "At least one required source/API/frequency/module/storage guard is red."
        next_step = "Fix red items first; do not add consumers or source cron until green."

    rows = []
    for check in non_green[:12]:
        rows.append(
            "<tr>"
            f"<td>{html.escape(str(check.get('name', 'unknown')))}</td>"
            f"<td>{html.escape(str(check.get('status', 'red')))}</td>"
            f"<td>{html.escape(str(check.get('message', '')))}</td>"
            "</tr>"
        )
    non_green_table = ""
    if rows:
        non_green_table = (
            "<h3>Items to Review</h3>"
            "<table border=\"1\" cellpadding=\"6\" cellspacing=\"0\">"
            "<tr><th>Check</th><th>Status</th><th>Message</th></tr>"
            + "".join(rows)
            + "</table>"
        )

    artifact = payload.get("data_artifact_guard", {})
    artifact_value = artifact.get("value")
    body = f"""<html><body style="font-family:Arial,Helvetica,sans-serif;max-width:760px;line-height:1.45">
<h2>SharedSignals Green Gate: {html.escape(status_label)}</h2>
<p><strong>Conclusion:</strong> {html.escape(conclusion)}</p>
<ul>
  <li>Generated at: {html.escape(str(payload.get("generated_at", "")))}</li>
  <li>External API endpoints: {html.escape(str(summary.get("endpoint_count", 0)))}</li>
  <li>Tushare active: {html.escape(str(summary.get("tushare_active", 0)))}/{html.escape(str(summary.get("tushare_allowlisted", 0)))}</li>
  <li>Tushare planned backlog: {html.escape(str(summary.get("tushare_planned_backlog", 0)))}</li>
  <li>Governance checks: green {html.escape(str(summary.get("green_checks", 0)))}, yellow {html.escape(str(summary.get("yellow_checks", 0)))}, red {html.escape(str(summary.get("red_checks", 0)))}</li>
  <li>Retired file artifact guard: {html.escape(str(artifact.get("status", "unknown")))} ({html.escape(str(artifact_value))} offenders)</li>
</ul>
<p><strong>Risk:</strong> {html.escape(risk)}</p>
<p><strong>Next step:</strong> {html.escape(next_step)}</p>
{non_green_table}
<p style="color:#666;font-size:12px">This report uses the same source governance logic as GET /source_status and adds the retired file-artifact guard. SharedSignals remains a data/API layer only.</p>
</body></html>"""
    return body


def build_green_gate_payload() -> dict[str, Any]:
    governance_report = source_governance_monitor.build_source_governance_report()
    artifact_guard = patrol.check_data_artifact_guard()
    checks = _green_gate_checks(governance_report, artifact_guard)
    status = _worst_status([str(governance_report.get("status") or "red")] + [str(check.get("status")) for check in checks])
    generated_at = datetime.now(timezone.utc).isoformat()
    return {
        "status": status,
        "generated_at": generated_at,
        "source_governance": governance_report,
        "data_artifact_guard": artifact_guard,
        "checks": checks,
        "subject": f"[SharedSignals][{status.upper()}] Green Gate {'OK' if status == 'green' else 'Review'} - {_utc_date()}",
    }


def send_green_gate_report(*, to: str = DEFAULT_TO, dry_run: bool = False) -> dict[str, Any]:
    payload = build_green_gate_payload()
    body = _render_html(payload)
    payload["body_html"] = body
    if dry_run:
        payload["delivery"] = {"status": "dry_run", "to": to}
        return payload

    delivery = _send_email(
        to=to,
        subject=payload["subject"],
        html_body=body,
        channel="system",
    )
    payload["delivery"] = delivery
    return payload


def _send_email(*, to: str, subject: str, html_body: str, channel: str) -> dict[str, Any]:
    from tools import email_sender  # noqa: WPS433

    return email_sender.send_email(to=to, subject=subject, html_body=html_body, channel=channel)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    serializable = dict(payload)
    serializable.pop("body_html", None)
    path.write_text(json.dumps(serializable, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Send SharedSignals Green Gate operator report")
    parser.add_argument("--to", default=DEFAULT_TO, help="Recipient email address")
    parser.add_argument("--dry-run", action="store_true", help="Build report without sending email")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH, help="JSON report output path")
    parser.add_argument("--body-output", type=Path, default=DEFAULT_BODY_OUTPUT_PATH, help="HTML body output path")
    parser.add_argument("--json", action="store_true", help="Print JSON payload to stdout")
    args = parser.parse_args()

    payload = send_green_gate_report(to=args.to, dry_run=args.dry_run)
    _write_json(args.output, payload)
    args.body_output.parent.mkdir(parents=True, exist_ok=True)
    args.body_output.write_text(payload["body_html"], encoding="utf-8")

    printable = dict(payload)
    printable.pop("body_html", None)
    if args.json or args.dry_run:
        print(json.dumps(printable, ensure_ascii=False, indent=2, sort_keys=True))

    delivery_status = str((payload.get("delivery") or {}).get("status") or "")
    if payload["status"] == "red":
        return 2
    if not args.dry_run and delivery_status not in {"sent", "saved_local"}:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

from tools import green_gate_report


def _governance_report(status: str = "green") -> dict:
    return {
        "status": status,
        "generated_at": "2026-07-09T00:10:00+00:00",
        "summary": {
            "endpoint_count": 23,
            "tushare_allowlisted": 115,
            "tushare_active": 115,
            "tushare_planned_backlog": 0,
            "green_checks": 7,
            "yellow_checks": 0,
            "red_checks": 0,
        },
        "checks": [
            {
                "name": "api_endpoint_surface",
                "status": status,
                "message": "all required external-agent endpoints are listed",
            }
        ],
    }


def test_green_gate_payload_uses_source_governance_and_artifact_guard(monkeypatch) -> None:
    monkeypatch.setattr(
        green_gate_report.source_governance_monitor,
        "build_source_governance_report",
        lambda: _governance_report(),
    )
    monkeypatch.setattr(
        green_gate_report.patrol,
        "check_data_artifact_guard",
        lambda: {"status": "ok", "value": 0, "threshold": 0, "offenders": []},
    )

    payload = green_gate_report.send_green_gate_report(to="soc@coze.email", dry_run=True)

    assert payload["status"] == "green"
    assert payload["delivery"]["status"] == "dry_run"
    assert "[SharedSignals][GREEN]" in payload["subject"]
    assert "External API endpoints: 23" in payload["body_html"]
    assert "Retired file artifact guard: ok (0 offenders)" in payload["body_html"]


def test_green_gate_report_sends_to_system_channel(monkeypatch) -> None:
    sent: dict = {}

    monkeypatch.setattr(
        green_gate_report.source_governance_monitor,
        "build_source_governance_report",
        lambda: _governance_report(),
    )
    monkeypatch.setattr(
        green_gate_report.patrol,
        "check_data_artifact_guard",
        lambda: {"status": "ok", "value": 0, "threshold": 0, "offenders": []},
    )

    def fake_send_email(*, to: str, subject: str, html_body: str, channel: str) -> dict:
        sent.update({"to": to, "subject": subject, "html_body": html_body, "channel": channel})
        return {"status": "sent", "provider": "test", "to": to}

    monkeypatch.setattr(green_gate_report, "_send_email", fake_send_email)

    payload = green_gate_report.send_green_gate_report(to="soc@coze.email", dry_run=False)

    assert payload["delivery"]["status"] == "sent"
    assert sent["to"] == "soc@coze.email"
    assert sent["channel"] == "system"
    assert sent["subject"] == payload["subject"]


def test_green_gate_report_turns_artifact_guard_into_red(monkeypatch) -> None:
    monkeypatch.setattr(
        green_gate_report.source_governance_monitor,
        "build_source_governance_report",
        lambda: _governance_report(),
    )
    monkeypatch.setattr(
        green_gate_report.patrol,
        "check_data_artifact_guard",
        lambda: {"status": "alert", "value": 1, "threshold": 0, "offenders": ["/tmp/old.csv"]},
    )

    payload = green_gate_report.send_green_gate_report(to="soc@coze.email", dry_run=True)

    assert payload["status"] == "red"
    assert "[SharedSignals][RED]" in payload["subject"]
    assert "data_artifact_guard" in payload["body_html"]

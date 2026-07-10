from __future__ import annotations

import json

from tools import external_api_probe


def test_unauthenticated_401_proves_public_route_reached_auth_gate() -> None:
    status, message = external_api_probe.evaluate_probe(
        http_status=401,
        token_configured=False,
    )

    assert status == "green"
    assert "authentication gate" in message


def test_cloudflare_525_is_not_treated_as_route_success() -> None:
    status, message = external_api_probe.evaluate_probe(
        http_status=525,
        token_configured=False,
    )

    assert status == "red"
    assert "525" in message


def test_probe_report_is_written_atomically(tmp_path) -> None:
    output_path = tmp_path / "watchdog_inputs" / "external_api_probe.json"
    report = {"status": "green", "http_status": 401}

    external_api_probe.write_report(report, output_path)

    assert json.loads(output_path.read_text(encoding="utf-8")) == report
    assert not list(output_path.parent.glob("*.tmp"))

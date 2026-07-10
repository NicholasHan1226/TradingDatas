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


def test_ssh_probe_uses_remote_vantage(monkeypatch) -> None:
    calls = []

    class _Completed:
        returncode = 0
        stdout = "401"
        stderr = ""

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return _Completed()

    monkeypatch.setattr(external_api_probe.subprocess, "run", fake_run)

    report = external_api_probe.run_probe(
        "https://signals.tradingagent.cc/health",
        ssh_target="root@47.82.153.58",
        ssh_key="/root/.ssh/sharedsignals_sg_relay_ed25519",
    )

    assert report["status"] == "green"
    assert report["http_status"] == 401
    assert report["vantage"] == "ssh:root@47.82.153.58"
    assert calls[0][0][-1] == "https://signals.tradingagent.cc/health"

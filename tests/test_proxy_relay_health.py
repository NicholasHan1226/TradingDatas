from __future__ import annotations

from tools import proxy_relay_health


def test_select_relay_url_skips_local_fallback(monkeypatch):
    monkeypatch.delenv("PROXY_RELAY_HEALTH_URL", raising=False)
    monkeypatch.setenv("POLYMARKET_HTTP_PROXIES", "http://127.0.0.1:18889,http://127.0.0.1:7890")

    assert proxy_relay_health._select_relay_url() == "http://127.0.0.1:18889"


def test_explicit_relay_url_wins(monkeypatch):
    monkeypatch.setenv("PROXY_RELAY_HEALTH_URL", "http://proxy.example:18080")
    monkeypatch.setenv("POLYMARKET_HTTP_PROXIES", "http://127.0.0.1:18889,http://127.0.0.1:7890")

    assert proxy_relay_health._select_relay_url() == "http://proxy.example:18080"


def test_check_proxy_relay_marks_expected_ip_mismatch_critical(monkeypatch):
    monkeypatch.setenv("PROXY_RELAY_HEALTH_URL", "http://127.0.0.1:18889")
    monkeypatch.setenv("PROXY_RELAY_EXPECTED_IP", "47.82.153.58")
    monkeypatch.setenv("PROXY_RELAY_CHECK_SYSTEMD", "0")
    monkeypatch.setattr(
        proxy_relay_health,
        "_fetch_egress_ip",
        lambda _proxy_url, _timeout: {"name": "egress_ip", "status": "ok", "egress_ip": "1.2.3.4"},
    )

    result = proxy_relay_health.check_proxy_relay()

    assert result["status"] == "critical"
    assert result["summary"]["critical"] == 1


def test_check_proxy_relay_ok(monkeypatch):
    monkeypatch.setenv("PROXY_RELAY_HEALTH_URL", "http://127.0.0.1:18889")
    monkeypatch.setenv("PROXY_RELAY_EXPECTED_IP", "47.82.153.58")
    monkeypatch.setenv("PROXY_RELAY_CHECK_SYSTEMD", "0")
    monkeypatch.setattr(
        proxy_relay_health,
        "_fetch_egress_ip",
        lambda _proxy_url, _timeout: {"name": "egress_ip", "status": "ok", "egress_ip": "47.82.153.58"},
    )

    result = proxy_relay_health.check_proxy_relay()

    assert result["status"] == "ok"
    assert result["summary"]["critical"] == 0

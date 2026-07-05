from __future__ import annotations

import urllib.error

from tools import watchdog
from tools.watchdog import compute_health_score


def test_health_sla_critical_external_report_reduces_watchdog_score():
    checks = [
        {"name": "api_health", "score_factor": 1.0},
        {"name": "db_freshness", "score_factor": 1.0},
        {"name": "collector_status", "score_factor": 1.0},
        {"name": "disk", "score_factor": 1.0},
        {"name": "memory", "score_factor": 1.0},
    ]

    assert compute_health_score(checks) == 100
    assert compute_health_score(checks, [{"status": "critical"}]) == 85
    assert compute_health_score(checks, [{"status": "degraded"}]) == 95
    assert compute_health_score(checks, [{"status": "critical", "_stale": True}]) == 100


def test_api_health_retries_transient_failure(monkeypatch):
    calls = {"count": 0}

    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, _limit):
            return b'{"status":"ok"}'

    def fake_urlopen(_req, timeout):
        calls["count"] += 1
        if calls["count"] == 1:
            raise urllib.error.URLError("temporary timeout")
        return Response()

    monkeypatch.setenv("WATCHDOG_API_HEALTH_RETRIES", "3")
    monkeypatch.setattr(watchdog.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(watchdog.time, "sleep", lambda _seconds: None)

    result = watchdog.check_api_health("http://127.0.0.1:8082/health")

    assert result["status"] == "ok"
    assert result["attempts"] == 2

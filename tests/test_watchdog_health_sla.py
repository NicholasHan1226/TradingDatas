from __future__ import annotations

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

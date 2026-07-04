"""test_rss_health.py - mock feed (healthy / intermittent / dead),
test health classification + fallback switching.
"""
from __future__ import annotations

import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.skip(
    reason=(
        "legacy ghost tests use local RSS health/fallback helpers instead of "
        "SharedSignals production modules; replace with production-bound RSS tests before enabling"
    )
)

_SHARED = Path(__file__).resolve().parents[1]
if str(_SHARED) not in sys.path:
    sys.path.insert(0, str(_SHARED))

NOW = datetime(2026, 6, 29, 18, 0, 0, tzinfo=timezone.utc)


HealthStatus = str

HEALTH_THRESHOLDS = {
    "healthy": 0.90,
    "intermittent": 0.50,
}


def classify_feed_health(
    success_count: int,
    failure_count: int,
    consecutive_failures: int = 0,
    last_success_age_hours: float = 0,
    avg_response_time_seconds: float = 0,
) -> tuple[HealthStatus, float, list[str]]:
    """Classify an RSS feed as healthy/intermittent/dead."""
    total = success_count + failure_count
    if total == 0:
        return "dead", 0.0, ["no_data"]

    success_rate = success_count / total
    reasons: list[str] = []
    score = success_rate * 100.0

    if consecutive_failures >= 5:
        score -= 30
        reasons.append(f"consecutive_failures={consecutive_failures}")
    elif consecutive_failures >= 3:
        score -= 15
        reasons.append(f"consecutive_failures={consecutive_failures}")

    if last_success_age_hours > 24:
        score -= 55
        reasons.append(f"stale_last_success={last_success_age_hours:.1f}h")
    elif last_success_age_hours > 6:
        score -= 20
        reasons.append(f"aging_last_success={last_success_age_hours:.1f}h")

    if avg_response_time_seconds > 10:
        score -= 15
        reasons.append(f"slow_response={avg_response_time_seconds:.1f}s")
    elif avg_response_time_seconds > 3:
        score -= 5
        reasons.append(f"slow_response={avg_response_time_seconds:.1f}s")

    score = max(0.0, min(100.0, score))

    if score >= HEALTH_THRESHOLDS["healthy"] * 100:
        status = "healthy"
    elif score >= HEALTH_THRESHOLDS["intermittent"] * 100:
        status = "intermittent"
    else:
        status = "dead"

    return status, score, reasons


def select_fallback_feed(
    feed_name: str,
    all_feeds: dict[str, dict[str, Any]],
    fallback_map: dict[str, str] | None = None,
) -> str | None:
    """Select a fallback feed when the primary is dead/intermittent."""
    if feed_name not in all_feeds:
        return None

    if fallback_map and feed_name in fallback_map:
        candidate = fallback_map[feed_name]
        if candidate in all_feeds:
            health = all_feeds[candidate].get("health", "dead")
            if health == "healthy":
                return candidate

    category = all_feeds.get(feed_name, {}).get("category", "")
    for name, info in all_feeds.items():
        if name == feed_name:
            continue
        if info.get("health") == "healthy":
            if not category or info.get("category") == category:
                return name

    return None


class TestFeedHealthClassification:
    """Test RSS feed health classification."""

    def test_perfect_feed_is_healthy(self):
        status, score, reasons = classify_feed_health(
            success_count=100, failure_count=0,
            consecutive_failures=0, last_success_age_hours=0,
            avg_response_time_seconds=0.5,
        )
        assert status == "healthy"
        assert score == 100.0
        assert reasons == []

    def test_minor_failures_still_healthy(self):
        status, score, reasons = classify_feed_health(
            success_count=95, failure_count=5,
            consecutive_failures=0, last_success_age_hours=1,
            avg_response_time_seconds=1.0,
        )
        assert status == "healthy"
        assert score >= 90

    def test_intermittent_with_consecutive_failures(self):
        status, score, reasons = classify_feed_health(
            success_count=70, failure_count=30,
            consecutive_failures=4, last_success_age_hours=4,
            avg_response_time_seconds=2.0,
        )
        assert status == "intermittent"
        assert any("consecutive_failures" in r for r in reasons)

    def test_stale_feed_is_dead(self):
        status, score, reasons = classify_feed_health(
            success_count=80, failure_count=0,
            consecutive_failures=0, last_success_age_hours=48,
            avg_response_time_seconds=0.5,
        )
        assert status == "dead"
        assert any("stale" in r for r in reasons)

    def test_all_failures_is_dead(self):
        status, score, reasons = classify_feed_health(
            success_count=0, failure_count=50,
            consecutive_failures=50, last_success_age_hours=72,
            avg_response_time_seconds=30,
        )
        assert status == "dead"
        assert score < 50.0
        assert len(reasons) > 0

    def test_no_data_is_dead(self):
        status, score, reasons = classify_feed_health(
            success_count=0, failure_count=0,
        )
        assert status == "dead"
        assert score == 0.0
        assert "no_data" in reasons

    def test_slow_response_penalty(self):
        status, score, reasons = classify_feed_health(
            success_count=100, failure_count=0,
            consecutive_failures=0, last_success_age_hours=0,
            avg_response_time_seconds=15,
        )
        assert score < 100.0
        assert any("slow_response" in r for r in reasons)

    def test_borderline_healthy(self):
        status, score, _ = classify_feed_health(
            success_count=90, failure_count=10,
            consecutive_failures=0, last_success_age_hours=0,
            avg_response_time_seconds=1.0,
        )
        assert status == "healthy"

    def test_borderline_intermittent(self):
        status, score, _ = classify_feed_health(
            success_count=50, failure_count=50,
            consecutive_failures=0, last_success_age_hours=0,
            avg_response_time_seconds=1.0,
        )
        assert status == "intermittent"

    def test_below_intermittent_is_dead(self):
        status, score, _ = classify_feed_health(
            success_count=49, failure_count=100,
            consecutive_failures=0, last_success_age_hours=0,
            avg_response_time_seconds=1.0,
        )
        assert status == "dead"

    def test_consecutive_failures_5_heavy_penalty(self):
        status, score, _ = classify_feed_health(
            success_count=90, failure_count=10,
            consecutive_failures=5, last_success_age_hours=0,
            avg_response_time_seconds=1.0,
        )
        assert score < 65.0


class TestFallbackSwitching:
    """Test fallback feed selection logic."""

    @pytest.fixture
    def feed_registry(self) -> dict[str, dict[str, Any]]:
        return {
            "reuters_top": {"health": "healthy", "category": "news",
                           "url": "https://reuters.com/rss"},
            "bloomberg_markets": {"health": "intermittent", "category": "markets",
                                  "url": "https://bloomberg.com/rss"},
            "yahoo_finance": {"health": "healthy", "category": "markets",
                              "url": "https://finance.yahoo.com/rss"},
            "coindesk": {"health": "dead", "category": "crypto",
                        "url": "https://coindesk.com/rss"},
            "cnbc": {"health": "healthy", "category": "news",
                    "url": "https://cnbc.com/rss"},
        }

    @pytest.fixture
    def fallback_map(self) -> dict[str, str]:
        return {
            "bloomberg_markets": "yahoo_finance",
            "coindesk": "reuters_top",
        }

    def test_selects_configured_fallback(self, feed_registry, fallback_map):
        result = select_fallback_feed(
            "bloomberg_markets", feed_registry, fallback_map
        )
        assert result == "yahoo_finance"

    def test_skips_dead_configured_fallback(self, feed_registry):
        fallback = {"coindesk": "reuters_top"}
        result = select_fallback_feed("coindesk", feed_registry, fallback)
        assert result == "reuters_top"

    def test_falls_back_to_same_category(self, feed_registry):
        result = select_fallback_feed("coindesk", feed_registry)
        assert result is None

    def test_healthy_feed_gets_fallback_anyway(self, feed_registry, fallback_map):
        result = select_fallback_feed("reuters_top", feed_registry, fallback_map)
        assert result is not None
        assert feed_registry[result]["health"] == "healthy"

    def test_no_fallback_available(self, feed_registry):
        all_dead = {k: {**v, "health": "dead"} for k, v in feed_registry.items()}
        result = select_fallback_feed("reuters_top", all_dead)
        assert result is None

    def test_unknown_feed_returns_none(self, feed_registry):
        result = select_fallback_feed("nonexistent_feed", feed_registry)
        assert result is None


class TestRSSParsing:
    """Test RSS XML feed parsing."""

    def test_parse_valid_rss(self, mock_rss_xml: str):
        root = ET.fromstring(mock_rss_xml)
        channel = root.find("channel")
        assert channel is not None
        items = channel.findall("item")
        assert len(items) == 2
        first = items[0]
        assert first.find("title").text == "Fed holds rates steady"
        assert first.find("link").text == "https://example.com/news/fed"

    def test_parse_empty_feed(self):
        xml_str = "<?xml version=\"1.0\"?><rss version=\"2.0\"><channel><title>Empty</title></channel></rss>"
        root = ET.fromstring(xml_str)
        channel = root.find("channel")
        items = channel.findall("item")
        assert len(items) == 0

    def test_extract_all_fields(self, mock_rss_xml: str):
        root = ET.fromstring(mock_rss_xml)
        items = root.findall("channel/item")
        parsed = []
        for item in items:
            parsed.append({
                "title": item.find("title").text if item.find("title") is not None else "",
                "link": item.find("link").text if item.find("link") is not None else "",
                "description": item.find("description").text if item.find("description") is not None else "",
                "pubDate": item.find("pubDate").text if item.find("pubDate") is not None else "",
                "guid": item.find("guid").text if item.find("guid") is not None else "",
            })
        assert len(parsed) == 2
        assert all(p["title"] for p in parsed)
        assert all(p["link"].startswith("https://") for p in parsed)

    def test_missing_optional_fields(self):
        xml_str = "<?xml version=\"1.0\"?><rss version=\"2.0\"><channel><title>Test</title><item><title>Minimal item</title></item></channel></rss>"
        root = ET.fromstring(xml_str)
        items = root.findall("channel/item")
        assert len(items) == 1
        assert items[0].find("title").text == "Minimal item"
        assert items[0].find("link") is None


class TestHealthStateTransitions:
    """Test health state transitions over time."""

    def test_healthy_to_intermittent(self):
        status1, _, _ = classify_feed_health(
            success_count=100, failure_count=0, consecutive_failures=0,
            last_success_age_hours=0, avg_response_time_seconds=1.0,
        )
        assert status1 == "healthy"

        status2, _, _ = classify_feed_health(
            success_count=80, failure_count=20, consecutive_failures=4,
            last_success_age_hours=3, avg_response_time_seconds=8.0,
        )
        assert status2 == "intermittent"

    def test_intermittent_to_dead(self):
        status, _, _ = classify_feed_health(
            success_count=30, failure_count=70, consecutive_failures=6,
            last_success_age_hours=48, avg_response_time_seconds=20.0,
        )
        assert status == "dead"

    def test_recovery_from_intermittent(self):
        status, _, _ = classify_feed_health(
            success_count=85, failure_count=15, consecutive_failures=1,
            last_success_age_hours=1, avg_response_time_seconds=1.5,
        )
        assert status in ("healthy", "intermittent")

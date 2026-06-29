"""test_quality.py — known bad data (missing fields / outliers / expired),
test quality scoring and validation.
"""
from __future__ import annotations

import math
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

_SHARED = Path(__file__).resolve().parents[1]
if str(_SHARED) not in sys.path:
    sys.path.insert(0, str(_SHARED))

NOW = datetime(2026, 6, 29, 18, 0, 0, tzinfo=timezone.utc)


# ============================================================================
# Quality scoring utilities (implement in-module, mirror future patrol.py)
# ============================================================================

REQUIRED_OHLCV_FIELDS = {"market", "symbol", "trade_date", "open", "high", "low", "close", "volume"}
REQUIRED_EVENT_FIELDS = {"event_hash", "provider", "event_time", "title", "url"}


def compute_quality_score_ohlcv(row: dict) -> tuple[float, list[str]]:
    """Score an OHLCV row 0-100. Returns (score, issues list)."""
    issues = []
    score = 100.0

    # Check required fields
    missing = REQUIRED_OHLCV_FIELDS - set(row.keys())
    if missing:
        issues.append(f"missing_fields: {,.join(sorted(missing))}")
        score -= 30 * len(missing)

    # Check null/None values
    for field in ("open", "high", "low", "close", "volume"):
        val = row.get(field)
        if val is None:
            issues.append(f"null_{field}")
            score -= 10

    # Check OHLCV logic: high >= low, high >= open, high >= close, low <= open, low <= close
    o, h, l, c = row.get("open"), row.get("high"), row.get("low"), row.get("close")
    if all(v is not None for v in (o, h, l, c)):
        if h < l:
            issues.append("high_lt_low")
            score -= 20
        if h < max(o, c):
            issues.append("high_not_max")
            score -= 10
        if l > min(o, c):
            issues.append("low_not_min")
            score -= 10

    # Check non-negative prices
    for field in ("open", "high", "low", "close"):
        val = row.get(field)
        if val is not None and val < 0:
            issues.append(f"negative_{field}")
            score -= 20

    # Check volume non-negative
    vol = row.get("volume")
    if vol is not None and vol < 0:
        issues.append("negative_volume")
        score -= 15

    # Check extreme values (price > 1e6 or ratio anomalies)
    if all(v is not None for v in (o, h, l, c)):
        avg = (abs(o) + abs(h) + abs(l) + abs(c)) / 4
        if avg > 1_000_000:
            issues.append("extreme_price")
            score -= 20

    # All zeros
    if all(v == 0 for v in (o, h, l, c) if v is not None):
        issues.append("all_zeros")
        score -= 25

    return max(0.0, score), issues


def compute_quality_score_event(row: dict) -> tuple[float, list[str]]:
    """Score an event/news row 0-100."""
    issues = []
    score = 100.0

    # Check required fields
    missing = REQUIRED_EVENT_FIELDS - set(row.keys())
    if missing:
        issues.append(f"missing_fields: {,.join(sorted(missing))}")
        score -= 25 * len(missing)

    # Check empty/null critical fields
    for field in ("title", "url"):
        val = row.get(field)
        if val is None or (isinstance(val, str) and val.strip() == ""):
            issues.append(f"empty_{field}")
            score -= 15

    # Check freshness
    event_time = row.get("event_time")
    if event_time:
        try:
            if isinstance(event_time, str):
                et = datetime.fromisoformat(event_time.replace("Z", "+00:00"))
                age_hours = (NOW - et).total_seconds() / 3600
                if age_hours > 168:  # 7 days
                    issues.append(f"stale_event: {age_hours:.0f}h old")
                    score -= min(50, age_hours / 10)
                elif age_hours > 48:
                    issues.append(f"aging_event: {age_hours:.0f}h old")
                    score -= 10
        except (ValueError, TypeError):
            issues.append("unparseable_event_time")
            score -= 10

    # Check URL validity
    url = row.get("url", "")
    if url and isinstance(url, str):
        if not (url.startswith("http://") or url.startswith("https://")):
            issues.append("invalid_url_scheme")
            score -= 10

    # Check provider
    provider = row.get("provider")
    if not provider or (isinstance(provider, str) and provider.strip() == ""):
        issues.append("missing_provider")
        score -= 10

    return max(0.0, score), issues


class TestOHLCVQuality:
    """Test quality scoring for OHLCV data."""

    def test_perfect_row_scores_100(self):
        row = {
            "market": "Ashare", "symbol": "000001.SZ",
            "trade_date": "20260629",
            "open": 12.0, "high": 12.8, "low": 11.9, "close": 12.5,
            "volume": 50_000_000,
        }
        score, issues = compute_quality_score_ohlcv(row)
        assert score == 100.0
        assert issues == []

    def test_missing_fields_reduce_score(self, bad_data_missing_fields):
        for row in bad_data_missing_fields:
            score, issues = compute_quality_score_ohlcv(row)
            assert score < 100.0
            assert len(issues) > 0

    def test_negative_open_detected(self):
        row = {
            "market": "Ashare", "symbol": "000001.SZ", "trade_date": "20260629",
            "open": -5.0, "high": 10.0, "low": 9.0, "close": 10.0,
            "volume": 1_000_000,
        }
        score, issues = compute_quality_score_ohlcv(row)
        assert score < 80.0
        assert any("negative" in i for i in issues)

    def test_high_lt_low_detected(self):
        row = {
            "market": "Ashare", "symbol": "000001.SZ", "trade_date": "20260629",
            "open": 12.0, "high": 10.0, "low": 15.0, "close": 13.0,
            "volume": 1_000_000,
        }
        score, issues = compute_quality_score_ohlcv(row)
        assert score < 90.0
        assert any("high_lt_low" in i for i in issues)

    def test_all_zeros_detected(self):
        row = {
            "market": "Crypto", "symbol": "BTCUSDT", "trade_date": "20260629",
            "open": 0, "high": 0, "low": 0, "close": 0,
            "volume": 0,
        }
        score, issues = compute_quality_score_ohlcv(row)
        assert score < 80.0
        assert any("all_zeros" in i for i in issues)

    def test_null_close_detected(self):
        row = {
            "market": "Ashare", "symbol": "000001.SZ", "trade_date": "20260629",
            "open": 12.0, "high": 13.0, "low": 11.0, "close": None,
            "volume": 1_000_000,
        }
        score, issues = compute_quality_score_ohlcv(row)
        assert score < 95.0
        assert any("null_close" in i for i in issues)

    def test_negative_volume_detected(self):
        row = {
            "market": "Ashare", "symbol": "000001.SZ", "trade_date": "20260629",
            "open": 12.0, "high": 13.0, "low": 11.0, "close": 12.5,
            "volume": -5000,
        }
        score, issues = compute_quality_score_ohlcv(row)
        assert score < 85.0
        assert any("negative_volume" in i for i in issues)

    def test_score_never_below_zero(self):
        """Score floor is 0."""
        row = {}  # completely empty
        score, _ = compute_quality_score_ohlcv(row)
        assert score >= 0.0


class TestEventQuality:
    """Test quality scoring for event/news data."""

    def test_perfect_event_scores_100(self):
        row = {
            "event_hash": "abc123",
            "provider": "rss",
            "event_type": "news",
            "event_time": NOW.isoformat(),
            "trade_date": "20260629",
            "title": "Test Event",
            "url": "https://example.com/news/1",
            "source": "reuters",
        }
        score, issues = compute_quality_score_event(row)
        assert score == 100.0
        assert issues == []

    def test_missing_title_detected(self):
        row = {
            "event_hash": "abc",
            "provider": "rss",
            "event_time": NOW.isoformat(),
            "url": "https://example.com/news",
        }
        score, issues = compute_quality_score_event(row)
        assert score < 85.0
        assert any("missing_fields" in i for i in issues)

    def test_empty_title_detected(self):
        row = {
            "event_hash": "abc",
            "provider": "rss",
            "event_time": NOW.isoformat(),
            "title": "",
            "url": "https://example.com/news",
        }
        score, issues = compute_quality_score_event(row)
        assert score < 90.0
        assert any("empty_title" in i for i in issues)

    def test_stale_event_detected(self):
        old = (NOW - timedelta(days=10)).isoformat()
        row = {
            "event_hash": "old",
            "provider": "rss",
            "event_time": old,
            "title": "Old news",
            "url": "https://example.com/old",
        }
        score, issues = compute_quality_score_event(row)
        assert score < 70.0
        assert any("stale" in i for i in issues)

    def test_aging_event_moderate_penalty(self):
        old = (NOW - timedelta(days=3)).isoformat()
        row = {
            "event_hash": "aging",
            "provider": "rss",
            "event_time": old,
            "title": "Aging news",
            "url": "https://example.com/aging",
        }
        score, issues = compute_quality_score_event(row)
        assert score < 90.0  # less penalty than stale
        assert any("aging" in i for i in issues)

    def test_invalid_url_detected(self):
        row = {
            "event_hash": "abc",
            "provider": "rss",
            "event_time": NOW.isoformat(),
            "title": "Bad URL",
            "url": "ftp://example.com/news",
        }
        score, issues = compute_quality_score_event(row)
        assert score < 95.0
        assert any("invalid_url_scheme" in i for i in issues)

    def test_missing_provider_detected(self):
        row = {
            "event_hash": "abc",
            "event_time": NOW.isoformat(),
            "title": "No provider",
            "url": "https://example.com/news",
        }
        score, issues = compute_quality_score_event(row)
        assert score < 95.0
        assert any("missing_provider" in i for i in issues)

    def test_bad_data_expired_all_low_score(self, bad_data_expired):
        for row in bad_data_expired:
            score, _ = compute_quality_score_event(row)
            assert score < 80.0

    def test_score_never_below_zero(self):
        row = {}
        score, _ = compute_quality_score_event(row)
        assert score >= 0.0

"""test_freshness.py — different time intervals, test freshness_score calculation.
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
# Freshness scoring utilities
# ============================================================================

def compute_freshness_score(
    collected_at: datetime | str,
    reference_time: datetime | None = None,
    max_age_hours: float = 24.0,
    decay: str = "linear",
) -> float:
    """Compute a freshness score 0-100 for a data point.

    - 100: just collected (age=0)
    - 0: age >= max_age_hours

    decay modes:
      - "linear": score = 100 * (1 - age/max_age)
      - "exponential": score = 100 * exp(-age / (max_age/3))
      - "step": 100 (age <= max_age/2), 50 (age <= max_age), 0 (age > max_age)
    """
    if reference_time is None:
        reference_time = NOW

    if isinstance(collected_at, str):
        collected_at = datetime.fromisoformat(collected_at.replace("Z", "+00:00"))

    # Ensure both are timezone-aware or both naive
    if collected_at.tzinfo is None and reference_time.tzinfo is not None:
        collected_at = collected_at.replace(tzinfo=timezone.utc)
    elif collected_at.tzinfo is not None and reference_time.tzinfo is None:
        reference_time = reference_time.replace(tzinfo=timezone.utc)

    age_hours = (reference_time - collected_at).total_seconds() / 3600.0
    age_hours = max(0.0, age_hours)

    if decay == "linear":
        score = 100.0 * (1.0 - age_hours / max_age_hours)
    elif decay == "exponential":
        tau = max_age_hours / 3.0
        score = 100.0 * math.exp(-age_hours / tau)
    elif decay == "step":
        if age_hours <= max_age_hours / 2:
            score = 100.0
        elif age_hours <= max_age_hours:
            score = 50.0
        else:
            score = 0.0
    else:
        raise ValueError(f"Unknown decay mode: {decay}")

    return max(0.0, min(100.0, score))


def batch_freshness_summary(
    timestamps: list[datetime],
    max_age_hours: float = 24.0,
) -> dict[str, float]:
    """Compute summary statistics for a batch of data points."""
    if not timestamps:
        return {"count": 0, "fresh_pct": 0.0, "median_score": 0.0,
                "min_score": 0.0, "max_score": 0.0, "stale_pct": 0.0}

    scores = [compute_freshness_score(ts, max_age_hours=max_age_hours) for ts in timestamps]
    scores.sort()
    n = len(scores)

    return {
        "count": n,
        "fresh_pct": sum(1 for s in scores if s >= 90) / n * 100,
        "stale_pct": sum(1 for s in scores if s < 30) / n * 100,
        "median_score": scores[n // 2],
        "min_score": scores[0],
        "max_score": scores[-1],
    }


class TestFreshnessScore:
    """Test freshness_score calculation."""

    def test_just_collected_scores_100(self):
        score = compute_freshness_score(NOW)
        assert score == 100.0

    def test_half_max_age_linear(self):
        ts = NOW - timedelta(hours=12)
        score = compute_freshness_score(ts, max_age_hours=24, decay="linear")
        assert score == pytest.approx(50.0, abs=0.1)

    def test_exact_max_age_scores_zero_linear(self):
        ts = NOW - timedelta(hours=24)
        score = compute_freshness_score(ts, max_age_hours=24, decay="linear")
        assert score == pytest.approx(0.0, abs=0.1)

    def test_beyond_max_age_scores_zero(self):
        ts = NOW - timedelta(hours=48)
        score = compute_freshness_score(ts, max_age_hours=24, decay="linear")
        assert score == 0.0

    def test_exponential_decay(self):
        """Exponential decay is gentler than linear for small ages."""
        ts = NOW - timedelta(hours=8)  # 1/3 of 24h
        linear = compute_freshness_score(ts, max_age_hours=24, decay="linear")
        exp = compute_freshness_score(ts, max_age_hours=24, decay="exponential")
        assert exp > linear  # exponential decays slower initially

    def test_step_decay_half(self):
        ts = NOW - timedelta(hours=12)
        score = compute_freshness_score(ts, max_age_hours=24, decay="step")
        assert score == 100.0

    def test_step_decay_full(self):
        ts = NOW - timedelta(hours=18)
        score = compute_freshness_score(ts, max_age_hours=24, decay="step")
        assert score == 50.0

    def test_step_decay_beyond(self):
        ts = NOW - timedelta(hours=25)
        score = compute_freshness_score(ts, max_age_hours=24, decay="step")
        assert score == 0.0

    def test_future_timestamp_clamped_to_100(self):
        """Future timestamp should not score above 100."""
        ts = NOW + timedelta(hours=1)
        score = compute_freshness_score(ts)
        assert score <= 100.0

    def test_string_timestamp_accepted(self):
        ts = NOW.isoformat()
        score = compute_freshness_score(ts)
        assert score == 100.0

    def test_string_with_z_suffix(self):
        ts = NOW.isoformat().replace("+00:00", "Z")
        score = compute_freshness_score(ts)
        assert score == 100.0

    def test_custom_max_age(self):
        """With max_age_hours=2, 1h old should score 50% linear."""
        ts = NOW - timedelta(hours=1)
        score = compute_freshness_score(ts, max_age_hours=2, decay="linear")
        assert score == 50.0

    def test_score_never_negative(self):
        ts = NOW - timedelta(days=365)
        score = compute_freshness_score(ts, max_age_hours=1)
        assert score >= 0.0

    def test_unknown_decay_raises(self):
        with pytest.raises(ValueError):
            compute_freshness_score(NOW, decay="cubic")


class TestFreshnessIntervals:
    """Test freshness across different time intervals."""

    INTERVALS = [
        (0, 100.0),       # just now
        (1, 95.83),       # 1 hour
        (6, 75.0),        # 6 hours
        (12, 50.0),       # 12 hours
        (18, 25.0),       # 18 hours
        (23, 4.17),       # 23 hours
        (24, 0.0),        # exactly max age
        (48, 0.0),        # 2x max age
    ]

    @pytest.mark.parametrize("age_hours,expected", INTERVALS)
    def test_linear_decay_intervals(self, age_hours, expected):
        ts = NOW - timedelta(hours=age_hours)
        score = compute_freshness_score(ts, max_age_hours=24, decay="linear")
        assert score == pytest.approx(expected, abs=0.1)

    def test_1min_old_near_100(self):
        ts = NOW - timedelta(minutes=1)
        score = compute_freshness_score(ts, max_age_hours=24, decay="linear")
        assert score > 99.0

    def test_5min_old(self):
        ts = NOW - timedelta(minutes=5)
        score = compute_freshness_score(ts, max_age_hours=24, decay="linear")
        assert score > 99.0  # still very fresh

    def test_30min_old(self):
        ts = NOW - timedelta(minutes=30)
        score = compute_freshness_score(ts, max_age_hours=24, decay="linear")
        assert pytest.approx(score, abs=0.5) == 97.92  # ~97.9


class TestBatchFreshness:
    """Test batch freshness summaries."""

    def test_empty_batch(self):
        result = batch_freshness_summary([])
        assert result["count"] == 0
        assert result["fresh_pct"] == 0.0

    def test_all_fresh_batch(self):
        timestamps = [NOW - timedelta(minutes=m) for m in range(0, 30, 5)]
        result = batch_freshness_summary(timestamps, max_age_hours=24)
        assert result["fresh_pct"] == 100.0
        assert result["stale_pct"] == 0.0
        assert result["min_score"] > 95.0

    def test_all_stale_batch(self):
        timestamps = [NOW - timedelta(days=7 + d) for d in range(5)]
        result = batch_freshness_summary(timestamps, max_age_hours=24)
        assert result["stale_pct"] == 100.0
        assert result["max_score"] == 0.0

    def test_mixed_batch(self):
        timestamps = [
            NOW - timedelta(hours=1),    # fresh
            NOW - timedelta(hours=2),    # fresh
            NOW - timedelta(hours=12),   # stale-ish
            NOW - timedelta(hours=48),   # stale
        ]
        result = batch_freshness_summary(timestamps, max_age_hours=24)
        assert result["count"] == 4
        assert result["fresh_pct"] == 50.0  # 2 out of 4 >= 90
        assert result["stale_pct"] == 25.0  # 1 out of 4 < 30

    def test_median_score(self):
        timestamps = [NOW - timedelta(hours=h) for h in [0, 6, 12, 18, 24]]
        result = batch_freshness_summary(timestamps, max_age_hours=24)
        assert result["median_score"] == pytest.approx(50.0, abs=5.0)

    def test_different_max_age_affects_scores(self):
        """Shorter max_age means faster decay."""
        ts = NOW - timedelta(hours=4)
        score_24h = compute_freshness_score(ts, max_age_hours=24, decay="linear")
        score_6h = compute_freshness_score(ts, max_age_hours=6, decay="linear")
        assert score_6h < score_24h  # shorter max_age = faster scoring decay

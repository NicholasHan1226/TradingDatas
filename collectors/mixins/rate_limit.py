"""Rate limiter mixins for different provider strategies."""

from __future__ import annotations

import time
from threading import Lock
from typing import Optional


class RateLimiterMixin:
    """Sliding-window rate limiter (default: 200 calls/min per API key)."""

    _rate_window_sec: float = 60.0
    _rate_limit_per_window: int = 200
    _rate_calls: dict[str, list[float]] = {}
    _rate_lock: Lock = Lock()

    def _rate_limit(self, key: str, max_calls: Optional[int] = None) -> None:
        limit = max_calls or self._rate_limit_per_window
        now = time.time()
        window_start = now - self._rate_window_sec
        with self._rate_lock:
            stamps = self._rate_calls.get(key, [])
            stamps = [t for t in stamps if t > window_start]
            count = len(stamps)
            if count >= limit:
                oldest = stamps[0]
                sleep_for = oldest + self._rate_window_sec - now + 0.05
                if sleep_for > 0:
                    time.sleep(sleep_for)
                now = time.time()
                window_start = now - self._rate_window_sec
                stamps = [t for t in stamps if t > window_start]
            stamps.append(now)
            self._rate_calls[key] = stamps


class BinanceRateLimiter(RateLimiterMixin):
    """Binance weight-based rate limiter (1200 weight/min default)."""

    _binance_weights: dict[str, float] = {}
    _binance_weight_limit: float = 1200.0

    def _rate_limit_binance(self, key: str, weight: float = 1.0) -> None:
        """Enforce Binance weight bucket limit (1200/min)."""
        now = time.time()
        window_start = now - 60.0
        with self._rate_lock:
            stamps = self._binance_weights.get(key, [])
            stamps = [(t, w) for t, w in stamps if t > window_start]
            total_weight = sum(w for _, w in stamps)
            if total_weight + weight > self._binance_weight_limit:
                oldest_t = stamps[0][0]
                sleep_for = oldest_t + 60.0 - now + 0.1
                if sleep_for > 0:
                    time.sleep(sleep_for)
                now = time.time()
                window_start = now - 60.0
                stamps = [(t, w) for t, w in stamps if t > window_start]
            stamps.append((now, weight))
            self._binance_weights[key] = stamps

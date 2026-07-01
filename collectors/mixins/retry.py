"""Retry logic with exponential backoff and jitter."""

from __future__ import annotations

import logging
import random
import time
from typing import Callable, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


class RetryMixin:
    """Exponential backoff retry for network/transient errors."""

    retry_max: int = 3
    retry_base_delay: float = 1.0
    retry_max_delay: float = 60.0
    retry_jitter: bool = True
    retryable_exceptions: tuple[type[BaseException], ...] = (
        ConnectionError, TimeoutError, OSError,
    )

    def _should_retry(self, exc: BaseException) -> bool:
        """Check if exception is retryable. Override for provider-specific errors."""
        if isinstance(exc, self.retryable_exceptions):
            return True
        # Check for HTTP 429 / 5xx in string representation
        msg = str(exc).lower()
        if any(code in msg for code in ("429", "500", "502", "503", "504")):
            return True
        return False

    def _retry_sleep(self, attempt: int) -> float:
        delay = min(self.retry_base_delay * (2 ** attempt), self.retry_max_delay)
        if self.retry_jitter:
            delay *= 0.5 + random.random()
        return delay

    def _retry_call(self, fn: Callable[[], T], key: str = "") -> T:
        """Call fn with retry. Raises last exception if all retries exhausted."""
        last_exc: BaseException | None = None
        for attempt in range(self.retry_max + 1):
            try:
                return fn()
            except Exception as exc:
                last_exc = exc
                if attempt >= self.retry_max or not self._should_retry(exc):
                    raise
                delay = self._retry_sleep(attempt)
                logger.warning("retry %s attempt=%d/%d delay=%.2fs: %s",
                               key, attempt + 1, self.retry_max, delay, exc)
                time.sleep(delay)
        assert last_exc is not None
        raise last_exc

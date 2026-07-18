#!/usr/bin/env python3
"""SharedSignals native Tushare collector — generic collector class.

Uses the strict Tushare outcome helper to fetch provider rows without collapsing
provider failures into empty results. Production persistence is owned by
collectors/tushare/sync_daily.py, which writes rows directly into the SQLite
read model.

Import chain:
  collect() -> collect_outcome() -> env bootstrap -> tushare_common
"""

from __future__ import annotations

import hashlib
import logging
import re
import time
from threading import Lock
from typing import Any

from ..base import BaseCollector  # noqa: E402
from .tushare_common import (
    ProviderCallOutcome,
    provider_outcome_log_fields,
    safe_provider_exception_message,
)

logger = logging.getLogger(__name__)
_TUSHARE_CALL: Any | None = None
_TUSHARE_CALL_LOCK = Lock()
_SAFE_PARAM_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]{0,63}$")


def _parameter_log_summary(params: dict[str, Any]) -> dict[str, Any]:
    """Describe parameter structure without retaining any parameter value."""

    keys = []
    for key in params:
        text = str(key)
        keys.append(
            text if _SAFE_PARAM_KEY.fullmatch(text) else "<untrusted-param-key>"
        )
    return {
        "param_count": len(params),
        "param_keys": tuple(sorted(set(keys))),
    }


def _call_tushare(
    api_name: str,
    params: dict[str, Any],
    fields: str | None = None,
) -> ProviderCallOutcome:
    """Load env and the strict Tushare outcome call lazily."""
    global _TUSHARE_CALL
    if _TUSHARE_CALL is None:
        with _TUSHARE_CALL_LOCK:
            if _TUSHARE_CALL is None:
                from env_bootstrap import bootstrap_sharedsignals_env

                bootstrap_sharedsignals_env()
                from .tushare_common import get_token, tushare_rows_outcome

                def _strict_call(
                    call_api_name: str,
                    call_params: dict[str, Any],
                    call_fields: str | None,
                ) -> ProviderCallOutcome:
                    return tushare_rows_outcome(
                        call_api_name,
                        get_token(),
                        params=call_params,
                        fields=call_fields,
                    )

                _TUSHARE_CALL = _strict_call
    return _TUSHARE_CALL(api_name, params, fields)


# ---------------------------------------------------------------------------
# TushareCollector
# ---------------------------------------------------------------------------

class TushareCollector(BaseCollector):
    """Generic Tushare data collector backed by the SharedSignals Tushare wrapper.

    Includes API rate limiter for Tushare free tier (200 calls/min).

    Usage::

        collector = TushareCollector()
        rows = collector.collect("daily", {"ts_code": "000001.SZ",
                                           "start_date": "20250623",
                                           "end_date": "20250630"})
    """

    # Rate limiter state (class-level)
    _rate_window_sec = 60
    _rate_limit_per_window = 200  # Tushare free tier
    _rate_calls: dict[str, list[float]] = {}  # api_name -> list of timestamps
    _rate_lock = Lock()

    def __init__(self, config: dict[str, Any] | None = None):
        super().__init__(config)
        self.last_collect_failed = False
        self.last_collect_error = ""
        self.last_collect_outcome: ProviderCallOutcome | None = None
        self.collect_call_count = 0
        self.collect_failure_count = 0

    @classmethod
    def _rate_limit(cls, api_name: str):
        """Enforce per-API calls/minute limit. Sleeps if approaching threshold.

        Tushare free tier: 200 calls/min. This method tracks call timestamps
        per api_name, discards stale entries outside the 60s window, and
        sleeps when the count approaches the limit.
        """
        now = time.time()
        window_start = now - cls._rate_window_sec
        with cls._rate_lock:
            stamps = cls._rate_calls.get(api_name, [])
            stamps = [t for t in stamps if t > window_start]
            count = len(stamps)
            if count >= cls._rate_limit_per_window:
                # At limit: sleep until the oldest call exits the window
                oldest = stamps[0]
                sleep_for = oldest + cls._rate_window_sec - now + 0.05
                if sleep_for > 0:
                    logger.warning(
                        "rate_limit: %s at %d/%d calls/min, sleeping %.2fs",
                        api_name, count, cls._rate_limit_per_window, sleep_for,
                    )
                    time.sleep(sleep_for)
                # Recalculate after sleep
                now = time.time()
                window_start = now - cls._rate_window_sec
                stamps = [t for t in stamps if t > window_start]
            elif count >= cls._rate_limit_per_window * 0.9:
                # Approaching limit (90%): log warning
                logger.info(
                    "rate_limit: %s approaching limit %d/%d calls/min",
                    api_name, count, cls._rate_limit_per_window,
                )
            stamps.append(now)
            cls._rate_calls[api_name] = stamps

    @staticmethod
    def _dedup_key(api_name: str, row: dict) -> tuple:
        """Generate dedup key per API: (ts_code, trade_date) or equivalent."""
        keys = {
            "daily": ("ts_code", "trade_date"),
            "moneyflow": ("ts_code", "trade_date"),
            "adj_factor": ("ts_code", "trade_date"),
            "daily_basic": ("ts_code", "trade_date"),
            "fina_indicator": ("ts_code", "end_date"),
            "income": ("ts_code", "end_date"),
            "balancesheet": ("ts_code", "end_date"),
            "margin_detail": ("ts_code", "trade_date"),
            "stock_basic": ("ts_code",),
            "stk_factor": ("ts_code", "trade_date"),
            "index_daily": ("ts_code", "trade_date"),
            "fund_daily": ("ts_code", "trade_date"),
            "moneyflow_hsgt": ("trade_date",),
            "limit_list": ("ts_code", "trade_date"),
            "top_list": ("ts_code", "trade_date"),
            "block_trade": ("ts_code", "trade_date"),
            "hk_daily": ("ts_code", "trade_date"),
            "us_daily": ("ts_code", "trade_date"),
            "cn_cpi": ("month",),
            "cn_pmi": ("month",),
            "cn_m": ("month",),
            "cn_ppi": ("month",),
            "cn_gdp": ("quarter",),
            "sf_month": ("month",),
            "shibor": ("date",),
            "shibor_lpr": ("date",),
            "us_tycr": ("date",),
            "us_tbr": ("date",),
            "us_tltr": ("date",),
            "hibor": ("date",),
            "libor": ("date",),
            "repo_daily": ("trade_date", "repo_maturity"),
        }
        key_fields = keys.get(api_name, ("ts_code", "trade_date"))
        return tuple(str(row.get(f, "")) for f in key_fields)

    @staticmethod
    def _validate_row(api_name: str, row: dict) -> dict:
        """Basic validation: mark quality issues."""
        quality = {"score": 1.0, "issues": []}
        # OHLCV sanity
        if api_name in ("daily", "hk_daily", "us_daily"):
            for f in ("open", "high", "low", "close"):
                if f in row and row.get(f):
                    try:
                        v = float(row[f])
                        if v <= 0:
                            quality["issues"].append(f"{f}_zero_or_negative")
                            quality["score"] = max(0, quality["score"] - 0.2)
                    except (ValueError, TypeError):
                        quality["issues"].append(f"{f}_non_numeric")
                        quality["score"] = max(0, quality["score"] - 0.3)
            # High < Low check
            try:
                if float(row.get("high", 0)) < float(row.get("low", 0)):
                    quality["issues"].append("high_less_than_low")
                    quality["score"] = 0.0
            except (ValueError, TypeError):
                pass
        # Missing key fields
        for f in ("ts_code", "trade_date"):
            if api_name in ("daily", "moneyflow", "stk_factor"):
                if not row.get(f):
                    quality["issues"].append(f"missing_{f}")
                    quality["score"] = max(0, quality["score"] - 0.5)
        row["_quality"] = quality
        return row

    
    @staticmethod
    def _text_fingerprint(title: str, content: str = "") -> str:
        """Generate content hash for dedup."""
        clean = re.sub(r"\s+", "", (title + content)[:500])
        return hashlib.sha256(clean.encode()).hexdigest()[:16]

    @staticmethod
    def _title_similar(a: str, b: str) -> float:
        """Simple token overlap ratio for title similarity."""
        if not a or not b:
            return 0.0
        ta = set(re.findall(r"[一-鿿\w]+", a.lower()))
        tb = set(re.findall(r"[一-鿿\w]+", b.lower()))
        if not ta or not tb:
            return 0.0
        return len(ta & tb) / len(ta | tb)

    @classmethod
    def event_deduplicate(cls, rows: list[dict], time_window_h: int = 24) -> list[dict]:
        """Semantic dedup for news/events:
        1. URL exact match → skip
        2. Content hash match → skip  
        3. Title similarity >0.85 → skip (same news, different source)
        4. Time-window: same title within 24h → skip
        """
        if not rows:
            return rows
        seen_urls = set()
        seen_hashes = set()
        seen_titles = {}  # title → (hash, time)
        result = []
        for row in rows:
            url = str(row.get("source_url", row.get("url", ""))).strip()
            title = str(row.get("title", "")).strip()
            summary = str(row.get("summary", row.get("content", ""))).strip()
            event_time = str(row.get("event_time", row.get("trade_date", ""))).strip()
            
            # 1. URL dedup
            if url and url in seen_urls:
                row["_dedup_skip"] = "url_duplicate"
                continue
            if url:
                seen_urls.add(url)
            
            # 2. Content hash dedup
            fprint = cls._text_fingerprint(title, summary)
            if fprint in seen_hashes:
                row["_dedup_skip"] = "hash_duplicate"
                continue
            seen_hashes.add(fprint)
            
            # 3. Title similarity check
            for seen_title, (seen_hash, _) in list(seen_titles.items()):
                if cls._title_similar(title, seen_title) > 0.85:
                    row["_dedup_skip"] = "title_similar"
                    break
            if row.get("_dedup_skip"):
                continue
            
            seen_titles[title] = (fprint, event_time)
            result.append(row)
        
        return result

    def deduplicate(self, api_name: str, rows: list) -> list:
        """Dedup rows by primary key, keeping latest."""
        seen = {}
        for row in rows:
            key = self._dedup_key(api_name, row)
            seen[key] = row  # last wins
        return list(seen.values())

    def validate(self, api_name: str, rows: list) -> list:
        """Add quality metadata to each row."""
        return [self._validate_row(api_name, r) for r in rows]

    # ------------------------------------------------------------------
    # collect
    # ------------------------------------------------------------------

    def collect_outcome(
        self,
        api_name: str,
        params: dict[str, Any],
        fields: str | None = None,
    ) -> ProviderCallOutcome:
        """Call the strict provider path and retain its typed outcome."""

        self.collect_call_count += 1
        self.last_collect_failed = False
        self.last_collect_error = ""
        self._rate_limit(api_name)
        logger.info(
            "collect %s with params=%s",
            api_name,
            _parameter_log_summary(params),
        )
        candidate: Any = None
        try:
            candidate = _call_tushare(api_name, params, fields)
            if not isinstance(candidate, ProviderCallOutcome):
                raise TypeError("collector returned an invalid provider outcome type")
            candidate.validate_invariants()
            outcome = candidate
        except Exception as exc:
            outcome = ProviderCallOutcome(
                state="failed",
                rows=(),
                provider_code=None,
                error_code="provider_error",
                error_message=safe_provider_exception_message(
                    exc,
                    invalid_outcome=candidate is not None,
                ),
            )

        self.last_collect_outcome = outcome
        if outcome.state == "failed":
            self.last_collect_failed = True
            self.last_collect_error = (
                outcome.error_message
                or outcome.error_code
                or "Tushare provider call failed"
            )
            self.collect_failure_count += 1
            logger.error(
                "collect %s failed: outcome=%s",
                api_name,
                provider_outcome_log_fields(outcome),
            )
        else:
            logger.info(
                "collect %s → %d rows (%s)",
                api_name,
                len(outcome.rows),
                outcome.state,
            )
        return outcome

    def collect(
        self,
        api_name: str,
        params: dict[str, Any],
        fields: str | None = None,
    ) -> list[dict[str, Any]]:
        """Call a Tushare API and return rows as list[dict].

        Args:
            api_name:  Tushare API name (e.g. "daily", "moneyflow", "fina_indicator").
            params:    Dict of API parameters (ts_code, start_date, end_date, etc.).
            fields:    Optional comma-separated field list; when omitted the API
                       default fields are used.

        Returns:
            List of row dicts; empty list on error or no results.
        """
        return self.collect_outcome(api_name, params, fields).mutable_rows()

    # ------------------------------------------------------------------
    # BaseCollector-compatible metadata
    # ------------------------------------------------------------------

    name = "tushare"
    provider = "tushare"
    market = "Ashare"
    target_tables = ["market_bars_daily", "market_events"]

    def save(self, batch: Any, **kwargs: Any) -> Any:
        """Block the retired CSV persistence lifecycle."""
        del batch, kwargs
        raise RuntimeError("TushareCollector.save is retired; use sync_daily direct SQLite ingestion")

    def health_check(self) -> dict[str, Any]:
        """Check if Tushare API wrapper is importable and functional."""
        try:
            import importlib.util

            if importlib.util.find_spec(".tushare_api", package=__package__) is None:
                return {"status": "unavailable", "message": "tushare api wrapper not found"}
            return {"status": "available", "message": "tushare api wrapper loaded"}
        except ImportError as exc:
            return {"status": "unavailable", "message": str(exc)}

    def run(self, context: dict[str, Any] | None = None) -> dict[str, Any]:
        """Retired legacy lifecycle.

        Production Tushare jobs must use collectors/tushare/sync_daily.py so
        provider rows are planned from the SQLite read model and written back
        directly to SQLite. Keeping a CSV-writing lifecycle here would reopen a
        stale data path, so direct collector.run() is intentionally blocked.
        """
        del context
        raise RuntimeError("TushareCollector.run is retired; use collectors/tushare/sync_daily.py")


# ---------------------------------------------------------------------------
# Quick self-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    c = TushareCollector()
    rows = c.collect("daily", {"ts_code": "000001.SZ", "start_date": "20250630", "end_date": "20250630"})
    print(f"Self-test daily(000001.SZ, 20250630): {len(rows)} rows")
    for r in rows[:2]:
        print(r)

#!/usr/bin/env python3
"""SharedSignals native Tushare collector — generic collector class.

Uses the Ashare Tushare wrapper (_call) to fetch ANY Tushare API and persist
results as date-partitioned CSV under data/tushare/.

Import chain:
  collect() -> env bootstrap -> tushare_common (token) -> tushare_api (_call)
"""

from __future__ import annotations

import csv
import hashlib
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
import time
from threading import Lock
from typing import Any

_BASE_DIR = Path(__file__).resolve().parents[2]  # SharedSignals root

from ..base import BaseCollector  # noqa: E402

logger = logging.getLogger(__name__)
_TUSHARE_CALL: Any | None = None
_TUSHARE_CALL_LOCK = Lock()


def _call_tushare(api_name: str, params: dict[str, Any], fields: str = "") -> list[dict[str, Any]]:
    """Load env and Tushare wrapper lazily, only for real API calls."""
    global _TUSHARE_CALL
    if _TUSHARE_CALL is None:
        with _TUSHARE_CALL_LOCK:
            if _TUSHARE_CALL is None:
                from env_bootstrap import bootstrap_sharedsignals_env

                bootstrap_sharedsignals_env()
                from .tushare_api import _call

                _TUSHARE_CALL = _call
    return _TUSHARE_CALL(api_name, params, fields)


# ---------------------------------------------------------------------------
# TushareCollector
# ---------------------------------------------------------------------------

class TushareCollector(BaseCollector):
    """Generic Tushare data collector backed by the Ashare API wrapper.

    Includes API rate limiter for Tushare free tier (200 calls/min).

    Usage::

        collector = TushareCollector()
        rows = collector.collect("daily", {"ts_code": "000001.SZ",
                                           "start_date": "20250623",
                                           "end_date": "20250630"})
        collector.save("daily", rows, "20250630", filename="000001.SZ.csv")
    """

    # Rate limiter state (class-level)
    _rate_window_sec = 60
    _rate_limit_per_window = 200  # Tushare free tier
    _rate_calls: dict[str, list[float]] = {}  # api_name -> list of timestamps
    _rate_lock = Lock()

    # Data root (class-level — set from module _BASE_DIR)
    DATA_ROOT = _BASE_DIR / "data" / "tushare"

    def __init__(self, config: dict[str, Any] | None = None):
        super().__init__(config)

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
            "shibor": ("date",),
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
            except (ValueError, TypeError): pass
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
        self._rate_limit(api_name)
        logger.info("collect %s with params=%s", api_name, params)
        try:
            rows = _call_tushare(api_name, params, fields or "")
            logger.info("collect %s → %d rows", api_name, len(rows))
            return rows
        except Exception:
            logger.exception("collect %s failed", api_name)
            return []

    # ------------------------------------------------------------------
    # save
    # ------------------------------------------------------------------

    def save(
        self,
        api_name: str,
        rows: list[dict[str, Any]],
        trade_date: str,
        filename: str | None = None,
    ) -> Path | None:
        """Persist collected rows as a date-partitioned CSV file.

        Directory layout::

            data/tushare/{api_name}/{trade_date}/{filename}.csv

        Args:
            api_name:   Tushare API name.
            rows:       Collected row dicts.
            trade_date: Trade date string (YYYYMMDD) used for partitioning.
            filename:   Output CSV filename (without extension).  Defaults to
                        ``{api_name}_{trade_date}.csv``.

        Returns:
            Path to the written CSV file, or None if rows is empty.
        """
        if not rows:
            logger.info("save %s/%s: no rows, skipping", api_name, trade_date)
            return None

        dir_path = self.DATA_ROOT / api_name / trade_date
        dir_path.mkdir(parents=True, exist_ok=True)

        fname = (filename or f"{api_name}_{trade_date}") + ".csv"
        path = dir_path / fname

        try:
            import tempfile
            fields = list(rows[0].keys())
            # Write to temp file then atomically rename to avoid truncation races
            tmp_fd, tmp_path = tempfile.mkstemp(
                suffix=".csv", prefix=".tmp_", dir=str(dir_path)
            )
            try:
                with os.fdopen(tmp_fd, "w", encoding="utf-8-sig", newline="") as fh:
                    writer = csv.DictWriter(fh, fieldnames=fields)
                    writer.writeheader()
                    writer.writerows(rows)
                os.replace(tmp_path, str(path))
            except Exception:
                # Clean up temp file on failure
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise
            logger.info("save %s → %s (%d rows)", api_name, path, len(rows))
            return path
        except Exception:
            logger.exception("save %s failed", api_name)
            return None

    # ------------------------------------------------------------------
    # BaseCollector-compatible interface (orchestrator calls these)
    # ------------------------------------------------------------------

    name = "tushare"
    provider = "tushare"
    market = "Ashare"
    target_tables = ["market_bars_daily", "market_events"]

    def health_check(self) -> dict[str, Any]:
        """Check if Tushare API wrapper is importable and functional."""
        try:
            import importlib.util

            if importlib.util.find_spec(".tushare_api", package=__package__) is None:
                return {"status": "unavailable", "message": "tushare api wrapper not found"}
            return {"status": "available", "message": "tushare api wrapper loaded"}
        except ImportError as exc:
            return {"status": "unavailable", "message": str(exc)}

    def plan(self, context: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """Generate collection tasks by flattening priority groups from config.

        Resolves {ts_code} placeholders from stock_master.csv so that per-stock
        Tushare collectors produce real API calls instead of silent no-ops.
        """
        import re
        tasks: list[dict[str, Any]] = []

        # Collect all API entries across priority groups
        for key, value in self.config.items():
            if key == "priorities":
                for _prio_name, prio_tasks in value.items():
                    if isinstance(prio_tasks, list):
                        tasks.extend(prio_tasks)
            elif isinstance(value, list):
                tasks.extend(value)

        # Resolve {ts_code} placeholders against stock_master.csv
        resolved: list[dict[str, Any]] = []
        _placeholder_re = re.compile(r"\{ts_code\}")
        _stock_codes: list[str] | None = None

        for task in tasks:
            raw = str(task)
            if "{ts_code}" not in raw:
                resolved.append(task)
                continue
            # Lazy-load stock codes from reference CSV
            if _stock_codes is None:
                _stock_codes = self._load_stock_codes()
            if not _stock_codes:
                logger.warning("plan: {ts_code} placeholder found but no stock codes loaded — skipping %s", task.get("api_name", task))
                continue
            for code in _stock_codes:
                import json
                # Use json round-trip for safe placeholder substitution
                raw_resolved = json.loads(json.dumps(task).replace("{ts_code}", code))
                resolved.append(raw_resolved)

        return resolved

    def _load_stock_codes(self) -> list[str]:
        """Load ts_code list from stock_master.csv reference file."""
        import csv
        master = self.REFERENCE_ROOT / "stock_master.csv"
        if not master.exists():
            logger.warning("_load_stock_codes: %s not found", master)
            return []
        try:
            with open(master, "r", encoding="utf-8-sig", newline="") as f:
                rows = list(csv.DictReader(f))
            codes = [r["ts_code"] for r in rows if r.get("ts_code")]
            logger.info("_load_stock_codes: loaded %d codes from %s", len(codes), master)
            return codes
        except Exception:
            logger.exception("_load_stock_codes: failed to read %s", master)
            return []

    def run(self, context: dict[str, Any] | None = None) -> dict[str, Any]:
        """Orchestrator-compatible run() — executes full lifecycle via mixin hooks."""
        run_id = self._make_run_id()
        started_at = self._utc_now()

        result: dict[str, Any] = {
            "run_id": run_id, "collector": self.name, "started_at": started_at,
            "finished_at": "", "status": "running", "rows_read": 0,
            "rows_written": 0, "tables_written": [], "error": "", "notes": {},
        }

        try:
            health = self.health_check()
            if health.get("status") == "unavailable":
                result["status"] = "skipped"
                result["error"] = health.get("message", "collector unavailable")
                return self._finish(result)

            tasks = self.plan(context)
            if not tasks:
                result["status"] = "success"
                result["notes"]["message"] = "no tasks planned"
                return self._finish(result)

            for task in tasks:
                try:
                    rows = self.collect(
                        task["api_name"], task.get("params", {}), task.get("fields"),
                    )
                    if not rows:
                        continue
                    result["rows_read"] += len(rows)

                    validated = self.validate_batch(task["api_name"], rows)
                    deduped = self.deduplicate_batch(task["api_name"], validated)

                    trade_date = task.get("trade_date") or datetime.now(timezone.utc).strftime("%Y%m%d")
                    save_path = self.save(task["api_name"], deduped, trade_date)
                    if save_path:
                        result["rows_written"] += len(deduped)
                        result["tables_written"].extend(self.target_tables)
                except Exception:
                    logger.exception("task failed: %s", task)
                    result["notes"].setdefault("task_errors", []).append(str(task))

            result["status"] = "success" if result["rows_written"] > 0 else "partial_success"
        except Exception as exc:
            logger.exception("collector run failed: %s", self.name)
            result["status"] = "failed"
            result["error"] = str(exc)

        try:
            self._write_audit({
                "run_id": run_id,
                "started_at": started_at,
                "finished_at": self._utc_now(),
                "status": result["status"],
                "source": f"{self.name}:{self.provider}",
                "rows_read": result["rows_read"],
                "rows_written": result["rows_written"],
                "notes": {"config_hash": str(hash(str(self.config))), "error": result["error"]},
            })
        except Exception:
            logger.exception("audit write failed for %s", self.name)
        return self._finish(result)


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

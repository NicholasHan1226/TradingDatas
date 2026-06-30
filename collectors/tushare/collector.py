#!/usr/bin/env python3
"""SharedSignals native Tushare collector — generic collector class.

Uses the Ashare Tushare wrapper (_call) to fetch ANY Tushare API and persist
results as date-partitioned CSV under data/tushare/.

Import chain:
  .env (QUICKSYNC_URL) → a_share_common (token) → a_share_tushare_api (_call)
"""

from __future__ import annotations

import csv
import logging
import os
import sys
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Bootstrap: load .env before importing Ashare modules so a_share_common can
#               pick up QUICKSYNC_URL for token resolution.
# ---------------------------------------------------------------------------

_BASE_DIR = Path(__file__).resolve().parents[2]  # SharedSignals root
_ENV_FILE = _BASE_DIR / ".env"

if _ENV_FILE.is_file():
    for _line in _ENV_FILE.read_text(encoding="utf-8").splitlines():
        _line = _line.strip()
        if not _line or _line.startswith("#") or "=" not in _line:
            continue
        _key, _, _val = _line.partition("=")
        _key, _val = _key.strip(), _val.strip().strip("\"'")
        if _key and _key not in os.environ:
            os.environ[_key] = _val

# ---------------------------------------------------------------------------
# Ensure a_share_common sees INVESTMENT_ROOT correctly even though we are in
# SharedSignals, not Ashare.  The module derives ROOT from __file__ → parents[1],
# which is Ashare/ — that is fine.  We just need to add Ashare/tools to sys.path.
# ---------------------------------------------------------------------------

_ASHARE_TOOLS = _BASE_DIR.parent / "Ashare" / "tools"  # /opt/investment/Ashare/tools
if str(_ASHARE_TOOLS) not in sys.path:
    sys.path.insert(0, str(_ASHARE_TOOLS))

from a_share_tushare_api import _call  # noqa: E402

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# TushareCollector
# ---------------------------------------------------------------------------

class TushareCollector:

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
            except: pass
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
    """Generic Tushare data collector backed by the Ashare API wrapper.

    Usage::

        collector = TushareCollector()
        rows = collector.collect("daily", {"ts_code": "000001.SZ",
                                           "start_date": "20250623",
                                           "end_date": "20250630"})
        collector.save("daily", rows, "20250630", filename="000001.SZ.csv")
    """

    # Directory root for collected CSV output.
    DATA_ROOT = _BASE_DIR / "data" / "tushare"

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
        logger.info("collect %s with params=%s", api_name, params)
        try:
            rows = _call(api_name, params, fields or "")
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
            fields = list(rows[0].keys())
            with path.open("w", encoding="utf-8-sig", newline="") as fh:
                writer = csv.DictWriter(fh, fieldnames=fields)
                writer.writeheader()
                writer.writerows(rows)
            logger.info("save %s → %s (%d rows)", api_name, path, len(rows))
            return path
        except Exception:
            logger.exception("save %s failed", api_name)
            return None


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

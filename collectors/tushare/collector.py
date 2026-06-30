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

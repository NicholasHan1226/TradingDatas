"""Coverage tracking mixin — updates market_coverage_status after each run."""

from __future__ import annotations

import logging
import os
import sqlite3
from typing import Any

logger = logging.getLogger(__name__)


class CoverageMixin:
    """Updates per-symbol per-day coverage status."""

    db_path: str = ""

    def _ensure_coverage_path(self) -> None:
        if not self.db_path:
            root = os.environ.get("SHAREDSIGNALS_ROOT", "")
            self.db_path = os.path.join(root, "data", "marketdata.sqlite") if root else ""

    def _update_coverage(
        self,
        market: str,
        trade_date: str,
        symbol: str,
        status: str,
        provider: str = "",
        reason: str = "",
        source_file: str = "",
    ) -> bool:
        """Upsert one coverage record."""
        self._ensure_coverage_path()
        if not self.db_path or not os.path.exists(self.db_path):
            return False
        try:
            conn = sqlite3.connect(self.db_path)
            conn.execute(
                """INSERT OR REPLACE INTO market_coverage_status
                   (market, trade_date, symbol, coverage_status, reason, provider, source_file, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (market, trade_date, symbol, status, reason, provider, source_file,
                 self._utc_now() if hasattr(self, "_utc_now") else __import__("datetime").datetime.now().isoformat()),
            )
            conn.commit()
            conn.close()
            return True
        except Exception:
            logger.exception("coverage update failed for %s/%s/%s", market, symbol, trade_date)
            return False

    def _bulk_update_coverage(self, records: list[dict[str, Any]]) -> int:
        """Batch upsert coverage records. Returns count written."""
        self._ensure_coverage_path()
        if not records or not self.db_path or not os.path.exists(self.db_path):
            return 0
        written = 0
        try:
            conn = sqlite3.connect(self.db_path)
            now = __import__("datetime").datetime.now().isoformat()
            for rec in records:
                conn.execute(
                    """INSERT OR REPLACE INTO market_coverage_status
                       (market, trade_date, symbol, coverage_status, reason, provider, source_file, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (rec["market"], rec["trade_date"], rec["symbol"],
                     rec.get("status", "unknown"), rec.get("reason", ""),
                     rec.get("provider", ""), rec.get("source_file", ""), now),
                )
                written += 1
            conn.commit()
            conn.close()
        except Exception:
            logger.exception("bulk coverage update failed")
        return written

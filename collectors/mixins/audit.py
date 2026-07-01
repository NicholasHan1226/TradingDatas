"""Audit mixin — writes market_ingest_runs for every collector run."""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class SQLiteAuditMixin:
    """Writes ingest run audit records to SQLite and CSV staging."""

    db_path: str = ""
    csv_audit_path: str = ""

    def _ensure_audit_paths(self) -> None:
        if not self.db_path:
            root = os.environ.get("SHAREDSIGNALS_ROOT", "")
            self.db_path = os.path.join(root, "data", "marketdata.sqlite") if root else ""
        if not self.csv_audit_path:
            root = os.environ.get("SHAREDSIGNALS_ROOT", "")
            self.csv_audit_path = os.path.join(root, "data", "intake", "collection_runs.csv") if root else ""

    def _write_audit(self, run_result: dict[str, Any]) -> bool:
        """Write audit record to market_ingest_runs table and CSV staging."""
        self._ensure_audit_paths()
        success = False
        if not self.db_path:
            logger.debug("audit: no db_path configured, skipping sqlite audit")
        elif not os.path.exists(self.db_path):
            logger.warning("audit: db_path %s does not exist, skipping sqlite audit", self.db_path)
        else:
            try:
                conn = sqlite3.connect(self.db_path)
                conn.execute(
                    """INSERT OR REPLACE INTO market_ingest_runs
                       (run_id, started_at, finished_at, status, source, rows_read, rows_written, notes)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        run_result["run_id"],
                        run_result["started_at"],
                        run_result["finished_at"],
                        run_result["status"],
                        run_result["source"],
                        run_result.get("rows_read", 0),
                        run_result.get("rows_written", 0),
                        json.dumps(run_result.get("notes", {}), ensure_ascii=False),
                    ),
                )
                conn.commit()
                conn.close()
                success = True
            except Exception:
                logger.exception("audit sqlite write failed")

        if self.csv_audit_path:
            try:
                Path(self.csv_audit_path).parent.mkdir(parents=True, exist_ok=True)
                import csv
                write_header = not os.path.exists(self.csv_audit_path)
                with open(self.csv_audit_path, "a", newline="") as f:
                    writer = csv.writer(f)
                    if write_header:
                        writer.writerow(["run_id", "started_at", "finished_at", "status", "source",
                                         "rows_read", "rows_written", "notes"])
                    writer.writerow([
                        run_result["run_id"], run_result["started_at"], run_result["finished_at"],
                        run_result["status"], run_result["source"],
                        run_result.get("rows_read", 0), run_result.get("rows_written", 0),
                        json.dumps(run_result.get("notes", {}), ensure_ascii=False),
                    ])
                success = True
            except Exception:
                logger.exception("audit csv write failed")
        return success

    @staticmethod
    def _make_run_id() -> str:
        return uuid.uuid4().hex[:12]

    @staticmethod
    def _utc_now() -> str:
        return datetime.now(timezone.utc).isoformat()

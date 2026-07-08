"""BaseCollector — abstract interface for all SharedSignals data collectors.

Lifecycle: init -> health_check -> plan -> collect -> validate -> dedup -> save -> audit -> coverage_update

Each collector implementation must override: health_check, plan, collect, save.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from .mixins.rate_limit import RateLimiterMixin
from .mixins.retry import RetryMixin
from .mixins.validation import ValidatorMixin
from .mixins.dedup import DeduplicatorMixin
from .mixins.audit import SQLiteAuditMixin
from .mixins.coverage import CoverageMixin

logger = logging.getLogger(__name__)


class BaseCollector(
    RateLimiterMixin,
    RetryMixin,
    ValidatorMixin,
    DeduplicatorMixin,
    SQLiteAuditMixin,
    CoverageMixin,
    ABC,
):
    """Abstract base for all data collectors.

    Class Attributes (override in subclass):
        name: Collector identifier (e.g. "tushare", "binance", "polymarket", "rss")
        provider: Data source identifier written to provider column
        market: Market scope ("Ashare", "Crypto", "PredictionMarkets", "global")
        target_tables: List of schema table names this collector writes to
        enabled: Whether this collector is active
    """

    name: str = ""
    provider: str = ""
    market: str = ""
    target_tables: list[str] = []
    enabled: bool = True

    def __init__(self, config: dict[str, Any] | None = None):
        self.config = config or {}
        self._data_root = Path(__file__).resolve().parents[1] / "data"

    # -- abstract methods (must implement) ----------------------------------

    @abstractmethod
    def health_check(self) -> dict[str, Any]:
        """Return collector health: {status, message, last_success, ...}."""
        ...

    @abstractmethod
    def collect(self, task: Any) -> Any:
        """Execute one collection task, return collected data (list[dict] or CollectBatch)."""
        ...

    @abstractmethod
    def save(self, batch: Any, **kwargs: Any) -> Any:
        """Persist collected data directly to read-model tables.

        Implementations must return explicit SQLite/read-model write counts.
        Audit or migration files, if any, do not count as collection success.
        """
        ...

    # -- optional overrides --------------------------------------------------

    def plan(self, context: dict[str, Any] | None = None) -> list[Any]:
        """Generate list of CollectTask for this run. Default: empty plan."""
        return []

    def validate_batch(self, api_name: str, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Validate rows, adding _quality metadata."""
        return self.validate(api_name, rows)

    def deduplicate_batch(self, api_name: str, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Deduplicate rows by primary key."""
        return self.deduplicate(api_name, rows)

    # -- lifecycle runner -----------------------------------------------

    def run(self, context: dict[str, Any] | None = None) -> dict[str, Any]:
        """Execute full collector lifecycle for one tick. Returns RunResult as dict."""
        run_id = self._make_run_id()
        started_at = self._utc_now()
        result: dict[str, Any] = {
            "run_id": run_id,
            "collector": self.name,
            "started_at": started_at,
            "finished_at": "",
            "status": "running",
            "rows_read": 0,
            "rows_written": 0,
            "tables_written": [],
            "error": "",
            "notes": {},
        }

        try:
            # 1. Health check
            health = self.health_check()
            if health.get("status") == "unavailable":
                result["status"] = "skipped"
                result["error"] = health.get("message", "collector unavailable")
                result["notes"]["health"] = health
                return self._finish(result)

            # 2. Plan
            tasks = self.plan(context)
            if not tasks:
                result["status"] = "success"
                result["notes"]["message"] = "no tasks planned"
                return self._finish(result)

            # 3. Collect + Validate + Dedup + Save per task
            for task in tasks:
                try:
                    batch = self.collect(task)
                    if batch is None:
                        continue
                    rows = batch.rows if hasattr(batch, "rows") else batch
                    if not rows:
                        continue
                    result["rows_read"] += len(rows)
                    api = task.get("api_name", task.get("dataset", "")) if isinstance(task, dict) else ""
                    validated = self.validate_batch(api, rows)
                    deduped = self.deduplicate_batch(api, validated)
                    save_result = self.save(deduped, task=task)
                    if save_result and isinstance(save_result, dict):
                        written = int(
                            save_result.get(
                                "sqlite_rows_written",
                                save_result.get("rows_written", 0),
                            )
                            or 0
                        )
                        result["rows_written"] += written
                        if written > 0:
                            result["tables_written"].extend(
                                save_result.get("tables", self.target_tables)
                            )
                except Exception:
                    logger.exception("task failed: %s", task)
                    result["notes"].setdefault("task_errors", []).append(str(task))

            # 4. Audit
            if result["rows_written"] > 0:
                result["status"] = "success"
            elif result["rows_read"] > 0:
                result["status"] = "failed"
                result["error"] = "non-empty collection wrote zero read-model rows"
            else:
                result["status"] = "partial_success"
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
        except Exception as exc:
            logger.exception("collector run failed: %s", self.name)
            result["status"] = "failed"
            result["error"] = str(exc)

        return self._finish(result)

    def _finish(self, result: dict[str, Any]) -> dict[str, Any]:
        result["finished_at"] = self._utc_now()
        if result["status"] == "running":
            result["status"] = "partial_success"
        return result

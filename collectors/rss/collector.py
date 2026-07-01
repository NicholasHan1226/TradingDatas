"""RSS Collector wrapper — adapts the MarketGraph RSSCollector to the BaseCollector interface.

The actual RSS collection logic lives in MarketGraph's RSSCollector module
(referenced via reference/ symlinks). This wrapper provides:
  - A BaseCollector-compliant interface for unified orchestration
  - Health check that queries feed health monitor status
  - Plan generates per-source collect tasks
  - Collect delegates to the RSS bridge/filter pipeline
  - Save writes events to market_events via staging NDJSON
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# The RSS collector code is symlinked under reference/
_REF = Path(__file__).resolve().parents[1] / "reference"
if str(_REF) not in sys.path:
    sys.path.insert(0, str(_REF))

from .source_failover import SourceFailover  # noqa: E402
from .feed_health_monitor import FeedHealthMonitor  # noqa: E402

from ..base import BaseCollector  # noqa: E402

logger = logging.getLogger(__name__)


class RSSCollector(BaseCollector):
    """RSS news/event collector — wraps MarketGraph RSS pipeline.

    Writes to market_events table via NDJSON staging.
    """

    name = "rss"
    provider = "rss"
    market = "global"
    target_tables = ["market_events"]

    def __init__(self, config: dict[str, Any] | None = None):
        super().__init__(config)
        self._failover = SourceFailover()
        self._health_monitor = FeedHealthMonitor()

    # ------------------------------------------------------------------
    # Health check
    # ------------------------------------------------------------------

    def health_check(self) -> dict[str, Any]:
        try:
            h = self._health_monitor.check_all()
            healthy = sum(1 for v in h.values() if v.get("status") == "ok")
            total = len(h)
            if total == 0:
                return {"status": "degraded", "message": "no feeds configured"}
            if healthy == total:
                return {"status": "available", "message": f"{healthy}/{total} feeds ok"}
            if healthy > 0:
                return {"status": "degraded", "message": f"{healthy}/{total} feeds ok"}
            return {"status": "unavailable", "message": "0 feeds reachable"}
        except Exception as exc:
            return {"status": "unavailable", "message": str(exc)}

    # ------------------------------------------------------------------
    # Plan
    # ------------------------------------------------------------------

    def plan(self, context: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """Build per-feed collection plan. Each task is one RSS source."""
        try:
            source_status = self._failover.get_source_status()
        except Exception:
            source_status = {}

        tasks = []
        for source_name, status in source_status.items():
            if status.get("active", True):
                tasks.append({
                    "type": "rss_fetch",
                    "source": source_name,
                    "config": status.get("config", {}),
                })
        return tasks

    # ------------------------------------------------------------------
    # Collect
    # ------------------------------------------------------------------

    def collect(self, task: dict[str, Any]) -> list[dict[str, Any]]:
        """Fetch RSS feed via bridge and normalize to event rows."""
        source = task.get("source", "unknown")

        try:
            raw_items = self._fetch_source(source, task.get("config", {}))
        except Exception:
            logger.exception("rss fetch failed: %s", source)
            return []

        return self._normalize_events(raw_items, source)

    def _fetch_source(self, source: str, config: dict[str, Any]) -> list[dict[str, Any]]:
        """Fetch one RSS source, applying failover if needed."""
        try:
            from reference.rss_bridge import fetch_feed
        except ImportError:
            logger.warning("rss_bridge not importable, returning empty")
            return []

        items = fetch_feed(source, config)
        return items if isinstance(items, list) else []

    # ------------------------------------------------------------------
    # Normalize
    # ------------------------------------------------------------------

    def _normalize_events(self, raw: list[dict[str, Any]], source: str) -> list[dict[str, Any]]:
        collected_at = datetime.now(timezone.utc).isoformat()
        rows = []
        for item in raw:
            title = item.get("title", "")
            url = item.get("url", item.get("link", ""))
            event_hash = self._hash_event(url, title, source)

            rows.append({
                "event_hash": event_hash,
                "provider": self.provider,
                "event_type": item.get("event_type", "news"),
                "event_time": item.get("published", item.get("event_time", collected_at)),
                "trade_date": datetime.now(timezone.utc).strftime("%Y%m%d"),
                "market": item.get("market", self.market),
                "symbol": item.get("symbol", ""),
                "title": title,
                "content": item.get("content", item.get("summary", "")),
                "url": url,
                "source": source,
                "source_file": "",
                "collected_at": collected_at,
                "raw_json": json.dumps(item, ensure_ascii=False),
            })
        return rows

    @staticmethod
    def _hash_event(url: str, title: str, source: str) -> str:
        import hashlib
        key = f"{url}|{title}|{source}".encode("utf-8")
        return hashlib.sha256(key).hexdigest()[:16]

    # ------------------------------------------------------------------
    # Save
    # ------------------------------------------------------------------

    def save(self, rows: list[dict[str, Any]], task: dict[str, Any] | None = None) -> dict[str, Any]:
        if not rows:
            return {"rows_read": 0, "rows_written": 0, "tables": [], "errors": []}

        source = task.get("source", "unknown") if task else "unknown"
        now = datetime.now(timezone.utc)
        trade_date = now.strftime("%Y%m%d")

        dir_path = self._data_root / "rss" / "events" / trade_date
        dir_path.mkdir(parents=True, exist_ok=True)

        path = dir_path / f"{source}_{now.strftime('%H%M%S')}.ndjson"

        try:
            source_file = str(path.relative_to(Path.cwd()))
            with path.open("w", encoding="utf-8") as f:
                for row in rows:
                    row["source_file"] = source_file
                    f.write(json.dumps(row, ensure_ascii=False) + "\n")
            logger.info("rss save: %s → %d events", path.name, len(rows))
            return {
                "rows_read": len(rows), "rows_written": len(rows),
                "tables": ["market_events"], "errors": [],
                "source_file": source_file,
            }
        except Exception:
            logger.exception("rss save failed: %s", path)
            return {"rows_read": len(rows), "rows_written": 0, "tables": [], "errors": [str(path)]}

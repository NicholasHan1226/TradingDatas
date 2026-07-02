"""Polymarket prediction market collector — markets and price snapshots.

Writes to market_pm_markets and market_pm_prices tables.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

from ..base import BaseCollector

logger = logging.getLogger(__name__)


class PMCollector(BaseCollector):
    """Polymarket prediction market data collector.

    Sources:
        GET /markets — market listings (from Gamma API)
        GET /prices — price snapshots (from CLOB API)
    """

    name = "pm_polymarket"
    provider = "polymarket"
    market = "PredictionMarkets"
    target_tables = ["market_pm_markets", "market_pm_prices"]

    GAMMA_BASE = "https://gamma-api.polymarket.com"
    CLOB_BASE = "https://clob.polymarket.com"

    def __init__(self, config: dict[str, Any] | None = None):
        super().__init__(config)
        self._active_only = self.config.get("collection", {}).get("active_only", True)
        self._max_markets = self.config.get("collection", {}).get("max_markets_per_fetch", 500)
        self._rate_per_sec = self.config.get("rate_limit", {}).get("requests_per_sec", 5)
        self._last_call: float = 0.0
        self._session = requests.Session()

    # ------------------------------------------------------------------
    # Rate limit (simple token-bucket)
    # ------------------------------------------------------------------

    def _pm_throttle(self) -> None:
        now = time.time()
        delay = 1.0 / self._rate_per_sec
        since_last = now - self._last_call
        if since_last < delay:
            time.sleep(delay - since_last)
        self._last_call = time.time()

    # ------------------------------------------------------------------
    # Health check
    # ------------------------------------------------------------------

    def health_check(self) -> dict[str, Any]:
        try:
            self._pm_throttle()
            resp = self._session.get(f"{self.GAMMA_BASE}/markets", params={"limit": 1}, timeout=15)
            if resp.status_code == 200:
                return {"status": "available", "message": "polymarket api reachable"}
            return {"status": "degraded", "message": f"gamma returned {resp.status_code}"}
        except Exception as exc:
            return {"status": "unavailable", "message": str(exc)}

    # ------------------------------------------------------------------
    # Plan
    # ------------------------------------------------------------------

    def plan(self, context: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        return [{"type": "markets"}, {"type": "prices"}]

    # ------------------------------------------------------------------
    # Collect
    # ------------------------------------------------------------------

    def collect(self, task: dict[str, Any]) -> list[dict[str, Any]]:
        task_type = task.get("type", "markets")
        if task_type == "markets":
            return self._collect_markets()
        if task_type == "prices":
            return self._collect_prices()
        return []

    def _collect_markets(self) -> list[dict[str, Any]]:
        """Fetch market listings from Gamma API with pagination."""
        all_markets = []
        params: dict[str, Any] = {"limit": min(self._max_markets, 500)}
        if self._active_only:
            params["closed"] = "false"

        def _call_page(offset: int = 0) -> list[dict[str, Any]]:
            self._pm_throttle()
            p = {**params, "offset": offset}
            resp = self._session.get(f"{self.GAMMA_BASE}/markets", params=p, timeout=30)
            if resp.status_code == 429:
                time.sleep(5)
                resp = self._session.get(f"{self.GAMMA_BASE}/markets", params=p, timeout=30)
            resp.raise_for_status()
            return resp.json()

        max_iterations = max(self._max_markets // params.get("limit", 500) + 5, 50)
        offset = 0
        iteration = 0
        while iteration < max_iterations:
            iteration += 1
            try:
                page = self._retry_call(lambda: _call_page(offset), key=f"markets_{offset}")
                if not page:
                    break
                all_markets.extend(page)
                if len(page) < params.get("limit", 500):
                    break
                offset += len(page)
                if len(all_markets) >= self._max_markets:
                    break
            except Exception:
                logger.exception("pm markets fetch failed at offset=%d", offset)
                break
        if iteration >= max_iterations:
            logger.error("pm markets: pagination hit max_iterations=%d — possible infinite loop", max_iterations)

        return self._normalize_markets(all_markets)

    def _collect_prices(self, market_ids: list[str] | None = None) -> list[dict[str, Any]]:
        """Fetch price snapshots for active markets from CLOB API."""
        collected_at = datetime.now(timezone.utc).isoformat()
        rows: list[dict[str, Any]] = []

        # Get book for a set of token IDs (simplified: use midmarket from orderbook)
        try:
            self._pm_throttle()
            resp = self._session.get(f"{self.CLOB_BASE}/midpoint", timeout=15)
            resp.raise_for_status()
            prices_data = resp.json()

            for token_id, price in prices_data.items():
                price_hash = hashlib.sha256(
                    f"{token_id}|{collected_at}|{self.provider}".encode()
                ).hexdigest()[:16]
                rows.append({
                    "price_hash": price_hash,
                    "market_id": "",
                    "token_id": token_id,
                    "price_time": collected_at,
                    "price": float(price),
                    "provider": self.provider,
                    "source_file": "",
                    "collected_at": collected_at,
                    "raw_json": json.dumps({"token_id": token_id, "price": price}, ensure_ascii=False),
                })
        except Exception:
            logger.exception("pm prices fetch failed")

        return rows

    # ------------------------------------------------------------------
    # Normalize
    # ------------------------------------------------------------------

    def _normalize_markets(self, raw: list[dict[str, Any]]) -> list[dict[str, Any]]:
        collected_at = datetime.now(timezone.utc).isoformat()
        rows = []
        for m in raw:
            market_id = str(m.get("id", ""))
            rows.append({
                "market_id": market_id,
                "question": m.get("question", m.get("title", "")),
                "slug": m.get("slug", ""),
                "end_date": m.get("endDate", m.get("end_date", "")),
                "volume": float(m.get("volume", 0)),
                "liquidity": float(m.get("liquidity", 0)),
                "active": str(m.get("active", True)).lower(),
                "closed": str(m.get("closed", False)).lower(),
                "provider": self.provider,
                "source_file": "",
                "collected_at": collected_at,
                "raw_json": json.dumps(m, ensure_ascii=False),
            })
        return rows

    # ------------------------------------------------------------------
    # Save
    # ------------------------------------------------------------------

    def save(self, rows: list[dict[str, Any]], task: dict[str, Any] | None = None) -> dict[str, Any]:
        if not rows:
            return {"rows_read": 0, "rows_written": 0, "tables": [], "errors": []}

        task_type = task.get("type", "markets") if task else "markets"
        table = "market_pm_markets" if task_type == "markets" else "market_pm_prices"
        now = datetime.now(timezone.utc)
        trade_date = now.strftime("%Y%m%d")

        dir_path = self._data_root / "polymarket" / task_type / trade_date
        dir_path.mkdir(parents=True, exist_ok=True)

        path = dir_path / f"{now.strftime('%H%M%S')}.ndjson"

        try:
            source_file = str(path.relative_to(Path.cwd()))
            with path.open("w", encoding="utf-8") as f:
                for row in rows:
                    row["source_file"] = source_file
                    f.write(json.dumps(row, ensure_ascii=False) + "\n")
            logger.info("pm save: %s → %d rows to %s", task_type, len(rows), path.name)
            return {
                "rows_read": len(rows), "rows_written": len(rows),
                "tables": [table], "errors": [],
                "source_file": source_file,
            }
        except Exception:
            logger.exception("pm save failed: %s", path)
            return {"rows_read": len(rows), "rows_written": 0, "tables": [], "errors": [str(path)]}

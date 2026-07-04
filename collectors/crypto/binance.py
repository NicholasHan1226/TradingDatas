"""Binance crypto data collector — klines, 24h ticker.

Writes to market_bars_daily (1d interval) and market_bars_intraday (all other intervals).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

from ..base import BaseCollector

logger = logging.getLogger(__name__)


class CryptoCollector(BaseCollector):
    """Binance crypto market data collector.

    Sources:
        GET /api/v3/klines — OHLCV candles
        GET /api/v3/ticker/24hr — 24h price change statistics
    """

    name = "crypto_binance"
    provider = "binance"
    market = "Crypto"
    target_tables = ["market_bars_daily", "market_bars_intraday"]

    BASE_URL = "https://api.binance.com"
    KLINE_ENDPOINT = "/api/v3/klines"
    TICKER_ENDPOINT = "/api/v3/ticker/24hr"

    # Binance kline weight per call
    _kline_weight: float = 2.0
    _ticker_weight: float = 4.0

    def __init__(self, config: dict[str, Any] | None = None, proxy: str = ""):
        super().__init__(config)
        self._symbols = self.config.get("symbols", ["BTCUSDT", "ETHUSDT"])
        self._intervals = self.config.get("intervals", ["1d", "4h", "1h", "15m"])
        self._proxy = proxy or self.config.get("proxy", "")
        self._dry_run = self.config.get("dry_run", False)
        self._session = requests.Session()
        if self._proxy:
            self._session.proxies = {"https": self._proxy}
        self.retry_max = self.config.get("retry", {}).get("max_attempts", 3)

    # ------------------------------------------------------------------
    # Health check
    # ------------------------------------------------------------------

    def health_check(self) -> dict[str, Any]:
        try:
            resp = self._session.get(
                f"{self.BASE_URL}/api/v3/ping", timeout=10
            )
            if resp.status_code == 200:
                return {"status": "available", "message": "binance api reachable"}
            return {"status": "degraded", "message": f"ping returned {resp.status_code}"}
        except Exception as exc:
            return {"status": "unavailable", "message": str(exc)}

    # ------------------------------------------------------------------
    # Plan
    # ------------------------------------------------------------------

    def plan(self, context: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        context = context or {}
        if context.get("mode") == "ticker":
            symbols = context.get("symbols") or self._symbols
            return [{
                "api_name": "klines",
                "type": "ticker",
                "symbols": symbols,
                "symbol": "ticker",
                "interval": "24h_ticker",
            }]

        tasks = []
        intervals = context.get("intervals") or self._intervals
        symbols = context.get("symbols") or self._symbols
        for interval in intervals:
            for symbol in symbols:
                tasks.append({
                    "api_name": "klines",
                    "type": "klines",
                    "symbol": symbol,
                    "interval": interval,
                    "limit": 500,
                })
        return tasks

    # ------------------------------------------------------------------
    # Collect
    # ------------------------------------------------------------------

    def collect(self, task: dict[str, Any]) -> list[dict[str, Any]]:
        task_type = task.get("type", "klines")
        if task_type == "klines":
            return self._collect_klines(
                task["symbol"], task["interval"], task.get("limit", 500),
                task.get("start_time"), task.get("end_time"),
            )
        if task_type == "ticker":
            return self._collect_ticker(task.get("symbols", self._symbols))
        return []

    def deduplicate_batch(self, api_name: str, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Crypto bars are keyed by symbol, bar time and interval."""
        seen: dict[tuple[str, str, str], dict[str, Any]] = {}
        for row in rows:
            key = (
                str(row.get("symbol") or ""),
                str(row.get("bar_time") or row.get("trade_date") or ""),
                str(row.get("interval") or ""),
            )
            seen[key] = row
        return list(seen.values())

    def _collect_klines(
        self,
        symbol: str,
        interval: str,
        limit: int = 500,
        start_time: int | None = None,
        end_time: int | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch kline/candlestick data from Binance."""
        params: dict[str, Any] = {"symbol": symbol, "interval": interval, "limit": limit}
        if start_time:
            params["startTime"] = start_time
        if end_time:
            params["endTime"] = end_time

        def _call() -> list[dict[str, Any]]:
            resp = self._session.get(
                f"{self.BASE_URL}{self.KLINE_ENDPOINT}", params=params, timeout=30
            )
            if resp.status_code == 429:
                retry_after = int(resp.headers.get("Retry-After", "5"))
                logger.warning("binance 429, retry-after=%ds", retry_after)
                time.sleep(retry_after)
                resp = self._session.get(
                    f"{self.BASE_URL}{self.KLINE_ENDPOINT}", params=params, timeout=30
                )
            resp.raise_for_status()
            raw = resp.json()
            return self._normalize_klines(raw, symbol, interval)

        return self._retry_call(_call, key=f"klines_{symbol}_{interval}")

    def _collect_ticker(self, symbols: list[str] | None = None) -> list[dict[str, Any]]:
        symbols = symbols or self._symbols
        params = {"symbols": json.dumps(symbols, separators=(",", ":"))} if len(symbols) > 1 else {"symbol": symbols[0]}

        def _call() -> list[dict[str, Any]]:
            resp = self._session.get(
                f"{self.BASE_URL}{self.TICKER_ENDPOINT}", params=params, timeout=30
            )
            resp.raise_for_status()
            return self._normalize_tickers(resp.json())

        return self._retry_call(_call, key="ticker")

    # ------------------------------------------------------------------
    # Normalize
    # ------------------------------------------------------------------

    def _normalize_klines(self, raw: list[list[Any]], symbol: str, interval: str) -> list[dict[str, Any]]:
        """Convert Binance kline array to SharedSignals row dicts."""
        rows = []
        collected_at = datetime.now(timezone.utc).isoformat()
        is_daily = interval == "1d"

        for k in raw:
            open_time_ms = k[0]
            bar_time = datetime.fromtimestamp(open_time_ms / 1000, tz=timezone.utc)
            trade_date = bar_time.strftime("%Y%m%d")
            bar_time_str = bar_time.isoformat()

            row = {
                "market": "Crypto",
                "symbol": symbol,
                "trade_date": trade_date,
                "interval": interval,
                "bar_time": bar_time_str,
                "open": float(k[1]),
                "high": float(k[2]),
                "low": float(k[3]),
                "close": float(k[4]),
                "volume": float(k[5]),
                "amount": float(k[7]) if len(k) > 7 else 0.0,  # quote asset volume
                "provider": self.provider,
                "source_file": "",
                "collected_at": collected_at,
                "raw_json": json.dumps(
                    {"open_time": open_time_ms, "close_time": k[6], "trades": k[8]},
                    ensure_ascii=False,
                ),
            }
            rows.append(row)
        return rows

    def _normalize_tickers(self, raw: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Normalize 24h ticker to bar-like rows."""
        rows = []
        collected_at = datetime.now(timezone.utc).isoformat()
        trade_date = datetime.now(timezone.utc).strftime("%Y%m%d")

        for t in raw:
            symbol = t.get("symbol", "")
            row = {
                "market": "Crypto",
                "symbol": symbol,
                "trade_date": trade_date,
                "interval": "24h_ticker",
                "bar_time": collected_at,
                "open": float(t.get("openPrice", 0)),
                "high": float(t.get("highPrice", 0)),
                "low": float(t.get("lowPrice", 0)),
                "close": float(t.get("lastPrice", 0)),
                "volume": float(t.get("volume", 0)),
                "amount": float(t.get("quoteVolume", 0)),
                "provider": self.provider,
                "source_file": "",
                "collected_at": collected_at,
                "raw_json": json.dumps(t, ensure_ascii=False),
            }
            rows.append(row)
        return rows

    # ------------------------------------------------------------------
    # Save
    # ------------------------------------------------------------------

    def save(self, rows: list[dict[str, Any]], task: dict[str, Any] | None = None) -> dict[str, Any]:
        """Save klines to date-partitioned CSV staging. SQLite write delegated to writer/orchestrator."""
        if not rows:
            return {"rows_read": 0, "rows_written": 0, "tables": [], "errors": []}

        if self._dry_run:
            logger.info("dry_run: would save %d rows", len(rows))
            return {"rows_read": len(rows), "rows_written": 0, "tables": self.target_tables, "errors": []}

        interval = task.get("interval", "unknown") if task else "unknown"
        symbol = task.get("symbol", "unknown") if task else "unknown"
        now = datetime.now(timezone.utc)
        trade_date = now.strftime("%Y%m%d")
        ts = now.strftime("%H%M%S")

        dir_path = self._data_root / "crypto" / "binance" / interval / trade_date
        dir_path.mkdir(parents=True, exist_ok=True)

        fname = f"{symbol}_{ts}.ndjson"
        path = dir_path / fname

        try:
            try:
                source_file = str(path.relative_to(Path.cwd()))
            except ValueError:
                source_file = str(path)
            with path.open("w", encoding="utf-8") as f:
                for row in rows:
                    row["source_file"] = source_file
                    f.write(json.dumps(row, ensure_ascii=False) + "\n")
            logger.info("binance save: %s → %d rows", path.name, len(rows))
            return {
                "rows_read": len(rows), "rows_written": len(rows),
                "tables": self.target_tables, "errors": [],
                "source_file": source_file,
            }
        except Exception:
            logger.exception("binance save failed: %s", path)
            return {"rows_read": len(rows), "rows_written": 0, "tables": [], "errors": [str(path)]}

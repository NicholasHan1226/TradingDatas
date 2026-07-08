"""Binance crypto data collector — klines, 24h ticker.

Writes to market_bars_daily (1d interval) and market_bars_intraday (all other intervals).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import sqlite3
import time
from datetime import datetime, timezone
from typing import Any

import requests

from runtime_paths import marketdata_sqlite_path
from ..base import BaseCollector

logger = logging.getLogger(__name__)


def parse_proxy_list(value: str | list[str] | None) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [item.strip() for item in str(value or "").split(",") if item.strip()]


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
        self._proxies = parse_proxy_list(proxy or self.config.get("proxies") or self.config.get("proxy", ""))
        self._dry_run = self.config.get("dry_run", False)
        self._db_path = str(self.config.get("db") or marketdata_sqlite_path())
        self._session = requests.Session()
        self.retry_max = self.config.get("retry", {}).get("max_attempts", 3)

    def _should_retry(self, exc: BaseException) -> bool:
        if isinstance(exc, requests.RequestException):
            return True
        return super()._should_retry(exc)

    def _get(self, url: str, *, timeout: int, params: dict[str, Any] | None = None) -> requests.Response:
        errors: list[str] = []
        routes = self._proxies or [""]
        for idx, proxy in enumerate(routes, start=1):
            try:
                request_kwargs: dict[str, Any] = {"params": params, "timeout": timeout}
                if proxy:
                    request_kwargs["proxies"] = {"http": proxy, "https": proxy}
                return self._session.get(url, **request_kwargs)
            except requests.RequestException as exc:
                route = f"proxy#{idx}" if proxy else "direct"
                errors.append(f"{route}: {exc}")
                continue
        raise requests.ConnectionError(f"all binance routes failed: {errors[-3:]}")

    # ------------------------------------------------------------------
    # Health check
    # ------------------------------------------------------------------

    def health_check(self) -> dict[str, Any]:
        try:
            def _ping() -> dict[str, Any]:
                resp = self._get(f"{self.BASE_URL}/api/v3/ping", timeout=10)
                if resp.status_code == 200:
                    return {"status": "available", "message": "binance api reachable"}
                if resp.status_code == 429 or resp.status_code >= 500:
                    resp.raise_for_status()
                return {"status": "degraded", "message": f"ping returned {resp.status_code}"}

            return self._retry_call(_ping, key="binance_health")
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
            resp = self._get(f"{self.BASE_URL}{self.KLINE_ENDPOINT}", params=params, timeout=30)
            if resp.status_code == 429:
                retry_after = int(resp.headers.get("Retry-After", "5"))
                logger.warning("binance 429, retry-after=%ds", retry_after)
                time.sleep(retry_after)
                resp = self._get(f"{self.BASE_URL}{self.KLINE_ENDPOINT}", params=params, timeout=30)
            resp.raise_for_status()
            raw = resp.json()
            return self._normalize_klines(raw, symbol, interval)

        return self._retry_call(_call, key=f"klines_{symbol}_{interval}")

    def _collect_ticker(self, symbols: list[str] | None = None) -> list[dict[str, Any]]:
        symbols = symbols or self._symbols
        params = {"symbols": json.dumps(symbols, separators=(",", ":"))} if len(symbols) > 1 else {"symbol": symbols[0]}

        def _call() -> list[dict[str, Any]]:
            resp = self._get(f"{self.BASE_URL}{self.TICKER_ENDPOINT}", params=params, timeout=30)
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
        """Write Binance rows directly into the SharedSignals SQLite read model."""
        if not rows:
            return {"rows_read": 0, "rows_written": 0, "tables": [], "errors": []}

        if self._dry_run:
            logger.info("dry_run: would save %d rows", len(rows))
            return {"rows_read": len(rows), "rows_written": 0, "tables": self.target_tables, "errors": []}

        daily_rows: list[tuple[Any, ...]] = []
        intraday_rows: list[tuple[Any, ...]] = []
        source_file = "binance_direct"
        for row in rows:
            payload = dict(row)
            payload["source_file"] = source_file
            if str(payload.get("interval") or "") == "1d":
                daily_rows.append(
                    (
                        payload.get("market") or self.market,
                        payload.get("symbol") or "",
                        payload.get("trade_date") or "",
                        payload.get("open"),
                        payload.get("high"),
                        payload.get("low"),
                        payload.get("close"),
                        payload.get("volume"),
                        payload.get("amount"),
                        payload.get("provider") or self.provider,
                        payload.get("source_file") or source_file,
                        payload.get("collected_at") or datetime.now(timezone.utc).isoformat(),
                        payload.get("raw_json") if isinstance(payload.get("raw_json"), str) else json.dumps(payload, ensure_ascii=False),
                    )
                )
            else:
                intraday_rows.append(
                    (
                        payload.get("market") or self.market,
                        payload.get("symbol") or "",
                        payload.get("bar_time") or payload.get("collected_at") or datetime.now(timezone.utc).isoformat(),
                        payload.get("trade_date") or "",
                        payload.get("interval") or "",
                        payload.get("open"),
                        payload.get("high"),
                        payload.get("low"),
                        payload.get("close"),
                        payload.get("volume"),
                        payload.get("amount"),
                        None,
                        None,
                        None,
                        None,
                        "",
                        "",
                        payload.get("provider") or self.provider,
                        payload.get("source_file") or source_file,
                        payload.get("collected_at") or datetime.now(timezone.utc).isoformat(),
                        payload.get("raw_json") if isinstance(payload.get("raw_json"), str) else json.dumps(payload, ensure_ascii=False),
                    )
                )

        conn: sqlite3.Connection | None = None
        try:
            conn = sqlite3.connect(self._db_path, timeout=30)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=30000")
            if daily_rows:
                conn.executemany(
                    """
                    INSERT OR REPLACE INTO market_bars_daily
                    (market, symbol, trade_date, open, high, low, close, volume, amount, provider, source_file, collected_at, raw_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    daily_rows,
                )
            if intraday_rows:
                conn.executemany(
                    """
                    INSERT OR REPLACE INTO market_bars_intraday
                    (market, symbol, bar_time, trade_date, interval, open, high, low, close, volume, amount,
                     bid_price, ask_price, bid_size, ask_size, last_trade_date, expiry_date, provider, source_file, collected_at, raw_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    intraday_rows,
                )
            conn.commit()
        except Exception:
            if conn is not None:
                conn.rollback()
            logger.exception("binance sqlite save failed")
            return {"rows_read": len(rows), "rows_written": 0, "tables": [], "errors": [self._db_path]}
        finally:
            if conn is not None:
                conn.close()

        tables = []
        if daily_rows:
            tables.append("market_bars_daily")
        if intraday_rows:
            tables.append("market_bars_intraday")
        return {
            "rows_read": len(rows),
            "rows_written": len(daily_rows) + len(intraday_rows),
            "tables": tables,
            "errors": [],
            "source_file": source_file,
        }

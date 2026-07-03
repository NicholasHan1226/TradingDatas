#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Alpaca Market Data — real-time quotes & historical bars.

Complements/Replaces Tushare us_daily for US stock data during market hours.
Uses Alpaca's free IEX data feed.

Capabilities:
  - get_latest_quote(symbol) → {bid, ask, mid, timestamp}
  - get_latest_trade(symbol) → {price, size, timestamp}
  - get_bars(symbols, timeframe, start, end) → historical OHLCV
  - get_snapshot(symbols) → multi-symbol snapshot (latest bar)

Free IEX data: 15-min delayed for non-Alpaca-brokerage accounts.
Alpaca paper accounts get real-time IEX at no cost.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import (
    StockBarsRequest, StockLatestQuoteRequest,
    StockLatestTradeRequest, StockSnapshotRequest,
)
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit

from us_common import (
    MARKET_DIR, safe_float, now_iso, today_ymd,
    read_csv_rows, write_csv_rows,
)
from us_alpaca_auth import read_alpaca_config, is_configured

# ---- CSV output paths --------------------------------------------------------
QUOTES_PATH = MARKET_DIR / "alpaca_quotes.csv"
BARS_PATH = MARKET_DIR / "alpaca_bars_1d.csv"

# ---- TimeFrame helpers --------------------------------------------------------
TIMEFRAME_MAP: dict[str, TimeFrame] = {
    "1min": TimeFrame(1, TimeFrameUnit.Minute),
    "5min": TimeFrame(5, TimeFrameUnit.Minute),
    "15min": TimeFrame(15, TimeFrameUnit.Minute),
    "30min": TimeFrame(30, TimeFrameUnit.Minute),
    "1hour": TimeFrame(1, TimeFrameUnit.Hour),
    "1day": TimeFrame(1, TimeFrameUnit.Day),
}


class AlpacaMarketData:
    """Real-time + historical US market data via Alpaca."""

    def __init__(
        self, api_key: str | None = None, secret_key: str | None = None
    ) -> None:
        self._configured = False
        self._client = None
        try:
            if api_key and secret_key:
                creds = {"api_key": api_key, "secret_key": secret_key}
            else:
                creds = read_alpaca_config()
            self._client = StockHistoricalDataClient(
                api_key=creds["api_key"],
                secret_key=creds["secret_key"],
            )
            self._configured = True
        except (RuntimeError, Exception):
            pass
        MARKET_DIR.mkdir(parents=True, exist_ok=True)

    def _require_config(self) -> None:
        if not self._configured:
            raise RuntimeError(
                "Alpaca paper disabled or not configured. Set US_ALPACA_PAPER_ENABLED=1 "
                "with ALPACA_PAPER_API_KEY + ALPACA_PAPER_SECRET_KEY only for isolated paper tests."
            )

    # ------------------------------------------------------------------
    # Latest quote / trade (real-time snapshot)
    # ------------------------------------------------------------------

    def get_latest_quote(self, symbols: list[str]) -> dict[str, dict[str, Any]]:
        """Get latest bid/ask for one or more symbols."""
        self._require_config()
        try:
            req = StockLatestQuoteRequest(symbol_or_symbols=[s.upper() for s in symbols])
            result = self._client.get_stock_latest_quote(req)
            quotes: dict[str, dict] = {}
            for sym in symbols:
                quote = result.get(sym.upper())
                if quote:
                    quotes[sym.upper()] = {
                        "bid": safe_float(quote.bid_price),
                        "ask": safe_float(quote.ask_price),
                        "bid_size": safe_float(quote.bid_size),
                        "ask_size": safe_float(quote.ask_size),
                        "mid": round((safe_float(quote.bid_price) + safe_float(quote.ask_price)) / 2, 2),
                        "spread": round(safe_float(quote.ask_price) - safe_float(quote.bid_price), 2),
                        "timestamp": str(quote.timestamp),
                    }
            return quotes
        except Exception as e:
            return {"error": str(e)}

    def get_latest_trade(self, symbols: list[str]) -> dict[str, dict[str, Any]]:
        """Get latest trade price for one or more symbols."""
        self._require_config()
        try:
            req = StockLatestTradeRequest(symbol_or_symbols=[s.upper() for s in symbols])
            result = self._client.get_stock_latest_trade(req)
            trades: dict[str, dict] = {}
            for sym in symbols:
                trade = result.get(sym.upper())
                if trade:
                    trades[sym.upper()] = {
                        "price": safe_float(trade.price),
                        "size": safe_float(trade.size),
                        "timestamp": str(trade.timestamp),
                    }
            return trades
        except Exception as e:
            return {"error": str(e)}

    def get_snapshot(self, symbols: list[str]) -> dict[str, dict[str, Any]]:
        """Multi-symbol snapshot: latest OHLCV bar."""
        self._require_config()
        try:
            req = StockSnapshotRequest(symbol_or_symbols=[s.upper() for s in symbols])
            result = self._client.get_stock_snapshot(req)
            snapshots: dict[str, dict] = {}
            for sym in symbols:
                snap = result.get(sym.upper())
                if snap:
                    snapshots[sym.upper()] = {
                        "price": safe_float(snap.latest_trade.price) if snap.latest_trade else 0,
                        "bid": safe_float(snap.latest_quote.bid_price) if snap.latest_quote else 0,
                        "ask": safe_float(snap.latest_quote.ask_price) if snap.latest_quote else 0,
                        "daily_bar": {
                            "open": safe_float(snap.daily_bar.open) if snap.daily_bar else 0,
                            "high": safe_float(snap.daily_bar.high) if snap.daily_bar else 0,
                            "low": safe_float(snap.daily_bar.low) if snap.daily_bar else 0,
                            "close": safe_float(snap.daily_bar.close) if snap.daily_bar else 0,
                            "volume": safe_float(snap.daily_bar.volume) if snap.daily_bar else 0,
                        },
                    }
            return snapshots
        except Exception as e:
            return {"error": str(e)}

    # ------------------------------------------------------------------
    # Historical bars
    # ------------------------------------------------------------------

    def get_bars(
        self,
        symbols: list[str],
        timeframe: str = "1day",
        start: str | None = None,
        end: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Get historical OHLCV bars.

        Args:
            symbols: list of tickers
            timeframe: 1min/5min/15min/30min/1hour/1day
            start: ISO date string (YYYY-MM-DD)
            end: ISO date string
            limit: max bars per symbol (default 100)
        """
        tf = TIMEFRAME_MAP.get(timeframe, TimeFrame(1, TimeFrameUnit.Day))
        if not start:
            start = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%d")
        if not end:
            end = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        self._require_config()
        try:
            req = StockBarsRequest(
                symbol_or_symbols=[s.upper() for s in symbols],
                timeframe=tf,
                start=start,
                end=end,
                limit=limit,
            )
            result = self._client.get_stock_bars(req)
            rows: list[dict[str, Any]] = []
            for sym in symbols:
                bars = result.data.get(sym.upper(), [])
                for bar in bars:
                    rows.append({
                        "symbol": sym.upper(),
                        "timestamp": str(bar.timestamp),
                        "open": safe_float(bar.open),
                        "high": safe_float(bar.high),
                        "low": safe_float(bar.low),
                        "close": safe_float(bar.close),
                        "volume": safe_float(bar.volume),
                        "trade_count": getattr(bar, "trade_count", 0),
                        "vwap": safe_float(getattr(bar, "vwap", 0)),
                    })
            return rows
        except Exception as e:
            return [{"error": str(e)}]

    # ------------------------------------------------------------------
    # Collect → local CSV (same pattern as us_market_data.py)
    # ------------------------------------------------------------------

    def collect_daily_bars(
        self,
        symbols: list[str],
        days: int = 30,
    ) -> int:
        """Fetch N days of daily bars and write to alpaca_bars_1d.csv."""
        end = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        start = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")

        rows = self.get_bars(symbols, timeframe="1day", start=start, end=end, limit=days + 5)
        if rows and "error" not in str(rows[0]):
            write_csv_rows(BARS_PATH, rows, append=False)
        return len(rows)

    def collect_snapshots(self, symbols: list[str]) -> int:
        """Snapshot current quotes and write to alpaca_quotes.csv."""
        now = now_iso()
        snapshots = self.get_snapshot(symbols)
        if "error" in snapshots:
            return 0

        rows: list[dict[str, Any]] = []
        for sym, snap in snapshots.items():
            rows.append({
                "symbol": sym,
                "source_time": now,
                "source": "alpaca_snapshot",
                "status": "fresh",
                "capital_layer": "shadow",
                "is_real_money": "N",
                "workflow_result_path": "",
                "price": snap["price"],
                "bid": snap["bid"],
                "ask": snap["ask"],
                "open": snap["daily_bar"]["open"],
                "high": snap["daily_bar"]["high"],
                "low": snap["daily_bar"]["low"],
                "close": snap["daily_bar"]["close"],
                "volume": snap["daily_bar"]["volume"],
            })
        write_csv_rows(QUOTES_PATH, rows, append=True)
        return len(rows)


# =============================================================================
# CLI
# =============================================================================


def main() -> int:
    import argparse, json

    parser = argparse.ArgumentParser(description="Alpaca Market Data")
    parser.add_argument("--snapshot", action="store_true", help="Multi-symbol snapshot")
    parser.add_argument("--bars", action="store_true", help="Historical daily bars")
    parser.add_argument("--symbols", type=str, default="AAPL,MSFT,SPY",
                        help="Comma-separated symbols")
    parser.add_argument("--days", type=int, default=30, help="Days of history")
    parser.add_argument("--json", action="store_true", help="JSON output")
    args = parser.parse_args()

    if not is_configured():
        print(json.dumps({"error": "Alpaca not configured"}))
        return 1

    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    md = AlpacaMarketData()

    if args.snapshot:
        result = md.get_snapshot(symbols)
    elif args.bars:
        result = md.get_bars(symbols, timeframe="1day", limit=args.days)
    else:
        result = md.get_snapshot(symbols)

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

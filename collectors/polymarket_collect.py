#!/usr/bin/env python3
"""Polymarket collector for the SharedSignals read model.

This script is intentionally small and cron-friendly: fetch active Gamma
markets, derive price snapshots from the market payload, and write both tables
into the unified SQLite read model. TradingAgent and MarketGraph consume the
result through SharedSignals API/read model only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
import urllib.request
from datetime import datetime, timezone
from typing import Any, Iterable


DEFAULT_DB = "/opt/investment/MarketGraphRuntime/read_model/marketdata.sqlite"
GAMMA = "https://gamma-api.polymarket.com"
DEFAULT_PROXY = "http://127.0.0.1:7890"
PROVIDER = "polymarket"
SOURCE = "polymarket_gamma"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def coerce_float(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, ""):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def json_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return []
        return parsed if isinstance(parsed, list) else []
    return []


def open_json(url: str, *, proxy: str, timeout: int = 25) -> Any:
    proxies = [proxy, ""] if proxy else [""]
    last_error: Exception | None = None
    for item in proxies:
        try:
            handler = urllib.request.ProxyHandler({"http": item, "https": item}) if item else urllib.request.ProxyHandler({})
            opener = urllib.request.build_opener(handler)
            req = urllib.request.Request(url, headers={"User-Agent": "SharedSignals/1.0"})
            return json.loads(opener.open(req, timeout=timeout).read())
        except Exception as exc:  # pragma: no cover - exercised by production smoke
            last_error = exc
            continue
    raise RuntimeError(f"polymarket fetch failed: {last_error}")


def fetch_markets(limit: int, *, proxy: str) -> list[dict[str, Any]]:
    data = open_json(f"{GAMMA}/markets?closed=false&limit={int(limit)}", proxy=proxy)
    if not isinstance(data, list):
        raise RuntimeError("polymarket gamma returned non-list payload")
    return [row for row in data if isinstance(row, dict)]


def market_row(market: dict[str, Any], collected_at: str) -> tuple[Any, ...]:
    return (
        str(market.get("id") or market.get("conditionId") or ""),
        str(market.get("question") or market.get("title") or "")[:1000],
        str(market.get("slug") or ""),
        str(market.get("endDate") or market.get("end_date") or ""),
        coerce_float(market.get("volume") or market.get("volumeNum")),
        coerce_float(market.get("liquidity") or market.get("liquidityNum") or market.get("liquidityClob")),
        str(bool(market.get("active", True))).lower(),
        str(bool(market.get("closed", False))).lower(),
        PROVIDER,
        SOURCE,
        collected_at,
        json.dumps(market, ensure_ascii=False),
    )


def price_rows(market: dict[str, Any], collected_at: str) -> Iterable[tuple[Any, ...]]:
    market_id = str(market.get("id") or market.get("conditionId") or "")
    token_ids = [str(item) for item in json_list(market.get("clobTokenIds")) if str(item)]
    prices = json_list(market.get("outcomePrices"))
    outcomes = json_list(market.get("outcomes"))
    if not token_ids:
        return

    derived_prices: list[float] = []
    for idx, token_id in enumerate(token_ids):
        price = coerce_float(prices[idx], -1.0) if idx < len(prices) else -1.0
        if price < 0 and idx == 0:
            bid = coerce_float(market.get("bestBid"), -1.0)
            ask = coerce_float(market.get("bestAsk"), -1.0)
            if bid >= 0 and ask >= 0:
                price = (bid + ask) / 2.0
            else:
                price = coerce_float(market.get("lastTradePrice"), -1.0)
        if price < 0 and len(token_ids) == 2 and idx == 1 and derived_prices:
            price = 1.0 - derived_prices[0]
        if price < 0:
            continue

        price = max(0.0, min(1.0, price))
        derived_prices.append(price)
        raw = {
            "source": SOURCE,
            "market_id": market_id,
            "token_id": token_id,
            "outcome": outcomes[idx] if idx < len(outcomes) else "",
            "best_bid": market.get("bestBid"),
            "best_ask": market.get("bestAsk"),
            "last_trade_price": market.get("lastTradePrice"),
            "gamma_updated_at": market.get("updatedAt"),
        }
        price_hash = hashlib.sha256(f"{market_id}|{token_id}|{collected_at}|{SOURCE}".encode()).hexdigest()
        yield (
            price_hash,
            market_id,
            token_id,
            collected_at,
            price,
            PROVIDER,
            SOURCE,
            collected_at,
            json.dumps(raw, ensure_ascii=False),
        )


def write_rows(db_path: str, markets: list[dict[str, Any]], *, collected_at: str, dry_run: bool = False) -> dict[str, Any]:
    market_rows = [market_row(row, collected_at) for row in markets]
    price_rows_list = [price for row in markets for price in price_rows(row, collected_at)]
    if dry_run:
        return {"markets": len(market_rows), "prices": len(price_rows_list), "status": "dry_run"}

    run_id = f"polymarket_gamma_{collected_at.replace(':', '').replace('-', '').replace('+', 'Z')}"
    conn = sqlite3.connect(db_path, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.executemany(
            """
            INSERT OR REPLACE INTO market_pm_markets
            (market_id, question, slug, end_date, volume, liquidity, active, closed, provider, source_file, collected_at, raw_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            market_rows,
        )
        conn.executemany(
            """
            INSERT OR REPLACE INTO market_pm_prices
            (price_hash, market_id, token_id, price_time, price, provider, source_file, collected_at, raw_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            price_rows_list,
        )
        conn.execute(
            """
            INSERT OR REPLACE INTO market_ingest_runs
            (run_id, started_at, finished_at, status, source, rows_read, rows_written, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                collected_at,
                utc_now(),
                "success" if market_rows else "empty",
                SOURCE,
                len(markets),
                len(market_rows) + len(price_rows_list),
                json.dumps({"markets": len(market_rows), "prices": len(price_rows_list)}, ensure_ascii=False),
            ),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return {"markets": len(market_rows), "prices": len(price_rows_list), "status": "success" if market_rows else "empty"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Collect Polymarket markets/prices into SharedSignals read model")
    parser.add_argument("--db", default=os.getenv("SHAREDSIGNALS_MARKETDATA_DB", DEFAULT_DB))
    parser.add_argument("--limit", type=int, default=int(os.getenv("POLYMARKET_MAX_MARKETS", "200")))
    parser.add_argument("--proxy", default=os.getenv("POLYMARKET_HTTP_PROXY", DEFAULT_PROXY))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    collected_at = utc_now()
    try:
        markets = fetch_markets(args.limit, proxy=args.proxy)
        result = write_rows(args.db, markets, collected_at=collected_at, dry_run=args.dry_run)
    except Exception as exc:
        print(f"PM: failed at {collected_at}: {exc}", file=sys.stderr)
        return 1
    print(f"PM: {result['markets']} markets, {result['prices']} prices, status={result['status']} at {collected_at}")
    return 0 if result["markets"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Collect China futures 5-minute bars into the SharedSignals read model."""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from collectors.tushare.collector import TushareCollector  # noqa: E402
from storage.csv_bridge import DEFAULT_SQLITE_PATH, ingest_csv_to_sqlite  # noqa: E402

API_NAME = "rt_fut_min"
DEFAULT_PRODUCTS = ("rb", "cu", "i", "m", "if", "ih", "ic", "im")
DEFAULT_FREQ = "5MIN"
_DATE_RE = re.compile(r"^\d{8}$")

logger = logging.getLogger(__name__)


def default_trade_date() -> str:
    return datetime.now().strftime("%Y%m%d")


def normalize_product(symbol: str) -> str:
    raw = str(symbol or "").strip().split(".", 1)[0].lower()
    product = []
    for char in raw:
        if char.isalpha():
            product.append(char)
        else:
            break
    return "".join(product)


def parse_symbols(raw: str) -> list[str]:
    return [item.strip() for item in str(raw or "").split(",") if item.strip()]


def _sqlite_rows(db_path: Path, sql: str, params: tuple[Any, ...]) -> list[str]:
    if not db_path.exists():
        return []
    conn: sqlite3.Connection | None = None
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        rows = conn.execute(sql, params).fetchall()
    except Exception:
        logger.warning("failed to read futures universe from %s", db_path, exc_info=True)
        return []
    finally:
        if conn is not None:
            conn.close()
    return [str(row[0]) for row in rows if row and row[0]]


def load_recent_futures_symbols(
    db_path: Path,
    *,
    trade_date: str,
    products: set[str],
    max_symbols: int,
) -> list[str]:
    """Prefer contracts with latest daily bars, then fall back to assets."""

    symbols = _sqlite_rows(
        db_path,
        """
        SELECT DISTINCT symbol
        FROM market_bars_daily
        WHERE market='Futures'
        AND trade_date=(
            SELECT MAX(trade_date)
            FROM market_bars_daily
            WHERE market='Futures' AND trade_date<=?
        )
        ORDER BY symbol ASC
        """,
        (trade_date,),
    )
    if not symbols:
        symbols = _sqlite_rows(
            db_path,
            "SELECT symbol FROM market_assets WHERE market='Futures' ORDER BY symbol ASC",
            (),
        )

    selected: list[str] = []
    seen: set[str] = set()
    for symbol in symbols:
        key = symbol.lower()
        if key in seen:
            continue
        product = normalize_product(symbol)
        if products and product not in products:
            continue
        selected.append(symbol)
        seen.add(key)
        if len(selected) >= max_symbols:
            break
    return selected


def build_params(symbols: list[str], *, freq: str) -> dict[str, Any]:
    return {"ts_code": ",".join(symbols), "freq": freq}


def run_collection(
    *,
    trade_date: str,
    symbols: list[str],
    freq: str,
    dry_run: bool,
    sqlite_bridge_enabled: bool,
    sqlite_db_path: Path,
) -> dict[str, Any]:
    if not _DATE_RE.match(trade_date):
        raise ValueError(f"invalid trade_date {trade_date!r}, expected YYYYMMDD")
    if not symbols:
        raise ValueError("no futures symbols selected for 5-minute collection")
    params = build_params(symbols, freq=freq)
    summary: dict[str, Any] = {
        "api": API_NAME,
        "trade_date": trade_date,
        "freq": freq,
        "symbols": symbols,
        "symbol_count": len(symbols),
        "dry_run": dry_run,
        "rows": 0,
        "sqlite_bridge_rows": 0,
        "bridge_status": "disabled" if not sqlite_bridge_enabled else "empty",
        "state": "dry_run" if dry_run else "pending",
    }
    if dry_run:
        summary["params"] = params
        return summary

    collector = TushareCollector()
    rows = collector.collect(API_NAME, params, fields="")
    summary["rows"] = len(rows)
    if getattr(collector, "last_collect_failed", False):
        summary["state"] = "failed"
        summary["error"] = collector.last_collect_error
        return summary
    if not rows:
        summary["state"] = "empty"
        return summary
    path = collector.save(API_NAME, rows, trade_date, filename=f"{API_NAME}_{trade_date}_{freq.lower()}")
    summary["csv_path"] = str(path) if path else ""
    if sqlite_bridge_enabled and path is not None:
        summary["sqlite_bridge_rows"] = ingest_csv_to_sqlite(sqlite_db_path, "market_bars_intraday", path)
        summary["bridge_status"] = "ok"
    summary["state"] = "ok"
    return summary


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Collect CN futures 5-minute bars via Tushare rt_fut_min.")
    parser.add_argument("--trade-date", default=default_trade_date(), help="Trade date as YYYYMMDD, default today.")
    parser.add_argument("--symbols", default=os.environ.get("CN_FUTURES_5MIN_SYMBOLS", ""), help="Comma-separated futures contracts.")
    parser.add_argument("--products", default=os.environ.get("CN_FUTURES_5MIN_PRODUCTS", ",".join(DEFAULT_PRODUCTS)), help="Comma-separated product prefixes used when symbols are auto-selected.")
    parser.add_argument("--max-symbols", type=int, default=int(os.environ.get("CN_FUTURES_5MIN_MAX_SYMBOLS", "30")), help="Max auto-selected futures contracts.")
    parser.add_argument("--freq", default=os.environ.get("CN_FUTURES_5MIN_FREQ", DEFAULT_FREQ), help="Tushare rt_fut_min freq, default 5MIN.")
    parser.add_argument("--sqlite-db", type=Path, default=DEFAULT_SQLITE_PATH, help="SQLite read model path.")
    parser.add_argument("--no-sqlite-bridge", action="store_true", help="Collect CSV only.")
    parser.add_argument("--dry-run", action="store_true", help="Print selected symbols and params without calling Tushare.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        symbols = parse_symbols(args.symbols)
        products = {item.lower() for item in parse_symbols(args.products)}
        if not symbols:
            symbols = load_recent_futures_symbols(
                args.sqlite_db,
                trade_date=args.trade_date,
                products=products,
                max_symbols=max(1, int(args.max_symbols)),
            )
        summary = run_collection(
            trade_date=args.trade_date,
            symbols=symbols,
            freq=str(args.freq).upper(),
            dry_run=bool(args.dry_run),
            sqlite_bridge_enabled=not args.no_sqlite_bridge,
            sqlite_db_path=args.sqlite_db,
        )
    except Exception as exc:
        logger.error("%s", exc)
        print(json.dumps({"api": API_NAME, "state": "failed", "error": str(exc)}, ensure_ascii=False, sort_keys=True))
        return 2
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0 if summary.get("state") in {"ok", "empty", "dry_run"} else 2


if __name__ == "__main__":
    raise SystemExit(main())

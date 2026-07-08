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
from collectors.tushare.tushare_common import rows_to_dicts, tushare_data  # noqa: E402
from env_bootstrap import bootstrap_sharedsignals_env  # noqa: E402
from storage.read_model_store import DEFAULT_SQLITE_PATH, ingest_rows_to_sqlite  # noqa: E402

API_NAME = "rt_fut_min"
SINA_PROVIDER = "sina_futures_minute"
TUSHARE_PROVIDER = "tushare_rt_fut_min"
DEFAULT_PRODUCTS = ("rb", "cu", "i", "m", "if", "ih", "ic", "im")
DEFAULT_FREQ = "5MIN"
DEFAULT_SINA_MAX_ROWS_PER_SYMBOL = 240
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

    grouped: dict[str, list[str]] = {}
    seen: set[str] = set()
    for symbol in symbols:
        key = symbol.lower()
        if key in seen:
            continue
        product = normalize_product(symbol)
        if products and product not in products:
            continue
        seen.add(key)
        grouped.setdefault(product, []).append(symbol)

    selected: list[str] = []
    product_order = sorted(grouped)
    cursor = 0
    while len(selected) < max_symbols and product_order:
        added = False
        for product in product_order:
            candidates = grouped.get(product) or []
            if cursor < len(candidates):
                selected.append(candidates[cursor])
                added = True
                if len(selected) >= max_symbols:
                    break
        if not added:
            break
        cursor += 1
    return selected


def build_params(symbols: list[str], *, freq: str) -> dict[str, Any]:
    return {"ts_code": ",".join(symbols), "freq": freq}


def collect_rt_fut_min_rows(params: dict[str, Any], *, fields: str = "") -> list[dict[str, Any]]:
    """Collect rt_fut_min rows while preserving provider error details."""

    bootstrap_sharedsignals_env()
    data = tushare_data(API_NAME, params, fields, strict=False)
    code = data.get("code")
    error = str(data.get("error") or "").strip()
    if error or code not in (None, "", 0, "0"):
        code_text = "unknown" if code in (None, "") else str(code)
        detail = error or "empty provider error message"
        raise RuntimeError(f"Tushare {API_NAME} failed code={code_text}: {detail}")
    return rows_to_dicts(data)


def _sina_symbol(symbol: str) -> str:
    root = str(symbol or "").strip().split(".", 1)[0].upper()
    if not root or not any(char.isdigit() for char in root):
        return ""
    return root


def collect_sina_futures_minute_rows(
    symbols: list[str],
    *,
    period: str = "5",
    max_rows_per_symbol: int = DEFAULT_SINA_MAX_ROWS_PER_SYMBOL,
) -> list[dict[str, Any]]:
    """Collect CN futures minute rows from Sina through the SharedSignals owner."""

    try:
        import akshare as ak  # type: ignore
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"Sina futures provider unavailable: {exc}") from exc

    rows: list[dict[str, Any]] = []
    limit = max(1, int(max_rows_per_symbol))
    for symbol in symbols:
        sina_symbol = _sina_symbol(symbol)
        if not sina_symbol:
            continue
        try:
            frame = ak.futures_zh_minute_sina(symbol=sina_symbol, period=str(period))
        except Exception as exc:  # noqa: BLE001
            logger.warning("Sina futures minute collection failed for %s: %s", symbol, exc)
            continue
        if frame is None or getattr(frame, "empty", True):
            continue
        for item in frame.tail(limit).to_dict("records"):
            bar_time = str(item.get("datetime") or item.get("time") or "").strip()
            if not bar_time:
                continue
            rows.append(
                {
                    "ts_code": symbol,
                    "code": symbol,
                    "time": bar_time,
                    "open": item.get("open"),
                    "high": item.get("high"),
                    "low": item.get("low"),
                    "close": item.get("close"),
                    "vol": item.get("volume") or item.get("vol"),
                    "hold": item.get("hold"),
                    "provider": SINA_PROVIDER,
                }
            )
    return rows


def run_collection(
    *,
    trade_date: str,
    symbols: list[str],
    freq: str,
    provider: str = TUSHARE_PROVIDER,
    dry_run: bool,
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
        "provider": provider,
        "symbols": symbols,
        "symbol_count": len(symbols),
        "dry_run": dry_run,
        "rows": 0,
        "sqlite_rows": 0,
        "sqlite_status": "empty",
        "state": "dry_run" if dry_run else "pending",
    }
    if dry_run:
        summary["params"] = params
        return summary

    try:
        if provider == TUSHARE_PROVIDER:
            collector = TushareCollector()
            collector._rate_limit(API_NAME)
            rows = collect_rt_fut_min_rows(params, fields="")
            source = TUSHARE_PROVIDER
        elif provider == SINA_PROVIDER:
            rows = collect_sina_futures_minute_rows(
                symbols,
                period="5",
                max_rows_per_symbol=int(os.environ.get("CN_FUTURES_SINA_MAX_ROWS_PER_SYMBOL", str(DEFAULT_SINA_MAX_ROWS_PER_SYMBOL))),
            )
            source = SINA_PROVIDER
        else:
            raise ValueError(f"unsupported provider {provider!r}")
    except Exception as exc:
        summary["state"] = "failed"
        summary["error"] = str(exc)
        return summary
    summary["rows"] = len(rows)
    summary["source"] = source
    if not rows:
        summary["state"] = "empty"
        return summary
    summary["sqlite_rows"] = ingest_rows_to_sqlite(
        sqlite_db_path,
        "market_bars_intraday",
        API_NAME,
        rows,
        source_name=f"{API_NAME}_{trade_date}_{freq.lower()}",
    )
    if summary["sqlite_rows"] <= 0:
        summary["sqlite_status"] = "failed"
        summary["state"] = "failed"
        summary["error"] = f"direct sqlite write produced 0 rows for non-empty {API_NAME} collection"
        return summary
    summary["sqlite_status"] = "ok"
    summary["state"] = "ok"
    return summary


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Collect CN futures 5-minute bars into SharedSignals.")
    parser.add_argument("--trade-date", default=default_trade_date(), help="Trade date as YYYYMMDD, default today.")
    parser.add_argument("--symbols", default=os.environ.get("CN_FUTURES_5MIN_SYMBOLS", ""), help="Comma-separated futures contracts.")
    parser.add_argument("--products", default=os.environ.get("CN_FUTURES_5MIN_PRODUCTS", ",".join(DEFAULT_PRODUCTS)), help="Comma-separated product prefixes used when symbols are auto-selected.")
    parser.add_argument("--max-symbols", type=int, default=int(os.environ.get("CN_FUTURES_5MIN_MAX_SYMBOLS", "30")), help="Max auto-selected futures contracts.")
    parser.add_argument("--freq", default=os.environ.get("CN_FUTURES_5MIN_FREQ", DEFAULT_FREQ), help="5-minute interval label, default 5MIN.")
    parser.add_argument(
        "--provider",
        choices=(SINA_PROVIDER, TUSHARE_PROVIDER),
        default=os.environ.get("CN_FUTURES_5MIN_PROVIDER", SINA_PROVIDER),
        help="Explicit 5-minute futures data provider owned by SharedSignals.",
    )
    parser.add_argument("--sqlite-db", type=Path, default=DEFAULT_SQLITE_PATH, help="SQLite read model path.")
    parser.add_argument("--dry-run", action="store_true", help="Print selected symbols and params without collecting or writing rows.")
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
            provider=str(args.provider),
            dry_run=bool(args.dry_run),
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

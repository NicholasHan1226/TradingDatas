"""NDJSON-to-SQLite bridge for non-CSV SharedSignals collectors."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from env_bootstrap import env_int

DEFAULT_SQLITE_PATH = (
    Path(os.environ.get("MARKETGRAPH_RUNTIME_ROOT", "/opt/investment/MarketGraphRuntime"))
    / "read_model"
    / "marketdata.sqlite"
)

DAILY_COLUMNS = (
    "market", "symbol", "trade_date", "open", "high", "low", "close",
    "volume", "amount", "provider", "source_file", "collected_at", "raw_json",
)

INTRADAY_COLUMNS = (
    "market", "symbol", "bar_time", "trade_date", "interval", "open", "high",
    "low", "close", "volume", "amount", "provider", "source_file",
    "collected_at", "raw_json",
)


def _bridge_lock_path(db_path: Path) -> Path:
    return db_path.parent / f".{db_path.name}.ndjson_bridge.lock"


@contextmanager
def _sqlite_bridge_lock(db_path: Path):
    timeout = env_int("SHAREDSIGNALS_NDJSON_BRIDGE_LOCK_TIMEOUT", 180, min_value=0)
    lock_path = _bridge_lock_path(db_path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + timeout
    with lock_path.open("a+") as handle:
        while True:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError as exc:
                if timeout <= 0 or time.monotonic() >= deadline:
                    raise TimeoutError(f"timed out waiting for ndjson bridge lock: {lock_path}") from exc
                time.sleep(min(1.0, max(0.05, deadline - time.monotonic())))
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _coerce_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _normalize_crypto_row(row: dict[str, Any], source_file: str) -> tuple[str, dict[str, Any]] | None:
    symbol = str(row.get("symbol") or "").upper()
    trade_date = str(row.get("trade_date") or "")
    interval = str(row.get("interval") or "")
    if not symbol or not trade_date or not interval:
        return None

    now = datetime.now(timezone.utc).isoformat()
    payload = {
        "market": str(row.get("market") or "Crypto"),
        "symbol": symbol,
        "trade_date": trade_date,
        "interval": interval,
        "bar_time": str(row.get("bar_time") or row.get("collected_at") or now),
        "open": _coerce_float(row.get("open")),
        "high": _coerce_float(row.get("high")),
        "low": _coerce_float(row.get("low")),
        "close": _coerce_float(row.get("close")),
        "volume": _coerce_float(row.get("volume")) or 0.0,
        "amount": _coerce_float(row.get("amount")) or 0.0,
        "provider": str(row.get("provider") or "binance"),
        "source_file": str(row.get("source_file") or source_file),
        "collected_at": str(row.get("collected_at") or now),
        "raw_json": row.get("raw_json") if isinstance(row.get("raw_json"), str) else json.dumps(row, ensure_ascii=False),
    }
    return ("market_bars_daily" if interval == "1d" else "market_bars_intraday"), payload


def _iter_ndjson_rows(paths: Iterable[Path]) -> Iterable[tuple[Path, dict[str, Any]]]:
    for path in paths:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if line:
                    yield path, json.loads(line)


def ingest_crypto_ndjson_to_sqlite(
    db_path: Path | str = DEFAULT_SQLITE_PATH,
    source_root: Path | str | None = None,
    *,
    since_minutes: int | None = None,
) -> dict[str, Any]:
    """Ingest Binance collector NDJSON staging files into the read-model SQLite DB."""
    db = Path(db_path)
    root = Path(source_root) if source_root else Path(__file__).resolve().parents[1] / "data" / "crypto" / "binance"
    if not db.exists():
        raise FileNotFoundError(f"sqlite db not found: {db}")
    if not root.exists():
        return {"status": "ok", "files": 0, "rows_read": 0, "rows_written": 0, "tables": {}}

    cutoff = time.time() - since_minutes * 60 if since_minutes and since_minutes > 0 else None
    paths = sorted(root.glob("*/*/*.ndjson"))
    if cutoff is not None:
        paths = [path for path in paths if path.stat().st_mtime >= cutoff]

    daily_rows: list[dict[str, Any]] = []
    intraday_rows: list[dict[str, Any]] = []
    for path, row in _iter_ndjson_rows(paths):
        normalized = _normalize_crypto_row(row, str(path))
        if normalized is None:
            continue
        table, payload = normalized
        if table == "market_bars_daily":
            daily_rows.append(payload)
        else:
            intraday_rows.append(payload)

    with _sqlite_bridge_lock(db):
        conn = sqlite3.connect(str(db), timeout=30)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=30000")
        try:
            if daily_rows:
                placeholders = ",".join("?" for _ in DAILY_COLUMNS)
                conn.executemany(
                    f"INSERT OR REPLACE INTO market_bars_daily ({', '.join(DAILY_COLUMNS)}) VALUES ({placeholders})",
                    [tuple(row.get(column) for column in DAILY_COLUMNS) for row in daily_rows],
                )
            if intraday_rows:
                placeholders = ",".join("?" for _ in INTRADAY_COLUMNS)
                conn.executemany(
                    f"INSERT OR REPLACE INTO market_bars_intraday ({', '.join(INTRADAY_COLUMNS)}) VALUES ({placeholders})",
                    [tuple(row.get(column) for column in INTRADAY_COLUMNS) for row in intraday_rows],
                )
            conn.commit()
        finally:
            conn.close()

    deleted = 0
    for path in paths:
        try:
            path.unlink()
            deleted += 1
        except FileNotFoundError:
            continue

    row_count = len(daily_rows) + len(intraday_rows)
    return {
        "status": "ok",
        "files": len(paths),
        "files_deleted": deleted,
        "rows_read": row_count,
        "rows_written": row_count,
        "tables": {"market_bars_daily": len(daily_rows), "market_bars_intraday": len(intraday_rows)},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest crypto NDJSON staging files into SharedSignals SQLite read model.")
    parser.add_argument("--db", default=str(DEFAULT_SQLITE_PATH))
    parser.add_argument("--source-root", default=None)
    parser.add_argument("--since-minutes", type=int, default=None)
    args = parser.parse_args()

    result = ingest_crypto_ndjson_to_sqlite(
        Path(args.db),
        Path(args.source_root) if args.source_root else None,
        since_minutes=args.since_minutes,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()

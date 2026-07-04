#!/usr/bin/env python3
"""Run the Binance collector through the SharedSignals lifecycle."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover - production venv has PyYAML
    yaml = None

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from collectors.crypto.binance import CryptoCollector
from storage.ndjson_bridge import DEFAULT_SQLITE_PATH, ingest_crypto_ndjson_to_sqlite


def _load_config(path: Path) -> dict[str, Any]:
    if not path.exists() or yaml is None:
        return {
            "symbols": ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT"],
            "intervals": ["1d", "4h", "1h", "15m"],
        }
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect Binance crypto data into SharedSignals.")
    parser.add_argument("--mode", choices=("ticker", "klines", "all"), default="ticker")
    parser.add_argument("--interval", action="append", dest="intervals", help="Kline interval to collect. Repeatable.")
    parser.add_argument("--symbol", action="append", dest="symbols", help="Symbol to collect. Repeatable.")
    parser.add_argument("--config", default=str(Path(__file__).resolve().parent / "config.yaml"))
    parser.add_argument("--db", default=str(DEFAULT_SQLITE_PATH))
    parser.add_argument("--bridge-since-minutes", type=int, default=180)
    parser.add_argument("--no-bridge", action="store_true")
    args = parser.parse_args()

    config = _load_config(Path(args.config))
    if args.symbols:
        config["symbols"] = [symbol.upper() for symbol in args.symbols]
    if args.intervals:
        config["intervals"] = args.intervals
    proxy = os.getenv("BINANCE_HTTP_PROXY") or config.get("proxy", "")

    collector = CryptoCollector(config=config, proxy=proxy)
    contexts: list[dict[str, Any]] = []
    if args.mode in ("ticker", "all"):
        contexts.append({"mode": "ticker", "symbols": config.get("symbols")})
    if args.mode in ("klines", "all"):
        contexts.append({"mode": "klines", "symbols": config.get("symbols"), "intervals": config.get("intervals")})

    runs = [collector.run(context) for context in contexts]
    result: dict[str, Any] = {"collector": "crypto_binance", "runs": runs}
    if not args.no_bridge:
        result["bridge"] = ingest_crypto_ndjson_to_sqlite(
            Path(args.db),
            ROOT / "data" / "crypto" / "binance",
            since_minutes=args.bridge_since_minutes,
        )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))

    if any(run.get("status") not in {"success", "partial_success"} for run in runs):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

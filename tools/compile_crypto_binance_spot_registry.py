#!/usr/bin/env python3
"""Expand the frozen Binance Spot registry from one reviewed symbol template."""

from __future__ import annotations

import argparse
from copy import deepcopy
from pathlib import Path
import re

import yaml


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_UNIVERSE = ROOT / "config" / "crypto_binance_spot_universe.v1.yaml"
DEFAULT_REGISTRY = ROOT / "config" / "crypto_binance_spot_canary_registry.v1.yaml"
_SYMBOL = re.compile(r"[A-Z0-9]{2,16}USDT")


def _document(path: Path) -> dict[str, object]:
    payload = yaml.safe_load(path.read_bytes())
    if not isinstance(payload, dict):
        raise ValueError("Crypto registry input must be an object")
    return payload


def _symbols(path: Path) -> tuple[str, ...]:
    payload = _document(path)
    if set(payload) != {
        "version",
        "selection_policy",
        "selected_at",
        "quote_asset",
        "interval",
        "minimum_history_days",
        "symbols",
    }:
        raise ValueError("Crypto universe contract keys are invalid")
    raw = payload["symbols"]
    if (
        payload["version"] != 1
        or payload["quote_asset"] != "USDT"
        or payload["interval"] != "5m"
        or not isinstance(raw, list)
        or len(raw) != 10
    ):
        raise ValueError("Crypto universe contract is invalid")
    symbols = tuple(raw)
    if len(set(symbols)) != 10 or any(
        not isinstance(symbol, str) or _SYMBOL.fullmatch(symbol) is None
        for symbol in symbols
    ):
        raise ValueError("Crypto universe symbols are invalid")
    if symbols[:2] != ("BTCUSDT", "ETHUSDT"):
        raise ValueError("Crypto rollback canary symbols must remain first")
    return symbols


def _clone(template: dict[str, object], symbol: str, suffix: str) -> dict[str, object]:
    item = deepcopy(template)
    lower = symbol.lower()
    item["dataset_id"] = f"crypto.spot.binance.{lower}.{suffix}"
    item["aliases"] = [f"binance_spot.{lower}.{suffix}"]
    bindings = item["provider_bindings"]
    if not isinstance(bindings, list) or len(bindings) != 1:
        raise ValueError("Crypto registry template binding is invalid")
    binding = bindings[0]
    if not isinstance(binding, dict):
        raise ValueError("Crypto registry template binding is invalid")
    api_prefix = {
        "5m": "klines_",
        "rules": "exchangeInfo_",
        "book_ticker": "bookTicker_",
    }.get(suffix)
    if api_prefix is None:
        raise ValueError("Crypto registry template suffix is invalid")
    binding["api_name"] = api_prefix + lower
    binding["read_discriminator_value"] = (
        f"binance_spot_{lower}_{suffix.replace('.', '_')}"
    )
    request = binding["request_template"]
    if not isinstance(request, dict):
        raise ValueError("Crypto registry request template is invalid")
    request["symbol"] = symbol
    return item


def compile_registry(*, universe_path: Path, registry_path: Path) -> bytes:
    symbols = _symbols(universe_path)
    registry = _document(registry_path)
    datasets = registry.get("datasets")
    if not isinstance(datasets, list):
        raise ValueError("Crypto registry datasets are invalid")
    by_id = {
        item.get("dataset_id"): item for item in datasets if isinstance(item, dict)
    }
    bar = by_id.get("crypto.spot.binance.btcusdt.5m")
    rules = by_id.get("crypto.spot.binance.btcusdt.rules")
    book_ticker = by_id.get("crypto.spot.binance.btcusdt.book_ticker")
    if (
        not isinstance(bar, dict)
        or not isinstance(rules, dict)
        or not isinstance(book_ticker, dict)
    ):
        raise ValueError("Crypto registry templates are missing")
    registry["datasets"] = [
        *(_clone(bar, symbol, "5m") for symbol in symbols),
        *(_clone(rules, symbol, "rules") for symbol in symbols),
        *(_clone(book_ticker, symbol, "book_ticker") for symbol in symbols),
    ]
    return yaml.safe_dump(
        registry,
        allow_unicode=True,
        sort_keys=False,
        width=120,
    ).encode("utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--universe", type=Path, default=DEFAULT_UNIVERSE)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--output", type=Path, default=DEFAULT_REGISTRY)
    args = parser.parse_args()
    payload = compile_registry(
        universe_path=args.universe,
        registry_path=args.registry,
    )
    args.output.write_bytes(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Validate a frozen, receipt-bound 500-symbol CN minute-universe contract.

This tool is deliberately offline.  It validates an externally supplied,
reviewed universe input and emits only a hash-bound reference artifact; it does
not call a provider, open SQLite, alter the runtime registry, or schedule work.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path

import yaml

_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_UNIVERSE_ID = re.compile(r"[a-z][a-z0-9-]{2,127}\Z")
_TS_CODE = re.compile(r"[0-9]{6}\.(?:SH|SZ)\Z")
_EXACT_SYMBOL_COUNT = 500
_BATCH_SIZE = 100


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _text(value: object, label: str) -> str:
    if type(value) is not str or not value or value != value.strip():
        raise ValueError(f"{label} is invalid")
    return value


def _sha256_text(value: object, label: str) -> str:
    digest = _text(value, label)
    if _SHA256.fullmatch(digest) is None:
        raise ValueError(f"{label} must be a SHA-256 digest")
    return digest


def _as_of(value: object) -> str:
    raw = _text(value, "as_of")
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("as_of must be RFC3339") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("as_of must be timezone-aware")
    return parsed.astimezone(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{label} must be an object")
    return value


def _source(value: object) -> dict[str, str]:
    source = _mapping(value, "source")
    if set(source) != {
        "dataset_id",
        "provider",
        "receipt_id",
        "registry_sha256",
        "snapshot_sha256",
    }:
        raise ValueError("source keys are invalid")
    dataset_id = _text(source["dataset_id"], "source.dataset_id")
    provider = _text(source["provider"], "source.provider")
    receipt_id = _text(source["receipt_id"], "source.receipt_id")
    if dataset_id != "cn.equity.security_master" or provider != "tushare":
        raise ValueError("source must be the Tushare security master")
    if not receipt_id.startswith("receipt:"):
        raise ValueError("source.receipt_id is invalid")
    return {
        "dataset_id": dataset_id,
        "provider": provider,
        "receipt_id": receipt_id,
        "registry_sha256": _sha256_text(source["registry_sha256"], "source.registry_sha256"),
        "snapshot_sha256": _sha256_text(source["snapshot_sha256"], "source.snapshot_sha256"),
    }


def _selection(value: object) -> dict[str, object]:
    selection = _mapping(value, "selection")
    if set(selection) != {
        "source_field",
        "source_equals",
        "source_date_field",
        "source_date_lte_days",
        "source_order",
    }:
        raise ValueError("selection keys are invalid")
    source_equals = _mapping(selection["source_equals"], "selection.source_equals")
    if not source_equals:
        raise ValueError("selection.source_equals must not be empty")
    normalized_equals = {
        _text(key, "selection.source_equals key"): _text(
            item, f"selection.source_equals.{key}"
        )
        for key, item in source_equals.items()
    }
    max_age = selection["source_date_lte_days"]
    if type(max_age) is not int or max_age <= 0:
        raise ValueError("selection.source_date_lte_days is invalid")
    source_order = _text(selection["source_order"], "selection.source_order")
    if source_order not in {"lexical", "stable_hash"}:
        raise ValueError("selection.source_order is invalid")
    source_field = _text(selection["source_field"], "selection.source_field")
    if source_field != "ts_code":
        raise ValueError("selection.source_field must be ts_code")
    return {
        "source_field": source_field,
        "source_equals": dict(sorted(normalized_equals.items())),
        "source_date_field": _text(
            selection["source_date_field"], "selection.source_date_field"
        ),
        "source_date_lte_days": max_age,
        "source_order": source_order,
    }


def _symbols(value: object, declared_sha256: object) -> tuple[list[str], str]:
    if not isinstance(value, list) or len(value) != _EXACT_SYMBOL_COUNT:
        raise ValueError("symbols must contain exactly 500 symbols")
    symbols = [_text(symbol, f"symbols[{index}]") for index, symbol in enumerate(value)]
    if any(_TS_CODE.fullmatch(symbol) is None for symbol in symbols):
        raise ValueError("symbols contains an invalid ts_code")
    if len(set(symbols)) != len(symbols):
        raise ValueError("symbols must be unique")
    computed = _sha256(symbols)
    if _sha256_text(declared_sha256, "symbols_sha256") != computed:
        raise ValueError("symbols_sha256 does not bind the declared symbols")
    return symbols, computed


def validate_universe_contract(document: Mapping[str, object]) -> dict[str, object]:
    """Validate a frozen candidate and return a registry/manifest reference artifact."""

    if not isinstance(document, Mapping) or set(document) != {
        "schema_version",
        "universe_id",
        "as_of",
        "source",
        "selection",
        "batch_size",
        "symbols",
        "symbols_sha256",
    }:
        raise ValueError("minute universe contract keys are invalid")
    if document["schema_version"] != 1:
        raise ValueError("minute universe contract schema_version is invalid")
    universe_id = _text(document["universe_id"], "universe_id")
    if _UNIVERSE_ID.fullmatch(universe_id) is None:
        raise ValueError("universe_id is invalid")
    if document["batch_size"] != _BATCH_SIZE:
        raise ValueError("batch_size must be 100")
    as_of = _as_of(document["as_of"])
    source = _source(document["source"])
    selection = _selection(document["selection"])
    symbols, symbols_sha256 = _symbols(document["symbols"], document["symbols_sha256"])
    shards = [
        {"index": index, "value_count": _BATCH_SIZE}
        for index in range(_EXACT_SYMBOL_COUNT // _BATCH_SIZE)
    ]
    bound_contract = {
        "schema_version": 1,
        "universe_id": universe_id,
        "as_of": as_of,
        "source": source,
        "selection": selection,
        "batch_size": _BATCH_SIZE,
        "symbols": symbols,
        "symbols_sha256": symbols_sha256,
    }
    universe_sha256 = _sha256(bound_contract)
    return {
        "schema_version": 1,
        "universe_id": universe_id,
        "as_of": as_of,
        "source": source,
        "selection": selection,
        "symbol_count": _EXACT_SYMBOL_COUNT,
        "symbols_sha256": symbols_sha256,
        "universe_sha256": universe_sha256,
        "sharding": {
            "parameter": "ts_code",
            "batch_size": _BATCH_SIZE,
            "shard_count": len(shards),
            "shards": shards,
        },
        "registry_manifest_reference": {
            "dataset_id": "cn.dataset.rt_min",
            "provider": "tushare",
            "api_name": "rt_min",
            "parameter": "ts_code",
            "universe_id": universe_id,
            "universe_sha256": universe_sha256,
        },
    }


def _load_document(path: Path) -> Mapping[str, object]:
    try:
        document = yaml.safe_load(path.read_bytes())
    except yaml.YAMLError as exc:
        raise ValueError("minute universe contract must be YAML") from exc
    return _mapping(document, "minute universe contract")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--universe", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    artifact = validate_universe_contract(_load_document(args.universe))
    args.output.write_bytes(_canonical_json(artifact) + b"\n")
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())

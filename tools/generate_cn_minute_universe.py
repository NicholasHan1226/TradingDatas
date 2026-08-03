"""Generate a validated frozen 500-symbol minute candidate from reviewed inputs.

The generator is deliberately offline: it accepts a reviewed security-master
snapshot and its receipt/registry/hash references, deterministically replays
the retired five-by-100 selection semantics, then delegates the result to the
existing frozen-universe validator.  It never calls a provider, opens SQLite,
or changes runtime configuration.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.validate_cn_minute_universe import validate_universe_contract

_SOURCE_KEYS = frozenset(
    {
        "dataset_id",
        "provider",
        "receipt_id",
        "receipt_sha256",
        "registry_sha256",
        "snapshot_sha256",
    }
)
_LEGACY_SELECTION = {
    "source_field": "ts_code",
    "source_equals": {
        "curr_type": "CNY",
        "list_status": "L",
        "market": "主板",
    },
    "source_date_field": "list_date",
    "source_date_lte_days": 30,
    "source_order": "stable_hash",
}
_GENERATION_REQUEST_KEYS = frozenset(
    {
        "schema_version",
        "universe_id",
        "as_of",
        "source",
        "selection",
        "receipt",
        "snapshot_rows",
    }
)
_SHANGHAI = ZoneInfo("Asia/Shanghai")


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{label} must be an object")
    return value


def _as_of_date(value: object) -> date:
    if type(value) is not str or not value or value != value.strip():
        raise ValueError("as_of is invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("as_of must be RFC3339") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("as_of must be timezone-aware")
    return parsed.astimezone(_SHANGHAI).date()


def _source(value: object) -> dict[str, object]:
    source = _mapping(value, "source")
    if set(source) != _SOURCE_KEYS:
        raise ValueError("source keys are invalid")
    return dict(source)


def _reviewed_receipt(value: object, source: Mapping[str, object]) -> None:
    receipt = _mapping(value, "receipt")
    for key, expected in (
        ("schema_version", "tradingdatas.ingest_receipt.v1"),
        ("receipt_id", source["receipt_id"]),
        ("dataset_id", source["dataset_id"]),
        ("provider", source["provider"]),
        ("status", "success"),
    ):
        if receipt.get(key) != expected:
            raise ValueError(f"receipt.{key} does not match the reviewed source")
    if source["receipt_sha256"] != _sha256(dict(receipt)):
        raise ValueError("receipt_sha256 does not bind receipt")


def _snapshot_rows(value: object, source: Mapping[str, object]) -> list[Mapping[str, object]]:
    if not isinstance(value, list) or not value:
        raise ValueError("snapshot_rows must be a non-empty list")
    if source["snapshot_sha256"] != _sha256(value):
        raise ValueError("snapshot_sha256 does not bind snapshot_rows")
    rows: list[Mapping[str, object]] = []
    for index, row in enumerate(value):
        rows.append(_mapping(row, f"snapshot_rows[{index}]"))
    return rows


def _legacy_selection(value: object) -> Mapping[str, object]:
    selection = _mapping(value, "selection")
    if dict(selection) != _LEGACY_SELECTION:
        raise ValueError("selection does not match legacy 500-universe semantics")
    return selection


def _eligible_symbols(
    rows: Sequence[Mapping[str, object]], *, as_of: date, selection: Mapping[str, object]
) -> list[str]:
    cutoff = as_of.fromordinal(as_of.toordinal() - int(selection["source_date_lte_days"]))
    equals = _mapping(selection["source_equals"], "selection.source_equals")
    source_field = str(selection["source_field"])
    source_date_field = str(selection["source_date_field"])
    values: set[str] = set()
    for index, row in enumerate(rows):
        value = row.get(source_field)
        if type(value) is not str or not value:
            raise ValueError(f"snapshot_rows[{index}].{source_field} is invalid")
        for field in equals:
            if field not in row:
                raise ValueError(f"snapshot_rows[{index}] is missing selector field {field}")
        if any(row[field] != expected for field, expected in equals.items()):
            continue
        raw_date = row.get(source_date_field)
        if type(raw_date) is not str or len(raw_date) != 8 or not raw_date.isdigit():
            raise ValueError(f"snapshot_rows[{index}].{source_date_field} is invalid")
        try:
            listed = date.fromisoformat(f"{raw_date[:4]}-{raw_date[4:6]}-{raw_date[6:]}")
        except ValueError as exc:
            raise ValueError(f"snapshot_rows[{index}].{source_date_field} is invalid") from exc
        if listed <= cutoff:
            values.add(value)
    if len(values) < 500:
        raise ValueError("reviewed snapshot has fewer than 500 eligible symbols")
    return sorted(
        values,
        key=lambda value: hashlib.sha256(
            json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8")
        ).hexdigest(),
    )[:500]


def generate_universe_contract(document: Mapping[str, object]) -> dict[str, object]:
    """Create one candidate contract from reviewed external snapshot evidence."""

    if not isinstance(document, Mapping) or set(document) != _GENERATION_REQUEST_KEYS:
        raise ValueError("generation request keys are invalid")
    if document["schema_version"] != 1:
        raise ValueError("generation request schema_version is invalid")
    source = _source(document["source"])
    _reviewed_receipt(document["receipt"], source)
    rows = _snapshot_rows(document["snapshot_rows"], source)
    selection = _legacy_selection(document["selection"])
    symbols = _eligible_symbols(rows, as_of=_as_of_date(document["as_of"]), selection=selection)
    contract = {
        "schema_version": 2,
        "universe_id": document["universe_id"],
        "as_of": document["as_of"],
        "source": source,
        "selection": dict(selection),
        "batch_size": 100,
        "symbols": symbols,
        "symbols_sha256": _sha256(symbols),
    }
    validate_universe_contract(contract)
    return contract


def compile_reviewed_snapshot(document: Mapping[str, object]) -> dict[str, object]:
    """Generate then validate a reference artifact without retaining source payloads."""

    return validate_universe_contract(generate_universe_contract(document))


def _load_document(path: Path) -> Mapping[str, object]:
    try:
        document = yaml.safe_load(path.read_bytes())
    except yaml.YAMLError as exc:
        raise ValueError("generation request must be YAML") from exc
    return _mapping(document, "generation request")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    args.output.write_bytes(_canonical_json(compile_reviewed_snapshot(_load_document(args.input))) + b"\n")
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())

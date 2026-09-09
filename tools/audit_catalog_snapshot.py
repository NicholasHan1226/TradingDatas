"""Audit one complete catalog JSON offline; a snapshot is not recovery evidence."""

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.dont_write_bytecode = True
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from catalog_service import (
    _DATASET_ID_RE,
    _RUNTIME_STATES,
    _validated_runtime_row,
)
from storage.receipt_projection import RuntimeProjectionError


class SnapshotAuditError(ValueError):
    """Malformed, incomplete or unsafe snapshot; never include input in errors."""


def _reject_duplicates(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise SnapshotAuditError("duplicate_json_key")
        result[key] = value
    return result


def load_json(path):
    try:
        return json.loads(Path(path).read_text(), object_pairs_hook=_reject_duplicates)
    except (OSError, UnicodeError, ValueError):
        raise SnapshotAuditError("invalid_json_input") from None


def _identifier(value):
    return type(value) is str and len(value) <= 256 and _DATASET_ID_RE.fullmatch(value)


def audit_snapshot(snapshot, expected_dataset_ids):
    """Return safe counts only after validating the entire expected scope."""
    if (
        type(expected_dataset_ids) not in (list, tuple, set, frozenset)
        or not expected_dataset_ids
        or any(not _identifier(item) for item in expected_dataset_ids)
        or len(set(expected_dataset_ids)) != len(expected_dataset_ids)
    ):
        raise SnapshotAuditError("invalid_expected_scope")
    if type(snapshot) is not dict or set(snapshot) != {
        "api_version", "catalog_version", "request_id", "data", "next_cursor"
    }:
        raise SnapshotAuditError("invalid_envelope")
    if snapshot["api_version"] != "v1" or any(
        type(snapshot[key]) is not str
        or not snapshot[key]
        or snapshot[key] != snapshot[key].strip()
        for key in ("catalog_version", "request_id")
    ):
        raise SnapshotAuditError("invalid_envelope")
    if snapshot["next_cursor"] is not None:
        raise SnapshotAuditError("incomplete_catalog")
    data = snapshot["data"]
    if type(data) is not list or not data:
        raise SnapshotAuditError("empty_or_invalid_catalog")
    validated = {}
    for item in data:
        if type(item) is not dict or not _identifier(item.get("dataset_id")):
            raise SnapshotAuditError("invalid_dataset_identity")
        dataset_id = item["dataset_id"]
        if dataset_id in validated:
            raise SnapshotAuditError("duplicate_dataset_identity")
        runtime = item.get("runtime")
        if type(runtime) is not dict or "dataset_id" in runtime:
            raise SnapshotAuditError("invalid_runtime")
        try:
            row = _validated_runtime_row(
                {dataset_id: {**runtime, "dataset_id": dataset_id}}, dataset_id
            )
        except (RuntimeProjectionError, AssertionError):
            raise SnapshotAuditError("invalid_runtime") from None
        if any(
            not re.fullmatch(r"[a-z][a-z0-9_]{0,127}", reason)
            for reason in row["reasons"]
        ):
            raise SnapshotAuditError("unsafe_reason_code")
        receipt = row["receipt_id"]
        if receipt is not None and not re.fullmatch(r"(?:receipt:)?[0-9a-f]{64}", receipt):
            raise SnapshotAuditError("unsafe_receipt_id")
        validated[dataset_id] = row
    if set(validated) != set(expected_dataset_ids):
        raise SnapshotAuditError("scope_mismatch")
    counts = Counter(row["state"] for row in validated.values())
    return {
        "audit": "complete_snapshot",
        "recovery_verified": False,
        "dataset_count": len(validated),
        "state_counts": {state: counts[state] for state in sorted(_RUNTIME_STATES)},
        "failed_dataset_ids": sorted(
            key for key, row in validated.items() if row["state"] == "failed"
        ),
        "runtime_evidence": [
            {"dataset_id": key, "state": row["state"], "degraded": row["degraded"],
             "reasons": row["reasons"], "receipt_id": row["receipt_id"]}
            for key, row in sorted(validated.items())
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--expected-dataset-ids", type=Path, required=True,
                        help="JSON array defining the exact authorized catalog scope")
    args = parser.parse_args()
    try:
        result = audit_snapshot(load_json(args.snapshot), load_json(args.expected_dataset_ids))
    except SnapshotAuditError as exc:
        print(json.dumps({"audit": "rejected", "reason": str(exc)}))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

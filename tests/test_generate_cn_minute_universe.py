from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from tools.generate_cn_minute_universe import (
    compile_reviewed_snapshot,
    generate_universe_contract,
)

ROOT = Path(__file__).resolve().parents[1]


def _sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _stable_hash_order(values: list[str]) -> list[str]:
    return sorted(
        values,
        key=lambda value: hashlib.sha256(
            json.dumps(value, ensure_ascii=False, allow_nan=False).encode()
        ).hexdigest(),
    )


def _rows() -> list[dict[str, str]]:
    """Structural fixture only; it is not a proposed or real market universe."""

    eligible = [
        {
            "ts_code": f"{value:06d}.SZ",
            "market": "主板",
            "list_status": "L",
            "curr_type": "CNY",
            "list_date": "20260701",
        }
        for value in range(1, 502)
    ]
    return [
        *eligible,
        {
            "ts_code": "999999.SZ",
            "market": "主板",
            "list_status": "L",
            "curr_type": "CNY",
            "list_date": "20260705",
        },
        {
            "ts_code": "888888.SZ",
            "market": "创业板",
            "list_status": "L",
            "curr_type": "CNY",
            "list_date": "20260701",
        },
    ]


def _receipt() -> dict[str, object]:
    return {
        "schema_version": "tradingdatas.ingest_receipt.v1",
        "receipt_id": "receipt:reviewed-security-master",
        "dataset_id": "cn.equity.security_master",
        "provider": "tushare",
        "status": "success",
    }


def _request(rows: list[dict[str, str]] | None = None) -> dict[str, object]:
    snapshot_rows = _rows() if rows is None else rows
    receipt = _receipt()
    return {
        "schema_version": 1,
        "universe_id": "cn-equity-mainboard-rt-min-500-v1",
        "as_of": "2026-08-03T00:00:00Z",
        "source": {
            "dataset_id": "cn.equity.security_master",
            "provider": "tushare",
            "receipt_id": receipt["receipt_id"],
            "receipt_sha256": _sha256(receipt),
            "registry_sha256": "a" * 64,
            "snapshot_sha256": _sha256(snapshot_rows),
        },
        "selection": {
            "source_field": "ts_code",
            "source_equals": {
                "curr_type": "CNY",
                "list_status": "L",
                "market": "主板",
            },
            "source_date_field": "list_date",
            "source_date_lte_days": 30,
            "source_order": "stable_hash",
        },
        "receipt": receipt,
        "snapshot_rows": snapshot_rows,
    }


def test_generator_replays_legacy_filter_and_stable_hash_into_validated_contract() -> None:
    request = _request()

    contract = generate_universe_contract(request)
    artifact = compile_reviewed_snapshot(request)

    expected = _stable_hash_order([f"{value:06d}.SZ" for value in range(1, 502)])[:500]
    assert contract["symbols"] == expected
    assert contract["source"] == request["source"]
    assert artifact["symbol_count"] == 500
    assert artifact["symbols_sha256"] == _sha256(expected)
    assert artifact["sharding"]["shard_count"] == 5


def test_generator_fails_closed_without_a_snapshot() -> None:
    request = _request()
    request.pop("snapshot_rows")

    with pytest.raises(ValueError, match="generation request keys are invalid"):
        generate_universe_contract(request)


def test_generator_rejects_a_snapshot_or_receipt_hash_mismatch() -> None:
    request = _request()
    request["source"]["snapshot_sha256"] = "d" * 64  # type: ignore[index]

    with pytest.raises(ValueError, match="snapshot_sha256 does not bind snapshot_rows"):
        generate_universe_contract(request)

    request = _request()
    request["source"]["receipt_sha256"] = "d" * 64  # type: ignore[index]

    with pytest.raises(ValueError, match="receipt_sha256 does not bind receipt"):
        generate_universe_contract(request)


def test_generator_rejects_less_than_500_legacy_eligible_symbols() -> None:
    request = _request(_rows()[:499])

    with pytest.raises(ValueError, match="fewer than 500 eligible symbols"):
        generate_universe_contract(request)


def test_generator_rejects_selection_that_does_not_match_legacy_500_semantics() -> None:
    request = _request()
    request["selection"]["source_order"] = "lexical"  # type: ignore[index]

    with pytest.raises(ValueError, match="selection does not match legacy"):
        generate_universe_contract(request)


def test_cli_emits_the_existing_validator_reference(tmp_path) -> None:
    request_path = tmp_path / "reviewed-security-master.yaml"
    output_path = tmp_path / "reference.json"
    request_path.write_text(json.dumps(_request(), ensure_ascii=False), encoding="utf-8")

    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools" / "generate_cn_minute_universe.py"),
            "--input",
            str(request_path),
            "--output",
            str(output_path),
        ],
        capture_output=True,
        check=False,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert json.loads(output_path.read_text(encoding="utf-8")) == compile_reviewed_snapshot(_request())

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest

from collectors.tushare import tushare_common
from collectors.tushare.provider_native_ingest import collect_provider_native_dataset
from dataset_registry import load_dataset_registry
from storage.ingest_receipts import IngestContext
from storage.provider_dataset_rows import (
    PROVIDER_DATASET_ROWS_DDL,
    ProviderNativeAdmissionError,
    ingest_provider_native_rows,
)
from storage.schema import SCHEMA_SQL
from tests.test_provider_native_registry import generic_dataset, write_registry


CONFIG_HASH = "a" * 64


def _db(path: Path, *, generic_table: bool = True) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.executescript(SCHEMA_SQL)
        if generic_table:
            conn.executescript(PROVIDER_DATASET_ROWS_DDL)
        else:
            # Fresh canonical databases include the generic table.  This test
            # helper drops it only to prove runtime writers still fail closed
            # and never perform schema migration themselves.
            conn.execute("DROP TABLE provider_dataset_rows")
        conn.commit()
    finally:
        conn.close()


def _contract(tmp_path: Path, **dataset_overrides: object):
    registry = load_dataset_registry(
        write_registry(tmp_path, generic_dataset(**dataset_overrides))
    )
    dataset = registry.datasets[0]
    binding = registry.provider_binding(dataset.dataset_id, "tushare")
    return registry, dataset, binding


def _context(dataset, binding, attempt: int = 1) -> IngestContext:
    return IngestContext(
        attempt_id=f"018f47de-0000-7000-8000-{attempt:012d}",
        dataset_id=dataset.dataset_id,
        provider=binding.provider,
        provider_api=binding.api_name,
        request_window={"end_date": "20260717", "start_date": "20260717"},
        config_hash=CONFIG_HASH,
        adapter_version=binding.adapter_version,
        started_at=f"2026-07-17T01:00:{attempt:02d}+00:00",
        data_through=None,
    )


def _row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "ts_code": "000001.SZ",
        "trade_date": "20260717",
        "close": 11.25,
        "sequence": 1,
    }
    row.update(overrides)
    return row


def _fact(path: Path) -> sqlite3.Row:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute("SELECT * FROM provider_dataset_rows").fetchone()
        assert row is not None
        return row
    finally:
        conn.close()


def test_lossless_payload_and_quality_issues_are_stored_without_coercion(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "facts.sqlite"
    _db(db_path)
    _, dataset, binding = _contract(tmp_path)
    payload = _row(
        close="11.25",
        sequence=2**63,
        provider_new={"nested": [1, True, None]},
    )

    result = ingest_provider_native_rows(
        db_path,
        dataset=dataset,
        binding=binding,
        rows=[payload],
        context=_context(dataset, binding),
    )
    fact = _fact(db_path)

    assert result.status == "success"
    assert result.counts.inserted == 1
    assert json.loads(fact["payload_json"]) == payload
    assert fact["schema_major"] == 2
    assert fact["ingested_schema_version"] == "2.1.0"
    assert fact["quality_state"] == "degraded"
    assert json.loads(fact["quality_issues_json"]) == [
        "integer_out_of_int64:sequence",
        "type_mismatch:close:float",
        "unknown_field:provider_new",
    ]


def test_unsafe_unknown_field_names_are_hashed_without_changing_payload(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "facts.sqlite"
    _db(db_path)
    _, dataset, binding = _contract(tmp_path)
    unknown_keys = ("new-field", "新闻", "x" * 65)
    payload = _row(**{key: f"value-{index}" for index, key in enumerate(unknown_keys)})

    ingest_provider_native_rows(
        db_path,
        dataset=dataset,
        binding=binding,
        rows=[payload],
        context=_context(dataset, binding),
    )
    fact = _fact(db_path)

    assert json.loads(fact["payload_json"]) == payload
    expected = sorted(
        f"unknown_field_sha256:{hashlib.sha256(key.encode('utf-8')).hexdigest()}"
        for key in unknown_keys
    )
    issues = json.loads(fact["quality_issues_json"])
    assert issues == expected
    assert all(len(issue.rsplit(":", 1)[1]) == 64 for issue in issues)
    assert not any(key in fact["quality_issues_json"] for key in unknown_keys)


@pytest.mark.parametrize(
    ("as_of_format", "valid_value", "invalid_value"),
    [
        ("yyyymmdd", "20260228", "20260229"),
        (
            "rfc3339",
            "2026-07-17T01:02:03.123456+08:00",
            "2026-07-17 01:02:03+08:00",
        ),
    ],
)
def test_declared_time_format_quality_is_strict_and_payload_stays_lossless(
    tmp_path: Path,
    as_of_format: str,
    valid_value: str,
    invalid_value: str,
) -> None:
    db_path = tmp_path / "facts.sqlite"
    _db(db_path)
    _, dataset, binding = _contract(tmp_path, as_of_format=as_of_format)

    valid = ingest_provider_native_rows(
        db_path,
        dataset=dataset,
        binding=binding,
        rows=[_row(trade_date=valid_value)],
        context=_context(dataset, binding, 1),
    )
    invalid = ingest_provider_native_rows(
        db_path,
        dataset=dataset,
        binding=binding,
        rows=[_row(ts_code="000002.SZ", trade_date=invalid_value)],
        context=_context(dataset, binding, 2),
    )

    assert valid.status == "success"
    assert invalid.status == "success"
    with sqlite3.connect(db_path) as conn:
        facts = conn.execute(
            "SELECT payload_json, quality_state, quality_issues_json "
            "FROM provider_dataset_rows ORDER BY payload_json"
        ).fetchall()
    by_date = {json.loads(row[0])["trade_date"]: row for row in facts}
    assert by_date[valid_value][1:] == ("valid", "[]")
    assert json.loads(by_date[invalid_value][0])["trade_date"] == invalid_value
    assert by_date[invalid_value][1] == "degraded"
    assert json.loads(by_date[invalid_value][2]) == [
        f"time_format_mismatch:trade_date:{as_of_format}"
    ]


def test_snapshot_insert_unchanged_update_and_receipts_are_exact(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "facts.sqlite"
    _db(db_path)
    _, dataset, binding = _contract(tmp_path)

    inserted = ingest_provider_native_rows(
        db_path,
        dataset=dataset,
        binding=binding,
        rows=[_row()],
        context=_context(dataset, binding, 1),
    )
    unchanged = ingest_provider_native_rows(
        db_path,
        dataset=dataset,
        binding=binding,
        rows=[_row()],
        context=_context(dataset, binding, 2),
    )
    updated = ingest_provider_native_rows(
        db_path,
        dataset=dataset,
        binding=binding,
        rows=[_row(close=12.5)],
        context=_context(dataset, binding, 3),
    )

    assert (
        inserted.counts.inserted,
        inserted.counts.updated,
        inserted.counts.unchanged,
    ) == (1, 0, 0)
    assert (
        unchanged.counts.inserted,
        unchanged.counts.updated,
        unchanged.counts.unchanged,
    ) == (0, 0, 1)
    assert (
        updated.counts.inserted,
        updated.counts.updated,
        updated.counts.unchanged,
    ) == (0, 1, 0)
    fact = _fact(db_path)
    assert fact["revision"] == 2
    assert json.loads(fact["payload_json"])["close"] == 12.5
    assert fact["receipt_id"] == updated.receipt_ids[0]
    with sqlite3.connect(db_path) as conn:
        receipts = conn.execute(
            "SELECT notes FROM market_ingest_runs WHERE status='success'"
        ).fetchall()
    assert len(receipts) == 3
    assert {
        json.loads(receipt[0])["counts"]["count_semantics"] for receipt in receipts
    } == {"exact_row_outcomes"}


def test_snapshot_missing_key_uses_tagged_payload_fallback(tmp_path: Path) -> None:
    db_path = tmp_path / "facts.sqlite"
    _db(db_path)
    _, dataset, binding = _contract(tmp_path)

    ingest_provider_native_rows(
        db_path,
        dataset=dataset,
        binding=binding,
        rows=[_row(ts_code=None)],
        context=_context(dataset, binding),
    )
    fact = _fact(db_path)

    assert fact["row_key"].startswith("payload:")
    assert "snapshot_key_fallback:null:ts_code" in json.loads(
        fact["quality_issues_json"]
    )


def test_snapshot_blank_text_key_uses_tagged_payload_fallback_without_rewriting(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "facts.sqlite"
    _db(db_path)
    _, dataset, binding = _contract(tmp_path)
    payload = _row(ts_code="")

    ingest_provider_native_rows(
        db_path,
        dataset=dataset,
        binding=binding,
        rows=[payload],
        context=_context(dataset, binding),
    )
    fact = _fact(db_path)

    assert fact["row_key"].startswith("payload:")
    assert json.loads(fact["payload_json"]) == payload
    assert "snapshot_key_fallback:blank:ts_code" in json.loads(
        fact["quality_issues_json"]
    )


@pytest.mark.parametrize("logical_type", ("integer", "float"))
def test_snapshot_empty_string_nontext_key_keeps_type_mismatch_fallback(
    logical_type: str,
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "facts.sqlite"
    _db(db_path)
    fields = [dict(field) for field in generic_dataset()["fields"]]  # type: ignore[arg-type]
    fields[0]["logical_type"] = logical_type
    _, dataset, binding = _contract(tmp_path, fields=fields)
    payload = _row(ts_code="")

    ingest_provider_native_rows(
        db_path,
        dataset=dataset,
        binding=binding,
        rows=[payload],
        context=_context(dataset, binding),
    )
    fact = _fact(db_path)

    assert fact["row_key"].startswith("payload:")
    assert json.loads(fact["payload_json"]) == payload
    assert json.loads(fact["quality_issues_json"]) == [
        "snapshot_key_fallback:type_mismatch:ts_code",
        f"type_mismatch:ts_code:{logical_type}",
    ]


def test_same_attempt_conflicting_snapshot_key_rejects_everything(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "facts.sqlite"
    _db(db_path)
    _, dataset, binding = _contract(tmp_path)

    with pytest.raises(ProviderNativeAdmissionError, match="conflicting payload"):
        ingest_provider_native_rows(
            db_path,
            dataset=dataset,
            binding=binding,
            rows=[_row(close=10.0), _row(close=11.0)],
            context=_context(dataset, binding),
        )

    with sqlite3.connect(db_path) as conn:
        assert (
            conn.execute("SELECT COUNT(*) FROM provider_dataset_rows").fetchone()[0]
            == 0
        )
        assert (
            conn.execute("SELECT COUNT(*) FROM market_ingest_runs").fetchone()[0] == 0
        )


def test_append_only_payload_identity_never_updates(tmp_path: Path) -> None:
    db_path = tmp_path / "facts.sqlite"
    _db(db_path)
    dataset_payload = generic_dataset(point_in_time="append_only")
    dataset_payload["read_model_adapter"]["row_key_strategy"] = "payload_hash"  # type: ignore[index]
    registry = load_dataset_registry(write_registry(tmp_path, dataset_payload))
    dataset = registry.datasets[0]
    binding = dataset.provider_bindings[0]

    first = ingest_provider_native_rows(
        db_path,
        dataset=dataset,
        binding=binding,
        rows=[_row(close=10.0)],
        context=_context(dataset, binding, 1),
    )
    second = ingest_provider_native_rows(
        db_path,
        dataset=dataset,
        binding=binding,
        rows=[_row(close=11.0)],
        context=_context(dataset, binding, 2),
    )
    third = ingest_provider_native_rows(
        db_path,
        dataset=dataset,
        binding=binding,
        rows=[_row(close=10.0)],
        context=_context(dataset, binding, 3),
    )

    assert first.counts.inserted == 1
    assert second.counts.inserted == 1
    assert third.counts.unchanged == 1
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT revision FROM provider_dataset_rows ORDER BY row_key"
        ).fetchall()
    assert rows == [(1,), (1,)]


def test_resource_budgets_fail_before_any_write(tmp_path: Path) -> None:
    db_path = tmp_path / "facts.sqlite"
    _db(db_path)
    dataset_payload = generic_dataset()
    dataset_payload["provider_bindings"][0]["max_payload_bytes_per_row"] = 40  # type: ignore[index]
    registry = load_dataset_registry(write_registry(tmp_path, dataset_payload))
    dataset = registry.datasets[0]
    binding = dataset.provider_bindings[0]

    with pytest.raises(ProviderNativeAdmissionError) as exc_info:
        ingest_provider_native_rows(
            db_path,
            dataset=dataset,
            binding=binding,
            rows=[_row(provider_new="x" * 100)],
            context=_context(dataset, binding),
        )

    assert exc_info.value.error_code == "resource_budget"
    with sqlite3.connect(db_path) as conn:
        assert (
            conn.execute("SELECT COUNT(*) FROM provider_dataset_rows").fetchone()[0]
            == 0
        )
        assert (
            conn.execute("SELECT COUNT(*) FROM market_ingest_runs").fetchone()[0] == 0
        )


@pytest.mark.parametrize(
    ("binding_change", "rows", "message"),
    [
        (
            {"max_rows_per_attempt": 1},
            [_row(ts_code="000001.SZ"), _row(ts_code="000002.SZ")],
            "max_rows_per_attempt",
        ),
        (
            {"max_batch_bytes": 100},
            [
                _row(ts_code="000001.SZ", provider_new="x" * 30),
                _row(ts_code="000002.SZ", provider_new="y" * 30),
            ],
            "max_batch_bytes",
        ),
        (
            {"max_nesting_depth": 1},
            [_row(provider_new={"nested": [1]})],
            "max_nesting_depth",
        ),
    ],
)
def test_all_registry_ingest_budgets_are_enforced_before_write(
    tmp_path: Path,
    binding_change: dict[str, int],
    rows: list[dict[str, object]],
    message: str,
) -> None:
    db_path = tmp_path / "facts.sqlite"
    _db(db_path)
    dataset_payload = generic_dataset()
    dataset_payload["provider_bindings"][0].update(binding_change)  # type: ignore[index,union-attr]
    registry = load_dataset_registry(write_registry(tmp_path, dataset_payload))
    dataset = registry.datasets[0]
    binding = dataset.provider_bindings[0]

    with pytest.raises(ProviderNativeAdmissionError, match=message):
        ingest_provider_native_rows(
            db_path,
            dataset=dataset,
            binding=binding,
            rows=rows,
            context=_context(dataset, binding),
        )

    with sqlite3.connect(db_path) as conn:
        assert (
            conn.execute("SELECT COUNT(*) FROM provider_dataset_rows").fetchone()[0]
            == 0
        )
        assert (
            conn.execute("SELECT COUNT(*) FROM market_ingest_runs").fetchone()[0] == 0
        )


def test_non_json_and_nonfinite_values_are_hard_admission_failures(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "facts.sqlite"
    _db(db_path)
    _, dataset, binding = _contract(tmp_path)

    for value in (("tuple",), float("nan")):
        with pytest.raises(ProviderNativeAdmissionError):
            ingest_provider_native_rows(
                db_path,
                dataset=dataset,
                binding=binding,
                rows=[_row(provider_new=value)],
                context=_context(dataset, binding),
            )

    with sqlite3.connect(db_path) as conn:
        assert (
            conn.execute("SELECT COUNT(*) FROM provider_dataset_rows").fetchone()[0]
            == 0
        )
        assert (
            conn.execute("SELECT COUNT(*) FROM market_ingest_runs").fetchone()[0] == 0
        )


def test_schema_major_is_a_physical_identity_boundary(tmp_path: Path) -> None:
    db_path = tmp_path / "facts.sqlite"
    _db(db_path)
    _, dataset_v2, binding_v2 = _contract(tmp_path)
    registry_v3 = load_dataset_registry(
        write_registry(tmp_path, generic_dataset(schema_version="3.0.0"))
    )
    dataset_v3 = registry_v3.datasets[0]
    binding_v3 = dataset_v3.provider_bindings[0]

    ingest_provider_native_rows(
        db_path,
        dataset=dataset_v2,
        binding=binding_v2,
        rows=[_row()],
        context=_context(dataset_v2, binding_v2, 1),
    )
    ingest_provider_native_rows(
        db_path,
        dataset=dataset_v3,
        binding=binding_v3,
        rows=[_row()],
        context=_context(dataset_v3, binding_v3, 2),
    )

    with sqlite3.connect(db_path) as conn:
        facts = conn.execute(
            "SELECT schema_major, ingested_schema_version FROM provider_dataset_rows ORDER BY schema_major"
        ).fetchall()
    assert facts == [(2, "2.1.0"), (3, "3.0.0")]


def test_missing_table_fails_closed_without_creating_it(tmp_path: Path) -> None:
    db_path = tmp_path / "facts.sqlite"
    _db(db_path, generic_table=False)
    _, dataset, binding = _contract(tmp_path)

    with pytest.raises(RuntimeError, match="provider_dataset_rows.*missing"):
        ingest_provider_native_rows(
            db_path,
            dataset=dataset,
            binding=binding,
            rows=[_row()],
            context=_context(dataset, binding),
        )

    with sqlite3.connect(db_path) as conn:
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='provider_dataset_rows'"
            ).fetchone()[0]
            == 0
        )
        assert (
            conn.execute("SELECT COUNT(*) FROM market_ingest_runs").fetchone()[0] == 0
        )


def test_receipt_insert_failure_rolls_back_fact_rows(tmp_path: Path) -> None:
    db_path = tmp_path / "facts.sqlite"
    _db(db_path)
    _, dataset, binding = _contract(tmp_path)
    with sqlite3.connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TRIGGER reject_generic_receipt
            BEFORE INSERT ON market_ingest_runs
            BEGIN
              SELECT RAISE(ABORT, 'receipt rejected');
            END;
            """
        )

    with pytest.raises(sqlite3.IntegrityError, match="receipt rejected"):
        ingest_provider_native_rows(
            db_path,
            dataset=dataset,
            binding=binding,
            rows=[_row()],
            context=_context(dataset, binding),
        )

    with sqlite3.connect(db_path) as conn:
        assert (
            conn.execute("SELECT COUNT(*) FROM provider_dataset_rows").fetchone()[0]
            == 0
        )
        assert (
            conn.execute("SELECT COUNT(*) FROM market_ingest_runs").fetchone()[0] == 0
        )


class _FixtureResponse:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload

    def read(self) -> bytes:
        return self.payload


class _RawEnvelopeCollector:
    def __init__(self, envelope: dict[str, object]) -> None:
        self.envelope = envelope
        self.calls: list[tuple[str, dict[str, str], str | None]] = []

    def collect_outcome(
        self,
        api_name: str,
        params: dict[str, str],
        fields: str | None = None,
        *,
        scan_budget: tushare_common.SensitiveScanBudget | None = None,
    ) -> tushare_common.ProviderCallOutcome:
        assert scan_budget is not None
        self.calls.append((api_name, params, fields))
        response = _FixtureResponse(
            json.dumps(self.envelope, ensure_ascii=False).encode("utf-8")
        )
        with (
            patch.object(
                tushare_common,
                "get_api_url",
                return_value="https://fixture.invalid",
            ),
            patch.object(
                tushare_common.urllib.request,
                "urlopen",
                return_value=response,
            ),
        ):
            return tushare_common.tushare_rows_outcome(
                api_name,
                "fixture-token",
                params=params,
                fields=fields or "",
                scan_budget=scan_budget,
            )


@pytest.mark.parametrize(
    ("envelope", "expected_status", "expected_error"),
    [
        (
            {
                "code": 0,
                "msg": "",
                "data": {
                    "fields": ["ts_code", "trade_date", "close", "sequence"],
                    "items": [],
                },
            },
            "empty",
            (),
        ),
        (
            {"code": -2001, "msg": "抱歉，您没有访问该接口的权限", "data": None},
            "failed",
            ("permission_denied",),
        ),
    ],
)
def test_provider_entry_resolves_request_and_writes_terminal_receipts(
    tmp_path: Path,
    envelope: dict[str, object],
    expected_status: str,
    expected_error: tuple[str, ...],
) -> None:
    db_path = tmp_path / "facts.sqlite"
    _db(db_path)
    registry, dataset, _ = _contract(tmp_path)
    collector = _RawEnvelopeCollector(envelope)

    result = collect_provider_native_dataset(
        db_path,
        registry=registry,
        collector=collector,
        dataset_id=dataset.dataset_id,
        request_window={"end_date": "20260717", "start_date": "20260701"},
        attempt_id="018f47de-0000-7000-8000-000000000001",
        started_at="2026-07-17T01:00:00+00:00",
    )

    assert result.status == expected_status
    assert result.errors == expected_error
    assert collector.calls == [
        (
            "synthetic_native",
            {"end_date": "20260717", "exchange": "SSE", "start_date": "20260701"},
            "ts_code,trade_date,close,sequence",
        )
    ]
    with sqlite3.connect(db_path) as conn:
        receipt = json.loads(
            conn.execute("SELECT notes FROM market_ingest_runs").fetchone()[0]
        )
    assert receipt["dataset_id"] == dataset.dataset_id
    assert receipt["provider"] == "tushare"
    assert receipt["provider_api"] == "synthetic_native"
    assert receipt["adapter_version"] == "tushare-provider-native.v1"
    assert receipt["request_window"] == {
        "end_date": "20260717",
        "start_date": "20260701",
    }
    assert receipt["data_through"] is None


def test_provider_entry_parses_raw_success_and_derives_data_through_from_rows(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "facts.sqlite"
    _db(db_path)
    registry, dataset, _ = _contract(tmp_path)
    collector = _RawEnvelopeCollector(
        {
            "code": 0,
            "msg": "",
            "data": {
                "fields": ["ts_code", "trade_date", "close", "sequence"],
                "items": [
                    ["000001.SZ", "20260717", 11.25, 1],
                    ["000002.SZ", "20260718", 22.5, 2],
                ],
            },
        }
    )

    result = collect_provider_native_dataset(
        db_path,
        registry=registry,
        collector=collector,
        dataset_id=dataset.dataset_id,
        request_window={"end_date": "20260731", "start_date": "20260701"},
        attempt_id="018f47de-0000-7000-8000-000000000001",
        started_at="2026-07-17T01:00:00+00:00",
    )

    assert result.status == "success"
    assert result.counts.inserted == 2
    with sqlite3.connect(db_path) as conn:
        receipt = json.loads(
            conn.execute("SELECT notes FROM market_ingest_runs").fetchone()[0]
        )
        payloads = [
            json.loads(row[0])
            for row in conn.execute(
                "SELECT payload_json FROM provider_dataset_rows ORDER BY row_key"
            ).fetchall()
        ]
    assert receipt["data_through"] == "20260718"
    assert sorted(payload["ts_code"] for payload in payloads) == [
        "000001.SZ",
        "000002.SZ",
    ]


@pytest.mark.parametrize(
    ("dataset_overrides", "fields", "items", "expected_data_through"),
    [
        (
            {"partition_field": "sequence"},
            ["ts_code", "close", "sequence"],
            [["000001.SZ", 11.25, 4], ["000002.SZ", 22.5, 7]],
            "7",
        ),
        (
            {
                "as_of_field": None,
                "as_of_format": None,
                "partition_field": None,
            },
            ["ts_code", "trade_date", "close", "sequence"],
            [["000001.SZ", "20260717", 11.25, 1]],
            "2026-07-17T01:00:00+00:00",
        ),
        (
            {},
            ["ts_code", "trade_date", "close", "sequence"],
            [["000001.SZ", "not-a-date", 11.25, 1]],
            None,
        ),
        (
            {},
            ["ts_code", "close", "sequence"],
            [["000001.SZ", 11.25, 1]],
            None,
        ),
        (
            {"as_of_format": "rfc3339", "partition_field": "sequence"},
            ["ts_code", "trade_date", "close", "sequence"],
            [["000001.SZ", "2026-07-17T01:02:03Z", 11.25, 9]],
            "2026-07-17T01:02:03Z",
        ),
        (
            {"as_of_format": "rfc3339", "partition_field": "sequence"},
            ["ts_code", "trade_date", "close", "sequence"],
            [["000001.SZ", "2026-07-17 01:02:03Z", 11.25, 9]],
            "9",
        ),
    ],
)
def test_provider_entry_data_through_uses_only_validated_row_time_fallbacks(
    tmp_path: Path,
    dataset_overrides: dict[str, object],
    fields: list[str],
    items: list[list[object]],
    expected_data_through: str | None,
) -> None:
    db_path = tmp_path / "facts.sqlite"
    _db(db_path)
    registry, dataset, _ = _contract(tmp_path, **dataset_overrides)
    collector = _RawEnvelopeCollector(
        {
            "code": 0,
            "msg": "",
            "data": {"fields": fields, "items": items},
        }
    )

    result = collect_provider_native_dataset(
        db_path,
        registry=registry,
        collector=collector,
        dataset_id=dataset.dataset_id,
        request_window={"end_date": "20991231", "start_date": "20990101"},
        attempt_id="018f47de-0000-7000-8000-000000000001",
        started_at="2026-07-17T01:00:00+00:00",
    )

    assert result.status == "success"
    with sqlite3.connect(db_path) as conn:
        notes = json.loads(
            conn.execute("SELECT notes FROM market_ingest_runs").fetchone()[0]
        )
    assert notes["data_through"] == expected_data_through
    assert notes["data_through"] not in {"20990101", "20991231"}


def test_provider_entry_conflicting_stable_key_writes_only_failed_receipt(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "facts.sqlite"
    _db(db_path)
    registry, dataset, _ = _contract(tmp_path)
    collector = _RawEnvelopeCollector(
        {
            "code": 0,
            "msg": "",
            "data": {
                "fields": ["ts_code", "trade_date", "close", "sequence"],
                "items": [
                    ["000001.SZ", "20260717", 11.25, 1],
                    ["000001.SZ", "20260717", 12.0, 1],
                ],
            },
        }
    )

    result = collect_provider_native_dataset(
        db_path,
        registry=registry,
        collector=collector,
        dataset_id=dataset.dataset_id,
        request_window={"end_date": "20260717", "start_date": "20260701"},
        attempt_id="018f47de-0000-7000-8000-000000000001",
        started_at="2026-07-17T01:00:00+00:00",
    )

    assert result.status == "failed"
    assert result.errors == ("validation_failed",)
    with sqlite3.connect(db_path) as conn:
        assert (
            conn.execute("SELECT COUNT(*) FROM provider_dataset_rows").fetchone()[0]
            == 0
        )
        receipts = conn.execute(
            "SELECT status, notes FROM market_ingest_runs"
        ).fetchall()
    assert len(receipts) == 1
    assert receipts[0][0] == "failed"
    assert json.loads(receipts[0][1])["errors"] == ["validation_failed"]


def test_provider_entry_records_storage_failure_without_partial_facts(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "facts.sqlite"
    _db(db_path)
    registry, dataset, _ = _contract(tmp_path)
    collector = _RawEnvelopeCollector(
        {
            "code": 0,
            "msg": "",
            "data": {
                "fields": ["ts_code", "trade_date", "close", "sequence"],
                "items": [["000001.SZ", "20260717", 11.25, 1]],
            },
        }
    )
    with sqlite3.connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TRIGGER reject_provider_native_fact
            BEFORE INSERT ON provider_dataset_rows
            BEGIN
              SELECT RAISE(ABORT, 'fact rejected');
            END;
            """
        )

    result = collect_provider_native_dataset(
        db_path,
        registry=registry,
        collector=collector,
        dataset_id=dataset.dataset_id,
        request_window={"end_date": "20260717", "start_date": "20260701"},
        attempt_id="018f47de-0000-7000-8000-000000000001",
        started_at="2026-07-17T01:00:00+00:00",
    )

    assert result.status == "failed"
    assert result.errors == ("storage_failed",)
    with sqlite3.connect(db_path) as conn:
        assert (
            conn.execute("SELECT COUNT(*) FROM provider_dataset_rows").fetchone()[0]
            == 0
        )
        receipts = conn.execute(
            "SELECT status, notes FROM market_ingest_runs"
        ).fetchall()
    assert len(receipts) == 1
    assert receipts[0][0] == "failed"
    notes = json.loads(receipts[0][1])
    assert notes["data_through"] is None
    assert notes["errors"] == ["storage_failed"]


def test_provider_entry_rejects_invalid_window_before_provider_or_sqlite(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "facts.sqlite"
    _db(db_path)
    registry, dataset, _ = _contract(tmp_path)
    collector = _RawEnvelopeCollector(
        {
            "code": 0,
            "msg": "",
            "data": {
                "fields": ["ts_code", "trade_date", "close", "sequence"],
                "items": [["000001.SZ", "20260717", 11.25, 1]],
            },
        }
    )

    with pytest.raises(ValueError, match="request_window"):
        collect_provider_native_dataset(
            db_path,
            registry=registry,
            collector=collector,
            dataset_id=dataset.dataset_id,
            request_window={"end_date": "20260717"},
            attempt_id="018f47de-0000-7000-8000-000000000001",
            started_at="2026-07-17T01:00:00+00:00",
        )

    assert collector.calls == []
    with sqlite3.connect(db_path) as conn:
        assert (
            conn.execute("SELECT COUNT(*) FROM provider_dataset_rows").fetchone()[0]
            == 0
        )
        assert (
            conn.execute("SELECT COUNT(*) FROM market_ingest_runs").fetchone()[0] == 0
        )

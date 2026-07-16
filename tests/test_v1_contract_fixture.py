from __future__ import annotations

import base64
from dataclasses import replace
from datetime import datetime, timezone
import json
import re
import sqlite3
from pathlib import Path
from typing import Any

import pytest

import storage.ingest_receipts as receipt_module
from catalog_service import CatalogFilters, CatalogService
from dataset_registry import DatasetRegistry, load_dataset_registry
from query_contract import QueryAccessContext, parse_query_request
from query_cursor import CursorExpectation, SignedCursorCodec
from query_service import QueryService
from storage.ingest_receipts import IngestContext
from storage.read_model_store import ingest_rows_with_receipts
from storage.schema import SCHEMA_SQL


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = ROOT / "tests/fixtures/sharedsignals_v1_query_contract.json"

PUBLIC_ROUTES = ["GET /v1/catalog", "POST /v1/query"]
SIGNING_KEY = b"contract-fixture-signing-key-32-bytes"
HEALTHY_NOW = datetime(2026, 7, 16, 8, 0, tzinfo=timezone.utc)
STALE_NOW = datetime(2026, 7, 20, 8, 0, tzinfo=timezone.utc)
CATALOG_RESPONSE_KEYS = {
    "api_version",
    "catalog_version",
    "request_id",
    "data",
    "next_cursor",
}
CATALOG_ROW_KEYS = {
    "dataset_id",
    "aliases",
    "domain",
    "market",
    "entity_type",
    "data_classification",
    "schema_version",
    "fields",
    "default_fields",
    "filter_operators",
    "sortable_fields",
    "default_order",
    "cadence",
    "timezone",
    "freshness_sla_seconds",
    "limits",
    "point_in_time",
    "required_scope",
    "quota_class",
    "availability",
    "queryability",
    "runtime",
}
FIELD_KEYS = {
    "name",
    "logical_type",
    "nullable",
    "selectable",
    "filterable",
    "sortable",
    "operators",
}
QUERY_REQUEST_KEYS = {
    "dataset_id",
    "schema_major",
    "fields",
    "filters",
    "as_of",
    "order",
    "limit",
    "cursor",
}
QUERY_RESPONSE_KEYS = {
    "api_version",
    "catalog_version",
    "request_id",
    "dataset_id",
    "schema_version",
    "data",
    "next_cursor",
    "metadata",
}
METADATA_KEYS = {
    "state",
    "runtime_state",
    "degraded",
    "freshness",
    "quality",
    "lineage",
    "receipt_id",
    "data_through",
    "observed_at",
    "requested_as_of",
    "resolved_as_of",
    "reasons",
}
LINEAGE_KEYS = {
    "state",
    "complete",
    "provider_neutral",
    "authority",
    "dataset_id",
    "providers",
    "receipt_watermark",
}


def _fixture() -> dict[str, Any]:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _active_daily_registry() -> DatasetRegistry:
    source = load_dataset_registry()
    daily = source.resolve("cn.equity.daily")
    active_binding = replace(
        daily.provider_bindings[0],
        entitlement_state="active",
        activation_state="active",
    )
    return DatasetRegistry(
        (replace(daily, provider_bindings=(active_binding,)),),
        query_defaults=source.query_defaults,
    )


def _create_read_model(path: Path) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.executescript(SCHEMA_SQL)
        conn.commit()
    finally:
        conn.close()


def _query_payload(*, market: str, limit: int) -> dict[str, Any]:
    return {
        "dataset_id": "cn.equity.daily",
        "schema_major": 1,
        "fields": ["market", "symbol", "trade_date", "close"],
        "filters": {
            "market": market,
            "trade_date": {"eq": "20260716"},
        },
        "as_of": None,
        "order": ["market:asc", "symbol:asc", "trade_date:asc"],
        "limit": limit,
        "cursor": None,
    }


@pytest.fixture
def real_contract_harness(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, Any]:
    db_path = (tmp_path / "marketdata.sqlite").absolute()
    maintenance_lock = tmp_path / "read_model_maintenance.lock"
    maintenance_lock.touch()
    monkeypatch.setenv(
        "SHAREDSIGNALS_MAINTENANCE_LOCK_FILE",
        str(maintenance_lock),
    )
    _create_read_model(db_path)

    finished_at = "2026-07-16T07:35:00+00:00"
    monkeypatch.setattr(receipt_module, "_utc_now", lambda: finished_at)
    ingest_result = ingest_rows_with_receipts(
        db_path,
        "market_bars_daily",
        [
            {
                "ts_code": "000001.SZ",
                "trade_date": "20260716",
                "open": 10.0,
                "high": 11.0,
                "low": 9.0,
                "close": 10.5,
                "vol": 1000.0,
                "amount": 10500.0,
                "collected_at": finished_at,
            },
            {
                "ts_code": "600519.SH",
                "trade_date": "20260716",
                "open": 1400.0,
                "high": 1425.0,
                "low": 1390.0,
                "close": 1418.88,
                "vol": 2000.0,
                "amount": 2837760.0,
                "collected_at": finished_at,
            },
        ],
        context=IngestContext(
            attempt_id="contract-fixture-daily-success",
            dataset_id="cn.equity.daily",
            provider="tushare",
            provider_api="daily",
            request_window={"trade_date": "20260716"},
            config_hash="a" * 64,
            adapter_version="tushare-direct-sqlite.v1",
            started_at="2026-07-16T07:30:00+00:00",
            data_through="20260716",
        ),
        source_name="contract_fixture_daily",
    )
    assert ingest_result.status == "success"
    assert ingest_result.counts.committed == 2
    assert len(ingest_result.receipt_ids) == 1

    registry = _active_daily_registry()
    codec = SignedCursorCodec(SIGNING_KEY)
    access = QueryAccessContext.from_grants(
        tenant_id="tenant-contract-fixture",
        scopes=("market_data",),
        allowed_dataset_ids=(),
    )
    catalog_service = CatalogService(
        registry=registry,
        db_path=db_path,
        cursor_codec=codec,
    )
    query_service = QueryService(
        db_path=db_path,
        registry=registry,
        cursor_codec=codec,
    )

    healthy_request = _query_payload(market="Ashare", limit=1)
    degraded_request = _query_payload(market="Ashare", limit=2)
    generated = {
        "public_routes": PUBLIC_ROUTES,
        "catalog_response": catalog_service.list_datasets(
            access=access,
            filters=CatalogFilters(),
            limit=1,
            cursor=None,
            now=HEALTHY_NOW,
            request_id="00000000-0000-4000-8000-000000000001",
        ),
        "healthy_query": {
            "request": healthy_request,
            "response": query_service.execute(
                parse_query_request(healthy_request),
                access=access,
                now=HEALTHY_NOW,
                request_id="00000000-0000-4000-8000-000000000002",
            ),
        },
        "degraded_query": {
            "request": degraded_request,
            "response": query_service.execute(
                parse_query_request(degraded_request),
                access=access,
                now=STALE_NOW,
                request_id="00000000-0000-4000-8000-000000000003",
            ),
        },
    }
    return {
        "access": access,
        "codec": codec,
        "fixture": generated,
        "query_service": query_service,
    }


def _unverified_cursor_payload(token: str) -> dict[str, Any]:
    payload_segment = token.split(".", 1)[0]
    padding = "=" * ((4 - len(payload_segment) % 4) % 4)
    return json.loads(
        base64.urlsafe_b64decode(payload_segment + padding).decode("utf-8")
    )


def test_fixture_has_complete_serializer_parity_with_real_vertical_slice(
    real_contract_harness: dict[str, Any],
) -> None:
    assert _fixture() == real_contract_harness["fixture"]


def test_fact_market_filter_and_real_cursor_cannot_drift_from_writer(
    real_contract_harness: dict[str, Any],
) -> None:
    generated = real_contract_harness["fixture"]
    query_service = real_contract_harness["query_service"]
    access = real_contract_harness["access"]
    codec = real_contract_harness["codec"]

    assert generated["catalog_response"]["data"][0]["market"] == "CN"
    assert generated["healthy_query"]["request"]["filters"]["market"] == "Ashare"

    cn_request = _query_payload(market="CN", limit=10)
    cn_response = query_service.execute(
        parse_query_request(cn_request),
        access=access,
        now=HEALTHY_NOW,
        request_id="00000000-0000-4000-8000-000000000004",
    )
    assert cn_response["data"] == []

    ashare_request = _query_payload(market="Ashare", limit=10)
    ashare_response = query_service.execute(
        parse_query_request(ashare_request),
        access=access,
        now=HEALTHY_NOW,
        request_id="00000000-0000-4000-8000-000000000005",
    )
    assert [row["market"] for row in ashare_response["data"]] == [
        "Ashare",
        "Ashare",
    ]

    healthy = generated["healthy_query"]["response"]
    token = healthy["next_cursor"]
    assert isinstance(token, str)
    payload = _unverified_cursor_payload(token)
    claims = codec.decode(
        token,
        expected=CursorExpectation(
            kind="query",
            catalog_version=healthy["catalog_version"],
            dataset_id=healthy["dataset_id"],
            schema_major=1,
            query_hash=payload["query_hash"],
            policy_id=access.policy_id,
            receipt_watermark=healthy["metadata"]["lineage"][
                "receipt_watermark"
            ],
        ),
        now=HEALTHY_NOW,
    )
    assert claims.receipt_watermark == healthy["metadata"]["lineage"][
        "receipt_watermark"
    ]
    assert claims.sort_key == (
        0,
        "Ashare",
        0,
        "000001.SZ",
        0,
        "20260716",
        1,
    )


def test_real_cursor_continuation_returns_exact_second_page_without_drift(
    real_contract_harness: dict[str, Any],
) -> None:
    generated = real_contract_harness["fixture"]
    page1_request = generated["healthy_query"]["request"]
    page1 = generated["healthy_query"]["response"]
    continuation_request = json.loads(json.dumps(page1_request))
    continuation_request["cursor"] = page1["next_cursor"]

    page2 = real_contract_harness["query_service"].execute(
        parse_query_request(continuation_request),
        access=real_contract_harness["access"],
        now=HEALTHY_NOW,
        request_id="00000000-0000-4000-8000-000000000006",
    )

    assert continuation_request == {
        **page1_request,
        "cursor": page1["next_cursor"],
    }
    page1_symbols = [row["symbol"] for row in page1["data"]]
    page2_symbols = [row["symbol"] for row in page2["data"]]
    combined_symbols = page1_symbols + page2_symbols

    assert page1_symbols == ["000001.SZ"]
    assert page2_symbols == ["600519.SH"]
    assert combined_symbols == ["000001.SZ", "600519.SH"]
    assert len(combined_symbols) == len(set(combined_symbols))
    assert page2["next_cursor"] is None
    assert page1["metadata"]["lineage"]["receipt_watermark"] == page2[
        "metadata"
    ]["lineage"]["receipt_watermark"]


def test_fixture_freezes_exact_public_routes_and_catalog_row() -> None:
    fixture = _fixture()

    assert set(fixture) == {
        "public_routes",
        "catalog_response",
        "healthy_query",
        "degraded_query",
    }
    assert fixture["public_routes"] == PUBLIC_ROUTES

    catalog = fixture["catalog_response"]
    assert set(catalog) == CATALOG_RESPONSE_KEYS
    assert catalog["api_version"] == "v1"
    assert len(catalog["data"]) == 1
    assert catalog["next_cursor"] is None

    row = catalog["data"][0]
    assert set(row) == CATALOG_ROW_KEYS
    assert row["dataset_id"] == "cn.equity.daily"
    assert row["market"] == "CN"
    assert row["schema_version"] == "1.0.0"
    assert all(set(field) == FIELD_KEYS for field in row["fields"])
    assert set(row["runtime"]) == {
        "state",
        "degraded",
        "data_through",
        "observed_at",
        "receipt_id",
        "reasons",
    }


def test_fixture_freezes_healthy_and_degraded_query_contracts() -> None:
    fixture = _fixture()
    catalog_version = fixture["catalog_response"]["catalog_version"]

    for name in ("healthy_query", "degraded_query"):
        example = fixture[name]
        assert set(example) == {"request", "response"}
        assert set(example["request"]) == QUERY_REQUEST_KEYS
        assert set(example["response"]) == QUERY_RESPONSE_KEYS
        assert example["request"]["dataset_id"] == "cn.equity.daily"
        assert example["request"]["schema_major"] == 1
        assert example["response"]["dataset_id"] == "cn.equity.daily"
        assert example["response"]["schema_version"] == "1.0.0"
        assert example["response"]["catalog_version"] == catalog_version
        assert example["request"]["filters"]["market"] == "Ashare"
        assert all(row["market"] == "Ashare" for row in example["response"]["data"])

        metadata = example["response"]["metadata"]
        assert set(metadata) == METADATA_KEYS
        assert set(metadata["freshness"]) == {
            "state",
            "stale",
            "sla_seconds",
        }
        assert set(metadata["quality"]) == {"state", "valid", "evidence"}
        assert set(metadata["lineage"]) == LINEAGE_KEYS
        assert metadata["freshness"]
        assert metadata["quality"]
        assert metadata["lineage"]
        assert metadata["lineage"]["provider_neutral"] is True
        assert metadata["lineage"]["authority"] == "sqlite_ingest_receipts"

    healthy = fixture["healthy_query"]["response"]
    assert healthy["data"]
    assert healthy["metadata"]["state"] == "ready"
    assert healthy["metadata"]["runtime_state"] == "success"
    assert healthy["metadata"]["degraded"] is False
    assert re.fullmatch(r"[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", healthy["next_cursor"])

    degraded = fixture["degraded_query"]["response"]
    assert degraded["data"]
    assert degraded["next_cursor"] is None
    assert degraded["metadata"]["state"] == "stale"
    assert degraded["metadata"]["runtime_state"] == "stale"
    assert degraded["metadata"]["degraded"] is True
    assert degraded["metadata"]["freshness"]["stale"] is True
    assert degraded["metadata"]["reasons"]


def test_fixture_contains_only_public_v1_wire_fields() -> None:
    serialized = json.dumps(_fixture(), ensure_ascii=False, sort_keys=True)

    for forbidden in (
        "primary_table",
        "target_tables",
        "provider_api",
        "adapter_version",
        "database_path",
        "query_hash",
        "policy_id",
        "sort_key",
        "expires_at",
        "__ss_rowid",
        "SELECT ",
    ):
        assert forbidden not in serialized

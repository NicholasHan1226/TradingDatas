from __future__ import annotations

from datetime import datetime, timezone
import http.client
import json
from pathlib import Path
import sqlite3
import threading
from types import SimpleNamespace
from typing import Any

import pytest
import yaml

import api_server
import auth
import collectors.tushare.collector as collector_module
import collectors.tushare.tushare_common as tushare_common
from catalog_service import CatalogService
from collectors.tushare.collector import TushareCollector
from collectors.tushare.provider_native_ingest import collect_provider_native_dataset
from dataset_registry import load_dataset_registry
from query_cursor import SignedCursorCodec
from query_service import QueryService
from storage.provider_dataset_rows import PROVIDER_DATASET_ROWS_DDL
from storage.schema import SCHEMA_SQL


SIGNING_KEY = b"provider-native-zero-code-signing-key"
TOKEN = "provider-native-zero-code-token"


def _registry_document() -> dict[str, object]:
    return {
        "version": 1,
        "query_defaults": {
            "max_request_bytes": 65_536,
            "max_response_bytes": 4_194_304,
            "max_page_size": 500,
            "max_lookback_days": 36_500,
            "max_selected_fields": 100,
            "max_filter_terms": 16,
            "max_in_values": 100,
            "max_order_terms": 8,
            "max_catalog_search_chars": 128,
            "cursor_ttl_seconds": 900,
            "sqlite_progress_steps": 1_000_000,
        },
        "datasets": [
            {
                "dataset_id": "cn.synthetic.zero_code",
                "aliases": ["tushare.synthetic_zero_code"],
                "domain": "reference",
                "market": "CN",
                "entity_type": "provider_row",
                "data_classification": "objective_factual",
                "schema_version": "2.0.0",
                "fields": [
                    {
                        "name": "ts_code",
                        "logical_type": "text",
                        "nullable": False,
                        "selectable": True,
                        "filterable": True,
                        "sortable": True,
                    },
                    {
                        "name": "trade_date",
                        "logical_type": "text",
                        "nullable": False,
                        "selectable": True,
                        "filterable": True,
                        "sortable": True,
                    },
                    {
                        "name": "large_native_integer",
                        "logical_type": "integer",
                        "nullable": True,
                        "selectable": True,
                        "filterable": False,
                        "sortable": False,
                    },
                    {
                        "name": "nullable_native",
                        "logical_type": "text",
                        "nullable": True,
                        "selectable": True,
                        "filterable": True,
                        "sortable": False,
                    },
                ],
                "primary_key": ["ts_code", "trade_date"],
                "default_projection": [
                    "ts_code",
                    "trade_date",
                    "large_native_integer",
                    "nullable_native",
                ],
                "as_of_field": "trade_date",
                "as_of_format": "yyyymmdd",
                "range_field": "trade_date",
                "partition_field": "trade_date",
                "cadence_class": "postclose",
                "timezone": "Asia/Shanghai",
                "freshness_sla_seconds": 86_400,
                "max_page_size": 500,
                "max_lookback_days": 3650,
                "point_in_time": "current_snapshot",
                "backfill_policy": "provider_limited",
                "empty_data_policy": "allowed",
                "required_scope": "market_data",
                "quota_class": "beta_standard",
                "provider_bindings": [
                    {
                        "provider": "tushare",
                        "api_name": "synthetic_zero_code",
                        "adapter_version": "tushare-provider-native.v1",
                        "read_discriminator_value": "tushare_synthetic_zero_code",
                        "entitlement_state": "active",
                        "activation_state": "active",
                        "target_tables": ["provider_dataset_rows"],
                        "request_template": {
                            "start_date": "${window.start_date}",
                            "end_date": "${window.end_date}",
                            "exchange": "SSE",
                        },
                        "requested_fields": [
                            "ts_code",
                            "trade_date",
                            "large_native_integer",
                            "nullable_native",
                        ],
                        "max_rows_per_attempt": 100,
                        "max_payload_bytes_per_row": 65_536,
                        "max_batch_bytes": 4_194_304,
                        "max_nesting_depth": 16,
                    }
                ],
                "read_model_adapter": {
                    "adapter_version": "provider-native-json.v1",
                    "primary_table": "provider_dataset_rows",
                    "fixed_field_filters": [],
                    "storage_kind": "provider_native_rows",
                    "row_key_strategy": "primary_key",
                },
            }
        ],
    }


def _create_registry(tmp_path: Path):
    path = tmp_path / "registry.yaml"
    path.write_text(
        yaml.safe_dump(_registry_document(), sort_keys=False), encoding="utf-8"
    )
    return load_dataset_registry(path)


def _create_database(path: Path) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.executescript(SCHEMA_SQL)
        conn.executescript(PROVIDER_DATASET_ROWS_DDL)
        conn.commit()
    finally:
        conn.close()


class _Response:
    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = json.dumps(
            payload,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        ).encode("utf-8")

    def read(self) -> bytes:
        return self._payload


def _token_hash(token: str) -> str:
    return auth._hash_token(token)  # noqa: SLF001 - exercise real token lookup


def _http_query(port: int, body: dict[str, object]) -> tuple[int, dict[str, Any]]:
    raw = json.dumps(body, separators=(",", ":")).encode("utf-8")
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    connection.request(
        "POST",
        "/v1/query",
        body=raw,
        headers={
            "Authorization": f"Bearer {TOKEN}",
            "Content-Type": "application/json",
            "Content-Length": str(len(raw)),
        },
    )
    response = connection.getresponse()
    payload = json.loads(response.read().decode("utf-8"))
    status = response.status
    connection.close()
    return status, payload


def test_registry_only_dataset_reaches_real_v1_query_losslessly(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = _create_registry(tmp_path)
    repository = Path(__file__).resolve().parents[1]
    for implementation in (
        "dataset_registry.py",
        "storage/provider_dataset_rows.py",
        "collectors/tushare/provider_native_ingest.py",
        "query_service.py",
        "catalog_service.py",
        "api_server.py",
    ):
        assert "synthetic_zero_code" not in (repository / implementation).read_text(
            encoding="utf-8"
        )
    database = tmp_path / "marketdata.sqlite"
    _create_database(database)
    captured_request: dict[str, object] = {}
    large_integer = 2**70

    def urlopen(request: object, timeout: float) -> _Response:
        assert timeout == 30
        raw_data = getattr(request, "data")
        assert isinstance(raw_data, bytes)
        captured_request.update(json.loads(raw_data.decode("utf-8")))
        return _Response(
            {
                "code": 0,
                "msg": None,
                "data": {
                    "fields": [
                        "ts_code",
                        "trade_date",
                        "large_native_integer",
                        "nullable_native",
                        "provider_added_without_registry_change",
                    ],
                    "items": [
                        [
                            "600000.SH",
                            "20260717",
                            large_integer,
                            None,
                            {"nested": [1, "原样保留"]},
                        ]
                    ],
                },
            }
        )

    monkeypatch.setattr(tushare_common.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(tushare_common, "get_api_url", lambda: "https://invalid.test")
    monkeypatch.setattr(
        collector_module,
        "_TUSHARE_CALL",
        lambda api_name, params, fields: tushare_common.tushare_rows_outcome(
            api_name,
            "synthetic-provider-token",
            params=params,
            fields=fields,
        ),
    )
    TushareCollector._rate_calls.clear()

    started_at = datetime.now(timezone.utc).isoformat()
    result = collect_provider_native_dataset(
        database,
        registry=registry,
        collector=TushareCollector(),
        dataset_id="cn.synthetic.zero_code",
        request_window={"start_date": "20260717", "end_date": "20260717"},
        attempt_id="zero-code-attempt-1",
        started_at=started_at,
    )
    assert result.status == "success"
    assert captured_request == {
        "api_name": "synthetic_zero_code",
        "token": "synthetic-provider-token",
        "params": {
            "end_date": "20260717",
            "exchange": "SSE",
            "start_date": "20260717",
        },
        "fields": ("ts_code,trade_date,large_native_integer,nullable_native"),
    }

    conn = sqlite3.connect(database)
    try:
        stored = conn.execute(
            "SELECT payload_json, quality_state, quality_issues_json "
            "FROM provider_dataset_rows"
        ).fetchone()
        receipt = conn.execute(
            "SELECT status, notes FROM market_ingest_runs WHERE status = 'success'"
        ).fetchone()
    finally:
        conn.close()
    assert stored is not None
    payload = json.loads(stored[0])
    assert payload == {
        "large_native_integer": large_integer,
        "nullable_native": None,
        "provider_added_without_registry_change": {"nested": [1, "原样保留"]},
        "trade_date": "20260717",
        "ts_code": "600000.SH",
    }
    assert stored[1] == "degraded"
    assert "unknown_field:provider_added_without_registry_change" in json.loads(
        stored[2]
    )
    assert receipt is not None and receipt[0] == "success"
    receipt_notes = json.loads(receipt[1])
    assert receipt_notes["data_through"] == "20260717"

    maintenance_lock = tmp_path / "read_model_maintenance.lock"
    maintenance_lock.touch()
    (tmp_path / f".{database.name}.read_model_store.lock").touch()
    monkeypatch.setenv("SHAREDSIGNALS_MAINTENANCE_LOCK_FILE", str(maintenance_lock))

    codec = SignedCursorCodec(SIGNING_KEY)
    query = QueryService(db_path=database, registry=registry, cursor_codec=codec)
    catalog = CatalogService(db_path=database, registry=registry, cursor_codec=codec)
    monkeypatch.setattr(
        auth,
        "_TOKEN_HASHES",
        {
            _token_hash(TOKEN): {
                "tenant_id": "zero-code-tenant",
                "tier": "internal",
                "scopes": ["market_data"],
                "auth_method": "token_hash",
            }
        },
    )
    monkeypatch.setattr(auth, "LOCALHOST_BYPASS", False)
    monkeypatch.setattr(auth, "RATE_LIMITS", {**auth.RATE_LIMITS, "internal": None})
    monkeypatch.setattr(
        auth,
        "CONCURRENCY_LIMITS",
        {**auth.CONCURRENCY_LIMITS, "internal": None},
    )
    monkeypatch.setattr(auth, "_REQUEST_LOG", auth.OrderedDict())
    monkeypatch.setattr(auth, "_ACTIVE_REQUESTS", {})
    monkeypatch.setattr(auth, "_DEDUP_CACHE", auth.OrderedDict())
    monkeypatch.setattr(api_server, "auth", auth)
    monkeypatch.setattr(api_server, "reader", SimpleNamespace())
    monkeypatch.setattr(
        api_server, "_build_v1_services", lambda: (catalog, query), raising=False
    )

    server = api_server.SharedSignalsHTTPServer(
        ("127.0.0.1", 0), api_server.Handler, request_timeout=5, max_threads=4
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        status, response = _http_query(
            int(server.server_address[1]),
            {"dataset_id": "cn.synthetic.zero_code", "schema_major": 2},
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert status == 200, response
    expected_data = [
        {
            "ts_code": "600000.SH",
            "trade_date": "20260717",
            "large_native_integer": large_integer,
            "nullable_native": None,
        }
    ]
    if response["data"] != expected_data:
        pytest.fail(json.dumps(response, ensure_ascii=False, indent=2))
    assert response["metadata"]["runtime_state"] == "success"
    assert response["metadata"]["data_through"] == "2026-07-17T00:00:00+08:00"
    assert response["metadata"]["degraded"] is True
    assert "payload_json" not in response["data"][0]
    assert "receipt_id" not in response["data"][0]

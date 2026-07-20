from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
import http.client
import json
from pathlib import Path
import sqlite3
import threading
from typing import Any

import pytest
import yaml

import api_server
import auth
import collectors.tushare.collector as collector_module
import collectors.tushare.tushare_common as tushare_common
import storage.ingest_receipts as receipt_module
from catalog_service import CatalogService
from collectors.tushare.collector import TushareCollector
from collectors.tushare.provider_native_ingest import collect_provider_native_dataset
from dataset_registry import DatasetRegistry, load_dataset_registry
from query_cursor import SignedCursorCodec
from query_service import QueryService
from storage.schema import SCHEMA_SQL
from storage.schema_contract import PROVIDER_DATASET_ROWS_DDL


SIGNING_KEY = b"provider-native-zero-code-signing-key"
TOKEN = "provider-native-zero-code-token"
TARGET_REGISTRY_PATH = (
    Path(__file__).resolve().parents[1]
    / "config"
    / "provider_native_dataset_registry.yaml"
)
REQUEST_PROFILES_PATH = (
    Path(__file__).resolve().parents[1] / "config" / "tushare_request_profiles.v1.yaml"
)


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
                        "request_shape": "snapshot_or_date_range",
                        "request_template": {
                            "start_date": "${window.start_date}",
                            "end_date": "${window.end_date}",
                            "exchange": "SSE",
                        },
                        "fanout": {"strategy": "none"},
                        "pagination": {"strategy": "none"},
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


def test_request_profiles_do_not_activate_or_generate_dataset_specific_runtime():
    profiles = yaml.safe_load(REQUEST_PROFILES_PATH.read_text(encoding="utf-8"))
    registry = yaml.safe_load(TARGET_REGISTRY_PATH.read_text(encoding="utf-8"))
    profile_apis = {
        api_name
        for group in profiles["groups"].values()
        for api_name in group["api_names"]
    }
    bindings = {
        dataset["provider_bindings"][0]["api_name"]: dataset["provider_bindings"][0]
        for dataset in registry["datasets"]
    }

    assert len(profile_apis) == 187
    assert profile_apis.isdisjoint({"daily", "stock_basic", "trade_cal"})
    assert all(bindings[api]["entitlement_state"] == "unknown" for api in profile_apis)
    assert all(bindings[api]["activation_state"] == "paused" for api in profile_apis)
    assert all(bindings[api]["request_template"] == {} for api in profile_apis)


def _create_registry(tmp_path: Path):
    path = tmp_path / "registry.yaml"
    path.write_text(
        yaml.safe_dump(_registry_document(), sort_keys=False), encoding="utf-8"
    )
    return load_dataset_registry(path)


def _active_target_registry(dataset_id: str) -> DatasetRegistry:
    source = load_dataset_registry(TARGET_REGISTRY_PATH)
    dataset = source.resolve(dataset_id)
    binding = replace(
        dataset.provider_bindings[0],
        entitlement_state="active",
        activation_state="active",
    )
    return DatasetRegistry(
        (replace(dataset, provider_bindings=(binding,)),),
        query_defaults=source.query_defaults,
    )


def _active_stock_basic_scan_registry() -> DatasetRegistry:
    """Activate the real 17-field contract without truncation semantics.

    This fixture isolates the transport scan capacity from the production
    snapshot completeness rule that intentionally rejects an exact provider
    page limit as potentially truncated.
    """

    source = load_dataset_registry(TARGET_REGISTRY_PATH)
    dataset = source.resolve("cn.equity.security_master")
    binding = dataset.provider_bindings[0]
    assert binding.response_completeness is not None
    binding = replace(
        binding,
        entitlement_state="active",
        activation_state="active",
        response_completeness=replace(
            binding.response_completeness,
            reject_at_row_limit=False,
        ),
    )
    return DatasetRegistry(
        (replace(dataset, provider_bindings=(binding,)),),
        query_defaults=source.query_defaults,
    )


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

    def read(self, size: int = -1) -> bytes:
        return self._payload if size < 0 else self._payload[:size]


def test_registry_scan_budget_accepts_approved_6000_by_17_with_singular_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = _active_stock_basic_scan_registry()
    dataset = registry.resolve("cn.equity.security_master")
    binding = registry.provider_binding(dataset.dataset_id, "tushare")
    fields = [field.name for field in dataset.fields]
    assert len(fields) == 17
    assert binding.requested_fields == tuple(fields)
    assert binding.max_rows_per_attempt == 6000
    items = [
        [
            f"{index:06d}.SZ",
            f"{index:06d}",
            f"name-{index}",
            "Shenzhen",
            "industry",
            f"full-name-{index}",
            f"english-name-{index}",
            f"spell-{index}",
            "主板",
            "SZSE",
            "CNY",
            "L",
            "20200101",
            None,
            "N",
            "controller",
            "company",
        ]
        for index in range(binding.max_rows_per_attempt)
    ]
    database = tmp_path / "marketdata.sqlite"
    _create_database(database)
    observed_scan_budgets: list[tushare_common.SensitiveScanBudget | None] = []
    observed_requested_fields: list[str | None] = []

    monkeypatch.setattr(
        tushare_common,
        "_provider_urlopen",
        lambda _request, timeout: (
            _Response(
                {
                    "code": 0,
                    "msg": None,
                    "data": {"fields": fields, "items": items},
                }
            )
            if timeout == 30
            else pytest.fail("unexpected provider timeout")
        ),
    )
    monkeypatch.setattr(
        tushare_common, "get_api_url", lambda: "https://api.quicksync.cn"
    )

    def provider_call(
        api_name: str,
        params: dict[str, object],
        requested_fields: str | None,
        scan_budget: tushare_common.SensitiveScanBudget | None = None,
    ) -> tushare_common.ProviderCallOutcome:
        observed_scan_budgets.append(scan_budget)
        observed_requested_fields.append(requested_fields)
        return tushare_common.tushare_rows_outcome(
            api_name,
            "synthetic-provider-token",
            params=params,
            fields=requested_fields,
            scan_budget=scan_budget,
        )

    monkeypatch.setattr(collector_module, "_TUSHARE_CALL", provider_call)

    result = collect_provider_native_dataset(
        database,
        registry=registry,
        collector=TushareCollector(),
        dataset_id=dataset.dataset_id,
        request_window={},
        attempt_id="stock-basic-approved-scan-budget",
        started_at="2026-07-18T01:00:00+00:00",
    )

    assert result.status == "success"
    assert result.counts.committed == 6000
    assert observed_requested_fields == [",".join(fields)]
    assert len(observed_scan_budgets) == 1
    assert isinstance(
        observed_scan_budgets[0],
        tushare_common.SensitiveScanBudget,
    )
    assert observed_scan_budgets[0].max_nodes > 210_001
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM provider_dataset_rows"
        ).fetchone() == (6000,)
        receipt = connection.execute(
            "SELECT status, rows_written, notes FROM market_ingest_runs"
        ).fetchone()
    assert receipt is not None
    assert receipt[:2] == ("success", 6000)
    receipt_payload = json.loads(receipt[2])
    assert receipt_payload["errors"] == []
    assert receipt_payload["request_identity"]["request_variant"] == {
        "list_status": "L"
    }


def test_registry_scan_budget_hard_cap_fails_before_provider_call(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _active_stock_basic_scan_registry()
    dataset = source.resolve("cn.equity.security_master")
    binding = replace(
        source.provider_binding(dataset.dataset_id, "tushare"),
        max_rows_per_attempt=50_000,
    )
    registry = DatasetRegistry(
        (replace(dataset, provider_bindings=(binding,)),),
        query_defaults=source.query_defaults,
    )
    database = tmp_path / "marketdata.sqlite"
    _create_database(database)
    provider_called = False

    def provider_call(*_args: object, **_kwargs: object) -> None:
        nonlocal provider_called
        provider_called = True
        pytest.fail("provider must not be called for an excessive scan budget")

    monkeypatch.setattr(collector_module, "_TUSHARE_CALL", provider_call)

    with pytest.raises(ValueError, match="scan node budget exceeds"):
        collect_provider_native_dataset(
            database,
            registry=registry,
            collector=TushareCollector(),
            dataset_id=dataset.dataset_id,
            request_window={},
            attempt_id="stock-basic-excessive-scan-budget",
            started_at="2026-07-18T01:00:00+00:00",
        )

    assert provider_called is False
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM provider_dataset_rows"
        ).fetchone() == (0,)
        assert connection.execute(
            "SELECT COUNT(*) FROM market_ingest_runs"
        ).fetchone() == (0,)


def test_legacy_collect_outcome_keeps_three_argument_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: list[tuple[str, dict[str, object], str | None]] = []

    def legacy_call(
        api_name: str,
        params: dict[str, object],
        fields: str | None,
    ) -> tushare_common.ProviderCallOutcome:
        observed.append((api_name, params, fields))
        return tushare_common.ProviderCallOutcome(
            state="empty",
            rows=(),
            provider_code=0,
            error_code=None,
            error_message=None,
        )

    monkeypatch.setattr(collector_module, "_TUSHARE_CALL", legacy_call)

    outcome = TushareCollector().collect_outcome("daily", {}, None)

    assert outcome.state == "empty"
    assert observed == [("daily", {}, None)]


@pytest.mark.parametrize("secret_row_index", [0, 1, 2], ids=["first", "middle", "last"])
def test_registry_scan_budget_rejects_provider_token_at_any_row_position(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    secret_row_index: int,
) -> None:
    registry = _create_registry(tmp_path)
    dataset = registry.resolve("cn.synthetic.zero_code")
    fields = [field.name for field in dataset.fields]
    provider_token = "provider-secret-must-not-cross-boundary"
    items: list[list[object]] = [
        [f"{index:06d}.SZ", "20260717", index, f"safe-{index}"] for index in range(3)
    ]
    items[secret_row_index][-1] = provider_token
    database = tmp_path / "marketdata.sqlite"
    _create_database(database)

    monkeypatch.setattr(
        tushare_common,
        "_provider_urlopen",
        lambda _request, timeout: (
            _Response(
                {
                    "code": 0,
                    "msg": None,
                    "data": {"fields": fields, "items": items},
                }
            )
            if timeout == 30
            else pytest.fail("unexpected provider timeout")
        ),
    )
    monkeypatch.setattr(
        tushare_common, "get_api_url", lambda: "https://api.quicksync.cn"
    )

    def provider_call(
        api_name: str,
        params: dict[str, object],
        requested_fields: str | None,
        scan_budget: tushare_common.SensitiveScanBudget | None = None,
    ) -> tushare_common.ProviderCallOutcome:
        return tushare_common.tushare_rows_outcome(
            api_name,
            provider_token,
            params=params,
            fields=requested_fields,
            scan_budget=scan_budget,
        )

    monkeypatch.setattr(collector_module, "_TUSHARE_CALL", provider_call)

    result = collect_provider_native_dataset(
        database,
        registry=registry,
        collector=TushareCollector(),
        dataset_id=dataset.dataset_id,
        request_window={"end_date": "20260717", "start_date": "20260717"},
        attempt_id=f"provider-token-{secret_row_index}",
        started_at="2026-07-18T01:00:00+00:00",
    )

    assert result.status == "failed"
    assert result.errors == ("provider_error",)
    assert provider_token not in repr(result)
    assert provider_token not in caplog.text
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM provider_dataset_rows"
        ).fetchone() == (0,)
        receipts = connection.execute(
            "SELECT status, notes FROM market_ingest_runs"
        ).fetchall()
    assert len(receipts) == 1
    assert receipts[0][0] == "failed"
    assert provider_token not in receipts[0][1]


def test_provider_native_row_overflow_writes_failed_receipt_without_facts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = _create_registry(tmp_path)
    dataset = registry.resolve("cn.synthetic.zero_code")
    binding = registry.provider_binding(dataset.dataset_id, "tushare")
    assert binding.max_rows_per_attempt == 100
    fields = [field.name for field in dataset.fields]
    items = [
        [f"{index:06d}.SZ", "20260717", index, None]
        for index in range(binding.max_rows_per_attempt + 1)
    ]
    database = tmp_path / "marketdata.sqlite"
    _create_database(database)

    monkeypatch.setattr(
        tushare_common,
        "_provider_urlopen",
        lambda _request, timeout: (
            _Response(
                {
                    "code": 0,
                    "msg": None,
                    "data": {"fields": fields, "items": items},
                }
            )
            if timeout == 30
            else pytest.fail("unexpected provider timeout")
        ),
    )
    monkeypatch.setattr(
        tushare_common, "get_api_url", lambda: "https://api.quicksync.cn"
    )

    def provider_call(
        api_name: str,
        params: dict[str, object],
        requested_fields: str | None,
        scan_budget: tushare_common.SensitiveScanBudget | None = None,
    ) -> tushare_common.ProviderCallOutcome:
        return tushare_common.tushare_rows_outcome(
            api_name,
            "synthetic-provider-token",
            params=params,
            fields=requested_fields,
            scan_budget=scan_budget,
        )

    monkeypatch.setattr(collector_module, "_TUSHARE_CALL", provider_call)

    result = collect_provider_native_dataset(
        database,
        registry=registry,
        collector=TushareCollector(),
        dataset_id=dataset.dataset_id,
        request_window={"end_date": "20260717", "start_date": "20260717"},
        attempt_id="provider-row-overflow",
        started_at="2026-07-18T01:00:00+00:00",
    )

    assert result.status == "failed"
    assert result.errors == ("resource_budget",)
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM provider_dataset_rows"
        ).fetchone() == (0,)
        receipts = connection.execute(
            "SELECT status, notes FROM market_ingest_runs"
        ).fetchall()
    assert len(receipts) == 1
    assert receipts[0][0] == "failed"
    assert json.loads(receipts[0][1])["errors"] == ["resource_budget"]


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
    # 04:00 UTC is 12:00 Asia/Shanghai on 2026-07-17, within the 24-hour SLA.
    frozen_now = datetime(2026, 7, 17, 4, tzinfo=timezone.utc)

    class FrozenApiClock:
        @classmethod
        def now(cls, requested_timezone: object = None) -> datetime:
            assert requested_timezone is timezone.utc
            return frozen_now

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

    monkeypatch.setattr(tushare_common, "_provider_urlopen", urlopen)
    monkeypatch.setattr(
        tushare_common, "get_api_url", lambda: "https://api.quicksync.cn"
    )
    monkeypatch.setattr(
        collector_module,
        "_TUSHARE_CALL",
        lambda api_name, params, fields, scan_budget=None: (
            tushare_common.tushare_rows_outcome(
                api_name,
                "synthetic-provider-token",
                params=params,
                fields=fields,
                scan_budget=scan_budget,
            )
        ),
    )

    monkeypatch.setattr(receipt_module, "_utc_now", lambda: frozen_now.isoformat())
    started_at = frozen_now.isoformat()
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
                "scopes": ["query", "market_data"],
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
    monkeypatch.setattr(api_server, "datetime", FrozenApiClock)
    monkeypatch.setattr(
        api_server, "_build_v1_services", lambda: (catalog, query), raising=False
    )

    server = api_server.TradingDatasHTTPServer(
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
            "provider_added_without_registry_change": {"nested": [1, "原样保留"]},
        }
    ]
    if response["data"] != expected_data:
        pytest.fail(json.dumps(response, ensure_ascii=False, indent=2))
    assert response["metadata"]["runtime_state"] == "success"
    assert response["metadata"]["data_through"] == "2026-07-17T00:00:00+08:00"
    assert response["metadata"]["degraded"] is True
    assert "payload_json" not in response["data"][0]
    assert "receipt_id" not in response["data"][0]


@pytest.mark.parametrize(
    ("dataset_id", "request_window", "row", "expected_params"),
    [
        pytest.param(
            "cn.equity.daily",
            {"trade_date": "20260717"},
            {
                "ts_code": "600000.SH",
                "trade_date": "20260717",
                "open": 10.0,
                "high": 10.8,
                "low": 9.9,
                "close": 10.5,
                "pre_close": 9.8,
                "change": 0.7,
                "pct_chg": 7.1429,
                "vol": 123456.0,
                "amount": 1296296.0,
                "ah_vol": 12.0,
                "ah_amount": 126.0,
            },
            {"trade_date": "20260717"},
            id="daily-all-13-fields",
        ),
    ],
)
def test_target_contract_requests_all_declared_fields_and_complete_response_is_valid(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    dataset_id: str,
    request_window: dict[str, str],
    row: dict[str, object],
    expected_params: dict[str, str],
) -> None:
    registry = _active_target_registry(dataset_id)
    dataset = registry.resolve(dataset_id)
    binding = registry.provider_binding(dataset_id, "tushare")
    declared_fields = [field.name for field in dataset.fields]
    database = tmp_path / "marketdata.sqlite"
    _create_database(database)
    captured_request: dict[str, object] = {}

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
                    "fields": declared_fields,
                    "items": [[row[field] for field in declared_fields]],
                },
            }
        )

    monkeypatch.setattr(tushare_common, "_provider_urlopen", urlopen)
    monkeypatch.setattr(
        tushare_common, "get_api_url", lambda: "https://api.quicksync.cn"
    )
    monkeypatch.setattr(
        collector_module,
        "_TUSHARE_CALL",
        lambda api_name, params, requested_fields, scan_budget=None: (
            tushare_common.tushare_rows_outcome(
                api_name,
                "synthetic-provider-token",
                params=params,
                fields=requested_fields,
                scan_budget=scan_budget,
            )
        ),
    )

    result = collect_provider_native_dataset(
        database,
        registry=registry,
        collector=TushareCollector(),
        dataset_id=dataset_id,
        request_window=request_window,
        attempt_id=f"{dataset_id}-complete-response",
        started_at="2026-07-17T04:00:00+00:00",
    )

    assert result.status == "success"
    assert captured_request == {
        "api_name": binding.api_name,
        "token": "synthetic-provider-token",
        "params": expected_params,
        "fields": ",".join(declared_fields),
    }
    with sqlite3.connect(database) as connection:
        stored = connection.execute(
            "SELECT quality_state, quality_issues_json FROM provider_dataset_rows"
        ).fetchone()
    assert stored == ("valid", "[]")
    assert not any(
        issue.startswith("missing_field:") for issue in json.loads(stored[1])
    )


@pytest.mark.parametrize(
    ("dataset_id", "request_window", "fields", "items", "expected_params"),
    [
        pytest.param(
            "cn.equity.daily",
            {"trade_date": "20260717"},
            [
                "ts_code",
                "trade_date",
                "close",
                "provider_added_without_registry_change",
            ],
            [["600000.SH", "20260717", 10.5, {"nested": [1, "原样保留"]}]],
            {"trade_date": "20260717"},
            id="single-partition",
        ),
    ],
)
def test_target_contracts_reach_local_v1_query_with_lossless_degraded_payload(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    dataset_id: str,
    request_window: dict[str, str],
    fields: list[str],
    items: list[list[object]],
    expected_params: dict[str, str],
) -> None:
    registry = _active_target_registry(dataset_id)
    dataset = registry.resolve(dataset_id)
    database = tmp_path / "marketdata.sqlite"
    _create_database(database)
    captured_request: dict[str, object] = {}
    frozen_now = datetime(2026, 7, 17, 4, tzinfo=timezone.utc)

    class FrozenApiClock:
        @classmethod
        def now(cls, requested_timezone: object = None) -> datetime:
            assert requested_timezone is timezone.utc
            return frozen_now

    def urlopen(request: object, timeout: float) -> _Response:
        assert timeout == 30
        raw_data = getattr(request, "data")
        assert isinstance(raw_data, bytes)
        captured_request.update(json.loads(raw_data.decode("utf-8")))
        return _Response(
            {
                "code": 0,
                "msg": None,
                "data": {"fields": fields, "items": items},
            }
        )

    monkeypatch.setattr(tushare_common, "_provider_urlopen", urlopen)
    monkeypatch.setattr(
        tushare_common, "get_api_url", lambda: "https://api.quicksync.cn"
    )
    monkeypatch.setattr(
        collector_module,
        "_TUSHARE_CALL",
        lambda api_name, params, requested_fields, scan_budget=None: (
            tushare_common.tushare_rows_outcome(
                api_name,
                "synthetic-provider-token",
                params=params,
                fields=requested_fields,
                scan_budget=scan_budget,
            )
        ),
    )
    monkeypatch.setattr(receipt_module, "_utc_now", lambda: frozen_now.isoformat())

    result = collect_provider_native_dataset(
        database,
        registry=registry,
        collector=TushareCollector(),
        dataset_id=dataset_id,
        request_window=request_window,
        attempt_id=f"{dataset_id}-success",
        started_at=frozen_now.isoformat(),
    )

    assert result.status == "success"
    assert captured_request["params"] == expected_params
    assert captured_request["fields"] == ",".join(
        field.name for field in dataset.fields
    )
    conn = sqlite3.connect(database)
    try:
        stored = conn.execute(
            "SELECT payload_json, quality_state FROM provider_dataset_rows"
        ).fetchone()
        receipt = conn.execute(
            "SELECT status, notes FROM market_ingest_runs"
        ).fetchone()
    finally:
        conn.close()
    assert stored is not None
    assert json.loads(stored[0])["provider_added_without_registry_change"] == {
        "nested": [1, "原样保留"]
    }
    assert stored[1] == "degraded"
    assert receipt is not None and receipt[0] == "success"
    assert json.loads(receipt[1])["request_window"] == request_window

    query = QueryService(
        db_path=database,
        registry=registry,
        cursor_codec=SignedCursorCodec(SIGNING_KEY),
    )
    catalog = CatalogService(
        db_path=database,
        registry=registry,
        cursor_codec=SignedCursorCodec(SIGNING_KEY),
    )
    monkeypatch.setattr(
        tushare_common,
        "_provider_urlopen",
        lambda *_args, **_kwargs: pytest.fail("V1 query must not call the provider"),
    )
    monkeypatch.setattr(
        auth,
        "_TOKEN_HASHES",
        {
            _token_hash(TOKEN): {
                "tenant_id": "zero-code-tenant",
                "tier": "internal",
                "scopes": ["query", "market_data"],
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
    monkeypatch.setattr(api_server, "datetime", FrozenApiClock)
    monkeypatch.setattr(
        api_server, "_build_v1_services", lambda: (catalog, query), raising=False
    )

    server = api_server.TradingDatasHTTPServer(
        ("127.0.0.1", 0), api_server.Handler, request_timeout=5, max_threads=4
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        status, response = _http_query(
            int(server.server_address[1]),
            {"dataset_id": dataset_id, "schema_major": 2},
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert status == 200, response
    assert response["metadata"]["runtime_state"] == "success"
    assert response["metadata"]["degraded"] is True
    assert response["data"][0]["provider_added_without_registry_change"] == {
        "nested": [1, "原样保留"]
    }


@pytest.mark.parametrize(
    ("response", "expected_status", "expected_receipt"),
    [
        pytest.param(
            {"code": 0, "msg": None, "data": {"fields": ["ts_code"], "items": []}},
            "empty",
            "empty",
            id="allowed-empty",
        ),
        pytest.param(
            {"code": -2001, "msg": "permission denied", "data": None},
            "failed",
            "failed",
            id="provider-failed",
        ),
    ],
)
def test_daily_target_contract_preserves_empty_and_failed_receipt_truth(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    response: dict[str, object],
    expected_status: str,
    expected_receipt: str,
) -> None:
    registry = _active_target_registry("cn.equity.daily")
    database = tmp_path / "marketdata.sqlite"
    _create_database(database)
    captured_request: dict[str, object] = {}

    def urlopen(request: object, timeout: float) -> _Response:
        assert timeout == 30
        raw_data = getattr(request, "data")
        assert isinstance(raw_data, bytes)
        captured_request.update(json.loads(raw_data.decode("utf-8")))
        return _Response(response)

    monkeypatch.setattr(tushare_common, "_provider_urlopen", urlopen)
    monkeypatch.setattr(
        tushare_common, "get_api_url", lambda: "https://api.quicksync.cn"
    )
    monkeypatch.setattr(
        collector_module,
        "_TUSHARE_CALL",
        lambda api_name, params, requested_fields, scan_budget=None: (
            tushare_common.tushare_rows_outcome(
                api_name,
                "synthetic-provider-token",
                params=params,
                fields=requested_fields,
                scan_budget=scan_budget,
            )
        ),
    )

    result = collect_provider_native_dataset(
        database,
        registry=registry,
        collector=TushareCollector(),
        dataset_id="cn.equity.daily",
        request_window={"trade_date": "20260717"},
        attempt_id=f"daily-{expected_status}",
        started_at="2026-07-17T04:00:00+00:00",
    )

    assert result.status == expected_status
    assert captured_request["params"] == {"trade_date": "20260717"}
    dataset = registry.resolve("cn.equity.daily")
    assert captured_request["fields"] == ",".join(
        field.name for field in dataset.fields
    )
    conn = sqlite3.connect(database)
    try:
        receipt = conn.execute("SELECT status FROM market_ingest_runs").fetchone()
    finally:
        conn.close()
    assert receipt == (expected_receipt,)

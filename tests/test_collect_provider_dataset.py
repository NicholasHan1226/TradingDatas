from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
from types import MappingProxyType
from zoneinfo import ZoneInfo

import pytest

from collectors.tushare.tushare_common import ProviderCallOutcome
import collectors.tushare.provider_native_ingest as native_ingest
import provider_ingest_contract as ingest_contract_module
from dataset_registry import (
    DatasetDefinition,
    DatasetField,
    DatasetRegistry,
    FanoutPolicy,
    PaginationPolicy,
    ProviderBinding,
    ReadModelAdapter,
    RequestWindowPolicy,
    ResponseCompletenessPolicy,
    load_dataset_registry,
)
from storage.ingest_receipts import IngestResult, ProviderRequestIdentity
import storage.ingest_receipts as ingest_receipts
from storage.receipt_projection import (
    load_dataset_runtime_projection,
    project_dataset_runtime_evidence,
)
from storage.schema import SCHEMA_SQL
from storage.schema_contract import PROVIDER_DATASET_ROWS_DDL
import tools.collect_provider_dataset as runner


SHANGHAI_TEST_NOW = datetime(
    2026,
    7,
    20,
    16,
    0,
    tzinfo=ZoneInfo("Asia/Shanghai"),
)
SHANGHAI_TEST_DATA_DATE = SHANGHAI_TEST_NOW.strftime("%Y%m%d")
SHANGHAI_TEST_NOW_UTC_TEXT = (
    SHANGHAI_TEST_NOW.astimezone(timezone.utc)
    .isoformat(timespec="microseconds")
    .replace("+00:00", "Z")
)
ROOT = Path(__file__).resolve().parents[1]


def _registry(
    *,
    activation_state: str = "active",
    empty_data_policy: str = "forbidden",
) -> DatasetRegistry:
    fields = (
        DatasetField(
            name="ts_code",
            logical_type="text",
            nullable=False,
            selectable=True,
            filterable=True,
            sortable=True,
        ),
        DatasetField(
            name="trade_date",
            logical_type="text",
            nullable=False,
            selectable=True,
            filterable=True,
            sortable=True,
        ),
        DatasetField(
            name="close",
            logical_type="float",
            nullable=True,
            selectable=True,
            filterable=True,
            sortable=True,
        ),
    )
    binding = ProviderBinding(
        provider="tushare",
        api_name="synthetic_runner",
        adapter_version="tushare-provider-native.v1",
        read_discriminator_value="synthetic_runner",
        entitlement_state="active",
        activation_state=activation_state,
        target_tables=("provider_dataset_rows",),
        request_template=MappingProxyType(
            {
                "from_date": "${window.start_date}",
                "symbol": "600000.SH",
                "to_date": "${window.end_date}",
            }
        ),
        request_window_policy=RequestWindowPolicy(
            required_keys=("start_date", "end_date"),
            formats=MappingProxyType(
                {"end_date": "yyyymmdd", "start_date": "yyyymmdd"}
            ),
            range_start_key="start_date",
            range_end_key="end_date",
            max_span_days=366,
        ),
        response_completeness=ResponseCompletenessPolicy(
            strategy="one_row_per_calendar_date",
            date_field="trade_date",
            request_start_key="start_date",
            request_end_key="end_date",
            fixed_field_matches=MappingProxyType({"ts_code": "symbol"}),
        ),
        requested_fields=(),
        max_rows_per_attempt=1000,
        max_payload_bytes_per_row=65_536,
        max_batch_bytes=4_194_304,
        max_nesting_depth=16,
    )
    dataset = DatasetDefinition(
        dataset_id="cn.synthetic.runner",
        aliases=("tushare.synthetic_runner",),
        domain="market",
        market="CN",
        entity_type="provider_row",
        data_classification="objective_factual",
        schema_version="1.0.0",
        fields=fields,
        primary_key=("ts_code", "trade_date"),
        default_projection=("ts_code", "trade_date", "close"),
        as_of_field="trade_date",
        as_of_format="yyyymmdd",
        range_field="trade_date",
        partition_field="trade_date",
        cadence_class="postclose",
        timezone="Asia/Shanghai",
        freshness_sla_seconds=86_400,
        max_page_size=500,
        max_lookback_days=3650,
        point_in_time="current_snapshot",
        backfill_policy="provider_limited",
        empty_data_policy=empty_data_policy,
        required_scope="market_data",
        quota_class="beta_standard",
        provider_bindings=(binding,),
        read_model_adapter=ReadModelAdapter(
            adapter_version="provider-native-json.v1",
            primary_table="provider_dataset_rows",
            fixed_field_filters=(),
            storage_kind="provider_native_rows",
            row_key_strategy="primary_key",
        ),
    )
    return DatasetRegistry((dataset,))


def _two_dataset_registry() -> DatasetRegistry:
    base = _registry()
    first = base.resolve("cn.synthetic.runner")
    first_binding = base.provider_binding(first.dataset_id, "tushare")
    second_binding = replace(
        first_binding,
        api_name="synthetic_second",
        read_discriminator_value="tushare_synthetic_second",
    )
    second = replace(
        first,
        dataset_id="cn.synthetic.second",
        aliases=("tushare.synthetic_second",),
        provider_bindings=(second_binding,),
    )
    return DatasetRegistry((first, second))


def _strategy_registry(
    strategy: str,
    *,
    empty_data_policy: str = "forbidden",
    max_rows_per_attempt: int = 3,
) -> DatasetRegistry:
    base = _registry(empty_data_policy=empty_data_policy)
    dataset = base.resolve("cn.synthetic.runner")
    binding = base.provider_binding(dataset.dataset_id, "tushare")
    if strategy == "unique_primary_key_snapshot":
        response = ResponseCompletenessPolicy(
            strategy=strategy,
            fixed_field_matches=MappingProxyType({}),
            reject_at_row_limit=True,
        )
        replacement = replace(
            binding,
            request_template=MappingProxyType({"list_status": "L"}),
            request_window_policy=None,
            response_completeness=response,
            max_rows_per_attempt=max_rows_per_attempt,
        )
        dataset = replace(
            dataset,
            primary_key=("ts_code",),
            partition_field=None,
            provider_bindings=(replacement,),
        )
    elif strategy == "single_partition_unique_primary_key":
        response = ResponseCompletenessPolicy(
            strategy=strategy,
            partition_field="trade_date",
            request_partition_key="trade_date",
            fixed_field_matches=MappingProxyType({}),
            reject_at_row_limit=True,
        )
        replacement = replace(
            binding,
            request_template=MappingProxyType({"trade_date": "${window.trade_date}"}),
            request_window_policy=RequestWindowPolicy(
                required_keys=("trade_date",),
                formats=MappingProxyType({"trade_date": "yyyymmdd"}),
                range_start_key="trade_date",
                range_end_key="trade_date",
                max_span_days=1,
            ),
            response_completeness=response,
            max_rows_per_attempt=max_rows_per_attempt,
        )
        dataset = replace(dataset, provider_bindings=(replacement,))
    else:
        raise ValueError("unsupported test response strategy")
    return DatasetRegistry((dataset,))


def _fanout_snapshot_registry(
    *, empty_data_policy: str = "forbidden"
) -> DatasetRegistry:
    base = _registry(empty_data_policy=empty_data_policy)
    dataset = base.resolve("cn.synthetic.runner")
    binding = base.provider_binding(dataset.dataset_id, "tushare")
    response = ResponseCompletenessPolicy(
        strategy="unique_primary_key_snapshot",
        fixed_field_matches=MappingProxyType({}),
        fanout_field="ts_code",
        snapshot_field="trade_date",
        reject_at_row_limit=True,
    )
    replacement = replace(
        binding,
        request_template=MappingProxyType({"list_status": "L"}),
        request_window_policy=None,
        request_shape="entity_fanout",
        fanout=FanoutPolicy(
            strategy="literal_values",
            parameter="symbol",
            values=("600000.SH", "000001.SZ"),
            batch_size=1,
        ),
        response_completeness=response,
        max_rows_per_attempt=10,
    )
    return DatasetRegistry(
        (replace(dataset, provider_bindings=(replacement,)),)
    )


def _fut_settle_contract() -> tuple[DatasetDefinition, ProviderBinding]:
    registry = load_dataset_registry(ROOT / "config" / "provider_native_dataset_registry.yaml")
    dataset = registry.resolve("cn.dataset.fut_settle")
    return dataset, registry.provider_binding(dataset.dataset_id, "tushare")


def _broker_recommend_contract() -> tuple[DatasetDefinition, ProviderBinding]:
    registry = load_dataset_registry(ROOT / "config" / "provider_native_dataset_registry.yaml")
    dataset = registry.resolve("cn.dataset.broker_recommend")
    return dataset, registry.provider_binding(dataset.dataset_id, "tushare")


def _validate_broker_recommend_rows(
    binding: ProviderBinding,
    rows: tuple[Mapping[str, object], ...],
) -> None:
    dataset, _ = _broker_recommend_contract()
    native_ingest._validate_response_completeness(
        dataset,
        binding,
        rows,
        request_window={"month": "202608"},
        resolved_params={"month": "202608"},
        calls=(),
    )


def test_broker_recommend_contract_accepts_matching_month_partition() -> None:
    _, binding = _broker_recommend_contract()

    _validate_broker_recommend_rows(
        binding,
        (
            {
                "month": "202608",
                "broker": "broker-a",
                "ts_code": "600000.SH",
                "name": "example",
            },
        ),
    )


def test_broker_recommend_contract_rejects_mismatched_month_partition() -> None:
    _, binding = _broker_recommend_contract()

    with pytest.raises(ValueError, match="partition does not match request"):
        _validate_broker_recommend_rows(
            binding,
            (
                {
                    "month": "202607",
                    "broker": "broker-a",
                    "ts_code": "600000.SH",
                    "name": "example",
                },
            ),
        )


def _validate_fut_settle_rows(
    binding: ProviderBinding,
    rows: tuple[Mapping[str, object], ...],
) -> None:
    dataset, _ = _fut_settle_contract()
    native_ingest._validate_response_completeness(
        dataset,
        binding,
        rows,
        request_window={"trade_date": "20260803"},
        resolved_params={"trade_date": "20260803"},
        calls=(),
    )


def test_fut_settle_contract_rejects_duplicate_trade_date_ts_code_identity() -> None:
    _, binding = _fut_settle_contract()

    with pytest.raises(ValueError, match="duplicate primary key"):
        _validate_fut_settle_rows(
            binding,
            (
                {"trade_date": "20260803", "ts_code": "M2609.DCE"},
                {"trade_date": "20260803", "ts_code": "M2609.DCE"},
            ),
        )


@pytest.mark.parametrize(
    ("row", "message"),
    (
        ({"ts_code": "M2609.DCE"}, "exact YYYYMMDD format"),
        (
            {"trade_date": "20260804", "ts_code": "M2609.DCE"},
            "partition does not match request",
        ),
    ),
)
def test_fut_settle_contract_rejects_missing_or_wrong_trade_date_partition(
    row: Mapping[str, object], message: str
) -> None:
    _, binding = _fut_settle_contract()

    with pytest.raises(ValueError, match=message):
        _validate_fut_settle_rows(binding, (row,))


def test_fut_settle_contract_rejects_rows_at_declared_limit() -> None:
    _, binding = _fut_settle_contract()
    bounded_binding = replace(binding, max_rows_per_attempt=2)

    with pytest.raises(ValueError, match="reached the declared row limit"):
        _validate_fut_settle_rows(
            bounded_binding,
            (
                {"trade_date": "20260803", "ts_code": "M2609.DCE"},
                {"trade_date": "20260803", "ts_code": "M2611.DCE"},
            ),
        )


def _fut_mapping_contract() -> tuple[DatasetDefinition, ProviderBinding]:
    registry = load_dataset_registry(ROOT / "config" / "provider_native_dataset_registry.yaml")
    dataset = registry.resolve("cn.dataset.fut_mapping")
    return dataset, registry.provider_binding(dataset.dataset_id, "tushare")


def _validate_fut_mapping_rows(
    binding: ProviderBinding,
    rows: tuple[Mapping[str, object], ...],
) -> None:
    dataset, _ = _fut_mapping_contract()
    native_ingest._validate_response_completeness(
        dataset,
        binding,
        rows,
        request_window={"trade_date": "20260803"},
        resolved_params={"trade_date": "20260803"},
        calls=(),
    )


def test_fut_mapping_contract_requires_non_null_day_and_continuous_contract_identity() -> None:
    dataset, binding = _fut_mapping_contract()
    fields = {field.name: field for field in dataset.fields}

    assert fields["trade_date"].nullable is False
    assert fields["ts_code"].nullable is False
    assert dataset.primary_key == ("trade_date", "ts_code")
    assert binding.response_completeness is not None


def test_fut_mapping_contract_rejects_duplicate_trade_date_ts_code_identity() -> None:
    _, binding = _fut_mapping_contract()

    with pytest.raises(ValueError, match="duplicate primary key"):
        _validate_fut_mapping_rows(
            binding,
            (
                {"trade_date": "20260803", "ts_code": "M2609.DCE"},
                {"trade_date": "20260803", "ts_code": "M2609.DCE"},
            ),
        )


@pytest.mark.parametrize(
    ("row", "message"),
    (
        ({"ts_code": "M2609.DCE"}, "exact YYYYMMDD format"),
        (
            {"trade_date": "20260804", "ts_code": "M2609.DCE"},
            "partition does not match request",
        ),
    ),
)
def test_fut_mapping_contract_rejects_missing_or_wrong_trade_date_partition(
    row: Mapping[str, object], message: str
) -> None:
    _, binding = _fut_mapping_contract()

    with pytest.raises(ValueError, match=message):
        _validate_fut_mapping_rows(binding, (row,))


def test_fut_mapping_contract_rejects_rows_at_declared_limit() -> None:
    _, binding = _fut_mapping_contract()
    bounded_binding = replace(binding, max_rows_per_attempt=2)

    with pytest.raises(ValueError, match="reached the declared row limit"):
        _validate_fut_mapping_rows(
            bounded_binding,
            (
                {"trade_date": "20260803", "ts_code": "M2609.DCE"},
                {"trade_date": "20260803", "ts_code": "M2611.DCE"},
            ),
        )


def _fut_daily_contract() -> tuple[DatasetDefinition, ProviderBinding]:
    registry = load_dataset_registry(ROOT / "config" / "provider_native_dataset_registry.yaml")
    dataset = registry.resolve("cn.dataset.fut_daily")
    return dataset, registry.provider_binding(dataset.dataset_id, "tushare")


def _validate_fut_daily_rows(
    binding: ProviderBinding,
    rows: tuple[Mapping[str, object], ...],
) -> None:
    dataset, _ = _fut_daily_contract()
    native_ingest._validate_response_completeness(
        dataset,
        binding,
        rows,
        request_window={"trade_date": "20260803"},
        resolved_params={"trade_date": "20260803"},
        calls=(),
    )


def test_fut_daily_contract_requires_non_null_day_and_contract_identity() -> None:
    dataset, binding = _fut_daily_contract()
    fields = {field.name: field for field in dataset.fields}

    assert fields["trade_date"].nullable is False
    assert fields["ts_code"].nullable is False
    assert dataset.primary_key == ("trade_date", "ts_code")
    assert binding.response_completeness is not None


def test_fut_daily_rejects_incomplete_requested_response_before_persistence(
    tmp_path: Path,
) -> None:
    dataset, binding = _fut_daily_contract()
    registry = DatasetRegistry(
        (replace(dataset, provider_bindings=(replace(binding, activation_state="active"),)),)
    )
    response_fields = tuple(field for field in binding.requested_fields if field != "oi_chg")
    row = {
        field: (
            "M2609.DCE"
            if field == "ts_code"
            else "20260803"
            if field == "trade_date"
            else 1.0
        )
        for field in response_fields
    }
    collector = _FakeCollector(
        ProviderCallOutcome(
            state="success",
            rows=(row,),
            provider_code=0,
            error_code=None,
            error_message=None,
            response_fields=response_fields,
        )
    )
    db_path = tmp_path / "fut-daily-incomplete-fields.sqlite"
    _database(db_path)

    result = native_ingest.collect_provider_native_dataset(
        db_path,
        registry=registry,
        collector=collector,
        dataset_id=dataset.dataset_id,
        request_window={"trade_date": "20260803"},
        attempt_id="fut-daily-requested-fields",
        started_at="2026-08-04T00:00:00+00:00",
    )

    assert result.status == "failed"
    assert result.errors == ("validation_failed",)
    assert collector.calls == [
        (
            "fut_daily",
            {"trade_date": "20260803"},
            ",".join(binding.requested_fields),
        )
    ]
    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM provider_dataset_rows").fetchone() == (0,)
        assert conn.execute("SELECT status FROM market_ingest_runs").fetchall() == [
            ("failed",)
        ]


def test_fut_daily_contract_rejects_duplicate_trade_date_ts_code_identity() -> None:
    _, binding = _fut_daily_contract()

    with pytest.raises(ValueError, match="duplicate primary key"):
        _validate_fut_daily_rows(
            binding,
            (
                {"trade_date": "20260803", "ts_code": "M2609.DCE"},
                {"trade_date": "20260803", "ts_code": "M2609.DCE"},
            ),
        )


@pytest.mark.parametrize(
    ("row", "message"),
    (
        ({"ts_code": "M2609.DCE"}, "exact YYYYMMDD format"),
        (
            {"trade_date": "20260804", "ts_code": "M2609.DCE"},
            "partition does not match request",
        ),
    ),
)
def test_fut_daily_contract_rejects_missing_or_wrong_trade_date_partition(
    row: Mapping[str, object], message: str
) -> None:
    _, binding = _fut_daily_contract()

    with pytest.raises(ValueError, match=message):
        _validate_fut_daily_rows(binding, (row,))


def test_fut_daily_contract_rejects_rows_at_declared_limit() -> None:
    _, binding = _fut_daily_contract()
    bounded_binding = replace(binding, max_rows_per_attempt=2)

    with pytest.raises(ValueError, match="reached the declared row limit"):
        _validate_fut_daily_rows(
            bounded_binding,
            (
                {"trade_date": "20260803", "ts_code": "M2609.DCE"},
                {"trade_date": "20260803", "ts_code": "M2611.DCE"},
            ),
        )


def _fut_index_daily_contract() -> tuple[DatasetDefinition, ProviderBinding]:
    registry = load_dataset_registry(ROOT / "config" / "provider_native_dataset_registry.yaml")
    dataset = registry.resolve("cn.dataset.fut_index_daily")
    return dataset, registry.provider_binding(dataset.dataset_id, "tushare")


def _validate_fut_index_daily_rows(binding: ProviderBinding, rows: tuple[Mapping[str, object], ...]) -> None:
    dataset, _ = _fut_index_daily_contract()
    native_ingest._validate_response_completeness(dataset, binding, rows, request_window={"trade_date": "20260803"}, resolved_params={"trade_date": "20260803"}, calls=())


def test_fut_index_daily_contract_requires_identity_and_completeness() -> None:
    dataset, binding = _fut_index_daily_contract()
    fields = {field.name: field for field in dataset.fields}
    assert fields["trade_date"].nullable is False
    assert fields["ts_code"].nullable is False
    assert dataset.primary_key == ("trade_date", "ts_code")
    assert binding.response_completeness is not None
    assert binding.requested_fields == (
        "trade_date",
        "ts_code",
        "close",
        "open",
        "high",
        "low",
        "pre_close",
        "change",
        "pct_chg",
        "vol",
        "amount",
    )


def test_fut_index_daily_rejects_response_schema_mismatch_before_persistence(
    tmp_path: Path,
) -> None:
    dataset, _ = _fut_index_daily_contract()
    collector = _FakeCollector(
        ProviderCallOutcome(
            state="success",
            rows=({"trade_date": "20260803", "ts_code": "NH001.CI"},),
            provider_code=0,
            error_code=None,
            error_message=None,
            response_fields=("trade_date", "ts_code"),
        )
    )
    db_path = tmp_path / "fut-index-daily.sqlite"
    _database(db_path)

    result = native_ingest.collect_provider_native_dataset(
        db_path,
        registry=load_dataset_registry(ROOT / "config" / "provider_native_dataset_registry.yaml"),
        collector=collector,
        dataset_id=dataset.dataset_id,
        request_window={"trade_date": "20260803"},
        attempt_id="fut-index-daily-requested-fields",
        started_at="2026-08-03T18:00:00+00:00",
    )

    assert result.status == "failed"
    assert result.errors == ("validation_failed",)
    assert collector.calls == [
        (
            "fut_index_daily",
            {"trade_date": "20260803"},
            "trade_date,ts_code,close,open,high,low,pre_close,change,pct_chg,vol,amount",
        )
    ]
    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM provider_dataset_rows").fetchone() == (0,)
        assert conn.execute("SELECT status FROM market_ingest_runs").fetchall() == [
            ("failed",)
        ]


def test_fut_index_daily_rejects_row_missing_requested_field_before_persistence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dataset, binding = _fut_index_daily_contract()
    row = {
        "trade_date": "20260803",
        "ts_code": "NH001.CI",
        "close": 101.0,
        "open": 100.0,
        "high": 102.0,
        "low": 99.0,
        "pre_close": 100.5,
        "change": 0.5,
        "pct_chg": 0.4975,
        "vol": 1000.0,
    }
    complete_row = {field: 1.0 for field in binding.requested_fields}
    complete_row["trade_date"] = "20260803"
    complete_row["ts_code"] = "NH001.CI"
    outcome = ProviderCallOutcome(
        state="success",
        rows=(complete_row,),
        provider_code=0,
        error_code=None,
        error_message=None,
        response_fields=binding.requested_fields,
    )
    object.__setattr__(outcome, "rows", (MappingProxyType(row),))
    monkeypatch.setattr(ProviderCallOutcome, "validate_invariants", lambda _self: None)
    collector = _FakeCollector(outcome)
    db_path = tmp_path / "fut-index-daily-row-missing-field.sqlite"
    _database(db_path)

    result = native_ingest.collect_provider_native_dataset(
        db_path,
        registry=load_dataset_registry(ROOT / "config" / "provider_native_dataset_registry.yaml"),
        collector=collector,
        dataset_id=dataset.dataset_id,
        request_window={"trade_date": "20260803"},
        attempt_id="fut-index-daily-row-missing-field",
        started_at="2026-08-04T00:00:00+00:00",
    )

    assert result.status == "failed"
    assert result.errors == ("validation_failed",)
    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM provider_dataset_rows").fetchone() == (0,)
        receipt = conn.execute("SELECT status, notes FROM market_ingest_runs").fetchone()
    assert receipt is not None
    assert receipt[0] == "failed"
    assert json.loads(receipt[1])["errors"] == [
        "validation_failed",
        "response_field_coverage",
    ]


def test_fut_index_daily_accepts_response_schema_covering_requested_fields(
    tmp_path: Path,
) -> None:
    dataset, binding = _fut_index_daily_contract()
    row = {
        "trade_date": "20260803",
        "ts_code": "NH001.CI",
        "close": 101.0,
        "open": 100.0,
        "high": 102.0,
        "low": 99.0,
        "pre_close": 100.5,
        "change": 0.5,
        "pct_chg": 0.4975,
        "vol": 1000.0,
        "amount": 100000.0,
    }
    collector = _FakeCollector(
        ProviderCallOutcome(
            state="success",
            rows=(row,),
            provider_code=0,
            error_code=None,
            error_message=None,
            response_fields=binding.requested_fields,
        )
    )
    db_path = tmp_path / "fut-index-daily-complete.sqlite"
    _database(db_path)

    result = native_ingest.collect_provider_native_dataset(
        db_path,
        registry=load_dataset_registry(ROOT / "config" / "provider_native_dataset_registry.yaml"),
        collector=collector,
        dataset_id=dataset.dataset_id,
        request_window={"trade_date": "20260803"},
        attempt_id="fut-index-daily-complete-fields",
        started_at="2026-08-03T18:00:00+00:00",
    )

    assert result.status == "success"
    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM provider_dataset_rows").fetchone() == (1,)


@pytest.mark.parametrize(("rows", "message"), (
    (({"trade_date": "20260803", "ts_code": "NH001.CI"}, {"trade_date": "20260803", "ts_code": "NH001.CI"}), "duplicate primary key"),
    (({"ts_code": "NH001.CI"},), "exact YYYYMMDD format"),
    (({"trade_date": "20260804", "ts_code": "NH001.CI"},), "partition does not match request"),
))
def test_fut_index_daily_contract_rejects_duplicate_or_wrong_partition(rows: tuple[Mapping[str, object], ...], message: str) -> None:
    _, binding = _fut_index_daily_contract()
    with pytest.raises(ValueError, match=message):
        _validate_fut_index_daily_rows(binding, rows)


def test_fut_index_daily_contract_rejects_rows_at_declared_limit() -> None:
    _, binding = _fut_index_daily_contract()
    with pytest.raises(ValueError, match="reached the declared row limit"):
        _validate_fut_index_daily_rows(replace(binding, max_rows_per_attempt=2), ({"trade_date": "20260803", "ts_code": "NH001.CI"}, {"trade_date": "20260803", "ts_code": "NH002.CI"}))


def _fut_weekly_monthly_contract() -> tuple[DatasetDefinition, ProviderBinding]:
    registry = load_dataset_registry(ROOT / "config" / "provider_native_dataset_registry.yaml")
    dataset = registry.resolve("cn.dataset.fut_weekly_monthly")
    return dataset, registry.provider_binding(dataset.dataset_id, "tushare")


def _validate_fut_weekly_monthly_rows(
    binding: ProviderBinding,
    rows: tuple[Mapping[str, object], ...],
    *,
    freq: str = "week",
) -> None:
    dataset, _ = _fut_weekly_monthly_contract()
    native_ingest._validate_response_completeness(
        dataset,
        binding,
        rows,
        request_window={"trade_date": "20260803"},
        resolved_params={"trade_date": "20260803", "freq": freq},
        calls=(),
    )


def test_fut_weekly_monthly_contract_requires_frequency_scoped_day_identity() -> None:
    dataset, binding = _fut_weekly_monthly_contract()
    fields = {field.name: field for field in dataset.fields}

    assert fields["trade_date"].nullable is False
    assert fields["freq"].nullable is False
    assert fields["ts_code"].nullable is False
    assert dataset.primary_key == ("trade_date", "freq", "ts_code")
    assert binding.request_variants == ({"freq": "week"}, {"freq": "month"})
    assert binding.response_completeness is not None
    assert binding.response_completeness.fixed_field_matches == {"freq": "freq"}
    assert binding.requested_fields == (
        "ts_code",
        "trade_date",
        "end_date",
        "freq",
        "open",
        "high",
        "low",
        "close",
        "pre_close",
        "settle",
        "pre_settle",
        "vol",
        "amount",
        "oi",
        "oi_chg",
        "exchange",
        "change1",
        "change2",
    )


def test_fut_weekly_monthly_rejects_response_schema_mismatch_before_persistence(
    tmp_path: Path,
) -> None:
    dataset, _ = _fut_weekly_monthly_contract()
    collector = _FakeCollector(
        ProviderCallOutcome(
            state="success",
            rows=(
                {
                    "trade_date": "20260803",
                    "freq": "week",
                    "ts_code": "M2609.DCE",
                },
            ),
            provider_code=0,
            error_code=None,
            error_message=None,
            response_fields=("trade_date", "freq", "ts_code"),
        )
    )
    db_path = tmp_path / "fut-weekly-monthly.sqlite"
    _database(db_path)

    result = native_ingest.collect_provider_native_dataset(
        db_path,
        registry=load_dataset_registry(
            ROOT / "config" / "provider_native_dataset_registry.yaml"
        ),
        collector=collector,
        dataset_id=dataset.dataset_id,
        request_window={"trade_date": "20260803"},
        request_variant={"freq": "week"},
        attempt_id="fut-weekly-monthly-requested-fields",
        started_at="2026-08-03T18:00:00+00:00",
    )

    assert result.status == "failed"
    assert result.errors == ("validation_failed",)
    assert collector.calls == [
        (
            "fut_weekly_monthly",
            {"freq": "week", "trade_date": "20260803"},
            "ts_code,trade_date,end_date,freq,open,high,low,close,pre_close,settle,pre_settle,vol,amount,oi,oi_chg,exchange,change1,change2",
        )
    ]
    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM provider_dataset_rows").fetchone() == (0,)
        assert conn.execute("SELECT status FROM market_ingest_runs").fetchall() == [
            ("failed",)
        ]


@pytest.mark.parametrize(
    ("rows", "message"),
    (
        (
            (
                {"trade_date": "20260803", "freq": "week", "ts_code": "M2609.DCE"},
                {"trade_date": "20260803", "freq": "week", "ts_code": "M2609.DCE"},
            ),
            "duplicate primary key",
        ),
        (({"freq": "week", "ts_code": "M2609.DCE"},), "exact YYYYMMDD format"),
        (
            ({"trade_date": "20260804", "freq": "week", "ts_code": "M2609.DCE"},),
            "partition does not match request",
        ),
        (
            ({"trade_date": "20260803", "freq": "month", "ts_code": "M2609.DCE"},),
            "fixed field does not match request",
        ),
    ),
)
def test_fut_weekly_monthly_contract_rejects_invalid_frequency_scoped_partition(
    rows: tuple[Mapping[str, object], ...], message: str
) -> None:
    _, binding = _fut_weekly_monthly_contract()

    with pytest.raises(ValueError, match=message):
        _validate_fut_weekly_monthly_rows(binding, rows)


def test_fut_weekly_monthly_contract_rejects_rows_at_declared_limit() -> None:
    _, binding = _fut_weekly_monthly_contract()

    with pytest.raises(ValueError, match="reached the declared row limit"):
        _validate_fut_weekly_monthly_rows(
            replace(binding, max_rows_per_attempt=2),
            (
                {"trade_date": "20260803", "freq": "week", "ts_code": "M2609.DCE"},
                {"trade_date": "20260803", "freq": "week", "ts_code": "M2611.DCE"},
            ),
        )


def _request_window_binding(
    format_name: str,
    *,
    ranged: bool = False,
    max_span_days: int = 1,
) -> ProviderBinding:
    base = _registry()
    binding = base.provider_binding("cn.synthetic.runner", "tushare")
    keys = ("start", "end") if ranged else ("period",)
    return replace(
        binding,
        request_template=MappingProxyType(
            {f"provider_{key}": f"${{window.{key}}}" for key in keys}
        ),
        request_window_policy=RequestWindowPolicy(
            required_keys=keys,
            formats=MappingProxyType({key: format_name for key in keys}),
            range_start_key=keys[0],
            range_end_key=keys[-1],
            max_span_days=max_span_days,
        ),
        response_completeness=None,
    )


def _paginated_strategy_registry(*, max_pages: int = 12) -> DatasetRegistry:
    base = _strategy_registry(
        "unique_primary_key_snapshot",
        empty_data_policy="allowed",
        max_rows_per_attempt=32,
    )
    dataset = base.resolve("cn.synthetic.runner")
    binding = replace(
        base.provider_binding(dataset.dataset_id, "tushare"),
        pagination=PaginationPolicy(
            strategy="offset",
            limit_parameter="limit",
            offset_parameter="offset",
            page_size=1,
            max_pages=max_pages,
        ),
        response_completeness=None,
    )
    return DatasetRegistry((replace(dataset, provider_bindings=(binding,)),))


def _variant_cohort_registry(*, empty_data_policy: str = "forbidden") -> DatasetRegistry:
    base = _strategy_registry(
        "unique_primary_key_snapshot",
        empty_data_policy=empty_data_policy,
        max_rows_per_attempt=10,
    )
    dataset = base.resolve("cn.synthetic.runner")
    binding = replace(
        base.provider_binding(dataset.dataset_id, "tushare"),
        request_variants=tuple(
            MappingProxyType({"list_status": status}) for status in ("L", "D", "P")
        ),
    )
    return DatasetRegistry((replace(dataset, provider_bindings=(binding,)),))


def _database(path: Path) -> None:
    with sqlite3.connect(path) as conn:
        conn.executescript(SCHEMA_SQL)
        conn.executescript(PROVIDER_DATASET_ROWS_DDL)


class _FakeCollector:
    def __init__(
        self,
        outcome: ProviderCallOutcome | None = None,
        *,
        error: Exception | None = None,
    ) -> None:
        self.outcome = outcome
        self.error = error
        self.calls: list[tuple[str, dict[str, str], str | None]] = []

    def collect_outcome(
        self,
        api_name: str,
        params: dict[str, str],
        fields: str | None = None,
        *,
        scan_budget: object | None = None,
    ) -> ProviderCallOutcome:
        assert scan_budget is not None
        self.calls.append((api_name, params, fields))
        if self.error is not None:
            raise self.error
        assert self.outcome is not None
        return self.outcome


class _VariantOutcomeCollector:
    def __init__(self, outcomes: Mapping[str, ProviderCallOutcome]) -> None:
        self.outcomes = outcomes
        self.calls: list[str] = []

    def collect_outcome(
        self,
        _api_name: str,
        params: dict[str, str],
        _fields: str | None = None,
        *,
        scan_budget: object | None = None,
    ) -> ProviderCallOutcome:
        assert scan_budget is not None
        status = params["list_status"]
        self.calls.append(status)
        return self.outcomes[status]


class _FanoutOutcomeCollector:
    def __init__(self, outcomes: Mapping[str, ProviderCallOutcome]) -> None:
        self.outcomes = outcomes
        self.calls: list[str] = []

    def collect_outcome(
        self,
        _api_name: str,
        params: dict[str, str],
        _fields: str | None = None,
        *,
        scan_budget: object | None = None,
    ) -> ProviderCallOutcome:
        assert scan_budget is not None
        symbol = params["symbol"]
        self.calls.append(symbol)
        return self.outcomes[symbol]


def _variant_success(symbol: str) -> ProviderCallOutcome:
    return ProviderCallOutcome(
        state="success",
        rows=(
            {
                "ts_code": symbol,
                "trade_date": "20260720",
                "close": 12.5,
            },
        ),
        provider_code=0,
        error_code=None,
        error_message=None,
    )


def _variant_empty() -> ProviderCallOutcome:
    return ProviderCallOutcome(
        state="empty",
        rows=(),
        provider_code=0,
        error_code=None,
        error_message=None,
    )


def _variant_failed() -> ProviderCallOutcome:
    return ProviderCallOutcome(
        state="failed",
        rows=(),
        provider_code=-2001,
        error_code="permission_denied",
        error_message="permission denied",
    )


def _run(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    *,
    outcome: ProviderCallOutcome,
    registry: DatasetRegistry | None = None,
    request_file: bool = False,
    request_window: dict[str, str] | None = None,
) -> tuple[int, dict[str, object], _FakeCollector, Path]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    registry = registry or _registry()
    fake = _FakeCollector(outcome)
    monkeypatch.setattr(runner, "load_runtime_dataset_registry", lambda: registry)
    monkeypatch.setattr(runner, "TushareCollector", lambda: fake)
    db_path = tmp_path / "facts.sqlite"
    _database(db_path)
    if request_window is None:
        request_window = {"end_date": "20260717", "start_date": "20260717"}
    args = [
        "--db-path",
        str(db_path),
        "--dataset-id",
        "cn.synthetic.runner",
        "--attempt-id",
        "runner-attempt-1",
        "--started-at",
        "2026-07-17T01:00:00+00:00",
        "--execute",
    ]
    if request_file:
        window_path = tmp_path / "request-window.json"
        window_path.write_text(json.dumps(request_window), encoding="utf-8")
        args.extend(["--request-window-file", str(window_path)])
    else:
        args.extend(["--request-window-json", json.dumps(request_window)])

    code = runner.main(args)
    output = json.loads(capsys.readouterr().out)
    return code, output, fake, db_path


def provider_fact_count(db_path: Path) -> int:
    with sqlite3.connect(db_path) as conn:
        return int(
            conn.execute("SELECT COUNT(*) FROM provider_dataset_rows").fetchone()[0]
        )


def success_receipt_count(db_path: Path) -> int:
    with sqlite3.connect(db_path) as conn:
        return int(
            conn.execute(
                "SELECT COUNT(*) FROM market_ingest_runs WHERE status = 'success'"
            ).fetchone()[0]
        )


def test_retry_attempts_each_write_one_terminal_receipt_with_unique_attempt_id(
    tmp_path: Path,
) -> None:
    class SequenceCollector:
        def __init__(self) -> None:
            self.outcomes = iter(
                (
                    ProviderCallOutcome(
                        state="failed",
                        rows=(),
                        provider_code=None,
                        error_code="rate_limited",
                        error_message="retry later",
                    ),
                    ProviderCallOutcome(
                        state="success",
                        rows=(
                            {
                                "ts_code": "600000.SH",
                                "trade_date": "20260717",
                                "close": 12.5,
                            },
                        ),
                        provider_code=0,
                        error_code=None,
                        error_message=None,
                    ),
                )
            )

        def collect_outcome(
            self,
            _api_name: str,
            _params: dict[str, str],
            _fields: str | None = None,
            *,
            scan_budget: object | None = None,
        ) -> ProviderCallOutcome:
            assert scan_budget is not None
            return next(self.outcomes)

    db_path = tmp_path / "facts.sqlite"
    _database(db_path)

    result = native_ingest.collect_provider_native_dataset(
        db_path,
        registry=_registry(),
        collector=SequenceCollector(),
        dataset_id="cn.synthetic.runner",
        request_window={"start_date": "20260717", "end_date": "20260717"},
        attempt_id="retry-root-attempt",
        started_at="2026-07-17T01:00:00+00:00",
        retry=native_ingest.RetrySettings(max_attempts=2),
    )

    assert result.status == "success"
    assert len(result.receipt_ids) == 2
    assert provider_fact_count(db_path) == 1
    with sqlite3.connect(db_path) as conn:
        receipts = [
            json.loads(row[0])
            for row in conn.execute(
                "SELECT notes FROM market_ingest_runs ORDER BY finished_at, run_id"
            )
        ]
    assert {receipt["status"] for receipt in receipts} == {"failed", "success"}
    assert len({receipt["attempt_id"] for receipt in receipts}) == 2
    assert receipts[0]["request_identity"] == receipts[1]["request_identity"]
    assert all("requests" not in receipt for receipt in receipts)


@pytest.mark.parametrize("full_final_page", [False, True])
def test_each_pagination_call_has_its_own_terminal_receipt(
    tmp_path: Path,
    full_final_page: bool,
) -> None:
    class SequenceCollector:
        def __init__(self) -> None:
            final = (
                ProviderCallOutcome(
                    state="success",
                    rows=(
                        {
                            "ts_code": "600002.SH",
                            "trade_date": "20260717",
                            "close": 13.0,
                        },
                    ),
                    provider_code=0,
                    error_code=None,
                    error_message=None,
                )
                if full_final_page
                else ProviderCallOutcome(
                    state="empty",
                    rows=(),
                    provider_code=0,
                    error_code=None,
                    error_message=None,
                )
            )
            self.outcomes = iter(
                (
                    ProviderCallOutcome(
                        state="success",
                        rows=(
                            {
                                "ts_code": "600000.SH",
                                "trade_date": "20260717",
                                "close": 12.5,
                            },
                        ),
                        provider_code=0,
                        error_code=None,
                        error_message=None,
                    ),
                    final,
                )
            )

        def collect_outcome(
            self,
            _api_name: str,
            _params: dict[str, str],
            _fields: str | None = None,
            *,
            scan_budget: object | None = None,
        ) -> ProviderCallOutcome:
            assert scan_budget is not None
            return next(self.outcomes)

    base = _strategy_registry(
        "unique_primary_key_snapshot",
        empty_data_policy="allowed",
        max_rows_per_attempt=3,
    )
    dataset = base.resolve("cn.synthetic.runner")
    binding = replace(
        base.provider_binding(dataset.dataset_id, "tushare"),
        pagination=PaginationPolicy(
            strategy="offset",
            limit_parameter="limit",
            offset_parameter="offset",
            page_size=1,
            max_pages=2,
        ),
    )
    registry = DatasetRegistry((replace(dataset, provider_bindings=(binding,)),))
    db_path = tmp_path / "facts.sqlite"
    _database(db_path)

    result = native_ingest.collect_provider_native_dataset(
        db_path,
        registry=registry,
        collector=SequenceCollector(),
        dataset_id=dataset.dataset_id,
        request_window={},
        attempt_id="pagination-root-attempt",
        started_at="2026-07-17T01:00:00+00:00",
    )

    assert len(result.receipt_ids) == 2
    assert result.status == ("failed" if full_final_page else "success")
    assert provider_fact_count(db_path) == (2 if full_final_page else 1)
    with sqlite3.connect(db_path) as conn:
        receipts = [
            json.loads(row[0])
            for row in conn.execute(
                "SELECT notes FROM market_ingest_runs ORDER BY run_id"
            )
        ]
    assert len({receipt["attempt_id"] for receipt in receipts}) == 2
    assert {receipt["request_identity"]["page_index"] for receipt in receipts} == {0, 1}
    assert all("requests" not in receipt for receipt in receipts)
    if full_final_page:
        assert result.errors == ("resource_budget",)
        assert {receipt["status"] for receipt in receipts} == {"success"}
        assert {tuple(receipt["errors"]) for receipt in receipts} == {()}


def test_later_storage_failure_reports_prior_committed_physical_call_truthfully(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class SequenceCollector:
        def __init__(self) -> None:
            self.outcomes = iter(
                (
                    ProviderCallOutcome(
                        state="success",
                        rows=(
                            {
                                "ts_code": "600000.SH",
                                "trade_date": "20260717",
                                "close": 12.5,
                            },
                            {
                                "ts_code": "600002.SH",
                                "trade_date": "20260717",
                                "close": 12.75,
                            },
                        ),
                        provider_code=0,
                        error_code=None,
                        error_message=None,
                    ),
                    ProviderCallOutcome(
                        state="success",
                        rows=(
                            {
                                "ts_code": "600001.SH",
                                "trade_date": "20260717",
                                "close": 13.0,
                            },
                        ),
                        provider_code=0,
                        error_code=None,
                        error_message=None,
                    ),
                )
            )

        def collect_outcome(
            self,
            _api_name: str,
            _params: dict[str, str],
            _fields: str | None = None,
            *,
            scan_budget: object | None = None,
        ) -> ProviderCallOutcome:
            assert scan_budget is not None
            return next(self.outcomes)

    base = _strategy_registry(
        "unique_primary_key_snapshot",
        max_rows_per_attempt=5,
    )
    dataset = base.resolve("cn.synthetic.runner")
    binding = replace(
        base.provider_binding(dataset.dataset_id, "tushare"),
        pagination=PaginationPolicy(
            strategy="offset",
            limit_parameter="limit",
            offset_parameter="offset",
            page_size=2,
            max_pages=2,
        ),
        response_completeness=None,
    )
    dataset = replace(dataset, provider_bindings=(binding,))
    registry = DatasetRegistry((dataset,))
    db_path = tmp_path / "facts.sqlite"
    _database(db_path)
    original = native_ingest.ingest_provider_native_rows
    storage_call_count = 0

    def fail_second_storage_call(*args: object, **kwargs: object):
        nonlocal storage_call_count
        storage_call_count += 1
        if storage_call_count == 2:
            raise sqlite3.OperationalError("injected second-call storage failure")
        return original(*args, **kwargs)

    monkeypatch.setattr(
        native_ingest,
        "ingest_provider_native_rows",
        fail_second_storage_call,
    )

    result = native_ingest.collect_provider_native_dataset(
        db_path,
        registry=registry,
        collector=SequenceCollector(),
        dataset_id=dataset.dataset_id,
        request_window={},
        attempt_id="partial-storage-root",
        started_at=datetime.now(timezone.utc).isoformat(),
    )

    assert result.status == "failed"
    assert result.errors == ("storage_failed",)
    assert result.counts.committed == 2
    assert result.counts.inserted == 2
    assert result.counts.count_semantics == (
        "aggregate_partial_physical_call_transactions"
    )
    assert len(result.receipt_ids) == 2
    assert provider_fact_count(db_path) == 2
    with sqlite3.connect(db_path) as conn:
        statuses = conn.execute(
            "SELECT status FROM market_ingest_runs ORDER BY run_id"
        ).fetchall()
    assert {row[0] for row in statuses} == {"success", "failed"}
    projection = load_dataset_runtime_projection(
        db_path,
        dataset,
        registry=registry,
        now=datetime.now(timezone.utc),
    )
    assert projection.state == "failed"
    assert projection.reasons == ("storage_failed",)


@pytest.mark.parametrize("failed_call_index", (2, 10))
@pytest.mark.parametrize("recovery_state", ("empty", "success"))
def test_execution_projection_keeps_storage_failure_over_later_empty_terminator(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failed_call_index: int,
    recovery_state: str,
) -> None:
    monkeypatch.setattr(ingest_receipts, "_utc_now", lambda: SHANGHAI_TEST_NOW_UTC_TEXT)

    class SequenceCollector:
        def __init__(self, outcomes: tuple[ProviderCallOutcome, ...]) -> None:
            self.outcomes = iter(outcomes)

        def collect_outcome(
            self,
            _api_name: str,
            _params: dict[str, str],
            _fields: str | None = None,
            *,
            scan_budget: object | None = None,
        ) -> ProviderCallOutcome:
            assert scan_budget is not None
            return next(self.outcomes)

    def success(index: int) -> ProviderCallOutcome:
        return ProviderCallOutcome(
            state="success",
            rows=(
                {
                    "ts_code": f"{600000 + index:06d}.SH",
                    "trade_date": SHANGHAI_TEST_DATA_DATE,
                    "close": 10.0 + index,
                },
            ),
            provider_code=0,
            error_code=None,
            error_message=None,
        )

    empty = ProviderCallOutcome(
        state="empty",
        rows=(),
        provider_code=0,
        error_code=None,
        error_message=None,
    )
    registry = _paginated_strategy_registry()
    dataset = registry.resolve("cn.synthetic.runner")
    db_path = tmp_path / "facts.sqlite"
    _database(db_path)
    original = native_ingest.ingest_provider_native_rows
    storage_call_count = 0

    def fail_selected_storage_call(*args: object, **kwargs: object):
        nonlocal storage_call_count
        call_index = storage_call_count
        storage_call_count += 1
        if call_index == failed_call_index:
            raise sqlite3.OperationalError("injected physical-call storage failure")
        return original(*args, **kwargs)

    monkeypatch.setattr(
        native_ingest,
        "ingest_provider_native_rows",
        fail_selected_storage_call,
    )
    started_at = SHANGHAI_TEST_NOW - timedelta(minutes=2)
    result = native_ingest.collect_provider_native_dataset(
        db_path,
        registry=registry,
        collector=SequenceCollector(
            tuple(success(index) for index in range(11)) + (empty,)
        ),
        dataset_id=dataset.dataset_id,
        request_window={},
        attempt_id=f"twelve-call-root-{failed_call_index}",
        started_at=started_at.isoformat(),
    )

    assert result.status == "failed"
    assert result.errors == ("storage_failed",)
    assert result.counts.committed == 10
    assert result.counts.inserted == 10
    assert len(result.receipt_ids) == 12
    assert provider_fact_count(db_path) == 10
    with sqlite3.connect(db_path) as conn:
        receipts = [
            json.loads(row[0])
            for row in conn.execute(
                "SELECT notes FROM market_ingest_runs ORDER BY run_id"
            )
        ]
    failed = [
        receipt for receipt in receipts if receipt["errors"] == ["storage_failed"]
    ]
    assert len(failed) == 1
    assert failed[0]["attempt_id"].endswith(
        f":provider-call:{failed_call_index:012d}:retry:000000000000"
    )
    assert receipts[-1]["attempt_id"] != failed[0]["attempt_id"]

    projection = load_dataset_runtime_projection(
        db_path,
        dataset,
        registry=registry,
        now=SHANGHAI_TEST_NOW + timedelta(seconds=1),
    )
    assert projection.state == "failed"
    assert projection.degraded is True
    assert projection.receipt_id in result.receipt_ids
    assert projection.reasons == ("storage_failed",)

    monkeypatch.setattr(
        native_ingest,
        "ingest_provider_native_rows",
        original,
    )
    recovery_outcomes = (empty,) if recovery_state == "empty" else (success(31), empty)
    recovered = native_ingest.collect_provider_native_dataset(
        db_path,
        registry=registry,
        collector=SequenceCollector(recovery_outcomes),
        dataset_id=dataset.dataset_id,
        request_window={},
        attempt_id=f"independent-recovery-{failed_call_index}-{recovery_state}",
        started_at=(started_at + timedelta(minutes=1)).isoformat(),
    )
    assert recovered.status == recovery_state
    recovered_projection = load_dataset_runtime_projection(
        db_path,
        dataset,
        registry=registry,
        now=SHANGHAI_TEST_NOW + timedelta(seconds=1),
    )
    assert recovered_projection.state == recovery_state
    assert recovered_projection.receipt_id in recovered.receipt_ids


def test_retry_group_uses_numeric_terminal_retry_before_execution_projection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ingest_receipts, "_utc_now", lambda: SHANGHAI_TEST_NOW_UTC_TEXT)

    class SequenceCollector:
        def __init__(self) -> None:
            self.outcomes = iter(
                (
                    ProviderCallOutcome(
                        state="failed",
                        rows=(),
                        provider_code=None,
                        error_code="rate_limited",
                        error_message="retry later",
                    ),
                    ProviderCallOutcome(
                        state="success",
                        rows=(
                            {
                                "ts_code": "600000.SH",
                                "trade_date": SHANGHAI_TEST_DATA_DATE,
                                "close": 12.5,
                            },
                        ),
                        provider_code=0,
                        error_code=None,
                        error_message=None,
                    ),
                    ProviderCallOutcome(
                        state="empty",
                        rows=(),
                        provider_code=0,
                        error_code=None,
                        error_message=None,
                    ),
                )
            )

        def collect_outcome(
            self,
            _api_name: str,
            _params: dict[str, str],
            _fields: str | None = None,
            *,
            scan_budget: object | None = None,
        ) -> ProviderCallOutcome:
            assert scan_budget is not None
            return next(self.outcomes)

    registry = _paginated_strategy_registry(max_pages=2)
    dataset = registry.resolve("cn.synthetic.runner")
    db_path = tmp_path / "facts.sqlite"
    _database(db_path)
    started_at = SHANGHAI_TEST_NOW - timedelta(minutes=1)
    result = native_ingest.collect_provider_native_dataset(
        db_path,
        registry=registry,
        collector=SequenceCollector(),
        dataset_id=dataset.dataset_id,
        request_window={},
        attempt_id="retry-execution-root",
        started_at=started_at.isoformat(),
        retry=native_ingest.RetrySettings(max_attempts=2),
    )

    assert result.status == "success"
    assert result.counts.committed == 1
    assert len(result.receipt_ids) == 3
    assert provider_fact_count(db_path) == 1
    with sqlite3.connect(db_path) as conn:
        receipts = [
            json.loads(row[0])
            for row in conn.execute(
                "SELECT notes FROM market_ingest_runs ORDER BY run_id"
            )
        ]
    assert sorted(
        (
            receipt["request_identity"]["page_index"],
            int(receipt["attempt_id"].split(":provider-call:")[1][:12]),
            int(receipt["attempt_id"].rsplit(":retry:", 1)[1]),
            receipt["status"],
        )
        for receipt in receipts
    ) == [
        (0, 0, 0, "failed"),
        (0, 1, 1, "success"),
        (1, 2, 0, "empty"),
    ]
    projection = load_dataset_runtime_projection(
        db_path,
        dataset,
        registry=registry,
        now=SHANGHAI_TEST_NOW + timedelta(seconds=1),
    )
    assert projection.state == "success"
    assert projection.degraded is False
    assert projection.receipt_id in result.receipt_ids
    assert projection.reasons == ()


def test_default_plan_validates_registry_without_provider_or_database_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(runner, "load_runtime_dataset_registry", _registry)
    monkeypatch.setattr(
        runner,
        "TushareCollector",
        lambda: pytest.fail("plan mode must not construct a provider collector"),
    )
    db_path = tmp_path / "must-not-be-created.sqlite"

    code = runner.main(
        [
            "--db-path",
            str(db_path),
            "--dataset-id",
            "cn.synthetic.runner",
            "--request-window-json",
            '{"start_date":"20260701","end_date":"20260717"}',
        ]
    )

    output = json.loads(capsys.readouterr().out)
    assert code == runner.EXIT_SUCCESS
    assert output == {
        "dataset_id": "cn.synthetic.runner",
        "mode": "plan",
        "parameter_keys": ["from_date", "symbol", "to_date"],
        "provider": "tushare",
        "provider_api": "synthetic_runner",
        "request_window_keys": ["end_date", "start_date"],
        "requested_field_count": 0,
        "state": "planned",
        "will_call_provider": False,
        "will_write_database": False,
    }
    assert "202607" not in json.dumps(output)
    assert not db_path.exists()


def test_batch_plan_validates_every_item_before_provider_or_database_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(runner, "load_runtime_dataset_registry", _two_dataset_registry)
    monkeypatch.setattr(
        runner,
        "TushareCollector",
        lambda: pytest.fail("plan mode must not construct a provider collector"),
    )
    manifest = tmp_path / "batch.json"
    manifest.write_text(
        json.dumps(
            {
                "version": 1,
                "items": [
                    {
                        "dataset_id": "cn.synthetic.runner",
                        "request_window": {
                            "end_date": "20260717",
                            "start_date": "20260701",
                        },
                    },
                    {
                        "dataset_id": "cn.synthetic.second",
                        "request_window": {
                            "end_date": "20260717",
                            "start_date": "20260701",
                        },
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    db_path = tmp_path / "must-not-be-created.sqlite"

    code = runner.main(["--db-path", str(db_path), "--batch-file", str(manifest)])

    output = json.loads(capsys.readouterr().out)
    assert code == runner.EXIT_SUCCESS
    assert output == {
        "batch_item_count": 2,
        "dataset_ids": ["cn.synthetic.runner", "cn.synthetic.second"],
        "mode": "plan",
        "state": "planned",
        "will_call_provider": False,
        "will_write_database": False,
    }
    assert "202607" not in json.dumps(output)
    assert not db_path.exists()


def test_batch_rejects_unsorted_or_invalid_item_before_provider_or_database(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    fake = _FakeCollector()
    monkeypatch.setattr(runner, "load_runtime_dataset_registry", _two_dataset_registry)
    monkeypatch.setattr(runner, "TushareCollector", lambda: fake)
    manifest = tmp_path / "batch.json"
    manifest.write_text(
        json.dumps(
            {
                "version": 1,
                "items": [
                    {"dataset_id": "cn.synthetic.second", "request_window": {}},
                    {"dataset_id": "cn.synthetic.runner", "request_window": {}},
                ],
            }
        ),
        encoding="utf-8",
    )
    db_path = tmp_path / "must-not-be-created.sqlite"

    code = runner.main(
        ["--db-path", str(db_path), "--batch-file", str(manifest), "--execute"]
    )

    output = json.loads(capsys.readouterr().out)
    assert code == runner.EXIT_VALIDATION
    assert output == {
        "error_code": "invalid_request",
        "mode": "execute",
        "state": "validation",
    }
    assert fake.calls == []
    assert not db_path.exists()


def test_batch_execute_reuses_one_generic_collector_and_keeps_receipts_per_dataset(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    outcome = ProviderCallOutcome(
        state="success",
        rows=({"ts_code": "600000.SH", "trade_date": "20260717", "close": 12.5},),
        provider_code=0,
        error_code=None,
        error_message=None,
    )
    fake = _FakeCollector(outcome)
    monkeypatch.setattr(runner, "load_runtime_dataset_registry", _two_dataset_registry)
    monkeypatch.setattr(runner, "TushareCollector", lambda: fake)
    manifest = tmp_path / "batch.json"
    manifest.write_text(
        json.dumps(
            {
                "version": 1,
                "items": [
                    {
                        "dataset_id": "cn.synthetic.runner",
                        "request_window": {
                            "end_date": "20260717",
                            "start_date": "20260717",
                        },
                    },
                    {
                        "dataset_id": "cn.synthetic.second",
                        "request_window": {
                            "end_date": "20260717",
                            "start_date": "20260717",
                        },
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    db_path = tmp_path / "facts.sqlite"
    _database(db_path)

    code = runner.main(
        ["--db-path", str(db_path), "--batch-file", str(manifest), "--execute"]
    )

    output = json.loads(capsys.readouterr().out)
    assert code == runner.EXIT_SUCCESS
    assert output["state"] == "success"
    assert [item["dataset_id"] for item in output["items"]] == [
        "cn.synthetic.runner",
        "cn.synthetic.second",
    ]
    assert len(fake.calls) == 2
    with sqlite3.connect(db_path) as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM market_ingest_runs WHERE status = 'success'"
        ).fetchone() == (2,)


def test_execute_success_uses_only_registry_binding_and_writes_fact_and_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    outcome = ProviderCallOutcome(
        state="success",
        rows=({"ts_code": "600000.SH", "trade_date": "20260717", "close": 12.5},),
        provider_code=0,
        error_code=None,
        error_message=None,
    )
    code, output, fake, db_path = _run(
        monkeypatch,
        capsys,
        tmp_path,
        outcome=outcome,
        request_file=True,
    )

    assert code == runner.EXIT_SUCCESS
    assert output["state"] == "success"
    assert output["counts"] == {
        "committed": 1,
        "inserted": 1,
        "rejected": 0,
        "returned": 1,
        "unchanged": 0,
        "updated": 0,
        "validated": 1,
    }
    assert output["receipt_count"] == 1
    assert fake.calls == [
        (
            "synthetic_runner",
            {
                "from_date": "20260717",
                "symbol": "600000.SH",
                "to_date": "20260717",
            },
            None,
        )
    ]
    with sqlite3.connect(db_path) as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM provider_dataset_rows"
        ).fetchone() == (1,)
        assert conn.execute(
            "SELECT status, source FROM market_ingest_runs"
        ).fetchone() == ("success", "cn.synthetic.runner")


@pytest.mark.parametrize(
    ("outcome", "expected_code", "expected_state"),
    [
        (
            ProviderCallOutcome(
                state="empty",
                rows=(),
                provider_code=0,
                error_code=None,
                error_message=None,
            ),
            2,
            "validation",
        ),
        (
            ProviderCallOutcome(
                state="failed",
                rows=(),
                provider_code=-2001,
                error_code="permission_denied",
                error_message="permission denied",
            ),
            4,
            "failed",
        ),
    ],
)
def test_execute_has_distinct_empty_and_failed_exit_codes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    outcome: ProviderCallOutcome,
    expected_code: int,
    expected_state: str,
) -> None:
    code, output, fake, _ = _run(monkeypatch, capsys, tmp_path, outcome=outcome)

    assert code == expected_code
    assert code == (
        runner.EXIT_VALIDATION if expected_state == "validation" else runner.EXIT_FAILED
    )
    assert output["state"] == expected_state
    assert len(fake.calls) == 1


def test_forbidden_empty_window_writes_failed_terminal_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    registry = _registry(empty_data_policy="forbidden")
    fake = _FakeCollector(
        ProviderCallOutcome(
            state="empty",
            rows=(),
            provider_code=0,
            error_code=None,
            error_message=None,
        )
    )
    monkeypatch.setattr(runner, "load_runtime_dataset_registry", lambda: registry)
    monkeypatch.setattr(runner, "TushareCollector", lambda: fake)
    db_path = tmp_path / "facts.sqlite"
    _database(db_path)

    code = runner.main(
        [
            "--db-path",
            str(db_path),
            "--dataset-id",
            "cn.synthetic.runner",
            "--request-window-json",
            '{"start_date":"20260701","end_date":"20260717"}',
            "--attempt-id",
            "forbidden-empty-1",
            "--started-at",
            "2026-07-17T01:00:00+00:00",
            "--execute",
        ]
    )

    output = json.loads(capsys.readouterr().out)
    assert code == runner.EXIT_VALIDATION
    assert output["state"] == "validation"
    assert output["error_codes"] == ["validation_failed"]
    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT status FROM market_ingest_runs").fetchone() == (
            "failed",
        )


def test_completeness_empty_uses_the_dataset_empty_data_policy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    registry = _registry(empty_data_policy="allowed")
    fake = _FakeCollector(
        ProviderCallOutcome(
            state="empty",
            rows=(),
            provider_code=0,
            error_code=None,
            error_message=None,
        )
    )
    monkeypatch.setattr(runner, "load_runtime_dataset_registry", lambda: registry)
    monkeypatch.setattr(runner, "TushareCollector", lambda: fake)
    db_path = tmp_path / "facts.sqlite"
    _database(db_path)

    code = runner.main(
        [
            "--db-path",
            str(db_path),
            "--dataset-id",
            "cn.synthetic.runner",
            "--request-window-json",
            '{"start_date":"20260717","end_date":"20260717"}',
            "--execute",
        ]
    )

    output = json.loads(capsys.readouterr().out)
    assert code == runner.EXIT_EMPTY
    assert output["state"] == "empty"
    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT status FROM market_ingest_runs").fetchall() == [
            ("empty",)
        ]


def _calendar_row(
    date_value: object, *, symbol: str = "600000.SH"
) -> dict[str, object]:
    return {
        "ts_code": symbol,
        "trade_date": date_value,
        "close": 12.5,
    }


def test_response_completeness_accepts_exact_inclusive_window_before_storage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    rows = (
        _calendar_row("20260701"),
        {**_calendar_row("20260702"), "provider_extra": "preserved"},
        _calendar_row("20260703"),
    )
    outcome = ProviderCallOutcome(
        state="success",
        rows=rows,
        provider_code=0,
        error_code=None,
        error_message=None,
    )

    code, output, _, db_path = _run(
        monkeypatch,
        capsys,
        tmp_path,
        outcome=outcome,
        request_window={"start_date": "20260701", "end_date": "20260703"},
    )

    assert code == runner.EXIT_SUCCESS
    assert output["state"] == "success"
    with sqlite3.connect(db_path) as conn:
        stored_rows = conn.execute(
            "SELECT payload_json, quality_state, quality_issues_json "
            "FROM provider_dataset_rows ORDER BY row_key"
        ).fetchall()
        payloads = [json.loads(row[0]) for row in stored_rows]
        assert len(payloads) == 3
        assert any(payload.get("provider_extra") == "preserved" for payload in payloads)
        extra_row = next(
            row for row in stored_rows if "provider_extra" in json.loads(row[0])
        )
        assert extra_row[1] == "degraded"
        assert "unknown_field:provider_extra" in json.loads(extra_row[2])
        receipt_rows = conn.execute(
            "SELECT status, notes FROM market_ingest_runs"
        ).fetchall()
        assert [row[0] for row in receipt_rows] == ["success"]
        assert json.loads(receipt_rows[0][1])["data_through"] == "20260703"


@pytest.mark.parametrize(
    "rows",
    [
        (_calendar_row("20260702"), _calendar_row("20260703")),
        (_calendar_row("20260701"), _calendar_row("20260703")),
        (_calendar_row("20260701"), _calendar_row("20260702")),
        (
            _calendar_row("20260701"),
            _calendar_row("20260702"),
            _calendar_row("20260702"),
            _calendar_row("20260703"),
        ),
        (
            _calendar_row("20260630"),
            _calendar_row("20260701"),
            _calendar_row("20260702"),
            _calendar_row("20260703"),
        ),
        (
            _calendar_row("20260701"),
            _calendar_row("20260702", symbol="000001.SZ"),
            _calendar_row("20260703"),
        ),
        (
            _calendar_row("20260701"),
            _calendar_row("2026070x"),
            _calendar_row("20260703"),
        ),
    ],
    ids=(
        "missing-first",
        "missing-middle",
        "missing-last",
        "duplicate",
        "out-of-range",
        "wrong-fixed-value",
        "invalid-date",
    ),
)
def test_response_completeness_failure_writes_only_failed_receipt(
    rows: tuple[dict[str, object], ...],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    outcome = ProviderCallOutcome(
        state="success",
        rows=rows,
        provider_code=0,
        error_code=None,
        error_message=None,
    )

    code, output, _, db_path = _run(
        monkeypatch,
        capsys,
        tmp_path,
        outcome=outcome,
        request_window={"start_date": "20260701", "end_date": "20260703"},
    )

    assert code == runner.EXIT_VALIDATION
    assert output["state"] == "validation"
    assert output["error_codes"] == ["validation_failed"]
    with sqlite3.connect(db_path) as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM provider_dataset_rows"
        ).fetchone() == (0,)
        receipt_rows = conn.execute(
            "SELECT status, notes FROM market_ingest_runs"
        ).fetchall()
        assert [row[0] for row in receipt_rows] == ["failed"]
        receipt = json.loads(receipt_rows[0][1])
        assert receipt["data_through"] is None
        assert receipt["errors"] == ["validation_failed", "response_completeness"]


def test_snapshot_accepts_unique_primary_keys_below_provider_cap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    code, output, _, db_path = _run(
        monkeypatch,
        capsys,
        tmp_path,
        registry=_strategy_registry("unique_primary_key_snapshot"),
        request_window={},
        outcome=ProviderCallOutcome(
            state="success",
            rows=(
                _calendar_row("20260717"),
                _calendar_row("20260718", symbol="000001.SZ"),
            ),
            provider_code=0,
            error_code=None,
            error_message=None,
        ),
    )

    assert code == runner.EXIT_SUCCESS
    assert output["state"] == "success"
    assert provider_fact_count(db_path) == 2


def test_fanout_snapshot_requires_every_requested_value_at_one_bar_end() -> None:
    binding = _registry().provider_binding("cn.synthetic.runner", "tushare")
    policy = ResponseCompletenessPolicy(
        strategy="unique_primary_key_snapshot",
        fixed_field_matches=MappingProxyType({}),
        fanout_field="ts_code",
        snapshot_field="time",
    )
    outcome = ProviderCallOutcome(
        state="success",
        rows=({"ts_code": "000001.SZ", "time": "2026-07-28 15:00:00"},),
        provider_code=0,
        error_code=None,
        error_message=None,
    )

    def call(symbol: str) -> native_ingest.ProviderCall:
        return native_ingest.ProviderCall(
            identity=ProviderRequestIdentity(
                request_variant=MappingProxyType({}),
                fanout_parameter="ts_code",
                fanout_values=(symbol,),
                page_offset=None,
                page_index=0,
            ),
            outcome=outcome,
            call_index=0,
            retry_index=0,
        )

    rows = (
        {"ts_code": "000001.SZ", "time": "2026-07-28 15:00:00"},
        {"ts_code": "000002.SZ", "time": "2026-07-28 15:00:00"},
    )
    native_ingest._validate_fanout_snapshot(  # noqa: SLF001
        binding,
        policy,
        rows,
        calls=(call("000001.SZ"), call("000002.SZ")),
    )

    with pytest.raises(ValueError, match="has no requested values"):
        native_ingest._validate_fanout_snapshot(  # noqa: SLF001
            binding,
            policy,
            rows,
            calls=(),
        )
    with pytest.raises(ValueError, match="fanout coverage is incomplete"):
        native_ingest._validate_fanout_snapshot(  # noqa: SLF001
            binding,
            policy,
            rows[:1],
            calls=(call("000001.SZ"), call("000002.SZ")),
        )
    with pytest.raises(ValueError, match="snapshot time is inconsistent"):
        native_ingest._validate_fanout_snapshot(
            binding,
            policy,
            (rows[0], {"ts_code": "000002.SZ", "time": "2026-07-28 14:55:00"}),
            calls=(call("000001.SZ"), call("000002.SZ")),
        )  # noqa: SLF001


def test_public_fanout_coverage_reason_code_preserves_empty_policies(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        ingest_receipts,
        "_utc_now",
        lambda: "2026-07-20T08:01:00+00:00",
    )
    partial_registry = _fanout_snapshot_registry(empty_data_policy="allowed")
    partial_collector = _FanoutOutcomeCollector(
        {
            "600000.SH": ProviderCallOutcome(
                state="success",
                rows=(
                    {
                        "ts_code": "600000.SH",
                        "trade_date": "20260720",
                        "close": 12.5,
                    },
                ),
                provider_code=0,
                error_code=None,
                error_message=None,
            ),
            "000001.SZ": _variant_empty(),
        }
    )
    partial_db = tmp_path / "partial.sqlite"
    _database(partial_db)

    partial = native_ingest.collect_provider_native_dataset(
        partial_db,
        registry=partial_registry,
        collector=partial_collector,
        dataset_id="cn.synthetic.runner",
        request_window={},
        attempt_id="public-partial-fanout",
        started_at="2026-07-20T08:00:00+00:00",
    )

    assert partial.status == "failed"
    assert partial.errors == (
        "validation_failed",
        "validation_fanout_coverage_incomplete",
    )
    assert provider_fact_count(partial_db) == 0
    with sqlite3.connect(partial_db) as conn:
        receipts = [
            json.loads(notes)
            for (notes,) in conn.execute(
                "SELECT notes FROM market_ingest_runs ORDER BY run_id"
            )
        ]
    assert len(receipts) == 2
    assert {tuple(receipt["errors"]) for receipt in receipts} == {
        ("validation_failed", "validation_fanout_coverage_incomplete"),
    }
    partial_projection = load_dataset_runtime_projection(
        partial_db,
        partial_registry.resolve("cn.synthetic.runner"),
        registry=partial_registry,
        now=datetime(2026, 7, 20, 9, tzinfo=timezone.utc),
    )
    assert partial_projection.state == "failed"
    assert partial_projection.reasons == (
        "validation_failed",
        "validation_fanout_coverage_incomplete",
    )

    empty_registry = _fanout_snapshot_registry(empty_data_policy="allowed")
    empty_collector = _FanoutOutcomeCollector(
        {"600000.SH": _variant_empty(), "000001.SZ": _variant_empty()}
    )
    empty_db = tmp_path / "allowed-empty.sqlite"
    _database(empty_db)
    empty = native_ingest.collect_provider_native_dataset(
        empty_db,
        registry=empty_registry,
        collector=empty_collector,
        dataset_id="cn.synthetic.runner",
        request_window={},
        attempt_id="public-allowed-empty-fanout",
        started_at="2026-07-20T08:00:00+00:00",
    )
    assert empty.status == "empty"
    assert empty.errors == ()
    assert provider_fact_count(empty_db) == 0
    with sqlite3.connect(empty_db) as conn:
        assert conn.execute(
            "SELECT status, COUNT(*) FROM market_ingest_runs GROUP BY status"
        ).fetchall() == [("empty", 2)]

    forbidden_registry = _fanout_snapshot_registry(empty_data_policy="forbidden")
    forbidden_collector = _FanoutOutcomeCollector(
        {"600000.SH": _variant_empty(), "000001.SZ": _variant_empty()}
    )
    forbidden_db = tmp_path / "forbidden-empty.sqlite"
    _database(forbidden_db)
    forbidden = native_ingest.collect_provider_native_dataset(
        forbidden_db,
        registry=forbidden_registry,
        collector=forbidden_collector,
        dataset_id="cn.synthetic.runner",
        request_window={},
        attempt_id="public-forbidden-empty-fanout",
        started_at="2026-07-20T08:00:00+00:00",
    )
    assert forbidden.status == "failed"
    assert forbidden.errors == ("validation_failed",)
    assert provider_fact_count(forbidden_db) == 0


def test_public_fanout_provider_failure_preserves_prior_success_sibling(
    tmp_path: Path,
) -> None:
    registry = _fanout_snapshot_registry(empty_data_policy="allowed")
    collector = _FanoutOutcomeCollector(
        {
            "000001.SZ": _variant_success("000001.SZ"),
            "600000.SH": _variant_failed(),
        }
    )
    db_path = tmp_path / "partial-provider-failure.sqlite"
    _database(db_path)

    result = native_ingest.collect_provider_native_dataset(
        db_path,
        registry=registry,
        collector=collector,
        dataset_id="cn.synthetic.runner",
        request_window={},
        attempt_id="018f47de-0000-7000-8000-000000000099",
        started_at="2026-07-20T08:00:00+00:00",
    )

    assert result.status == "failed"
    assert result.errors == ("permission_denied",)
    assert result.counts.committed == 1
    assert len(result.receipt_ids) == 2
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT status, rows_written FROM market_ingest_runs ORDER BY started_at, run_id"
        ).fetchall()
        assert sorted(rows) == [("failed", 0), ("success", 1)]
        assert conn.execute(
            "SELECT COUNT(*) FROM provider_dataset_rows"
        ).fetchone()[0] == 1


def test_rt_min_template_cohort_requires_the_frozen_complete_snapshot() -> None:
    registry = load_dataset_registry(ROOT / "config" / "provider_native_dataset_registry.yaml")
    dataset = registry.resolve("cn.dataset.rt_min")
    binding = registry.provider_binding(dataset.dataset_id, "tushare")
    expected = tuple(binding.request_template["ts_code"].split(","))
    assert len(expected) == 30
    assert len(set(expected)) == 30

    bar_end = "2026-08-04 14:55:00"
    complete_rows = tuple(
        {"ts_code": symbol, "freq": "5MIN", "time": bar_end}
        for symbol in expected
    )
    call = native_ingest.ProviderCall(
        identity=ProviderRequestIdentity(
            request_variant=MappingProxyType({}),
            fanout_parameter=None,
            fanout_values=(),
            page_offset=None,
            page_index=0,
        ),
        outcome=ProviderCallOutcome("success", complete_rows, 0, None, None),
        call_index=0,
        retry_index=0,
    )

    def validate(rows: tuple[dict[str, str], ...]) -> None:
        native_ingest._validate_response_completeness(  # noqa: SLF001
            dataset,
            binding,
            rows,
            request_window={},
            resolved_params=dict(binding.request_template),
            calls=(call,),
        )

    validate(complete_rows)
    with pytest.raises(ValueError, match="fanout coverage is incomplete"):
        validate(complete_rows[:-1])
    with pytest.raises(ValueError, match="duplicate primary key"):
        validate(complete_rows[:-1] + (complete_rows[0],))
    with pytest.raises(ValueError, match="fanout coverage is incomplete"):
        validate((*complete_rows[:-1], {**complete_rows[-1], "ts_code": "999999.SZ"}))
    with pytest.raises(ValueError, match="fixed field does not match request"):
        validate(({**complete_rows[0], "freq": "1MIN"}, *complete_rows[1:]))
    with pytest.raises(ValueError, match="snapshot time is inconsistent"):
        validate(
            (*complete_rows[:-1], {**complete_rows[-1], "time": "2026-08-04 14:50:00"})
        )
    dynamic_binding = replace(
        binding,
        request_template=MappingProxyType(
            {"freq": "5MIN", "ts_code": "600000.SH,${window.ts_code}"}
        ),
    )
    with pytest.raises(ValueError, match="has no requested values"):
        native_ingest._validate_response_completeness(  # noqa: SLF001
            dataset,
            dynamic_binding,
            complete_rows,
            request_window={},
            resolved_params=dict(dynamic_binding.request_template),
            calls=(call,),
        )


def test_windowed_unique_primary_key_allows_empty_fanout_partition() -> None:
    policy = ResponseCompletenessPolicy(
        strategy="windowed_unique_primary_key",
        date_field="pub_time",
        request_start_key="start_time",
        request_end_key="end_time",
        fanout_field="src",
        fixed_field_matches=MappingProxyType({}),
    )
    base = _registry()
    dataset = replace(
        base.resolve("cn.synthetic.runner"),
        fields=(
            DatasetField("src", "text", False, True, True, True),
            DatasetField("pub_time", "text", False, True, True, True),
            DatasetField("title", "text", False, True, True, True),
        ),
        primary_key=("src", "pub_time", "title"),
        default_projection=("src", "pub_time", "title"),
        as_of_field=None,
        as_of_format=None,
        range_field=None,
        partition_field=None,
    )
    binding = replace(
        base.provider_binding(dataset.dataset_id, "tushare"),
        request_template=MappingProxyType(
            {
                "start_time": "${window.start_time}",
                "end_time": "${window.end_time}",
            }
        ),
        request_window_policy=RequestWindowPolicy(
            required_keys=("start_time", "end_time"),
            formats=MappingProxyType(
                {
                    "start_time": "local_datetime_seconds",
                    "end_time": "local_datetime_seconds",
                }
            ),
            range_start_key="start_time",
            range_end_key="end_time",
            max_span_days=1,
        ),
        fanout=FanoutPolicy(
            strategy="literal_values",
            parameter="src",
            values=("source_a", "source_b"),
            batch_size=1,
        ),
        response_completeness=policy,
    )
    row = {
        "src": "source_a",
        "pub_time": "2026-07-31 10:30:00",
        "title": "one",
    }
    call = native_ingest.ProviderCall(
        identity=ProviderRequestIdentity(
            request_variant=MappingProxyType({}),
            fanout_parameter="src",
            fanout_values=("source_a",),
            page_offset=None,
            page_index=0,
        ),
        outcome=ProviderCallOutcome("success", (row,), 0, None, None),
        call_index=0,
        retry_index=0,
    )
    empty_call = replace(
        call,
        identity=replace(call.identity, fanout_values=("source_b",)),
        outcome=ProviderCallOutcome("empty", (), 0, None, None),
        call_index=1,
    )
    rows = (row,)
    native_ingest._validate_windowed_unique_primary_keys(  # noqa: SLF001
        dataset,
        binding,
        policy,
        rows,
        request_window={
            "start_time": "2026-07-31 00:00:00",
            "end_time": "2026-07-31 23:59:59",
        },
        calls=(call, empty_call),
    )

    with pytest.raises(ValueError, match="falls outside"):
        native_ingest._validate_windowed_unique_primary_keys(  # noqa: SLF001
            dataset,
            binding,
            policy,
            ({**rows[0], "pub_time": "2026-08-01 00:00:00"},),
            request_window={
                "start_time": "2026-07-31 00:00:00",
                "end_time": "2026-07-31 23:59:59",
            },
            calls=(call, empty_call),
        )
    with pytest.raises(ValueError, match="was not requested"):
        native_ingest._validate_windowed_unique_primary_keys(  # noqa: SLF001
            dataset,
            binding,
            policy,
            ({**rows[0], "src": "other"},),
            request_window={
                "start_time": "2026-07-31 00:00:00",
                "end_time": "2026-07-31 23:59:59",
            },
            calls=(call, empty_call),
        )


def test_event_stream_unique_primary_key_asserts_window_and_identity() -> None:
    policy = ResponseCompletenessPolicy(
        strategy="event_stream_unique_primary_key",
        date_field="datetime",
        request_start_key="start_time",
        request_end_key="end_time",
        fixed_field_matches=MappingProxyType({}),
        reject_at_row_limit=True,
    )
    base = _registry()
    dataset = replace(
        base.resolve("cn.synthetic.runner"),
        fields=(
            DatasetField("datetime", "text", False, True, True, True),
            DatasetField("title", "text", False, True, True, True),
            DatasetField("content", "text", True, True, True, True),
        ),
        primary_key=("datetime", "title"),
        default_projection=("datetime", "title", "content"),
        as_of_field=None,
        as_of_format=None,
        range_field=None,
        partition_field=None,
    )
    binding = replace(
        base.provider_binding(dataset.dataset_id, "tushare"),
        request_template=MappingProxyType(
            {
                "start_time": "${window.start_time}",
                "end_time": "${window.end_time}",
            }
        ),
        request_window_policy=RequestWindowPolicy(
            required_keys=("start_time", "end_time"),
            formats=MappingProxyType(
                {
                    "start_time": "local_datetime_seconds",
                    "end_time": "local_datetime_seconds",
                }
            ),
            range_start_key="start_time",
            range_end_key="end_time",
            max_span_days=1,
        ),
        response_completeness=policy,
    )
    window = {
        "start_time": "2026-07-31 00:00:00",
        "end_time": "2026-07-31 23:59:59",
    }
    rows = (
        {"datetime": "2026-07-31 09:30:00", "title": "one", "content": None},
        {"datetime": "2026-07-31 10:30:00", "title": "two", "content": "x"},
    )
    native_ingest._validate_event_stream_unique_primary_keys(  # noqa: SLF001
        dataset,
        binding,
        policy,
        rows,
        request_window=window,
    )
    # Legal-empty content windows stay admissible.
    native_ingest._validate_event_stream_unique_primary_keys(  # noqa: SLF001
        dataset,
        binding,
        policy,
        (),
        request_window=window,
    )
    with pytest.raises(ValueError, match="falls outside"):
        native_ingest._validate_event_stream_unique_primary_keys(  # noqa: SLF001
            dataset,
            binding,
            policy,
            ({"datetime": "2026-08-01 00:00:00", "title": "three", "content": None},),
            request_window=window,
        )
    with pytest.raises(ValueError):
        native_ingest._validate_event_stream_unique_primary_keys(  # noqa: SLF001
            dataset,
            binding,
            policy,
            (rows[0], dict(rows[0])),
            request_window=window,
        )


def test_fanout_row_limit_is_applied_per_provider_call() -> None:
    base = _registry()
    dataset = replace(
        base.resolve("cn.synthetic.runner"),
        primary_key=("ts_code",),
    )
    binding = replace(
        base.provider_binding(dataset.dataset_id, "tushare"),
        fanout=FanoutPolicy(
            strategy="literal_values",
            parameter="src",
            values=("source_a", "source_b"),
            batch_size=1,
        ),
        response_completeness=ResponseCompletenessPolicy(
            strategy="unique_primary_key_snapshot",
            fixed_field_matches=MappingProxyType({}),
            reject_at_row_limit=True,
        ),
        max_rows_per_attempt=2,
    )
    rows = (
        {"ts_code": "000001.SZ"},
        {"ts_code": "000002.SZ"},
    )

    def call(source: str, outcome_rows: tuple[dict[str, str], ...], index: int):
        return native_ingest.ProviderCall(
            identity=ProviderRequestIdentity(
                request_variant=MappingProxyType({}),
                fanout_parameter="src",
                fanout_values=(source,),
                page_offset=None,
                page_index=0,
            ),
            outcome=ProviderCallOutcome("success", outcome_rows, 0, None, None),
            call_index=index,
            retry_index=0,
        )

    native_ingest._validate_response_completeness(  # noqa: SLF001
        dataset,
        binding,
        rows,
        request_window={},
        resolved_params={},
        calls=(call("source_a", (rows[0],), 0), call("source_b", (rows[1],), 1)),
    )

    with pytest.raises(ValueError, match="declared row limit"):
        native_ingest._validate_response_completeness(  # noqa: SLF001
            dataset,
            binding,
            rows,
            request_window={},
            resolved_params={},
            calls=(
                call("source_a", (rows[0], rows[0]), 0),
                call("source_b", (rows[1],), 1),
            ),
        )


def test_snapshot_data_through_uses_provider_bar_time_not_collection_start() -> None:
    registry = _strategy_registry("unique_primary_key_snapshot")
    original = registry.resolve("cn.synthetic.runner")
    binding = registry.provider_binding(original.dataset_id, "tushare")
    assert binding.response_completeness is not None
    snapshot_binding = replace(
        binding,
        response_completeness=replace(
            binding.response_completeness,
            snapshot_field="trade_date",
        ),
    )
    dataset = replace(
        original,
        as_of_field=None,
        as_of_format=None,
        partition_field=None,
        provider_bindings=(snapshot_binding,),
    )
    outcome = ProviderCallOutcome(
        state="success",
        rows=(_calendar_row("20260718"),),
        provider_code=0,
        error_code=None,
        error_message=None,
    )

    assert native_ingest._data_through(  # noqa: SLF001
        dataset,
        snapshot_binding,
        outcome,
        "2026-07-28T15:05:00+00:00",
    ) == "20260718"


def test_snapshot_rejects_duplicate_primary_key_before_storage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    code, output, _, db_path = _run(
        monkeypatch,
        capsys,
        tmp_path,
        registry=_strategy_registry("unique_primary_key_snapshot"),
        request_window={},
        outcome=ProviderCallOutcome(
            state="success",
            rows=(_calendar_row("20260717"), _calendar_row("20260718")),
            provider_code=0,
            error_code=None,
            error_message=None,
        ),
    )

    assert code == runner.EXIT_VALIDATION
    assert output["state"] == "validation"
    assert output["error_codes"] == ["validation_failed"]
    with sqlite3.connect(db_path) as conn:
        assert provider_fact_count(db_path) == 0
        assert success_receipt_count(db_path) == 0
        receipt_rows = conn.execute(
            "SELECT status, notes FROM market_ingest_runs"
        ).fetchall()
        assert [row[0] for row in receipt_rows] == ["failed"]
        assert json.loads(receipt_rows[0][1])["data_through"] is None


def test_snapshot_rejects_mixed_homogeneous_snapshot_field_before_storage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    base = _strategy_registry("unique_primary_key_snapshot")
    dataset = base.resolve("cn.synthetic.runner")
    binding = base.provider_binding(dataset.dataset_id, "tushare")
    assert binding.response_completeness is not None
    registry = DatasetRegistry(
        (
            replace(
                dataset,
                provider_bindings=(
                    replace(
                        binding,
                        response_completeness=replace(
                            binding.response_completeness,
                            snapshot_field="trade_date",
                        ),
                    ),
                ),
            ),
        )
    )

    code, output, _, db_path = _run(
        monkeypatch,
        capsys,
        tmp_path,
        registry=registry,
        request_window={},
        outcome=ProviderCallOutcome(
            state="success",
            rows=(
                _calendar_row("20260717"),
                _calendar_row("20260718", symbol="000001.SZ"),
            ),
            provider_code=0,
            error_code=None,
            error_message=None,
        ),
    )

    assert code == runner.EXIT_VALIDATION
    assert output["state"] == "validation"
    assert provider_fact_count(db_path) == 0
    assert success_receipt_count(db_path) == 0


def test_snapshot_preserves_unusable_key_degraded_payload_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    payload = _calendar_row("20260717", symbol="")
    code, output, _, db_path = _run(
        monkeypatch,
        capsys,
        tmp_path,
        registry=_strategy_registry("unique_primary_key_snapshot"),
        request_window={},
        outcome=ProviderCallOutcome(
            state="success",
            rows=(payload,),
            provider_code=0,
            error_code=None,
            error_message=None,
        ),
    )

    assert code == runner.EXIT_SUCCESS
    assert output["state"] == "success"
    with sqlite3.connect(db_path) as conn:
        row_key, quality_state, issues_json, payload_json = conn.execute(
            "SELECT row_key, quality_state, quality_issues_json, payload_json "
            "FROM provider_dataset_rows"
        ).fetchone()
    assert row_key.startswith("payload:")
    assert quality_state == "degraded"
    assert "snapshot_key_fallback:blank:ts_code" in json.loads(issues_json)
    assert json.loads(payload_json) == payload


def test_snapshot_rejects_exact_provider_row_cap_before_storage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    code, output, _, db_path = _run(
        monkeypatch,
        capsys,
        tmp_path,
        registry=_strategy_registry(
            "unique_primary_key_snapshot", max_rows_per_attempt=2
        ),
        request_window={},
        outcome=ProviderCallOutcome(
            state="success",
            rows=(
                _calendar_row("20260717"),
                _calendar_row("20260718", symbol="000001.SZ"),
            ),
            provider_code=0,
            error_code=None,
            error_message=None,
        ),
    )

    assert code == runner.EXIT_VALIDATION
    assert output["state"] == "validation"
    assert output["error_codes"] == ["validation_failed"]
    with sqlite3.connect(db_path) as conn:
        assert provider_fact_count(db_path) == 0
        assert success_receipt_count(db_path) == 0
        receipt_rows = conn.execute(
            "SELECT status, notes FROM market_ingest_runs"
        ).fetchall()
        assert [row[0] for row in receipt_rows] == ["failed"]
        assert json.loads(receipt_rows[0][1])["data_through"] is None


def test_partition_accepts_unique_rows_matching_requested_date(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    code, output, _, db_path = _run(
        monkeypatch,
        capsys,
        tmp_path,
        registry=_strategy_registry("single_partition_unique_primary_key"),
        request_window={"trade_date": "20260717"},
        outcome=ProviderCallOutcome(
            state="success",
            rows=(
                _calendar_row("20260717"),
                _calendar_row("20260717", symbol="000001.SZ"),
            ),
            provider_code=0,
            error_code=None,
            error_message=None,
        ),
    )

    assert code == runner.EXIT_SUCCESS
    assert output["state"] == "success"
    assert provider_fact_count(db_path) == 2


@pytest.mark.parametrize("trade_date", ("20260718", "2026071x"))
def test_partition_rejects_wrong_or_invalid_trade_date_before_storage(
    trade_date: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    code, output, _, db_path = _run(
        monkeypatch,
        capsys,
        tmp_path,
        registry=_strategy_registry("single_partition_unique_primary_key"),
        request_window={"trade_date": "20260717"},
        outcome=ProviderCallOutcome(
            state="success",
            rows=(_calendar_row(trade_date),),
            provider_code=0,
            error_code=None,
            error_message=None,
        ),
    )

    assert code == runner.EXIT_VALIDATION
    assert output["state"] == "validation"
    assert output["error_codes"] == ["validation_failed"]
    assert provider_fact_count(db_path) == 0
    assert success_receipt_count(db_path) == 0


def test_partition_rejects_duplicate_primary_key_before_storage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    code, output, _, db_path = _run(
        monkeypatch,
        capsys,
        tmp_path,
        registry=_strategy_registry("single_partition_unique_primary_key"),
        request_window={"trade_date": "20260717"},
        outcome=ProviderCallOutcome(
            state="success",
            rows=(_calendar_row("20260717"), _calendar_row("20260717")),
            provider_code=0,
            error_code=None,
            error_message=None,
        ),
    )

    assert code == runner.EXIT_VALIDATION
    assert output["state"] == "validation"
    assert output["error_codes"] == ["validation_failed"]
    assert provider_fact_count(db_path) == 0
    assert success_receipt_count(db_path) == 0


def test_partition_preserves_unusable_nonpartition_key_degraded_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    code, output, _, db_path = _run(
        monkeypatch,
        capsys,
        tmp_path,
        registry=_strategy_registry("single_partition_unique_primary_key"),
        request_window={"trade_date": "20260717"},
        outcome=ProviderCallOutcome(
            state="success",
            rows=(_calendar_row("20260717", symbol=""),),
            provider_code=0,
            error_code=None,
            error_message=None,
        ),
    )

    assert code == runner.EXIT_SUCCESS
    assert output["state"] == "success"
    with sqlite3.connect(db_path) as conn:
        row_key, issues_json = conn.execute(
            "SELECT row_key, quality_issues_json FROM provider_dataset_rows"
        ).fetchone()
    assert row_key.startswith("payload:")
    assert "snapshot_key_fallback:blank:ts_code" in json.loads(issues_json)


def test_partition_rejects_exact_provider_row_cap_before_storage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    code, output, _, db_path = _run(
        monkeypatch,
        capsys,
        tmp_path,
        registry=_strategy_registry(
            "single_partition_unique_primary_key", max_rows_per_attempt=2
        ),
        request_window={"trade_date": "20260717"},
        outcome=ProviderCallOutcome(
            state="success",
            rows=(
                _calendar_row("20260717"),
                _calendar_row("20260717", symbol="000001.SZ"),
            ),
            provider_code=0,
            error_code=None,
            error_message=None,
        ),
    )

    assert code == runner.EXIT_VALIDATION
    assert output["state"] == "validation"
    assert output["error_codes"] == ["validation_failed"]
    assert provider_fact_count(db_path) == 0
    assert success_receipt_count(db_path) == 0


def test_partition_empty_is_recorded_empty_when_policy_allows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    code, output, _, db_path = _run(
        monkeypatch,
        capsys,
        tmp_path,
        registry=_strategy_registry(
            "single_partition_unique_primary_key", empty_data_policy="allowed"
        ),
        request_window={"trade_date": "20260717"},
        outcome=ProviderCallOutcome(
            state="empty",
            rows=(),
            provider_code=0,
            error_code=None,
            error_message=None,
        ),
    )

    assert code == runner.EXIT_EMPTY
    assert output["state"] == "empty"
    assert provider_fact_count(db_path) == 0
    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT status FROM market_ingest_runs").fetchone() == (
            "empty",
        )


def test_success_empty_and_failed_receipts_keep_config_hash_and_honest_data_through(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    registry = _strategy_registry(
        "unique_primary_key_snapshot", empty_data_policy="allowed"
    )
    dataset = registry.resolve("cn.synthetic.runner")
    binding = registry.provider_binding(dataset.dataset_id, "tushare")
    expected_hash = native_ingest._config_hash(dataset, binding)  # noqa: SLF001

    _, _, _, success_db = _run(
        monkeypatch,
        capsys,
        tmp_path / "success",
        registry=registry,
        request_window={},
        outcome=ProviderCallOutcome(
            state="success",
            rows=(_calendar_row("20260718"),),
            provider_code=0,
            error_code=None,
            error_message=None,
        ),
    )
    _, _, _, empty_db = _run(
        monkeypatch,
        capsys,
        tmp_path / "empty",
        registry=registry,
        request_window={},
        outcome=ProviderCallOutcome(
            state="empty",
            rows=(),
            provider_code=0,
            error_code=None,
            error_message=None,
        ),
    )
    _, _, _, failed_db = _run(
        monkeypatch,
        capsys,
        tmp_path / "failed",
        registry=registry,
        request_window={},
        outcome=ProviderCallOutcome(
            state="success",
            rows=(_calendar_row("20260717"), _calendar_row("20260718")),
            provider_code=0,
            error_code=None,
            error_message=None,
        ),
    )

    for db_path, expected_data_through in (
        (success_db, "20260718"),
        (empty_db, None),
        (failed_db, None),
    ):
        with sqlite3.connect(db_path) as conn:
            notes = json.loads(
                conn.execute("SELECT notes FROM market_ingest_runs").fetchone()[0]
            )
        assert notes["config_hash"] == expected_hash
        assert notes["data_through"] == expected_data_through


def test_response_completeness_contract_changes_the_ingest_config_hash() -> None:
    registry = _registry()
    dataset = registry.resolve("cn.synthetic.runner")
    binding = registry.provider_binding(dataset.dataset_id, "tushare")
    assert binding.response_completeness is not None
    changed_binding = replace(
        binding,
        response_completeness=replace(
            binding.response_completeness,
            fixed_field_matches=MappingProxyType({}),
        ),
    )

    assert native_ingest._config_hash(  # noqa: SLF001
        dataset, binding
    ) != native_ingest._config_hash(dataset, changed_binding)  # noqa: SLF001


def test_transport_profile_changes_the_ingest_config_hash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = _registry()
    dataset = registry.resolve("cn.synthetic.runner")
    binding = registry.provider_binding(dataset.dataset_id, "tushare")
    original = ingest_contract_module.provider_ingest_config_hash(dataset, binding)

    monkeypatch.setattr(
        ingest_contract_module,
        "provider_transport_profile",
        lambda provider: {
            "data_provider": provider,
            "endpoint": "https://api.quicksync.cn",
            "profile_id": "quicksync-tushare-compatible.changed-test",
            "profile_sha256": "f" * 64,
            "redirects_allowed": False,
            "tls_minimum": "TLSv1.3",
            "tls_maximum": "TLSv1.3",
            "transport_service": "quicksync",
        },
    )

    assert (
        ingest_contract_module.provider_ingest_config_hash(dataset, binding) != original
    )


@pytest.mark.parametrize(
    "case",
    (
        "request_shape",
        "request_variants",
        "fanout",
        "pagination",
        "as_of_format",
        "empty_data_policy",
        "read_discriminator_value",
        "target_tables",
        "read_model_adapter",
    ),
)
def test_every_provider_native_request_and_admission_field_changes_config_hash(
    case: str,
) -> None:
    registry = _registry()
    dataset = registry.resolve("cn.synthetic.runner")
    binding = registry.provider_binding(dataset.dataset_id, "tushare")
    changed_dataset = dataset
    changed_binding = binding

    if case == "request_shape":
        changed_binding = replace(binding, request_shape="entity_fanout")
    elif case == "request_variants":
        changed_binding = replace(
            binding,
            request_variants=(MappingProxyType({"exchange": "SSE"}),),
        )
    elif case == "fanout":
        changed_binding = replace(
            binding,
            fanout=FanoutPolicy(
                strategy="registry_entities",
                parameter="ts_code",
                source_dataset_id="cn.synthetic.source",
                source_field="ts_code",
                batch_size=10,
            ),
        )
    elif case == "pagination":
        changed_binding = replace(
            binding,
            pagination=PaginationPolicy(
                strategy="offset",
                limit_parameter="limit",
                offset_parameter="offset",
                page_size=100,
                max_pages=2,
            ),
        )
    elif case == "as_of_format":
        changed_dataset = replace(dataset, as_of_format="iso_datetime")
    elif case == "empty_data_policy":
        changed_dataset = replace(dataset, empty_data_policy="allowed")
    elif case == "read_discriminator_value":
        changed_binding = replace(
            binding,
            read_discriminator_value="synthetic_runner_v2",
        )
    elif case == "target_tables":
        changed_binding = replace(binding, target_tables=("other_table",))
    elif case == "read_model_adapter":
        changed_dataset = replace(
            dataset,
            read_model_adapter=replace(
                dataset.read_model_adapter,
                row_key_strategy="payload_hash",
            ),
        )
    else:  # pragma: no cover - the parametrization is exhaustive.
        raise AssertionError(case)

    assert ingest_contract_module.provider_ingest_config_hash(
        changed_dataset,
        changed_binding,
    ) != ingest_contract_module.provider_ingest_config_hash(dataset, binding)


@pytest.mark.parametrize(
    ("field_name", "changed_value"),
    (
        ("strategy", "single_partition_unique_primary_key"),
        ("date_field", "trade_date"),
        ("request_start_key", "start_date"),
        ("request_end_key", "end_date"),
        ("partition_field", "trade_date"),
        ("request_partition_key", "trade_date"),
        ("fixed_field_matches", MappingProxyType({"ts_code": "symbol"})),
        ("reject_at_row_limit", True),
    ),
)
def test_response_completeness_every_behavioral_field_changes_config_hash(
    field_name: str,
    changed_value: object,
) -> None:
    registry = _strategy_registry("unique_primary_key_snapshot")
    dataset = registry.resolve("cn.synthetic.runner")
    binding = registry.provider_binding(dataset.dataset_id, "tushare")
    assert binding.response_completeness is not None
    binding = replace(
        binding,
        response_completeness=replace(
            binding.response_completeness, reject_at_row_limit=False
        ),
    )
    changed_binding = replace(
        binding,
        response_completeness=replace(
            binding.response_completeness, **{field_name: changed_value}
        ),
    )

    assert native_ingest._config_hash(  # noqa: SLF001
        dataset, binding
    ) != native_ingest._config_hash(dataset, changed_binding)  # noqa: SLF001


def test_provider_admission_failure_uses_validation_exit_code(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    outcome = ProviderCallOutcome(
        state="success",
        rows=(
            {"ts_code": "600000.SH", "trade_date": "20260717", "close": 12.5},
            {"ts_code": "600000.SH", "trade_date": "20260717", "close": 13.0},
        ),
        provider_code=0,
        error_code=None,
        error_message=None,
    )

    code, output, fake, db_path = _run(
        monkeypatch,
        capsys,
        tmp_path,
        outcome=outcome,
    )

    assert code == runner.EXIT_VALIDATION
    assert output["state"] == "validation"
    assert output["error_codes"] == ["validation_failed"]
    assert len(fake.calls) == 1
    with sqlite3.connect(db_path) as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM provider_dataset_rows"
        ).fetchone() == (0,)
        assert conn.execute("SELECT status FROM market_ingest_runs").fetchone() == (
            "failed",
        )


def test_validation_receipt_persists_allowlisted_predicate_without_diagnostics(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base = _registry()
    dataset = base.resolve("cn.synthetic.runner")
    binding = replace(
        base.provider_binding(dataset.dataset_id, "tushare"),
        requested_fields=("ts_code",),
    )
    registry = DatasetRegistry((replace(dataset, provider_bindings=(binding,)),))
    outcome = ProviderCallOutcome(
        state="success",
        rows=(({"ts_code": "600000.SH"}),),
        provider_code=0,
        error_code=None,
        error_message=None,
        response_fields=(),
    )
    db_path = tmp_path / "validation-predicate.sqlite"
    _database(db_path)
    monkeypatch.setattr(
        ingest_receipts,
        "_utc_now",
        lambda: "2026-07-17T01:01:00+00:00",
    )
    monkeypatch.setattr(
        native_ingest,
        "_validate_response_field_coverage",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            native_ingest.ProviderValidationError(
                "Authorization: Bearer SECRET_TOKEN response-body-marker",
                predicate=ingest_receipts.VALIDATION_RESPONSE_FIELD_COVERAGE,
            )
        ),
    )
    result = native_ingest.collect_provider_native_dataset(
        db_path,
        registry=registry,
        collector=_FakeCollector(outcome),
        dataset_id=dataset.dataset_id,
        request_window={"start_date": "20260717", "end_date": "20260717"},
        attempt_id="validation-predicate",
        started_at="2026-07-17T01:00:00+00:00",
    )
    assert result.status == "failed"
    with sqlite3.connect(db_path) as conn:
        notes_text = conn.execute("SELECT notes FROM market_ingest_runs").fetchone()[0]
    notes = json.loads(notes_text)
    assert notes["errors"] == ["validation_failed", "response_field_coverage"]
    assert all(
        forbidden not in notes_text
        for forbidden in (
            "Authorization",
            "Bearer",
            "SECRET_TOKEN",
            "response-body-marker",
        )
    )
def test_paused_dataset_is_rejected_before_provider_call(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    registry = _registry(activation_state="paused")
    fake = _FakeCollector(
        ProviderCallOutcome(
            state="empty",
            rows=(),
            provider_code=0,
            error_code=None,
            error_message=None,
        )
    )
    monkeypatch.setattr(runner, "load_runtime_dataset_registry", lambda: registry)
    monkeypatch.setattr(runner, "TushareCollector", lambda: fake)
    db_path = tmp_path / "facts.sqlite"
    _database(db_path)

    code = runner.main(
        [
            "--db-path",
            str(db_path),
            "--dataset-id",
            "cn.synthetic.runner",
            "--request-window-json",
            '{"start_date":"20260701","end_date":"20260717"}',
            "--execute",
        ]
    )

    output = json.loads(capsys.readouterr().out)
    assert code == runner.EXIT_VALIDATION
    assert output == {
        "error_code": "invalid_request",
        "mode": "execute",
        "state": "validation",
    }
    assert fake.calls == []
    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM market_ingest_runs").fetchone() == (
            0,
        )


@pytest.mark.parametrize(
    "window_json",
    [
        '{"start_date":"20260701"}',
        '{"start_date":"20260701","end_date":"20260717","extra":"x"}',
        '{"start_date":"first","start_date":"second","end_date":"20260717"}',
        '["not", "an", "object"]',
        '{"start_date":1,"end_date":"20260717"}',
        '{"start_date":"2026-07-01","end_date":"20260717"}',
        '{"start_date":"20260718","end_date":"20260717"}',
        '{"start_date":"20250101","end_date":"20260102"}',
    ],
)
def test_request_window_is_strict_and_fails_before_provider_or_database(
    window_json: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    fake = _FakeCollector()
    monkeypatch.setattr(runner, "load_runtime_dataset_registry", _registry)
    monkeypatch.setattr(runner, "TushareCollector", lambda: fake)
    db_path = tmp_path / "must-not-be-created.sqlite"

    code = runner.main(
        [
            "--db-path",
            str(db_path),
            "--dataset-id",
            "cn.synthetic.runner",
            "--request-window-json",
            window_json,
            "--execute",
        ]
    )

    output = json.loads(capsys.readouterr().out)
    assert code == runner.EXIT_VALIDATION
    assert output["state"] == "validation"
    assert fake.calls == []
    assert not db_path.exists()


@pytest.mark.parametrize(
    ("format_name", "window"),
    [
        ("yyyymmdd", {"start": "20240229", "end": "20240229"}),
        ("yyyymm", {"period": "202602"}),
        ("yyyy_qn", {"period": "2026Q4"}),
        ("yyyyww", {"period": "202653"}),
        (
            "local_datetime_seconds",
            {
                "start": "2026-07-20 00:00:00",
                "end": "2026-07-20 23:59:59",
            },
        ),
    ],
)
def test_request_window_codec_accepts_each_runtime_format_canonically(
    format_name: str,
    window: dict[str, str],
) -> None:
    binding = _request_window_binding(format_name, ranged=len(window) == 2)

    normalized, params = native_ingest._resolved_request(binding, window)

    assert normalized == dict(sorted(window.items()))
    assert params == {
        f"provider_{key}": value for key, value in sorted(window.items())
    }


@pytest.mark.parametrize("format_name", ["identity", "rfc3339"])
def test_request_window_codec_keeps_unused_formats_fail_closed(
    format_name: str,
) -> None:
    binding = _request_window_binding(format_name)

    with pytest.raises(ValueError, match="runtime request_window format"):
        native_ingest._resolved_request(binding, {"period": "20260720"})


@pytest.mark.parametrize(
    ("format_name", "value"),
    [
        ("yyyymmdd", "20230229"),
        ("yyyymm", "202613"),
        ("yyyy_qn", "2026Q0"),
        ("yyyyww", "202654"),
    ],
)
def test_request_window_codec_rejects_noncanonical_calendar_values(
    format_name: str,
    value: str,
) -> None:
    binding = _request_window_binding(format_name)

    with pytest.raises(ValueError, match="request_window.*invalid"):
        native_ingest._resolved_request(binding, {"period": value})


def test_local_datetime_window_rejects_invalid_order_and_span() -> None:
    binding = _request_window_binding(
        "local_datetime_seconds", ranged=True, max_span_days=1
    )
    invalid = (
        (
            {"start": "2026-07-20T00:00:00", "end": "2026-07-20 00:00:00"},
            "request_window.*invalid",
        ),
        (
            {"start": "2026-07-20 00:00:01", "end": "2026-07-20 00:00:00"},
            "range start",
        ),
        (
            {"start": "2026-07-20 23:59:59", "end": "2026-07-21 00:00:00"},
            "max_span_days",
        ),
    )

    for window, message in invalid:
        with pytest.raises(ValueError, match=message):
            native_ingest._resolved_request(binding, window)


def test_complete_variant_cohort_accepts_success_success_and_legal_empty(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        ingest_receipts,
        "_utc_now",
        lambda: "2026-07-20T08:01:00+00:00",
    )
    collector = _VariantOutcomeCollector(
        MappingProxyType(
            {
                "L": _variant_success("600001.SH"),
                "D": _variant_success("600002.SH"),
                "P": _variant_empty(),
            }
        )
    )
    registry = _variant_cohort_registry(empty_data_policy="forbidden")
    db_path = tmp_path / "facts.sqlite"
    _database(db_path)

    result = native_ingest.collect_provider_native_dataset(
        db_path,
        registry=registry,
        collector=collector,
        dataset_id="cn.synthetic.runner",
        request_window={},
        attempt_id="variant-cohort-root",
        started_at="2026-07-20T08:00:00+00:00",
    )

    assert result.status == "success"
    assert result.errors == ()
    assert collector.calls == ["L", "D", "P"]
    assert provider_fact_count(db_path) == 2
    with sqlite3.connect(db_path) as conn:
        payloads = [
            json.loads(notes)
            for (notes,) in conn.execute(
                "SELECT notes FROM market_ingest_runs ORDER BY run_id"
            )
        ]
    assert {payload["status"] for payload in payloads} == {"success", "empty"}
    assert {
        payload["request_identity"]["request_variant"]["list_status"]
        for payload in payloads
    } == {"L", "D", "P"}
    assert {
        payload["attempt_id"].split(":provider-call:", 1)[0]
        for payload in payloads
    } == {"variant-cohort-root"}
    projection = load_dataset_runtime_projection(
        db_path,
        registry.resolve("cn.synthetic.runner"),
        registry=registry,
        now=datetime(2026, 7, 20, 9, tzinfo=timezone.utc),
    )
    assert projection.state == "success"
    assert projection.degraded is False


def test_one_shot_execute_runs_the_complete_registry_variant_cohort(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    registry = _variant_cohort_registry(empty_data_policy="forbidden")
    collector = _VariantOutcomeCollector(
        MappingProxyType(
            {
                "L": _variant_success("600001.SH"),
                "D": _variant_success("600002.SH"),
                "P": _variant_empty(),
            }
        )
    )
    monkeypatch.setattr(runner, "load_runtime_dataset_registry", lambda: registry)
    monkeypatch.setattr(runner, "TushareCollector", lambda: collector)
    monkeypatch.setattr(
        ingest_receipts,
        "_utc_now",
        lambda: "2026-07-20T08:01:00+00:00",
    )
    db_path = tmp_path / "facts.sqlite"
    _database(db_path)

    code = runner.main(
        [
            "--db-path",
            str(db_path),
            "--dataset-id",
            "cn.synthetic.runner",
            "--request-window-json",
            "{}",
            "--attempt-id",
            "11111111-1111-4111-8111-111111111111",
            "--started-at",
            "2026-07-20T08:00:00+00:00",
            "--execute",
        ]
    )

    assert code == runner.EXIT_SUCCESS
    assert json.loads(capsys.readouterr().out)["state"] == "success"
    assert collector.calls == ["L", "D", "P"]


def test_complete_all_empty_variant_cohort_applies_forbidden_policy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        ingest_receipts,
        "_utc_now",
        lambda: "2026-07-20T08:01:00+00:00",
    )
    registry = _variant_cohort_registry(empty_data_policy="forbidden")
    collector = _VariantOutcomeCollector(
        MappingProxyType({status: _variant_empty() for status in ("L", "D", "P")})
    )
    db_path = tmp_path / "facts.sqlite"
    _database(db_path)

    result = native_ingest.collect_provider_native_dataset(
        db_path,
        registry=registry,
        collector=collector,
        dataset_id="cn.synthetic.runner",
        request_window={},
        attempt_id="all-empty-variant-cohort",
        started_at="2026-07-20T08:00:00+00:00",
    )

    assert collector.calls == ["L", "D", "P"]
    assert result.status == "failed"
    assert result.errors == ("validation_failed",)
    with sqlite3.connect(db_path) as conn:
        assert conn.execute(
            "SELECT status, COUNT(*) FROM market_ingest_runs GROUP BY status"
        ).fetchall() == [("empty", 3)]
    projection = load_dataset_runtime_projection(
        db_path,
        registry.resolve("cn.synthetic.runner"),
        registry=registry,
        now=datetime(2026, 7, 20, 9, tzinfo=timezone.utc),
    )
    assert projection.state == "failed"
    assert projection.reasons == ("validation_failed",)


@pytest.mark.parametrize(
    ("p_outcome", "expected_reason"),
    [
        (None, "variant_cohort_incomplete"),
        (_variant_failed(), "permission_denied"),
    ],
    ids=("missing-p", "failed-p"),
)
def test_incomplete_or_failed_variant_cohort_projects_failed(
    tmp_path: Path,
    p_outcome: ProviderCallOutcome | None,
    expected_reason: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        ingest_receipts,
        "_utc_now",
        lambda: "2026-07-20T08:01:00+00:00",
    )
    registry = _variant_cohort_registry(empty_data_policy="forbidden")
    db_path = tmp_path / "facts.sqlite"
    _database(db_path)
    started_at = "2026-07-20T08:00:00+00:00"
    outcomes = {
        "L": _variant_success("600001.SH"),
        "D": _variant_success("600002.SH"),
    }
    if p_outcome is not None:
        outcomes["P"] = p_outcome
    def collect() -> IngestResult:
        return native_ingest.collect_provider_native_dataset(
            db_path,
            registry=registry,
            collector=_VariantOutcomeCollector(MappingProxyType(outcomes)),
            dataset_id="cn.synthetic.runner",
            request_window={},
            attempt_id="11111111-1111-4111-8111-111111111111",
            started_at=started_at,
        )
    if p_outcome is None:
        with pytest.raises(KeyError, match="P"):
            collect()
    else:
        result = collect()
        assert result.status == "failed"
        assert result.counts.committed == 2

    projection = load_dataset_runtime_projection(
        db_path,
        registry.resolve("cn.synthetic.runner"),
        registry=registry,
        now=datetime(2026, 7, 20, 9, tzinfo=timezone.utc),
    )

    assert projection.state == "failed"
    assert projection.degraded is True
    assert projection.data_through is None
    assert projection.reasons == (expected_reason,)
    with sqlite3.connect(db_path) as conn:
        evidence = project_dataset_runtime_evidence(
            conn,
            registry.resolve("cn.synthetic.runner"),
            registry=registry,
            now=datetime(2026, 7, 20, 9, tzinfo=timezone.utc),
        )
    assert evidence.last_success_receipt_id is None
    assert evidence.last_success_receipt_ids == ()


def test_unexpected_provider_exception_cannot_leak_secret_material(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    secret = "Bearer provider-token-must-not-escape"
    fake = _FakeCollector(error=RuntimeError(secret))
    monkeypatch.setattr(runner, "load_runtime_dataset_registry", _registry)
    monkeypatch.setattr(runner, "TushareCollector", lambda: fake)
    db_path = tmp_path / "facts.sqlite"
    _database(db_path)

    code = runner.main(
        [
            "--db-path",
            str(db_path),
            "--dataset-id",
            "cn.synthetic.runner",
            "--request-window-json",
            '{"start_date":"20260701","end_date":"20260717"}',
            "--execute",
        ]
    )

    rendered = capsys.readouterr().out
    assert code == runner.EXIT_FAILED
    assert secret not in rendered
    assert "provider-token" not in rendered
    assert json.loads(rendered) == {
        "error_code": "collection_failed",
        "mode": "execute",
        "state": "failed",
    }


@pytest.mark.parametrize(
    ("flag", "value"), [("--attempt-id", ""), ("--started-at", "")]
)
def test_explicit_empty_optional_identity_is_not_silently_replaced(
    flag: str,
    value: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    fake = _FakeCollector()
    monkeypatch.setattr(runner, "load_runtime_dataset_registry", _registry)
    monkeypatch.setattr(runner, "TushareCollector", lambda: fake)
    db_path = tmp_path / "must-not-be-created.sqlite"

    code = runner.main(
        [
            "--db-path",
            str(db_path),
            "--dataset-id",
            "cn.synthetic.runner",
            "--request-window-json",
            '{"start_date":"20260701","end_date":"20260717"}',
            flag,
            value,
            "--execute",
        ]
    )

    assert code == runner.EXIT_VALIDATION
    assert json.loads(capsys.readouterr().out)["state"] == "validation"
    assert fake.calls == []
    assert not db_path.exists()


def test_cli_has_no_provider_api_or_field_override() -> None:
    args = runner.parse_args(
        [
            "--db-path",
            "facts.sqlite",
            "--dataset-id",
            "cn.synthetic.runner",
            "--request-window-json",
            "{}",
        ]
    )

    assert not hasattr(args, "api_name")
    assert not hasattr(args, "fields")


def test_singular_request_identity_reaches_typed_storage_receipt_handoff(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base = _registry()
    dataset = base.resolve("cn.synthetic.runner")
    binding = base.provider_binding(dataset.dataset_id, "tushare")
    variant = MappingProxyType({"symbol": "600001.SH"})
    binding = replace(
        binding,
        request_variants=(MappingProxyType({"symbol": "600000.SH"}), variant),
        pagination=PaginationPolicy(
            strategy="offset",
            limit_parameter="limit",
            offset_parameter="offset",
            page_size=2,
            max_pages=2,
        ),
    )
    dataset = replace(dataset, provider_bindings=(binding,))
    registry = DatasetRegistry((dataset,))
    fake = _FakeCollector(
        ProviderCallOutcome(
            state="success",
            rows=(
                {
                    "ts_code": "600001.SH",
                    "trade_date": "20260717",
                    "close": 12.5,
                },
            ),
            provider_code=0,
            error_code=None,
            error_message=None,
        )
    )
    captured: list[tuple[native_ingest.ProviderCall, ...]] = []
    original = native_ingest._persist_provider_execution

    def capture(*args: object, **kwargs: object) -> IngestResult:
        execution = kwargs["execution"]
        assert isinstance(execution, native_ingest.ProviderExecution)
        captured.append(execution.calls)
        return original(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(native_ingest, "_persist_provider_execution", capture)
    db_path = tmp_path / "facts.sqlite"
    _database(db_path)

    result = native_ingest.collect_provider_native_dataset(
        db_path,
        registry=registry,
        collector=fake,
        dataset_id=dataset.dataset_id,
        request_window={"start_date": "20260717", "end_date": "20260717"},
        request_variant=variant,
        attempt_id="typed-identity-attempt",
        started_at=datetime.now(timezone.utc).isoformat(),
    )

    assert result.status == "success"
    assert result.errors == ()
    assert provider_fact_count(db_path) == 1
    assert len(captured) == 1
    request = captured[0][0].identity
    assert dict(request.request_variant) == {"symbol": "600001.SH"}
    assert request.fanout_parameter is None
    assert request.fanout_values == ()
    assert request.page_offset == 0
    assert request.page_index == 0
    with sqlite3.connect(db_path) as conn:
        notes = json.loads(
            conn.execute("SELECT notes FROM market_ingest_runs").fetchone()[0]
        )
    assert notes["request_identity"] == request.canonical_payload()


def test_literal_values_fanout_uses_registry_values_without_sqlite_source(
    tmp_path: Path,
) -> None:
    registry = _registry()
    dataset = registry.resolve("cn.synthetic.runner")
    binding = replace(
        registry.provider_binding(dataset.dataset_id, "tushare"),
        request_shape="dimension_fanout",
        fanout=FanoutPolicy(
            strategy="literal_values",
            parameter="exchange",
            values=("SZSE", "SSE"),
            batch_size=1,
        ),
    )

    assert native_ingest._load_completed_fanout_batches(
        tmp_path / "unused.sqlite",
        registry=registry,
        binding=binding,
    ) == (
        native_ingest.FanoutBatch(parameter="exchange", values=("SSE",)),
        native_ingest.FanoutBatch(parameter="exchange", values=("SZSE",)),
    )


def test_dataset_field_fanout_reads_only_completed_sqlite_facts_stably(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base = _registry()
    source = base.resolve("cn.synthetic.runner")
    source_binding = replace(
        base.provider_binding(source.dataset_id, "tushare"),
        response_completeness=None,
    )
    source = replace(
        source,
        fields=source.fields
        + (
            DatasetField(
                name="market",
                logical_type="text",
                nullable=True,
                selectable=True,
                filterable=True,
                sortable=True,
            ),
            DatasetField(
                name="list_status",
                logical_type="text",
                nullable=True,
                selectable=True,
                filterable=True,
                sortable=True,
            ),
            DatasetField(
                name="curr_type",
                logical_type="text",
                nullable=True,
                selectable=True,
                filterable=True,
                sortable=True,
            ),
            DatasetField(
                name="list_date",
                logical_type="text",
                nullable=True,
                selectable=True,
                filterable=True,
                sortable=True,
            ),
        ),
        provider_bindings=(source_binding,),
    )
    target_binding = replace(
        source_binding,
        api_name="synthetic_target",
        read_discriminator_value="synthetic_target",
        request_shape="entity_fanout",
        fanout=FanoutPolicy(
            strategy="dataset_field",
            parameter="symbol",
            source_dataset_id=source.dataset_id,
            source_field="ts_code",
            batch_size=1,
            source_equals=(
                ("market", "主板"),
                ("list_status", "L"),
                ("curr_type", "CNY"),
            ),
            source_date_field="list_date",
            source_date_lte_days=30,
        ),
        pagination=PaginationPolicy(strategy="none"),
        response_completeness=None,
    )
    target = replace(
        source,
        dataset_id="cn.synthetic.target",
        aliases=("tushare.synthetic_target",),
        provider_bindings=(target_binding,),
    )
    registry = DatasetRegistry((source, target))
    db_path = tmp_path / "facts.sqlite"
    _database(db_path)
    now = datetime.now(timezone.utc).isoformat()
    recent_list_date = (
        datetime.now(timezone.utc).date() - timedelta(days=5)
    ).strftime("%Y%m%d")
    source_collector = _FakeCollector(
        ProviderCallOutcome(
            state="success",
            rows=(
                {
                    "ts_code": "600001.SH",
                    "trade_date": "20260716",
                    "close": 10.0,
                    "market": "主板",
                    "list_status": "L",
                    "curr_type": "CNY",
                    "list_date": "20100101",
                },
                {
                    "ts_code": "600000.SH",
                    "trade_date": "20260717",
                    "close": 11.0,
                    "market": "主板",
                    "list_status": "L",
                    "curr_type": "CNY",
                    "list_date": "20100101",
                },
                {
                    "ts_code": "300001.SZ",
                    "trade_date": "20260717",
                    "close": 12.0,
                    "market": "创业板",
                    "list_status": "L",
                    "curr_type": "CNY",
                    "list_date": "20100101",
                },
                {
                    "ts_code": "605999.SH",
                    "trade_date": "20260717",
                    "close": 13.0,
                    "market": "主板",
                    "list_status": "L",
                    "curr_type": "CNY",
                    "list_date": recent_list_date,
                },
            ),
            provider_code=0,
            error_code=None,
            error_message=None,
        )
    )
    source_result = native_ingest.collect_provider_native_dataset(
        db_path,
        registry=registry,
        collector=source_collector,
        dataset_id=source.dataset_id,
        request_window={"start_date": "20260716", "end_date": "20260717"},
        attempt_id="source-completed-attempt",
        started_at=now,
    )
    assert source_result.status == "success"

    target_collector = _FakeCollector(
        ProviderCallOutcome(
            state="success",
            rows=(
                {
                    "ts_code": "600000.SH",
                    "trade_date": "20260717",
                    "close": 11.0,
                },
            ),
            provider_code=0,
            error_code=None,
            error_message=None,
        )
    )
    target_result = native_ingest.collect_provider_native_dataset(
        db_path,
        registry=registry,
        collector=target_collector,
        dataset_id=target.dataset_id,
        request_window={"start_date": "20260717", "end_date": "20260717"},
        attempt_id="target-fanout-attempt",
        started_at=datetime.now(timezone.utc).isoformat(),
    )

    assert [call[1]["symbol"] for call in target_collector.calls] == [
        "600000.SH",
        "600001.SH",
    ]
    assert target_result.status == "success"
    assert target_result.errors == ()
    assert len(target_result.receipt_ids) == 2
    assert provider_fact_count(db_path) == 5
    with sqlite3.connect(db_path) as conn:
        target_receipts = [
            json.loads(row[0])
            for row in conn.execute(
                "SELECT notes FROM market_ingest_runs WHERE source=? ORDER BY run_id",
                (target.dataset_id,),
            )
        ]
    assert len({receipt["attempt_id"] for receipt in target_receipts}) == 2
    assert {
        tuple(receipt["request_identity"]["fanout_values"])
        for receipt in target_receipts
    } == {("600000.SH",), ("600001.SH",)}

    with sqlite3.connect(db_path) as conn:
        source_receipt_id, source_notes = conn.execute(
            "SELECT run_id, notes FROM market_ingest_runs WHERE source=?",
            (source.dataset_id,),
        ).fetchone()
        forged = json.loads(source_notes)
        forged["schema_version"] = "tradingdatas.ingest_receipt.v999"
        conn.execute(
            "UPDATE market_ingest_runs SET notes=? WHERE run_id=?",
            (
                json.dumps(
                    forged,
                    ensure_ascii=False,
                    allow_nan=False,
                    separators=(",", ":"),
                    sort_keys=True,
                ),
                source_receipt_id,
            ),
        )

    rejected_collector = _FakeCollector(
        ProviderCallOutcome(
            state="success",
            rows=(
                {
                    "ts_code": "600000.SH",
                    "trade_date": "20260717",
                    "close": 11.0,
                },
            ),
            provider_code=0,
            error_code=None,
            error_message=None,
        )
    )
    rejected = native_ingest.collect_provider_native_dataset(
        db_path,
        registry=registry,
        collector=rejected_collector,
        dataset_id=target.dataset_id,
        request_window={"start_date": "20260717", "end_date": "20260717"},
        attempt_id="target-forged-source-attempt",
        started_at=datetime.now(timezone.utc).isoformat(),
    )

    assert rejected.status == "failed"
    assert rejected.errors == ("config_error",)
    assert rejected_collector.calls == []

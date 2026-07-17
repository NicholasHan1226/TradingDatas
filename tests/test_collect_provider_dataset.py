from __future__ import annotations

import json
from pathlib import Path
import sqlite3
from types import MappingProxyType

import pytest

from collectors.tushare.tushare_common import ProviderCallOutcome
from dataset_registry import (
    DatasetDefinition,
    DatasetField,
    DatasetRegistry,
    ProviderBinding,
    ReadModelAdapter,
)
from storage.provider_dataset_rows import PROVIDER_DATASET_ROWS_DDL
from storage.schema import SCHEMA_SQL
import tools.collect_provider_dataset as runner


def _registry(*, activation_state: str = "active") -> DatasetRegistry:
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
                "end_date": "${window.end_date}",
                "exchange": "SSE",
                "start_date": "${window.start_date}",
            }
        ),
        requested_fields=("ts_code", "trade_date", "close"),
        max_rows_per_attempt=100,
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
        empty_data_policy="allowed",
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
    ) -> ProviderCallOutcome:
        self.calls.append((api_name, params, fields))
        if self.error is not None:
            raise self.error
        assert self.outcome is not None
        return self.outcome


def _run(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    *,
    outcome: ProviderCallOutcome,
    request_file: bool = False,
) -> tuple[int, dict[str, object], _FakeCollector, Path]:
    registry = _registry()
    fake = _FakeCollector(outcome)
    monkeypatch.setattr(runner, "load_runtime_dataset_registry", lambda: registry)
    monkeypatch.setattr(runner, "TushareCollector", lambda: fake)
    db_path = tmp_path / "facts.sqlite"
    _database(db_path)
    request_window = {"end_date": "20260717", "start_date": "20260701"}
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
        "parameter_keys": ["end_date", "exchange", "start_date"],
        "provider": "tushare",
        "provider_api": "synthetic_runner",
        "request_window_keys": ["end_date", "start_date"],
        "requested_field_count": 3,
        "state": "planned",
        "will_call_provider": False,
        "will_write_database": False,
    }
    assert "202607" not in json.dumps(output)
    assert not db_path.exists()


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
                "end_date": "20260717",
                "exchange": "SSE",
                "start_date": "20260701",
            },
            "ts_code,trade_date,close",
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
            3,
            "empty",
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
        runner.EXIT_EMPTY if expected_state == "empty" else runner.EXIT_FAILED
    )
    assert output["state"] == expected_state
    assert len(fake.calls) == 1


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

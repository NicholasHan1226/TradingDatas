from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from types import MappingProxyType
from typing import Any

import pytest

from collectors.tushare import collector as collector_module
from collectors.tushare import tushare_common
from collectors.tushare.collector import RequestBudgetExceeded, TushareCollector
from collectors.tushare.provider_native_ingest import (
    FanoutBatch,
    RetrySettings,
    _select_resumable_fanout_batches,
    _execute_provider_requests,
    _resolved_request,
    _stable_fanout_batches,
)
from collectors.tushare.tushare_common import (
    ProviderCallOutcome,
    SensitiveScanBudget,
)
from dataset_registry import (
    DatasetDefinition,
    DatasetField,
    FanoutPolicy,
    PaginationPolicy,
    ProviderBinding,
    ReadModelAdapter,
    ResumableFanoutPolicy,
)
from storage.receipt_projection import ValidatedReceiptHistoryEntry
from datetime import datetime, timezone
from tools import run_provider_native_schedule as scheduler
from provider_ingest_contract import provider_ingest_config_hash


def _binding(
    *,
    fanout: FanoutPolicy | None = None,
    pagination: PaginationPolicy | None = None,
    max_rows: int = 20,
    max_batch_bytes: int = 65_536,
) -> ProviderBinding:
    return ProviderBinding(
        provider="tushare",
        api_name="synthetic_generic",
        adapter_version="tushare-provider-native.v1",
        read_discriminator_value="synthetic_generic",
        entitlement_state="active",
        activation_state="active",
        target_tables=("provider_dataset_rows",),
        request_shape="dimension_fanout"
        if fanout and fanout.strategy == "dataset_field"
        else "snapshot_or_date_range",
        request_template=MappingProxyType(
            {
                "exchange": "SSE",
                "limit": "100",
                "trade_date": "${window.trade_date}",
            }
        ),
        request_variants=(
            MappingProxyType({"exchange": "SSE", "limit": "100"}),
            MappingProxyType({"exchange": "SZSE", "limit": 100}),
        ),
        fanout=fanout or FanoutPolicy(strategy="none"),
        pagination=pagination or PaginationPolicy(strategy="none"),
        requested_fields=(),
        max_rows_per_attempt=max_rows,
        max_payload_bytes_per_row=4_096,
        max_batch_bytes=max_batch_bytes,
        max_nesting_depth=8,
    )


def _synthetic_dataset(binding: ProviderBinding) -> DatasetDefinition:
    return DatasetDefinition(
        dataset_id="cn.synthetic",
        aliases=(), domain="equity", market="ashare", entity_type="equity",
        data_classification="reference", schema_version="1.0.0",
        fields=(DatasetField("ts_code", "text", False, True, True, True),),
        primary_key=("ts_code",), default_projection=("ts_code",),
        as_of_field=None, as_of_format=None, range_field=None, partition_field=None,
        cadence_class="daily_reference", timezone="Asia/Shanghai",
        freshness_sla_seconds=3600, max_page_size=100, max_lookback_days=30,
        point_in_time="snapshot", backfill_policy="none", empty_data_policy="allowed",
        required_scope="ashare", quota_class="standard", provider_bindings=(binding,),
        read_model_adapter=ReadModelAdapter(
            adapter_version="synthetic.v1", primary_table="provider_dataset_rows",
            fixed_field_filters=(),
        ),
    )


class _SequenceCollector:
    def __init__(self, outcomes: list[ProviderCallOutcome]) -> None:
        self._outcomes = iter(outcomes)
        self.calls: list[tuple[str, dict[str, Any], str | None]] = []

    def collect_outcome(
        self,
        api_name: str,
        params: dict[str, Any],
        fields: str | None = None,
        *,
        scan_budget: SensitiveScanBudget | None = None,
    ) -> ProviderCallOutcome:
        assert scan_budget is not None
        self.calls.append((api_name, dict(params), fields))
        return next(self._outcomes)


def _success(*rows: Mapping[str, Any]) -> ProviderCallOutcome:
    return ProviderCallOutcome(
        state="success",
        rows=tuple(rows),
        provider_code=0,
        error_code=None,
        error_message=None,
    )


def _failed(code: str) -> ProviderCallOutcome:
    return ProviderCallOutcome(
        state="failed",
        rows=(),
        provider_code=None,
        error_code=code,
        error_message="provider request failed",
    )


def _empty() -> ProviderCallOutcome:
    return ProviderCallOutcome(
        state="empty",
        rows=(),
        provider_code=0,
        error_code=None,
        error_message=None,
    )


def _execute(
    collector: Any,
    binding: ProviderBinding,
    *,
    retry: RetrySettings = RetrySettings(),
    retry_empty: bool = False,
):
    _, params = _resolved_request(
        binding,
        {"trade_date": "20260720"},
        request_variant={"exchange": "SZSE", "limit": 100},
    )
    return _execute_provider_requests(
        collector=collector,
        binding=binding,
        base_params=params,
        request_variant={"exchange": "SZSE", "limit": 100},
        fanout_batches=(FanoutBatch(parameter=None, values=()),),
        requested_fields=None,
        scan_budget=SensitiveScanBudget(max_depth=16, max_nodes=10_000),
        retry=retry,
        retry_empty=retry_empty,
        sleep=lambda _seconds: None,
    )


def test_typed_variant_merge_preserves_scalar_type_and_window_value() -> None:
    binding = _binding()

    window, params = _resolved_request(
        binding,
        {"trade_date": "20260720"},
        request_variant={"exchange": "SZSE", "limit": 100},
    )

    assert window == {"trade_date": "20260720"}
    assert params == {
        "exchange": "SZSE",
        "limit": 100,
        "trade_date": "20260720",
    }
    assert type(params["limit"]) is int
    with pytest.raises(ValueError, match="registered request variant"):
        _resolved_request(
            binding,
            {"trade_date": "20260720"},
            request_variant={"exchange": "SZSE", "limit": "100"},
        )


def test_execution_treats_absent_fanout_as_one_response_budget() -> None:
    binding = replace(_binding(), fanout=None)
    execution = _execute(
        _SequenceCollector(
            [_success({"ts_code": "600000.SH", "trade_date": "20260720"})]
        ),
        binding,
    )

    assert execution.outcome.state == "success"
    assert len(execution.outcome.rows) == 1


def test_fanout_values_are_typed_stably_deduplicated_and_batched() -> None:
    batches = _stable_fanout_batches(
        ["SZSE", "BSE", "SSE", "SZSE", "BSE"],
        parameter="exchange",
        batch_size=2,
    )

    assert batches == (
        FanoutBatch(parameter="exchange", values=("BSE", "SSE")),
        FanoutBatch(parameter="exchange", values=("SZSE",)),
    )


def test_fanout_stable_hash_order_is_bounded_without_code_order_bias() -> None:
    values = ("600000.SH", "000001.SZ", "601899.SH", "000858.SZ", "600519.SH")

    first = _stable_fanout_batches(
        values,
        parameter="ts_code",
        batch_size=2,
        max_values=4,
        source_order="stable_hash",
    )
    second = _stable_fanout_batches(
        tuple(reversed(values)),
        parameter="ts_code",
        batch_size=2,
        max_values=4,
        source_order="stable_hash",
    )

    assert first == second
    assert sum(len(batch.values) for batch in first) == 4
    assert first != _stable_fanout_batches(
        values,
        parameter="ts_code",
        batch_size=2,
        max_values=4,
    )


def test_resumable_fanout_batch_identity_is_deterministic_and_legacy_is_unchanged() -> None:
    values = ("600000.SH", "000001.SZ", "601899.SH")
    first = _stable_fanout_batches(
        values, parameter="ts_code", batch_size=2, resumable=True
    )
    second = _stable_fanout_batches(
        tuple(reversed(values)), parameter="ts_code", batch_size=2, resumable=True
    )
    assert first == second
    assert [(item.batch_index, item.batch_count) for item in first] == [(0, 2), (1, 2)]
    assert all(item.cursor_contract_version == 2 for item in first)
    assert _stable_fanout_batches(values, parameter="ts_code", batch_size=2) == (
        FanoutBatch(parameter="ts_code", values=("000001.SZ", "600000.SH")),
        FanoutBatch(parameter="ts_code", values=("601899.SH",)),
    )


def _history_for_batch(batch: FanoutBatch, *, status: str, dataset_id: str = "cn.synthetic", config_hash: str = "c" * 64):
    return ValidatedReceiptHistoryEntry(
        dataset_id=dataset_id,
        provider="tushare",
        receipt_id=f"receipt-{batch.batch_index}-{status}",
        status=status,
        cohort_status=status,
        started_at=datetime(2026, 8, 13, tzinfo=timezone.utc),
        finished_at=datetime(2026, 8, 13, 0, 1, tzinfo=timezone.utc),
        request_window={"trade_date": "20260813"},
        request_variant={"exchange": "SSE", "limit": 100},
        execution_id=f"execution-{batch.batch_index}",
        config_hash=config_hash,
        cursor_contract_version=2,
        frozen_universe_sha256=batch.frozen_universe_sha256,
        batch_index=batch.batch_index,
        batch_count=batch.batch_count,
        batch_values_sha256=batch.batch_values_sha256,
        physical_call_index=batch.batch_index,
        retry_index=0,
    )


def test_resumable_selection_skips_completed_and_retries_only_failed_batch() -> None:
    batches = _stable_fanout_batches(
        ("000001.SZ", "000002.SZ", "600000.SH"),
        parameter="ts_code",
        batch_size=1,
        resumable=True,
    )
    policy = ResumableFanoutPolicy(cursor_contract_version=2, max_batches_per_run=1)
    binding = replace(_binding(fanout=FanoutPolicy(
        strategy="literal_values", parameter="ts_code", values=("000001.SZ", "000002.SZ", "600000.SH"), batch_size=1,
    )), resumable_fanout=policy, request_variants=(MappingProxyType({"exchange": "SSE", "limit": 100}),))
    dataset = _synthetic_dataset(binding)
    config_hash = provider_ingest_config_hash(dataset, binding)
    histories = (
        _history_for_batch(batches[0], status="success", config_hash=config_hash),
        _history_for_batch(batches[1], status="failed", config_hash=config_hash),
    )
    selected = _select_resumable_fanout_batches(
        batches, dataset=dataset, binding=binding,
        request_window={"trade_date": "20260813"}, histories=histories,
    )
    assert selected == (batches[1],)
    assert _select_resumable_fanout_batches(
        batches, dataset=dataset, binding=binding,
        request_window={"trade_date": "20260814"}, histories=histories,
    ) == (batches[0],)
    complete_histories = tuple(
        _history_for_batch(batch, status="success", config_hash=config_hash)
        for batch in batches
    )
    assert _select_resumable_fanout_batches(
        batches, dataset=dataset, binding=binding,
        request_window={"trade_date": "20260813"}, histories=complete_histories,
    ) == ()
    assert _select_resumable_fanout_batches(
        batches, dataset=dataset, binding=binding,
        request_window={"trade_date": "20260813"}, histories=histories,
    ) == _select_resumable_fanout_batches(
        batches, dataset=dataset, binding=binding,
        request_window={"trade_date": "20260813"}, histories=histories,
    )


@pytest.mark.parametrize(
    "mutator",
    [
        lambda item: replace(item, dataset_id="cn.other"),
        lambda item: replace(item, provider="other-provider"),
        lambda item: replace(item, request_window={"trade_date": "20260814"}),
        lambda item: replace(item, config_hash="d" * 64),
        lambda item: replace(item, frozen_universe_sha256="e" * 64),
        lambda item: replace(item, cursor_contract_version=None),
    ],
)
def test_resumable_selection_ignores_mismatched_or_legacy_receipt(mutator) -> None:
    batches = _stable_fanout_batches(
        ("000001.SZ", "000002.SZ"), parameter="ts_code", batch_size=1, resumable=True
    )
    binding = replace(
        _binding(
            fanout=FanoutPolicy(
                strategy="literal_values", parameter="ts_code",
                values=("000001.SZ", "000002.SZ"), batch_size=1,
            )
        ),
        resumable_fanout=ResumableFanoutPolicy(),
        request_variants=(MappingProxyType({"exchange": "SSE", "limit": 100}),),
    )
    dataset = _synthetic_dataset(binding)
    config_hash = provider_ingest_config_hash(dataset, binding)
    receipt = _history_for_batch(batches[0], status="success", config_hash=config_hash)
    assert _select_resumable_fanout_batches(
        batches,
        dataset=dataset,
        binding=binding,
        request_window={"trade_date": "20260813"},
        histories=(mutator(receipt),),
    ) == (batches[0],)


def test_absent_resumable_policy_keeps_all_legacy_batches() -> None:
    batches = _stable_fanout_batches(
        ("000001.SZ", "000002.SZ"), parameter="ts_code", batch_size=1
    )
    binding = _binding(
        fanout=FanoutPolicy(
            strategy="literal_values", parameter="ts_code",
            values=("000001.SZ", "000002.SZ"), batch_size=1,
        )
    )
    assert _select_resumable_fanout_batches(
        batches, dataset=_synthetic_dataset(binding), binding=binding,
        request_window={"trade_date": "20260813"}, histories=(),
    ) == batches


def test_executor_passes_complete_cursor_identity_to_each_physical_call() -> None:
    batch = FanoutBatch(
        parameter="ts_code",
        values=("000001.SZ",),
        cursor_contract_version=2,
        frozen_universe_sha256="a" * 64,
        batch_index=0,
        batch_count=1,
        batch_values_sha256="b" * 64,
    )
    # Exercise the physical-call path directly with the v2 batch identity.
    _, params = _resolved_request(
        _binding(), {"trade_date": "20260720"},
        request_variant={"exchange": "SZSE", "limit": 100},
    )
    physical = _execute_provider_requests(
        collector=_SequenceCollector([_success({"ts_code": "000001.SZ"})]),
        binding=_binding(),
        base_params=params,
        request_variant={"exchange": "SZSE", "limit": 100},
        fanout_batches=(batch,),
        requested_fields=None,
        scan_budget=SensitiveScanBudget(max_depth=16, max_nodes=10_000),
        retry=RetrySettings(),
        retry_empty=False,
        sleep=lambda _seconds: None,
    )
    assert physical.calls[0].identity.cursor_contract_version == 2
    assert physical.calls[0].identity.frozen_universe_sha256 == "a" * 64


def test_executor_sends_one_fanout_batch_as_one_comma_parameter() -> None:
    codes = tuple(f"0000{index:02d}.SZ" for index in range(1, 11))
    binding = _binding(
        fanout=FanoutPolicy(
            strategy="dataset_field",
            parameter="ts_code",
            source_dataset_id="cn.equity.security_master",
            source_field="ts_code",
            batch_size=10,
        )
    )
    batches = _stable_fanout_batches(
        codes,
        parameter="ts_code",
        batch_size=binding.fanout.batch_size or 0,
    )
    collector = _SequenceCollector([_success({"ts_code": codes[0]})])
    _, params = _resolved_request(
        binding,
        {"trade_date": "20260720"},
        request_variant={"exchange": "SZSE", "limit": 100},
    )

    execution = _execute_provider_requests(
        collector=collector,
        binding=binding,
        base_params=params,
        request_variant={"exchange": "SZSE", "limit": 100},
        fanout_batches=batches,
        requested_fields=None,
        scan_budget=SensitiveScanBudget(max_depth=16, max_nodes=10_000),
        retry=RetrySettings(),
        retry_empty=False,
        sleep=lambda _seconds: None,
    )

    assert len(collector.calls) == 1
    assert collector.calls[0][1]["ts_code"] == ",".join(codes)
    assert execution.calls[0].identity.fanout_values == codes


def test_fanout_row_budget_is_applied_per_provider_call() -> None:
    binding = _binding(
        fanout=FanoutPolicy(
            strategy="dataset_field",
            parameter="ts_code",
            source_dataset_id="cn.equity.security_master",
            source_field="ts_code",
            batch_size=1,
        ),
        max_rows=2,
    )
    batches = _stable_fanout_batches(
        ("000001.SZ", "000002.SZ"),
        parameter="ts_code",
        batch_size=1,
    )
    collector = _SequenceCollector(
        [
            _success({"ts_code": "000001.SZ"}, {"ts_code": "000001.SZ"}),
            _success({"ts_code": "000002.SZ"}, {"ts_code": "000002.SZ"}),
        ]
    )
    _, params = _resolved_request(
        binding,
        {"trade_date": "20260720"},
        request_variant={"exchange": "SZSE", "limit": 100},
    )

    execution = _execute_provider_requests(
        collector=collector,
        binding=binding,
        base_params=params,
        request_variant={"exchange": "SZSE", "limit": 100},
        fanout_batches=batches,
        requested_fields=None,
        scan_budget=SensitiveScanBudget(max_depth=16, max_nodes=10_000),
        retry=RetrySettings(),
        retry_empty=False,
        sleep=lambda _seconds: None,
    )

    assert execution.outcome.state == "success"
    assert len(execution.outcome.rows) == 4
    assert len(execution.calls) == 2


def test_offset_pagination_stops_on_short_page_and_preserves_rows() -> None:
    binding = _binding(
        pagination=PaginationPolicy(
            strategy="offset",
            limit_parameter="page_limit",
            offset_parameter="page_offset",
            page_size=2,
            max_pages=3,
        )
    )
    collector = _SequenceCollector(
        [
            _success({"id": 1}, {"id": 2}),
            _success({"id": 3}),
        ]
    )

    execution = _execute(collector, binding)

    assert execution.outcome.mutable_rows() == [{"id": 1}, {"id": 2}, {"id": 3}]
    assert [call[1]["page_offset"] for call in collector.calls] == [0, 2]
    assert [call[1]["page_limit"] for call in collector.calls] == [2, 2]
    assert [call.identity.page_offset for call in execution.calls] == [0, 2]
    assert [call.identity.page_index for call in execution.calls] == [0, 1]


def test_full_final_page_fails_closed_at_max_pages() -> None:
    binding = _binding(
        pagination=PaginationPolicy(
            strategy="offset",
            limit_parameter="page_limit",
            offset_parameter="page_offset",
            page_size=2,
            max_pages=2,
        )
    )
    collector = _SequenceCollector(
        [
            _success({"id": 1}, {"id": 2}),
            _success({"id": 3}, {"id": 4}),
        ]
    )

    execution = _execute(collector, binding)

    assert execution.outcome.state == "failed"
    assert execution.outcome.error_code == "resource_budget"
    assert len(collector.calls) == 2


def test_row_and_byte_budgets_fail_closed_before_storage() -> None:
    row_binding = _binding(max_rows=1)
    row_execution = _execute(
        _SequenceCollector([_success({"id": 1}, {"id": 2})]),
        row_binding,
    )
    assert row_execution.outcome.state == "failed"
    assert row_execution.outcome.error_code == "resource_budget"

    byte_binding = _binding(max_batch_bytes=8)
    byte_execution = _execute(
        _SequenceCollector([_success({"value": "payload"})]),
        byte_binding,
    )
    assert byte_execution.outcome.state == "failed"
    assert byte_execution.outcome.error_code == "resource_budget"


def test_retries_only_rate_limited_provider_outcomes() -> None:
    """A transport failure may already have written bytes, so never replay it."""

    retryable = "rate_limited"
    collector = _SequenceCollector([_failed(retryable), _success({"id": 1})])
    execution = _execute(
        collector,
        _binding(),
        retry=RetrySettings(max_attempts=2),
    )
    assert execution.outcome.state == "success"
    assert len(collector.calls) == 2

    permission = _SequenceCollector([_failed("permission_denied"), _success({"id": 1})])
    execution = _execute(
        permission,
        _binding(),
        retry=RetrySettings(max_attempts=2),
    )
    assert execution.outcome.state == "failed"
    assert len(permission.calls) == 1

    validation = _SequenceCollector([_failed("provider_error"), _success({"id": 1})])
    execution = _execute(
        validation,
        _binding(),
        retry=RetrySettings(max_attempts=2),
    )
    assert execution.outcome.state == "failed"
    assert len(validation.calls) == 1

    transport = _SequenceCollector([_failed("transport_error"), _success({"id": 1})])
    execution = _execute(
        transport,
        _binding(),
        retry=RetrySettings(max_attempts=2),
    )
    assert execution.outcome.state == "failed"
    assert len(transport.calls) == 1


def test_allowed_empty_provider_outcome_terminates_without_retry() -> None:
    collector = _SequenceCollector([_empty()])
    execution = _execute(
        collector,
        _binding(),
        retry=RetrySettings(max_attempts=3),
        retry_empty=False,
    )

    assert execution.outcome.state == "empty"
    assert len(collector.calls) == 1
    assert [call.retry_index for call in execution.calls] == [0]


def test_forbidden_empty_provider_outcome_retains_bounded_retry() -> None:
    collector = _SequenceCollector([_empty(), _empty(), _empty()])
    execution = _execute(
        collector,
        _binding(),
        retry=RetrySettings(max_attempts=3),
        retry_empty=True,
    )

    assert execution.outcome.state == "empty"
    assert len(collector.calls) == 3
    assert [call.retry_index for call in execution.calls] == [0, 1, 2]


def test_seven_allowed_empty_event_plans_use_seven_shared_budget_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider_delegations: list[str] = []

    def empty_provider(api_name: str, *_args: object) -> ProviderCallOutcome:
        provider_delegations.append(api_name)
        return _empty()

    monkeypatch.setattr(collector_module, "_TUSHARE_CALL", empty_provider)
    schedule = scheduler.load_schedule()
    ledger = scheduler.RuntimeRateBudgetLedger(schedule)
    assert schedule.rate_budgets["event"].account_requests_per_run == 24

    for index in range(7):
        api_name = f"synthetic_event_{index}"
        plan = scheduler.ScheduledRun(
            dataset_id=f"cn.synthetic.event_{index}",
            provider="tushare",
            provider_api=api_name,
            cadence_class="event",
            request_window={"trade_date": "20260720"},
            rate_budget_class="event",
        )
        collector = TushareCollector(
            request_gate=lambda requested_api, plan=plan: ledger.consume(
                plan, requested_api
            )
        )

        execution = _execute(
            collector,
            replace(_binding(), api_name=api_name),
            retry=RetrySettings(max_attempts=3),
            retry_empty=False,
        )

        assert execution.outcome.state == "empty"
        assert len(execution.calls) == 1

    assert provider_delegations == [f"synthetic_event_{index}" for index in range(7)]


def test_pre_provider_resource_budget_rejection_remains_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider_delegations = 0

    def provider(*_args: object) -> ProviderCallOutcome:
        nonlocal provider_delegations
        provider_delegations += 1
        return _empty()

    def reject(_api_name: str) -> None:
        raise RequestBudgetExceeded("provider request budget exhausted")

    monkeypatch.setattr(collector_module, "_TUSHARE_CALL", provider)
    execution = _execute(
        TushareCollector(request_gate=reject),
        _binding(),
        retry=RetrySettings(max_attempts=3),
        retry_empty=False,
    )

    assert execution.outcome.state == "failed"
    assert execution.outcome.error_code == "resource_budget"
    assert execution.outcome.error_message == "local rate budget exceeded"
    assert len(execution.calls) == 1
    assert provider_delegations == 0


def test_public_rate_window_outcome_is_retried_by_ingest(monkeypatch) -> None:
    monkeypatch.setattr(
        tushare_common,
        "get_api_url",
        lambda: "https://api.quicksync.cn",
    )

    def rate_limited(*_args: object, **_kwargs: object) -> None:
        raise tushare_common._QuickSyncRateLimitError(  # noqa: SLF001
            "QuickSync rate-limit wait timed out"
        )

    monkeypatch.setattr(tushare_common, "_provider_urlopen", rate_limited)
    public_outcome = tushare_common.tushare_rows_outcome("daily", "stub-token")
    collector = _SequenceCollector([public_outcome, _success({"id": 1})])

    execution = _execute(
        collector,
        _binding(),
        retry=RetrySettings(max_attempts=2),
    )

    assert public_outcome.error_code == "rate_limited"
    assert execution.outcome.state == "success"
    assert len(collector.calls) == 2


def test_retry_attempts_keep_one_singular_identity_and_distinct_call_ordinals() -> None:
    collector = _SequenceCollector([_failed("rate_limited"), _success({"id": 1})])

    execution = _execute(
        collector,
        _binding(),
        retry=RetrySettings(max_attempts=2),
    )

    assert [call.call_index for call in execution.calls] == [0, 1]
    assert [call.retry_index for call in execution.calls] == [0, 1]
    assert execution.calls[0].identity is not execution.calls[1].identity
    assert (
        execution.calls[0].identity.canonical_payload()
        == execution.calls[1].identity.canonical_payload()
    )

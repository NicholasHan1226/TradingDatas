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
    _execute_provider_requests,
    _resolved_request,
    _stable_fanout_batches,
)
from collectors.tushare.tushare_common import (
    ProviderCallOutcome,
    SensitiveScanBudget,
)
from dataset_registry import FanoutPolicy, PaginationPolicy, ProviderBinding
from tools import run_provider_native_schedule as scheduler


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
    assert schedule.rate_budgets["event"].account_requests_per_run == 12

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

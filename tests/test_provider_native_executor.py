from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Any

import pytest

from collectors.tushare import tushare_common
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


def _execute(
    collector: _SequenceCollector,
    binding: ProviderBinding,
    *,
    retry: RetrySettings = RetrySettings(),
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

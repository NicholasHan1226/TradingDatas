from __future__ import annotations

from dataclasses import replace
from math import nan

import pytest

from dataset_registry import load_dataset_registry


def _contract():
    import query_contract

    return query_contract


def _payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "dataset_id": "cn.equity.daily",
        "schema_major": 1,
        "fields": ["symbol", "trade_date", "close"],
        "filters": {
            "symbol": "600519.SH",
            "trade_date": {"between": ["20260701", "20260716"]},
        },
        "as_of": None,
        "order": ["trade_date:desc", "symbol:asc"],
        "limit": 100,
        "cursor": None,
    }
    payload.update(overrides)
    return payload


@pytest.mark.parametrize(
    "payload",
    [
        {"dataset_id": "cn.equity.daily", "schema_major": True},
        {"dataset_id": "cn.equity.daily", "schema_major": 1, "limit": "100"},
        {
            "dataset_id": "cn.equity.daily",
            "schema_major": 1,
            "fields": ["close", "close"],
        },
        {"dataset_id": "cn.equity.daily", "schema_major": 1, "order": []},
        {"dataset_id": "cn.equity.daily", "schema_major": 1, "sql": "select 1"},
        {
            "dataset_id": "cn.equity.daily",
            "schema_major": 1,
            "latest_partition": True,
        },
        {
            "dataset_id": "cn.equity.daily",
            "schema_major": 1,
            "any_of_eq_filters": [["symbol", "600519.SH"]],
        },
        {"dataset_id": "cn.equity.daily", "schema_major": 1, 1: "invalid-key"},
    ],
)
def test_query_request_rejects_noncanonical_payload(
    payload: dict[str, object],
) -> None:
    contract = _contract()

    with pytest.raises(contract.QueryValidationError):
        contract.parse_query_request(payload)


def test_query_request_accepts_scalar_and_operator_filters() -> None:
    contract = _contract()

    request = contract.parse_query_request(_payload(as_of="2026-07-16T00:00:00Z"))

    assert request == contract.QueryRequest(
        dataset_id="cn.equity.daily",
        schema_major=1,
        fields=("symbol", "trade_date", "close"),
        filters={
            "symbol": {"eq": "600519.SH"},
            "trade_date": {"between": ("20260701", "20260716")},
        },
        as_of="2026-07-16T00:00:00+00:00",
        order=("trade_date:desc", "symbol:asc"),
        limit=100,
        cursor=None,
    )


def test_query_request_preserves_registry_owned_default_order() -> None:
    contract = _contract()

    request = contract.parse_query_request(
        {"dataset_id": "cn.equity.daily", "schema_major": 1}
    )

    assert request.fields == ()
    assert dict(request.filters) == {}
    assert request.order is None
    assert request.limit == 500
    assert request.cursor is None


@pytest.mark.parametrize(
    "override",
    [
        {"fields": [f"field_{index}" for index in range(101)]},
        {"filters": {f"field_{index}": index for index in range(17)}},
        {"filters": {"symbol": {"in": list(range(101))}}},
        {"order": [f"field_{index}:asc" for index in range(9)]},
        {"limit": True},
        {"limit": 1.0},
        {"fields": ("symbol",)},
        {"filters": []},
        {"filters": {"symbol": "600519.SH", 1: "invalid-key"}},
        {"filters": {"symbol": {"eq": "x", "in": ["x"]}}},
        {"filters": {"symbol": {"contains": "x"}}},
        {"filters": {"symbol": {"in": []}}},
        {"filters": {"trade_date": {"between": ["20260701"]}}},
        {"filters": {"close": nan}},
        {"order": ["trade_date:desc", "trade_date:desc"]},
        {"order": ["trade_date desc"]},
        {"as_of": "2026-07-16T00:00:00"},
    ],
)
def test_query_request_enforces_native_types_and_contract_budgets(
    override: dict[str, object],
) -> None:
    contract = _contract()

    with pytest.raises(contract.QueryValidationError):
        contract.parse_query_request(_payload(**override))


def test_query_request_distinguishes_resource_budget_failures() -> None:
    contract = _contract()

    with pytest.raises(contract.QueryBudgetError):
        contract.parse_query_request(
            _payload(fields=[f"field_{index}" for index in range(101)])
        )


def test_query_request_hash_is_key_order_independent() -> None:
    contract = _contract()
    first = contract.parse_query_request(
        _payload(
            filters={
                "symbol": {"eq": "600519.SH"},
                "trade_date": {"between": ["20260701", "20260716"]},
            }
        )
    )
    second = contract.parse_query_request(
        _payload(
            filters={
                "trade_date": {"between": ["20260701", "20260716"]},
                "symbol": {"eq": "600519.SH"},
            },
            cursor="another-page-token",
        )
    )

    first_hash = contract.normalized_query_hash(first)
    assert contract.normalized_query_hash(second) == first_hash
    assert contract.normalized_query_hash(replace(first, limit=99)) != first_hash
    assert (
        contract.normalized_query_hash(
            first,
            options=contract.QueryExecutionOptions(latest_partition=True),
            resolved_partition="20260716",
        )
        != first_hash
    )
    assert (
        contract.normalized_query_hash(
            first,
            options=contract.QueryExecutionOptions(
                any_of_eq_filters=(("parent_symbol", "000300.SH"),)
            ),
        )
        != first_hash
    )


def test_access_policy_hash_binds_tenant_scopes_and_exact_dataset_grants() -> None:
    contract = _contract()

    first = contract.QueryAccessContext.from_grants(
        tenant_id="tenant-a",
        scopes=("market_data", "external_read", "market_data"),
        allowed_dataset_ids=("cn.equity.daily", "cn.market.trade_calendar"),
    )
    reordered = contract.QueryAccessContext.from_grants(
        tenant_id="tenant-a",
        scopes=("external_read", "market_data"),
        allowed_dataset_ids=("cn.market.trade_calendar", "cn.equity.daily"),
    )

    assert first == reordered
    assert first.scopes == ("external_read", "market_data")
    assert first.allowed_dataset_ids == (
        "cn.equity.daily",
        "cn.market.trade_calendar",
    )
    assert len(first.policy_id) == 64
    assert (
        contract.access_policy_hash(
            "tenant-b",
            first.scopes,
            first.allowed_dataset_ids,
        )
        != first.policy_id
    )
    assert (
        contract.access_policy_hash(
            first.tenant_id,
            (*first.scopes, "events"),
            first.allowed_dataset_ids,
        )
        != first.policy_id
    )
    assert (
        contract.access_policy_hash(
            first.tenant_id,
            first.scopes,
            (*first.allowed_dataset_ids, "cn.equity.weekly"),
        )
        != first.policy_id
    )


def test_query_as_of_normalizes_dataset_timezone_and_stricter_upper_bound() -> None:
    contract = _contract()
    daily = load_dataset_registry().resolve("cn.equity.daily")
    request = contract.parse_query_request(
        _payload(
            as_of="2026-07-15T16:30:00Z",
            filters={"trade_date": {"lte": "20260715"}},
        )
    )

    resolved = contract.resolve_query_as_of(request, daily)

    assert resolved.field == "trade_date"
    assert resolved.requested_as_of == "2026-07-15T16:30:00+00:00"
    assert resolved.resolved_as_of == "2026-07-15T00:00:00+08:00"
    assert resolved.encoded_cutoff == "20260715"


def test_query_as_of_rejects_dataset_without_declared_capability() -> None:
    contract = _contract()
    asset = load_dataset_registry().resolve("cn.equity.security_master")
    request = contract.parse_query_request(
        _payload(
            dataset_id=asset.dataset_id,
            as_of="2026-07-16T00:00:00+08:00",
        )
    )

    with pytest.raises(contract.QueryValidationError, match="as_of"):
        contract.resolve_query_as_of(request, asset)


@pytest.mark.parametrize(
    "options",
    [
        {"latest_partition": 1},
        {"any_of_eq_filters": (("a", 1), ("b", 2), ("c", 3), ("d", 4), ("e", 5))},
        {"any_of_eq_filters": (("not a field", "x"),)},
        {"any_of_eq_filters": (("symbol", ["not-scalar"]),)},
    ],
)
def test_internal_query_options_remain_bounded(options: dict[str, object]) -> None:
    contract = _contract()

    with pytest.raises(contract.QueryValidationError):
        contract.QueryExecutionOptions(**options)

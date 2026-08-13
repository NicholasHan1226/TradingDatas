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


def test_query_request_receipt_proof_opt_in_is_explicit_and_typed() -> None:
    contract = _contract()
    assert contract.parse_query_request(_payload()).include_receipt_proofs is False
    assert contract.parse_query_request(
        _payload(include_receipt_proofs=True)
    ).include_receipt_proofs is True
    with pytest.raises(contract.QueryValidationError):
        contract.parse_query_request(_payload(include_receipt_proofs=1))


def test_query_request_accepts_numeric_leading_provider_fields() -> None:
    contract = _contract()

    request = contract.parse_query_request(
        _payload(
            fields=["1m"],
            filters={"1m": {"gte": 1.0}},
            order=["1m:desc"],
        )
    )

    assert request.fields == ("1m",)
    assert dict(request.filters["1m"]) == {"gte": 1.0}
    assert request.order == ("1m:desc",)


@pytest.mark.parametrize(
    "override",
    (
        {"fields": ["a" * 65]},
        {"filters": {"a" * 65: {"eq": 1}}},
        {"order": [f"{'a' * 65}:asc"]},
    ),
)
def test_query_request_rejects_provider_fields_longer_than_64_characters(
    override: dict[str, object],
) -> None:
    contract = _contract()
    with pytest.raises(contract.QueryValidationError):
        contract.parse_query_request(_payload(**override))


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


def test_access_context_direct_construction_normalizes_and_recomputes_policy() -> None:
    contract = _contract()

    context = contract.QueryAccessContext(
        tenant_id="tenant-a",
        scopes=("market_data", "external_read", "market_data"),
        allowed_dataset_ids=("cn.market.trade_calendar", "cn.equity.daily"),
        policy_id="stale-or-forged",
    )

    assert context.scopes == ("external_read", "market_data")
    assert context.allowed_dataset_ids == (
        "cn.equity.daily",
        "cn.market.trade_calendar",
    )
    assert context.policy_id == contract.access_policy_hash(
        context.tenant_id,
        context.scopes,
        context.allowed_dataset_ids,
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"tenant_id": "tenant-b"},
        {"scopes": ("events", "external_read")},
        {"allowed_dataset_ids": ("cn.equity.weekly",)},
    ],
)
def test_access_context_replace_cannot_retain_stale_policy(
    changes: dict[str, object],
) -> None:
    contract = _contract()
    original = contract.QueryAccessContext.from_grants(
        tenant_id="tenant-a",
        scopes=("external_read",),
        allowed_dataset_ids=("cn.equity.daily",),
    )

    changed = replace(original, **changes)

    assert changed.policy_id != original.policy_id
    assert changed.policy_id == contract.access_policy_hash(
        changed.tenant_id,
        changed.scopes,
        changed.allowed_dataset_ids,
    )


def test_query_request_direct_construction_deeply_freezes_filters() -> None:
    contract = _contract()
    source = {"symbol": {"in": ["000001.SZ", "600519.SH"]}}
    request = contract.QueryRequest(
        dataset_id="cn.equity.daily",
        schema_major=1,
        fields=("symbol",),
        filters=source,
        as_of=None,
        order=None,
        limit=10,
        cursor=None,
    )
    initial_hash = contract.normalized_query_hash(request)

    source["symbol"]["in"][0] = "300750.SZ"

    assert request.filters["symbol"] == {"in": ("000001.SZ", "600519.SH")}
    assert contract.normalized_query_hash(request) == initial_hash

    replacement_source = {"symbol": {"eq": "600519.SH"}}
    replaced = replace(request, filters=replacement_source)
    replacement_hash = contract.normalized_query_hash(replaced)
    replacement_source["symbol"]["eq"] = "000001.SZ"

    assert replaced.filters["symbol"] == {"eq": "600519.SH"}
    assert contract.normalized_query_hash(replaced) == replacement_hash


@pytest.mark.parametrize("construction", ["public", "direct"])
@pytest.mark.parametrize(
    "as_of",
    [
        "2026-07-16T00:00:00+08:60",
        "2026-07-16T00:00:00+08:99",
        "2026-07-16T00:60:00Z",
        "2026-07-16T00:00:60Z",
        "2026-07-16T24:00:00Z",
        "2026-07-16T00:00:00+24:00",
        "2026-02-30T00:00:00Z",
        "2026-07-16T00:00:00.1234567Z",
        "2026-07-16T00:00:00-00:00",
        "2026-07-16t00:00:00Z",
        "2026-07-16T00:00:00z",
        "٢٠٢٦-07-16T00:00:00Z",
        "2026-٠٧-١٦T00:00:00Z",
    ],
)
def test_query_request_rejects_noncanonical_rfc3339_subset(
    construction: str,
    as_of: str,
) -> None:
    contract = _contract()

    with pytest.raises(contract.QueryValidationError, match="RFC3339"):
        if construction == "public":
            contract.parse_query_request(_payload(as_of=as_of))
        else:
            contract.QueryRequest(
                dataset_id="cn.equity.daily",
                schema_major=1,
                fields=(),
                filters={},
                as_of=as_of,
                order=None,
                limit=1,
                cursor=None,
            )


@pytest.mark.parametrize(
    ("as_of", "canonical"),
    [
        (
            "2024-02-29T23:59:59Z",
            "2024-02-29T23:59:59+00:00",
        ),
        (
            "2026-07-16T23:59:59+23:59",
            "2026-07-16T23:59:59+23:59",
        ),
        (
            "2026-07-16T23:59:59-23:59",
            "2026-07-16T23:59:59-23:59",
        ),
        (
            "2026-07-16T00:00:00+08:59",
            "2026-07-16T00:00:00+08:59",
        ),
        (
            "2026-07-16T00:00:00+00:00",
            "2026-07-16T00:00:00+00:00",
        ),
        (
            "2026-07-16T00:00:00.1Z",
            "2026-07-16T00:00:00.100000+00:00",
        ),
        (
            "2026-07-16T00:00:00.123456Z",
            "2026-07-16T00:00:00.123456+00:00",
        ),
    ],
)
def test_query_request_accepts_strict_rfc3339_boundaries(
    as_of: str,
    canonical: str,
) -> None:
    contract = _contract()

    request = contract.parse_query_request(_payload(as_of=as_of))

    assert request.as_of == canonical


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


@pytest.mark.parametrize(
    ("values", "expected_cutoff"),
    [
        (["20260714", "20260715"], "20260715"),
        (["20260717", "20260718"], "20260716"),
    ],
)
def test_query_as_of_yyyymmdd_in_uses_declared_maximum_upper_bound(
    values: list[str],
    expected_cutoff: str,
) -> None:
    contract = _contract()
    daily = load_dataset_registry().resolve("cn.equity.daily")
    request = contract.parse_query_request(
        _payload(
            as_of="2026-07-16T00:00:00+08:00",
            filters={"trade_date": {"in": values}},
        )
    )

    resolved = contract.resolve_query_as_of(request, daily)

    assert resolved.encoded_cutoff == expected_cutoff


def test_query_as_of_yyyymmdd_in_rejects_invalid_member() -> None:
    contract = _contract()
    daily = load_dataset_registry().resolve("cn.equity.daily")
    request = contract.parse_query_request(
        _payload(
            as_of="2026-07-16T00:00:00+08:00",
            filters={"trade_date": {"in": ["20260715", "not-a-date"]}},
        )
    )

    with pytest.raises(contract.QueryValidationError, match="yyyymmdd"):
        contract.resolve_query_as_of(request, daily)


def test_query_as_of_yyyymm_uses_month_partition_and_filter_bound() -> None:
    contract = _contract()
    dataset = replace(
        load_dataset_registry().resolve("cn.equity.daily"),
        as_of_field="month",
        as_of_format="yyyymm",
        range_field="month",
        partition_field="month",
    )
    request = contract.parse_query_request(
        _payload(
            as_of="2026-07-31T23:59:59+08:00",
            filters={"month": {"in": ["202606", "202607"]}},
        )
    )

    resolved = contract.resolve_query_as_of(request, dataset)

    assert resolved.encoded_cutoff == "202607"
    assert resolved.resolved_as_of == "2026-07-01T00:00:00+08:00"


def test_query_as_of_yyyymm_rejects_invalid_filter_member() -> None:
    contract = _contract()
    dataset = replace(
        load_dataset_registry().resolve("cn.equity.daily"),
        as_of_field="month",
        as_of_format="yyyymm",
        range_field="month",
        partition_field="month",
    )
    request = contract.parse_query_request(
        _payload(
            as_of="2026-07-31T23:59:59+08:00",
            filters={"month": {"eq": "202613"}},
        )
    )

    with pytest.raises(contract.QueryValidationError, match="yyyymm"):
        contract.resolve_query_as_of(request, dataset)


@pytest.mark.parametrize(
    ("values", "expected_cutoff"),
    [
        (
            ["2026-07-16T10:00:00Z", "2026-07-16T11:00:00Z"],
            "2026-07-16T11:00:00+00:00",
        ),
        (
            ["2026-07-16T13:00:00Z", "2026-07-16T14:00:00Z"],
            "2026-07-16T12:00:00.123456+00:00",
        ),
    ],
)
def test_query_as_of_rfc3339_in_uses_declared_maximum_upper_bound(
    values: list[str],
    expected_cutoff: str,
) -> None:
    contract = _contract()
    dataset = replace(
        load_dataset_registry().resolve("cn.equity.daily"),
        as_of_field="collected_at",
        as_of_format="rfc3339",
        timezone="UTC",
    )
    request = contract.parse_query_request(
        _payload(
            as_of="2026-07-16T12:00:00.123456Z",
            filters={"collected_at": {"in": values}},
        )
    )

    resolved = contract.resolve_query_as_of(request, dataset)

    assert resolved.encoded_cutoff == expected_cutoff


def test_query_as_of_rfc3339_in_rejects_invalid_member() -> None:
    contract = _contract()
    dataset = replace(
        load_dataset_registry().resolve("cn.equity.daily"),
        as_of_field="collected_at",
        as_of_format="rfc3339",
        timezone="UTC",
    )
    request = contract.parse_query_request(
        _payload(
            as_of="2026-07-16T12:00:00Z",
            filters={
                "collected_at": {"in": ["2026-07-16T11:00:00Z", "not-a-timestamp"]}
            },
        )
    )

    with pytest.raises(contract.QueryValidationError, match="RFC3339"):
        contract.resolve_query_as_of(request, dataset)


@pytest.mark.parametrize(
    "invalid_bound",
    [
        "2026-07-16T00:00:00+08:60",
        "2026-07-16T00:00:00+08:99",
        "2026-07-16T00:00:00-00:00",
    ],
)
def test_query_as_of_rfc3339_dataset_bound_rejects_invalid_offset(
    invalid_bound: str,
) -> None:
    contract = _contract()
    dataset = replace(
        load_dataset_registry().resolve("cn.equity.daily"),
        as_of_field="collected_at",
        as_of_format="rfc3339",
        timezone="UTC",
    )
    request = contract.parse_query_request(
        _payload(
            as_of="2026-07-16T23:59:59Z",
            filters={"collected_at": {"eq": invalid_bound}},
        )
    )

    with pytest.raises(contract.QueryValidationError, match="RFC3339"):
        contract.resolve_query_as_of(request, dataset)


def test_query_as_of_rfc3339_cross_timezone_preserves_valid_offset_boundary() -> None:
    contract = _contract()
    dataset = replace(
        load_dataset_registry().resolve("cn.equity.daily"),
        as_of_field="collected_at",
        as_of_format="rfc3339",
        timezone="UTC",
    )
    request = contract.parse_query_request(
        _payload(
            as_of="2026-07-16T23:59:59Z",
            filters={"collected_at": {"eq": "2026-07-16T00:00:00+08:59"}},
        )
    )

    resolved = contract.resolve_query_as_of(request, dataset)

    assert resolved.encoded_cutoff == "2026-07-15T15:01:00+00:00"


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


def test_internal_query_options_classify_or_term_overflow_as_budget() -> None:
    contract = _contract()
    four_terms = (("a", 1), ("b", 2), ("c", 3), ("d", 4))

    options = contract.QueryExecutionOptions(any_of_eq_filters=four_terms)

    assert options.any_of_eq_filters == four_terms
    with pytest.raises(contract.QueryBudgetError):
        contract.QueryExecutionOptions(any_of_eq_filters=(*four_terms, ("e", 5)))

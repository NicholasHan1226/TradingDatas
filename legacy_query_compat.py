"""Pure request/response translation for migrated legacy read surfaces."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import re
from typing import Mapping

from dataset_registry import DatasetDefinition, DatasetRegistry
from query_contract import (
    QueryBudgetError,
    QueryExecutionOptions,
    QueryRequest,
    QueryValidationError,
)


_CANONICAL_LIMIT_RE = re.compile(r"[1-9][0-9]*\Z", re.ASCII)
_API_NAME_RE = re.compile(r"[A-Za-z0-9_]+\Z", re.ASCII)
_YYYYMMDD_RE = re.compile(r"[0-9]{8}\Z", re.ASCII)
_DASHED_DATE_RE = re.compile(
    r"(?P<year>[0-9]{4})[-/](?P<month>[0-9]{2})[-/](?P<day>[0-9]{2})\Z",
    re.ASCII,
)
_MARKET_ALIASES = {
    "ashare": "Ashare",
    "a_share": "Ashare",
    "cn": "Ashare",
    "china": "Ashare",
    "cnfutures": "Futures",
    "cn_futures": "Futures",
    "future": "Futures",
    "futures": "Futures",
    "fund": "Fund",
    "etf": "ETF",
    "option": "Options",
    "options": "Options",
    "hk": "HK",
    "us": "US",
}
_LEGACY_CONTROL_PARAMS = frozenset(
    {
        "api_name",
        "table",
        "limit",
        "cursor",
        "ts_code",
        "symbol",
        "start",
        "start_date",
        "end",
        "end_date",
        "date",
        "trade_date",
        "ann_date",
        "period",
    }
)


@dataclass(frozen=True)
class LegacyQueryInvocation:
    request: QueryRequest
    options: QueryExecutionOptions


def normalize_stock_master_table(value: object) -> str | None:
    """Return the sole canonical stock-master name for accepted legacy spelling."""

    if type(value) is not str:
        return None
    return "stock_master" if value.strip().casefold() == "stock_master" else None


def _canonical_params(params: Mapping[str, str]) -> dict[str, str]:
    if not isinstance(params, Mapping):
        raise QueryValidationError("legacy parameters must be a mapping")
    normalized: dict[str, str] = {}
    for key, value in params.items():
        if type(key) is not str or type(value) is not str:
            raise QueryValidationError("legacy parameters must contain strings")
        if key in normalized:
            raise QueryValidationError("legacy parameters contain duplicates")
        normalized[key] = value
    return normalized


def _limit(params: Mapping[str, str]) -> int:
    raw = params.get("limit")
    if raw is None:
        return 500
    if _CANONICAL_LIMIT_RE.fullmatch(raw) is None:
        raise QueryValidationError("limit must be a canonical integer in 1..500")
    if len(raw) > 3 or (len(raw) == 3 and raw > "500"):
        raise QueryBudgetError("limit exceeds compatibility maximum 500")
    return int(raw)


def _cursor(params: Mapping[str, str]) -> str | None:
    raw = params.get("cursor")
    if raw is None:
        return None
    if not raw or raw != raw.strip():
        raise QueryValidationError("cursor must be a canonical non-empty string")
    return raw


def _canonical_date(value: str, name: str) -> str:
    if not value or value != value.strip():
        raise QueryValidationError(f"{name} must be a canonical date")
    if _YYYYMMDD_RE.fullmatch(value) is not None:
        candidate = value
    else:
        match = _DASHED_DATE_RE.fullmatch(value)
        if match is None:
            raise QueryValidationError(f"{name} must use YYYYMMDD or YYYY-MM-DD")
        candidate = "".join(
            (match.group("year"), match.group("month"), match.group("day"))
        )
    try:
        datetime.strptime(candidate, "%Y%m%d")
    except ValueError:
        raise QueryValidationError(f"{name} must be a valid date") from None
    return candidate


def _one_legacy_value(
    params: Mapping[str, str],
    names: tuple[str, ...],
    *,
    label: str,
) -> str | None:
    values = [params[name] for name in names if name in params and params[name] != ""]
    if not values:
        if any(name in params for name in names):
            raise QueryValidationError(f"{label} must not be empty")
        return None
    if any(value != values[0] for value in values[1:]):
        raise QueryValidationError(f"conflicting {label} parameters")
    return values[0]


def _date_field(dataset: DatasetDefinition) -> str | None:
    if dataset.range_field is not None:
        return dataset.range_field
    declared = {field.name: field for field in dataset.fields}
    for name in ("trade_date", "ann_date", "event_time", "updated_at", "collected_at"):
        field = declared.get(name)
        if field is not None and field.filterable and field.sortable:
            return name
    return None


def _schema_major(dataset: DatasetDefinition) -> int:
    major = dataset.schema_version.split(".", 1)[0]
    if not major.isdigit() or int(major) <= 0:
        raise QueryValidationError("dataset schema version is not compatible")
    return int(major)


def _market_value(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise QueryValidationError("market must not be empty")
    return _MARKET_ALIASES.get(normalized.casefold(), normalized)


class LegacyQueryCompat:
    """Translate legacy names into one registry-owned query invocation."""

    __slots__ = ("_registry",)

    def __init__(self, registry: DatasetRegistry) -> None:
        if not isinstance(registry, DatasetRegistry):
            raise TypeError("registry must be DatasetRegistry")
        self._registry = registry

    def tushare_request(
        self,
        params: Mapping[str, str],
    ) -> LegacyQueryInvocation:
        normalized = _canonical_params(params)
        api_name = normalized.get("api_name")
        if (
            api_name is None
            or _API_NAME_RE.fullmatch(api_name) is None
            or api_name != api_name.strip()
        ):
            raise QueryValidationError("api_name is required")
        try:
            dataset = self._registry.resolve(f"tushare.{api_name}")
            binding = self._registry.provider_binding(dataset.dataset_id, "tushare")
        except KeyError:
            raise QueryValidationError("api_name is not available") from None
        if binding.api_name != api_name:
            raise QueryValidationError("api_name is not available")

        filters: dict[str, object] = {}
        options: list[tuple[str, object]] = []
        fields = {field.name: field for field in dataset.fields}
        symbol = _one_legacy_value(
            normalized,
            ("ts_code", "symbol"),
            label="symbol",
        )
        if symbol is not None:
            if {
                "parent_symbol",
                "child_symbol",
            } <= fields.keys() and all(
                fields[name].filterable for name in ("parent_symbol", "child_symbol")
            ):
                options.extend(
                    (("parent_symbol", symbol), ("child_symbol", symbol))
                )
            elif "symbol" in fields and fields["symbol"].filterable:
                filters["symbol"] = {"eq": symbol}
            else:
                raise QueryValidationError("symbol is not supported by this dataset")

        date_field = _date_field(dataset)
        start = _one_legacy_value(
            normalized,
            ("start_date", "start"),
            label="start_date",
        )
        end = _one_legacy_value(
            normalized,
            ("end_date", "end"),
            label="end_date",
        )
        exact = _one_legacy_value(
            normalized,
            ("date", "trade_date", "ann_date", "period"),
            label="date",
        )
        if exact is not None and (start is not None or end is not None):
            raise QueryValidationError("date cannot be combined with a date window")
        if (start is not None or end is not None or exact is not None) and date_field is None:
            raise QueryValidationError("date filtering is not supported by this dataset")
        if exact is not None and date_field is not None:
            filters[date_field] = {"eq": _canonical_date(exact, "date")}
        elif start is not None and end is not None and date_field is not None:
            start_value = _canonical_date(start, "start_date")
            end_value = _canonical_date(end, "end_date")
            if start_value > end_value:
                raise QueryValidationError("start_date must not exceed end_date")
            filters[date_field] = {"between": (start_value, end_value)}
        elif start is not None and date_field is not None:
            filters[date_field] = {"gte": _canonical_date(start, "start_date")}
        elif end is not None and date_field is not None:
            filters[date_field] = {"lte": _canonical_date(end, "end_date")}

        for name, value in normalized.items():
            if name in _LEGACY_CONTROL_PARAMS:
                continue
            field = fields.get(name)
            if field is None or not field.filterable:
                raise QueryValidationError(f"legacy parameter {name!r} is not supported")
            if name in filters:
                raise QueryValidationError(f"legacy parameter {name!r} is duplicated")
            filters[name] = {"eq": _market_value(value) if name == "market" else value}

        latest_partition = bool(
            dataset.partition_field is not None
            and start is None
            and end is None
            and exact is None
        )
        order = (f"{date_field}:desc",) if date_field is not None else None
        request = QueryRequest(
            dataset_id=dataset.dataset_id,
            schema_major=_schema_major(dataset),
            fields=(),
            filters=filters,
            as_of=None,
            order=order,
            limit=_limit(normalized),
            cursor=_cursor(normalized),
        )
        return LegacyQueryInvocation(
            request=request,
            options=QueryExecutionOptions(
                latest_partition=latest_partition,
                any_of_eq_filters=tuple(options),
            ),
        )

    def stock_master_request(
        self,
        params: Mapping[str, str],
    ) -> LegacyQueryInvocation:
        normalized = _canonical_params(params)
        table = normalize_stock_master_table(normalized.get("table"))
        if table is None:
            raise QueryValidationError("reference table must be stock_master")
        normalized["table"] = table
        unknown = set(normalized) - {"table", "limit", "cursor"}
        if unknown:
            raise QueryValidationError("stock_master parameters are not supported")
        try:
            dataset = self._registry.resolve("cn.equity.security_master")
        except KeyError:
            raise QueryValidationError("stock_master is not available") from None
        return LegacyQueryInvocation(
            request=QueryRequest(
                dataset_id=dataset.dataset_id,
                schema_major=_schema_major(dataset),
                fields=(),
                filters={},
                as_of=None,
                order=("symbol:asc",),
                limit=_limit(normalized),
                cursor=_cursor(normalized),
            ),
            options=QueryExecutionOptions(),
        )

    def legacy_envelope(
        self,
        query_envelope: Mapping[str, object],
    ) -> dict[str, object]:
        if not isinstance(query_envelope, Mapping):
            raise QueryValidationError("query envelope is invalid")
        data = query_envelope.get("data")
        metadata_value = query_envelope.get("metadata")
        if type(data) is not list or not isinstance(metadata_value, Mapping):
            raise QueryValidationError("query envelope is invalid")
        if any(type(row) is not dict for row in data):
            raise QueryValidationError("query envelope is invalid")

        metadata = dict(metadata_value)
        reasons = metadata.get("reasons", [])
        if type(reasons) is not list or any(type(reason) is not str for reason in reasons):
            raise QueryValidationError("query envelope metadata is invalid")
        metadata["degraded_reasons"] = list(reasons)
        metadata["next_cursor"] = query_envelope.get("next_cursor")
        metadata["row_count"] = len(data)
        for name in (
            "catalog_version",
            "request_id",
            "dataset_id",
            "schema_version",
        ):
            metadata[name] = query_envelope.get(name)

        source: str | None = None
        lineage = metadata.get("lineage")
        if isinstance(lineage, Mapping):
            providers = lineage.get("providers")
            if type(providers) is list and providers and type(providers[0]) is str:
                source = providers[0]
        return {
            "data": [dict(row) for row in data],
            "metadata": metadata,
            "source": source,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

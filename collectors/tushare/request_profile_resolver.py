"""Validate deprecated Tushare request profiles during contract migration.

This module is migration-only.  It is not an entitlement or activation authority and
must not be imported by the collector, scheduler, or production command surface.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import math
import re
from types import MappingProxyType
from typing import Any
from zoneinfo import ZoneInfo


_PROFILE_ID = "tushare-request-profiles.v1"
_PROVIDER = "tushare"
_DOCUMENT_SNAPSHOT_ID = "tushare-official-document-contracts.v1"
_INPUT_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,63}")
_OUTPUT_FIELD_NAME = re.compile(r"[A-Za-z0-9_]{1,64}")
_UTC_SECOND = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")
_SHANGHAI = ZoneInfo("Asia/Shanghai")
_MAX_OFFSET_SECONDS = 366 * 24 * 60 * 60
_TRANSFORMS = frozenset(
    {"yyyymmdd", "yyyymm", "yyyy_qn", "yyyyww", "local_datetime_seconds"}
)
_PROFILE_TRANSFORMS = _TRANSFORMS | {"last_completed_quarter_end"}
_UNRESOLVED_ENUM_REASON = "official_enum_table_not_snapshotted"
_PROFILE_REASONS = frozenset(
    {
        "current_approved_bounded_static",
        "clock_static_literal_ready",
        "requires_fresh_stock_anchor",
        "empty_parameter_unbounded",
        "requires_fresh_anchor",
        "official_enum_unresolved",
    }
)
_EXECUTABLE_REASONS = frozenset(
    {"current_approved_bounded_static", "clock_static_literal_ready"}
)
_BLOCKED_REASONS = _PROFILE_REASONS - _EXECUTABLE_REASONS
_EXPECTED_COUNTS = {
    "dataset_profiles": 187,
    "profile_ready": 153,
    "selectable_probe": 135,
    "pending_stock_anchor": 18,
    "plan_only_blocked": 34,
    "empty_parameter_blocked": 14,
    "other_anchor_blocked": 18,
    "unresolved_enum_blocked": 2,
}
_EXPECTED_LIMITS = {
    "require_explicit_dataset_selection": True,
    "max_selected_datasets": 5,
    "max_calls_per_dataset": 1,
    "retries": 0,
    "max_response_bytes": 131_072,
    "timezone": "Asia/Shanghai",
}


@dataclass(frozen=True)
class RequestParameter:
    source: str
    value: object = None
    transform: str | None = None
    offset_seconds: int | None = None


@dataclass(frozen=True)
class RequestProfileSpec:
    dataset_id: str
    api_name: str
    classification: str
    executable: bool
    reason: str
    parameters: Mapping[str, RequestParameter]
    fields: tuple[str, ...]
    max_response_bytes: int
    source_document_sha256: str


@dataclass(frozen=True)
class ProbeSpec:
    dataset_id: str
    api_name: str
    classification: str
    params: Mapping[str, object]
    parameter_sources: Mapping[str, str]
    fields: tuple[str, ...]
    max_response_bytes: int
    source_document_sha256: str


@dataclass(frozen=True)
class RequestProfileCatalog:
    profiles: Mapping[str, RequestProfileSpec]
    counts: Mapping[str, int]
    max_selected_datasets: int


def _text(value: object, label: str) -> str:
    if type(value) is not str or not value or value != value.strip():
        raise ValueError(f"{label} must be non-empty canonical text")
    return value


def _exact_keys(value: Mapping[str, Any], expected: set[str], label: str) -> None:
    if set(value) != expected:
        raise ValueError(f"{label} keys do not match the frozen contract")


def _json_scalar(value: object, label: str) -> object:
    if value is None or type(value) in (str, bool, int):
        return value
    if type(value) is float and math.isfinite(value):
        return value
    raise ValueError(f"{label} must be a finite JSON scalar")


def _input_contract(
    document: Mapping[str, Any], api_name: str
) -> tuple[set[str], set[str]]:
    raw_fields = document.get("input_fields")
    if type(raw_fields) is not list:
        raise ValueError(f"{api_name}.input_fields must be a list")
    names: set[str] = set()
    required: set[str] = set()
    for index, raw_field in enumerate(raw_fields):
        if type(raw_field) is not dict:
            raise ValueError(f"{api_name}.input field {index} must be a mapping")
        name = _text(raw_field.get("name"), f"{api_name}.input field {index}.name")
        if _INPUT_NAME.fullmatch(name) is None or name in names:
            raise ValueError(f"{api_name}.input field names are invalid")
        names.add(name)
        if raw_field.get("required") == "Y":
            required.add(name)
    return names, required


def _first_legal_output_field(document: Mapping[str, Any], api_name: str) -> str:
    raw_fields = document.get("output_fields")
    if type(raw_fields) is not list:
        raise ValueError(f"{api_name}.output_fields must be a list")
    for raw_field in raw_fields:
        if type(raw_field) is not dict:
            continue
        name = raw_field.get("name")
        if type(name) is str and _OUTPUT_FIELD_NAME.fullmatch(name) is not None:
            return name
    raise ValueError(f"{api_name} has no legal documented output field")


def _validated_parameter(
    raw: object,
    *,
    api_name: str,
    parameter_name: str,
    executable: bool,
) -> RequestParameter | None:
    label = f"request profile {api_name}.{parameter_name}"
    if type(raw) is not dict:
        raise ValueError(f"{label} must be a mapping")
    source = raw.get("source")
    if source == "literal":
        _exact_keys(raw, {"source", "value"}, label)
        return RequestParameter(
            source="literal",
            value=_json_scalar(raw["value"], f"{label}.value"),
        )
    if source == "observed_at":
        _exact_keys(raw, {"source", "transform", "offset_seconds"}, label)
        transform = raw["transform"]
        if type(transform) is not str or transform not in _PROFILE_TRANSFORMS:
            raise ValueError(f"{label}.transform is unsupported")
        offset = raw["offset_seconds"]
        if type(offset) is not int or abs(offset) > _MAX_OFFSET_SECONDS:
            raise ValueError(f"{label}.offset_seconds must be a bounded integer")
        if executable and transform not in _TRANSFORMS:
            raise ValueError(f"{label}.transform is not executable")
        return RequestParameter(
            source="observed_at",
            transform=transform,
            offset_seconds=offset,
        )
    if source == "dataset_field":
        _exact_keys(
            raw,
            {
                "source",
                "dataset_id",
                "field",
                "requires_fresh_success_receipt",
            },
            label,
        )
        _text(raw["dataset_id"], f"{label}.dataset_id")
        field = _text(raw["field"], f"{label}.field")
        if _OUTPUT_FIELD_NAME.fullmatch(field) is None:
            raise ValueError(f"{label}.field is invalid")
        if raw["requires_fresh_success_receipt"] is not True:
            raise ValueError(
                f"{label}.requires_fresh_success_receipt must be exactly true"
            )
        if executable:
            raise ValueError(f"{label}.source is not executable")
        return None
    if source == "unresolved_enum":
        _exact_keys(raw, {"source", "reason"}, label)
        if raw["reason"] != _UNRESOLVED_ENUM_REASON:
            raise ValueError(f"{label}.reason is unsupported")
        if executable:
            raise ValueError(f"{label}.source is not executable")
        return None
    raise ValueError(f"{label}.source is unsupported")


def load_request_profile_catalog(
    value: Mapping[str, Any],
    *,
    document_by_api: Mapping[str, Mapping[str, Any]],
    dataset_by_api: Mapping[str, str],
    classification_by_api: Mapping[str, str],
    existing_activations: Sequence[str],
    expected_document_sha: str,
) -> RequestProfileCatalog:
    """Validate the frozen profile surface and retain each request definition."""

    _exact_keys(
        value,
        {
            "version",
            "profile_id",
            "provider",
            "source_documents",
            "excluded_existing_activations",
            "counts",
            "execution_limits",
            "fields_strategy",
            "groups",
        },
        "request profiles",
    )
    if (
        value.get("version") != 1
        or value.get("profile_id") != _PROFILE_ID
        or value.get("provider") != _PROVIDER
    ):
        raise ValueError("request profiles identity is unsupported")
    if value.get("fields_strategy") != "first_documented_output_field":
        raise ValueError("request profile fields strategy differs")
    source = value.get("source_documents")
    if type(source) is not dict or source != {
        "snapshot_id": _DOCUMENT_SNAPSHOT_ID,
        "sha256": expected_document_sha,
        "contract_count": len(document_by_api),
    }:
        raise ValueError("request profile document source differs")
    if value.get("excluded_existing_activations") != sorted(existing_activations):
        raise ValueError("request profile existing activations differ")
    if value.get("counts") != _EXPECTED_COUNTS:
        raise ValueError("request profile counts differ from frozen scope")
    if value.get("execution_limits") != _EXPECTED_LIMITS:
        raise ValueError("request profile execution limits differ")

    groups = value.get("groups")
    if type(groups) is not dict or not groups:
        raise ValueError("request profile groups must be a mapping")
    profiles: dict[str, RequestProfileSpec] = {}
    seen_apis: set[str] = set()
    reason_counts = {reason: 0 for reason in _PROFILE_REASONS}
    executable_count = 0
    for group_name, group in groups.items():
        if type(group_name) is not str or type(group) is not dict:
            raise ValueError("request profile group is invalid")
        _exact_keys(
            group,
            {"execution_state", "reason", "parameters", "api_names"},
            f"request profile group {group_name}",
        )
        state = group["execution_state"]
        reason = group["reason"]
        if state not in {"executable", "plan_only"} or reason not in _PROFILE_REASONS:
            raise ValueError(f"request profile group {group_name} state differs")
        executable = state == "executable"
        if (executable and reason not in _EXECUTABLE_REASONS) or (
            not executable and reason not in _BLOCKED_REASONS
        ):
            raise ValueError(f"request profile group {group_name} reason differs")
        raw_parameters = group["parameters"]
        if type(raw_parameters) is not dict:
            raise ValueError(f"request profile group {group_name} params differ")
        api_names = group["api_names"]
        if (
            type(api_names) is not list
            or not api_names
            or api_names != sorted(set(api_names))
        ):
            raise ValueError(f"request profile group {group_name} APIs differ")

        for api_name_value in api_names:
            api_name = _text(api_name_value, f"request profile group {group_name} API")
            if (
                api_name in seen_apis
                or api_name not in document_by_api
                or api_name not in dataset_by_api
                or api_name not in classification_by_api
                or api_name in existing_activations
            ):
                raise ValueError("request profiles contain duplicate or unknown API")
            document = document_by_api[api_name]
            input_fields, required_fields = _input_contract(document, api_name)
            parameter_names = set(raw_parameters)
            if any(
                type(name) is not str or _INPUT_NAME.fullmatch(name) is None
                for name in parameter_names
            ) or not parameter_names.issubset(input_fields):
                raise ValueError(f"request profile {api_name} parameters differ")

            parameters: dict[str, RequestParameter] = {}
            if not required_fields.issubset(parameter_names):
                raise ValueError(
                    f"request profile {api_name} omits required input fields"
                )
            for name in sorted(parameter_names):
                parameter = _validated_parameter(
                    raw_parameters[name],
                    api_name=api_name,
                    parameter_name=name,
                    executable=executable,
                )
                if parameter is not None:
                    parameters[name] = parameter

            dataset_id = _text(dataset_by_api[api_name], f"{api_name}.dataset_id")
            if dataset_id in profiles:
                raise ValueError("request profiles contain duplicate dataset")
            profiles[dataset_id] = RequestProfileSpec(
                dataset_id=dataset_id,
                api_name=api_name,
                classification=_text(
                    classification_by_api[api_name], f"{api_name}.classification"
                ),
                executable=executable,
                reason=reason,
                parameters=MappingProxyType(parameters),
                fields=(_first_legal_output_field(document, api_name),),
                max_response_bytes=_EXPECTED_LIMITS["max_response_bytes"],
                source_document_sha256=_text(
                    document.get("doc_sha256"), f"{api_name}.doc_sha256"
                ),
            )
            seen_apis.add(api_name)
            reason_counts[reason] += 1
            executable_count += executable

    expected_apis = set(document_by_api) - set(existing_activations)
    if (
        seen_apis != expected_apis
        or len(profiles) != _EXPECTED_COUNTS["dataset_profiles"]
    ):
        raise ValueError("request profiles do not exactly cover remaining APIs")
    if (
        executable_count != _EXPECTED_COUNTS["selectable_probe"]
        or reason_counts["requires_fresh_stock_anchor"] != 18
        or reason_counts["empty_parameter_unbounded"] != 14
        or reason_counts["requires_fresh_anchor"] != 18
        or reason_counts["official_enum_unresolved"] != 2
    ):
        raise ValueError("request profile group counts differ")
    return RequestProfileCatalog(
        profiles=MappingProxyType(dict(sorted(profiles.items()))),
        counts=MappingProxyType(dict(_EXPECTED_COUNTS)),
        max_selected_datasets=_EXPECTED_LIMITS["max_selected_datasets"],
    )


def _parse_observed_at(value: str) -> datetime:
    if type(value) is not str or _UTC_SECOND.fullmatch(value) is None:
        raise ValueError("observed_at must be an exact UTC second ending in Z")
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except ValueError:
        raise ValueError("observed_at must be a valid UTC timestamp") from None


def _transform_observed_at(
    observed_at: datetime, transform: str, offset_seconds: int
) -> str:
    try:
        local = (observed_at + timedelta(seconds=offset_seconds)).astimezone(_SHANGHAI)
    except (OverflowError, ValueError):
        raise ValueError("request profile observed_at offset is out of range") from None
    if transform == "yyyymmdd":
        return local.strftime("%Y%m%d")
    if transform == "yyyymm":
        return local.strftime("%Y%m")
    if transform == "yyyy_qn":
        return f"{local.year:04d}Q{((local.month - 1) // 3) + 1}"
    if transform == "yyyyww":
        iso_year, iso_week, _ = local.isocalendar()
        return f"{iso_year:04d}{iso_week:02d}"
    if transform == "local_datetime_seconds":
        return local.strftime("%Y-%m-%d %H:%M:%S")
    raise ValueError("request profile observed_at transform is unsupported")


def resolve_request_profile(
    profile: RequestProfileSpec, *, observed_at: str
) -> ProbeSpec:
    """Resolve one migration fixture without credentials, provider I/O, or activation."""

    if not isinstance(profile, RequestProfileSpec) or not profile.executable:
        raise ValueError("request profile is not executable")
    if (
        len(profile.fields) != 1
        or _OUTPUT_FIELD_NAME.fullmatch(profile.fields[0]) is None
        or profile.max_response_bytes != _EXPECTED_LIMITS["max_response_bytes"]
    ):
        raise ValueError("request profile output budget is invalid")
    clock = _parse_observed_at(observed_at)
    params: dict[str, object] = {}
    parameter_sources: dict[str, str] = {}
    for name, parameter in profile.parameters.items():
        if type(name) is not str or _INPUT_NAME.fullmatch(name) is None:
            raise ValueError("request profile contains an invalid parameter name")
        if (
            parameter.source == "literal"
            and parameter.transform is None
            and parameter.offset_seconds is None
        ):
            params[name] = _json_scalar(
                parameter.value,
                f"request profile {profile.api_name}.{name}.value",
            )
            parameter_sources[name] = "reviewed_policy_literal"
            continue
        if (
            parameter.source != "observed_at"
            or parameter.value is not None
            or parameter.transform not in _TRANSFORMS
            or type(parameter.offset_seconds) is not int
            or abs(parameter.offset_seconds) > _MAX_OFFSET_SECONDS
        ):
            raise ValueError("request profile contains an unresolved parameter")
        params[name] = _transform_observed_at(
            clock,
            parameter.transform,
            parameter.offset_seconds,
        )
        parameter_sources[name] = (
            "reviewed_profile_observed_at:"
            f"{parameter.transform}:offset_seconds={parameter.offset_seconds}"
        )
    return ProbeSpec(
        dataset_id=profile.dataset_id,
        api_name=profile.api_name,
        classification=profile.classification,
        params=MappingProxyType(dict(sorted(params.items()))),
        parameter_sources=MappingProxyType(dict(sorted(parameter_sources.items()))),
        fields=profile.fields,
        max_response_bytes=profile.max_response_bytes,
        source_document_sha256=profile.source_document_sha256,
    )

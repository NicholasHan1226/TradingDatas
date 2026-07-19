#!/usr/bin/env python3
"""Compile legacy Tushare registry/config into a provider-native candidate.

The compiler is deliberately offline and side-effect free by default.  It reads
the existing registry, capability plan, and collector configuration, then emits
either a deterministic bundle, a candidate registry, or an unresolved/conflict
report.  It never changes ``config/dataset_registry.yaml`` and never calls a
provider.

Examples::

    python tools/compile_provider_native_registry.py
    python tools/compile_provider_native_registry.py --kind report
    python tools/compile_provider_native_registry.py \
      --kind candidate --output /private/tmp/provider-native-registry.yaml
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from copy import deepcopy
import hashlib
import os
from pathlib import Path
from pathlib import PurePosixPath
import re
import tempfile
from typing import Any, Mapping, Sequence

import yaml


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REGISTRY_PATH = REPOSITORY_ROOT / "config" / "dataset_registry.yaml"
DEFAULT_CAPABILITY_PLAN_PATH = (
    REPOSITORY_ROOT / "config" / "tushare_capability_plan.yaml"
)
DEFAULT_COLLECTOR_CONFIG_PATH = (
    REPOSITORY_ROOT / "collectors" / "tushare" / "config.yaml"
)
DEFAULT_UPSTREAM_CONTRACTS_PATH = (
    REPOSITORY_ROOT / "config" / "tushare_upstream_contracts.v1.yaml"
)
DEFAULT_ACTIVATION_PATH = REPOSITORY_ROOT / "config" / "provider_native_activation.yaml"

PROVIDER = "tushare"
PROVIDER_ADAPTER_VERSION = "tushare-provider-native.v1"
READ_ADAPTER_VERSION = "provider-native-json.v1"
PROVIDER_NATIVE_TABLE = "provider_dataset_rows"

_SAFE_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,63}")
_WINDOW_PLACEHOLDER = re.compile(r"\$\{window\.([A-Za-z_][A-Za-z0-9_]{0,63})\}")
_HASH_PATTERN = re.compile(r"[0-9a-f]{64}")
_COMMIT_PATTERN = re.compile(r"[0-9a-f]{40}")
_SCHEMA_VERSION_PATTERN = re.compile(r"[1-9][0-9]*\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)")
_LOGICAL_TYPES = frozenset({"text", "integer", "float"})
_AS_OF_FORMATS = frozenset({"yyyymmdd", "rfc3339"})
_ROOT_CONTRACT_KEYS = frozenset(
    {"version", "bundle_id", "provider", "provenance", "contracts"}
)
_PROVENANCE_KEYS = frozenset(
    {"repository_url", "pinned_commit", "index_path", "index_sha256"}
)
_CONTRACT_KEYS = frozenset(
    {
        "dataset_id",
        "provider",
        "api_name",
        "source_document_url",
        "source_document_sha256",
        "schema_version",
        "fields",
        "primary_key",
        "default_projection",
        "as_of_field",
        "as_of_format",
        "range_field",
        "partition_field",
        "cadence_class",
        "point_in_time",
        "backfill_policy",
        "empty_data_policy",
        "required_scope",
        "quota_class",
        "request_template",
        "request_variants",
        "request_window_policy",
        "response_completeness",
        "requested_fields",
        "budgets",
        "reviewed_type_overrides",
    }
)
_CONTRACT_REQUIRED_KEYS = _CONTRACT_KEYS - {"request_window_policy"}
_CONTRACT_FIELD_KEYS = frozenset(
    {
        "name",
        "declared_source_type",
        "logical_type",
        "nullable",
        "selectable",
        "filterable",
        "sortable",
    }
)
_WINDOW_POLICY_KEYS = frozenset(
    {
        "required_keys",
        "formats",
        "range_start_key",
        "range_end_key",
        "max_span_days",
    }
)
_RESPONSE_COMPLETENESS_KEYS = frozenset(
    {
        "strategy",
        "date_field",
        "request_start_key",
        "request_end_key",
        "partition_field",
        "request_partition_key",
        "fixed_field_matches",
        "reject_at_row_limit",
    }
)
_RESPONSE_COMPLETENESS_STRATEGIES = frozenset(
    {
        "one_row_per_calendar_date",
        "unique_primary_key_snapshot",
        "single_partition_unique_primary_key",
    }
)
_BUDGET_KEYS = frozenset(
    {
        "max_rows_per_attempt",
        "max_payload_bytes_per_row",
        "max_batch_bytes",
        "max_nesting_depth",
    }
)
_TYPE_OVERRIDE_KEYS = frozenset(
    {
        "field",
        "declared_source_type",
        "observed_json_type",
        "logical_type",
        "reason",
        "evidence",
    }
)
_ACTIVATION_ROOT_KEYS = frozenset({"version", "activations"})
_ACTIVATION_ENTRY_KEYS = frozenset(
    {
        "dataset_id",
        "provider",
        "entitlement_state",
        "activation_state",
        "evidence_ref",
    }
)
_ENTITLEMENT_STATES = frozenset({"active", "locked", "unknown", "excluded", "retired"})
_ACTIVATION_STATES = frozenset({"active", "paused"})
_EVIDENCE_REF_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,255}")
_SENSITIVE_EVIDENCE_PATTERN = re.compile(
    r"(?:secret|token|password|authorization|bearer|credential|api[_-]?key)",
    re.IGNORECASE,
)


def _mapping(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a mapping")
    return value


def _sequence(value: object, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError(f"{label} must be a list")
    return value


def _non_empty_text(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip()


def _plan_index(
    plan: Mapping[str, Any],
) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, object]]]:
    index: dict[str, list[dict[str, Any]]] = defaultdict(list)
    conflicts: list[dict[str, object]] = []
    modules = plan.get("modules", [])
    if not isinstance(modules, list):
        return index, [
            {
                "code": "invalid_capability_plan_modules",
                "api_name": None,
                "details": ["modules must be a list"],
            }
        ]
    for module_index, raw_module in enumerate(modules):
        if not isinstance(raw_module, dict):
            conflicts.append(
                {
                    "code": "invalid_capability_plan_module",
                    "api_name": None,
                    "details": [f"modules[{module_index}] must be a mapping"],
                }
            )
            continue
        apis = raw_module.get("apis", [])
        if not isinstance(apis, list):
            conflicts.append(
                {
                    "code": "invalid_capability_plan_apis",
                    "api_name": None,
                    "details": [f"modules[{module_index}].apis must be a list"],
                }
            )
            continue
        for api_index, raw_api in enumerate(apis):
            if not isinstance(raw_api, dict):
                conflicts.append(
                    {
                        "code": "invalid_capability_plan_api",
                        "api_name": None,
                        "details": [
                            f"modules[{module_index}].apis[{api_index}] must be a mapping"
                        ],
                    }
                )
                continue
            api_name = _non_empty_text(raw_api.get("api_name"))
            if api_name is None:
                conflicts.append(
                    {
                        "code": "missing_capability_api_name",
                        "api_name": None,
                        "details": [f"modules[{module_index}].apis[{api_index}]"],
                    }
                )
                continue
            item = deepcopy(raw_api)
            item["module"] = raw_module.get("module")
            item["market"] = raw_module.get("market")
            item["effective_cadence"] = raw_api.get("cadence") or raw_module.get(
                "default_cadence"
            )
            index[api_name].append(item)
    return dict(index), conflicts


def _collector_index(
    collector: Mapping[str, Any],
) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, object]]]:
    index: dict[str, list[dict[str, Any]]] = defaultdict(list)
    conflicts: list[dict[str, object]] = []
    priorities = collector.get("priorities", {})
    if not isinstance(priorities, dict):
        return index, [
            {
                "code": "invalid_collector_priorities",
                "api_name": None,
                "details": ["priorities must be a mapping"],
            }
        ]
    for raw_tier, raw_items in priorities.items():
        tier = _non_empty_text(raw_tier)
        if tier is None or not isinstance(raw_items, list):
            conflicts.append(
                {
                    "code": "invalid_collector_tier",
                    "api_name": None,
                    "details": [str(raw_tier)],
                }
            )
            continue
        for item_index, raw_item in enumerate(raw_items):
            if not isinstance(raw_item, dict):
                conflicts.append(
                    {
                        "code": "invalid_collector_item",
                        "api_name": None,
                        "details": [f"{tier}[{item_index}] must be a mapping"],
                    }
                )
                continue
            api_name = _non_empty_text(raw_item.get("api_name"))
            if api_name is None:
                conflicts.append(
                    {
                        "code": "missing_collector_api_name",
                        "api_name": None,
                        "details": [f"{tier}[{item_index}]"],
                    }
                )
                continue
            item = deepcopy(raw_item)
            item["compiler_tier"] = tier
            index[api_name].append(item)
    return dict(index), conflicts


def _append_reason(
    reasons: list[dict[str, object]], code: str, details: Sequence[str]
) -> None:
    reasons.append({"code": code, "details": list(details)})


def _reject_contract_keys(
    value: Mapping[str, Any],
    allowed: frozenset[str],
    label: str,
    *,
    required: frozenset[str] | None = None,
) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise ValueError(f"{label} has unknown key(s): {', '.join(unknown)}")
    missing = sorted((required or allowed) - set(value))
    if missing:
        raise ValueError(f"{label} is missing key(s): {', '.join(missing)}")


def _required_text(value: object, label: str) -> str:
    normalized = _non_empty_text(value)
    if normalized is None:
        raise ValueError(f"{label} must be a non-empty string")
    return normalized


def _required_bool(value: object, label: str) -> bool:
    if type(value) is not bool:
        raise ValueError(f"{label} must be a boolean")
    return value


def _activation_index(
    document: Mapping[str, Any] | None,
) -> dict[tuple[str, str], dict[str, str | None]]:
    if document is None:
        return {}
    root = _mapping(deepcopy(document), "activation manifest")
    _reject_contract_keys(root, _ACTIVATION_ROOT_KEYS, "activation manifest")
    if type(root["version"]) is not int or root["version"] != 1:
        raise ValueError("activation manifest.version must be integer 1")
    index: dict[tuple[str, str], dict[str, str | None]] = {}
    for entry_index, raw_entry in enumerate(
        _sequence(root["activations"], "activation manifest.activations")
    ):
        label = f"activation manifest.activations[{entry_index}]"
        entry = _mapping(raw_entry, label)
        _reject_contract_keys(entry, _ACTIVATION_ENTRY_KEYS, label)
        dataset_id = _required_text(entry["dataset_id"], f"{label}.dataset_id")
        provider = _required_text(entry["provider"], f"{label}.provider")
        entitlement_state = _required_text(
            entry["entitlement_state"], f"{label}.entitlement_state"
        )
        activation_state = _required_text(
            entry["activation_state"], f"{label}.activation_state"
        )
        if entitlement_state not in _ENTITLEMENT_STATES:
            raise ValueError(f"{label}.entitlement_state is unsupported")
        if activation_state not in _ACTIVATION_STATES:
            raise ValueError(f"{label}.activation_state is unsupported")
        raw_evidence_ref = entry["evidence_ref"]
        if raw_evidence_ref is None:
            evidence_ref = None
        else:
            evidence_ref = _required_text(raw_evidence_ref, f"{label}.evidence_ref")
            path = PurePosixPath(evidence_ref)
            if (
                evidence_ref != str(path)
                or path.is_absolute()
                or ".." in path.parts
                or _EVIDENCE_REF_PATTERN.fullmatch(evidence_ref) is None
                or _SENSITIVE_EVIDENCE_PATTERN.search(evidence_ref) is not None
            ):
                raise ValueError(
                    f"{label}.evidence_ref must be a non-sensitive relative reference"
                )
        if activation_state == "active":
            if entitlement_state != "active":
                raise ValueError(
                    f"{label} activation_state=active requires entitlement_state=active"
                )
            if evidence_ref is None:
                raise ValueError(f"{label} active activation requires evidence_ref")
        key = (dataset_id, provider)
        if key in index:
            raise ValueError(
                f"duplicate activation for dataset/provider: {dataset_id}/{provider}"
            )
        index[key] = {
            "entitlement_state": entitlement_state,
            "activation_state": activation_state,
            "evidence_ref": evidence_ref,
        }
    return index


def _required_positive_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{label} must be a positive integer")
    return value


def _required_string_list(
    value: object,
    label: str,
    *,
    allow_empty: bool = False,
) -> list[str]:
    items = _sequence(value, label)
    if not items and not allow_empty:
        raise ValueError(f"{label} must not be empty")
    normalized = [_required_text(item, f"{label} item") for item in items]
    if len(normalized) != len(set(normalized)):
        raise ValueError(f"{label} must not contain duplicates")
    return normalized


def _declared_field(
    raw: object,
    *,
    contract_label: str,
    index: int,
) -> dict[str, Any]:
    label = f"{contract_label}.fields[{index}]"
    value = _mapping(raw, label)
    _reject_contract_keys(value, _CONTRACT_FIELD_KEYS, label)
    name = _required_text(value["name"], f"{label}.name")
    if _SAFE_IDENTIFIER.fullmatch(name) is None:
        raise ValueError(f"{label}.name must use the provider field grammar")
    logical_type = _required_text(value["logical_type"], f"{label}.logical_type")
    if logical_type not in _LOGICAL_TYPES:
        raise ValueError(f"{label}.logical_type is unsupported")
    return {
        "name": name,
        "declared_source_type": _required_text(
            value["declared_source_type"], f"{label}.declared_source_type"
        ),
        "logical_type": logical_type,
        "nullable": _required_bool(value["nullable"], f"{label}.nullable"),
        "selectable": _required_bool(value["selectable"], f"{label}.selectable"),
        "filterable": _required_bool(value["filterable"], f"{label}.filterable"),
        "sortable": _required_bool(value["sortable"], f"{label}.sortable"),
    }


def _request_template_contract(raw: object, label: str) -> dict[str, str]:
    value = _mapping(raw, label)
    normalized: dict[str, str] = {}
    for raw_key in sorted(value, key=str):
        key = _required_text(raw_key, f"{label} key")
        if _SAFE_IDENTIFIER.fullmatch(key) is None:
            raise ValueError(f"{label} key must use the provider field grammar")
        template_value = value[raw_key]
        if not isinstance(template_value, str) or not template_value:
            raise ValueError(f"{label}.{key} must be a non-empty string")
        if any(ord(character) < 32 for character in template_value):
            raise ValueError(f"{label}.{key} must not contain control characters")
        if "${" in template_value and _WINDOW_PLACEHOLDER.fullmatch(template_value) is None:
            raise ValueError(f"{label}.{key} has an invalid window placeholder")
        normalized[key] = template_value
    return normalized


def _request_variants_contract(
    raw: object,
    *,
    request_template: Mapping[str, str],
    label: str,
) -> list[dict[str, str]]:
    values = _sequence(raw, label)
    if not values:
        raise ValueError(f"{label} must not be empty")
    normalized: list[dict[str, str]] = []
    expected_keys: frozenset[str] | None = None
    seen: set[tuple[tuple[str, str], ...]] = set()
    for index, raw_variant in enumerate(values):
        value = _mapping(raw_variant, f"{label}[{index}]")
        variant: dict[str, str] = {}
        for raw_key in sorted(value, key=str):
            key = _required_text(raw_key, f"{label}[{index}] key")
            if _SAFE_IDENTIFIER.fullmatch(key) is None:
                raise ValueError(f"{label}[{index}] key must use provider grammar")
            if key not in request_template:
                raise ValueError(
                    f"{label}[{index}].{key} is missing from request_template"
                )
            if _WINDOW_PLACEHOLDER.fullmatch(request_template[key]):
                raise ValueError(
                    f"{label}[{index}].{key} cannot override a window placeholder"
                )
            item = _required_text(value[raw_key], f"{label}[{index}].{key}")
            if any(ord(character) < 32 for character in item) or "${" in item:
                raise ValueError(f"{label}[{index}].{key} must be a concrete value")
            variant[key] = item
        keys = frozenset(variant)
        if not keys:
            if len(values) != 1:
                raise ValueError(f"{label} empty variant must be the only variant")
        elif expected_keys is None:
            expected_keys = keys
        elif keys != expected_keys:
            raise ValueError(f"{label} variants must use the same keys")
        identity = tuple(sorted(variant.items()))
        if identity in seen:
            raise ValueError(f"{label} contains a duplicate variant")
        seen.add(identity)
        normalized.append(dict(identity))
    if expected_keys is not None:
        template_default = tuple(
            sorted((key, request_template[key]) for key in expected_keys)
        )
        if template_default not in seen:
            raise ValueError(f"{label} must include the request_template default")
    return normalized


def _window_policy_contract(
    raw: object,
    *,
    request_template: Mapping[str, str],
    label: str,
) -> dict[str, Any] | None:
    if raw is None:
        return None
    value = _mapping(raw, label)
    _reject_contract_keys(value, _WINDOW_POLICY_KEYS, label)
    required_keys = _required_string_list(value["required_keys"], f"{label}.required_keys")
    formats_value = _mapping(value["formats"], f"{label}.formats")
    formats = {
        _required_text(key, f"{label}.formats key"): _required_text(
            item, f"{label}.formats.{key}"
        )
        for key, item in formats_value.items()
    }
    if set(formats) != set(required_keys):
        raise ValueError(f"{label}.formats keys must exactly equal required_keys")
    if set(formats.values()) != {"yyyymmdd"}:
        raise ValueError(f"{label}.formats only supports yyyymmdd")
    placeholders = [
        match.group(1)
        for template_value in request_template.values()
        if (match := _WINDOW_PLACEHOLDER.fullmatch(template_value)) is not None
    ]
    if len(placeholders) != len(set(placeholders)) or set(placeholders) != set(
        required_keys
    ):
        raise ValueError(
            f"{label} request_template placeholders must exactly equal required_keys"
        )
    start_key = _required_text(value["range_start_key"], f"{label}.range_start_key")
    end_key = _required_text(value["range_end_key"], f"{label}.range_end_key")
    max_span_days = _required_positive_int(
        value["max_span_days"], f"{label}.max_span_days"
    )
    if start_key == end_key and not (
        required_keys == [start_key] and max_span_days == 1
    ):
        raise ValueError(
            f"{label} range keys must be distinct declared required_keys unless one "
            "key has max_span_days=1"
        )
    if {start_key, end_key} - set(required_keys):
        raise ValueError(f"{label} range keys must be declared required_keys")
    return {
        "required_keys": required_keys,
        "formats": dict(sorted(formats.items())),
        "range_start_key": start_key,
        "range_end_key": end_key,
        "max_span_days": max_span_days,
    }


def _response_completeness_contract(
    raw: object,
    *,
    fields_by_name: Mapping[str, Mapping[str, Any]],
    request_template: Mapping[str, str],
    window_policy: Mapping[str, Any] | None,
    as_of_field: str | None,
    as_of_format: str | None,
    label: str,
) -> dict[str, Any]:
    value = _mapping(raw, label)
    strategy = _required_text(value["strategy"], f"{label}.strategy")
    if strategy not in _RESPONSE_COMPLETENESS_STRATEGIES:
        raise ValueError(f"{label}.strategy is unsupported")
    required_keys = {
        "one_row_per_calendar_date": {
            "strategy",
            "date_field",
            "request_start_key",
            "request_end_key",
            "fixed_field_matches",
        },
        "unique_primary_key_snapshot": {
            "strategy",
            "fixed_field_matches",
            "reject_at_row_limit",
        },
        "single_partition_unique_primary_key": {
            "strategy",
            "partition_field",
            "request_partition_key",
            "fixed_field_matches",
            "reject_at_row_limit",
        },
    }[strategy]
    allowed_keys = set(required_keys)
    if strategy == "one_row_per_calendar_date":
        allowed_keys.add("reject_at_row_limit")
    _reject_contract_keys(value, frozenset(allowed_keys), label, required=frozenset(required_keys))
    reject_at_row_limit = _required_bool(
        value.get("reject_at_row_limit", False), f"{label}.reject_at_row_limit"
    )

    date_field: str | None = None
    request_start_key: str | None = None
    request_end_key: str | None = None
    partition_field: str | None = None
    request_partition_key: str | None = None
    if strategy == "one_row_per_calendar_date":
        date_field = _required_text(value["date_field"], f"{label}.date_field")
        request_start_key = _required_text(
            value["request_start_key"], f"{label}.request_start_key"
        )
        request_end_key = _required_text(
            value["request_end_key"], f"{label}.request_end_key"
        )
        if window_policy is None:
            raise ValueError(f"{label} requires request_window_policy")
        if request_start_key != window_policy["range_start_key"]:
            raise ValueError(f"{label}.request_start_key must equal the window range start")
        if request_end_key != window_policy["range_end_key"]:
            raise ValueError(f"{label}.request_end_key must equal the window range end")
    elif strategy == "unique_primary_key_snapshot":
        if window_policy is not None:
            raise ValueError(f"{label}.unique_primary_key_snapshot must not use request_window_policy")
    else:
        partition_field = _required_text(
            value["partition_field"], f"{label}.partition_field"
        )
        request_partition_key = _required_text(
            value["request_partition_key"], f"{label}.request_partition_key"
        )
        if window_policy is None:
            raise ValueError(f"{label} requires request_window_policy")
        if (
            window_policy["required_keys"] != [request_partition_key]
            or window_policy["range_start_key"] != request_partition_key
            or window_policy["range_end_key"] != request_partition_key
            or window_policy["max_span_days"] != 1
        ):
            raise ValueError(
                f"{label}.single_partition_unique_primary_key requires one "
                "max_span_days=1 request window key"
            )

    raw_matches = _mapping(
        value["fixed_field_matches"], f"{label}.fixed_field_matches"
    )
    fixed_field_matches: dict[str, str] = {}
    for raw_field, raw_param in raw_matches.items():
        field_name = _required_text(
            raw_field, f"{label}.fixed_field_matches row field"
        )
        param_name = _required_text(
            raw_param, f"{label}.fixed_field_matches.{field_name}"
        )
        if _SAFE_IDENTIFIER.fullmatch(field_name) is None:
            raise ValueError(
                f"{label}.fixed_field_matches row field must use provider grammar"
            )
        if _SAFE_IDENTIFIER.fullmatch(param_name) is None:
            raise ValueError(
                f"{label}.fixed_field_matches target must use provider grammar"
            )
        if field_name not in fields_by_name:
            raise ValueError(
                f"{label}.fixed_field_matches references undeclared field: {field_name}"
            )
        if param_name not in request_template:
            raise ValueError(
                f"{label}.fixed_field_matches target is missing from request_template: "
                f"{param_name}"
            )
        fixed_field_matches[field_name] = param_name
    normalized = {
        "strategy": strategy,
        "fixed_field_matches": dict(sorted(fixed_field_matches.items())),
        "reject_at_row_limit": reject_at_row_limit,
    }
    if strategy == "one_row_per_calendar_date":
        normalized.update(
            {
                "date_field": date_field,
                "request_start_key": request_start_key,
                "request_end_key": request_end_key,
            }
        )
    elif strategy == "single_partition_unique_primary_key":
        normalized.update(
            {
                "partition_field": partition_field,
                "request_partition_key": request_partition_key,
            }
        )
    return normalized


def _normalized_contract(raw: object, *, index: int, provider: str) -> dict[str, Any]:
    label = f"upstream contracts[{index}]"
    value = _mapping(raw, label)
    _reject_contract_keys(value, _CONTRACT_KEYS, label, required=_CONTRACT_REQUIRED_KEYS)
    dataset_id = _required_text(value["dataset_id"], f"{label}.dataset_id")
    contract_provider = _required_text(value["provider"], f"{label}.provider")
    if contract_provider != provider:
        raise ValueError(f"{label}.provider must match bundle provider")
    api_name = _required_text(value["api_name"], f"{label}.api_name")
    if _SAFE_IDENTIFIER.fullmatch(api_name) is None:
        raise ValueError(f"{label}.api_name must use the provider API grammar")
    source_hash = _required_text(
        value["source_document_sha256"], f"{label}.source_document_sha256"
    )
    if _HASH_PATTERN.fullmatch(source_hash) is None:
        raise ValueError(f"{label}.source_document_sha256 must be SHA-256")
    schema_version = _required_text(value["schema_version"], f"{label}.schema_version")
    if _SCHEMA_VERSION_PATTERN.fullmatch(schema_version) is None:
        raise ValueError(f"{label}.schema_version must use MAJOR.MINOR.PATCH")

    raw_fields = _sequence(value["fields"], f"{label}.fields")
    if not raw_fields:
        raise ValueError(f"{label}.fields must not be empty")
    fields = [
        _declared_field(field, contract_label=label, index=field_index)
        for field_index, field in enumerate(raw_fields)
    ]
    field_names = [field["name"] for field in fields]
    if len(field_names) != len(set(field_names)):
        raise ValueError(f"{label}.fields contains duplicate field names")
    fields_by_name = {field["name"]: field for field in fields}

    primary_key = _required_string_list(value["primary_key"], f"{label}.primary_key")
    default_projection = _required_string_list(
        value["default_projection"], f"{label}.default_projection"
    )
    for key_name, names in (
        ("primary_key", primary_key),
        ("default_projection", default_projection),
    ):
        undeclared = sorted(set(names) - set(fields_by_name))
        if undeclared:
            raise ValueError(
                f"{label}.{key_name} references undeclared field(s): {', '.join(undeclared)}"
            )
    if any(fields_by_name[name]["nullable"] for name in primary_key):
        raise ValueError(f"{label}.primary_key fields must not be nullable")

    optional_fields: dict[str, str | None] = {}
    for key in ("as_of_field", "range_field", "partition_field"):
        raw_name = value[key]
        name = None if raw_name is None else _required_text(raw_name, f"{label}.{key}")
        if name is not None and name not in fields_by_name:
            raise ValueError(f"{label}.{key} references undeclared field: {name}")
        optional_fields[key] = name
    as_of_format = value["as_of_format"]
    if optional_fields["as_of_field"] is None:
        if as_of_format is not None:
            raise ValueError(f"{label}.as_of_format requires as_of_field")
    else:
        as_of_format = _required_text(as_of_format, f"{label}.as_of_format")
        if as_of_format not in _AS_OF_FORMATS:
            raise ValueError(f"{label}.as_of_format is unsupported")

    request_template = _request_template_contract(
        value["request_template"], f"{label}.request_template"
    )
    request_variants = _request_variants_contract(
        value["request_variants"],
        request_template=request_template,
        label=f"{label}.request_variants",
    )
    window_policy = _window_policy_contract(
        value.get("request_window_policy"),
        request_template=request_template,
        label=f"{label}.request_window_policy",
    )
    response_completeness = _response_completeness_contract(
        value["response_completeness"],
        fields_by_name=fields_by_name,
        request_template=request_template,
        window_policy=window_policy,
        as_of_field=optional_fields["as_of_field"],
        as_of_format=as_of_format,
        label=f"{label}.response_completeness",
    )
    requested_fields = _required_string_list(
        value["requested_fields"],
        f"{label}.requested_fields",
        allow_empty=True,
    )
    undeclared_requested = sorted(set(requested_fields) - set(fields_by_name))
    if undeclared_requested:
        raise ValueError(
            f"{label}.requested_fields references undeclared field(s): "
            f"{', '.join(undeclared_requested)}"
        )

    empty_data_policy = _required_text(
        value["empty_data_policy"], f"{label}.empty_data_policy"
    )
    if (
        response_completeness["strategy"] == "one_row_per_calendar_date"
        and empty_data_policy != "forbidden"
    ):
        raise ValueError(
            f"{label}.empty_data_policy must be forbidden for "
            "one_row_per_calendar_date"
        )

    for fixed_field in response_completeness["fixed_field_matches"]:
        field_contract = fields_by_name[fixed_field]
        if field_contract["logical_type"] != "text" or field_contract["nullable"]:
            raise ValueError(
                f"{label}.response_completeness.fixed_field_matches fields must be "
                "non-null text"
            )
    completeness_key_fields = set(primary_key) | set(
        response_completeness["fixed_field_matches"]
    )
    if response_completeness["strategy"] == "one_row_per_calendar_date":
        date_field = response_completeness["date_field"]
        if date_field not in fields_by_name:
            raise ValueError(
                f"{label}.response_completeness.date_field is undeclared: {date_field}"
            )
        if optional_fields["as_of_field"] != date_field or as_of_format != "yyyymmdd":
            raise ValueError(
                f"{label}.response_completeness.date_field must be the contract "
                "yyyymmdd as_of_field"
            )
        if {
            optional_fields["range_field"],
            optional_fields["partition_field"],
        } != {date_field}:
            raise ValueError(
                f"{label}.response_completeness requires as_of/range/partition to "
                "equal date_field"
            )
        completeness_date_field = fields_by_name[date_field]
        if (
            completeness_date_field["logical_type"] != "text"
            or completeness_date_field["nullable"]
        ):
            raise ValueError(
                f"{label}.response_completeness.date_field must be non-null text"
            )
        calendar_key_fields = {
            date_field,
            *response_completeness["fixed_field_matches"],
        }
        if set(primary_key) != calendar_key_fields:
            raise ValueError(
                f"{label}.primary_key must exactly contain completeness date_field "
                "and fixed row fields"
            )
    elif response_completeness["strategy"] == "single_partition_unique_primary_key":
        partition_field = response_completeness["partition_field"]
        if partition_field not in fields_by_name:
            raise ValueError(
                f"{label}.response_completeness.partition_field is undeclared: "
                f"{partition_field}"
            )
        if (
            optional_fields["as_of_field"] != partition_field
            or optional_fields["range_field"] != partition_field
            or optional_fields["partition_field"] != partition_field
            or as_of_format != "yyyymmdd"
        ):
            raise ValueError(
                f"{label}.response_completeness.partition_field must be the "
                "contract yyyymmdd as_of/range/partition field"
            )
        partition_contract = fields_by_name[partition_field]
        if (
            partition_contract["logical_type"] != "text"
            or partition_contract["nullable"]
        ):
            raise ValueError(
                f"{label}.response_completeness.partition_field must be non-null text"
            )
        if partition_field not in primary_key:
            raise ValueError(
                f"{label}.response_completeness.partition_field must be in "
                "primary_key"
            )
        completeness_key_fields.add(partition_field)
    if requested_fields:
        missing_completeness_fields = sorted(
            completeness_key_fields - set(requested_fields)
        )
        if missing_completeness_fields:
            raise ValueError(
                f"{label}.requested_fields must include completeness field(s): "
                f"{', '.join(missing_completeness_fields)}"
            )

    budgets_value = _mapping(value["budgets"], f"{label}.budgets")
    _reject_contract_keys(budgets_value, _BUDGET_KEYS, f"{label}.budgets")
    budgets = {
        key: _required_positive_int(budgets_value[key], f"{label}.budgets.{key}")
        for key in sorted(_BUDGET_KEYS)
    }
    if (
        window_policy is not None
        and budgets["max_rows_per_attempt"] < window_policy["max_span_days"]
    ):
        raise ValueError(
            f"{label}.budgets.max_rows_per_attempt must be >= "
            "request_window_policy.max_span_days"
        )

    overrides: list[dict[str, str]] = []
    override_fields: set[str] = set()
    for override_index, raw_override in enumerate(
        _sequence(value["reviewed_type_overrides"], f"{label}.reviewed_type_overrides")
    ):
        override_label = f"{label}.reviewed_type_overrides[{override_index}]"
        override = _mapping(raw_override, override_label)
        _reject_contract_keys(override, _TYPE_OVERRIDE_KEYS, override_label)
        normalized = {
            key: _required_text(override[key], f"{override_label}.{key}")
            for key in sorted(_TYPE_OVERRIDE_KEYS)
        }
        field_name = normalized["field"]
        if field_name not in fields_by_name:
            raise ValueError(f"{override_label}.field is undeclared")
        if field_name in override_fields:
            raise ValueError(f"{label} has duplicate type override for {field_name}")
        field = fields_by_name[field_name]
        if normalized["declared_source_type"] != field["declared_source_type"]:
            raise ValueError(f"{override_label} declared source type does not match field")
        if normalized["logical_type"] != field["logical_type"]:
            raise ValueError(f"{override_label} logical type does not match field")
        override_fields.add(field_name)
        overrides.append(normalized)

    declared_default_types = {"str": "text", "int": "integer", "float": "float"}
    for field in fields:
        expected = declared_default_types.get(field["declared_source_type"])
        if expected is not None and field["logical_type"] != expected:
            if field["name"] not in override_fields:
                raise ValueError(
                    f"{label}.fields {field['name']} changes declared type without reviewed override"
                )

    point_in_time = _required_text(value["point_in_time"], f"{label}.point_in_time")
    if point_in_time not in {"current_snapshot", "append_only"}:
        raise ValueError(f"{label}.point_in_time is unsupported")
    return {
        "dataset_id": dataset_id,
        "provider": contract_provider,
        "api_name": api_name,
        "source_document_url": _required_text(
            value["source_document_url"], f"{label}.source_document_url"
        ),
        "source_document_sha256": source_hash,
        "schema_version": schema_version,
        "fields": fields,
        "primary_key": primary_key,
        "default_projection": default_projection,
        **optional_fields,
        "as_of_format": as_of_format,
        "cadence_class": _required_text(
            value["cadence_class"], f"{label}.cadence_class"
        ),
        "point_in_time": point_in_time,
        "backfill_policy": _required_text(
            value["backfill_policy"], f"{label}.backfill_policy"
        ),
        "empty_data_policy": empty_data_policy,
        "required_scope": _required_text(
            value["required_scope"], f"{label}.required_scope"
        ),
        "quota_class": _required_text(value["quota_class"], f"{label}.quota_class"),
        "request_template": request_template,
        "request_variants": request_variants,
        "request_window_policy": window_policy,
        "response_completeness": response_completeness,
        "requested_fields": requested_fields,
        "budgets": budgets,
        "reviewed_type_overrides": overrides,
    }


def load_upstream_contract_bundle(document: Mapping[str, Any]) -> dict[str, Any]:
    """Strictly normalize one pinned upstream contract bundle."""

    root = _mapping(deepcopy(document), "upstream contract bundle")
    _reject_contract_keys(root, _ROOT_CONTRACT_KEYS, "upstream contract bundle")
    if root["version"] != 1 or isinstance(root["version"], bool):
        raise ValueError("upstream contract bundle.version must be integer 1")
    provider = _required_text(root["provider"], "upstream contract bundle.provider")
    if provider != PROVIDER:
        raise ValueError(f"upstream contract bundle.provider must be {PROVIDER}")
    provenance = _mapping(root["provenance"], "upstream contract bundle.provenance")
    _reject_contract_keys(
        provenance,
        _PROVENANCE_KEYS,
        "upstream contract bundle.provenance",
    )
    normalized_provenance = {
        key: _required_text(provenance[key], f"upstream contract bundle.provenance.{key}")
        for key in sorted(_PROVENANCE_KEYS)
    }
    if _COMMIT_PATTERN.fullmatch(normalized_provenance["pinned_commit"]) is None:
        raise ValueError("upstream contract bundle provenance commit must be a git SHA")
    if _HASH_PATTERN.fullmatch(normalized_provenance["index_sha256"]) is None:
        raise ValueError("upstream contract bundle provenance index must be SHA-256")

    contracts = [
        _normalized_contract(contract, index=index, provider=provider)
        for index, contract in enumerate(
            _sequence(root["contracts"], "upstream contract bundle.contracts")
        )
    ]
    by_dataset: dict[str, dict[str, Any]] = {}
    by_api: dict[str, str] = {}
    for contract in contracts:
        dataset_id = contract["dataset_id"]
        api_name = contract["api_name"]
        if dataset_id in by_dataset:
            raise ValueError(f"duplicate dataset_id in upstream contracts: {dataset_id}")
        if api_name in by_api:
            raise ValueError(
                f"duplicate provider API in upstream contracts: {api_name} "
                f"({by_api[api_name]}, {dataset_id})"
            )
        by_dataset[dataset_id] = contract
        by_api[api_name] = dataset_id
    return {
        "version": 1,
        "bundle_id": _required_text(
            root["bundle_id"], "upstream contract bundle.bundle_id"
        ),
        "provider": provider,
        "provenance": normalized_provenance,
        "contracts": [by_dataset[key] for key in sorted(by_dataset)],
    }


def compile_provider_native_registry(
    registry_document: Mapping[str, Any],
    capability_plan: Mapping[str, Any],
    collector_config: Mapping[str, Any],
    upstream_contracts: Mapping[str, Any],
    *,
    activation_document: Mapping[str, Any] | None = None,
    source_sha256: Mapping[str, str] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return a deterministic candidate registry and fail-closed report."""

    source_registry = _mapping(deepcopy(registry_document), "registry")
    datasets = _sequence(source_registry.get("datasets"), "registry.datasets")
    normalized_bundle = load_upstream_contract_bundle(upstream_contracts)
    activation_index = _activation_index(activation_document)
    contract_index = {
        contract["dataset_id"]: contract for contract in normalized_bundle["contracts"]
    }
    candidate: dict[str, Any] = {
        "version": deepcopy(source_registry.get("version")),
        "query_defaults": deepcopy(source_registry.get("query_defaults")),
        "datasets": [],
    }
    plan_index, global_conflicts = _plan_index(capability_plan)
    collector_index, collector_conflicts = _collector_index(collector_config)
    global_conflicts.extend(collector_conflicts)

    registry_api_names: set[str] = set()
    registry_dataset_ids: set[str] = set()
    resolved: list[dict[str, object]] = []
    unresolved: list[dict[str, object]] = []
    conflicts: list[dict[str, object]] = list(global_conflicts)

    for dataset_index, raw_dataset in enumerate(datasets):
        if not isinstance(raw_dataset, dict):
            conflicts.append(
                {
                    "code": "invalid_registry_dataset",
                    "api_name": None,
                    "details": [f"datasets[{dataset_index}] must be a mapping"],
                }
            )
            continue
        dataset_id = _non_empty_text(raw_dataset.get("dataset_id")) or (
            f"datasets[{dataset_index}]"
        )
        registry_dataset_ids.add(dataset_id)
        raw_bindings = raw_dataset.get("provider_bindings", [])
        bindings = raw_bindings if isinstance(raw_bindings, list) else []
        tushare_bindings = [
            binding
            for binding in bindings
            if isinstance(binding, dict) and binding.get("provider") == PROVIDER
        ]
        api_name = (
            _non_empty_text(tushare_bindings[0].get("api_name"))
            if len(tushare_bindings) == 1
            else None
        )
        if api_name is not None:
            registry_api_names.add(api_name)

        contract = contract_index.get(dataset_id)
        if contract is None:
            unresolved.append(
                {
                    "dataset_id": dataset_id,
                    "api_name": api_name,
                    "reason_codes": ["missing_upstream_contract"],
                }
            )
            continue
        reasons: list[dict[str, object]] = []
        if len(tushare_bindings) != 1:
            _append_reason(
                reasons,
                "missing_or_duplicate_tushare_binding",
                [f"count={len(tushare_bindings)}"],
            )
        if any(
            isinstance(binding, dict) and binding.get("provider") != PROVIDER
            for binding in bindings
        ):
            _append_reason(
                reasons,
                "additional_provider_binding",
                sorted(
                    str(binding.get("provider"))
                    for binding in bindings
                    if isinstance(binding, dict) and binding.get("provider") != PROVIDER
                ),
            )

        plan_rows = plan_index.get(api_name or "", [])
        config_rows = collector_index.get(api_name or "", [])
        if api_name is not None:
            if contract["provider"] != PROVIDER or contract["api_name"] != api_name:
                _append_reason(
                    reasons,
                    "upstream_contract_binding_mismatch",
                    [
                        f"registry={PROVIDER}/{api_name}",
                        f"contract={contract['provider']}/{contract['api_name']}",
                    ],
                )

        if reasons:
            reason_codes = sorted({str(reason["code"]) for reason in reasons})
            unresolved.append(
                {
                    "dataset_id": dataset_id,
                    "api_name": api_name,
                    "reason_codes": reason_codes,
                }
            )
            for reason in sorted(reasons, key=lambda item: str(item["code"])):
                if reason["code"] == "missing_upstream_contract":
                    continue
                conflicts.append(
                    {
                        "code": reason["code"],
                        "dataset_id": dataset_id,
                        "api_name": api_name,
                        "details": reason["details"],
                    }
                )
            continue

        assert api_name is not None
        compiled_dataset = deepcopy(raw_dataset)
        for key in (
            "schema_profile",
            "fields",
            "primary_key",
            "default_projection",
            "as_of_field",
            "as_of_format",
            "range_field",
            "partition_field",
            "max_page_size",
            "max_lookback_days",
            "point_in_time",
            "backfill_policy",
            "empty_data_policy",
            "required_scope",
            "quota_class",
        ):
            compiled_dataset.pop(key, None)
        compiled_dataset.update(
            {
                "schema_version": contract["schema_version"],
                "fields": [
                    {
                        key: field[key]
                        for key in (
                            "name",
                            "logical_type",
                            "nullable",
                            "selectable",
                            "filterable",
                            "sortable",
                        )
                    }
                    for field in contract["fields"]
                ],
                "primary_key": contract["primary_key"],
                "default_projection": contract["default_projection"],
                "as_of_field": contract["as_of_field"],
                "as_of_format": contract["as_of_format"],
                "range_field": contract["range_field"],
                "partition_field": contract["partition_field"],
                "cadence_class": contract["cadence_class"],
                "point_in_time": contract["point_in_time"],
                "backfill_policy": contract["backfill_policy"],
                "empty_data_policy": contract["empty_data_policy"],
                "required_scope": contract["required_scope"],
                "quota_class": contract["quota_class"],
            }
        )
        binding = deepcopy(tushare_bindings[0])
        activation = activation_index.get((dataset_id, PROVIDER))
        binding["entitlement_state"] = (
            "unknown" if activation is None else activation["entitlement_state"]
        )
        binding["activation_state"] = (
            "paused" if activation is None else activation["activation_state"]
        )
        binding["adapter_version"] = PROVIDER_ADAPTER_VERSION
        binding["target_tables"] = [PROVIDER_NATIVE_TABLE]
        binding["request_template"] = contract["request_template"]
        binding["request_variants"] = contract["request_variants"]
        binding["request_window_policy"] = contract["request_window_policy"]
        binding["response_completeness"] = contract["response_completeness"]
        binding["requested_fields"] = contract["requested_fields"]
        binding.update(contract["budgets"])
        compiled_dataset["provider_bindings"] = [binding]
        row_key_strategy = {
            "current_snapshot": "primary_key",
            "append_only": "payload_hash",
        }[contract["point_in_time"]]
        compiled_dataset["read_model_adapter"] = {
            "adapter_version": READ_ADAPTER_VERSION,
            "primary_table": PROVIDER_NATIVE_TABLE,
            "fixed_field_filters": [],
            "storage_kind": "provider_native_rows",
            "row_key_strategy": row_key_strategy,
        }
        candidate["datasets"].append(compiled_dataset)
        plan_row = plan_rows[0] if len(plan_rows) == 1 else None
        config_row = config_rows[0] if len(config_rows) == 1 else None
        resolved.append(
            {
                "dataset_id": dataset_id,
                "api_name": api_name,
                "mode": None if plan_row is None else plan_row.get("mode"),
                "cadence": contract["cadence_class"],
                "tier": None if config_row is None else config_row.get("compiler_tier"),
                "requested_fields_source": "upstream_all"
                if not contract["requested_fields"]
                else "reviewed_projection",
                "requested_fields_count": len(contract["requested_fields"]),
                "source_document_sha256": contract["source_document_sha256"],
                "reviewed_type_overrides": sorted(
                    override["field"]
                    for override in contract["reviewed_type_overrides"]
                ),
                "request_window_fields": []
                if contract["request_window_policy"] is None
                else list(contract["request_window_policy"]["required_keys"]),
                "response_completeness_strategy": contract[
                    "response_completeness"
                ]["strategy"],
                "activation_evidence_ref": None
                if activation is None
                else activation["evidence_ref"],
            }
        )

    compiled_activation_keys = {
        (dataset["dataset_id"], binding["provider"])
        for dataset in candidate["datasets"]
        for binding in dataset["provider_bindings"]
    }
    unknown_activation_keys = sorted(set(activation_index) - compiled_activation_keys)
    if unknown_activation_keys:
        targets = ", ".join(
            f"{dataset_id}/{provider}"
            for dataset_id, provider in unknown_activation_keys
        )
        raise ValueError(f"unknown activation target(s): {targets}")

    for api_name in sorted(set(plan_index) - registry_api_names):
        conflicts.append(
            {
                "code": "capability_api_without_registry",
                "dataset_id": None,
                "api_name": api_name,
                "details": [],
            }
        )
    for api_name in sorted(set(collector_index) - registry_api_names):
        conflicts.append(
            {
                "code": "collector_api_without_registry",
                "dataset_id": None,
                "api_name": api_name,
                "details": [],
            }
        )
    for dataset_id in sorted(set(contract_index) - registry_dataset_ids):
        contract = contract_index[dataset_id]
        conflicts.append(
            {
                "code": "upstream_contract_without_registry_owner",
                "dataset_id": None,
                "api_name": contract["api_name"],
                "details": [dataset_id],
            }
        )

    conflicts.sort(
        key=lambda item: (
            str(item.get("dataset_id") or ""),
            str(item.get("api_name") or ""),
            str(item.get("code") or ""),
            tuple(str(detail) for detail in item.get("details", [])),
        )
    )
    report: dict[str, Any] = {
        "report_version": 3,
        "compiler_contract": "provider-native-registry-compiler.v3",
        "sources": dict(sorted((source_sha256 or {}).items())),
        "upstream_contract_bundle": {
            "bundle_id": normalized_bundle["bundle_id"],
            "provider": normalized_bundle["provider"],
            "provenance": normalized_bundle["provenance"],
        },
        "budget_policy": {
            "source": "upstream_contract_bundle.contracts[].budgets",
            "missing_or_invalid": "unresolved",
        },
        "totals": {
            "registry_datasets": len(datasets),
            "converted_datasets": len(resolved),
            "unresolved_datasets": len(unresolved),
            "conflict_records": len(conflicts),
            "global_conflicts": sum(
                1 for conflict in conflicts if conflict.get("dataset_id") is None
            ),
        },
        "resolved": resolved,
        "unresolved": unresolved,
        "conflicts": conflicts,
    }
    return candidate, report


def render_compilation(
    candidate: Mapping[str, Any], report: Mapping[str, Any], *, kind: str
) -> str:
    """Render one deterministic YAML artifact."""

    if kind == "candidate":
        payload: Mapping[str, Any] = candidate
    elif kind == "report":
        payload = report
    elif kind == "bundle":
        payload = {"candidate_registry": candidate, "report": report}
    else:
        raise ValueError("output kind must be bundle, candidate, or report")
    return yaml.safe_dump(
        dict(payload),
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=False,
        width=100,
    )


def _load_yaml(path: Path, label: str) -> dict[str, Any]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return _mapping(raw, label)


class _DuplicateKeySafeLoader(yaml.SafeLoader):
    pass


def _construct_unique_mapping(
    loader: yaml.SafeLoader,
    node: yaml.MappingNode,
    deep: bool = False,
) -> dict[object, object]:
    loader.flatten_mapping(node)
    mapping: dict[object, object] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        try:
            duplicate = key in mapping
        except TypeError as exc:
            raise ValueError("activation YAML mapping key must be hashable") from exc
        if duplicate:
            raise ValueError(f"duplicate YAML mapping key in activation manifest: {key}")
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_DuplicateKeySafeLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)


def _load_activation_yaml(path: Path) -> dict[str, Any]:
    raw = yaml.load(
        path.read_text(encoding="utf-8"),
        Loader=_DuplicateKeySafeLoader,
    )
    return _mapping(raw, "activation manifest")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _atomic_write(path: Path, content: str) -> None:
    parent = path.parent
    if not parent.is_dir():
        raise ValueError(f"output parent does not exist: {parent}")
    descriptor, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=parent)
    temp_path = Path(temp_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    finally:
        temp_path.unlink(missing_ok=True)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY_PATH)
    parser.add_argument(
        "--capability-plan", type=Path, default=DEFAULT_CAPABILITY_PLAN_PATH
    )
    parser.add_argument(
        "--collector-config", type=Path, default=DEFAULT_COLLECTOR_CONFIG_PATH
    )
    parser.add_argument(
        "--upstream-contracts",
        type=Path,
        default=DEFAULT_UPSTREAM_CONTRACTS_PATH,
    )
    parser.add_argument(
        "--kind",
        choices=("bundle", "candidate", "report"),
        default="bundle",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="write only this explicit path; stdout is the default",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    input_paths = (
        args.registry,
        args.capability_plan,
        args.collector_config,
        args.upstream_contracts,
        DEFAULT_ACTIVATION_PATH,
    )
    for path in input_paths:
        if not path.is_file():
            parser.error(f"input file does not exist: {path}")
    if args.output is not None:
        output_resolved = args.output.resolve(strict=False)
        if any(output_resolved == path.resolve() for path in input_paths):
            parser.error("refusing to overwrite an input file")

    source_hashes = {
        "collectors/tushare/config.yaml": _sha256(args.collector_config),
        "config/dataset_registry.yaml": _sha256(args.registry),
        "config/tushare_capability_plan.yaml": _sha256(args.capability_plan),
        "config/tushare_upstream_contracts.v1.yaml": _sha256(
            args.upstream_contracts
        ),
        "config/provider_native_activation.yaml": _sha256(DEFAULT_ACTIVATION_PATH),
    }
    candidate, report = compile_provider_native_registry(
        _load_yaml(args.registry, "registry"),
        _load_yaml(args.capability_plan, "capability plan"),
        _load_yaml(args.collector_config, "collector config"),
        _load_yaml(args.upstream_contracts, "upstream contracts"),
        activation_document=_load_activation_yaml(DEFAULT_ACTIVATION_PATH),
        source_sha256=source_hashes,
    )
    if args.kind in {"candidate", "bundle"}:
        if not candidate["datasets"]:
            parser.error(
                "refusing to render a target candidate with zero resolved contracts"
            )
        if report["totals"]["conflict_records"]:
            parser.error("refusing to render a target candidate with contract conflicts")
    content = render_compilation(candidate, report, kind=args.kind)
    if args.output is None:
        print(content, end="")
    else:
        _atomic_write(args.output, content)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

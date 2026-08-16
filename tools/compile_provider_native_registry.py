#!/usr/bin/env python3
"""Compile reviewed declarations into the provider-native dataset registry.

The compiler is offline, deterministic, and fail closed. Dataset identity,
schema, cadence, request execution, and budgets come only from the pinned
upstream contract bundle plus any explicitly declared supplemental provider
contract bundles (each with its own provider identity and provenance).
Entitlement/activation and reviewed runtime compatibility come only from one
QuickSync observation declaration, which stays scoped to the primary tushare
bundle and never promotes a supplemental contract. Query limits come only
from the explicit query-default declaration.
The only artifact written is the provider-native dataset registry.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import tempfile
from typing import Any, Mapping, Sequence
from zoneinfo import ZoneInfo

import yaml


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_PATH = (
    REPOSITORY_ROOT / "config" / "provider_native_dataset_registry.yaml"
)
DEFAULT_UPSTREAM_CONTRACTS_PATH = (
    REPOSITORY_ROOT / "config" / "tushare_upstream_contracts.v1.yaml"
)
DEFAULT_OBSERVATIONS_PATH = (
    REPOSITORY_ROOT / "config" / "quicksync_interface_observations.v1.yaml"
)
DEFAULT_SUPPLEMENTAL_CONTRACTS_PATHS = (
    REPOSITORY_ROOT / "config" / "firecrawl_upstream_contracts.v1.yaml",
)
FORMAL_COMPILATION_MODE = "formal"
PREACTIVATION_COMPILATION_MODE = "preactivation_candidate"
COMPILATION_MODES = frozenset(
    {FORMAL_COMPILATION_MODE, PREACTIVATION_COMPILATION_MODE}
)

PROVIDER = "tushare"
ASHARE_MARKET_TIMEZONE = ZoneInfo("Asia/Shanghai")
PROVIDER_ADAPTER_VERSION = "tushare-provider-native.v1"
# Additional provider contract bundles compiled into the same single registry.
# Each supplemental bundle keeps its own provider identity and provenance; the
# QuickSync observations/activation evidence below stay scoped to PROVIDER and
# never promote a supplemental contract.
_BUNDLE_PROVIDERS = frozenset({PROVIDER, "firecrawl"})
_PROVIDER_ADAPTER_VERSIONS = {
    PROVIDER: PROVIDER_ADAPTER_VERSION,
    "firecrawl": "firecrawl-web-extraction.v1",
}
READ_ADAPTER_VERSION = "provider-native-json.v1"
PROVIDER_NATIVE_TABLE = "provider_dataset_rows"
DEFAULT_QUERY_DEFAULTS = {
    "max_request_bytes": 65_536,
    "max_response_bytes": 4_194_304,
    "max_page_size": 500,
    "max_lookback_days": 36_500,
    "max_selected_fields": 100,
    "max_filter_terms": 16,
    "max_in_values": 500,
    "max_order_terms": 8,
    "max_catalog_search_chars": 128,
    "cursor_ttl_seconds": 900,
    "sqlite_progress_steps": 1_000_000,
}

_SAFE_PROVIDER_FIELD = re.compile(r"[A-Za-z0-9_]{1,64}")
_SAFE_PARAMETER_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,63}")
_WINDOW_PLACEHOLDER = re.compile(r"\$\{window\.([A-Za-z_][A-Za-z0-9_]{0,63})\}")
_HASH_PATTERN = re.compile(r"[0-9a-f]{64}")
_COMMIT_PATTERN = re.compile(r"[0-9a-f]{40}")
_SCHEMA_VERSION_PATTERN = re.compile(
    r"[1-9][0-9]*\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)"
)
_EVIDENCE_REF_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,255}")
_SENSITIVE_EVIDENCE_PATTERN = re.compile(
    r"(?:secret|token|password|authorization|bearer|credential|api[_-]?key)",
    re.IGNORECASE,
)
_PROVIDER_SCAN_FIELD_HEADROOM = 16
_PROVIDER_SCAN_FIXED_NODE_HEADROOM = 4_096
# The scanner bounds total nodes independently and shrinks the per-attempt row
# limit as a schema widens.  Keep the field ceiling above the largest reviewed
# provider-native schema so a safe wide dataset is not needlessly paused.
_PROVIDER_SCAN_ABSOLUTE_MAX_FIELDS = 512
_PROVIDER_SCAN_ABSOLUTE_MAX_NODES = 2_000_000
_PROVIDER_SCAN_ENVELOPE_DEPTH = 4
_PROVIDER_SCAN_ABSOLUTE_MAX_DEPTH = 64
_ROOT_KEYS = frozenset({"version", "bundle_id", "provider", "provenance", "contracts"})
_PROVENANCE_KEYS = frozenset(
    {"repository_url", "pinned_commit", "index_path", "index_sha256"}
)
_CONTRACT_KEYS = frozenset(
    {
        "dataset_id",
        "aliases",
        "domain",
        "market",
        "entity_type",
        "data_classification",
        "provider",
        "api_name",
        "source_document_url",
        "source_document_sha256",
        "schema_version",
        "input_fields",
        "fields",
        "primary_key",
        "default_projection",
        "as_of_field",
        "as_of_format",
        "range_field",
        "partition_field",
        "cadence_class",
        "timezone",
        "freshness_sla_seconds",
        "known_future_horizon_days",
        "point_in_time",
        "backfill_policy",
        "empty_data_policy",
        "required_scope",
        "quota_class",
        "request_shape",
        "request_template",
        "request_variants",
        "fanout",
        "pagination",
        "request_window_policy",
        "response_completeness",
        "resumable_fanout",
        "requested_fields",
        "budgets",
        "reviewed_type_overrides",
        "probe_state",
        "probe_block_reasons",
        "ingest_contract_state",
        "ingest_contract_block_reasons",
    }
)
_CONTRACT_REQUIRED_KEYS = _CONTRACT_KEYS - {
    "request_window_policy",
    "known_future_horizon_days",
    "resumable_fanout",
}
_FIELD_KEYS = frozenset(
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
_INPUT_FIELD_KEYS = frozenset({"name", "declared_source_type", "required"})
_INPUT_DECLARED_SOURCE_TYPES = frozenset(
    {"None", "datetime", "float", "int", "intint", "str"}
)
_OBSERVATION_ROOT_KEYS = frozenset(
    {
        "version",
        "provider",
        "transport_service",
        "matrix_evidence",
        "classifications",
        "active_evidence",
        "dependency_seed_authorities",
        "response_contract_overrides",
    }
)
_MATRIX_EVIDENCE_KEYS = frozenset(
    {
        "schema_version",
        "sha256",
        "observed_at",
        "api_names_sha256",
        "interface_count",
        "raw_data_persisted",
        "credential_persisted",
        "interface_probe_scheme",
        "production_ready",
        "production_transport_alignment",
    }
)
_CLASSIFICATION_KEYS = frozenset(
    {
        "validated_contract_match",
        "numeric_field_repaired",
        "schema_subset",
        "quality_anomaly",
        "empty",
        "permission_denied",
        "credential_rejected",
        "unsupported",
    }
)
_ENTITLEMENT_STATES = frozenset({"active", "locked", "unknown", "excluded", "retired"})
_ACTIVATION_STATES = frozenset({"active", "paused"})
_FRESH_ACTIVATION_STATES = frozenset({"success", "valid_empty"})
_PROBE_RESULT_STATES = _FRESH_ACTIVATION_STATES | {
    "provider_failed_unclassified",
    "field_contract_mismatch",
}
_PROBE_STATES = frozenset({"executable", "blocked"})
_INGEST_CONTRACT_STATES = frozenset({"ready", "blocked"})
_PROBE_BLOCK_REASONS = frozenset(
    {
        "dependency_seed_receipt_unresolved",
        "official_requiredness_unknown",
        "request_anchor_unresolved",
        "required_enum_unresolved",
        "required_parameter_unresolved",
    }
)
_INGEST_CONTRACT_BLOCK_REASONS = _PROBE_BLOCK_REASONS | {
    "response_completeness_unresolved_at_observed_limit"
}
_REQUEST_WINDOW_FORMATS = frozenset(
    {
        "identity",
        "local_datetime_seconds",
        "rfc3339",
        "yyyy_qn",
        "yyyymm",
        "yyyymmdd",
        "yyyyww",
    }
)
# These formats can be produced deterministically from the shared cadence
# planner.  ``local_datetime_seconds`` deliberately remains manual-window
# only: the planner rejects automatic intraday ranges rather than guessing a
# market session.  Keep this list at the generic request-shape boundary; do
# not add per-dataset activation exceptions.
_AUTOMATIC_REQUEST_WINDOW_FORMATS = frozenset(
    {"yyyymmdd", "yyyymm", "yyyy_qn", "yyyyww"}
)


def _activation_window_is_supported(contract: Mapping[str, Any]) -> bool:
    """Return whether fresh HTTPS evidence may activate this request shape.

    Local datetime windows are deliberately not scheduler inputs. A bounded
    ``on_demand`` event cohort is different: a caller supplies its exact
    window, and the generic collector can validate each literal fanout shard
    against a non-empty event identity. Keep that exception structural, not
    dataset-specific, so it cannot promote a session-minute or open-ended
    local-time contract.
    """

    window = contract["request_window_policy"]
    if window is None:
        return True
    formats = set(window["formats"].values())
    if formats <= _AUTOMATIC_REQUEST_WINDOW_FORMATS:
        return True
    completeness = contract["response_completeness"]
    return (
        contract["cadence_class"] == "on_demand"
        and formats == {"local_datetime_seconds"}
        and bool(contract["primary_key"])
        and contract["fanout"]["strategy"] == "literal_values"
        and completeness is not None
        and completeness["strategy"] == "windowed_unique_primary_key"
    )


_REQUEST_SHAPES = frozenset(
    {
        "snapshot_or_date_range",
        "entity_fanout",
        "dimension_fanout",
        "event_or_intraday_window",
    }
)
_CADENCE_CLASSES = frozenset(
    {
        "session_minute",
        "postclose_daily",
        "daily_reference",
        "weekly",
        "monthly",
        "quarterly_reporting",
        "event",
        "on_demand",
    }
)
_FANOUT_KEYS = frozenset(
    {
        "strategy",
        "parameter",
        "values",
        "source_dataset_id",
        "source_field",
        "batch_size",
        "source_equals",
        "source_date_field",
        "source_date_lte_days",
        "max_values",
        "source_order",
    }
)
_PAGINATION_KEYS = frozenset(
    {"strategy", "limit_parameter", "offset_parameter", "page_size", "max_pages"}
)
_WINDOW_KEYS = frozenset(
    {"required_keys", "formats", "range_start_key", "range_end_key", "max_span_days"}
)
_COMPLETENESS_KEYS = frozenset(
    {
        "strategy",
        "date_field",
        "request_start_key",
        "request_end_key",
        "partition_field",
        "request_partition_key",
        "fanout_field",
        "snapshot_field",
        "fixed_field_matches",
        "reject_at_row_limit",
    }
)
_COMPLETENESS_STRATEGIES = frozenset(
    {
        "one_row_per_calendar_date",
        "unique_primary_key_snapshot",
        "single_partition_unique_primary_key",
        "windowed_unique_primary_key",
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
_OVERRIDE_KEYS = frozenset(
    {
        "field",
        "declared_source_type",
        "observed_json_type",
        "logical_type",
        "reason",
        "evidence",
    }
)
_RESPONSE_CONTRACT_OVERRIDE_KEYS = frozenset(
    {
        "evidence_ref",
        "schema_version",
        "missing_fields",
        "type_overrides",
        "additional_fields",
    }
)
_RESPONSE_TYPE_OVERRIDE_KEYS = frozenset(
    {"field", "declared_source_type", "logical_type"}
)
_ACTIVATION_EVIDENCE_ROOT_KEYS = frozenset(
    {
        "version",
        "provider",
        "transport_service",
        "evidence",
        "seed_authorities",
        "plan_projection",
        "activation_projection",
        "results",
    }
)
_ACTIVATION_EVIDENCE_KEYS = frozenset(
    {
        "schema_version",
        "source_sha256",
        "bindings_sha256",
        "promotion_stage",
        "release_commit",
        "request_plan_sha256",
        "official_contract_sha256",
        "request_observations_sha256",
        "transport_observations_sha256",
        "planned_api_names_sha256",
        "executed_api_names_sha256",
        "results_sha256",
        "started_at",
        "finished_at",
        "run_clock",
        "scheduled_partition",
        "scope",
        "interface_count",
        "coverage",
        "summary",
        "transport",
        "concurrency",
        "rate_budget",
        "response_budget",
        "retries",
        "production_ready",
        "raw_data_persisted",
        "credential_persisted",
        "request_values_persisted",
    }
)
_RAW_PROBE_EVIDENCE_ROOT_KEYS = frozenset(
    {
        "schema_version",
        "production_ready",
        "raw_data_persisted",
        "credential_persisted",
        "request_values_persisted",
        "commit",
        "request_plan_sha256",
        "official_contract_sha256",
        "transport_observations_sha256",
        "request_observations_sha256",
        "api_names_sha256",
        "scheduled_partition",
        "run_clock",
        "seed_authorities",
        "scope",
        "interface_count",
        "coverage",
        "started_at",
        "finished_at",
        "retries",
        "concurrency",
        "rate_budget",
        "response_budget",
        "transport",
        "summary",
        "results",
    }
)
_RAW_PROBE_RESULT_KEYS = frozenset(
    {
        "api_name",
        "state",
        "provider_class",
        "row_count",
        "response_bytes",
        "response_sha256",
        "response_redacted",
        "fields",
        "elapsed_ms",
    }
)
_PROBE_RESULT_KEYS = frozenset(
    {
        "api_name",
        "state",
        "provider_class",
        "row_count",
        "response_bytes",
        "response_sha256",
        "fields",
        "elapsed_ms",
        "result_sha256",
    }
)
_SEED_AUTHORITY_KEYS = frozenset(
    {"dataset_id", "field", "schema_version", "receipt_id", "data_through"}
)
_FORMAL_SEED_AUTHORITY_KEYS = _SEED_AUTHORITY_KEYS | {"dependent_api_names"}
_COUNT_HASH_KEYS = frozenset(
    {"ingest_ready_count", "ingest_ready_api_names_sha256"}
)
_ACTIVATION_PROJECTION_KEYS = frozenset(
    {
        "candidate_count",
        "candidate_api_names_sha256",
        "active_count",
        "active_api_names_sha256",
        "paused_count",
        "paused_api_names_sha256",
    }
)
_COVERAGE_KEYS = frozenset(
    {"blocked", "executable", "executed", "planned", "selected"}
)
_PROBE_SUMMARY_KEYS = frozenset(
    {"success", "valid_empty", "provider_failed_unclassified", "field_contract_mismatch"}
)
_TRANSPORT_KEYS = frozenset({"endpoint_host", "scheme"})
_RATE_BUDGET_KEYS = frozenset(
    {"authorizations", "max_requests", "window_seconds"}
)
_AUTHORIZATION_KEYS = frozenset(
    {
        "active_after_last",
        "active_before_first",
        "authorized",
        "first_authorized_at_epoch",
        "last_authorized_at_epoch",
    }
)
_RESPONSE_BUDGET_KEYS = frozenset(
    {"observed_bytes", "per_call_bytes", "per_run_bytes"}
)
_RECEIPT_ID_PATTERN = re.compile(r"receipt:[0-9a-f]{64}")


def _mapping(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a mapping")
    return value


def _sequence(value: object, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError(f"{label} must be a list")
    return value


def _reject_keys(
    value: Mapping[str, Any],
    allowed: frozenset[str],
    label: str,
    *,
    required: frozenset[str] | None = None,
) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise ValueError(f"{label} has unknown key(s): {', '.join(unknown)}")
    missing = sorted((allowed if required is None else required) - set(value))
    if missing:
        raise ValueError(f"{label} is missing key(s): {', '.join(missing)}")


def _required_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    return value.strip()


def _required_bool(value: object, label: str) -> bool:
    if type(value) is not bool:
        raise ValueError(f"{label} must be a boolean")
    return value


def _required_positive_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{label} must be a positive integer")
    return value


def _required_non_negative_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{label} must be a non-negative integer")
    return value


def _required_finite_number(value: object, label: str) -> int | float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be a finite number")
    if not math.isfinite(value):
        raise ValueError(f"{label} must be a finite number")
    return value


def _required_sha256(value: object, label: str) -> str:
    digest = _required_text(value, label)
    if _HASH_PATTERN.fullmatch(digest) is None:
        raise ValueError(f"{label} must be SHA-256")
    return digest


def _required_rfc3339(value: object, label: str) -> tuple[str, datetime]:
    text = _required_text(value, label)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{label} must be RFC3339") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{label} must include timezone")
    return text, parsed


def _api_names_sha256(api_names: Sequence[str] | set[str]) -> str:
    return hashlib.sha256(
        ("\n".join(sorted(api_names)) + "\n").encode("utf-8")
    ).hexdigest()


def _canonical_json_sha256(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _string_list(value: object, label: str, *, allow_empty: bool = False) -> list[str]:
    values = _sequence(value, label)
    normalized = [
        _required_text(item, f"{label}[{index}]") for index, item in enumerate(values)
    ]
    if not allow_empty and not normalized:
        raise ValueError(f"{label} must not be empty")
    if len(normalized) != len(set(normalized)):
        raise ValueError(f"{label} must not contain duplicates")
    return normalized


def _input_fields(value: object, label: str) -> list[dict[str, Any]]:
    fields = _sequence(value, label)
    if not fields:
        raise ValueError(f"{label} must not be empty")
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, raw_field in enumerate(fields):
        field_label = f"{label}[{index}]"
        field = _mapping(raw_field, field_label)
        _reject_keys(field, _INPUT_FIELD_KEYS, field_label)
        name = _required_text(field["name"], f"{field_label}.name")
        if _SAFE_PARAMETER_NAME.fullmatch(name) is None:
            raise ValueError(f"{field_label}.name must use provider parameter grammar")
        if name in seen:
            raise ValueError(f"{label} contains duplicate name: {name}")
        seen.add(name)
        declared_source_type = _required_text(
            field["declared_source_type"],
            f"{field_label}.declared_source_type",
        )
        if declared_source_type not in _INPUT_DECLARED_SOURCE_TYPES:
            choices = ", ".join(sorted(_INPUT_DECLARED_SOURCE_TYPES))
            raise ValueError(
                f"{field_label}.declared_source_type must be one of: {choices}"
            )
        required = field["required"]
        if required is not None and type(required) is not bool:
            raise ValueError(f"{field_label}.required must be a boolean or null")
        normalized.append(
            {
                "name": name,
                "declared_source_type": declared_source_type,
                "required": required,
            }
        )
    return normalized


def _json_scalar(value: object, label: str) -> str | int | float | bool | None:
    if value is None or type(value) in {str, int, bool}:
        return value
    if type(value) is float and math.isfinite(value):
        return value
    raise ValueError(f"{label} must be a concrete finite JSON scalar")


def _query_defaults(value: Mapping[str, Any] | None) -> dict[str, int]:
    source = DEFAULT_QUERY_DEFAULTS if value is None else value
    declaration = _mapping(deepcopy(source), "query defaults")
    _reject_keys(declaration, frozenset(DEFAULT_QUERY_DEFAULTS), "query defaults")
    return {
        key: _required_positive_int(declaration[key], f"query defaults.{key}")
        for key in DEFAULT_QUERY_DEFAULTS
    }


def _observation_field_map(raw: object, label: str) -> dict[str, list[str]]:
    source = _mapping(raw, label)
    result: dict[str, list[str]] = {}
    for raw_api_name, raw_fields in source.items():
        api_name = _required_text(raw_api_name, f"{label} key")
        if _SAFE_PARAMETER_NAME.fullmatch(api_name) is None:
            raise ValueError(f"{label} key must use provider API grammar")
        fields = _string_list(raw_fields, f"{label}.{api_name}")
        if any(_SAFE_PROVIDER_FIELD.fullmatch(field) is None for field in fields):
            raise ValueError(f"{label}.{api_name} contains an invalid provider field")
        result[api_name] = fields
    return result


def _safe_evidence_ref(value: object, label: str) -> str:
    evidence = _required_text(value, label)
    path = PurePosixPath(evidence)
    if (
        evidence != str(path)
        or path.is_absolute()
        or ".." in path.parts
        or _EVIDENCE_REF_PATTERN.fullmatch(evidence) is None
        or _SENSITIVE_EVIDENCE_PATTERN.search(evidence) is not None
    ):
        raise ValueError(f"{label} must be a non-sensitive relative reference")
    return evidence


def _response_contract_override_index(
    raw: object,
    contracts: Mapping[str, Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Parse small, evidence-bound QuickSync response deltas.

    Official Tushare documents remain the source declaration.  A delta exists
    only when the approved QuickSync transport returns a stable, incompatible
    field subset, type, or additional field.  It cannot alter identity,
    cadence, request mappings, or completeness contracts.
    """

    source = _mapping(raw, "QuickSync observations.response_contract_overrides")
    result: dict[str, dict[str, Any]] = {}
    expected_types = {
        "str": "text",
        "int": "integer",
        "float": "float",
        "datetime": "text",
    }
    for raw_api_name, raw_override in source.items():
        api_name = _required_text(
            raw_api_name, "QuickSync observations.response_contract_overrides key"
        )
        if _SAFE_PARAMETER_NAME.fullmatch(api_name) is None or api_name not in contracts:
            raise ValueError(
                "QuickSync response contract override must name one declared provider API: "
                f"{api_name}"
            )
        label = f"QuickSync observations.response_contract_overrides.{api_name}"
        override = _mapping(raw_override, label)
        _reject_keys(override, _RESPONSE_CONTRACT_OVERRIDE_KEYS, label)
        schema_version = _required_text(override["schema_version"], f"{label}.schema_version")
        if _SCHEMA_VERSION_PATTERN.fullmatch(schema_version) is None:
            raise ValueError(f"{label}.schema_version must use semantic version grammar")
        base = contracts[api_name]
        base_major = int(str(base["schema_version"]).split(".", 1)[0])
        observed_major = int(schema_version.split(".", 1)[0])
        if observed_major <= base_major:
            raise ValueError(
                f"{label}.schema_version must advance the source contract major"
            )
        missing_fields = _string_list(
            override["missing_fields"], f"{label}.missing_fields", allow_empty=True
        )
        if any(_SAFE_PROVIDER_FIELD.fullmatch(field) is None for field in missing_fields):
            raise ValueError(f"{label}.missing_fields contains invalid provider field")
        base_fields = {field["name"] for field in base["fields"]}
        unknown_missing = sorted(set(missing_fields) - base_fields)
        if unknown_missing:
            raise ValueError(f"{label}.missing_fields contains undeclared field: {unknown_missing[0]}")

        type_overrides: list[dict[str, str]] = []
        override_names: set[str] = set()
        for index, raw_type in enumerate(_sequence(override["type_overrides"], f"{label}.type_overrides")):
            type_label = f"{label}.type_overrides[{index}]"
            type_override = _mapping(raw_type, type_label)
            _reject_keys(type_override, _RESPONSE_TYPE_OVERRIDE_KEYS, type_label)
            field_name = _required_text(type_override["field"], f"{type_label}.field")
            declared_source_type = _required_text(
                type_override["declared_source_type"], f"{type_label}.declared_source_type"
            )
            logical_type = _required_text(type_override["logical_type"], f"{type_label}.logical_type")
            if (
                field_name not in base_fields
                or field_name in missing_fields
                or field_name in override_names
            ):
                raise ValueError(f"{type_label}.field must name one retained declared field")
            if expected_types.get(declared_source_type) != logical_type:
                raise ValueError(f"{type_label} must use the canonical logical type")
            override_names.add(field_name)
            type_overrides.append(
                {
                    "field": field_name,
                    "declared_source_type": declared_source_type,
                    "logical_type": logical_type,
                }
            )

        additional_fields = _fields(override["additional_fields"], f"{label}.additional_fields") if override["additional_fields"] else []
        additional_names = {field["name"] for field in additional_fields}
        overlap = sorted(additional_names & base_fields)
        if overlap:
            raise ValueError(f"{label}.additional_fields overlaps declared field: {overlap[0]}")
        result[api_name] = {
            "evidence_ref": _safe_evidence_ref(override["evidence_ref"], f"{label}.evidence_ref"),
            "schema_version": schema_version,
            "missing_fields": missing_fields,
            "type_overrides": type_overrides,
            "additional_fields": additional_fields,
        }
    return result


def _observation_index(
    document: Mapping[str, Any] | None,
    contracts: Sequence[Mapping[str, Any]],
) -> dict[tuple[str, str], dict[str, Any]]:
    if document is None:
        return {}
    root = _mapping(deepcopy(document), "QuickSync observations")
    _reject_keys(root, _OBSERVATION_ROOT_KEYS, "QuickSync observations")
    if type(root["version"]) is not int or root["version"] != 1:
        raise ValueError("QuickSync observations.version must be integer 1")
    if _required_text(root["provider"], "QuickSync observations.provider") != PROVIDER:
        raise ValueError(f"QuickSync observations.provider must be {PROVIDER}")
    if (
        _required_text(
            root["transport_service"], "QuickSync observations.transport_service"
        )
        != "quicksync"
    ):
        raise ValueError("QuickSync observations.transport_service must be quicksync")

    matrix = _mapping(root["matrix_evidence"], "QuickSync observations.matrix_evidence")
    _reject_keys(
        matrix, _MATRIX_EVIDENCE_KEYS, "QuickSync observations.matrix_evidence"
    )
    for key in ("sha256", "api_names_sha256"):
        value = _required_text(
            matrix[key], f"QuickSync observations.matrix_evidence.{key}"
        )
        if _HASH_PATTERN.fullmatch(value) is None:
            raise ValueError(
                f"QuickSync observations.matrix_evidence.{key} must be SHA-256"
            )
    _required_text(
        matrix["schema_version"],
        "QuickSync observations.matrix_evidence.schema_version",
    )
    observed_at = _required_text(
        matrix["observed_at"], "QuickSync observations.matrix_evidence.observed_at"
    )
    try:
        parsed_observed_at = datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(
            "QuickSync observations.matrix_evidence.observed_at must be RFC3339"
        ) from exc
    if parsed_observed_at.tzinfo is None:
        raise ValueError(
            "QuickSync observations.matrix_evidence.observed_at must include timezone"
        )
    interface_count = _required_positive_int(
        matrix["interface_count"],
        "QuickSync observations.matrix_evidence.interface_count",
    )
    for key in ("raw_data_persisted", "credential_persisted"):
        if _required_bool(matrix[key], f"QuickSync observations.matrix_evidence.{key}"):
            raise ValueError(
                f"QuickSync observations.matrix_evidence.{key} must be false"
            )
    if (
        _required_text(
            matrix["interface_probe_scheme"],
            "QuickSync observations.matrix_evidence.interface_probe_scheme",
        )
        != "http"
    ):
        raise ValueError(
            "QuickSync observations.matrix_evidence.interface_probe_scheme must be http"
        )
    if _required_bool(
        matrix["production_ready"],
        "QuickSync observations.matrix_evidence.production_ready",
    ):
        raise ValueError(
            "QuickSync observations.matrix_evidence.production_ready must be false"
        )
    if (
        _required_text(
            matrix["production_transport_alignment"],
            "QuickSync observations.matrix_evidence.production_transport_alignment",
        )
        != "blocked_until_safe_pre_request_dns_failover_is_implemented_and_verified"
    ):
        raise ValueError(
            "QuickSync observations.matrix_evidence.production_transport_alignment "
            "must remain blocked"
        )

    classifications = _mapping(
        root["classifications"], "QuickSync observations.classifications"
    )
    _reject_keys(
        classifications,
        _CLASSIFICATION_KEYS,
        "QuickSync observations.classifications",
    )
    grouped: dict[str, list[str] | dict[str, list[str]]] = {
        "validated_contract_match": _string_list(
            classifications["validated_contract_match"],
            "QuickSync observations.classifications.validated_contract_match",
        ),
        "numeric_field_repaired": _observation_field_map(
            classifications["numeric_field_repaired"],
            "QuickSync observations.classifications.numeric_field_repaired",
        ),
        "schema_subset": _observation_field_map(
            classifications["schema_subset"],
            "QuickSync observations.classifications.schema_subset",
        ),
    }
    for key in (
        "quality_anomaly",
        "empty",
        "permission_denied",
        "credential_rejected",
        "unsupported",
    ):
        grouped[key] = _string_list(
            classifications[key],
            f"QuickSync observations.classifications.{key}",
            allow_empty=True,
        )

    api_class: dict[str, str] = {}
    for classification, entries in grouped.items():
        api_names = entries if isinstance(entries, list) else list(entries)
        for api_name in api_names:
            previous = api_class.get(api_name)
            if previous is not None:
                raise ValueError(
                    f"QuickSync observation API overlaps classifications: {api_name} "
                    f"({previous}, {classification})"
                )
            api_class[api_name] = classification

    by_api = {contract["api_name"]: contract for contract in contracts}
    by_dataset = {contract["dataset_id"]: contract for contract in contracts}
    if set(api_class) != set(by_api):
        missing = sorted(set(by_api) - set(api_class))
        extra = sorted(set(api_class) - set(by_api))
        raise ValueError(
            "QuickSync observation API set must exactly match contracts; "
            f"missing={missing[:1]}, extra={extra[:1]}"
        )
    if interface_count != len(api_class):
        raise ValueError("QuickSync observation interface_count does not match API set")
    api_set_hash = hashlib.sha256(
        ("\n".join(sorted(api_class)) + "\n").encode("utf-8")
    ).hexdigest()
    if matrix["api_names_sha256"] != api_set_hash:
        raise ValueError(
            "QuickSync observation api_names_sha256 does not match API set"
        )

    response_contract_overrides = _response_contract_override_index(
        root["response_contract_overrides"], by_api
    )

    formal_seed_authorities = _sequence(
        root["dependency_seed_authorities"],
        "QuickSync observations.dependency_seed_authorities",
    )
    formal_seed_keys: set[tuple[str, str, str]] = set()
    for index, raw_seed in enumerate(formal_seed_authorities):
        label = f"QuickSync observations.dependency_seed_authorities[{index}]"
        seed = _mapping(raw_seed, label)
        _reject_keys(seed, _FORMAL_SEED_AUTHORITY_KEYS, label)
        dataset_id = _required_text(seed["dataset_id"], f"{label}.dataset_id")
        field = _required_text(seed["field"], f"{label}.field")
        schema_version = _required_text(
            seed["schema_version"], f"{label}.schema_version"
        )
        source = by_dataset.get(dataset_id)
        if source is None:
            raise ValueError(f"{label}.dataset_id is not in the contract bundle")
        if schema_version != source["schema_version"]:
            raise ValueError(f"{label}.schema_version does not match source dataset")
        if field not in {item["name"] for item in source["fields"]}:
            raise ValueError(f"{label}.field does not match source dataset")
        receipt_id = _required_text(seed["receipt_id"], f"{label}.receipt_id")
        if _RECEIPT_ID_PATTERN.fullmatch(receipt_id) is None:
            raise ValueError(f"{label}.receipt_id is invalid")
        _required_rfc3339(seed["data_through"], f"{label}.data_through")
        dependents = _string_list(
            seed["dependent_api_names"], f"{label}.dependent_api_names"
        )
        if not dependents:
            raise ValueError(f"{label}.dependent_api_names must not be empty")
        if dependents != sorted(dependents) or len(set(dependents)) != len(dependents):
            raise ValueError(f"{label}.dependent_api_names must be sorted and unique")
        for api_name in dependents:
            contract = by_api.get(api_name)
            if contract is None:
                raise ValueError(f"{label}.dependent_api_names contains unknown API")
            fanout = contract["fanout"]
            if (
                set(contract["probe_block_reasons"])
                != {"dependency_seed_receipt_unresolved"}
                or set(contract["ingest_contract_block_reasons"])
                != {"dependency_seed_receipt_unresolved"}
                or fanout["strategy"] != "dataset_field"
                or fanout["source_dataset_id"] != dataset_id
                or fanout["source_field"] != field
            ):
                raise ValueError(
                    f"{label}.dependent_api_names contains an ineligible API: {api_name}"
                )
        seed_key = (dataset_id, field, schema_version)
        if seed_key in formal_seed_keys:
            raise ValueError("QuickSync dependency seed authorities duplicate")
        formal_seed_keys.add(seed_key)

    if formal_seed_authorities != sorted(
        formal_seed_authorities,
        key=lambda item: (item["dataset_id"], item["field"], item["schema_version"]),
    ):
        raise ValueError("QuickSync dependency seed authorities must be sorted")

    numeric_fields = grouped["numeric_field_repaired"]
    schema_fields = grouped["schema_subset"]
    assert isinstance(numeric_fields, dict)
    assert isinstance(schema_fields, dict)
    active_source = _mapping(
        root["active_evidence"], "QuickSync observations.active_evidence"
    )
    active_evidence: dict[str, str] = {}
    for raw_api_name, raw_evidence in active_source.items():
        api_name = _required_text(
            raw_api_name, "QuickSync observations.active_evidence key"
        )
        # External activation evidence may establish a current executable
        # request/result binding even when the reviewed observation matrix is
        # a bounded schema subset or a legal empty response.  Those classes
        # remain fail-closed for quality/permission/credential/unsupported
        # observations and do not alter the declared field contract.
        if api_class.get(api_name) not in {
            "validated_contract_match",
            "numeric_field_repaired",
            "schema_subset",
            "empty",
        }:
            raise ValueError(
                "QuickSync active evidence requires a verified full-field contract: "
                f"{api_name}"
            )
        active_evidence[api_name] = _safe_evidence_ref(
            raw_evidence, f"QuickSync observations.active_evidence.{api_name}"
        )

    entitlement_by_class = {
        "validated_contract_match": "active",
        "numeric_field_repaired": "active",
        "schema_subset": "active",
        "quality_anomaly": "active",
        "empty": "active",
        "permission_denied": "locked",
        "credential_rejected": "unknown",
        "unsupported": "excluded",
    }
    result: dict[tuple[str, str], dict[str, Any]] = {}
    for api_name in sorted(api_class):
        contract = by_api[api_name]
        classification = api_class[api_name]
        declared_fields = {field["name"] for field in contract["fields"]}
        if classification == "numeric_field_repaired":
            missing_repaired = sorted(set(numeric_fields[api_name]) - declared_fields)
            if missing_repaired:
                raise ValueError(
                    f"QuickSync repaired field remains absent from contract: {api_name}/"
                    f"{missing_repaired[0]}"
                )
        result[(contract["dataset_id"], contract["provider"])] = {
            "entitlement_state": entitlement_by_class[classification],
            "activation_state": "active" if api_name in active_evidence else "paused",
            "evidence_ref": active_evidence.get(api_name),
            "classification": classification,
            "schema_missing_fields": list(schema_fields.get(api_name, [])),
            "response_contract_override": response_contract_overrides.get(api_name),
        }
    for raw_seed in formal_seed_authorities:
        for api_name in raw_seed["dependent_api_names"]:
            contract = by_api[api_name]
            observation_key = (contract["dataset_id"], contract["provider"])
            result[observation_key].update(
                {
                    "effective_probe_state": "executable",
                    "effective_probe_block_reasons": [],
                    "effective_ingest_contract_state": "ready",
                    "effective_ingest_contract_block_reasons": [],
                }
            )
    return result


def _normalize_raw_probe_evidence(
    document: Mapping[str, Any],
) -> tuple[dict[str, Any], bool]:
    """Accept the probe tool's external sidecar without a second evidence writer."""

    root = _mapping(deepcopy(document), "HTTPS activation evidence")
    if root.get("schema_version") != "tradingdatas.quicksync.https_probe_evidence.v1":
        return root, False
    _reject_keys(
        root,
        _RAW_PROBE_EVIDENCE_ROOT_KEYS,
        "raw HTTPS probe evidence",
    )
    raw_results = _sequence(root["results"], "raw HTTPS probe evidence.results")
    normalized_results: list[dict[str, Any]] = []
    raw_summary_counts: dict[str, int] = {}
    normalized_summary_counts = {key: 0 for key in _PROBE_SUMMARY_KEYS}
    for index, raw_result in enumerate(raw_results):
        label = f"raw HTTPS probe evidence.results[{index}]"
        result = _mapping(raw_result, label)
        _reject_keys(result, _RAW_PROBE_RESULT_KEYS, label)
        if result["response_redacted"] is not False:
            raise ValueError("raw HTTPS probe evidence redacted results are not promotable")
        raw_state = _required_text(result["state"], f"{label}.state")
        if raw_state not in _PROBE_RESULT_STATES:
            raise ValueError(f"{label}.state is unsupported")
        raw_summary_counts[raw_state] = raw_summary_counts.get(raw_state, 0) + 1
        normalized_summary_counts[raw_state] += 1
        normalized = {
            key: result[key]
            for key in (
                "api_name",
                "provider_class",
                "row_count",
                "response_bytes",
                "response_sha256",
                "fields",
                "elapsed_ms",
            )
        }
        normalized["state"] = raw_state
        normalized_results.append(
            {
                **normalized,
                "result_sha256": _canonical_json_sha256(normalized),
            }
        )
    if [item["api_name"] for item in normalized_results] != sorted(
        item["api_name"] for item in normalized_results
    ):
        raise ValueError("raw HTTPS probe evidence results must be sorted")
    raw_summary = _mapping(root["summary"], "raw HTTPS probe evidence.summary")
    if not set(raw_summary).issubset(_PROBE_RESULT_STATES):
        raise ValueError("raw HTTPS probe evidence summary is inconsistent")
    for state in _PROBE_RESULT_STATES:
        if state not in raw_summary and raw_summary_counts.get(state, 0) == 0:
            continue
        if _required_non_negative_int(
            raw_summary.get(state, 0), f"raw HTTPS probe evidence.summary.{state}"
        ) != raw_summary_counts.get(state, 0):
            raise ValueError("raw HTTPS probe evidence summary is inconsistent")
    evidence = {
        "schema_version": root["schema_version"],
        "source_sha256": _canonical_json_sha256(root),
        "bindings_sha256": "",
        "promotion_stage": "preactivation_candidate",
        "release_commit": root["commit"],
        "request_plan_sha256": root["request_plan_sha256"],
        "official_contract_sha256": root["official_contract_sha256"],
        "request_observations_sha256": root["request_observations_sha256"],
        "transport_observations_sha256": root["transport_observations_sha256"],
        "planned_api_names_sha256": root["api_names_sha256"],
        "executed_api_names_sha256": _api_names_sha256(
            {item["api_name"] for item in normalized_results}
        ),
        "results_sha256": _canonical_json_sha256(
            [
                {key: value for key, value in item.items() if key != "result_sha256"}
                for item in normalized_results
            ]
        ),
        "started_at": root["started_at"],
        "finished_at": root["finished_at"],
        "run_clock": root["run_clock"],
        "scheduled_partition": root["scheduled_partition"],
        "scope": root["scope"],
        "interface_count": root["interface_count"],
        "coverage": root["coverage"],
        "summary": normalized_summary_counts,
        "transport": root["transport"],
        "concurrency": root["concurrency"],
        "rate_budget": root["rate_budget"],
        "response_budget": root["response_budget"],
        "retries": root["retries"],
        "production_ready": root["production_ready"],
        "raw_data_persisted": root["raw_data_persisted"],
        "credential_persisted": root["credential_persisted"],
        "request_values_persisted": root["request_values_persisted"],
    }
    binding_keys = (
        "source_sha256",
        "release_commit",
        "request_plan_sha256",
        "official_contract_sha256",
        "request_observations_sha256",
        "transport_observations_sha256",
        "planned_api_names_sha256",
        "executed_api_names_sha256",
        "run_clock",
        "scheduled_partition",
        "promotion_stage",
    )
    evidence["bindings_sha256"] = _canonical_json_sha256(
        {key: evidence[key] for key in binding_keys}
    )
    return (
        {
            "version": 1,
            "provider": PROVIDER,
            "transport_service": "quicksync",
            "evidence": evidence,
            "seed_authorities": root["seed_authorities"],
            "plan_projection": {},
            "activation_projection": {},
            "results": normalized_results,
        },
        True,
    )


def _activation_evidence_index(
    document: Mapping[str, Any] | None,
    contracts: Sequence[Mapping[str, Any]],
    observations_document: Mapping[str, Any] | None,
    observations: Mapping[tuple[str, str], Mapping[str, Any]],
) -> dict[tuple[str, str], dict[str, Any]]:
    if document is None:
        return {}
    if observations_document is None or not observations:
        raise ValueError("HTTPS activation evidence requires QuickSync observations")

    root, raw_probe_evidence = _normalize_raw_probe_evidence(document)
    _reject_keys(
        root,
        _ACTIVATION_EVIDENCE_ROOT_KEYS,
        "HTTPS activation evidence",
    )
    if type(root["version"]) is not int or root["version"] != 1:
        raise ValueError("HTTPS activation evidence.version must be integer 1")
    if _required_text(root["provider"], "HTTPS activation evidence.provider") != PROVIDER:
        raise ValueError(f"HTTPS activation evidence.provider must be {PROVIDER}")
    if (
        _required_text(
            root["transport_service"],
            "HTTPS activation evidence.transport_service",
        )
        != "quicksync"
    ):
        raise ValueError(
            "HTTPS activation evidence.transport_service must be quicksync"
        )

    evidence = _mapping(root["evidence"], "HTTPS activation evidence.evidence")
    _reject_keys(
        evidence,
        _ACTIVATION_EVIDENCE_KEYS,
        "HTTPS activation evidence.evidence",
    )
    if (
        _required_text(
            evidence["schema_version"],
            "HTTPS activation evidence.evidence.schema_version",
        )
        != "tradingdatas.quicksync.https_probe_evidence.v1"
    ):
        raise ValueError("HTTPS activation evidence has unsupported source schema")
    if (
        _required_text(
            evidence["promotion_stage"],
            "HTTPS activation evidence.evidence.promotion_stage",
        )
        != "preactivation_candidate"
    ):
        raise ValueError(
            "HTTPS activation evidence must remain a preactivation candidate"
        )
    for key in (
        "source_sha256",
        "bindings_sha256",
        "request_plan_sha256",
        "official_contract_sha256",
        "request_observations_sha256",
        "transport_observations_sha256",
        "planned_api_names_sha256",
        "executed_api_names_sha256",
        "results_sha256",
    ):
        _required_sha256(
            evidence[key], f"HTTPS activation evidence.evidence.{key}"
        )
    release_commit = _required_text(
        evidence["release_commit"],
        "HTTPS activation evidence.evidence.release_commit",
    )
    if _COMMIT_PATTERN.fullmatch(release_commit) is None:
        raise ValueError(
            "HTTPS activation evidence.evidence.release_commit must be a commit"
        )

    started_at, started = _required_rfc3339(
        evidence["started_at"], "HTTPS activation evidence.evidence.started_at"
    )
    finished_at, finished = _required_rfc3339(
        evidence["finished_at"], "HTTPS activation evidence.evidence.finished_at"
    )
    run_clock, run_at = _required_rfc3339(
        evidence["run_clock"], "HTTPS activation evidence.evidence.run_clock"
    )
    if not run_at <= started <= finished:
        raise ValueError("HTTPS activation evidence timestamps are not monotonic")
    scheduled_partition = _required_text(
        evidence["scheduled_partition"],
        "HTTPS activation evidence.evidence.scheduled_partition",
    )
    if (
        re.fullmatch(r"[0-9]{8}", scheduled_partition) is None
        or scheduled_partition
        != run_at.astimezone(ASHARE_MARKET_TIMEZONE).strftime("%Y%m%d")
    ):
        raise ValueError(
            "HTTPS activation evidence scheduled_partition must match run_clock"
        )
    binding_keys = (
        "source_sha256",
        "release_commit",
        "request_plan_sha256",
        "official_contract_sha256",
        "request_observations_sha256",
        "transport_observations_sha256",
        "planned_api_names_sha256",
        "executed_api_names_sha256",
        "run_clock",
        "scheduled_partition",
        "promotion_stage",
    )
    if evidence["bindings_sha256"] != _canonical_json_sha256(
        {key: evidence[key] for key in binding_keys}
    ):
        raise ValueError("HTTPS activation evidence bindings_sha256 drifted")
    scope = _required_text(
        evidence["scope"], "HTTPS activation evidence.evidence.scope"
    )
    if scope not in {"gaps", "executable"}:
        raise ValueError(
            "HTTPS activation evidence.evidence.scope must be gaps or executable"
        )

    by_api = {contract["api_name"]: contract for contract in contracts}
    by_dataset = {contract["dataset_id"]: contract for contract in contracts}
    planned_api_names = set(by_api)
    if evidence["planned_api_names_sha256"] != _api_names_sha256(planned_api_names):
        raise ValueError("HTTPS activation evidence planned API set does not match")
    stable_observations = yaml.safe_dump(
        dict(observations_document),
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=False,
        width=100,
    ).encode("utf-8")
    if evidence["transport_observations_sha256"] != hashlib.sha256(
        stable_observations
    ).hexdigest():
        raise ValueError("HTTPS activation evidence transport observations drifted")

    interface_count = _required_positive_int(
        evidence["interface_count"],
        "HTTPS activation evidence.evidence.interface_count",
    )
    coverage = _mapping(
        evidence["coverage"], "HTTPS activation evidence.evidence.coverage"
    )
    _reject_keys(
        coverage,
        _COVERAGE_KEYS,
        "HTTPS activation evidence.evidence.coverage",
    )
    coverage_counts = {
        key: _required_non_negative_int(
            coverage[key], f"HTTPS activation evidence.evidence.coverage.{key}"
        )
        for key in _COVERAGE_KEYS
    }
    expected_planned = (
        len(contracts) if scope == "gaps" else coverage_counts["executable"]
    )
    expected_blocked = (
        0
        if scope == "executable"
        else len(contracts) - coverage_counts["executable"]
    )
    if (
        coverage_counts["planned"] != expected_planned
        or coverage_counts["selected"] != interface_count
        or coverage_counts["executed"] != interface_count
        or not 1 <= interface_count <= coverage_counts["executable"]
        or coverage_counts["blocked"] != expected_blocked
    ):
        raise ValueError("HTTPS activation evidence coverage is inconsistent")

    summary = _mapping(
        evidence["summary"], "HTTPS activation evidence.evidence.summary"
    )
    _reject_keys(
        summary,
        _PROBE_SUMMARY_KEYS,
        "HTTPS activation evidence.evidence.summary",
    )
    expected_summary = {
        key: _required_non_negative_int(
            summary[key], f"HTTPS activation evidence.evidence.summary.{key}"
        )
        for key in _PROBE_SUMMARY_KEYS
    }
    if sum(expected_summary.values()) != interface_count:
        raise ValueError("HTTPS activation evidence summary is inconsistent")

    transport = _mapping(
        evidence["transport"], "HTTPS activation evidence.evidence.transport"
    )
    _reject_keys(
        transport,
        _TRANSPORT_KEYS,
        "HTTPS activation evidence.evidence.transport",
    )
    if (
        _required_text(
            transport["scheme"],
            "HTTPS activation evidence.evidence.transport.scheme",
        )
        != "https"
    ):
        raise ValueError("HTTPS activation evidence requires HTTPS transport")
    if (
        _required_text(
            transport["endpoint_host"],
            "HTTPS activation evidence.evidence.transport.endpoint_host",
        )
        != "api.quicksync.cn"
    ):
        raise ValueError("HTTPS activation evidence endpoint host is not QuickSync")
    _required_positive_int(
        evidence["concurrency"],
        "HTTPS activation evidence.evidence.concurrency",
    )
    if _required_non_negative_int(
        evidence["retries"], "HTTPS activation evidence.evidence.retries"
    ) != 0:
        raise ValueError("HTTPS activation evidence retries must be zero")
    for key in (
        "production_ready",
        "raw_data_persisted",
        "credential_persisted",
        "request_values_persisted",
    ):
        if _required_bool(
            evidence[key], f"HTTPS activation evidence.evidence.{key}"
        ):
            raise ValueError(
                f"HTTPS activation evidence.evidence.{key} must be false"
            )

    rate_budget = _mapping(
        evidence["rate_budget"],
        "HTTPS activation evidence.evidence.rate_budget",
    )
    _reject_keys(
        rate_budget,
        _RATE_BUDGET_KEYS,
        "HTTPS activation evidence.evidence.rate_budget",
    )
    max_requests = _required_positive_int(
        rate_budget["max_requests"],
        "HTTPS activation evidence.evidence.rate_budget.max_requests",
    )
    _required_positive_int(
        rate_budget["window_seconds"],
        "HTTPS activation evidence.evidence.rate_budget.window_seconds",
    )
    authorizations = _mapping(
        rate_budget["authorizations"],
        "HTTPS activation evidence.evidence.rate_budget.authorizations",
    )
    _reject_keys(
        authorizations,
        _AUTHORIZATION_KEYS,
        "HTTPS activation evidence.evidence.rate_budget.authorizations",
    )
    active_before = _required_non_negative_int(
        authorizations["active_before_first"],
        "HTTPS activation evidence.evidence.rate_budget.authorizations.active_before_first",
    )
    active_after = _required_non_negative_int(
        authorizations["active_after_last"],
        "HTTPS activation evidence.evidence.rate_budget.authorizations.active_after_last",
    )
    authorized = _required_non_negative_int(
        authorizations["authorized"],
        "HTTPS activation evidence.evidence.rate_budget.authorizations.authorized",
    )
    first_authorized = _required_finite_number(
        authorizations["first_authorized_at_epoch"],
        "HTTPS activation evidence.evidence.rate_budget.authorizations.first_authorized_at_epoch",
    )
    last_authorized = _required_finite_number(
        authorizations["last_authorized_at_epoch"],
        "HTTPS activation evidence.evidence.rate_budget.authorizations.last_authorized_at_epoch",
    )
    if (
        authorized != interface_count
        or active_before > max_requests
        or active_after > max_requests
        or first_authorized > last_authorized
    ):
        raise ValueError("HTTPS activation evidence rate budget is inconsistent")

    response_budget = _mapping(
        evidence["response_budget"],
        "HTTPS activation evidence.evidence.response_budget",
    )
    _reject_keys(
        response_budget,
        _RESPONSE_BUDGET_KEYS,
        "HTTPS activation evidence.evidence.response_budget",
    )
    observed_bytes = _required_non_negative_int(
        response_budget["observed_bytes"],
        "HTTPS activation evidence.evidence.response_budget.observed_bytes",
    )
    per_call_bytes = _required_positive_int(
        response_budget["per_call_bytes"],
        "HTTPS activation evidence.evidence.response_budget.per_call_bytes",
    )
    per_run_bytes = _required_positive_int(
        response_budget["per_run_bytes"],
        "HTTPS activation evidence.evidence.response_budget.per_run_bytes",
    )
    if observed_bytes > per_run_bytes:
        raise ValueError("HTTPS activation evidence exceeded response run budget")

    raw_results = _sequence(root["results"], "HTTPS activation evidence.results")
    if len(raw_results) != interface_count:
        raise ValueError("HTTPS activation evidence result count is inconsistent")
    result_entries: list[dict[str, Any]] = []
    result_by_api: dict[str, dict[str, Any]] = {}
    for index, raw_result in enumerate(raw_results):
        label = f"HTTPS activation evidence.results[{index}]"
        result = _mapping(raw_result, label)
        _reject_keys(result, _PROBE_RESULT_KEYS, label)
        api_name = _required_text(result["api_name"], f"{label}.api_name")
        if api_name not in by_api:
            raise ValueError(f"{label}.api_name is not in the contract bundle")
        if api_name in result_by_api:
            raise ValueError("HTTPS activation evidence results contain duplicate API")
        state = _required_text(result["state"], f"{label}.state")
        if state not in _PROBE_RESULT_STATES:
            raise ValueError(f"{label}.state is unsupported")
        source_result = {
            "api_name": api_name,
            "state": state,
            "provider_class": _required_text(
                result["provider_class"], f"{label}.provider_class"
            ),
            "row_count": _required_non_negative_int(
                result["row_count"], f"{label}.row_count"
            ),
            "response_bytes": _required_non_negative_int(
                result["response_bytes"], f"{label}.response_bytes"
            ),
            "response_sha256": _required_sha256(
                result["response_sha256"], f"{label}.response_sha256"
            ),
            "fields": _string_list(
                result["fields"], f"{label}.fields", allow_empty=True
            ),
            "elapsed_ms": _required_finite_number(
                result["elapsed_ms"], f"{label}.elapsed_ms"
            ),
        }
        if source_result["elapsed_ms"] < 0:
            raise ValueError(f"{label}.elapsed_ms must be non-negative")
        if source_result["response_bytes"] > per_call_bytes:
            raise ValueError(f"{label} exceeded response call budget")
        if (
            _required_sha256(result["result_sha256"], f"{label}.result_sha256")
            != _canonical_json_sha256(source_result)
        ):
            raise ValueError(f"{label}.result_sha256 does not match result")
        result_entries.append(source_result)
        result_by_api[api_name] = source_result
    result_api_names = list(result_by_api)
    if result_api_names != sorted(result_api_names):
        raise ValueError("HTTPS activation evidence results must be sorted")
    if evidence["executed_api_names_sha256"] != _api_names_sha256(result_api_names):
        raise ValueError("HTTPS activation evidence executed API set drifted")
    if evidence["results_sha256"] != _canonical_json_sha256(result_entries):
        raise ValueError("HTTPS activation evidence results projection drifted")
    actual_summary = {state: 0 for state in _PROBE_RESULT_STATES}
    for result in result_entries:
        actual_summary[result["state"]] += 1
    if actual_summary != expected_summary:
        raise ValueError("HTTPS activation evidence result states do not match summary")
    if sum(result["response_bytes"] for result in result_entries) != observed_bytes:
        raise ValueError("HTTPS activation evidence response bytes do not match budget")

    raw_seed_authorities = _sequence(
        root["seed_authorities"], "HTTPS activation evidence.seed_authorities"
    )
    seed_keys: set[tuple[str, str, str]] = set()
    raw_seed_by_key: dict[tuple[str, str, str], dict[str, Any]] = {}
    seed_order: list[tuple[str, str]] = []
    for index, raw_seed in enumerate(raw_seed_authorities):
        label = f"HTTPS activation evidence.seed_authorities[{index}]"
        seed = _mapping(raw_seed, label)
        _reject_keys(seed, _SEED_AUTHORITY_KEYS, label)
        dataset_id = _required_text(seed["dataset_id"], f"{label}.dataset_id")
        field = _required_text(seed["field"], f"{label}.field")
        schema_version = _required_text(
            seed["schema_version"], f"{label}.schema_version"
        )
        source = by_dataset.get(dataset_id)
        if source is None:
            raise ValueError(f"{label}.dataset_id is not in the contract bundle")
        if schema_version != source["schema_version"]:
            raise ValueError(f"{label}.schema_version does not match source dataset")
        if field not in {item["name"] for item in source["fields"]}:
            raise ValueError(f"{label}.field does not match source dataset")
        receipt_id = _required_text(seed["receipt_id"], f"{label}.receipt_id")
        if _RECEIPT_ID_PATTERN.fullmatch(receipt_id) is None:
            raise ValueError(f"{label}.receipt_id is invalid")
        _, data_through = _required_rfc3339(
            seed["data_through"], f"{label}.data_through"
        )
        if data_through > run_at:
            raise ValueError(f"{label}.data_through is in the future")
        seed_key = (dataset_id, field, schema_version)
        if seed_key in seed_keys:
            raise ValueError("HTTPS activation evidence seed authorities duplicate")
        seed_keys.add(seed_key)
        raw_seed_by_key[seed_key] = {
            "dataset_id": dataset_id,
            "field": field,
            "schema_version": schema_version,
            "receipt_id": receipt_id,
            # Keep the original text for the formal authority comparison.  The
            # parsed instant above is only used for the future-date guard.
            "data_through": seed["data_through"],
        }
        seed_order.append((dataset_id, field))
    if seed_order != sorted(seed_order):
        raise ValueError("HTTPS activation evidence seed authorities must be sorted")

    # A dependency producer may already be formally bound in the repository
    # without being repeated as a result in each dependent probe sidecar.  A
    # raw sidecar may reuse that authority only when every binding field is an
    # exact match and the formal authority explicitly names the dependent API.
    # This keeps external receipt claims fail-closed and does not infer rows.
    formal_seed_by_key: dict[tuple[str, str, str], dict[str, Any]] = {}
    formal_seed_authorities = _sequence(
        observations_document["dependency_seed_authorities"],
        "QuickSync observations.dependency_seed_authorities",
    )
    for index, raw_formal_seed in enumerate(formal_seed_authorities):
        label = f"QuickSync observations.dependency_seed_authorities[{index}]"
        formal_seed = _mapping(raw_formal_seed, label)
        key = (
            _required_text(formal_seed["dataset_id"], f"{label}.dataset_id"),
            _required_text(formal_seed["field"], f"{label}.field"),
            _required_text(
                formal_seed["schema_version"], f"{label}.schema_version"
            ),
        )
        formal_seed_by_key[key] = {
            "receipt_id": _required_text(
                formal_seed["receipt_id"], f"{label}.receipt_id"
            ),
            "data_through": _required_text(
                formal_seed["data_through"], f"{label}.data_through"
            ),
            "dependent_api_names": set(
                _string_list(
                    formal_seed["dependent_api_names"],
                    f"{label}.dependent_api_names",
                )
            ),
        }
    if raw_probe_evidence:
        for key, raw_seed in raw_seed_by_key.items():
            formal_seed = formal_seed_by_key.get(key)
            if formal_seed is None or any(
                raw_seed[field] != formal_seed[field]
                for field in ("receipt_id", "data_through")
            ):
                raise ValueError(
                    "HTTPS activation evidence seed authority does not match "
                    "formal dependency seed authority"
                )

    dependency_resolved: set[str] = set()
    for api_name, contract in by_api.items():
        if set(contract["probe_block_reasons"]) != {
            "dependency_seed_receipt_unresolved"
        } or set(contract["ingest_contract_block_reasons"]) != {
            "dependency_seed_receipt_unresolved"
        }:
            continue
        fanout = contract["fanout"]
        if fanout["strategy"] != "dataset_field":
            continue
        source = by_dataset.get(fanout["source_dataset_id"])
        if source is None:
            continue
        seed_key = (
            fanout["source_dataset_id"],
            fanout["source_field"],
            source["schema_version"],
        )
        if seed_key in seed_keys:
            formal_seed = formal_seed_by_key.get(seed_key)
            if formal_seed is None:
                raise ValueError(
                    "HTTPS activation evidence seed authority does not match "
                    "formal dependency seed authority"
                )
            if api_name not in formal_seed["dependent_api_names"]:
                if api_name in result_by_api:
                    raise ValueError(
                        "HTTPS activation evidence dependent API is not formally listed"
                    )
                continue
            source_result = result_by_api.get(source["api_name"])
            if source_result is None and raw_probe_evidence:
                # The formal authority makes every explicitly listed
                # dependent request-shape executable.  Activation still
                # requires that the dependent API appear as a fresh result;
                # omitted siblings (for example a later batch member) remain
                # paused in the candidate projection.
                dependency_resolved.add(api_name)
                continue
            if source_result is None or source_result["state"] not in _FRESH_ACTIVATION_STATES:
                raise ValueError(
                    "HTTPS activation evidence seed producer is not fresh eligible"
                )
            dependency_resolved.add(api_name)

    executable_api_names = {
        contract["api_name"]
        for contract in contracts
        if contract["probe_state"] == "executable"
    } | dependency_resolved
    if raw_probe_evidence:
        # The frozen executable-scope plan may contain every request-shape
        # dependent of a seed, while formal dependency authority intentionally
        # resolves only the explicitly listed safe siblings.  Keep those
        # plan-admissible names available for the result-subset/coverage check;
        # only ``dependency_resolved`` can make a contract ingest-ready or
        # active, and an unlisted dependent result is rejected above.
        for contract in contracts:
            if set(contract["probe_block_reasons"]) != {
                "dependency_seed_receipt_unresolved"
            } or set(contract["ingest_contract_block_reasons"]) != {
                "dependency_seed_receipt_unresolved"
            }:
                continue
            fanout = contract["fanout"]
            if fanout["strategy"] != "dataset_field":
                continue
            source = by_dataset.get(fanout["source_dataset_id"])
            if source is None:
                continue
            seed_key = (
                fanout["source_dataset_id"],
                fanout["source_field"],
                source["schema_version"],
            )
            if seed_key in seed_keys:
                executable_api_names.add(contract["api_name"])
    if (
        not raw_probe_evidence
        and coverage_counts["executable"] != len(executable_api_names)
    ):
        raise ValueError("HTTPS activation evidence executable coverage drifted")
    if raw_probe_evidence:
        if coverage_counts["executable"] > len(executable_api_names):
            raise ValueError("HTTPS activation evidence executable coverage drifted")
        cohort_evidence = interface_count < coverage_counts["executable"]
        if not set(result_by_api) <= executable_api_names:
            raise ValueError("HTTPS activation evidence result API is not executable")
    else:
        cohort_evidence = interface_count < len(executable_api_names)
        if cohort_evidence:
            if not set(result_by_api) < executable_api_names:
                raise ValueError("HTTPS activation evidence cohort is not a strict subset")
        elif set(result_by_api) != executable_api_names:
            raise ValueError("HTTPS activation evidence executable API set is not closed")
    ingest_ready_api_names = {
        api_name
        for api_name in result_by_api
        if by_api[api_name]["ingest_contract_state"] == "ready"
        or api_name in dependency_resolved
    }
    if not raw_probe_evidence:
        plan_projection = _mapping(
            root["plan_projection"], "HTTPS activation evidence.plan_projection"
        )
        _reject_keys(
            plan_projection,
            _COUNT_HASH_KEYS,
            "HTTPS activation evidence.plan_projection",
        )
        if _required_non_negative_int(
            plan_projection["ingest_ready_count"],
            "HTTPS activation evidence.plan_projection.ingest_ready_count",
        ) != len(ingest_ready_api_names):
            raise ValueError("HTTPS activation evidence ingest-ready count drifted")
        if _required_sha256(
            plan_projection["ingest_ready_api_names_sha256"],
            "HTTPS activation evidence.plan_projection.ingest_ready_api_names_sha256",
        ) != _api_names_sha256(ingest_ready_api_names):
            raise ValueError("HTTPS activation evidence ingest-ready API set drifted")

    fresh_api_names = {
        api_name
        for api_name, result in result_by_api.items()
        if result["state"] in _FRESH_ACTIVATION_STATES
    }
    candidate_api_names = fresh_api_names & ingest_ready_api_names
    previous_active = {
        contract["api_name"]
        for contract in contracts
        if observations[(contract["dataset_id"], contract["provider"])][
            "activation_state"
        ]
        == "active"
    }
    active_api_names = previous_active | {
        api_name
        for api_name in candidate_api_names
        if _activation_window_is_supported(by_api[api_name])
    }
    paused_api_names = planned_api_names - active_api_names
    if not raw_probe_evidence:
        activation_projection = _mapping(
            root["activation_projection"],
            "HTTPS activation evidence.activation_projection",
        )
        _reject_keys(
            activation_projection,
            _ACTIVATION_PROJECTION_KEYS,
            "HTTPS activation evidence.activation_projection",
        )
        if (
            _required_non_negative_int(
                activation_projection["candidate_count"],
                "HTTPS activation evidence.activation_projection.candidate_count",
            )
            != len(candidate_api_names)
            or _required_sha256(
                activation_projection["candidate_api_names_sha256"],
                "HTTPS activation evidence.activation_projection.candidate_api_names_sha256",
            )
            != _api_names_sha256(candidate_api_names)
            or
            _required_non_negative_int(
                activation_projection["active_count"],
                "HTTPS activation evidence.activation_projection.active_count",
            )
            != len(active_api_names)
            or _required_non_negative_int(
                activation_projection["paused_count"],
                "HTTPS activation evidence.activation_projection.paused_count",
            )
            != len(paused_api_names)
            or _required_sha256(
                activation_projection["active_api_names_sha256"],
                "HTTPS activation evidence.activation_projection.active_api_names_sha256",
            )
            != _api_names_sha256(active_api_names)
            or _required_sha256(
                activation_projection["paused_api_names_sha256"],
                "HTTPS activation evidence.activation_projection.paused_api_names_sha256",
            )
            != _api_names_sha256(paused_api_names)
        ):
            raise ValueError("HTTPS activation evidence activation projection drifted")

    if not previous_active <= active_api_names:
        raise ValueError("HTTPS activation evidence does not preserve fresh prior active set")

    projected: dict[tuple[str, str], dict[str, Any]] = {}
    for contract in contracts:
        api_name = contract["api_name"]
        key = (contract["dataset_id"], contract["provider"])
        baseline = observations[key]
        resolved = api_name in dependency_resolved
        projected[key] = {
            **baseline,
            "entitlement_state": (
                "active" if api_name in active_api_names else baseline["entitlement_state"]
            ),
            "activation_state": "active" if api_name in active_api_names else "paused",
            "effective_probe_state": (
                "executable"
                if resolved or baseline.get("effective_probe_state") == "executable"
                else contract["probe_state"]
            ),
            "effective_probe_block_reasons": (
                []
                if resolved or baseline.get("effective_probe_state") == "executable"
                else list(contract["probe_block_reasons"])
            ),
            "effective_ingest_contract_state": (
                "ready"
                if resolved or baseline.get("effective_ingest_contract_state") == "ready"
                else contract["ingest_contract_state"]
            ),
            "effective_ingest_contract_block_reasons": (
                []
                if resolved or baseline.get("effective_ingest_contract_state") == "ready"
                else list(contract["ingest_contract_block_reasons"])
            ),
        }
    del started_at, finished_at, run_clock
    return projected


def _fields(raw: object, label: str) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for index, raw_field in enumerate(_sequence(raw, f"{label}.fields")):
        field_label = f"{label}.fields[{index}]"
        field = _mapping(raw_field, field_label)
        _reject_keys(field, _FIELD_KEYS, field_label)
        name = _required_text(field["name"], f"{field_label}.name")
        if _SAFE_PROVIDER_FIELD.fullmatch(name) is None:
            raise ValueError(f"{field_label}.name must use provider field grammar")
        logical_type = _required_text(
            field["logical_type"], f"{field_label}.logical_type"
        )
        if logical_type not in {"text", "integer", "float"}:
            raise ValueError(f"{field_label}.logical_type is unsupported")
        result.append(
            {
                "name": name,
                "declared_source_type": _required_text(
                    field["declared_source_type"], f"{field_label}.declared_source_type"
                ),
                "logical_type": logical_type,
                "nullable": _required_bool(
                    field["nullable"], f"{field_label}.nullable"
                ),
                "selectable": _required_bool(
                    field["selectable"], f"{field_label}.selectable"
                ),
                "filterable": _required_bool(
                    field["filterable"], f"{field_label}.filterable"
                ),
                "sortable": _required_bool(
                    field["sortable"], f"{field_label}.sortable"
                ),
            }
        )
    if not result:
        raise ValueError(f"{label}.fields must not be empty")
    names = [field["name"] for field in result]
    if len(names) != len(set(names)):
        raise ValueError(f"{label}.fields contains duplicate field names")
    return result


def _request_template(raw: object, label: str) -> dict[str, str]:
    source = _mapping(raw, label)
    result: dict[str, str] = {}
    for raw_key, raw_value in source.items():
        key = _required_text(raw_key, f"{label} key")
        if _SAFE_PARAMETER_NAME.fullmatch(key) is None:
            raise ValueError(f"{label} key must use provider parameter grammar")
        result[key] = _required_text(raw_value, f"{label}.{key}")
    return dict(sorted(result.items()))


def _request_variants(
    raw: object, template: Mapping[str, str], label: str
) -> list[dict[str, Any]]:
    variants: list[dict[str, Any]] = []
    for index, raw_variant in enumerate(_sequence(raw, label)):
        variant_label = f"{label}[{index}]"
        variant = _mapping(raw_variant, variant_label)
        unknown = sorted(set(variant) - set(template))
        if unknown:
            raise ValueError(
                f"{variant_label} key is absent from request_template: {unknown[0]}"
            )
        normalized: dict[str, Any] = {}
        for key in sorted(variant):
            if _WINDOW_PLACEHOLDER.fullmatch(template[key]):
                raise ValueError(
                    f"{variant_label} cannot override placeholder parameter: {key}"
                )
            value = _json_scalar(variant[key], f"{variant_label}.{key}")
            normalized[key] = value
        variants.append(normalized)
    if not variants:
        raise ValueError(f"{label} must not be empty")
    static_defaults = {
        key: value
        for key, value in template.items()
        if _WINDOW_PLACEHOLDER.fullmatch(value) is None
    }
    if {} not in variants and not any(
        all(variant.get(key) == value for key, value in static_defaults.items())
        for variant in variants
    ):
        raise ValueError(f"{label} must include the request_template default variant")
    return variants


def _fanout(raw: object, request_shape: str, label: str) -> dict[str, Any]:
    value = _mapping(raw, label)
    strategy = _required_text(value.get("strategy"), f"{label}.strategy")
    if strategy == "none":
        _reject_keys(value, frozenset({"strategy"}), label)
        result = {"strategy": "none"}
    elif strategy == "literal_values":
        _reject_keys(
            value,
            _FANOUT_KEYS,
            label,
            required=frozenset({"strategy", "parameter", "values", "batch_size"}),
        )
        parameter = _required_text(value["parameter"], f"{label}.parameter")
        if _SAFE_PARAMETER_NAME.fullmatch(parameter) is None:
            raise ValueError(f"{label}.parameter must use provider field grammar")
        raw_values = value["values"]
        if not isinstance(raw_values, list) or not raw_values:
            raise ValueError(f"{label}.values must be a non-empty list")
        values = [_json_scalar(item, f"{label}.values[{index}]") for index, item in enumerate(raw_values)]
        if any(item is None or (type(item) is str and not item) for item in values):
            raise ValueError(f"{label}.values must be non-empty scalars")
        identities = {(type(item).__name__, item) for item in values}
        if len(identities) != len(values):
            raise ValueError(f"{label}.values must be unique")
        batch_size = _required_positive_int(
            value["batch_size"], f"{label}.batch_size"
        )
        result = {"strategy": strategy}
        # Preserve the declared source-key order in the compiled mapping.
        # The checked registry intentionally keeps large fanout values compact,
        # while other literal fanouts retain their existing order.
        for key in value:
            if key == "parameter":
                result["parameter"] = parameter
            elif key == "values":
                result["values"] = values
            elif key == "batch_size":
                result["batch_size"] = batch_size
    elif strategy == "dataset_field":
        _reject_keys(
            value,
            _FANOUT_KEYS,
            label,
            required=frozenset(
                {"strategy", "parameter", "source_dataset_id", "source_field", "batch_size"}
            ),
        )
        parameter = _required_text(value["parameter"], f"{label}.parameter")
        source_field = _required_text(value["source_field"], f"{label}.source_field")
        if (
            _SAFE_PARAMETER_NAME.fullmatch(parameter) is None
            or _SAFE_PROVIDER_FIELD.fullmatch(source_field) is None
        ):
            raise ValueError(f"{label} fields must use provider field grammar")
        result = {
            "strategy": strategy,
            "parameter": parameter,
            "source_dataset_id": _required_text(
                value["source_dataset_id"], f"{label}.source_dataset_id"
            ),
            "source_field": source_field,
            "batch_size": _required_positive_int(
                value["batch_size"], f"{label}.batch_size"
            ),
        }
        if "source_equals" in value:
            raw_equals = value["source_equals"]
            if not isinstance(raw_equals, dict):
                raise ValueError(f"{label}.source_equals must be an object")
            result["source_equals"] = {
                _required_text(field, f"{label}.source_equals field"): _required_text(
                    expected, f"{label}.source_equals.{field}"
                )
                for field, expected in sorted(raw_equals.items())
            }
        date_field = value.get("source_date_field")
        date_days = value.get("source_date_lte_days")
        if (date_field is None) != (date_days is None):
            raise ValueError(f"{label} source date selector is incomplete")
        if date_field is not None:
            result["source_date_field"] = _required_text(
                date_field, f"{label}.source_date_field"
            )
            result["source_date_lte_days"] = _required_positive_int(
                date_days, f"{label}.source_date_lte_days"
            )
        if "max_values" in value:
            result["max_values"] = _required_positive_int(
                value["max_values"], f"{label}.max_values"
            )
        if "source_order" in value:
            source_order = _required_text(value["source_order"], f"{label}.source_order")
            if source_order not in {"lexical", "stable_hash"}:
                raise ValueError(f"{label}.source_order is unsupported")
            result["source_order"] = source_order
    else:
        raise ValueError(f"{label}.strategy is unsupported")
    allowed_strategies = (
        {"dataset_field"}
        if request_shape == "entity_fanout"
        else {"dataset_field", "literal_values"}
        if request_shape == "dimension_fanout"
        else {"none", "literal_values"}
        if request_shape == "event_or_intraday_window"
        else {"none"}
    )
    if result["strategy"] not in allowed_strategies:
        if request_shape == "entity_fanout":
            raise ValueError(f"{label} for {request_shape} requires strategy=dataset_field")
        raise ValueError(f"{label} has an incompatible strategy for {request_shape}")
    return result


def _pagination(raw: object, label: str) -> dict[str, Any]:
    value = _mapping(raw, label)
    strategy = _required_text(value.get("strategy"), f"{label}.strategy")
    if strategy == "none":
        _reject_keys(value, frozenset({"strategy"}), label)
        return {"strategy": "none"}
    if strategy != "offset":
        raise ValueError(f"{label}.strategy is unsupported")
    _reject_keys(value, _PAGINATION_KEYS, label)
    limit_parameter = _required_text(
        value["limit_parameter"], f"{label}.limit_parameter"
    )
    offset_parameter = _required_text(
        value["offset_parameter"], f"{label}.offset_parameter"
    )
    if limit_parameter == offset_parameter:
        raise ValueError(f"{label} limit_parameter and offset_parameter must differ")
    if (
        _SAFE_PARAMETER_NAME.fullmatch(limit_parameter) is None
        or _SAFE_PARAMETER_NAME.fullmatch(offset_parameter) is None
    ):
        raise ValueError(f"{label} parameters must use provider field grammar")
    return {
        "strategy": strategy,
        "limit_parameter": limit_parameter,
        "offset_parameter": offset_parameter,
        "page_size": _required_positive_int(value["page_size"], f"{label}.page_size"),
        "max_pages": _required_positive_int(value["max_pages"], f"{label}.max_pages"),
    }


def _resumable_fanout(raw: object, label: str) -> dict[str, Any] | None:
    if raw is None:
        return None
    value = _mapping(raw, label)
    _reject_keys(value, frozenset({"cursor_contract_version", "max_batches_per_run"}), label)
    if value.get("cursor_contract_version") != 2:
        raise ValueError(f"{label}.cursor_contract_version must be 2")
    return {
        "cursor_contract_version": 2,
        "max_batches_per_run": _required_positive_int(
            value.get("max_batches_per_run"), f"{label}.max_batches_per_run"
        ),
    }


def _window_policy(
    raw: object, template: Mapping[str, str], label: str
) -> dict[str, Any] | None:
    placeholders = sorted(
        match.group(1)
        for value in template.values()
        if (match := _WINDOW_PLACEHOLDER.fullmatch(value)) is not None
    )
    if raw is None:
        if placeholders:
            raise ValueError(f"{label} is required for window placeholders")
        return None
    value = _mapping(raw, label)
    _reject_keys(value, _WINDOW_KEYS, label)
    required_keys = _string_list(value["required_keys"], f"{label}.required_keys")
    formats = _mapping(value["formats"], f"{label}.formats")
    if set(required_keys) != set(formats) or set(required_keys) != set(placeholders):
        raise ValueError(f"{label} keys must exactly match request window placeholders")
    normalized_formats = {
        key: _required_text(formats[key], f"{label}.formats.{key}")
        for key in sorted(formats)
    }
    if any(item not in _REQUEST_WINDOW_FORMATS for item in normalized_formats.values()):
        raise ValueError(f"{label}.formats contains unsupported format")
    start = _required_text(value["range_start_key"], f"{label}.range_start_key")
    end = _required_text(value["range_end_key"], f"{label}.range_end_key")
    if start not in required_keys or end not in required_keys:
        raise ValueError(f"{label} range keys must be required keys")
    return {
        "required_keys": required_keys,
        "formats": normalized_formats,
        "range_start_key": start,
        "range_end_key": end,
        "max_span_days": _required_positive_int(
            value["max_span_days"], f"{label}.max_span_days"
        ),
    }


def _completeness(
    raw: object,
    *,
    fields: set[str],
    template: Mapping[str, str],
    window: Mapping[str, Any] | None,
    label: str,
) -> dict[str, Any] | None:
    if raw is None:
        return None
    value = _mapping(raw, label)
    unknown = sorted(set(value) - _COMPLETENESS_KEYS)
    if unknown:
        raise ValueError(f"{label} has unknown key(s): {', '.join(unknown)}")
    strategy = _required_text(value.get("strategy"), f"{label}.strategy")
    if strategy not in _COMPLETENESS_STRATEGIES:
        raise ValueError(f"{label}.strategy is unsupported")
    fixed = _mapping(value.get("fixed_field_matches"), f"{label}.fixed_field_matches")
    normalized_fixed: dict[str, str] = {}
    for field, parameter in fixed.items():
        field_name = _required_text(field, f"{label}.fixed_field_matches key")
        parameter_name = _required_text(
            parameter, f"{label}.fixed_field_matches.{field_name}"
        )
        if field_name not in fields:
            raise ValueError(
                f"{label}.fixed_field_matches references undeclared field: {field_name}"
            )
        if parameter_name not in template:
            raise ValueError(
                f"{label}.fixed_field_matches references missing parameter: {parameter_name}"
            )
        normalized_fixed[field_name] = parameter_name
    result: dict[str, Any] = {
        "strategy": strategy,
        "fixed_field_matches": dict(sorted(normalized_fixed.items())),
        "reject_at_row_limit": _required_bool(
            value.get("reject_at_row_limit", True), f"{label}.reject_at_row_limit"
        ),
    }
    if strategy == "one_row_per_calendar_date":
        required = {
            "strategy",
            "date_field",
            "request_start_key",
            "request_end_key",
            "fixed_field_matches",
        }
        missing = sorted(required - set(value))
        if missing:
            raise ValueError(f"{label} is missing key(s): {', '.join(missing)}")
        if window is None:
            raise ValueError(f"{label} requires request_window_policy")
        date_field = _required_text(value["date_field"], f"{label}.date_field")
        start = _required_text(value["request_start_key"], f"{label}.request_start_key")
        end = _required_text(value["request_end_key"], f"{label}.request_end_key")
        if date_field not in fields:
            raise ValueError(f"{label}.date_field is undeclared")
        if start not in window["required_keys"] or end not in window["required_keys"]:
            raise ValueError(f"{label} request range keys must exist in window policy")
        result.update(
            date_field=date_field, request_start_key=start, request_end_key=end
        )
    elif strategy == "unique_primary_key_snapshot":
        fanout_field = value.get("fanout_field")
        snapshot_field = value.get("snapshot_field")
        if (fanout_field is None) != (snapshot_field is None):
            raise ValueError(f"{label} fanout and snapshot fields must be declared together")
        if snapshot_field is not None:
            snapshot_field = _required_text(
                snapshot_field, f"{label}.snapshot_field"
            )
            if snapshot_field not in fields:
                raise ValueError(f"{label}.snapshot_field is undeclared")
            result["snapshot_field"] = snapshot_field
        if fanout_field is not None:
            fanout_field = _required_text(fanout_field, f"{label}.fanout_field")
            if fanout_field not in fields:
                raise ValueError(f"{label}.fanout_field is undeclared")
            result["fanout_field"] = fanout_field
    elif strategy == "single_partition_unique_primary_key":
        required = {
            "strategy",
            "partition_field",
            "request_partition_key",
            "fixed_field_matches",
        }
        missing = sorted(required - set(value))
        if missing:
            raise ValueError(f"{label} is missing key(s): {', '.join(missing)}")
        if window is None:
            raise ValueError(f"{label} requires request_window_policy")
        partition = _required_text(value["partition_field"], f"{label}.partition_field")
        request_key = _required_text(
            value["request_partition_key"], f"{label}.request_partition_key"
        )
        if partition not in fields or request_key not in window["required_keys"]:
            raise ValueError(f"{label} partition identity is not declared")
        result.update(partition_field=partition, request_partition_key=request_key)
    elif strategy == "windowed_unique_primary_key":
        required = {
            "strategy",
            "date_field",
            "request_start_key",
            "request_end_key",
            "fanout_field",
            "fixed_field_matches",
        }
        missing = sorted(required - set(value))
        if missing:
            raise ValueError(f"{label} is missing key(s): {', '.join(missing)}")
        if window is None:
            raise ValueError(f"{label} requires request_window_policy")
        date_field = _required_text(value["date_field"], f"{label}.date_field")
        fanout_field = _required_text(value["fanout_field"], f"{label}.fanout_field")
        start = _required_text(value["request_start_key"], f"{label}.request_start_key")
        end = _required_text(value["request_end_key"], f"{label}.request_end_key")
        if date_field not in fields or fanout_field not in fields:
            raise ValueError(f"{label} window identity is not declared")
        if (
            start != window["range_start_key"]
            or end != window["range_end_key"]
            or window["formats"][start] != "local_datetime_seconds"
            or window["formats"][end] != "local_datetime_seconds"
        ):
            raise ValueError(
                f"{label} requires local_datetime_seconds window range keys"
            )
        result.update(
            date_field=date_field,
            request_start_key=start,
            request_end_key=end,
            fanout_field=fanout_field,
        )
    return result


def _normalized_contract(
    raw: object,
    *,
    index: int,
    provider: str,
    require_input_fields: bool,
) -> dict[str, Any]:
    label = f"upstream contracts[{index}]"
    value = _mapping(raw, label)
    required_keys = (
        _CONTRACT_REQUIRED_KEYS
        if require_input_fields
        else _CONTRACT_REQUIRED_KEYS
        - {
            "input_fields",
            "probe_state",
            "probe_block_reasons",
            "ingest_contract_state",
            "ingest_contract_block_reasons",
        }
    )
    _reject_keys(value, _CONTRACT_KEYS, label, required=required_keys)
    contract_provider = _required_text(value["provider"], f"{label}.provider")
    if contract_provider != provider:
        raise ValueError(f"{label}.provider must match bundle provider")
    api_name = _required_text(value["api_name"], f"{label}.api_name")
    if _SAFE_PARAMETER_NAME.fullmatch(api_name) is None:
        raise ValueError(f"{label}.api_name must use provider API grammar")
    source_hash = _required_text(
        value["source_document_sha256"], f"{label}.source_document_sha256"
    )
    if _HASH_PATTERN.fullmatch(source_hash) is None:
        raise ValueError(f"{label}.source_document_sha256 must be SHA-256")
    schema_version = _required_text(value["schema_version"], f"{label}.schema_version")
    if _SCHEMA_VERSION_PATTERN.fullmatch(schema_version) is None:
        raise ValueError(f"{label}.schema_version must use MAJOR.MINOR.PATCH")
    input_fields = (
        _input_fields(value["input_fields"], f"{label}.input_fields")
        if require_input_fields
        else None
    )
    fields = _fields(value["fields"], label)
    fields_by_name = {field["name"]: field for field in fields}
    primary_key = _string_list(
        value["primary_key"],
        f"{label}.primary_key",
        allow_empty=True,
    )
    default_projection = _string_list(
        value["default_projection"], f"{label}.default_projection"
    )
    for key, names in (
        ("primary_key", primary_key),
        ("default_projection", default_projection),
    ):
        missing = sorted(set(names) - set(fields_by_name))
        if missing:
            raise ValueError(
                f"{label}.{key} references undeclared field(s): {', '.join(missing)}"
            )
    if any(fields_by_name[name]["nullable"] for name in primary_key):
        raise ValueError(f"{label}.primary_key fields must not be nullable")
    optional: dict[str, str | None] = {}
    for key in ("as_of_field", "range_field", "partition_field"):
        raw_name = value[key]
        name = None if raw_name is None else _required_text(raw_name, f"{label}.{key}")
        if name is not None and name not in fields_by_name:
            raise ValueError(f"{label}.{key} references undeclared field: {name}")
        optional[key] = name
    as_of_format = value["as_of_format"]
    if optional["as_of_field"] is None:
        if as_of_format is not None:
            raise ValueError(f"{label}.as_of_format requires as_of_field")
    elif as_of_format not in {"yyyymm", "yyyymmdd", "rfc3339"}:
        raise ValueError(f"{label}.as_of_format is unsupported")
    request_shape = _required_text(value["request_shape"], f"{label}.request_shape")
    if request_shape not in _REQUEST_SHAPES:
        raise ValueError(f"{label}.request_shape is unsupported")
    template = _request_template(value["request_template"], f"{label}.request_template")
    variants = _request_variants(
        value["request_variants"], template, f"{label}.request_variants"
    )
    fanout = _fanout(value["fanout"], request_shape, f"{label}.fanout")
    resumable_fanout = _resumable_fanout(
        value.get("resumable_fanout"), f"{label}.resumable_fanout"
    )
    if resumable_fanout is not None and fanout["strategy"] == "none":
        raise ValueError(f"{label}.resumable_fanout requires a non-empty fanout")
    pagination = _pagination(value["pagination"], f"{label}.pagination")
    window = _window_policy(
        value.get("request_window_policy"), template, f"{label}.request_window_policy"
    )
    completeness = _completeness(
        value["response_completeness"],
        fields=set(fields_by_name),
        template=template,
        window=window,
        label=f"{label}.response_completeness",
    )
    requested_fields = _string_list(
        value["requested_fields"], f"{label}.requested_fields", allow_empty=True
    )
    missing_requested = sorted(set(requested_fields) - set(fields_by_name))
    if missing_requested:
        raise ValueError(
            f"{label}.requested_fields references undeclared field(s): {', '.join(missing_requested)}"
        )
    empty_data_policy = _required_text(
        value["empty_data_policy"], f"{label}.empty_data_policy"
    )
    fixed_fields = (
        set() if completeness is None else set(completeness["fixed_field_matches"])
    )
    for fixed_field in fixed_fields:
        field = fields_by_name[fixed_field]
        if field["logical_type"] != "text" or field["nullable"]:
            raise ValueError(
                f"{label}.response_completeness.fixed_field_matches fields "
                "must be non-null text"
            )
    completeness_fields = set(primary_key) | fixed_fields
    if (
        completeness is not None
        and completeness["strategy"] == "one_row_per_calendar_date"
    ):
        date_field = completeness["date_field"]
        if (
            optional["as_of_field"] != date_field
            or optional["range_field"] != date_field
            or optional["partition_field"] != date_field
            or as_of_format != "yyyymmdd"
        ):
            raise ValueError(
                f"{label}.response_completeness.date_field must be the "
                "contract yyyymmdd as_of/range/partition field"
            )
        if set(primary_key) != {date_field, *fixed_fields}:
            raise ValueError(
                f"{label}.primary_key must exactly contain completeness "
                "date_field and fixed row fields"
            )
        if empty_data_policy != "forbidden":
            raise ValueError(
                f"{label}.empty_data_policy must be forbidden for calendar completeness"
            )
        completeness_fields.add(date_field)
    elif (
        completeness is not None
        and completeness["strategy"] == "single_partition_unique_primary_key"
    ):
        partition_field = completeness["partition_field"]
        has_invalid_business_time = (
            optional["as_of_field"] != partition_field
            or optional["range_field"] != partition_field
            or optional["partition_field"] != partition_field
            or as_of_format not in {"yyyymm", "yyyymmdd"}
        )
        omits_business_time = (
            optional["as_of_field"] is None
            and optional["range_field"] is None
            and optional["partition_field"] is None
            and as_of_format is None
        )
        if (
            has_invalid_business_time and not omits_business_time
        ) or partition_field not in primary_key:
            raise ValueError(
                f"{label}.response_completeness.partition_field must be the "
                "contract yyyymm or yyyymmdd primary-key partition field, or all "
                "business-time fields must be null"
            )
        completeness_fields.add(partition_field)
    elif (
        completeness is not None
        and completeness["strategy"] == "windowed_unique_primary_key"
    ):
        date_field = completeness["date_field"]
        fanout_field = completeness["fanout_field"]
        if (
            date_field not in primary_key
            or fanout_field not in primary_key
            or fanout is None
            or fanout["strategy"] == "none"
        ):
            raise ValueError(
                f"{label}.response_completeness windowed contract requires fanout "
                "and primary-key event time/source fields"
            )
        completeness_fields.update({date_field, fanout_field})
    if requested_fields:
        missing_completeness = sorted(completeness_fields - set(requested_fields))
        if missing_completeness:
            raise ValueError(
                f"{label}.requested_fields must include completeness field(s): "
                f"{', '.join(missing_completeness)}"
            )
    budgets_value = _mapping(value["budgets"], f"{label}.budgets")
    _reject_keys(budgets_value, _BUDGET_KEYS, f"{label}.budgets")
    budgets = {
        key: _required_positive_int(budgets_value[key], f"{label}.budgets.{key}")
        for key in sorted(_BUDGET_KEYS)
    }
    if window is not None and budgets["max_rows_per_attempt"] < window["max_span_days"]:
        raise ValueError(
            f"{label}.budgets.max_rows_per_attempt must cover max_span_days"
        )
    overrides: list[dict[str, str]] = []
    override_names: set[str] = set()
    for override_index, raw_override in enumerate(
        _sequence(value["reviewed_type_overrides"], f"{label}.reviewed_type_overrides")
    ):
        override_label = f"{label}.reviewed_type_overrides[{override_index}]"
        override = _mapping(raw_override, override_label)
        _reject_keys(override, _OVERRIDE_KEYS, override_label)
        normalized = {
            key: _required_text(override[key], f"{override_label}.{key}")
            for key in sorted(_OVERRIDE_KEYS)
        }
        field_name = normalized["field"]
        if field_name not in fields_by_name or field_name in override_names:
            raise ValueError(
                f"{override_label}.field must name one unique declared field"
            )
        field = fields_by_name[field_name]
        if (
            normalized["declared_source_type"] != field["declared_source_type"]
            or normalized["logical_type"] != field["logical_type"]
        ):
            raise ValueError(f"{override_label} must match the declared field contract")
        override_names.add(field_name)
        overrides.append(normalized)
    default_types = {"str": "text", "int": "integer", "float": "float"}
    for field in fields:
        expected = default_types.get(field["declared_source_type"])
        if (
            expected is not None
            and field["logical_type"] != expected
            and field["name"] not in override_names
        ):
            raise ValueError(
                f"{label}.fields {field['name']} changes declared type without reviewed override"
            )
    request_contract: dict[str, Any] = {}
    if require_input_fields:
        probe_state = _required_text(value["probe_state"], f"{label}.probe_state")
        if probe_state not in _PROBE_STATES:
            raise ValueError(f"{label}.probe_state is unsupported")
        probe_reasons = _string_list(
            value["probe_block_reasons"],
            f"{label}.probe_block_reasons",
            allow_empty=True,
        )
        if probe_reasons != sorted(probe_reasons) or not set(probe_reasons).issubset(
            _PROBE_BLOCK_REASONS
        ):
            raise ValueError(f"{label}.probe_block_reasons is invalid")
        if (probe_state == "executable") != (not probe_reasons):
            raise ValueError(f"{label}.probe_state has inconsistent reasons")
        ingest_state = _required_text(
            value["ingest_contract_state"], f"{label}.ingest_contract_state"
        )
        if ingest_state not in _INGEST_CONTRACT_STATES:
            raise ValueError(f"{label}.ingest_contract_state is unsupported")
        ingest_reasons = _string_list(
            value["ingest_contract_block_reasons"],
            f"{label}.ingest_contract_block_reasons",
            allow_empty=True,
        )
        if ingest_reasons != sorted(ingest_reasons) or not set(ingest_reasons).issubset(
            _INGEST_CONTRACT_BLOCK_REASONS
        ):
            raise ValueError(f"{label}.ingest_contract_block_reasons is invalid")
        if (ingest_state == "ready") != (not ingest_reasons):
            raise ValueError(f"{label}.ingest_contract_state has inconsistent reasons")
        request_contract = {
            "probe_state": probe_state,
            "probe_block_reasons": probe_reasons,
            "ingest_contract_state": ingest_state,
            "ingest_contract_block_reasons": ingest_reasons,
        }
    cadence = _required_text(value["cadence_class"], f"{label}.cadence_class")
    if cadence not in _CADENCE_CLASSES:
        raise ValueError(f"{label}.cadence_class is unsupported")
    point_in_time = _required_text(value["point_in_time"], f"{label}.point_in_time")
    if point_in_time not in {"current_snapshot", "append_only"}:
        raise ValueError(f"{label}.point_in_time is unsupported")
    if point_in_time == "current_snapshot" and not primary_key:
        raise ValueError(f"{label} current_snapshot requires a non-empty primary_key")
    known_future_horizon_days = _required_non_negative_int(
        value.get("known_future_horizon_days", 0),
        f"{label}.known_future_horizon_days",
    )
    entity_type = _required_text(value["entity_type"], f"{label}.entity_type")
    if known_future_horizon_days and entity_type != "trade_calendar":
        raise ValueError(
            f"{label}.known_future_horizon_days requires entity_type trade_calendar"
        )
    if value["data_classification"] != "objective_factual":
        raise ValueError(f"{label}.data_classification is unsupported")
    return {
        "dataset_id": _required_text(value["dataset_id"], f"{label}.dataset_id"),
        "aliases": _string_list(value["aliases"], f"{label}.aliases"),
        "domain": _required_text(value["domain"], f"{label}.domain"),
        "market": _required_text(value["market"], f"{label}.market"),
        "entity_type": entity_type,
        "data_classification": "objective_factual",
        "provider": contract_provider,
        "api_name": api_name,
        "source_document_url": _required_text(
            value["source_document_url"], f"{label}.source_document_url"
        ),
        "source_document_sha256": source_hash,
        "schema_version": schema_version,
        **({"input_fields": input_fields} if input_fields is not None else {}),
        "fields": fields,
        "primary_key": primary_key,
        "default_projection": default_projection,
        **optional,
        "as_of_format": as_of_format,
        "cadence_class": cadence,
        "timezone": _required_text(value["timezone"], f"{label}.timezone"),
        "freshness_sla_seconds": _required_positive_int(
            value["freshness_sla_seconds"], f"{label}.freshness_sla_seconds"
        ),
        **(
            {"known_future_horizon_days": known_future_horizon_days}
            if known_future_horizon_days
            else {}
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
        "request_shape": request_shape,
        "request_template": template,
        "request_variants": variants,
        "fanout": fanout,
        **({"resumable_fanout": resumable_fanout} if resumable_fanout is not None else {}),
        "pagination": pagination,
        "request_window_policy": window,
        "response_completeness": completeness,
        "requested_fields": requested_fields,
        "budgets": budgets,
        "reviewed_type_overrides": overrides,
        **request_contract,
    }


def load_upstream_contract_bundle(document: Mapping[str, Any]) -> dict[str, Any]:
    """Strictly normalize one pinned upstream contract bundle."""

    root = _mapping(deepcopy(document), "upstream contract bundle")
    _reject_keys(root, _ROOT_KEYS, "upstream contract bundle")
    if type(root["version"]) is not int or root["version"] != 1:
        raise ValueError("upstream contract bundle.version must be integer 1")
    provider = _required_text(root["provider"], "upstream contract bundle.provider")
    if provider not in _BUNDLE_PROVIDERS:
        raise ValueError("upstream contract bundle.provider is unsupported")
    provenance = _mapping(root["provenance"], "upstream contract bundle.provenance")
    _reject_keys(provenance, _PROVENANCE_KEYS, "upstream contract bundle.provenance")
    normalized_provenance = {
        key: _required_text(
            provenance[key], f"upstream contract bundle.provenance.{key}"
        )
        for key in sorted(_PROVENANCE_KEYS)
    }
    if _COMMIT_PATTERN.fullmatch(normalized_provenance["pinned_commit"]) is None:
        raise ValueError("upstream contract bundle provenance commit must be a git SHA")
    if _HASH_PATTERN.fullmatch(normalized_provenance["index_sha256"]) is None:
        raise ValueError("upstream contract bundle provenance index must be SHA-256")
    raw_contracts = _sequence(root["contracts"], "upstream contract bundle.contracts")
    contract_values = [
        _mapping(item, f"upstream contracts[{index}]")
        for index, item in enumerate(raw_contracts)
    ]
    # The phase-1 compiler reuses this normalizer before it attaches official
    # input declarations. Preserve that all-or-none pre-attachment path without
    # synthesizing defaults; the downstream compiler below still rejects it.
    input_field_presence = ["input_fields" in item for item in contract_values]
    if any(input_field_presence) and not all(input_field_presence):
        missing_index = input_field_presence.index(False)
        raise ValueError(
            f"upstream contracts[{missing_index}] is missing key(s): input_fields"
        )
    require_input_fields = bool(contract_values) and all(input_field_presence)
    contracts = [
        _normalized_contract(
            item,
            index=index,
            provider=provider,
            require_input_fields=require_input_fields,
        )
        for index, item in enumerate(contract_values)
    ]
    by_dataset: dict[str, dict[str, Any]] = {}
    by_api: dict[str, str] = {}
    aliases: set[str] = set()
    for contract in contracts:
        dataset_id = contract["dataset_id"]
        api_name = contract["api_name"]
        if dataset_id in by_dataset:
            raise ValueError(
                f"duplicate dataset_id in upstream contracts: {dataset_id}"
            )
        if api_name in by_api:
            raise ValueError(
                f"duplicate provider API in upstream contracts: {api_name}"
            )
        overlap = aliases.intersection(contract["aliases"])
        if overlap:
            raise ValueError(
                f"duplicate alias in upstream contracts: {sorted(overlap)[0]}"
            )
        if dataset_id in aliases or any(
            alias in by_dataset for alias in contract["aliases"]
        ):
            raise ValueError("dataset identity conflicts with an alias")
        by_dataset[dataset_id] = contract
        by_api[api_name] = dataset_id
        aliases.update(contract["aliases"])
    return {
        "version": 1,
        "bundle_id": _required_text(
            root["bundle_id"], "upstream contract bundle.bundle_id"
        ),
        "provider": provider,
        "provenance": normalized_provenance,
        "contracts": [by_dataset[key] for key in sorted(by_dataset)],
    }


def _apply_observed_schema_subset(
    contract: Mapping[str, Any], observation: Mapping[str, Any] | None
) -> dict[str, Any]:
    normalized = deepcopy(dict(contract))
    if observation is None:
        return normalized
    missing = set(observation["schema_missing_fields"])
    if not missing:
        return normalized
    if observation["classification"] != "schema_subset":
        raise ValueError("schema missing fields require schema_subset classification")
    declared = {field["name"] for field in normalized["fields"]}
    unknown = sorted(missing - declared)
    if unknown:
        raise ValueError(
            f"QuickSync schema subset references undeclared field: "
            f"{normalized['api_name']}/{unknown[0]}"
        )
    completeness = normalized["response_completeness"]
    protected = set(normalized["primary_key"])
    protected.update(
        field
        for field in (
            normalized["as_of_field"],
            normalized["range_field"],
            normalized["partition_field"],
        )
        if field is not None
    )
    if completeness is not None:
        protected.update(completeness["fixed_field_matches"])
        for key in ("date_field", "partition_field"):
            field = completeness.get(key)
            if field is not None:
                protected.add(field)
        snapshot_field = completeness.get("snapshot_field")
        if snapshot_field is not None:
            protected.add(snapshot_field)
    overlap = sorted(missing & protected)
    if overlap:
        raise ValueError(
            f"QuickSync schema subset cannot remove structural field: "
            f"{normalized['api_name']}/{overlap[0]}"
        )
    normalized["fields"] = [
        field for field in normalized["fields"] if field["name"] not in missing
    ]
    normalized["default_projection"] = [
        field for field in normalized["default_projection"] if field not in missing
    ]
    normalized["requested_fields"] = [
        field for field in normalized["requested_fields"] if field not in missing
    ]
    normalized["reviewed_type_overrides"] = [
        item
        for item in normalized["reviewed_type_overrides"]
        if item["field"] not in missing
    ]
    if not normalized["fields"] or not normalized["default_projection"]:
        raise ValueError(
            f"QuickSync schema subset cannot empty schema/default projection: "
            f"{normalized['api_name']}"
        )
    return normalized


def _apply_observed_response_contract(
    contract: Mapping[str, Any], observation: Mapping[str, Any] | None
) -> dict[str, Any]:
    """Apply an evidence-bound transport response delta without changing behavior."""

    normalized = deepcopy(dict(contract))
    if observation is None:
        return normalized
    override = observation.get("response_contract_override")
    if override is None:
        return normalized

    missing = set(override["missing_fields"])
    fields_by_name = {field["name"]: field for field in normalized["fields"]}
    protected = set(normalized["primary_key"])
    protected.update(
        field
        for field in (
            normalized["as_of_field"],
            normalized["range_field"],
            normalized["partition_field"],
        )
        if field is not None
    )
    completeness = normalized["response_completeness"]
    if completeness is not None:
        protected.update(completeness["fixed_field_matches"])
        for key in ("date_field", "partition_field"):
            field = completeness.get(key)
            if field is not None:
                protected.add(field)
        snapshot_field = completeness.get("snapshot_field")
        if snapshot_field is not None:
            protected.add(snapshot_field)
    overlap = sorted(missing & protected)
    if overlap:
        raise ValueError(
            "QuickSync response contract cannot remove structural field: "
            f"{normalized['api_name']}/{overlap[0]}"
        )

    for type_override in override["type_overrides"]:
        field = fields_by_name[type_override["field"]]
        field["declared_source_type"] = type_override["declared_source_type"]
        field["logical_type"] = type_override["logical_type"]
    normalized["fields"] = [
        field for field in normalized["fields"] if field["name"] not in missing
    ]
    normalized["fields"].extend(deepcopy(override["additional_fields"]))
    normalized["default_projection"] = [
        field for field in normalized["default_projection"] if field not in missing
    ]
    normalized["default_projection"].extend(
        field["name"] for field in override["additional_fields"]
    )
    normalized["requested_fields"] = [
        field for field in normalized["requested_fields"] if field not in missing
    ]
    # A selectable field observed only in the QuickSync response extension
    # must be requested explicitly.  Otherwise it appears in the public
    # schema/default projection but is absent from every newly collected row.
    normalized["requested_fields"].extend(
        field["name"]
        for field in override["additional_fields"]
        if field["selectable"]
    )
    normalized["reviewed_type_overrides"] = [
        item
        for item in normalized["reviewed_type_overrides"]
        if item["field"] not in missing
    ]
    normalized["schema_version"] = override["schema_version"]
    if not normalized["fields"] or not normalized["default_projection"]:
        raise ValueError(
            f"QuickSync response contract cannot empty schema/default projection: "
            f"{normalized['api_name']}"
        )
    return normalized


def _compiled_dataset(
    contract: Mapping[str, Any], activation: Mapping[str, Any] | None
) -> dict[str, Any]:
    known_future_horizon_days = contract.get("known_future_horizon_days", 0)
    probe_state = (
        contract["probe_state"]
        if activation is None
        else activation.get("effective_probe_state", contract["probe_state"])
    )
    probe_block_reasons = (
        list(contract["probe_block_reasons"])
        if activation is None
        else list(
            activation.get(
                "effective_probe_block_reasons", contract["probe_block_reasons"]
            )
        )
    )
    ingest_contract_state = (
        contract["ingest_contract_state"]
        if activation is None
        else activation.get(
            "effective_ingest_contract_state", contract["ingest_contract_state"]
        )
    )
    ingest_contract_block_reasons = (
        list(contract["ingest_contract_block_reasons"])
        if activation is None
        else list(
            activation.get(
                "effective_ingest_contract_block_reasons",
                contract["ingest_contract_block_reasons"],
            )
        )
    )
    if activation is not None and activation["activation_state"] == "active":
        if probe_state != "executable":
            raise ValueError(
                f"{contract['api_name']} cannot activate while probe_state is blocked"
            )
        if ingest_contract_state != "ready":
            raise ValueError(
                f"{contract['api_name']} cannot activate while ingest contract is blocked"
            )
    activation_state = (
        "paused" if activation is None else activation["activation_state"]
    )
    budgets = deepcopy(contract["budgets"])
    if activation_state == "active":
        declared_fields = max(
            len(contract["fields"]), len(contract["requested_fields"])
        )
        field_budget = declared_fields + _PROVIDER_SCAN_FIELD_HEADROOM
        max_depth = budgets["max_nesting_depth"] + _PROVIDER_SCAN_ENVELOPE_DEPTH
        if (
            field_budget > _PROVIDER_SCAN_ABSOLUTE_MAX_FIELDS
            or max_depth > _PROVIDER_SCAN_ABSOLUTE_MAX_DEPTH
        ):
            activation_state = "paused"
        else:
            safe_row_limit = (
                _PROVIDER_SCAN_ABSOLUTE_MAX_NODES
                - _PROVIDER_SCAN_FIXED_NODE_HEADROOM
                - 1
            ) // (1 + 2 * field_budget)
            window = contract["request_window_policy"]
            if safe_row_limit < 1 or (
                window is not None and safe_row_limit < window["max_span_days"]
            ):
                activation_state = "paused"
            else:
                budgets["max_rows_per_attempt"] = min(
                    budgets["max_rows_per_attempt"], safe_row_limit
                )
    binding = {
        "provider": contract["provider"],
        "api_name": contract["api_name"],
        "adapter_version": _PROVIDER_ADAPTER_VERSIONS[contract["provider"]],
        "read_discriminator_value": f"{contract['provider']}_{contract['api_name']}",
        "entitlement_state": "unknown"
        if activation is None
        else activation["entitlement_state"],
        "activation_state": activation_state,
        "probe_state": probe_state,
        "probe_block_reasons": probe_block_reasons,
        "ingest_contract_state": ingest_contract_state,
        "ingest_contract_block_reasons": ingest_contract_block_reasons,
        "target_tables": [PROVIDER_NATIVE_TABLE],
        "input_fields": deepcopy(contract["input_fields"]),
        "request_shape": contract["request_shape"],
        "request_template": deepcopy(contract["request_template"]),
        "request_variants": deepcopy(contract["request_variants"]),
        "fanout": deepcopy(contract["fanout"]),
        **({"resumable_fanout": deepcopy(contract["resumable_fanout"])} if contract.get("resumable_fanout") is not None else {}),
        "pagination": deepcopy(contract["pagination"]),
        "request_window_policy": deepcopy(contract["request_window_policy"]),
        "response_completeness": deepcopy(contract["response_completeness"]),
        "requested_fields": list(contract["requested_fields"]),
        **budgets,
    }
    return {
        "dataset_id": contract["dataset_id"],
        "aliases": list(contract["aliases"]),
        "domain": contract["domain"],
        "market": contract["market"],
        "entity_type": contract["entity_type"],
        "data_classification": contract["data_classification"],
        "schema_version": contract["schema_version"],
        "cadence_class": contract["cadence_class"],
        "timezone": contract["timezone"],
        "freshness_sla_seconds": contract["freshness_sla_seconds"],
        **(
            {"known_future_horizon_days": known_future_horizon_days}
            if known_future_horizon_days
            else {}
        ),
        "provider_bindings": [binding],
        "read_model_adapter": {
            "adapter_version": READ_ADAPTER_VERSION,
            "primary_table": PROVIDER_NATIVE_TABLE,
            "fixed_field_filters": [],
            "storage_kind": "provider_native_rows",
            "row_key_strategy": {
                "current_snapshot": "primary_key",
                "append_only": "payload_hash",
            }[contract["point_in_time"]],
        },
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
        "primary_key": list(contract["primary_key"]),
        "default_projection": list(contract["default_projection"]),
        "as_of_field": contract["as_of_field"],
        "as_of_format": contract["as_of_format"],
        "range_field": contract["range_field"],
        "partition_field": contract["partition_field"],
        "point_in_time": contract["point_in_time"],
        "backfill_policy": contract["backfill_policy"],
        "empty_data_policy": contract["empty_data_policy"],
        "required_scope": contract["required_scope"],
        "quota_class": contract["quota_class"],
    }


def compile_provider_native_registry(
    upstream_contracts: Mapping[str, Any],
    *,
    observations_document: Mapping[str, Any] | None = None,
    activation_evidence_document: Mapping[str, Any] | None = None,
    supplemental_contracts: Sequence[Mapping[str, Any]] | None = None,
    query_defaults: Mapping[str, Any] | None = None,
    compilation_mode: str = FORMAL_COMPILATION_MODE,
) -> dict[str, Any]:
    """Return the deterministic single-authority registry document."""

    if compilation_mode not in COMPILATION_MODES:
        raise ValueError(f"unsupported compilation mode: {compilation_mode!r}")
    if (
        compilation_mode == PREACTIVATION_COMPILATION_MODE
        and activation_evidence_document is None
    ):
        raise ValueError("preactivation candidate mode requires activation evidence")

    bundle = load_upstream_contract_bundle(upstream_contracts)
    supplemental_bundles = [
        load_upstream_contract_bundle(document)
        for document in (supplemental_contracts or ())
    ]
    contracts = list(bundle["contracts"])
    seen_dataset_ids = {contract["dataset_id"] for contract in contracts}
    seen_api_names = {contract["api_name"] for contract in contracts}
    seen_aliases = {
        alias for contract in contracts for alias in contract["aliases"]
    }
    for supplemental in supplemental_bundles:
        if supplemental["provider"] == bundle["provider"]:
            raise ValueError(
                "supplemental contract bundle duplicates the primary provider"
            )
        for contract in supplemental["contracts"]:
            if (
                contract["dataset_id"] in seen_dataset_ids
                or contract["api_name"] in seen_api_names
                or seen_aliases.intersection(contract["aliases"])
                or contract["dataset_id"] in seen_aliases
                or any(alias in seen_dataset_ids for alias in contract["aliases"])
            ):
                raise ValueError(
                    "supplemental contract identity conflicts with the registry: "
                    f"{contract['dataset_id']}"
                )
            seen_dataset_ids.add(contract["dataset_id"])
            seen_api_names.add(contract["api_name"])
            seen_aliases.update(contract["aliases"])
            contracts.append(contract)
    missing_input_contracts = [
        contract["api_name"]
        for contract in contracts
        if "input_fields" not in contract
    ]
    if missing_input_contracts:
        raise ValueError(
            "upstream contract bundle is missing input_fields for API: "
            f"{missing_input_contracts[0]}"
        )
    observations = _observation_index(observations_document, bundle["contracts"])
    activation_evidence = (
        _activation_evidence_index(
            activation_evidence_document,
            bundle["contracts"],
            observations_document,
            observations,
        )
        if compilation_mode == PREACTIVATION_COMPILATION_MODE
        else {}
    )
    activation_index = (
        activation_evidence
        if compilation_mode == PREACTIVATION_COMPILATION_MODE
        else observations
    )
    return {
        "version": 1,
        "query_defaults": _query_defaults(query_defaults),
        "datasets": [
            _compiled_dataset(
                _apply_observed_schema_subset(
                    _apply_observed_response_contract(
                        contract,
                        observations.get(
                            (contract["dataset_id"], contract["provider"])
                        ),
                    ),
                    observations.get((contract["dataset_id"], contract["provider"])),
                ),
                activation_index.get(
                    (contract["dataset_id"], contract["provider"]),
                    observations.get((contract["dataset_id"], contract["provider"])),
                ),
            )
            for contract in contracts
        ],
    }


def render_registry(registry: Mapping[str, Any]) -> str:
    """Render the registry with stable key and dataset ordering."""

    rendered = yaml.safe_dump(
        dict(registry),
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=False,
        width=100,
    )
    # Keep very large literal fanouts on one deterministic line.  This is the
    # repository's established representation for bounded cohorts (the normal
    # small literal fanouts remain block lists), and avoids a formatting-only
    # drift when the compiler starts sourcing a large cohort from contracts.
    lines = rendered.splitlines()
    compacted: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        if line.strip() == "values:" and index + 1 < len(lines):
            indent = line[: len(line) - len(line.lstrip())]
            values: list[str] = []
            cursor = index + 1
            item_prefix = f"{indent}- "
            while cursor < len(lines) and lines[cursor].startswith(item_prefix):
                values.append(lines[cursor][len(item_prefix) :])
                cursor += 1
            if len(values) > 100:
                compacted.append(f"{indent}values: [{', '.join(values)}]")
                index = cursor
                continue
        compacted.append(line)
        index += 1
    return "\n".join(compacted) + "\n"


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
            raise ValueError("YAML mapping key must be hashable") from exc
        if duplicate:
            raise ValueError(f"duplicate YAML mapping key: {key}")
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_DuplicateKeySafeLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)


def _load_yaml(path: Path, label: str) -> dict[str, Any]:
    raw = yaml.load(path.read_text(encoding="utf-8"), Loader=_DuplicateKeySafeLoader)
    return _mapping(raw, label)


def _load_activation_evidence(
    path: Path,
    *,
    observations_document: Mapping[str, Any],
    observations_sha256: str,
) -> dict[str, Any]:
    """Bind raw probe sidecars to the exact input bytes before normalization.

    The probe writes a byte hash because its request plan is created from the
    file. The compiler uses the parsed canonical mapping internally. Validate
    the former at the CLI boundary, then translate only that binding for the
    existing deterministic compiler path.
    """

    evidence = _load_yaml(path, "HTTPS activation evidence")
    if evidence.get("schema_version") != "tradingdatas.quicksync.https_probe_evidence.v1":
        return evidence
    if evidence.get("transport_observations_sha256") != observations_sha256:
        raise ValueError("raw HTTPS probe evidence transport observations drifted")
    stable_observations = yaml.safe_dump(
        dict(observations_document),
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=False,
        width=100,
    ).encode("utf-8")
    normalized = deepcopy(evidence)
    normalized["transport_observations_sha256"] = hashlib.sha256(
        stable_observations
    ).hexdigest()
    return normalized


def _atomic_write(path: Path, content: str) -> None:
    if not path.parent.is_dir():
        raise ValueError(f"output parent does not exist: {path.parent}")
    descriptor, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
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
    parser.add_argument(
        "--upstream-contracts", type=Path, default=DEFAULT_UPSTREAM_CONTRACTS_PATH
    )
    parser.add_argument("--observations", type=Path, default=DEFAULT_OBSERVATIONS_PATH)
    parser.add_argument(
        "--activation-evidence",
        type=Path,
        default=None,
    )
    parser.add_argument(
        "--supplemental-contracts",
        type=Path,
        nargs="*",
        default=list(DEFAULT_SUPPLEMENTAL_CONTRACTS_PATHS),
    )
    parser.add_argument(
        "--compilation-mode",
        choices=sorted(COMPILATION_MODES),
        default=FORMAL_COMPILATION_MODE,
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    required_inputs = [args.upstream_contracts, args.observations]
    if args.compilation_mode == PREACTIVATION_COMPILATION_MODE:
        required_inputs.append(args.activation_evidence)
    required_inputs.extend(args.supplemental_contracts)
    for path in required_inputs:
        if path is None:
            continue
        if not path.is_file():
            parser.error(f"input file does not exist: {path}")
    if (
        args.compilation_mode == PREACTIVATION_COMPILATION_MODE
        and args.activation_evidence is None
    ):
        parser.error("preactivation candidate mode requires --activation-evidence")
    if args.compilation_mode == PREACTIVATION_COMPILATION_MODE:
        activation_evidence = args.activation_evidence.resolve()
        repository_root = REPOSITORY_ROOT.resolve()
        if (
            activation_evidence == repository_root
            or repository_root in activation_evidence.parents
        ):
            parser.error("activation evidence must be outside the repository")
    output = args.output.resolve(strict=False)
    protected_inputs = {
        args.upstream_contracts.resolve(),
        args.observations.resolve(),
        *(path.resolve() for path in args.supplemental_contracts),
    }
    if args.compilation_mode == PREACTIVATION_COMPILATION_MODE:
        protected_inputs.add(args.activation_evidence.resolve())
    if output in protected_inputs:
        parser.error("refusing to overwrite an input file")
    if args.compilation_mode == PREACTIVATION_COMPILATION_MODE and (
        output == DEFAULT_OUTPUT_PATH.resolve()
        or REPOSITORY_ROOT.resolve() in output.parents
    ):
        parser.error(
            "preactivation candidate cannot overwrite the checked registry or write inside the repository"
        )
    observations_bytes = args.observations.read_bytes()
    observations_document = _load_yaml(args.observations, "QuickSync observations")
    registry = compile_provider_native_registry(
        _load_yaml(args.upstream_contracts, "upstream contract bundle"),
        observations_document=observations_document,
        activation_evidence_document=(
            None
            if args.compilation_mode != PREACTIVATION_COMPILATION_MODE
            else _load_activation_evidence(
                args.activation_evidence,
                observations_document=observations_document,
                observations_sha256=hashlib.sha256(observations_bytes).hexdigest(),
            )
        ),
        supplemental_contracts=[
            _load_yaml(path, "supplemental contract bundle")
            for path in args.supplemental_contracts
        ],
        query_defaults=DEFAULT_QUERY_DEFAULTS,
        compilation_mode=args.compilation_mode,
    )
    if not registry["datasets"]:
        parser.error("refusing to write a registry with zero contracts")
    _atomic_write(args.output, render_registry(registry))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

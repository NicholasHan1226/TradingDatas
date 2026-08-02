#!/usr/bin/env python3
"""Compile all official in-scope Tushare documents into one runtime bundle.

Five separately reviewed contracts keep their stronger request, identity and
cadence declarations. Every other official contract is catalog-visible but
conservatively append-only and remains paused because it has no activation
entry. This keeps capability discovery complete without guessing entitlement,
request parameters, primary keys or collection frequency.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timedelta
import hashlib
import math
import os
from pathlib import Path
import re
import tempfile
from typing import Any, Mapping
from zoneinfo import ZoneInfo

import yaml

if __package__:
    from tools.compile_provider_native_registry import load_upstream_contract_bundle
else:  # pragma: no cover - exercised by the checked-in CLI test
    from compile_provider_native_registry import load_upstream_contract_bundle


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DOCUMENTS = ROOT / "config" / "tushare_document_contracts.v1.yaml"
DEFAULT_REVIEWED = ROOT / "config" / "tushare_reviewed_contracts.v1.yaml"
DEFAULT_POLICY = ROOT / "config" / "tushare_runtime_contract_policy.v1.yaml"
DEFAULT_CADENCE_POLICY = ROOT / "config" / "tushare_cadence_policy.v1.yaml"
DEFAULT_REQUEST_OBSERVATIONS = ROOT / "config" / "tushare_request_observations.v1.yaml"
DEFAULT_TRANSPORT_OBSERVATIONS = (
    ROOT / "config" / "quicksync_interface_observations.v1.yaml"
)
DEFAULT_OUTPUT = ROOT / "config" / "tushare_upstream_contracts.v1.yaml"

_SAFE_API_NAME = re.compile(r"[a-z][a-z0-9_]{0,63}\Z")
_SAFE_FIELD_NAME = re.compile(r"[A-Za-z0-9_]{1,64}\Z")
_SAFE_PARAMETER_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,63}\Z")
_SAFE_SEED_FIELD = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,63}\Z")
_SAFE_DATASET_ID = re.compile(r"[a-z][a-z0-9]*(?:[._-][a-z0-9]+){1,15}\Z")
_SAFE_REASON_CODE = re.compile(r"[a-z][a-z0-9_]{0,63}\Z")
_PUBLIC_EVIDENCE_TEXT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:+/\-TZ]{0,255}\Z")
_CREDENTIAL_TEXT = re.compile(
    r"(?:access[_-]?token|refresh[_-]?token|auth[_-]?token|bearer|api[_-]?key|"
    r"password|passwd|credential|client[_-]?secret|secret|cookie)",
    re.IGNORECASE,
)
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_SEMANTIC_VERSION = re.compile(r"[1-9][0-9]*\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\Z")
_EXPECTED_IN_SCOPE_CONTRACTS = 190
_INPUT_FIELD_KEYS = frozenset({"name", "declared_type", "description", "required"})
_INPUT_DECLARED_TYPES = frozenset(
    {
        "None",
        "datetime",
        "float",
        "int",
        "intint",
        "str",
    }
)
_INPUT_REQUIRED_VALUES: Mapping[str, bool | None] = {
    "Y": True,
    "N": False,
    "": None,
}
_POLICY_KEYS = frozenset(
    {
        "version",
        "policy_id",
        "provider",
        "source_snapshot_id",
        "source_snapshot_canonical_sha256",
        "catalog_only_defaults",
    }
)
_CADENCE_POLICY_KEYS = frozenset(
    {
        "version",
        "policy_id",
        "provider",
        "source_snapshot_id",
        "source_snapshot_canonical_sha256",
        "entries",
    }
)
_CADENCE_POLICY_ENTRY_KEYS = frozenset(
    {
        "api_name",
        "cadence_class",
        "freshness_sla_seconds",
        "source_document_sha256",
        "reason_code",
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
_CADENCE_REASON_CLASSES: Mapping[str, frozenset[str]] = {
    "doc_explicit_session_minute": frozenset({"session_minute"}),
    "doc_explicit_postclose_daily": frozenset({"postclose_daily"}),
    "doc_explicit_daily_reference": frozenset({"daily_reference"}),
    "doc_explicit_weekly": frozenset({"weekly"}),
    "doc_explicit_monthly": frozenset({"monthly"}),
    "doc_explicit_quarterly_reporting": frozenset({"quarterly_reporting"}),
    "doc_explicit_event": frozenset({"event"}),
    "ambiguous_insufficient_document_frequency": frozenset({"on_demand"}),
    "no_document_frequency_evidence": frozenset({"on_demand"}),
    "reviewed_contract_exact": _CADENCE_CLASSES,
}
_DEFAULT_KEYS = frozenset(
    {
        "dataset_id_prefix",
        "domain",
        "market",
        "entity_type",
        "data_classification",
        "schema_version",
        "cadence_class",
        "timezone",
        "freshness_sla_seconds",
        "point_in_time",
        "backfill_policy",
        "empty_data_policy",
        "required_scope",
        "quota_class",
        "request_shape",
        "max_default_projection_fields",
        "budgets",
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
_REQUEST_OBSERVATION_ROOT_KEYS = frozenset(
    {
        "version",
        "contract_id",
        "provider",
        "transport_service",
        "authority_scope",
        "production_ready",
        "provenance",
        "normalization_policy",
        "reason_codes",
        "counts",
        "entries",
    }
)
_REQUEST_OBSERVATION_ENTRY_KEYS = frozenset(
    {
        "api_name",
        "scope_labels",
        "transport_observation_class",
        "request_shape",
        "probe_state",
        "probe_block_reasons",
        "ingest_contract_state",
        "ingest_contract_block_reasons",
        "unresolved_parameter_keys",
        "parameters",
        "row_limit_observation",
        "request_variants",
    }
)
_REQUEST_OBSERVATION_REQUIRED_ENTRY_KEYS = _REQUEST_OBSERVATION_ENTRY_KEYS - {
    "request_variants"
}
_REQUEST_OBSERVATION_PROVENANCE_REQUIRED_KEYS = frozenset(
    {
        "official_contracts",
        "quicksync_interface_observations",
        "reviewed_contract_bundle",
        "registered_contract_bundle",
        "matrix_evidence",
        "api_names_sha256",
        "interface_count",
    }
)
_REQUEST_OBSERVATION_PROVENANCE_OPTIONAL_KEYS = frozenset(
    {"migration_request_profiles"}
)
_REQUEST_OBSERVATION_SOURCE_KEYS = frozenset({"path", "sha256"})
_REQUEST_OBSERVATION_MIGRATION_KEYS = frozenset({"path", "sha256", "authority", "role"})
_REQUEST_OBSERVATION_MATRIX_KEYS = frozenset(
    {
        "schema_version",
        "sha256",
        "observed_at",
        "api_names_sha256",
        "interface_count",
        "interface_probe_scheme",
        "production_ready",
    }
)
_NORMALIZATION_POLICY_KEYS = frozenset(
    {
        "allowed_parameter_sources",
        "allowed_transforms",
        "max_abs_offset_seconds",
        "required_true_must_be_mapped_or_probe_blocked",
        "required_unknown_must_be_probe_blocked",
        "blocked_plan_params_must_be_empty",
        "ingest_contract_is_independent_from_probe",
    }
)
_REASON_CODE_KEYS = frozenset({"probe", "ingest_contract"})
_PARAMETER_SOURCES = frozenset(
    {
        "dataset_field",
        "literal",
        "literal_values",
        "run_clock",
        "scheduled_partition",
    }
)
_PARAMETER_TRANSFORMS = frozenset(
    {
        "identity",
        "yyyymmdd",
        "yyyymm",
        "yyyy_qn",
        "yyyyww",
        "local_datetime_seconds",
        "rfc3339",
    }
)
_PROBE_STATES = frozenset({"executable", "blocked"})
_REQUEST_ACTIVATION_STATES = frozenset({"ready", "blocked"})
_REQUEST_SHAPES = frozenset(
    {
        "snapshot_or_date_range",
        "entity_fanout",
        "dimension_fanout",
        "event_or_intraday_window",
    }
)
_MAX_ABS_OFFSET_SECONDS = 31_622_400
_REQUEST_OBSERVATION_PROBE_REASONS = frozenset(
    {
        "dependency_seed_receipt_unresolved",
        "official_requiredness_unknown",
        "request_anchor_unresolved",
        "required_enum_unresolved",
        "required_parameter_unresolved",
    }
)
_REQUEST_OBSERVATION_ACTIVATION_REASONS = _REQUEST_OBSERVATION_PROBE_REASONS | {
    "response_completeness_unresolved_at_observed_limit"
}
_WINDOW_FORMATS = _PARAMETER_TRANSFORMS


class RuntimeContractCompilationError(ValueError):
    """The official contract set cannot be compiled without inference."""


def _mapping(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise RuntimeContractCompilationError(f"{label} must be a mapping")
    return value


def _list(value: object, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise RuntimeContractCompilationError(f"{label} must be a list")
    return value


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RuntimeContractCompilationError(f"{label} must be non-empty text")
    return value.strip()


def _positive_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise RuntimeContractCompilationError(f"{label} must be a positive integer")
    return value


def _exact_keys(value: Mapping[str, Any], expected: frozenset[str], label: str) -> None:
    unknown = sorted(set(value) - expected)
    missing = sorted(expected - set(value))
    if unknown or missing:
        details = []
        if unknown:
            details.append(f"unknown={','.join(unknown)}")
        if missing:
            details.append(f"missing={','.join(missing)}")
        raise RuntimeContractCompilationError(
            f"{label} keys invalid: {'; '.join(details)}"
        )


def _canonical_sha256(value: object) -> str:
    rendered = yaml.safe_dump(
        value,
        allow_unicode=True,
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(rendered).hexdigest()


def _yaml_mapping_from_bytes(raw: bytes, *, label: str) -> dict[str, Any]:
    if not isinstance(raw, bytes):
        raise RuntimeContractCompilationError(f"{label} must be raw bytes")
    try:
        value = yaml.safe_load(raw.decode("utf-8"))
    except (UnicodeError, yaml.YAMLError) as exc:
        raise RuntimeContractCompilationError(
            f"failed to parse {label}: {exc}"
        ) from exc
    return _mapping(value, label)


def _bound_yaml_mapping(
    raw: bytes,
    claimed_sha256: object,
    *,
    label: str,
) -> tuple[dict[str, Any], str]:
    """Parse an in-memory authority only after binding its exact bytes."""

    if not isinstance(raw, bytes):
        raise RuntimeContractCompilationError(f"{label} must be raw bytes")
    actual_sha256 = hashlib.sha256(raw).hexdigest()
    expected_sha256 = _sha256_text(claimed_sha256, f"{label} SHA")
    if actual_sha256 != expected_sha256:
        raise RuntimeContractCompilationError(f"{label} bytes do not match")
    return _yaml_mapping_from_bytes(raw, label=label), actual_sha256


def _sha256_text(value: object, label: str) -> str:
    text = _text(value, label)
    if _SHA256.fullmatch(text) is None:
        raise RuntimeContractCompilationError(f"{label} must be SHA-256")
    return text


def _sorted_unique_text_list(
    value: object,
    *,
    label: str,
    allowed: frozenset[str] | None = None,
    allow_empty: bool = True,
) -> list[str]:
    items = _list(value, label)
    normalized = [_text(item, f"{label}[{index}]") for index, item in enumerate(items)]
    if not allow_empty and not normalized:
        raise RuntimeContractCompilationError(f"{label} must not be empty")
    if normalized != sorted(set(normalized)):
        raise RuntimeContractCompilationError(f"{label} must be sorted and unique")
    if allowed is not None:
        unsupported = sorted(set(normalized) - allowed)
        if unsupported:
            raise RuntimeContractCompilationError(
                f"{label} contains unsupported value: {unsupported[0]}"
            )
    return normalized


def _reject_unknown_and_missing_keys(
    value: Mapping[str, Any],
    *,
    allowed: frozenset[str],
    required: frozenset[str],
    label: str,
) -> None:
    unknown = sorted(set(value) - allowed)
    missing = sorted(required - set(value))
    if unknown or missing:
        details = []
        if unknown:
            details.append(f"unknown={','.join(unknown)}")
        if missing:
            details.append(f"missing={','.join(missing)}")
        raise RuntimeContractCompilationError(
            f"{label} keys invalid: {'; '.join(details)}"
        )


def _request_observation_metadata(
    document: Mapping[str, Any],
    *,
    official_contract_sha256: str,
    transport_observations_sha256: str,
) -> Mapping[str, Any]:
    provenance = _mapping(document["provenance"], "request observations.provenance")
    provenance_allowed = (
        _REQUEST_OBSERVATION_PROVENANCE_REQUIRED_KEYS
        | _REQUEST_OBSERVATION_PROVENANCE_OPTIONAL_KEYS
    )
    _reject_unknown_and_missing_keys(
        provenance,
        allowed=provenance_allowed,
        required=_REQUEST_OBSERVATION_PROVENANCE_REQUIRED_KEYS,
        label="request observations.provenance",
    )
    official = _mapping(
        provenance["official_contracts"],
        "request observations.provenance.official_contracts",
    )
    _exact_keys(
        official,
        _REQUEST_OBSERVATION_SOURCE_KEYS,
        "request observations.provenance.official_contracts",
    )
    observed = _mapping(
        provenance["quicksync_interface_observations"],
        "request observations.provenance.quicksync_interface_observations",
    )
    _exact_keys(
        observed,
        _REQUEST_OBSERVATION_SOURCE_KEYS,
        "request observations.provenance.quicksync_interface_observations",
    )
    reviewed = _mapping(
        provenance["reviewed_contract_bundle"],
        "request observations.provenance.reviewed_contract_bundle",
    )
    _exact_keys(
        reviewed,
        _REQUEST_OBSERVATION_SOURCE_KEYS,
        "request observations.provenance.reviewed_contract_bundle",
    )
    registered = _mapping(
        provenance["registered_contract_bundle"],
        "request observations.provenance.registered_contract_bundle",
    )
    _exact_keys(
        registered,
        _REQUEST_OBSERVATION_SOURCE_KEYS,
        "request observations.provenance.registered_contract_bundle",
    )
    if official["path"] != "config/tushare_document_contracts.v1.yaml":
        raise RuntimeContractCompilationError(
            "request observations.provenance.official_contracts path is invalid"
        )
    if observed["path"] != "config/quicksync_interface_observations.v1.yaml":
        raise RuntimeContractCompilationError(
            "request observations.provenance.quicksync_interface_observations path is invalid"
        )
    if reviewed["path"] != "config/tushare_reviewed_contracts.v1.yaml":
        raise RuntimeContractCompilationError(
            "request observations.provenance.reviewed_contract_bundle path is invalid"
        )
    if registered["path"] != "config/tushare_upstream_contracts.v1.yaml":
        raise RuntimeContractCompilationError(
            "request observations.provenance.registered_contract_bundle path is invalid"
        )
    if _sha256_text(official["sha256"], "official contract bytes") != _sha256_text(
        official_contract_sha256, "official_contract_sha256"
    ):
        raise RuntimeContractCompilationError("official contract bytes do not match")
    if _sha256_text(observed["sha256"], "transport observation bytes") != _sha256_text(
        transport_observations_sha256, "transport_observations_sha256"
    ):
        raise RuntimeContractCompilationError(
            "transport observation bytes do not match"
        )
    _sha256_text(registered["sha256"], "registered contract bundle bytes")
    _sha256_text(reviewed["sha256"], "reviewed contract bundle bytes")

    if "migration_request_profiles" in provenance:
        migration = _mapping(
            provenance["migration_request_profiles"],
            "request observations.provenance.migration_request_profiles",
        )
        _exact_keys(
            migration,
            _REQUEST_OBSERVATION_MIGRATION_KEYS,
            "request observations.provenance.migration_request_profiles",
        )
        if (
            migration["path"] != "config/tushare_request_profiles.v1.yaml"
            or migration["authority"] is not False
            or migration["role"] != "reviewed_mapping_hint_only"
        ):
            raise RuntimeContractCompilationError(
                "request observations migration provenance is invalid"
            )
        _sha256_text(
            migration["sha256"],
            "request observations migration provenance SHA",
        )

    matrix = _mapping(
        provenance["matrix_evidence"],
        "request observations.provenance.matrix_evidence",
    )
    _exact_keys(
        matrix,
        _REQUEST_OBSERVATION_MATRIX_KEYS,
        "request observations.provenance.matrix_evidence",
    )
    if (
        matrix["schema_version"] != "tradingdatas.quicksync.final_interface_matrix.v2"
        or matrix["interface_probe_scheme"] != "http"
        or matrix["interface_count"] != _EXPECTED_IN_SCOPE_CONTRACTS
        or matrix["production_ready"] is not False
    ):
        raise RuntimeContractCompilationError(
            "request observations matrix provenance is invalid"
        )
    _sha256_text(matrix["sha256"], "request observations matrix evidence SHA")
    _sha256_text(
        matrix["api_names_sha256"],
        "request observations matrix API names SHA",
    )
    _text(matrix["observed_at"], "request observations matrix observed_at")
    if provenance["interface_count"] != _EXPECTED_IN_SCOPE_CONTRACTS:
        raise RuntimeContractCompilationError(
            "request observations provenance interface_count is invalid"
        )
    _sha256_text(
        provenance["api_names_sha256"],
        "request observations provenance API names SHA",
    )

    normalization = _mapping(
        document["normalization_policy"],
        "request observations.normalization_policy",
    )
    _exact_keys(
        normalization,
        _NORMALIZATION_POLICY_KEYS,
        "request observations.normalization_policy",
    )
    expected_normalization = {
        "allowed_parameter_sources": sorted(_PARAMETER_SOURCES),
        "allowed_transforms": sorted(_PARAMETER_TRANSFORMS),
        "max_abs_offset_seconds": _MAX_ABS_OFFSET_SECONDS,
        "required_true_must_be_mapped_or_probe_blocked": True,
        "required_unknown_must_be_probe_blocked": True,
        "blocked_plan_params_must_be_empty": True,
        "ingest_contract_is_independent_from_probe": True,
    }
    if normalization != expected_normalization:
        raise RuntimeContractCompilationError(
            "request observations.normalization_policy does not match compiler policy"
        )

    reason_codes = _mapping(
        document["reason_codes"], "request observations.reason_codes"
    )
    _exact_keys(reason_codes, _REASON_CODE_KEYS, "request observations.reason_codes")
    if reason_codes != {
        "probe": sorted(_REQUEST_OBSERVATION_PROBE_REASONS),
        "ingest_contract": sorted(_REQUEST_OBSERVATION_ACTIVATION_REASONS),
    }:
        raise RuntimeContractCompilationError(
            "request observations.reason_codes do not match compiler policy"
        )
    return provenance


def _request_variant_scalar(value: object, label: str) -> str | int | float | bool:
    if isinstance(value, str):
        if (
            not value
            or any(ord(character) < 32 for character in value)
            or "${" in value
        ):
            raise RuntimeContractCompilationError(
                f"{label} must be a concrete finite JSON scalar"
            )
        return value
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float) and math.isfinite(value):
        return value
    raise RuntimeContractCompilationError(
        f"{label} must be a concrete finite JSON scalar"
    )


def _request_variants(
    raw: object,
    *,
    parameters: Mapping[str, Mapping[str, Any]],
    label: str,
) -> list[dict[str, Any]]:
    values = _list(raw, label)
    if not values:
        raise RuntimeContractCompilationError(f"{label} must not be empty")
    normalized: list[dict[str, Any]] = []
    expected_keys: frozenset[str] | None = None
    seen: set[tuple[tuple[str, tuple[str, Any]], ...]] = set()
    for index, raw_variant in enumerate(values):
        variant_label = f"{label}[{index}]"
        variant = _mapping(raw_variant, variant_label)
        normalized_variant: dict[str, Any] = {}
        for raw_key, raw_value in variant.items():
            key = _text(raw_key, f"{variant_label} key")
            declaration = parameters.get(key)
            if declaration is None:
                raise RuntimeContractCompilationError(
                    f"{variant_label}.{key} is missing from mapped parameters"
                )
            if declaration["source"] != "literal":
                raise RuntimeContractCompilationError(
                    f"{variant_label}.{key} cannot override a dynamic parameter"
                )
            normalized_variant[key] = _request_variant_scalar(
                raw_value, f"{variant_label}.{key}"
            )
        keys = frozenset(normalized_variant)
        if not keys:
            if len(values) != 1:
                raise RuntimeContractCompilationError(
                    f"{label} empty variant must be the only variant"
                )
        elif expected_keys is None:
            expected_keys = keys
        elif keys != expected_keys:
            raise RuntimeContractCompilationError(
                f"{label} variants must use the same keys"
            )
        identity = tuple(
            (key, (type(item).__name__, item))
            for key, item in sorted(normalized_variant.items())
        )
        if identity in seen:
            raise RuntimeContractCompilationError(
                f"{label} contains a duplicate variant"
            )
        seen.add(identity)
        normalized.append(dict(sorted(normalized_variant.items())))
    if expected_keys is not None:
        template_default = tuple(
            (
                key,
                (
                    type(parameters[key]["value"]).__name__,
                    parameters[key]["value"],
                ),
            )
            for key in sorted(expected_keys)
        )
        if template_default not in seen:
            raise RuntimeContractCompilationError(
                f"{label} must include the mapped literal default"
            )
    return normalized


def _transport_class_by_api(document: Mapping[str, Any]) -> dict[str, str]:
    value = _mapping(deepcopy(document), "transport observations")
    if (
        value.get("provider") != "tushare"
        or value.get("transport_service") != "quicksync"
    ):
        raise RuntimeContractCompilationError(
            "transport observations must describe quicksync/tushare"
        )
    classifications = _mapping(
        value.get("classifications"), "transport observations.classifications"
    )
    by_api: dict[str, str] = {}
    for classification, raw_entries in classifications.items():
        class_name = _text(classification, "transport classification")
        api_names = (
            sorted(raw_entries)
            if isinstance(raw_entries, dict)
            else _list(raw_entries, f"transport classifications.{class_name}")
        )
        for index, raw_api_name in enumerate(api_names):
            api_name = _text(
                raw_api_name, f"transport classifications.{class_name}[{index}]"
            )
            if api_name in by_api:
                raise RuntimeContractCompilationError(
                    f"transport API has duplicate classification: {api_name}"
                )
            by_api[api_name] = class_name
    if len(by_api) != _EXPECTED_IN_SCOPE_CONTRACTS:
        raise RuntimeContractCompilationError(
            "transport observations must classify exactly 190 APIs"
        )
    return by_api


def _request_parameter(
    raw: object,
    *,
    label: str,
) -> dict[str, Any]:
    value = _mapping(raw, label)
    source = _text(value.get("source"), f"{label}.source")
    if source not in _PARAMETER_SOURCES:
        raise RuntimeContractCompilationError(
            f"{label} parameter source is unsupported"
        )
    if source == "literal":
        _exact_keys(value, frozenset({"source", "value"}), label)
        literal = value["value"]
        if isinstance(literal, bool) or not isinstance(literal, (str, int, float)):
            raise RuntimeContractCompilationError(f"{label}.value must be a scalar")
        if isinstance(literal, float) and not math.isfinite(literal):
            raise RuntimeContractCompilationError(f"{label}.value must be finite")
        if isinstance(literal, str) and not literal:
            raise RuntimeContractCompilationError(f"{label}.value must not be blank")
        return {"source": source, "value": literal}
    if source == "literal_values":
        _exact_keys(value, frozenset({"source", "values", "batch_size"}), label)
        raw_values = _list(value["values"], f"{label}.values")
        if not raw_values:
            raise RuntimeContractCompilationError(f"{label}.values must not be empty")
        values = [
            _request_parameter(
                {"source": "literal", "value": item},
                label=f"{label}.values[{index}]",
            )["value"]
            for index, item in enumerate(raw_values)
        ]
        identities = {(type(item).__name__, item) for item in values}
        if len(identities) != len(values):
            raise RuntimeContractCompilationError(f"{label}.values must be unique")
        return {
            "source": source,
            "values": values,
            "batch_size": _positive_int(value["batch_size"], f"{label}.batch_size"),
        }
    if source == "dataset_field":
        required_keys = frozenset(
            {"source", "dataset_id", "field", "requires_fresh_success_receipt"}
        )
        _reject_unknown_and_missing_keys(
            value,
            allowed=required_keys
            | {
                "batch_size",
                "source_equals",
                "source_date_field",
                "source_date_lte_days",
                "max_values",
                "source_order",
            },
            required=required_keys,
            label=label,
        )
        if value["requires_fresh_success_receipt"] is not True:
            raise RuntimeContractCompilationError(
                f"{label}.requires_fresh_success_receipt must be true"
            )
        result = {
            "source": source,
            "dataset_id": _text(value["dataset_id"], f"{label}.dataset_id"),
            "field": _text(value["field"], f"{label}.field"),
            "requires_fresh_success_receipt": True,
            "batch_size": _positive_int(
                value.get("batch_size", 1), f"{label}.batch_size"
            ),
        }
        if "source_equals" in value:
            raw_equals = value["source_equals"]
            if not isinstance(raw_equals, dict):
                raise RuntimeContractCompilationError(
                    f"{label}.source_equals must be an object"
                )
            normalized_equals: dict[str, str] = {}
            for field, expected in sorted(raw_equals.items()):
                normalized_equals[_text(field, f"{label}.source_equals field")] = _text(
                    expected, f"{label}.source_equals.{field}"
                )
            result["source_equals"] = normalized_equals
        date_field = value.get("source_date_field")
        date_days = value.get("source_date_lte_days")
        if (date_field is None) != (date_days is None):
            raise RuntimeContractCompilationError(
                f"{label} source date selector is incomplete"
            )
        if date_field is not None:
            result["source_date_field"] = _text(date_field, f"{label}.source_date_field")
            result["source_date_lte_days"] = _positive_int(
                date_days, f"{label}.source_date_lte_days"
            )
        if "max_values" in value:
            result["max_values"] = _positive_int(value["max_values"], f"{label}.max_values")
        if "source_order" in value:
            source_order = _text(value["source_order"], f"{label}.source_order")
            if source_order not in {"lexical", "stable_hash"}:
                raise RuntimeContractCompilationError(f"{label}.source_order is unsupported")
            result["source_order"] = source_order
        return result
    _exact_keys(value, frozenset({"source", "transform", "offset_seconds"}), label)
    transform = _text(value["transform"], f"{label}.transform")
    if transform not in _PARAMETER_TRANSFORMS:
        raise RuntimeContractCompilationError(
            f"{label} parameter transform is unsupported"
        )
    offset = value["offset_seconds"]
    if isinstance(offset, bool) or not isinstance(offset, int):
        raise RuntimeContractCompilationError(f"{label}.offset_seconds must be integer")
    if abs(offset) > _MAX_ABS_OFFSET_SECONDS:
        raise RuntimeContractCompilationError(
            f"{label}.offset_seconds exceeds the bounded offset"
        )
    return {"source": source, "transform": transform, "offset_seconds": offset}


def _request_observation_index(
    raw: Mapping[str, Any],
    *,
    documents_by_api: Mapping[str, Mapping[str, Any]],
    transport_observations: Mapping[str, Any],
    official_contract_sha256: str,
    transport_observations_sha256: str,
) -> dict[str, dict[str, Any]]:
    document = _mapping(deepcopy(raw), "request observations")
    _exact_keys(document, _REQUEST_OBSERVATION_ROOT_KEYS, "request observations")
    if document["version"] != 1:
        raise RuntimeContractCompilationError("request observations.version must be 1")
    if (
        document["contract_id"] != "tushare-request-observations.v1"
        or document["provider"] != "tushare"
        or document["transport_service"] != "quicksync"
        or document["authority_scope"] != "request_mapping_only"
        or document["production_ready"] is not False
    ):
        raise RuntimeContractCompilationError(
            "request observations identity is invalid"
        )
    provenance = _request_observation_metadata(
        document,
        official_contract_sha256=official_contract_sha256,
        transport_observations_sha256=transport_observations_sha256,
    )
    transport_by_api = _transport_class_by_api(transport_observations)
    entries = _list(document["entries"], "request observations.entries")
    if len(entries) != _EXPECTED_IN_SCOPE_CONTRACTS:
        raise RuntimeContractCompilationError(
            "request observations must contain exactly 190 entries"
        )
    normalized: dict[str, dict[str, Any]] = {}
    ordered_api_names: list[str] = []
    row_limit_count = 0
    for index, raw_entry in enumerate(entries):
        label = f"request observations.entries[{index}]"
        entry = _mapping(raw_entry, label)
        unknown = sorted(set(entry) - _REQUEST_OBSERVATION_ENTRY_KEYS)
        missing = sorted(_REQUEST_OBSERVATION_REQUIRED_ENTRY_KEYS - set(entry))
        if unknown or missing:
            raise RuntimeContractCompilationError(f"{label} keys invalid")
        api_name = _text(entry["api_name"], f"{label}.api_name")
        if api_name in normalized:
            raise RuntimeContractCompilationError(f"duplicate request API: {api_name}")
        official_document = documents_by_api.get(api_name)
        if official_document is None:
            raise RuntimeContractCompilationError(f"unknown request API: {api_name}")
        ordered_api_names.append(api_name)
        scopes = _list(entry["scope_labels"], f"{label}.scope_labels")
        if scopes != ["all", "gaps"]:
            raise RuntimeContractCompilationError(
                f"{label}.scope_labels must be [all, gaps]"
            )
        transport_class = _text(
            entry["transport_observation_class"],
            f"{label}.transport_observation_class",
        )
        if transport_by_api.get(api_name) != transport_class:
            raise RuntimeContractCompilationError(
                f"{api_name} transport classification does not match observations"
            )
        probe_state = _text(entry["probe_state"], f"{label}.probe_state")
        if probe_state not in _PROBE_STATES:
            raise RuntimeContractCompilationError(f"{label}.probe_state is unsupported")
        probe_reasons = _sorted_unique_text_list(
            entry["probe_block_reasons"],
            label=f"{label}.probe_block_reasons",
            allowed=_REQUEST_OBSERVATION_PROBE_REASONS,
        )
        if (probe_state == "executable") != (not probe_reasons):
            raise RuntimeContractCompilationError(
                f"{label} probe_state={probe_state} has inconsistent reasons"
            )
        ingest_contract_state = _text(
            entry["ingest_contract_state"], f"{label}.ingest_contract_state"
        )
        if ingest_contract_state not in _REQUEST_ACTIVATION_STATES:
            raise RuntimeContractCompilationError(
                f"{label}.ingest_contract_state is unsupported"
            )
        activation_reasons = _sorted_unique_text_list(
            entry["ingest_contract_block_reasons"],
            label=f"{label}.ingest_contract_block_reasons",
            allowed=_REQUEST_OBSERVATION_ACTIVATION_REASONS,
        )
        if (ingest_contract_state == "ready") != (not activation_reasons):
            raise RuntimeContractCompilationError(
                f"{label} ingest_contract_state={ingest_contract_state} has inconsistent reasons"
            )
        unresolved = _sorted_unique_text_list(
            entry["unresolved_parameter_keys"],
            label=f"{label}.unresolved_parameter_keys",
        )
        official_inputs = {
            _text(item.get("name"), f"{api_name}.input field"): item.get("required")
            for item in _list(
                official_document.get("input_fields"), f"{api_name}.input_fields"
            )
            if isinstance(item, dict)
        }
        parameters = _mapping(entry["parameters"], f"{label}.parameters")
        unknown_parameters = sorted(set(parameters) - set(official_inputs))
        if unknown_parameters:
            raise RuntimeContractCompilationError(
                f"{api_name} maps undeclared provider parameter {unknown_parameters[0]}"
            )
        normalized_parameters = {
            parameter: _request_parameter(
                parameters[parameter], label=f"{label}.parameters.{parameter}"
            )
            for parameter in sorted(parameters)
        }
        required_true = {
            name for name, required in official_inputs.items() if required == "Y"
        }
        missing_required = sorted(required_true - set(normalized_parameters))
        if missing_required and probe_state != "blocked":
            raise RuntimeContractCompilationError(
                f"{api_name} required provider parameter is unmapped"
            )
        required_unknown = {
            name for name, required in official_inputs.items() if required == ""
        }
        if required_unknown and probe_state != "blocked":
            raise RuntimeContractCompilationError(
                f"{api_name} has unknown official requiredness"
            )
        if required_unknown != set(unresolved) & required_unknown:
            raise RuntimeContractCompilationError(
                f"{api_name} unresolved_parameter_keys must cover unknown requiredness"
            )
        if probe_state == "blocked" and not set(unresolved).issubset(
            set(official_inputs)
        ):
            raise RuntimeContractCompilationError(
                f"{api_name} unresolved_parameter_keys is not an official input subset"
            )
        row_limit = entry["row_limit_observation"]
        if row_limit is not None:
            row = _mapping(row_limit, f"{label}.row_limit_observation")
            _exact_keys(
                row,
                frozenset({"observed_count", "detection", "reject_at_limit"}),
                f"{label}.row_limit_observation",
            )
            _positive_int(
                row["observed_count"], f"{label}.row_limit_observation.observed_count"
            )
            if row["reject_at_limit"] is not True:
                raise RuntimeContractCompilationError(
                    f"{label}.row_limit_observation.reject_at_limit must be true"
                )
            if (
                "response_completeness_unresolved_at_observed_limit"
                not in activation_reasons
            ):
                raise RuntimeContractCompilationError(
                    f"{api_name} row limit must block activation"
                )
            row_limit_count += 1
        request_shape = _text(entry["request_shape"], f"{label}.request_shape")
        if request_shape not in _REQUEST_SHAPES:
            raise RuntimeContractCompilationError(
                f"{label}.request_shape is unsupported"
            )
        fanout_count = sum(
            declaration["source"] in {"dataset_field", "literal_values"}
            for declaration in normalized_parameters.values()
        )
        requires_fanout = request_shape in {"entity_fanout", "dimension_fanout"}
        if requires_fanout != (fanout_count == 1):
            raise RuntimeContractCompilationError(
                f"{label}.request_shape and fanout mapping are inconsistent"
            )
        normalized_variants = _request_variants(
            entry.get("request_variants", [{}]),
            parameters=normalized_parameters,
            label=f"{label}.request_variants",
        )
        normalized[api_name] = {
            "api_name": api_name,
            "scope_labels": ["all", "gaps"],
            "transport_observation_class": transport_class,
            "request_shape": request_shape,
            "probe_state": probe_state,
            "probe_block_reasons": probe_reasons,
            "ingest_contract_state": ingest_contract_state,
            "ingest_contract_block_reasons": activation_reasons,
            "unresolved_parameter_keys": unresolved,
            "parameters": normalized_parameters,
            "row_limit_observation": deepcopy(row_limit),
            "request_variants": normalized_variants,
        }
    if ordered_api_names != sorted(ordered_api_names):
        raise RuntimeContractCompilationError("request observation APIs must be sorted")
    if set(normalized) != set(documents_by_api):
        raise RuntimeContractCompilationError(
            "request observations must contain exactly 190 official APIs"
        )
    api_hash = hashlib.sha256(
        ("\n".join(sorted(normalized)) + "\n").encode("utf-8")
    ).hexdigest()
    if provenance.get("api_names_sha256") != api_hash:
        raise RuntimeContractCompilationError(
            "request observation API set hash mismatch"
        )
    counts = {
        "interfaces": len(normalized),
        "probe_executable": sum(
            item["probe_state"] == "executable" for item in normalized.values()
        ),
        "probe_blocked": sum(
            item["probe_state"] == "blocked" for item in normalized.values()
        ),
        "ingest_contract_ready": sum(
            item["ingest_contract_state"] == "ready" for item in normalized.values()
        ),
        "ingest_contract_blocked": sum(
            item["ingest_contract_state"] == "blocked" for item in normalized.values()
        ),
        "row_limit_ingest_contract_blocked": row_limit_count,
    }
    if document["counts"] != counts:
        raise RuntimeContractCompilationError(
            "request observation counts do not match entries"
        )
    return normalized


def _normalized_policy(raw: Mapping[str, Any]) -> tuple[str, dict[str, Any]]:
    policy = _mapping(deepcopy(raw), "runtime policy")
    _exact_keys(policy, _POLICY_KEYS, "runtime policy")
    if policy["version"] != 1:
        raise RuntimeContractCompilationError("runtime policy.version must be 1")
    provider = _text(policy["provider"], "runtime policy.provider")
    defaults = _mapping(policy["catalog_only_defaults"], "catalog_only_defaults")
    _exact_keys(defaults, _DEFAULT_KEYS, "catalog_only_defaults")
    budgets = _mapping(defaults["budgets"], "catalog_only_defaults.budgets")
    _exact_keys(budgets, _BUDGET_KEYS, "catalog_only_defaults.budgets")
    defaults["budgets"] = {
        key: _positive_int(budgets[key], f"catalog_only_defaults.budgets.{key}")
        for key in sorted(_BUDGET_KEYS)
    }
    defaults["freshness_sla_seconds"] = _positive_int(
        defaults["freshness_sla_seconds"],
        "catalog_only_defaults.freshness_sla_seconds",
    )
    defaults["max_default_projection_fields"] = _positive_int(
        defaults["max_default_projection_fields"],
        "catalog_only_defaults.max_default_projection_fields",
    )
    for key in _DEFAULT_KEYS - {
        "budgets",
        "freshness_sla_seconds",
        "max_default_projection_fields",
    }:
        defaults[key] = _text(defaults[key], f"catalog_only_defaults.{key}")
    if defaults["point_in_time"] != "append_only":
        raise RuntimeContractCompilationError(
            "catalog-only point_in_time must be append_only"
        )
    if defaults["cadence_class"] != "on_demand":
        raise RuntimeContractCompilationError(
            "catalog-only cadence_class must be on_demand"
        )
    return provider, defaults


def _normalized_cadence_policy(
    raw: Mapping[str, Any],
    *,
    documents: Mapping[str, Any],
    documents_by_api: Mapping[str, Mapping[str, Any]],
    provider: str,
) -> dict[str, dict[str, object]]:
    """Validate the one-entry-per-official-document cadence authority."""

    policy = _mapping(deepcopy(raw), "cadence policy")
    _exact_keys(policy, _CADENCE_POLICY_KEYS, "cadence policy")
    if policy["version"] != 1:
        raise RuntimeContractCompilationError("cadence policy.version must be 1")
    if policy["policy_id"] != "tushare-cadence-policy.v1":
        raise RuntimeContractCompilationError("cadence policy_id is invalid")
    if _text(policy["provider"], "cadence policy.provider") != provider:
        raise RuntimeContractCompilationError(
            "cadence policy provider does not match runtime policy"
        )
    if policy["source_snapshot_id"] != documents.get("snapshot_id"):
        raise RuntimeContractCompilationError(
            "cadence policy document snapshot id does not match official documents"
        )
    expected_sha = _sha256_text(
        policy["source_snapshot_canonical_sha256"],
        "cadence policy.source_snapshot_canonical_sha256",
    )
    if _canonical_sha256(documents) != expected_sha:
        raise RuntimeContractCompilationError(
            "cadence policy document snapshot SHA does not match official documents"
        )

    entries = _list(policy["entries"], "cadence policy.entries")
    by_api: dict[str, dict[str, object]] = {}
    ordered_api_names: list[str] = []
    for index, raw_entry in enumerate(entries):
        entry = _mapping(raw_entry, f"cadence policy.entries[{index}]")
        _exact_keys(entry, _CADENCE_POLICY_ENTRY_KEYS, f"cadence policy.entries[{index}]")
        api_name = _text(entry["api_name"], f"cadence policy.entries[{index}].api_name")
        if _SAFE_API_NAME.fullmatch(api_name) is None:
            raise RuntimeContractCompilationError(
                f"cadence policy API name is invalid: {api_name}"
            )
        if api_name in by_api:
            raise RuntimeContractCompilationError(
                f"duplicate cadence policy API: {api_name}"
            )
        cadence_class = _text(
            entry["cadence_class"],
            f"cadence policy.entries[{index}].cadence_class",
        )
        if cadence_class not in _CADENCE_CLASSES:
            raise RuntimeContractCompilationError(
                f"cadence policy.entries[{index}].cadence_class is unsupported"
            )
        freshness_sla_seconds = _positive_int(
            entry["freshness_sla_seconds"],
            f"cadence policy.entries[{index}].freshness_sla_seconds",
        )
        source_document_sha256 = _sha256_text(
            entry["source_document_sha256"],
            f"cadence policy.entries[{index}].source_document_sha256",
        )
        reason_code = _text(
            entry["reason_code"], f"cadence policy.entries[{index}].reason_code"
        )
        if _SAFE_REASON_CODE.fullmatch(reason_code) is None:
            raise RuntimeContractCompilationError(
                f"cadence policy.entries[{index}].reason_code is invalid"
            )
        allowed_cadence_classes = _CADENCE_REASON_CLASSES.get(reason_code)
        if allowed_cadence_classes is None:
            raise RuntimeContractCompilationError(
                f"cadence policy.entries[{index}].reason_code is unsupported"
            )
        if cadence_class not in allowed_cadence_classes:
            raise RuntimeContractCompilationError(
                f"cadence policy reason_code {reason_code} does not allow "
                f"cadence_class {cadence_class}"
            )
        ordered_api_names.append(api_name)
        by_api[api_name] = {
            "cadence_class": cadence_class,
            "freshness_sla_seconds": freshness_sla_seconds,
            "source_document_sha256": source_document_sha256,
            "reason_code": reason_code,
        }
    if ordered_api_names != sorted(ordered_api_names):
        raise RuntimeContractCompilationError("cadence policy APIs must be sorted")
    if len(by_api) != _EXPECTED_IN_SCOPE_CONTRACTS:
        raise RuntimeContractCompilationError(
            "cadence policy must contain exactly 190 official APIs"
        )
    unknown = sorted(set(by_api) - set(documents_by_api))
    if unknown:
        raise RuntimeContractCompilationError(
            f"cadence policy contains unknown API(s): {','.join(unknown)}"
        )
    missing = sorted(set(documents_by_api) - set(by_api))
    if missing:
        raise RuntimeContractCompilationError(
            f"cadence policy is missing official API(s): {','.join(missing)}"
        )
    for api_name, entry in by_api.items():
        if entry["source_document_sha256"] != documents_by_api[api_name].get(
            "doc_sha256"
        ):
            raise RuntimeContractCompilationError(
                f"cadence policy {api_name} source document SHA does not match official document"
            )
    return by_api


def _field_contracts(document: Mapping[str, Any]) -> list[dict[str, object]]:
    api_name = _text(document.get("api_name"), "document.api_name")
    fields: list[dict[str, object]] = []
    seen: set[str] = set()
    for index, raw_field in enumerate(
        _list(document.get("output_fields"), f"{api_name}.output_fields")
    ):
        field = _mapping(raw_field, f"{api_name}.output_fields[{index}]")
        name = _text(field.get("name"), f"{api_name}.output_fields[{index}].name")
        declared_type = _text(
            field.get("declared_type"),
            f"{api_name}.output_fields[{index}].declared_type",
        )
        if _SAFE_FIELD_NAME.fullmatch(name) is None:
            # Provider payload fields may start with a digit (for example
            # ``1w`` or ``10day``). Other names remain available only through
            # the lossless raw payload and must never be silently renamed.
            continue
        if name in seen:
            raise RuntimeContractCompilationError(
                f"{api_name} has duplicate output field {name}"
            )
        seen.add(name)
        logical_type = {
            "float": "float",
            "int": "integer",
        }.get(declared_type, "text")
        typed = declared_type in {"str", "int", "float", "datetime"}
        fields.append(
            {
                "name": name,
                "declared_source_type": declared_type,
                "logical_type": logical_type,
                "nullable": True,
                "selectable": True,
                "filterable": typed,
                "sortable": typed,
            }
        )
    if not fields:
        raise RuntimeContractCompilationError(
            f"{api_name} has no provider-field-compatible outputs"
        )
    return fields


def _input_field_contracts(document: Mapping[str, Any]) -> list[dict[str, object]]:
    api_name = _text(document.get("api_name"), "document.api_name")
    fields: list[dict[str, object]] = []
    seen: set[str] = set()
    for index, raw_field in enumerate(
        _list(document.get("input_fields"), f"{api_name}.input_fields")
    ):
        label = f"{api_name}.input_fields[{index}]"
        field = _mapping(raw_field, label)
        _exact_keys(field, _INPUT_FIELD_KEYS, label)
        name = _text(field["name"], f"{label}.name")
        if _SAFE_PARAMETER_NAME.fullmatch(name) is None:
            raise RuntimeContractCompilationError(
                f"{api_name} has invalid input field {name}"
            )
        if name in seen:
            raise RuntimeContractCompilationError(
                f"{api_name} has duplicate input field {name}"
            )
        declared_type = _text(field["declared_type"], f"{label}.declared_type")
        if declared_type not in _INPUT_DECLARED_TYPES:
            raise RuntimeContractCompilationError(
                f"{api_name} input field {name} has unsupported declared type "
                f"{declared_type}"
            )
        required = field["required"]
        if not isinstance(required, str) or required not in _INPUT_REQUIRED_VALUES:
            raise RuntimeContractCompilationError(
                f"{api_name} input field {name} has unsupported required marker"
            )
        seen.add(name)
        fields.append(
            {
                "name": name,
                "declared_source_type": declared_type,
                "required": _INPUT_REQUIRED_VALUES[required],
            }
        )
    return fields


def _with_input_fields(
    contract: Mapping[str, Any], input_fields: list[dict[str, object]]
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in contract.items():
        if key == "fields":
            result["input_fields"] = deepcopy(input_fields)
        result[key] = deepcopy(value)
    if "input_fields" not in result:
        raise RuntimeContractCompilationError("runtime contract is missing fields")
    return result


def _catalog_only_contract(
    document: Mapping[str, Any],
    *,
    provider: str,
    defaults: Mapping[str, Any],
    cadence: Mapping[str, object],
) -> dict[str, object]:
    api_name = _text(document.get("api_name"), "document.api_name")
    if _SAFE_API_NAME.fullmatch(api_name) is None:
        raise RuntimeContractCompilationError(f"invalid provider API name: {api_name}")
    fields = _field_contracts(document)
    projection_limit = int(defaults["max_default_projection_fields"])
    return {
        "dataset_id": f"{defaults['dataset_id_prefix']}.{api_name}",
        "aliases": [f"{provider}.{api_name}"],
        "domain": defaults["domain"],
        "market": defaults["market"],
        "entity_type": defaults["entity_type"],
        "data_classification": defaults["data_classification"],
        "provider": provider,
        "api_name": api_name,
        "source_document_url": _text(document.get("doc_url"), f"{api_name}.doc_url"),
        "source_document_sha256": _text(
            document.get("doc_sha256"), f"{api_name}.doc_sha256"
        ),
        "schema_version": defaults["schema_version"],
        "fields": fields,
        "primary_key": [],
        "default_projection": [field["name"] for field in fields[:projection_limit]],
        "as_of_field": None,
        "as_of_format": None,
        "range_field": None,
        "partition_field": None,
        "cadence_class": cadence["cadence_class"],
        "timezone": defaults["timezone"],
        "freshness_sla_seconds": cadence["freshness_sla_seconds"],
        "point_in_time": defaults["point_in_time"],
        "backfill_policy": defaults["backfill_policy"],
        "empty_data_policy": defaults["empty_data_policy"],
        "required_scope": defaults["required_scope"],
        "quota_class": defaults["quota_class"],
        "request_shape": defaults["request_shape"],
        "request_template": {},
        "request_variants": [{}],
        "fanout": {"strategy": "none"},
        "pagination": {"strategy": "none"},
        "request_window_policy": None,
        "response_completeness": None,
        "requested_fields": [],
        "budgets": deepcopy(defaults["budgets"]),
        "reviewed_type_overrides": [],
    }


def _request_execution_contract(
    observation: Mapping[str, Any],
    *,
    reviewed_contract: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Project one executable observation onto the existing generic data plane."""

    blocked_fanout_fields = [
        declaration
        for declaration in observation["parameters"].values()
        if declaration["source"] in {"dataset_field", "literal_values"}
    ]
    if observation["probe_state"] == "blocked" and not blocked_fanout_fields:
        if reviewed_contract is not None:
            raise RuntimeContractCompilationError(
                f"reviewed API cannot have a blocked probe: {observation['api_name']}"
            )
        return {
            "request_shape": observation["request_shape"],
            "request_template": {},
            "request_variants": [{}],
            "fanout": {"strategy": "none"},
            "pagination": {"strategy": "none"},
            "request_window_policy": None,
        }

    template: dict[str, Any] = {}
    window_formats: dict[str, str] = {}
    fanout_fields: list[tuple[str, Mapping[str, Any]]] = []
    pagination_values: dict[str, int] = {}
    for parameter, declaration in observation["parameters"].items():
        source = declaration["source"]
        if source == "literal":
            if parameter in {"limit", "offset"} and isinstance(
                declaration["value"], int
            ):
                pagination_values[parameter] = declaration["value"]
            else:
                template[parameter] = declaration["value"]
        elif source in {"run_clock", "scheduled_partition"}:
            template[parameter] = f"${{window.{parameter}}}"
            window_formats[parameter] = declaration["transform"]
        else:
            fanout_fields.append((parameter, declaration))
    if fanout_fields:
        if len(fanout_fields) != 1:
            raise RuntimeContractCompilationError(
                f"{observation['api_name']} executable fanout must have one source"
            )
        parameter, declaration = fanout_fields[0]
        if declaration["source"] == "literal_values":
            fanout = {
                "strategy": "literal_values",
                "parameter": parameter,
                "values": declaration["values"],
                "batch_size": declaration["batch_size"],
            }
        else:
            fanout = {
                "strategy": "dataset_field",
                "parameter": parameter,
                "source_dataset_id": declaration["dataset_id"],
                "source_field": declaration["field"],
                "batch_size": declaration["batch_size"],
            }
            for key in (
                "source_equals",
                "source_date_field",
                "source_date_lte_days",
                "max_values",
                "source_order",
            ):
                if key in declaration:
                    fanout[key] = declaration[key]
    else:
        fanout = {"strategy": "none"}
    if pagination_values:
        if set(pagination_values) != {"limit", "offset"}:
            raise RuntimeContractCompilationError(
                f"{observation['api_name']} pagination requires limit and offset"
            )
        pagination = {
            "strategy": "offset",
            "limit_parameter": "limit",
            "offset_parameter": "offset",
            "page_size": pagination_values["limit"],
            "max_pages": 1,
        }
    else:
        pagination = {"strategy": "none"}
    if window_formats:
        keys = (
            ["start_date", "end_date"]
            if set(window_formats) == {"start_date", "end_date"}
            else sorted(window_formats)
        )
        start = "start_date" if "start_date" in keys else keys[0]
        end = "end_date" if "end_date" in keys else keys[-1]
        window_policy: dict[str, Any] | None = {
            "required_keys": keys,
            "formats": {key: window_formats[key] for key in keys},
            "range_start_key": start,
            "range_end_key": end,
            "max_span_days": 1,
        }
    else:
        window_policy = None
    projected = {
        "request_shape": observation["request_shape"],
        "request_template": dict(sorted(template.items())),
        "request_variants": deepcopy(observation["request_variants"]),
        "fanout": fanout,
        "pagination": pagination,
        "request_window_policy": window_policy,
    }
    if reviewed_contract is None:
        return projected
    for key in (
        "request_shape",
        "request_template",
        "request_variants",
        "fanout",
        "pagination",
    ):
        if reviewed_contract[key] != projected[key]:
            raise RuntimeContractCompilationError(
                f"reviewed {observation['api_name']} request mapping drifted at {key}"
            )
    reviewed_window = reviewed_contract.get("request_window_policy")
    if (reviewed_window is None) != (window_policy is None):
        raise RuntimeContractCompilationError(
            f"reviewed {observation['api_name']} request window mapping drifted"
        )
    if reviewed_window is not None and (
        reviewed_window["required_keys"] != window_policy["required_keys"]
        or reviewed_window["formats"] != window_policy["formats"]
        or reviewed_window["range_start_key"] != window_policy["range_start_key"]
        or reviewed_window["range_end_key"] != window_policy["range_end_key"]
    ):
        raise RuntimeContractCompilationError(
            f"reviewed {observation['api_name']} request window mapping drifted"
        )
    return {key: deepcopy(reviewed_contract[key]) for key in projected}


def _with_request_observation(
    contract: Mapping[str, Any], observation: Mapping[str, Any]
) -> dict[str, Any]:
    execution = _request_execution_contract(
        observation,
        reviewed_contract=contract if contract.get("primary_key") else None,
    )
    result = deepcopy(dict(contract))
    result.update(execution)
    result.update(
        probe_state=observation["probe_state"],
        probe_block_reasons=list(observation["probe_block_reasons"]),
        ingest_contract_state=observation["ingest_contract_state"],
        ingest_contract_block_reasons=list(
            observation["ingest_contract_block_reasons"]
        ),
    )
    return result


def compile_runtime_contract_bundle(
    document_snapshot: bytes,
    reviewed_bundle: bytes,
    policy_document: bytes,
    cadence_policy: bytes,
    *,
    request_observations: bytes,
    transport_observations: bytes,
    official_contract_sha256: str,
    transport_observations_sha256: str,
    request_observations_sha256: str,
) -> dict[str, object]:
    """Return a deterministic 190-interface bundle without runtime activation."""

    documents, official_sha = _bound_yaml_mapping(
        document_snapshot,
        official_contract_sha256,
        label="official contract",
    )
    policy = _yaml_mapping_from_bytes(policy_document, label="runtime policy")
    cadence_document = _yaml_mapping_from_bytes(
        cadence_policy, label="cadence policy"
    )
    request_document, _request_sha = _bound_yaml_mapping(
        request_observations,
        request_observations_sha256,
        label="request observations",
    )
    transport_document, transport_sha = _bound_yaml_mapping(
        transport_observations,
        transport_observations_sha256,
        label="transport observations",
    )
    provider, defaults = _normalized_policy(policy)
    if documents.get("snapshot_id") != policy.get("source_snapshot_id"):
        raise RuntimeContractCompilationError(
            "document snapshot id does not match policy"
        )
    expected_sha = _text(
        policy.get("source_snapshot_canonical_sha256"),
        "runtime policy.source_snapshot_canonical_sha256",
    )
    if (
        _SHA256.fullmatch(expected_sha) is None
        or _canonical_sha256(documents) != expected_sha
    ):
        raise RuntimeContractCompilationError(
            "document snapshot SHA does not match policy"
        )
    if documents.get("provider") != provider:
        raise RuntimeContractCompilationError("document provider does not match policy")

    raw_documents = _list(documents.get("contracts"), "document snapshot.contracts")
    by_api: dict[str, dict[str, Any]] = {}
    input_fields_by_api: dict[str, list[dict[str, object]]] = {}
    for index, raw in enumerate(raw_documents):
        document = _mapping(raw, f"document snapshot.contracts[{index}]")
        api_name = _text(document.get("api_name"), f"document[{index}].api_name")
        if api_name in by_api:
            raise RuntimeContractCompilationError(f"duplicate document API: {api_name}")
        by_api[api_name] = document
        input_fields_by_api[api_name] = _input_field_contracts(document)
    expected_count = documents.get("counts", {}).get("in_scope_contracts")
    if (
        expected_count != _EXPECTED_IN_SCOPE_CONTRACTS
        or len(by_api) != _EXPECTED_IN_SCOPE_CONTRACTS
    ):
        raise RuntimeContractCompilationError(
            "document snapshot must contain exactly 190 in-scope APIs"
        )
    cadence_by_api = _normalized_cadence_policy(
        cadence_document,
        documents=documents,
        documents_by_api=by_api,
        provider=provider,
    )
    request_by_api = _request_observation_index(
        request_document,
        documents_by_api=by_api,
        transport_observations=transport_document,
        official_contract_sha256=official_sha,
        transport_observations_sha256=transport_sha,
    )
    request_provenance = _mapping(
        request_document["provenance"], "request observations.provenance"
    )
    reviewed_source = _mapping(
        request_provenance["reviewed_contract_bundle"],
        "request observations.provenance.reviewed_contract_bundle",
    )
    reviewed_document, _reviewed_sha = _bound_yaml_mapping(
        reviewed_bundle,
        reviewed_source["sha256"],
        label="reviewed contract bundle",
    )

    try:
        reviewed = load_upstream_contract_bundle(reviewed_document)
    except ValueError as exc:
        raise RuntimeContractCompilationError(
            f"reviewed bundle is invalid: {exc}"
        ) from exc
    if reviewed["provider"] != provider:
        raise RuntimeContractCompilationError("reviewed provider does not match policy")
    reviewed_by_api: dict[str, Mapping[str, Any]] = {}
    for contract in reviewed["contracts"]:
        api_name = str(contract["api_name"])
        document = by_api.get(api_name)
        if document is None:
            raise RuntimeContractCompilationError(
                f"reviewed API is absent from official documents: {api_name}"
            )
        if contract["source_document_sha256"] != document.get("doc_sha256"):
            raise RuntimeContractCompilationError(
                f"reviewed {api_name} does not match official document"
            )
        reviewed_by_api[api_name] = contract

    for api_name, cadence in cadence_by_api.items():
        reviewed_contract = reviewed_by_api.get(api_name)
        reason_code = cadence["reason_code"]
        if reviewed_contract is None:
            if reason_code == "reviewed_contract_exact":
                raise RuntimeContractCompilationError(
                    f"cadence policy {api_name} uses reviewed_contract_exact "
                    "without a reviewed contract"
                )
            continue
        if reason_code != "reviewed_contract_exact":
            raise RuntimeContractCompilationError(
                f"cadence policy reviewed API {api_name} reason_code must be "
                "reviewed_contract_exact"
            )
        if cadence["cadence_class"] != reviewed_contract["cadence_class"]:
            raise RuntimeContractCompilationError(
                f"cadence policy {api_name} does not match reviewed contract cadence"
            )
        if (
            cadence["freshness_sla_seconds"]
            != reviewed_contract["freshness_sla_seconds"]
        ):
            raise RuntimeContractCompilationError(
                f"cadence policy {api_name} does not match reviewed contract freshness"
            )

    contracts = [
        deepcopy(reviewed_by_api[api_name])
        if api_name in reviewed_by_api
        else _catalog_only_contract(
            by_api[api_name],
            provider=provider,
            defaults=defaults,
            cadence=cadence_by_api[api_name],
        )
        for api_name in sorted(by_api)
    ]
    dataset_ids = [str(item["dataset_id"]) for item in contracts]
    aliases = [alias for item in contracts for alias in item["aliases"]]
    if len(dataset_ids) != len(set(dataset_ids)) or len(aliases) != len(set(aliases)):
        raise RuntimeContractCompilationError("compiled dataset identity is not unique")

    result = {
        "version": 1,
        "bundle_id": "tushare-upstream-contracts.v1",
        "provider": provider,
        "provenance": deepcopy(reviewed["provenance"]),
        "contracts": sorted(contracts, key=lambda item: str(item["dataset_id"])),
    }
    # Reuse the existing strict registry validator for every pre-existing
    # contract field, then attach the official input contract. The downstream
    # registry compiler adopts this new field in a separate integration step.
    validated = load_upstream_contract_bundle(result)
    with_inputs = [
        _with_input_fields(contract, input_fields_by_api[str(contract["api_name"])])
        for contract in validated["contracts"]
    ]
    validated["contracts"] = [
        _with_request_observation(contract, request_by_api[str(contract["api_name"])])
        for contract in with_inputs
    ]
    try:
        validated_final_bundle = load_upstream_contract_bundle(validated)
    except ValueError as exc:
        raise RuntimeContractCompilationError(
            f"compiled runtime bundle is invalid: {exc}"
        ) from exc
    _registered_seed_requirements(validated_final_bundle["contracts"], request_by_api)
    return validated


def _render_probe_clock(value: datetime, transform: str) -> str:
    local = value.astimezone(ZoneInfo("Asia/Shanghai"))
    if transform == "yyyymmdd":
        return local.strftime("%Y%m%d")
    if transform == "yyyymm":
        return local.strftime("%Y%m")
    if transform == "yyyy_qn":
        return f"{local.year}Q{((local.month - 1) // 3) + 1}"
    if transform == "yyyyww":
        return local.strftime("%G%V")
    if transform == "local_datetime_seconds":
        return local.strftime("%Y-%m-%d %H:%M:%S")
    if transform == "rfc3339":
        rendered = value.isoformat(timespec="seconds")
        return rendered[:-6] + "Z" if rendered.endswith("+00:00") else rendered
    raise RuntimeContractCompilationError(
        f"cannot render run clock with transform {transform}"
    )


def _registered_seed_requirements(
    contracts: list[Mapping[str, Any]],
    observation_by_api: Mapping[str, Mapping[str, Any]],
) -> dict[tuple[str, str], dict[str, str]]:
    by_api: dict[str, Mapping[str, Any]] = {}
    by_dataset: dict[str, Mapping[str, Any]] = {}
    for index, contract in enumerate(contracts):
        item = _mapping(contract, f"registered contracts[{index}]")
        api_name = _text(
            item.get("api_name"), f"registered contracts[{index}].api_name"
        )
        dataset_id = _text(
            item.get("dataset_id"), f"registered contracts[{index}].dataset_id"
        )
        if api_name in by_api or dataset_id in by_dataset:
            raise RuntimeContractCompilationError(
                "registered contracts contain duplicate API or dataset identity"
            )
        by_api[api_name] = item
        by_dataset[dataset_id] = item
    if set(by_api) != set(observation_by_api):
        raise RuntimeContractCompilationError(
            "registered contracts do not match request observation APIs"
        )

    requirements: dict[tuple[str, str], dict[str, str]] = {}
    for api_name, observation in observation_by_api.items():
        consumer = by_api[api_name]
        fanout = _mapping(consumer.get("fanout"), f"registered {api_name}.fanout")
        declarations = [
            (parameter, declaration)
            for parameter, declaration in observation["parameters"].items()
            if declaration["source"] == "dataset_field"
        ]
        literal_declarations = [
            (parameter, declaration)
            for parameter, declaration in observation["parameters"].items()
            if declaration["source"] == "literal_values"
        ]
        if literal_declarations:
            if declarations or len(literal_declarations) != 1:
                raise RuntimeContractCompilationError(
                    f"{api_name} must declare exactly one fanout source"
                )
            parameter, declaration = literal_declarations[0]
            expected_fanout = {
                "strategy": "literal_values",
                "parameter": parameter,
                "values": declaration["values"],
                "batch_size": declaration["batch_size"],
            }
            if dict(fanout) != expected_fanout:
                raise RuntimeContractCompilationError(
                    f"registered {api_name} literal fanout does not match request observation"
                )
            continue
        if not declarations:
            if fanout.get("strategy") != "none":
                raise RuntimeContractCompilationError(
                    f"registered {api_name} fanout does not match request observation"
                )
            continue
        if len(declarations) != 1:
            raise RuntimeContractCompilationError(
                f"{api_name} must declare exactly one registered seed"
            )
        parameter, declaration = declarations[0]
        source = by_dataset.get(declaration["dataset_id"])
        if source is None:
            raise RuntimeContractCompilationError(
                f"{api_name}.{parameter} references unknown seed dataset"
            )
        field_names = {
            _text(field.get("name"), f"registered {source['dataset_id']}.field")
            for field in _list(
                source.get("fields"), f"registered {source['dataset_id']}.fields"
            )
            if isinstance(field, dict)
        }
        if declaration["field"] not in field_names:
            raise RuntimeContractCompilationError(
                f"{api_name}.{parameter} references unknown seed field"
            )
        for field_name in declaration.get("source_equals", {}):
            if field_name not in field_names:
                raise RuntimeContractCompilationError(
                    f"{api_name}.{parameter} selector references unknown seed field"
                )
        date_field = declaration.get("source_date_field")
        if date_field is not None and date_field not in field_names:
            raise RuntimeContractCompilationError(
                f"{api_name}.{parameter} date selector references unknown seed field"
            )
        expected_fanout = {
            "strategy": "dataset_field",
            "parameter": parameter,
            "source_dataset_id": declaration["dataset_id"],
            "source_field": declaration["field"],
            "batch_size": declaration["batch_size"],
        }
        for key in (
            "source_equals",
            "source_date_field",
            "source_date_lte_days",
            "max_values",
            "source_order",
        ):
            if key in declaration:
                expected_fanout[key] = declaration[key]
        if fanout != expected_fanout:
            raise RuntimeContractCompilationError(
                f"registered {api_name} fanout does not match request observation"
            )
        producer_api = _text(
            source.get("api_name"), f"registered {source['dataset_id']}.api_name"
        )
        producer_observation = observation_by_api.get(producer_api)
        if (
            producer_observation is None
            or producer_observation["probe_state"] != "executable"
            or source.get("probe_state") != "executable"
        ):
            raise RuntimeContractCompilationError(
                f"{api_name}.{parameter} seed producer must be executable"
            )
        schema_version = _text(
            source.get("schema_version"),
            f"registered {source['dataset_id']}.schema_version",
        )
        if _SEMANTIC_VERSION.fullmatch(schema_version) is None:
            raise RuntimeContractCompilationError(
                f"registered {source['dataset_id']} schema_version is invalid"
            )
        key = (declaration["dataset_id"], declaration["field"])
        requirements[key] = {
            "schema_version": schema_version,
            "producer_api": producer_api,
        }
    return requirements


def _trusted_seed_values(
    raw: list[Mapping[str, Any]] | None,
    *,
    registered_requirements: Mapping[tuple[str, str], Mapping[str, str]],
) -> dict[tuple[str, str], dict[str, Any]]:
    values: dict[tuple[str, str], dict[str, Any]] = {}
    for index, raw_item in enumerate([] if raw is None else deepcopy(raw)):
        label = f"dataset_field_values[{index}]"
        item = _mapping(raw_item, label)
        _exact_keys(
            item,
            frozenset(
                {
                    "dataset_id",
                    "field",
                    "value",
                    "receipt_id",
                    "receipt_state",
                    "data_through",
                    "schema_version",
                    "fresh",
                }
            ),
            label,
        )
        if item["receipt_state"] != "success" or item["fresh"] is not True:
            raise RuntimeContractCompilationError(
                f"{label} must bind a fresh success receipt"
            )
        dataset_id = _text(item["dataset_id"], f"{label}.dataset_id")
        field = _text(item["field"], f"{label}.field")
        if _SAFE_DATASET_ID.fullmatch(dataset_id) is None:
            raise RuntimeContractCompilationError(f"{label}.dataset_id is invalid")
        if _SAFE_SEED_FIELD.fullmatch(field) is None:
            raise RuntimeContractCompilationError(f"{label}.field is invalid")
        key = (dataset_id, field)
        requirement = registered_requirements.get(key)
        if requirement is None:
            raise RuntimeContractCompilationError(
                f"{label} is not a registered request seed"
            )
        receipt_id = _text(item["receipt_id"], f"{label}.receipt_id")
        data_through = _text(item["data_through"], f"{label}.data_through")
        if (
            _PUBLIC_EVIDENCE_TEXT.fullmatch(receipt_id) is None
            or _PUBLIC_EVIDENCE_TEXT.fullmatch(data_through) is None
            or _CREDENTIAL_TEXT.search(receipt_id) is not None
            or _CREDENTIAL_TEXT.search(data_through) is not None
        ):
            raise RuntimeContractCompilationError(
                f"{label} contains unsafe receipt evidence"
            )
        schema_version = _text(item["schema_version"], f"{label}.schema_version")
        if _SEMANTIC_VERSION.fullmatch(schema_version) is None:
            raise RuntimeContractCompilationError(
                f"{label}.schema_version must use MAJOR.MINOR.PATCH"
            )
        if schema_version != requirement["schema_version"]:
            raise RuntimeContractCompilationError(
                f"{label}.schema_version does not match registered producer"
            )
        value = item["value"]
        if isinstance(value, bool) or not isinstance(value, (str, int, float)):
            raise RuntimeContractCompilationError(f"{label}.value must be a scalar")
        if isinstance(value, float) and not math.isfinite(value):
            raise RuntimeContractCompilationError(f"{label}.value must be finite")
        if isinstance(value, str) and not value:
            raise RuntimeContractCompilationError(f"{label}.value must not be blank")
        if key in values:
            raise RuntimeContractCompilationError(f"duplicate trusted seed: {key}")
        values[key] = {
            "value": value,
            "receipt_id": receipt_id,
            "data_through": data_through,
            "schema_version": requirement["schema_version"],
        }
    return values


def compile_https_probe_plan(
    document_snapshot: bytes,
    request_observations: bytes,
    transport_observations: bytes,
    *,
    registered_contract_bundle: bytes,
    official_contract_sha256: str,
    transport_observations_sha256: str,
    request_observations_sha256: str,
    expected_commit: str,
    run_clock: datetime,
    scheduled_partition: str,
    dataset_field_values: list[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Materialize a credential-free, deterministic 190-interface HTTPS plan."""

    documents, official_sha = _bound_yaml_mapping(
        document_snapshot,
        official_contract_sha256,
        label="official contract",
    )
    request_document, request_sha = _bound_yaml_mapping(
        request_observations,
        request_observations_sha256,
        label="request observations",
    )
    transport_document, transport_sha = _bound_yaml_mapping(
        transport_observations,
        transport_observations_sha256,
        label="transport observations",
    )
    raw_contracts = _list(documents.get("contracts"), "document snapshot.contracts")
    by_api: dict[str, dict[str, Any]] = {}
    for index, raw_contract in enumerate(raw_contracts):
        contract = _mapping(raw_contract, f"document snapshot.contracts[{index}]")
        api_name = _text(contract.get("api_name"), f"document[{index}].api_name")
        if api_name in by_api:
            raise RuntimeContractCompilationError(f"duplicate document API: {api_name}")
        by_api[api_name] = contract
    if len(by_api) != _EXPECTED_IN_SCOPE_CONTRACTS:
        raise RuntimeContractCompilationError(
            "document snapshot must contain exactly 190 in-scope APIs"
        )
    observation_by_api = _request_observation_index(
        request_document,
        documents_by_api=by_api,
        transport_observations=transport_document,
        official_contract_sha256=official_sha,
        transport_observations_sha256=transport_sha,
    )
    request_provenance = _mapping(
        request_document["provenance"], "request observations.provenance"
    )
    registered_source = _mapping(
        request_provenance["registered_contract_bundle"],
        "request observations.provenance.registered_contract_bundle",
    )
    registered_document, _registered_sha = _bound_yaml_mapping(
        registered_contract_bundle,
        registered_source["sha256"],
        label="registered contract bundle",
    )
    try:
        registered_bundle = load_upstream_contract_bundle(registered_document)
    except ValueError as exc:
        raise RuntimeContractCompilationError(
            f"registered contract bundle is invalid: {exc}"
        ) from exc
    registered_requirements = _registered_seed_requirements(
        registered_bundle["contracts"], observation_by_api
    )
    commit = _text(expected_commit, "expected_commit")
    if re.fullmatch(r"[0-9a-f]{40}", commit) is None:
        raise RuntimeContractCompilationError("expected_commit must be a full git SHA")
    if run_clock.tzinfo is None or run_clock.utcoffset() is None:
        raise RuntimeContractCompilationError("run_clock must be timezone-aware")
    try:
        partition_clock = datetime.strptime(scheduled_partition, "%Y%m%d").replace(
            tzinfo=ZoneInfo("Asia/Shanghai")
        )
    except (TypeError, ValueError) as exc:
        raise RuntimeContractCompilationError(
            "scheduled_partition must be a valid YYYYMMDD date"
        ) from exc
    trusted_seeds = _trusted_seed_values(
        dataset_field_values,
        registered_requirements=registered_requirements,
    )
    entries: list[dict[str, Any]] = []
    for api_name in sorted(observation_by_api):
        observation = observation_by_api[api_name]
        effective_probe_state = observation["probe_state"]
        effective_probe_reasons = list(observation["probe_block_reasons"])
        effective_ingest_state = observation["ingest_contract_state"]
        effective_ingest_reasons = list(observation["ingest_contract_block_reasons"])
        dataset_declarations = [
            declaration
            for declaration in observation["parameters"].values()
            if declaration["source"] == "dataset_field"
        ]
        seeds_resolved = dataset_declarations and all(
            (declaration["dataset_id"], declaration["field"]) in trusted_seeds
            for declaration in dataset_declarations
        )
        if dataset_declarations and not seeds_resolved:
            effective_probe_state = "blocked"
            effective_probe_reasons = ["dependency_seed_receipt_unresolved"]
            effective_ingest_state = "blocked"
            effective_ingest_reasons = ["dependency_seed_receipt_unresolved"]
        elif effective_probe_reasons == ["dependency_seed_receipt_unresolved"]:
            effective_probe_state = "executable"
            effective_probe_reasons = []
            if effective_ingest_reasons == ["dependency_seed_receipt_unresolved"]:
                effective_ingest_state = "ready"
                effective_ingest_reasons = []
        params: dict[str, Any] = {}
        if effective_probe_state == "executable":
            for parameter, declaration in observation["parameters"].items():
                source = declaration["source"]
                if source == "literal":
                    params[parameter] = declaration["value"]
                elif source in {"run_clock", "scheduled_partition"}:
                    base = run_clock if source == "run_clock" else partition_clock
                    value = base + timedelta(seconds=declaration["offset_seconds"])
                    params[parameter] = _render_probe_clock(
                        value, declaration["transform"]
                    )
                elif source == "literal_values":
                    # The HTTPS plan is one bounded transport probe per API, not
                    # a collection cohort.  The runtime fanout remains the
                    # authority for every declared value and completeness.
                    params[parameter] = declaration["values"][0]
                else:
                    params[parameter] = trusted_seeds[
                        (declaration["dataset_id"], declaration["field"])
                    ]["value"]
        output_fields = _list(
            by_api[api_name].get("output_fields"), f"{api_name}.output_fields"
        )
        fields = [
            str(item["name"])
            for item in output_fields
            if isinstance(item, dict)
            and isinstance(item.get("name"), str)
            and _SAFE_PARAMETER_NAME.fullmatch(str(item["name"])) is not None
        ][:1]
        if not fields:
            raise RuntimeContractCompilationError(
                f"{api_name} has no safe output field for HTTPS probe"
            )
        entries.append(
            {
                "api_name": api_name,
                "scope_labels": list(observation["scope_labels"]),
                "probe_state": effective_probe_state,
                "probe_block_reasons": effective_probe_reasons,
                "ingest_contract_state": effective_ingest_state,
                "ingest_contract_block_reasons": effective_ingest_reasons,
                "params": dict(sorted(params.items())),
                "fields": fields,
            }
        )
    executable = sum(entry["probe_state"] == "executable" for entry in entries)
    ingest_ready = sum(entry["ingest_contract_state"] == "ready" for entry in entries)
    return {
        "schema_version": "tradingdatas.quicksync.https_probe_plan.v1",
        "production_ready": False,
        "provenance": {
            "expected_commit": commit,
            "official_contract_sha256": _sha256_text(
                official_sha, "official_contract_sha256"
            ),
            "transport_observations_sha256": _sha256_text(
                transport_sha,
                "transport_observations_sha256",
            ),
            "request_observations_sha256": request_sha,
            "api_names_sha256": hashlib.sha256(
                ("\n".join(sorted(observation_by_api)) + "\n").encode("utf-8")
            ).hexdigest(),
            "scheduled_partition": scheduled_partition,
            "run_clock": run_clock.isoformat(),
            "seed_authorities": [
                {
                    "dataset_id": dataset_id,
                    "field": field,
                    "receipt_id": authority["receipt_id"],
                    "data_through": authority["data_through"],
                    "schema_version": authority["schema_version"],
                }
                for (dataset_id, field), authority in sorted(trusted_seeds.items())
            ],
        },
        "counts": {
            "planned": len(entries),
            "executable": executable,
            "blocked": len(entries) - executable,
            "ingest_contract_ready": ingest_ready,
            "ingest_contract_blocked": len(entries) - ingest_ready,
        },
        "entries": entries,
    }


def render_contract_bundle(bundle: Mapping[str, Any]) -> str:
    return yaml.safe_dump(
        deepcopy(dict(bundle)),
        allow_unicode=True,
        sort_keys=False,
        width=1000,
    )


def _read_authority_bytes(path: Path, label: str) -> bytes:
    try:
        return path.read_bytes()
    except OSError as exc:
        raise RuntimeContractCompilationError(f"failed to read {label}: {exc}") from exc


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--documents", type=Path, default=DEFAULT_DOCUMENTS)
    parser.add_argument("--reviewed", type=Path, default=DEFAULT_REVIEWED)
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    parser.add_argument("--cadence-policy", type=Path, default=DEFAULT_CADENCE_POLICY)
    parser.add_argument(
        "--request-observations", type=Path, default=DEFAULT_REQUEST_OBSERVATIONS
    )
    parser.add_argument(
        "--transport-observations", type=Path, default=DEFAULT_TRANSPORT_OBSERVATIONS
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    inputs = {
        args.documents.resolve(),
        args.reviewed.resolve(),
        args.policy.resolve(),
        args.cadence_policy.resolve(),
        args.request_observations.resolve(),
        args.transport_observations.resolve(),
    }
    if args.output.resolve() in inputs:
        raise RuntimeContractCompilationError("output must not overwrite an input")
    document_bytes = _read_authority_bytes(args.documents, "document snapshot")
    reviewed_bytes = _read_authority_bytes(args.reviewed, "reviewed bundle")
    policy_bytes = _read_authority_bytes(args.policy, "runtime policy")
    cadence_policy_bytes = _read_authority_bytes(
        args.cadence_policy, "cadence policy"
    )
    request_bytes = _read_authority_bytes(
        args.request_observations, "request observations"
    )
    transport_bytes = _read_authority_bytes(
        args.transport_observations, "transport observations"
    )
    bundle = compile_runtime_contract_bundle(
        document_bytes,
        reviewed_bytes,
        policy_bytes,
        cadence_policy_bytes,
        request_observations=request_bytes,
        transport_observations=transport_bytes,
        official_contract_sha256=hashlib.sha256(document_bytes).hexdigest(),
        transport_observations_sha256=hashlib.sha256(transport_bytes).hexdigest(),
        request_observations_sha256=hashlib.sha256(request_bytes).hexdigest(),
    )
    _atomic_write(args.output, render_contract_bundle(bundle))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

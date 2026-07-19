#!/usr/bin/env python3
"""Compile all official in-scope Tushare documents into one runtime bundle.

Three separately reviewed contracts keep their stronger request, identity and
cadence declarations. Every other official contract is catalog-visible but
conservatively append-only and remains paused because it has no activation
entry. This keeps capability discovery complete without guessing entitlement,
request parameters, primary keys or collection frequency.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import os
from pathlib import Path
import re
import tempfile
from typing import Any, Mapping

import yaml

if __package__:
    from tools.compile_provider_native_registry import load_upstream_contract_bundle
else:  # pragma: no cover - exercised by the checked-in CLI test
    from compile_provider_native_registry import load_upstream_contract_bundle


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DOCUMENTS = ROOT / "config" / "tushare_document_contracts.v1.yaml"
DEFAULT_REVIEWED = ROOT / "config" / "tushare_reviewed_contracts.v1.yaml"
DEFAULT_POLICY = ROOT / "config" / "tushare_runtime_contract_policy.v1.yaml"
DEFAULT_OUTPUT = ROOT / "config" / "tushare_upstream_contracts.v1.yaml"

_SAFE_API_NAME = re.compile(r"[a-z][a-z0-9_]{0,63}\Z")
_SAFE_FIELD_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,63}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
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
            # The raw JSON row is still returned when callers omit fields. An
            # invalid provider name must not be invented or silently renamed.
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


def _catalog_only_contract(
    document: Mapping[str, Any],
    *,
    provider: str,
    defaults: Mapping[str, Any],
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
        "cadence_class": defaults["cadence_class"],
        "timezone": defaults["timezone"],
        "freshness_sla_seconds": defaults["freshness_sla_seconds"],
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


def compile_runtime_contract_bundle(
    document_snapshot: Mapping[str, Any],
    reviewed_bundle: Mapping[str, Any],
    policy_document: Mapping[str, Any],
) -> dict[str, object]:
    """Return a deterministic 190-interface bundle without runtime activation."""

    documents = _mapping(deepcopy(document_snapshot), "document snapshot")
    provider, defaults = _normalized_policy(policy_document)
    if documents.get("snapshot_id") != policy_document.get("source_snapshot_id"):
        raise RuntimeContractCompilationError(
            "document snapshot id does not match policy"
        )
    expected_sha = _text(
        policy_document.get("source_snapshot_canonical_sha256"),
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
    for index, raw in enumerate(raw_documents):
        document = _mapping(raw, f"document snapshot.contracts[{index}]")
        api_name = _text(document.get("api_name"), f"document[{index}].api_name")
        if api_name in by_api:
            raise RuntimeContractCompilationError(f"duplicate document API: {api_name}")
        by_api[api_name] = document
    expected_count = documents.get("counts", {}).get("in_scope_contracts")
    if expected_count != len(by_api):
        raise RuntimeContractCompilationError("document snapshot count is inconsistent")

    try:
        reviewed = load_upstream_contract_bundle(deepcopy(reviewed_bundle))
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

    contracts = [
        deepcopy(reviewed_by_api[api_name])
        if api_name in reviewed_by_api
        else _catalog_only_contract(
            by_api[api_name], provider=provider, defaults=defaults
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
    # Reuse the strict registry compiler validator before returning anything.
    return load_upstream_contract_bundle(result)


def render_contract_bundle(bundle: Mapping[str, Any]) -> str:
    return yaml.safe_dump(
        deepcopy(dict(bundle)),
        allow_unicode=True,
        sort_keys=False,
        width=1000,
    )


def _load_yaml(path: Path, label: str) -> dict[str, Any]:
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise RuntimeContractCompilationError(f"failed to read {label}: {exc}") from exc
    return _mapping(value, label)


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
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    inputs = {args.documents.resolve(), args.reviewed.resolve(), args.policy.resolve()}
    if args.output.resolve() in inputs:
        raise RuntimeContractCompilationError("output must not overwrite an input")
    bundle = compile_runtime_contract_bundle(
        _load_yaml(args.documents, "document snapshot"),
        _load_yaml(args.reviewed, "reviewed bundle"),
        _load_yaml(args.policy, "runtime policy"),
    )
    _atomic_write(args.output, render_contract_bundle(bundle))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

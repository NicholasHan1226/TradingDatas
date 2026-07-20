#!/usr/bin/env python3
"""One-shot, read-only Tushare entitlement probes from a reviewed policy."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
import re
import sys
from types import MappingProxyType
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from collectors.tushare.tushare_common import (  # noqa: E402
    ProviderCallOutcome,
    read_tushare_config,
    tushare_rows_outcome,
)


DEFAULT_POLICY = ROOT / "config" / "provider_entitlement_probes.v1.yaml"
DEFAULT_DOCUMENTS = ROOT / "config" / "tushare_document_contracts.v1.yaml"
DEFAULT_REGISTRY = ROOT / "config" / "provider_native_dataset_registry.yaml"

_POLICY_ID = "tushare-entitlement-probe.v1"
_PROVIDER = "tushare"
_PERMISSION_POLICY_VERSION = "tushare-permission-denial.v1"
_EXECUTABLE_CLASSIFICATIONS = frozenset({"bounded_static_probe"})
_CLASSIFICATIONS = frozenset(
    {
        "existing_activation_evidence",
        "bounded_static_probe",
        "conditional_parameter_review_required",
        "time_window_review_required",
        "empty_parameter_review_required",
        "required_parameter_config",
    }
)
_HASH_PATTERN = re.compile(r"[0-9a-f]{64}")
_COMMIT_PATTERN = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})")
_UTC_OBSERVED_AT_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")


class _UniqueLoader(yaml.SafeLoader):
    pass


def _construct_unique_mapping(
    loader: _UniqueLoader,
    node: yaml.MappingNode,
    deep: bool = False,
) -> dict[Any, Any]:
    mapping: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            raise ValueError(f"duplicate YAML key: {key}")
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_UniqueLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)


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
class ProbePolicy:
    policy_id: str
    provider: str
    config_sha256: str
    document_snapshot_id: str
    document_snapshot_sha256: str
    registry_sha256: str
    contract_count: int
    classifications: Mapping[str, tuple[str, ...]]
    contract_targets: Mapping[str, tuple[str, str, str]]
    executable_probes: tuple[ProbeSpec, ...]
    locked_error_code: str
    locked_provider_codes: frozenset[str]


def _read_yaml(path: Path, label: str) -> tuple[dict[str, Any], bytes]:
    raw = path.read_bytes()
    try:
        value = yaml.load(raw.decode("utf-8"), Loader=_UniqueLoader)
    except (UnicodeError, yaml.YAMLError, ValueError) as exc:
        raise ValueError(f"{label} is not valid canonical YAML") from exc
    if type(value) is not dict:
        raise ValueError(f"{label} must be a mapping")
    return value, raw


def _exact_keys(value: Mapping[str, Any], expected: set[str], label: str) -> None:
    if set(value) != expected:
        raise ValueError(f"{label} keys do not match the frozen contract")


def _text(value: object, label: str) -> str:
    if type(value) is not str or not value or value != value.strip():
        raise ValueError(f"{label} must be non-empty canonical text")
    return value


def _sha256_text(value: object, label: str) -> str:
    text = _text(value, label)
    if _HASH_PATTERN.fullmatch(text) is None:
        raise ValueError(f"{label} must be SHA-256")
    return text


def _positive_int(value: object, label: str) -> int:
    if type(value) is not int or value <= 0:
        raise ValueError(f"{label} must be a positive integer")
    return value


def _json_scalar(value: object, label: str) -> object:
    if value is None or type(value) in (str, bool, int):
        return value
    if type(value) is float and math.isfinite(value):
        return value
    raise ValueError(f"{label} must be a finite JSON scalar")


def canonical_sha256(value: object) -> str:
    rendered = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(rendered).hexdigest()


def load_probe_policy(
    policy_path: Path,
    documents_path: Path,
    registry_path: Path,
) -> ProbePolicy:
    policy, policy_raw = _read_yaml(policy_path, "probe policy")
    documents, documents_raw = _read_yaml(documents_path, "document snapshot")
    registry, registry_raw = _read_yaml(registry_path, "dataset registry")
    _exact_keys(
        policy,
        {
            "version",
            "policy_id",
            "provider",
            "source_documents",
            "source_registry",
            "permission_policy",
            "classifications",
            "executable_probes",
        },
        "probe policy",
    )
    if policy["version"] != 1 or policy["policy_id"] != _POLICY_ID:
        raise ValueError("probe policy version is unsupported")
    if policy["provider"] != _PROVIDER:
        raise ValueError("probe policy provider is unsupported")

    document_source = policy["source_documents"]
    registry_source = policy["source_registry"]
    permission_policy = policy["permission_policy"]
    if type(document_source) is not dict or type(registry_source) is not dict:
        raise ValueError("probe policy source bindings must be mappings")
    if type(permission_policy) is not dict:
        raise ValueError("probe policy permission policy must be a mapping")
    _exact_keys(
        document_source,
        {"snapshot_id", "sha256", "contract_count"},
        "document source binding",
    )
    _exact_keys(
        registry_source,
        {"version", "sha256", "dataset_count"},
        "registry source binding",
    )
    _exact_keys(
        permission_policy,
        {"version", "locked_error_code", "provider_codes"},
        "permission policy",
    )
    expected_document_sha = _sha256_text(
        document_source["sha256"], "document source SHA-256"
    )
    if hashlib.sha256(documents_raw).hexdigest() != expected_document_sha:
        raise ValueError("document snapshot SHA-256 mismatch")
    expected_registry_sha = _sha256_text(
        registry_source["sha256"], "registry source SHA-256"
    )
    if hashlib.sha256(registry_raw).hexdigest() != expected_registry_sha:
        raise ValueError("dataset registry SHA-256 mismatch")
    if document_source["snapshot_id"] != documents.get("snapshot_id"):
        raise ValueError("document snapshot id mismatch")
    if registry_source["version"] != registry.get("version"):
        raise ValueError("dataset registry version mismatch")
    document_count = _positive_int(
        document_source["contract_count"], "document contract count"
    )
    registry_count = _positive_int(
        registry_source["dataset_count"], "registry dataset count"
    )
    if document_count != registry_count:
        raise ValueError("document and registry counts differ")

    raw_contracts = documents.get("contracts")
    raw_datasets = registry.get("datasets")
    if type(raw_contracts) is not list or type(raw_datasets) is not list:
        raise ValueError("document contracts and registry datasets must be lists")
    if len(raw_contracts) != document_count or len(raw_datasets) != registry_count:
        raise ValueError("source count does not match the frozen policy")

    document_by_api: dict[str, dict[str, Any]] = {}
    for index, contract in enumerate(raw_contracts):
        if type(contract) is not dict:
            raise ValueError(f"document contract {index} must be a mapping")
        api_name = _text(
            contract.get("api_name"), f"document contract {index}.api_name"
        )
        if api_name in document_by_api:
            raise ValueError(f"duplicate document API: {api_name}")
        _sha256_text(contract.get("doc_sha256"), f"{api_name}.doc_sha256")
        if type(contract.get("input_fields")) is not list:
            raise ValueError(f"{api_name}.input_fields must be a list")
        if type(contract.get("output_fields")) is not list:
            raise ValueError(f"{api_name}.output_fields must be a list")
        document_by_api[api_name] = contract

    dataset_by_api: dict[str, str] = {}
    for index, dataset in enumerate(raw_datasets):
        if type(dataset) is not dict:
            raise ValueError(f"registry dataset {index} must be a mapping")
        dataset_id = _text(
            dataset.get("dataset_id"), f"registry dataset {index}.dataset_id"
        )
        bindings = dataset.get("provider_bindings")
        if (
            type(bindings) is not list
            or len(bindings) != 1
            or type(bindings[0]) is not dict
        ):
            raise ValueError(f"{dataset_id} must have one provider binding")
        binding = bindings[0]
        if binding.get("provider") != _PROVIDER:
            raise ValueError(f"{dataset_id} provider binding is not Tushare")
        api_name = _text(binding.get("api_name"), f"{dataset_id}.api_name")
        if api_name in dataset_by_api:
            raise ValueError(f"duplicate registry API: {api_name}")
        dataset_by_api[api_name] = dataset_id
    if set(document_by_api) != set(dataset_by_api):
        raise ValueError("document and registry APIs differ")

    raw_classes = policy["classifications"]
    if type(raw_classes) is not dict or set(raw_classes) != _CLASSIFICATIONS:
        raise ValueError("classification names do not match the frozen policy")
    classifications: dict[str, tuple[str, ...]] = {}
    classified: list[str] = []
    for name in sorted(raw_classes):
        values = raw_classes[name]
        if type(values) is not list:
            raise ValueError(f"classification {name} must be a list")
        normalized = tuple(_text(value, f"classification {name}") for value in values)
        if tuple(sorted(normalized)) != normalized or len(set(normalized)) != len(
            normalized
        ):
            raise ValueError(f"classification {name} must be sorted and unique")
        classifications[name] = normalized
        classified.extend(normalized)
    if len(classified) != len(set(classified)):
        raise ValueError("classification contains a duplicate API")
    if set(classified) != set(document_by_api):
        raise ValueError("classifications must exactly cover official contracts")
    classification_by_api = {
        api_name: classification
        for classification, api_names in classifications.items()
        for api_name in api_names
    }
    contract_targets = {
        dataset_by_api[api_name]: (
            api_name,
            classification_by_api[api_name],
            document_by_api[api_name]["doc_sha256"],
        )
        for api_name in sorted(document_by_api)
    }

    raw_specs = policy["executable_probes"]
    if type(raw_specs) is not dict:
        raise ValueError("executable_probes must be a mapping")
    specs: list[ProbeSpec] = []
    for api_name in sorted(raw_specs):
        spec = raw_specs[api_name]
        if type(spec) is not dict:
            raise ValueError(f"probe {api_name} must be a mapping")
        _exact_keys(
            spec,
            {
                "dataset_id",
                "classification",
                "executable",
                "params",
                "parameter_sources",
                "fields",
                "max_response_bytes",
            },
            f"probe {api_name}",
        )
        if spec["executable"] is not True:
            raise ValueError(f"probe {api_name} must be explicitly executable")
        classification = _text(
            spec["classification"], f"probe {api_name}.classification"
        )
        if classification not in _EXECUTABLE_CLASSIFICATIONS:
            raise ValueError(f"probe {api_name} is not an executable classification")
        if api_name not in classifications[classification]:
            raise ValueError(f"probe {api_name} classification binding differs")
        dataset_id = _text(spec["dataset_id"], f"probe {api_name}.dataset_id")
        if dataset_by_api.get(api_name) != dataset_id:
            raise ValueError(f"probe {api_name} dataset binding differs")
        raw_params = spec["params"]
        raw_sources = spec["parameter_sources"]
        raw_fields = spec["fields"]
        if type(raw_params) is not dict or type(raw_sources) is not dict:
            raise ValueError(f"probe {api_name} params and sources must be mappings")
        if type(raw_fields) is not list or not raw_fields:
            raise ValueError(f"probe {api_name}.fields must be a non-empty list")
        params = {
            _text(key, f"probe {api_name}.params key"): _json_scalar(
                value, f"probe {api_name}.params.{key}"
            )
            for key, value in raw_params.items()
        }
        parameter_sources = {
            _text(key, f"probe {api_name}.parameter_sources key"): _text(
                value, f"probe {api_name}.parameter_sources.{key}"
            )
            for key, value in raw_sources.items()
        }
        if set(parameter_sources) != set(params) or set(parameter_sources.values()) != {
            "reviewed_policy_literal"
        }:
            raise ValueError(f"probe {api_name} parameter sources are incomplete")
        input_fields = {
            _text(field.get("name"), f"{api_name}.input field")
            for field in document_by_api[api_name]["input_fields"]
            if type(field) is dict
        }
        required_fields = {
            _text(field.get("name"), f"{api_name}.required input field")
            for field in document_by_api[api_name]["input_fields"]
            if type(field) is dict and field.get("required") == "Y"
        }
        if not set(params).issubset(input_fields) or not required_fields.issubset(
            params
        ):
            raise ValueError(f"probe {api_name} parameters do not satisfy the document")
        fields = tuple(_text(value, f"probe {api_name}.field") for value in raw_fields)
        output_fields = {
            _text(field.get("name"), f"{api_name}.output field")
            for field in document_by_api[api_name]["output_fields"]
            if type(field) is dict
        }
        if len(set(fields)) != len(fields) or not set(fields).issubset(output_fields):
            raise ValueError(
                f"probe {api_name} requested fields differ from the document"
            )
        max_response_bytes = _positive_int(
            spec["max_response_bytes"], f"probe {api_name}.max_response_bytes"
        )
        if max_response_bytes > 64 * 1024 * 1024:
            raise ValueError(
                f"probe {api_name} response budget exceeds the hard maximum"
            )
        specs.append(
            ProbeSpec(
                dataset_id=dataset_id,
                api_name=api_name,
                classification=classification,
                params=MappingProxyType(dict(sorted(params.items()))),
                parameter_sources=MappingProxyType(
                    dict(sorted(parameter_sources.items()))
                ),
                fields=fields,
                max_response_bytes=max_response_bytes,
                source_document_sha256=document_by_api[api_name]["doc_sha256"],
            )
        )

    if permission_policy["version"] != _PERMISSION_POLICY_VERSION:
        raise ValueError("permission policy version is unsupported")
    locked_error_code = _text(
        permission_policy["locked_error_code"], "locked permission error code"
    )
    if locked_error_code != "permission_denied":
        raise ValueError("locked permission error code is unsupported")
    raw_codes = permission_policy["provider_codes"]
    if type(raw_codes) is not list or not raw_codes:
        raise ValueError("permission provider codes must be a non-empty list")
    locked_codes = frozenset(
        str(value) for value in raw_codes if type(value) in (int, str)
    )
    if locked_codes != frozenset({"-2001"}):
        raise ValueError("permission provider codes do not match the strict allowlist")

    return ProbePolicy(
        policy_id=_POLICY_ID,
        provider=_PROVIDER,
        config_sha256=hashlib.sha256(policy_raw).hexdigest(),
        document_snapshot_id=documents["snapshot_id"],
        document_snapshot_sha256=expected_document_sha,
        registry_sha256=expected_registry_sha,
        contract_count=document_count,
        classifications=MappingProxyType(classifications),
        contract_targets=MappingProxyType(contract_targets),
        executable_probes=tuple(specs),
        locked_error_code=locked_error_code,
        locked_provider_codes=locked_codes,
    )


def build_plan(
    policy: ProbePolicy, *, code_commit: str | None = None
) -> dict[str, Any]:
    if code_commit is not None:
        _validated_commit(code_commit)
    return {
        "schema_version": "tradingdatas.entitlement_probe.plan.v1",
        "mode": "plan",
        "provider": policy.provider,
        "policy_id": policy.policy_id,
        "code_commit": code_commit,
        "config_sha256": policy.config_sha256,
        "document_snapshot_id": policy.document_snapshot_id,
        "document_snapshot_sha256": policy.document_snapshot_sha256,
        "registry_sha256": policy.registry_sha256,
        "contract_count": policy.contract_count,
        "classification_counts": {
            key: len(value) for key, value in sorted(policy.classifications.items())
        },
        "executable_probe_count": len(policy.executable_probes),
        "executable_dataset_ids": [
            spec.dataset_id for spec in policy.executable_probes
        ],
        "provider_calls": 0,
        "facts_written": 0,
        "ingest_receipts_written": 0,
        "activation_mutations": 0,
    }


def _validated_commit(value: str) -> str:
    if type(value) is not str or _COMMIT_PATTERN.fullmatch(value) is None:
        raise ValueError("code_commit must be a lowercase 40 or 64 character hash")
    return value


def _validated_observed_at(value: str) -> str:
    if type(value) is not str or _UTC_OBSERVED_AT_PATTERN.fullmatch(value) is None:
        raise ValueError("observed_at must be an exact UTC second ending in Z")
    try:
        datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        raise ValueError("observed_at must be a valid UTC timestamp") from None
    return value


def _decision(
    policy: ProbePolicy,
    outcome: ProviderCallOutcome,
    *,
    response_observed_bytes: int | None,
    response_sha256: str | None,
    response_truncated: bool,
) -> tuple[str, list[str]]:
    if outcome.state in {"success", "empty"}:
        if (
            response_observed_bytes is None
            or response_sha256 is None
            or response_truncated
        ):
            return "unknown", ["response_metadata_incomplete"]
        return (
            "entitled_active",
            [
                "provider_success"
                if outcome.state == "success"
                else "provider_legal_empty"
            ],
        )
    if outcome.error_code == "resource_budget":
        return "unknown", ["response_resource_budget"]
    if (
        outcome.state == "failed"
        and outcome.error_code == policy.locked_error_code
        and str(outcome.provider_code) in policy.locked_provider_codes
    ):
        return "locked", ["strict_permission_denial"]
    return "unknown", ["provider_failure_unclassified"]


def execute_probe(
    policy: ProbePolicy,
    *,
    token: str,
    observed_at: str,
    code_commit: str,
    provider_call: Callable[..., ProviderCallOutcome] = tushare_rows_outcome,
    selected_dataset_ids: Sequence[str] | None = None,
) -> dict[str, Any]:
    code_commit = _validated_commit(code_commit)
    observed_at = _validated_observed_at(observed_at)
    if type(token) is not str or not token:
        raise ValueError("provider credential is unavailable")
    specs_by_dataset = {spec.dataset_id: spec for spec in policy.executable_probes}
    if selected_dataset_ids is None:
        targets: tuple[ProbeSpec | str, ...] = policy.executable_probes
    else:
        selected = tuple(selected_dataset_ids)
        if len(set(selected)) != len(selected) or any(
            type(value) is not str or value not in policy.contract_targets
            for value in selected
        ):
            raise ValueError(
                "selected_dataset_ids must be unique known policy datasets"
            )
        targets = tuple(
            specs_by_dataset.get(dataset_id, dataset_id)
            for dataset_id in sorted(selected)
        )

    results: list[dict[str, Any]] = []
    provider_calls = 0
    for target in targets:
        if isinstance(target, str):
            api_name, classification, document_sha256 = policy.contract_targets[target]
            results.append(
                {
                    "dataset_id": target,
                    "api_name": api_name,
                    "classification": classification,
                    "source_document_sha256": document_sha256,
                    "canonical_request_sha256": None,
                    "parameter_sources": {},
                    "observed_at": observed_at,
                    "typed_outcome": None,
                    "row_count": 0,
                    "rows_sha256": canonical_sha256([]),
                    "response_observed_bytes": None,
                    "response_sha256": None,
                    "response_truncated": False,
                    "decision": "unknown",
                    "reasons": ["not_executable"],
                }
            )
            continue
        spec = target
        request = {
            "api_name": spec.api_name,
            "params": dict(spec.params),
            "fields": list(spec.fields),
        }
        telemetry: list[tuple[int, str | None]] = []

        def observe_response(size: int, digest: str | None) -> None:
            if (
                telemetry
                or type(size) is not int
                or size < 0
                or (digest is not None and _HASH_PATTERN.fullmatch(digest) is None)
            ):
                telemetry[:] = [(-1, None)]
                return
            telemetry.append((size, digest))

        call_exception = False
        try:
            provider_calls += 1
            outcome = provider_call(
                spec.api_name,
                token,
                params=dict(spec.params),
                fields=",".join(spec.fields),
                max_response_bytes=spec.max_response_bytes,
                response_observer=observe_response,
            )
            if not isinstance(outcome, ProviderCallOutcome):
                raise TypeError("provider outcome type is invalid")
            outcome.validate_invariants()
        except Exception:
            call_exception = True
            outcome = ProviderCallOutcome(
                state="failed",
                rows=(),
                provider_code=None,
                error_code="transport_error",
                error_message="provider call failed",
            )

        response_bytes: int | None = None
        response_sha256: str | None = None
        if len(telemetry) == 1 and telemetry[0][0] >= 0:
            response_bytes, response_sha256 = telemetry[0]
        if call_exception:
            decision, reasons = "unknown", ["provider_call_exception"]
        elif telemetry == [(-1, None)]:
            decision, reasons = "unknown", ["response_metadata_invalid"]
        else:
            response_truncated = outcome.error_code == "resource_budget"
            decision, reasons = _decision(
                policy,
                outcome,
                response_observed_bytes=response_bytes,
                response_sha256=response_sha256,
                response_truncated=response_truncated,
            )
        rows = outcome.mutable_rows() if outcome.state == "success" else []
        results.append(
            {
                "dataset_id": spec.dataset_id,
                "api_name": spec.api_name,
                "classification": spec.classification,
                "source_document_sha256": spec.source_document_sha256,
                "canonical_request_sha256": canonical_sha256(request),
                "parameter_sources": dict(spec.parameter_sources),
                "observed_at": observed_at,
                "typed_outcome": {
                    "state": outcome.state,
                    "provider_code": outcome.provider_code,
                    "error_code": outcome.error_code,
                },
                "row_count": len(rows),
                "rows_sha256": canonical_sha256(rows),
                "response_observed_bytes": response_bytes,
                "response_sha256": response_sha256,
                "response_truncated": outcome.error_code == "resource_budget",
                "decision": decision,
                "reasons": reasons,
            }
        )

    evidence: dict[str, Any] = {
        "schema_version": "tradingdatas.entitlement_probe.evidence.v1",
        "mode": "execute",
        "provider": policy.provider,
        "policy_id": policy.policy_id,
        "permission_policy_version": _PERMISSION_POLICY_VERSION,
        "code_commit": code_commit,
        "config_sha256": policy.config_sha256,
        "document_snapshot_id": policy.document_snapshot_id,
        "document_snapshot_sha256": policy.document_snapshot_sha256,
        "registry_sha256": policy.registry_sha256,
        "observed_at": observed_at,
        "provider_calls": provider_calls,
        "facts_written": 0,
        "ingest_receipts_written": 0,
        "activation_mutations": 0,
        "results": results,
    }
    evidence["evidence_self_sha256"] = canonical_sha256(evidence)
    return evidence


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_POLICY)
    parser.add_argument("--documents", type=Path, default=DEFAULT_DOCUMENTS)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--code-commit")
    parser.add_argument("--observed-at")
    parser.add_argument("--dataset-id", action="append", default=None)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    policy = load_probe_policy(args.config, args.documents, args.registry)
    if not args.execute:
        output = build_plan(policy, code_commit=args.code_commit)
    else:
        if args.code_commit is None or args.observed_at is None:
            parser.error("--execute requires --code-commit and --observed-at")
        token = read_tushare_config()["token"]
        output = execute_probe(
            policy,
            token=token,
            observed_at=args.observed_at,
            code_commit=args.code_commit,
            selected_dataset_ids=args.dataset_id,
        )
    print(json.dumps(output, sort_keys=True, separators=(",", ":"), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

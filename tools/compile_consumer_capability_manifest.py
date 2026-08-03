"""Compile a contract-only, machine-readable capability manifest for internal consumers.

The manifest is deliberately separate from runtime receipt authority.  It states
what the checked-in registry declares and which configured consumers may request
those datasets through the fixed read-only API; it never calls a provider, opens
SQLite, or asserts ready/live/stable runtime health.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dataset_registry import (
    DatasetDefinition,
    ProviderBinding,
    load_dataset_registry,
)

DEFAULT_PROFILE = ROOT / "config" / "internal_consumer_capability_profile.v1.yaml"
DEFAULT_REGISTRY = ROOT / "config" / "provider_native_dataset_registry.yaml"
_CONSUMER_ID = re.compile(r"[a-z][a-z0-9_]{0,63}\Z")
_ACCESS_MODES = frozenset({"api_read_only"})
_RUNTIME_READINESS = frozenset({"formal_ready"})


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _string_list(value: object, label: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{label} must be a non-empty list")
    if any(type(item) is not str or not item for item in value):
        raise ValueError(f"{label} values are invalid")
    if list(value) != sorted(value) or len(set(value)) != len(value):
        raise ValueError(f"{label} must be sorted and unique")
    return tuple(value)


def _load_profile(path: Path) -> tuple[str, tuple[dict[str, object], ...]]:
    try:
        payload = yaml.safe_load(path.read_bytes())
    except yaml.YAMLError as exc:
        raise ValueError("consumer capability profile must be YAML") from exc
    if not isinstance(payload, dict) or set(payload) != {"version", "profile_id", "consumers"}:
        raise ValueError("consumer capability profile keys are invalid")
    if payload["version"] != 1:
        raise ValueError("consumer capability profile version is invalid")
    profile_id = payload["profile_id"]
    if type(profile_id) is not str or not profile_id:
        raise ValueError("consumer capability profile_id is invalid")
    consumers = payload["consumers"]
    if not isinstance(consumers, list) or not consumers:
        raise ValueError("consumer capability profile consumers are invalid")
    normalized: list[dict[str, object]] = []
    for index, raw in enumerate(consumers):
        label = f"consumer capability profile consumers[{index}]"
        if not isinstance(raw, dict) or set(raw) != {
            "consumer_id",
            "access_mode",
            "markets",
            "required_scopes",
            "data_classifications",
            "runtime_readiness_required",
        }:
            raise ValueError(f"{label} keys are invalid")
        consumer_id = raw["consumer_id"]
        if type(consumer_id) is not str or _CONSUMER_ID.fullmatch(consumer_id) is None:
            raise ValueError(f"{label}.consumer_id is invalid")
        access_mode = raw["access_mode"]
        if access_mode not in _ACCESS_MODES:
            raise ValueError(f"{label}.access_mode is invalid")
        readiness = _string_list(raw["runtime_readiness_required"], f"{label}.runtime_readiness_required")
        if not set(readiness).issubset(_RUNTIME_READINESS):
            raise ValueError(f"{label}.runtime_readiness_required is invalid")
        normalized.append(
            {
                "consumer_id": consumer_id,
                "access_mode": access_mode,
                "markets": _string_list(raw["markets"], f"{label}.markets"),
                "required_scopes": _string_list(raw["required_scopes"], f"{label}.required_scopes"),
                "data_classifications": _string_list(
                    raw["data_classifications"], f"{label}.data_classifications"
                ),
                "runtime_readiness_required": readiness,
            }
        )
    normalized.sort(key=lambda item: str(item["consumer_id"]))
    ids = [str(item["consumer_id"]) for item in normalized]
    if len(ids) != len(set(ids)):
        raise ValueError("consumer capability profile consumer_id values must be unique")
    return profile_id, tuple(normalized)


def _request_template_ts_code_scope(binding: ProviderBinding) -> dict[str, object] | None:
    """Return a frozen scope only for an explicit multi-code literal request."""

    if binding.fanout is not None and binding.fanout.strategy != "none":
        return None
    raw_value = binding.request_template.get("ts_code")
    if type(raw_value) is not str or "," not in raw_value:
        return None
    values = tuple(raw_value.split(","))
    if (
        len(values) < 2
        or any(not value or value != value.strip() for value in values)
        or len(set(values)) != len(values)
    ):
        raise ValueError(
            f"{binding.api_name} request_template.ts_code literal universe is invalid"
        )
    return {
        "kind": "versioned_literal_values",
        "frozen": True,
        "parameter": "ts_code",
        "value_count": len(values),
        "values_sha256": hashlib.sha256(_canonical_json(list(values))).hexdigest(),
        "batch_semantics": {
            "request_count": 1,
            "values_per_request": len(values),
        },
    }


def _entity_scope(binding: ProviderBinding) -> dict[str, object]:
    request_template_scope = _request_template_ts_code_scope(binding)
    if request_template_scope is not None:
        return request_template_scope
    fanout = binding.fanout
    if fanout is None or fanout.strategy == "none":
        return {"kind": "none"}
    if fanout.strategy == "literal_values":
        values = list(fanout.values)
        return {
            "kind": "versioned_literal_values",
            "frozen": True,
            "value_count": len(values),
            "values_sha256": hashlib.sha256(_canonical_json(values)).hexdigest(),
            "batch_size": fanout.batch_size,
        }
    if fanout.strategy != "dataset_field":
        raise ValueError("unsupported fanout policy")
    return {
        "kind": "dynamic_seed_dataset",
        "frozen": False,
        "source_dataset_id": fanout.source_dataset_id,
        "source_field": fanout.source_field,
        "max_values": fanout.max_values,
        "batch_size": fanout.batch_size,
    }


def _applicability(
    dataset: DatasetDefinition, consumers: Sequence[Mapping[str, object]]
) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for consumer in consumers:
        if (
            dataset.market not in consumer["markets"]
            or dataset.required_scope not in consumer["required_scopes"]
            or dataset.data_classification not in consumer["data_classifications"]
        ):
            continue
        records.append(
            {
                "consumer_id": consumer["consumer_id"],
                "access_mode": consumer["access_mode"],
                "contract_eligible": True,
                "runtime_readiness_required": list(consumer["runtime_readiness_required"]),
            }
        )
    return records


def compile_manifest(*, profile_path: Path, registry_path: Path) -> dict[str, object]:
    """Compile a deterministic manifest from the immutable registry and profile bytes."""

    profile_id, consumers = _load_profile(profile_path)
    registry = load_dataset_registry(registry_path)
    datasets: list[dict[str, object]] = []
    matched_consumers: Counter[str] = Counter()
    cadence: Counter[str] = Counter()
    shapes: Counter[str] = Counter()
    dynamic_unfrozen = 0
    for dataset in sorted(registry.datasets, key=lambda item: item.dataset_id):
        bindings = dataset.provider_bindings
        request_shapes = sorted(
            {binding.request_shape for binding in bindings if binding.request_shape is not None}
        )
        if len(request_shapes) != 1:
            raise ValueError(f"{dataset.dataset_id} must declare exactly one request_shape")
        entity_scopes = [_entity_scope(binding) for binding in bindings]
        if len({_canonical_json(scope) for scope in entity_scopes}) != 1:
            raise ValueError(f"{dataset.dataset_id} provider bindings disagree on entity scope")
        entity_scope = entity_scopes[0]
        applicable = _applicability(dataset, consumers)
        for item in applicable:
            matched_consumers[str(item["consumer_id"])] += 1
        if entity_scope.get("frozen") is False:
            dynamic_unfrozen += 1
        cadence[dataset.cadence_class] += 1
        shapes[request_shapes[0]] += 1
        datasets.append(
            {
                "dataset_id": dataset.dataset_id,
                "cadence": dataset.cadence_class,
                "request_shape": request_shapes[0],
                "read_contract": {
                    "identity_fields": list(dataset.primary_key),
                    "freshness_sla_seconds": dataset.freshness_sla_seconds,
                    "readable_fields": [
                        field.name for field in dataset.fields if field.selectable
                    ],
                    "default_projection": list(dataset.default_projection),
                },
                "entity_scope": entity_scope,
                "consumer_applicability": applicable,
                "runtime_evidence": {
                    "authority": "onboarding_status_artifact",
                    "status": "not_attested_by_contract_manifest",
                },
            }
        )
    unmatched = [
        str(consumer["consumer_id"])
        for consumer in consumers
        if matched_consumers[str(consumer["consumer_id"])] == 0
    ]
    if unmatched:
        raise ValueError(
            "consumer capability profile does not match any registry dataset: "
            + ", ".join(unmatched)
        )
    return {
        "schema_version": 1,
        "profile_id": profile_id,
        "profile_sha256": _sha256(profile_path),
        "registry_sha256": _sha256(registry_path),
        "runtime_claim_boundary": {
            "authority": "onboarding_status_artifact",
            "contract_manifest_asserts": "contract_only",
            "runtime_states_not_asserted": ["ready", "live", "stable"],
        },
        "coverage": {
            "dataset_count": len(datasets),
            "by_cadence": dict(sorted(cadence.items())),
            "by_request_shape": dict(sorted(shapes.items())),
            "dynamic_unfrozen_entity_scopes": dynamic_unfrozen,
        },
        "datasets": datasets,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", type=Path, default=DEFAULT_PROFILE)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    args.output.write_bytes(_canonical_json(compile_manifest(profile_path=args.profile, registry_path=args.registry)) + b"\n")
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())

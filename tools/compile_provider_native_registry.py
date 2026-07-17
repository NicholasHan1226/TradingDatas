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

PROVIDER = "tushare"
PROVIDER_ADAPTER_VERSION = "tushare-provider-native.v1"
READ_ADAPTER_VERSION = "provider-native-json.v1"
PROVIDER_NATIVE_TABLE = "provider_dataset_rows"

# Generic technical admission limits, shared by every compiled binding.  An
# explicit legacy row_limit_guard may only tighten the row limit.  These are not
# provider semantics and do not activate any dataset.
DEFAULT_MAX_ROWS_PER_ATTEMPT = 10_000
DEFAULT_MAX_PAYLOAD_BYTES_PER_ROW = 65_536
DEFAULT_MAX_BATCH_BYTES = 4_194_304
DEFAULT_MAX_NESTING_DEPTH = 16

_SAFE_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,63}")
_LEGACY_PLACEHOLDER = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]{0,63})\}")
_WINDOW_PLACEHOLDER = re.compile(r"\$\{window\.([A-Za-z_][A-Za-z0-9_]{0,63})\}")
_ALLOWED_MODES = frozenset({"scheduled", "event_lane", "independent", "planned"})


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


def _effective_contract_value(
    registry: Mapping[str, Any], dataset: Mapping[str, Any], key: str
) -> object:
    if key in dataset:
        return dataset[key]
    profile_name = dataset.get("schema_profile")
    profiles = registry.get("schema_profiles", {})
    if isinstance(profile_name, str) and isinstance(profiles, dict):
        profile = profiles.get(profile_name)
        if isinstance(profile, dict):
            return profile.get(key)
    return None


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


def _convert_params(raw: object) -> tuple[dict[str, str], list[str]]:
    if raw is None:
        return {}, []
    if not isinstance(raw, dict):
        return {}, ["params must be a mapping"]
    converted: dict[str, str] = {}
    errors: list[str] = []
    for raw_key in sorted(raw, key=str):
        value = raw[raw_key]
        if not isinstance(raw_key, str) or _SAFE_IDENTIFIER.fullmatch(raw_key) is None:
            errors.append(f"invalid parameter name: {raw_key!r}")
            continue
        if not isinstance(value, str):
            errors.append(f"{raw_key} must be a string")
            continue
        legacy = _LEGACY_PLACEHOLDER.fullmatch(value)
        window = _WINDOW_PLACEHOLDER.fullmatch(value)
        if legacy is not None:
            converted[raw_key] = f"${{window.{legacy.group(1)}}}"
        elif window is not None:
            converted[raw_key] = value
        elif "{" in value or "}" in value or "${" in value:
            errors.append(f"{raw_key} has non-canonical placeholder {value!r}")
        else:
            converted[raw_key] = value
    return converted, errors


def _legacy_fields_hint_count(raw: object) -> int:
    """Count the old projection hint without making it an ingest contract."""

    if not isinstance(raw, str):
        return 0
    return len([field for field in raw.split(",") if field.strip()])


def _append_reason(
    reasons: list[dict[str, object]], code: str, details: Sequence[str]
) -> None:
    reasons.append({"code": code, "details": list(details)})


def _pause_tushare_binding(dataset: dict[str, Any]) -> None:
    bindings = dataset.get("provider_bindings", [])
    if not isinstance(bindings, list):
        return
    for binding in bindings:
        if isinstance(binding, dict) and binding.get("provider") == PROVIDER:
            binding["activation_state"] = "paused"


def _generic_budgets(config_item: Mapping[str, Any]) -> dict[str, int]:
    explicit_rows = config_item.get("row_limit_guard")
    max_rows = (
        explicit_rows
        if isinstance(explicit_rows, int)
        and not isinstance(explicit_rows, bool)
        and explicit_rows > 0
        else DEFAULT_MAX_ROWS_PER_ATTEMPT
    )
    return {
        "max_rows_per_attempt": max_rows,
        "max_payload_bytes_per_row": DEFAULT_MAX_PAYLOAD_BYTES_PER_ROW,
        "max_batch_bytes": DEFAULT_MAX_BATCH_BYTES,
        "max_nesting_depth": DEFAULT_MAX_NESTING_DEPTH,
    }


def compile_provider_native_registry(
    registry_document: Mapping[str, Any],
    capability_plan: Mapping[str, Any],
    collector_config: Mapping[str, Any],
    *,
    source_sha256: Mapping[str, str] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return a deterministic candidate registry and fail-closed report."""

    source_registry = _mapping(deepcopy(registry_document), "registry")
    candidate = deepcopy(source_registry)
    datasets = _sequence(candidate.get("datasets"), "registry.datasets")
    plan_index, global_conflicts = _plan_index(capability_plan)
    collector_index, collector_conflicts = _collector_index(collector_config)
    global_conflicts.extend(collector_conflicts)

    registry_api_names: set[str] = set()
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
        if not plan_rows:
            _append_reason(reasons, "missing_capability_plan", [])
        elif len(plan_rows) > 1:
            _append_reason(
                reasons, "duplicate_capability_plan", [f"count={len(plan_rows)}"]
            )
        if not config_rows:
            _append_reason(reasons, "missing_collector_config", [])
        elif len(config_rows) > 1:
            _append_reason(
                reasons, "duplicate_collector_config", [f"count={len(config_rows)}"]
            )

        plan_row = plan_rows[0] if len(plan_rows) == 1 else None
        config_row = config_rows[0] if len(config_rows) == 1 else None
        cadence = None
        mode = None
        if plan_row is not None:
            cadence = _non_empty_text(plan_row.get("effective_cadence"))
            mode = _non_empty_text(plan_row.get("mode"))
            if cadence is None:
                _append_reason(reasons, "missing_plan_cadence", [])
            if mode not in _ALLOWED_MODES:
                _append_reason(
                    reasons,
                    "invalid_plan_mode",
                    [] if mode is None else [mode],
                )
        if plan_row is not None and config_row is not None:
            plan_tier = _non_empty_text(plan_row.get("tier"))
            config_tier = _non_empty_text(config_row.get("compiler_tier"))
            if plan_tier is not None and plan_tier != config_tier:
                _append_reason(
                    reasons,
                    "tier_conflict",
                    [f"plan={plan_tier}", f"collector={config_tier}"],
                )

        request_template: dict[str, str] = {}
        legacy_fields_hint_count = 0
        requested_fields: list[str] = []
        requested_fields_source = "upstream_all"
        if config_row is not None:
            request_template, param_errors = _convert_params(config_row.get("params"))
            if param_errors:
                _append_reason(reasons, "invalid_param_template", param_errors)
            # The legacy ``fields`` value was a typed-storage projection.  A
            # provider-native call deliberately omits it so Tushare returns its
            # complete fields/items envelope.  Keep only a diagnostic count.
            legacy_fields_hint_count = _legacy_fields_hint_count(
                config_row.get("fields")
            )

        point_in_time = _effective_contract_value(
            source_registry, raw_dataset, "point_in_time"
        )
        row_key_strategy = {
            "current_snapshot": "primary_key",
            "append_only": "payload_hash",
        }.get(point_in_time)
        if row_key_strategy is None:
            _append_reason(
                reasons,
                "unsupported_point_in_time",
                [str(point_in_time)],
            )

        if reasons:
            original_activation_state = (
                tushare_bindings[0].get("activation_state")
                if len(tushare_bindings) == 1
                else None
            )
            _pause_tushare_binding(raw_dataset)
            reason_codes = sorted({str(reason["code"]) for reason in reasons})
            unresolved.append(
                {
                    "dataset_id": dataset_id,
                    "api_name": api_name,
                    "mode": mode,
                    "cadence": cadence,
                    "original_activation_state": original_activation_state,
                    "candidate_activation_state": "paused",
                    "reason_codes": reason_codes,
                }
            )
            for reason in sorted(reasons, key=lambda item: str(item["code"])):
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
        assert plan_row is not None
        assert config_row is not None
        assert cadence is not None
        assert mode is not None
        assert row_key_strategy is not None
        binding = tushare_bindings[0]
        binding["adapter_version"] = PROVIDER_ADAPTER_VERSION
        binding["target_tables"] = [PROVIDER_NATIVE_TABLE]
        binding["request_template"] = request_template
        binding["requested_fields"] = requested_fields
        binding.update(_generic_budgets(config_row))
        raw_dataset["cadence_class"] = cadence
        raw_dataset["read_model_adapter"] = {
            "adapter_version": READ_ADAPTER_VERSION,
            "primary_table": PROVIDER_NATIVE_TABLE,
            "fixed_field_filters": [],
            "storage_kind": "provider_native_rows",
            "row_key_strategy": row_key_strategy,
        }
        resolved.append(
            {
                "dataset_id": dataset_id,
                "api_name": api_name,
                "mode": mode,
                "cadence": cadence,
                "tier": config_row.get("compiler_tier"),
                "requested_fields_source": requested_fields_source,
                "requested_fields_count": len(requested_fields),
                "legacy_fields_hint_count": legacy_fields_hint_count,
                "request_window_fields": sorted(
                    match.group(1)
                    for value in request_template.values()
                    if (match := _WINDOW_PLACEHOLDER.fullmatch(value)) is not None
                ),
            }
        )

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

    conflicts.sort(
        key=lambda item: (
            str(item.get("dataset_id") or ""),
            str(item.get("api_name") or ""),
            str(item.get("code") or ""),
            tuple(str(detail) for detail in item.get("details", [])),
        )
    )
    report: dict[str, Any] = {
        "report_version": 1,
        "compiler_contract": "provider-native-registry-compiler.v1",
        "sources": dict(sorted((source_sha256 or {}).items())),
        "budget_policy": {
            "max_rows_per_attempt_default": DEFAULT_MAX_ROWS_PER_ATTEMPT,
            "explicit_row_limit_source": "collector_config.row_limit_guard",
            "max_payload_bytes_per_row": DEFAULT_MAX_PAYLOAD_BYTES_PER_ROW,
            "max_batch_bytes": DEFAULT_MAX_BATCH_BYTES,
            "max_nesting_depth": DEFAULT_MAX_NESTING_DEPTH,
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
    input_paths = (args.registry, args.capability_plan, args.collector_config)
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
    }
    candidate, report = compile_provider_native_registry(
        _load_yaml(args.registry, "registry"),
        _load_yaml(args.capability_plan, "capability plan"),
        _load_yaml(args.collector_config, "collector config"),
        source_sha256=source_hashes,
    )
    content = render_compilation(candidate, report, kind=args.kind)
    if args.output is None:
        print(content, end="")
    else:
        _atomic_write(args.output, content)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

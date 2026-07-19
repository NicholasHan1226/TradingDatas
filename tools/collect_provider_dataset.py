#!/usr/bin/env python3
"""Plan or execute one registry-owned provider-native dataset collection.

The CLI intentionally accepts a dataset ID and request-window values only.
Provider API names, provider fields, static request parameters, budgets, and
activation state always come from the process-selected TradingDatas dataset
registry. Only trusted process configuration can select the provider-native
target artifact. Plan mode is the default and neither calls the provider nor
opens the database.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from types import MappingProxyType
from typing import Any, Mapping
import uuid


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from collectors.tushare.collector import TushareCollector  # noqa: E402
from collectors.tushare import provider_native_ingest  # noqa: E402
from dataset_registry import (  # noqa: E402
    DatasetDefinition,
    DatasetRegistry,
    ProviderBinding,
    RequestScalar,
    load_runtime_dataset_registry,
)
from storage.ingest_receipts import IngestContext, IngestResult  # noqa: E402


EXIT_SUCCESS = 0
EXIT_VALIDATION = 2
EXIT_EMPTY = 3
EXIT_FAILED = 4

_MAX_REQUEST_WINDOW_BYTES = 65_536
_VALIDATION_ERROR_CODES = frozenset(
    {"config_error", "resource_budget", "validation_failed"}
)


@dataclass(frozen=True)
class _CollectionPlan:
    dataset: DatasetDefinition
    binding: ProviderBinding
    request_window: Mapping[str, str]
    request_variant: Mapping[str, RequestScalar]
    parameter_keys: tuple[str, ...]


def _utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )


def _json_object_without_duplicate_keys(
    pairs: list[tuple[str, Any]],
) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("request-window JSON contains duplicate keys")
        value[key] = item
    return value


def _read_request_window(
    *,
    inline_json: str | None,
    json_file: Path | None,
) -> dict[str, str]:
    if (inline_json is None) == (json_file is None):
        raise ValueError("provide exactly one request-window input")
    if inline_json is not None:
        raw = inline_json.encode("utf-8")
    else:
        assert json_file is not None
        if not json_file.is_file():
            raise ValueError("request-window file must be an existing regular file")
        if json_file.stat().st_size > _MAX_REQUEST_WINDOW_BYTES:
            raise ValueError("request-window JSON exceeds the input budget")
        raw = json_file.read_bytes()
    if len(raw) > _MAX_REQUEST_WINDOW_BYTES:
        raise ValueError("request-window JSON exceeds the input budget")
    try:
        decoded = raw.decode("utf-8")
        payload = json.loads(
            decoded,
            object_pairs_hook=_json_object_without_duplicate_keys,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("request-window must be valid UTF-8 JSON") from exc
    if type(payload) is not dict:
        raise ValueError("request-window must be one JSON object")
    if any(
        type(key) is not str or type(value) is not str for key, value in payload.items()
    ):
        raise ValueError("request-window keys and values must be strings")
    return payload


def _build_plan(
    *,
    registry: DatasetRegistry,
    dataset_id: str,
    request_window: Mapping[str, str],
    attempt_id: str,
    started_at: str,
) -> _CollectionPlan:
    dataset = registry.resolve(dataset_id)
    if dataset.dataset_id != dataset_id:
        raise ValueError("collection requires a canonical dataset_id")
    binding = registry.provider_binding(dataset.dataset_id, "tushare")
    if dataset.read_model_adapter.storage_kind != "provider_native_rows":
        raise ValueError("dataset is not configured for provider-native collection")
    if binding.entitlement_state != "active" or binding.activation_state != "active":
        raise ValueError("dataset binding is not entitled and active")
    normalized_window, params = provider_native_ingest._resolved_request(  # noqa: SLF001
        binding,
        request_window,
    )
    request_variant = binding.request_variants[0]

    # Reuse the receipt boundary's public-text and timestamp validation in plan
    # mode without touching SQLite or the provider.
    IngestContext(
        attempt_id=attempt_id,
        dataset_id=dataset.dataset_id,
        provider=binding.provider,
        provider_api=binding.api_name,
        request_window=normalized_window,
        config_hash=None,
        adapter_version=binding.adapter_version,
        started_at=started_at,
        data_through=None,
    )
    return _CollectionPlan(
        dataset=dataset,
        binding=binding,
        request_window=MappingProxyType(normalized_window),
        request_variant=MappingProxyType(dict(request_variant)),
        parameter_keys=tuple(sorted(params)),
    )


def _plan_summary(plan: _CollectionPlan) -> dict[str, object]:
    return {
        "dataset_id": plan.dataset.dataset_id,
        "mode": "plan",
        "parameter_keys": list(plan.parameter_keys),
        "provider": plan.binding.provider,
        "provider_api": plan.binding.api_name,
        "request_window_keys": sorted(plan.request_window),
        "requested_field_count": len(plan.binding.requested_fields),
        "state": "planned",
        "will_call_provider": False,
        "will_write_database": False,
    }


def _result_summary(
    plan: _CollectionPlan,
    result: IngestResult,
) -> tuple[int, dict[str, object]]:
    counts = {
        "committed": result.counts.committed,
        "inserted": result.counts.inserted,
        "rejected": result.counts.rejected,
        "returned": result.counts.returned,
        "unchanged": result.counts.unchanged,
        "updated": result.counts.updated,
        "validated": result.counts.validated,
    }
    summary: dict[str, object] = {
        "counts": counts,
        "dataset_id": plan.dataset.dataset_id,
        "error_codes": list(result.errors),
        "mode": "execute",
        "provider": plan.binding.provider,
        "provider_api": plan.binding.api_name,
        "receipt_count": len(result.receipt_ids),
        "state": result.status,
    }
    if result.status == "success":
        return EXIT_SUCCESS, summary
    if result.status == "empty":
        return EXIT_EMPTY, summary
    if set(result.errors) & _VALIDATION_ERROR_CODES:
        summary["state"] = "validation"
        return EXIT_VALIDATION, summary
    return EXIT_FAILED, summary


def _render(payload: Mapping[str, object]) -> None:
    print(
        json.dumps(
            payload,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Plan or execute one registry-driven provider-native Tushare dataset"
        )
    )
    parser.add_argument("--db-path", required=True, type=Path)
    parser.add_argument("--dataset-id", required=True)
    window = parser.add_mutually_exclusive_group(required=True)
    window.add_argument(
        "--request-window-json",
        help="JSON object whose keys exactly match the registry request template",
    )
    window.add_argument(
        "--request-window-file",
        type=Path,
        help="UTF-8 JSON file containing the exact request-window object",
    )
    parser.add_argument("--attempt-id")
    parser.add_argument("--started-at")
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Call the provider and write SQLite; the default is a no-write plan",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    mode = "execute" if args.execute else "plan"
    try:
        request_window = _read_request_window(
            inline_json=args.request_window_json,
            json_file=args.request_window_file,
        )
        attempt_id = str(uuid.uuid4()) if args.attempt_id is None else args.attempt_id
        started_at = _utc_now() if args.started_at is None else args.started_at
        registry = load_runtime_dataset_registry()
        plan = _build_plan(
            registry=registry,
            dataset_id=args.dataset_id,
            request_window=request_window,
            attempt_id=attempt_id,
            started_at=started_at,
        )
    except Exception:
        _render(
            {
                "error_code": "invalid_request",
                "mode": mode,
                "state": "validation",
            }
        )
        return EXIT_VALIDATION

    if not args.execute:
        _render(_plan_summary(plan))
        return EXIT_SUCCESS

    try:
        result = provider_native_ingest.collect_provider_native_dataset(
            args.db_path,
            registry=registry,
            collector=TushareCollector(),
            dataset_id=plan.dataset.dataset_id,
            request_window=plan.request_window,
            attempt_id=attempt_id,
            started_at=started_at,
            request_variant=plan.request_variant,
        )
        exit_code, summary = _result_summary(plan, result)
    except Exception:
        exit_code = EXIT_FAILED
        summary = {
            "error_code": "collection_failed",
            "mode": "execute",
            "state": "failed",
        }
    _render(summary)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())

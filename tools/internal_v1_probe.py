#!/usr/bin/env python3
"""Fail-closed authenticated probe for the loopback SharedSignals V1 API."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sys
from typing import Any, Callable, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dataset_registry import load_dataset_registry  # noqa: E402


DEFAULT_BASE_URL = "http://127.0.0.1:18082"
DEFAULT_TIMEOUT_SECONDS = 12.0
MAX_RESPONSE_BYTES = 4_194_304
MAX_CATALOG_PAGES = 100
_DATASET_ID = re.compile(r"[A-Za-z0-9]+(?:[._-][A-Za-z0-9]+)*\Z")
_COMPACT_DATE = re.compile(r"[0-9]{8}\Z")
_EVIDENCE_ISO_TIMESTAMP = re.compile(
    r"(?P<year>[0-9]{4})-(?P<month>[0-9]{2})-(?P<day>[0-9]{2})"
    r"T(?P<hour>[01][0-9]|2[0-3]):(?P<minute>[0-5][0-9]):"
    r"(?P<second>[0-5][0-9])(?:\.(?P<fraction>[0-9]{1,6}))?"
    r"(?P<zone>Z|[+-](?:[01][0-9]|2[0-3]):[0-5][0-9])?\Z"
)
_STARTUP_STATES = frozenset({"paused", "unobserved"})
_STARTUP_POLICIES = frozenset({"strict", "bootstrap"})
_FORBIDDEN_PROBE_CREDENTIALS = frozenset(
    {
        "QUICKSYNC_API_TOKEN",
        "QUICKSYNC_API_URL",
        "QUICKSYNC_TOKEN",
        "QUICKSYNC_URL",
        "TUSHARE_API_TOKEN",
        "TUSHARE_API_URL",
        "TUSHARE_MCP_URL",
        "TUSHARE_TOKEN",
    }
)


Transport = Callable[..., dict[str, Any]]


@dataclass(frozen=True)
class ProbeResult:
    exit_code: int
    payload: Mapping[str, object]


def _validated_base_url(base_url: object) -> str:
    if type(base_url) is not str or base_url != DEFAULT_BASE_URL:
        raise ValueError(f"internal V1 base URL must be exactly {DEFAULT_BASE_URL}")
    return DEFAULT_BASE_URL


def _validated_token(token: object) -> str:
    if type(token) is not str or not token or token != token.strip():
        raise ValueError("internal V1 token is required")
    if any(ord(character) < 33 or ord(character) == 127 for character in token):
        raise ValueError("internal V1 token contains invalid characters")
    return token


def _probe_token_from_environment() -> str:
    if any(os.environ.get(name) for name in _FORBIDDEN_PROBE_CREDENTIALS):
        raise ValueError("probe credential source is not allowed")
    return _validated_token(os.environ.get("SHAREDSIGNALS_INTERNAL_V1_TOKEN", ""))


def _validated_datasets(values: object) -> tuple[str, ...]:
    if not isinstance(values, tuple) or not values:
        raise ValueError("expected dataset IDs must be one non-empty tuple")
    if len(values) != len(set(values)):
        raise ValueError("expected dataset IDs must not contain duplicates")
    for value in values:
        if type(value) is not str or _DATASET_ID.fullmatch(value) is None:
            raise ValueError("expected dataset ID is invalid")
    return tuple(sorted(values))


def expected_dataset_ids_from_registry(registry_path: Path) -> tuple[str, ...]:
    if not isinstance(registry_path, Path) or not registry_path.is_absolute():
        raise ValueError("probe registry path must be absolute")
    registry = load_dataset_registry(registry_path)
    expected = tuple(
        dataset.dataset_id
        for dataset in registry.datasets
        if dataset.read_model_adapter.storage_kind == "provider_native_rows"
        and any(
            binding.entitlement_state == "active"
            and binding.activation_state == "active"
            for binding in dataset.provider_bindings
        )
    )
    return _validated_datasets(expected)


def _urlopen_transport(
    url: str,
    *,
    method: str,
    headers: dict[str, str],
    body: dict[str, Any] | None,
    timeout: float,
) -> dict[str, Any]:
    encoded: bytes | None = None
    request_headers = dict(headers)
    if body is not None:
        encoded = json.dumps(
            body,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        request_headers["Content-Type"] = "application/json"
    request = Request(url, data=encoded, headers=request_headers, method=method)
    try:
        with urlopen(request, timeout=timeout) as response:
            if int(response.status) != 200:
                raise RuntimeError("internal V1 returned a non-200 response")
            raw = response.read(MAX_RESPONSE_BYTES + 1)
    except HTTPError as exc:
        exc.read(1024)
        raise RuntimeError("internal V1 returned an HTTP error") from None
    except (URLError, TimeoutError, OSError):
        raise RuntimeError("internal V1 transport failed") from None
    if len(raw) > MAX_RESPONSE_BYTES:
        raise RuntimeError("internal V1 response exceeds the probe budget")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise RuntimeError("internal V1 returned invalid JSON") from None
    if type(payload) is not dict:
        raise RuntimeError("internal V1 response must be one object")
    return payload


def _required_object(payload: Mapping[str, Any], key: str) -> dict[str, Any]:
    value = payload.get(key)
    if type(value) is not dict:
        raise ValueError(f"V1 response {key} must be an object")
    return value


def _required_list(payload: Mapping[str, Any], key: str) -> list[Any]:
    value = payload.get(key)
    if type(value) is not list:
        raise ValueError(f"V1 response {key} must be a list")
    return value


def _dataset_timezone(value: object) -> ZoneInfo:
    if type(value) is not str or not value:
        raise ValueError("catalog dataset timezone is invalid")
    try:
        return ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError):
        raise ValueError("catalog dataset timezone is invalid") from None


def _parse_evidence_timestamp(value: object) -> tuple[datetime, bool]:
    if type(value) is not str or not value or value != value.strip():
        raise ValueError("runtime evidence timestamp is invalid")
    match = _EVIDENCE_ISO_TIMESTAMP.fullmatch(value)
    if match is None:
        raise ValueError("runtime evidence timestamp is invalid")
    candidate = f"{value[:-1]}+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(candidate)
        aware = match.group("zone") is not None
        if aware and (parsed.tzinfo is None or parsed.utcoffset() is None):
            raise ValueError
        if not aware and parsed.tzinfo is not None:
            raise ValueError
    except (OverflowError, ValueError):
        raise ValueError("runtime evidence timestamp is invalid") from None
    return parsed, aware


def _localize_unambiguous_timestamp(
    parsed: datetime,
    dataset_timezone: ZoneInfo,
) -> datetime:
    candidates: list[datetime] = []
    try:
        for fold in (0, 1):
            candidate = parsed.replace(tzinfo=dataset_timezone, fold=fold)
            round_trip = candidate.astimezone(timezone.utc).astimezone(dataset_timezone)
            if round_trip.replace(tzinfo=None) == parsed:
                candidates.append(candidate)
        offsets = {candidate.utcoffset() for candidate in candidates}
    except (OverflowError, ValueError):
        raise ValueError("runtime evidence timestamp is invalid") from None
    if not candidates or len(offsets) != 1 or None in offsets:
        raise ValueError("runtime evidence timestamp is invalid")
    return candidates[0].replace(fold=0)


def _catalog_data_through_instant(
    value: object,
    *,
    dataset_timezone: object,
) -> datetime:
    local_timezone = _dataset_timezone(dataset_timezone)
    if type(value) is str and _COMPACT_DATE.fullmatch(value) is not None:
        try:
            parsed = datetime.strptime(value, "%Y%m%d").replace(tzinfo=local_timezone)
        except ValueError:
            raise ValueError("runtime evidence timestamp is invalid") from None
        return parsed.astimezone(timezone.utc)
    parsed, aware = _parse_evidence_timestamp(value)
    if not aware:
        parsed = _localize_unambiguous_timestamp(parsed, local_timezone)
    return parsed.astimezone(timezone.utc)


def _catalog_observed_at_instant(value: object) -> datetime:
    parsed, aware = _parse_evidence_timestamp(value)
    if not aware:
        raise ValueError("runtime evidence timestamp is invalid")
    return parsed.astimezone(timezone.utc)


def _canonical_query_instant(value: object) -> datetime:
    parsed, aware = _parse_evidence_timestamp(value)
    if not aware or type(value) is not str:
        raise ValueError("runtime evidence timestamp is invalid")
    canonical = parsed.isoformat(
        timespec="microseconds" if parsed.microsecond else "seconds"
    )
    if value != canonical:
        raise ValueError("runtime evidence timestamp is not canonical")
    return parsed.astimezone(timezone.utc)


def _same_data_through_evidence(
    catalog_value: object,
    query_value: object,
    *,
    dataset_timezone: object,
) -> bool:
    return _catalog_data_through_instant(
        catalog_value,
        dataset_timezone=dataset_timezone,
    ) == _canonical_query_instant(query_value)


def _same_observed_at_evidence(
    catalog_value: object,
    query_value: object,
) -> bool:
    return _catalog_observed_at_instant(catalog_value) == _canonical_query_instant(
        query_value
    )


def _validate_common(payload: Mapping[str, Any]) -> str:
    if payload.get("api_version") != "v1":
        raise ValueError("V1 api_version is invalid")
    catalog_version = payload.get("catalog_version")
    request_id = payload.get("request_id")
    if type(catalog_version) is not str or not catalog_version:
        raise ValueError("V1 catalog_version is invalid")
    if type(request_id) is not str or not request_id:
        raise ValueError("V1 request_id is invalid")
    return catalog_version


def _validate_catalog_runtime(row: Mapping[str, Any]) -> None:
    runtime = _required_object(row, "runtime")
    required = {
        "state",
        "degraded",
        "receipt_id",
        "data_through",
        "observed_at",
        "reasons",
    }
    if not required <= set(runtime):
        raise ValueError("catalog runtime metadata is incomplete")
    state = runtime["state"]
    if state not in {"success", "empty", "unobserved", "paused", "failed", "stale"}:
        raise ValueError("catalog runtime state is invalid")
    if type(runtime["degraded"]) is not bool:
        raise ValueError("catalog runtime state is invalid")
    if type(runtime["reasons"]) is not list or any(
        type(reason) is not str or not reason for reason in runtime["reasons"]
    ):
        raise ValueError("catalog runtime reasons are invalid")
    if state == "success" and (
        runtime["degraded"] is not False
        or runtime["reasons"]
        or any(
            type(runtime[key]) is not str or not runtime[key]
            for key in ("receipt_id", "data_through", "observed_at")
        )
    ):
        raise ValueError("catalog success evidence is incomplete")


def _catalog_rows(
    *,
    base_url: str,
    headers: dict[str, str],
    timeout: float,
    transport: Transport,
) -> tuple[str, dict[str, dict[str, Any]]]:
    cursor: str | None = None
    catalog_version: str | None = None
    by_id: dict[str, dict[str, Any]] = {}
    seen_cursors: set[str] = set()
    for _ in range(MAX_CATALOG_PAGES):
        params: dict[str, object] = {"limit": 500}
        if cursor is not None:
            params["cursor"] = cursor
        payload = transport(
            f"{base_url}/v1/catalog?{urlencode(params)}",
            method="GET",
            headers=headers,
            body=None,
            timeout=timeout,
        )
        current_version = _validate_common(payload)
        if catalog_version is None:
            catalog_version = current_version
        elif current_version != catalog_version:
            raise ValueError("catalog_version changed during probe pagination")
        for raw_row in _required_list(payload, "data"):
            if type(raw_row) is not dict:
                raise ValueError("catalog row must be an object")
            dataset_id = raw_row.get("dataset_id")
            schema_major = raw_row.get("schema_major")
            if (
                type(dataset_id) is not str
                or type(schema_major) is not int
                or schema_major <= 0
            ):
                raise ValueError("catalog identity is invalid")
            if dataset_id in by_id:
                raise ValueError("catalog contains duplicate dataset identity")
            _validate_catalog_runtime(raw_row)
            by_id[dataset_id] = raw_row
        raw_cursor = payload.get("next_cursor")
        if raw_cursor is None:
            assert catalog_version is not None
            return catalog_version, by_id
        if type(raw_cursor) is not str or not raw_cursor or raw_cursor in seen_cursors:
            raise ValueError("catalog cursor is invalid")
        seen_cursors.add(raw_cursor)
        cursor = raw_cursor
    raise ValueError("catalog pagination exceeds the probe budget")


def _query_state(
    *,
    payload: Mapping[str, Any],
    dataset_id: str,
    catalog_version: str,
    catalog_runtime: Mapping[str, Any],
    dataset_timezone: object,
    startup_policy: str,
) -> dict[str, str]:
    if _validate_common(payload) != catalog_version:
        raise ValueError("query catalog_version does not match catalog")
    if payload.get("dataset_id") != dataset_id:
        raise ValueError("query dataset identity does not match request")
    if type(payload.get("schema_version")) is not str or not payload["schema_version"]:
        raise ValueError("query schema_version is invalid")
    data = _required_list(payload, "data")
    metadata = _required_object(payload, "metadata")
    required = {
        "state",
        "runtime_state",
        "degraded",
        "freshness",
        "quality",
        "lineage",
        "receipt_id",
        "data_through",
        "observed_at",
        "requested_as_of",
        "resolved_as_of",
        "reasons",
    }
    if not required <= set(metadata):
        raise ValueError("query metadata is incomplete")
    freshness = _required_object(metadata, "freshness")
    quality = _required_object(metadata, "quality")
    lineage = _required_object(metadata, "lineage")
    if not {"state", "stale", "sla_seconds"} <= set(freshness):
        raise ValueError("query freshness metadata is incomplete")
    if not {"state", "valid", "evidence"} <= set(quality):
        raise ValueError("query quality metadata is incomplete")
    if not {
        "state",
        "complete",
        "provider_neutral",
        "authority",
        "dataset_id",
        "providers",
        "receipt_watermark",
    } <= set(lineage):
        raise ValueError("query lineage metadata is incomplete")
    runtime_state = metadata["runtime_state"]
    degraded = metadata["degraded"]
    if type(runtime_state) is not str or type(degraded) is not bool:
        raise ValueError("query runtime state is invalid")
    if (
        catalog_runtime.get("state") != runtime_state
        or catalog_runtime.get("degraded") is not degraded
    ):
        raise ValueError("catalog and query runtime evidence disagree")
    if type(metadata["reasons"]) is not list or any(
        type(reason) is not str or not reason for reason in metadata["reasons"]
    ):
        raise ValueError("query reasons are invalid")
    if metadata["reasons"] != sorted(set(metadata["reasons"])):
        raise ValueError("query reasons are not canonical")
    if (
        type(freshness["state"]) is not str
        or type(freshness["stale"]) is not bool
        or type(freshness["sla_seconds"]) is not int
        or freshness["sla_seconds"] <= 0
        or type(quality["state"]) is not str
        or type(quality["valid"]) is not bool
        or type(lineage["state"]) is not str
        or type(lineage["complete"]) is not bool
        or type(lineage["provider_neutral"]) is not bool
        or type(lineage["authority"]) is not str
        or not lineage["authority"]
        or type(lineage["dataset_id"]) is not str
    ):
        raise ValueError("query nested metadata is invalid")
    if type(quality["evidence"]) is not list or any(
        type(reason) is not str or not reason for reason in quality["evidence"]
    ):
        raise ValueError("query quality evidence is invalid")
    if quality["evidence"] != sorted(set(quality["evidence"])):
        raise ValueError("query quality evidence is not canonical")
    providers = lineage["providers"]
    if (
        type(providers) is not list
        or any(type(provider) is not str or not provider for provider in providers)
        or providers != sorted(set(providers))
    ):
        raise ValueError("query lineage providers are invalid")
    if runtime_state in _STARTUP_STATES and degraded and startup_policy == "bootstrap":
        if any(
            metadata[key] is not None
            for key in ("receipt_id", "data_through", "observed_at")
        ):
            raise ValueError("startup state must not fabricate receipt evidence")
        return {"dataset_id": dataset_id, "state": runtime_state, "status": "starting"}
    healthy = (
        runtime_state == "success"
        and bool(data)
        and metadata["state"] == "ready"
        and degraded is False
        and freshness.get("state") == "fresh"
        and freshness.get("stale") is False
        and quality.get("state") == "valid"
        and quality.get("valid") is True
        and lineage.get("state") == "complete"
        and lineage.get("complete") is True
        and lineage.get("provider_neutral") is True
        and lineage.get("authority") == "sqlite_ingest_receipts"
        and lineage.get("dataset_id") == dataset_id
        and type(lineage.get("providers")) is list
        and bool(lineage["providers"])
        and type(lineage.get("receipt_watermark")) is str
        and bool(lineage["receipt_watermark"])
        and all(
            type(metadata[key]) is str and bool(metadata[key])
            for key in ("receipt_id", "data_through", "observed_at")
        )
        and type(metadata.get("reasons")) is list
        and not metadata["reasons"]
        and catalog_runtime.get("receipt_id") == metadata.get("receipt_id")
        and _same_data_through_evidence(
            catalog_runtime.get("data_through"),
            metadata.get("data_through"),
            dataset_timezone=dataset_timezone,
        )
        and _same_observed_at_evidence(
            catalog_runtime.get("observed_at"),
            metadata.get("observed_at"),
        )
    )
    return {
        "dataset_id": dataset_id,
        "state": runtime_state,
        "status": "healthy" if healthy else "failed",
    }


def probe_internal_v1(
    *,
    base_url: str,
    token: str,
    expected_dataset_ids: tuple[str, ...],
    startup_policy: str,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    transport: Transport = _urlopen_transport,
) -> ProbeResult:
    origin = _validated_base_url(base_url)
    credential = _validated_token(token)
    expected = _validated_datasets(expected_dataset_ids)
    if startup_policy not in _STARTUP_POLICIES:
        raise ValueError("startup policy must be strict or bootstrap")
    if (
        isinstance(timeout, bool)
        or not isinstance(timeout, (int, float))
        or timeout <= 0
    ):
        raise ValueError("probe timeout must be positive")
    headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {credential}",
        "User-Agent": "SharedSignals-Internal-V1-Probe/1.0",
    }
    try:
        catalog_version, catalog = _catalog_rows(
            base_url=origin,
            headers=headers,
            timeout=float(timeout),
            transport=transport,
        )
        missing = sorted(set(expected) - set(catalog))
        unexpected = sorted(set(catalog) - set(expected))
        if missing or unexpected:
            return ProbeResult(
                1,
                {
                    "datasets": sorted(
                        [
                            {
                                "dataset_id": item,
                                "state": "missing",
                                "status": "failed",
                            }
                            for item in missing
                        ]
                        + [
                            {
                                "dataset_id": item,
                                "state": "unexpected",
                                "status": "failed",
                            }
                            for item in unexpected
                        ],
                        key=lambda item: item["dataset_id"],
                    ),
                    "status": "failed",
                },
            )
        results: list[dict[str, str]] = []
        for dataset_id in expected:
            row = catalog[dataset_id]
            query = {
                "as_of": None,
                "cursor": None,
                "dataset_id": dataset_id,
                "fields": [],
                "filters": {},
                "limit": 1,
                "schema_major": row["schema_major"],
            }
            payload = transport(
                f"{origin}/v1/query",
                method="POST",
                headers=headers,
                body=query,
                timeout=float(timeout),
            )
            results.append(
                _query_state(
                    payload=payload,
                    dataset_id=dataset_id,
                    catalog_version=catalog_version,
                    catalog_runtime=_required_object(row, "runtime"),
                    dataset_timezone=row.get("timezone"),
                    startup_policy=startup_policy,
                )
            )
    except (RuntimeError, ValueError):
        return ProbeResult(1, {"datasets": [], "status": "failed"})
    if any(item["status"] == "failed" for item in results):
        return ProbeResult(1, {"datasets": results, "status": "failed"})
    if any(item["status"] == "starting" for item in results):
        return ProbeResult(2, {"datasets": results, "status": "starting"})
    return ProbeResult(0, {"datasets": results, "status": "healthy"})


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-url",
        default=os.environ.get("SHAREDSIGNALS_INTERNAL_V1_BASE_URL", DEFAULT_BASE_URL),
    )
    parser.add_argument("--registry", required=True, type=Path)
    parser.add_argument(
        "--startup-policy",
        choices=sorted(_STARTUP_POLICIES),
        default=os.environ.get("SHAREDSIGNALS_INTERNAL_V1_STARTUP_POLICY", "strict"),
    )
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        origin = _validated_base_url(args.base_url)
        result = probe_internal_v1(
            base_url=origin,
            token=_probe_token_from_environment(),
            expected_dataset_ids=expected_dataset_ids_from_registry(args.registry),
            startup_policy=args.startup_policy,
            timeout=args.timeout,
            transport=_urlopen_transport,
        )
    except Exception:
        result = ProbeResult(1, {"datasets": [], "status": "failed"})
    print(
        json.dumps(
            result.payload,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    )
    return result.exit_code


if __name__ == "__main__":
    raise SystemExit(main())

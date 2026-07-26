#!/usr/bin/env python3
"""Generate bounded, credential-free HTTPS interface evidence for QuickSync.

The request plan is a temporary derived artifact produced by the separately
reviewed request-observation compiler.  This tool validates and executes that
plan; it never invents interface parameters and never acts as runtime
authority.  Without ``--execute`` it performs validation only and makes no
provider call.
"""

from __future__ import annotations

import argparse
from collections import Counter
from collections.abc import Callable, Iterator, Mapping
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile
import threading
import time
from types import MappingProxyType

import yaml


ENTRY_ROOT = Path(__file__).parents[1]
ROOT = ENTRY_ROOT
IMPORT_ROOT = ENTRY_ROOT.resolve()
if str(IMPORT_ROOT) not in sys.path:
    sys.path.insert(0, str(IMPORT_ROOT))

from collectors.tushare.tushare_common import (  # noqa: E402
    ProviderCallOutcome,
    get_tushare_config,
    tushare_rows_outcome,
)


IMMUTABLE_RELEASES_ROOT = Path("/opt/investment/releases/tradingdatas")
IMMUTABLE_RELEASE_OWNER_UID = 0
REQUEST_OBSERVATIONS_PATH = ROOT / "config" / "tushare_request_observations.v1.yaml"
TRANSPORT_OBSERVATIONS_PATH = (
    ROOT / "config" / "quicksync_interface_observations.v1.yaml"
)
OFFICIAL_CONTRACTS_PATH = ROOT / "config" / "tushare_document_contracts.v1.yaml"
PLAN_SCHEMA_VERSION = "tradingdatas.quicksync.https_probe_plan.v1"
EVIDENCE_SCHEMA_VERSION = "tradingdatas.quicksync.https_probe_evidence.v1"
RATE_BUDGET_SCHEMA_VERSION = "tradingdatas.quicksync.request_start_budget.v1"
DEFAULT_LOCK_PATH = Path(
    "/opt/investment-data/tradingdatas/evidence/.quicksync-interface-probe.lock"
)
MAX_INTERFACE_COUNT = 512
MAX_CONCURRENCY = 4
MAX_REQUESTS_PER_WINDOW = 200
REQUEST_WINDOW_SECONDS = 60
MAX_RESPONSE_BYTES_PER_CALL = 2 * 1024 * 1024
MAX_RESPONSE_BYTES_PER_RUN = 32 * 1024 * 1024
MAX_PLAN_BYTES = 4 * 1024 * 1024
MAX_EVIDENCE_BYTES = 4 * 1024 * 1024
MAX_RATE_BUDGET_BYTES = 64 * 1024

_HASH = re.compile(r"^[0-9a-f]{64}$")
_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_API_NAME = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_FIELD_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
_PARAMETER_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
_DATASET_ID = re.compile(r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+){1,15}$")
_PUBLIC_EVIDENCE_TEXT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:+/\-TZ]{0,255}$")
_SEMANTIC_VERSION = re.compile(r"^[1-9][0-9]*\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)$")
_CREDENTIAL_TEXT = re.compile(
    r"(?:access[_-]?token|refresh[_-]?token|auth[_-]?token|bearer|api[_-]?key|"
    r"password|passwd|credential|client[_-]?secret|secret|cookie)",
    re.IGNORECASE,
)
_CREDENTIAL_PARAMETER = re.compile(
    r"(?:^|_)(?:access_?token|refresh_?token|auth_?token|token|api_?key|"
    r"password|passwd|credential|client_?secret|secret|cookie)(?:$|_)",
    re.IGNORECASE,
)
_ALLOWED_SCOPE_LABELS = frozenset({"all", "gaps"})
_ALLOWED_SCOPES = _ALLOWED_SCOPE_LABELS | frozenset({"executable"})
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
_CREDENTIAL_REJECTED_MESSAGES = (
    re.compile(r"authentication\s+(?:failed|rejected)[.!]?"),
    re.compile(r"(?:身份|认证)验证?(?:失败|被拒绝)[。.!]?"),
)
_PERMISSION_DENIED_MESSAGES = (
    re.compile(r"(?:permission|access)\s+denied[.!]?"),
    re.compile(r"(?:not\s+authori[sz]ed|unauthorized|forbidden)[.!]?"),
    re.compile(r"(?:您的|账户)?权限不足[。.!]?"),
    re.compile(r"(?:抱歉[，,]\s*)?(?:您|你|用户|账户)没有访问该接口的权限[。.!]?"),
    re.compile(r"(?:该|此)?接口权限(?:不足|被拒绝|未开通)[。.!]?"),
)
_UNSUPPORTED_MESSAGES = (
    re.compile(r"(?:api|endpoint|interface)\s+is\s+unsupported[.!]?"),
    re.compile(r"unsupported\s+(?:api|endpoint|interface)[.!]?"),
    re.compile(r"(?:api|接口|端点)(?:不受支持|不支持)[。.!]?"),
)
_NOT_MAPPED_MESSAGES = (
    re.compile(r"(?:api|endpoint|interface)\s+is\s+not\s+mapped[.!]?"),
    re.compile(r"no\s+mapping\s+(?:exists\s+)?for\s+(?:api|endpoint|interface)[.!]?"),
    re.compile(r"(?:api|接口|端点)(?:未映射|未注册|未实现)[。.!]?"),
)
_PARAMETER_ERROR_MESSAGES = (
    re.compile(r"(?:invalid|missing)\s+(?:request\s+)?parameters?[.!]?"),
    re.compile(r"parameter\s+error[.!]?"),
    re.compile(r"required\s+parameter\s+is\s+missing[.!]?"),
    re.compile(r"(?:请求)?参数(?:错误|无效|缺失|不正确)[。.!]?"),
)
_PROVIDER_FAILURE_MESSAGES = (
    ("credential_rejected", _CREDENTIAL_REJECTED_MESSAGES),
    ("permission_denied", _PERMISSION_DENIED_MESSAGES),
    ("unsupported", _UNSUPPORTED_MESSAGES),
    ("not_mapped", _NOT_MAPPED_MESSAGES),
    ("parameter_error", _PARAMETER_ERROR_MESSAGES),
)
_PROVIDER_FAILURE_CLASSES = frozenset(
    {
        "permission_denied",
        "credential_rejected",
        "unsupported",
        "not_mapped",
        "parameter_error",
        "provider_failed_unclassified",
    }
)
_RESULT_STATES = _PROVIDER_FAILURE_CLASSES | {
    "success",
    "valid_empty",
    "field_contract_mismatch",
}
_RESULT_PROVIDER_CLASSES = _PROVIDER_FAILURE_CLASSES | {
    "ok",
    "field_contract_mismatch",
}


class ProbeValidationError(RuntimeError):
    """The frozen probe plan or local evidence target is not trustworthy."""


class ProbeExecutionError(RuntimeError):
    """The bounded probe could not finish without weakening a safety gate."""


class ProbeBusyError(ProbeExecutionError):
    """Another probe process already owns the account-wide execution lock."""


class ProbeRateBudgetError(ProbeExecutionError):
    """The account-wide request-start budget cannot authorize the probe."""


@dataclass(frozen=True)
class ProbeLock:
    path: Path
    descriptor: int
    created: bool


@dataclass(frozen=True)
class RequestStartReservation:
    reserved_at_epoch: float
    reserved: int
    active_before: int
    active_after: int


@dataclass(frozen=True)
class ProbeEntry:
    api_name: str
    scope_labels: tuple[str, ...]
    probe_state: str
    probe_block_reasons: tuple[str, ...]
    ingest_contract_state: str
    ingest_contract_block_reasons: tuple[str, ...]
    params: Mapping[str, object]
    fields: tuple[str, ...]


@dataclass(frozen=True)
class ProbePlan:
    sha256: str
    expected_commit: str
    official_contract_sha256: str
    transport_observations_sha256: str
    request_observations_sha256: str
    api_names_sha256: str
    scheduled_partition: str
    run_clock: str
    seed_authorities: tuple[Mapping[str, str], ...]
    counts: Mapping[str, int]
    entries: tuple[ProbeEntry, ...]

    def planned(self, scope: str) -> tuple[ProbeEntry, ...]:
        if scope not in _ALLOWED_SCOPES:
            raise ProbeValidationError("probe scope is invalid")
        if scope == "executable":
            return tuple(
                entry for entry in self.entries if entry.probe_state == "executable"
            )
        return tuple(entry for entry in self.entries if scope in entry.scope_labels)

    def select(self, scope: str) -> tuple[ProbeEntry, ...]:
        return tuple(
            entry for entry in self.planned(scope) if entry.probe_state == "executable"
        )

    def blocked(self, scope: str) -> tuple[ProbeEntry, ...]:
        return tuple(
            entry for entry in self.planned(scope) if entry.probe_state == "blocked"
        )


def _mapping(value: object, label: str) -> dict[str, object]:
    if type(value) is not dict:
        raise ProbeValidationError(f"{label} must be a mapping")
    return value


def _exact_keys(
    value: Mapping[str, object], expected: frozenset[str], label: str
) -> None:
    if frozenset(value) != expected:
        raise ProbeValidationError(f"{label} keys are invalid")


def _sha256(value: object, label: str) -> str:
    if type(value) is not str or _HASH.fullmatch(value) is None:
        raise ProbeValidationError(f"{label} must be SHA-256")
    return value


def _commit(value: object) -> str:
    if type(value) is not str or _COMMIT.fullmatch(value) is None:
        raise ProbeValidationError("expected_commit must be a full commit SHA")
    return value


def _scheduled_partition(value: object) -> str:
    if type(value) is not str or re.fullmatch(r"[0-9]{8}", value) is None:
        raise ProbeValidationError("scheduled_partition must be YYYYMMDD")
    try:
        parsed = datetime.strptime(value, "%Y%m%d")
    except ValueError:
        raise ProbeValidationError("scheduled_partition must be YYYYMMDD") from None
    if parsed.strftime("%Y%m%d") != value:
        raise ProbeValidationError("scheduled_partition must be YYYYMMDD")
    return value


def _run_clock(value: object) -> str:
    if type(value) is not str or not value or len(value.encode("utf-8")) > 64:
        raise ProbeValidationError("run_clock must be a timezone-aware ISO timestamp")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        raise ProbeValidationError(
            "run_clock must be a timezone-aware ISO timestamp"
        ) from None
    if (
        parsed.tzinfo is None
        or parsed.utcoffset() is None
        or parsed.isoformat() != value
    ):
        raise ProbeValidationError("run_clock must be a timezone-aware ISO timestamp")
    return value


def _seed_authorities(value: object) -> tuple[Mapping[str, str], ...]:
    if type(value) is not list or len(value) > MAX_INTERFACE_COUNT:
        raise ProbeValidationError("seed_authorities must be a bounded list")
    authorities: list[Mapping[str, str]] = []
    identities: list[tuple[str, str]] = []
    expected_keys = frozenset(
        {"dataset_id", "field", "receipt_id", "data_through", "schema_version"}
    )
    for index, raw_value in enumerate(value):
        raw = _mapping(raw_value, f"seed_authorities[{index}]")
        _exact_keys(raw, expected_keys, f"seed_authorities[{index}]")
        if any(type(item) is not str for item in raw.values()):
            raise ProbeValidationError(f"seed_authorities[{index}] is invalid")
        dataset_id = str(raw["dataset_id"])
        field = str(raw["field"])
        receipt_id = str(raw["receipt_id"])
        data_through = str(raw["data_through"])
        schema_version = str(raw["schema_version"])
        if _DATASET_ID.fullmatch(dataset_id) is None:
            raise ProbeValidationError(
                f"seed_authorities[{index}].dataset_id is invalid"
            )
        if _FIELD_NAME.fullmatch(field) is None:
            raise ProbeValidationError(f"seed_authorities[{index}].field is invalid")
        if (
            _PUBLIC_EVIDENCE_TEXT.fullmatch(receipt_id) is None
            or _PUBLIC_EVIDENCE_TEXT.fullmatch(data_through) is None
            or _CREDENTIAL_TEXT.search(receipt_id) is not None
            or _CREDENTIAL_TEXT.search(data_through) is not None
        ):
            raise ProbeValidationError(
                f"seed_authorities[{index}] contains unsafe evidence text"
            )
        if _SEMANTIC_VERSION.fullmatch(schema_version) is None:
            raise ProbeValidationError(
                f"seed_authorities[{index}].schema_version is invalid"
            )
        identity = (dataset_id, field)
        identities.append(identity)
        authorities.append(
            MappingProxyType(
                {
                    "dataset_id": dataset_id,
                    "field": field,
                    "receipt_id": receipt_id,
                    "data_through": data_through,
                    "schema_version": schema_version,
                }
            )
        )
    if identities != sorted(identities) or len(set(identities)) != len(identities):
        raise ProbeValidationError("seed_authorities must be unique and sorted")
    return tuple(authorities)


def _safe_parameter_value(value: object, *, depth: int = 0) -> object:
    if depth > 4:
        raise ProbeValidationError("request parameter nesting is too deep")
    if value is None or type(value) in {bool, int}:
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise ProbeValidationError("request parameter number is not finite")
        return value
    if type(value) is str:
        if len(value.encode("utf-8")) > 4096 or any(
            ord(character) < 32 or ord(character) == 127 for character in value
        ):
            raise ProbeValidationError("request parameter text is invalid")
        return value
    if type(value) is list:
        if len(value) > 1024:
            raise ProbeValidationError("request parameter list is too large")
        return tuple(_safe_parameter_value(item, depth=depth + 1) for item in value)
    raise ProbeValidationError("request parameter value is unsupported")


def _state_and_reasons(
    raw: Mapping[str, object],
    *,
    index: int,
    state_field: str,
    reasons_field: str,
    allowed_states: frozenset[str],
    allowed_reasons: frozenset[str],
    ready_state: str,
) -> tuple[str, tuple[str, ...]]:
    state = raw[state_field]
    raw_reasons = raw[reasons_field]
    if type(state) is not str or state not in allowed_states:
        raise ProbeValidationError(f"entries[{index}].{state_field} is invalid")
    if type(raw_reasons) is not list or any(
        type(reason) is not str for reason in raw_reasons
    ):
        raise ProbeValidationError(f"entries[{index}].{reasons_field} is invalid")
    reasons = tuple(raw_reasons)
    if (
        reasons != tuple(sorted(reasons))
        or len(set(reasons)) != len(reasons)
        or not set(reasons).issubset(allowed_reasons)
        or (state == ready_state and bool(reasons))
        or (state != ready_state and not reasons)
    ):
        raise ProbeValidationError(f"entries[{index}].{reasons_field} is invalid")
    return state, reasons


def _entry(value: object, index: int) -> ProbeEntry:
    raw = _mapping(value, f"entries[{index}]")
    _exact_keys(
        raw,
        frozenset(
            {
                "api_name",
                "scope_labels",
                "probe_state",
                "probe_block_reasons",
                "ingest_contract_state",
                "ingest_contract_block_reasons",
                "params",
                "fields",
            }
        ),
        f"entries[{index}]",
    )
    api_name = raw["api_name"]
    if type(api_name) is not str or _API_NAME.fullmatch(api_name) is None:
        raise ProbeValidationError(f"entries[{index}].api_name is invalid")

    raw_labels = raw["scope_labels"]
    if type(raw_labels) is not list or not raw_labels:
        raise ProbeValidationError(f"entries[{index}].scope_labels is invalid")
    if any(type(label) is not str for label in raw_labels):
        raise ProbeValidationError(f"entries[{index}].scope_labels is invalid")
    labels = tuple(raw_labels)
    if (
        len(set(labels)) != len(labels)
        or not set(labels).issubset(_ALLOWED_SCOPE_LABELS)
        or "all" not in labels
        or labels != tuple(sorted(labels))
    ):
        raise ProbeValidationError(f"entries[{index}].scope_labels is invalid")

    probe_state, probe_block_reasons = _state_and_reasons(
        raw,
        index=index,
        state_field="probe_state",
        reasons_field="probe_block_reasons",
        allowed_states=_PROBE_STATES,
        allowed_reasons=_PROBE_BLOCK_REASONS,
        ready_state="executable",
    )
    ingest_contract_state, ingest_contract_block_reasons = _state_and_reasons(
        raw,
        index=index,
        state_field="ingest_contract_state",
        reasons_field="ingest_contract_block_reasons",
        allowed_states=_INGEST_CONTRACT_STATES,
        allowed_reasons=_INGEST_CONTRACT_BLOCK_REASONS,
        ready_state="ready",
    )

    raw_params = _mapping(raw["params"], f"entries[{index}].params")
    if probe_state == "blocked" and raw_params:
        raise ProbeValidationError(f"entries[{index}].blocked params must be empty")
    if len(raw_params) > 128:
        raise ProbeValidationError(f"entries[{index}].params is too large")
    params: dict[str, object] = {}
    for key, item in raw_params.items():
        if (
            type(key) is not str
            or _PARAMETER_NAME.fullmatch(key) is None
            or _CREDENTIAL_PARAMETER.search(key) is not None
        ):
            raise ProbeValidationError(f"entries[{index}].params key is invalid")
        params[key] = _safe_parameter_value(item)

    raw_fields = raw["fields"]
    if type(raw_fields) is not list or not 1 <= len(raw_fields) <= 512:
        raise ProbeValidationError(f"entries[{index}].fields is invalid")
    if any(
        type(field) is not str or _FIELD_NAME.fullmatch(field) is None
        for field in raw_fields
    ):
        raise ProbeValidationError(f"entries[{index}].fields is invalid")
    fields = tuple(raw_fields)
    if len(set(fields)) != len(fields):
        raise ProbeValidationError(f"entries[{index}].fields contains duplicates")

    return ProbeEntry(
        api_name=api_name,
        scope_labels=labels,
        probe_state=probe_state,
        probe_block_reasons=probe_block_reasons,
        ingest_contract_state=ingest_contract_state,
        ingest_contract_block_reasons=ingest_contract_block_reasons,
        params=MappingProxyType(params),
        fields=fields,
    )


def _absolute_canonical_path(path: Path, label: str) -> Path:
    raw = os.fspath(path)
    if not os.path.isabs(raw) or os.path.normpath(raw) != raw or raw.endswith(os.sep):
        raise ProbeValidationError(f"{label} must be an absolute canonical path")
    return Path(raw)


def _assert_no_symlink_components(path: Path, label: str) -> None:
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current = current / part
        try:
            metadata = os.lstat(current)
        except OSError:
            raise ProbeValidationError(f"{label} is unavailable") from None
        if stat.S_ISLNK(metadata.st_mode):
            raise ProbeValidationError(f"{label} may not traverse a symlink")


def _read_private_plan(path: Path) -> bytes:
    plan_path = _absolute_canonical_path(path, "request plan")
    _assert_no_symlink_components(plan_path.parent, "request plan parent")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(plan_path, flags)
    except OSError:
        raise ProbeValidationError("request plan is unavailable") from None
    try:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_uid != os.geteuid()
            or before.st_nlink != 1
            or stat.S_IMODE(before.st_mode) != 0o600
            or before.st_size <= 0
            or before.st_size > MAX_PLAN_BYTES
        ):
            raise ProbeValidationError("request plan ownership or mode is invalid")
        chunks: list[bytes] = []
        remaining = MAX_PLAN_BYTES + 1
        while remaining:
            chunk = os.read(descriptor, min(remaining, 64 * 1024))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        payload = b"".join(chunks)
        after = os.fstat(descriptor)
        if (
            len(payload) != before.st_size
            or len(payload) > MAX_PLAN_BYTES
            or (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
            != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
        ):
            raise ProbeValidationError("request plan changed while being read")
    finally:
        os.close(descriptor)
    return payload


def load_probe_plan(path: Path) -> ProbePlan:
    payload = _read_private_plan(path)
    try:
        document = yaml.safe_load(payload.decode("utf-8"))
    except (UnicodeDecodeError, yaml.YAMLError):
        raise ProbeValidationError("request plan is not valid UTF-8 YAML") from None
    root = _mapping(document, "request plan")
    _exact_keys(
        root,
        frozenset(
            {"schema_version", "production_ready", "provenance", "counts", "entries"}
        ),
        "request plan",
    )
    if root["schema_version"] != PLAN_SCHEMA_VERSION:
        raise ProbeValidationError("request plan schema_version is unsupported")
    if root["production_ready"] is not False:
        raise ProbeValidationError("request plan production_ready must remain false")

    provenance = _mapping(root["provenance"], "request plan provenance")
    _exact_keys(
        provenance,
        frozenset(
            {
                "expected_commit",
                "official_contract_sha256",
                "transport_observations_sha256",
                "request_observations_sha256",
                "api_names_sha256",
                "scheduled_partition",
                "run_clock",
                "seed_authorities",
            }
        ),
        "request plan provenance",
    )
    expected_commit = _commit(provenance["expected_commit"])
    official_sha = _sha256(
        provenance["official_contract_sha256"], "official_contract_sha256"
    )
    transport_sha = _sha256(
        provenance["transport_observations_sha256"],
        "transport_observations_sha256",
    )
    request_sha = _sha256(
        provenance["request_observations_sha256"],
        "request_observations_sha256",
    )
    api_names_sha = _sha256(provenance["api_names_sha256"], "api_names_sha256")
    scheduled_partition = _scheduled_partition(provenance["scheduled_partition"])
    run_clock = _run_clock(provenance["run_clock"])
    seed_authorities = _seed_authorities(provenance["seed_authorities"])

    raw_entries = root["entries"]
    if (
        type(raw_entries) is not list
        or not 1 <= len(raw_entries) <= MAX_INTERFACE_COUNT
    ):
        raise ProbeValidationError("request plan interface count is invalid")
    entries = tuple(_entry(value, index) for index, value in enumerate(raw_entries))
    api_names = tuple(entry.api_name for entry in entries)
    if api_names != tuple(sorted(api_names)) or len(set(api_names)) != len(api_names):
        raise ProbeValidationError("request plan API names must be unique and sorted")
    computed_api_names_sha = hashlib.sha256(
        ("\n".join(api_names) + "\n").encode("utf-8")
    ).hexdigest()
    if computed_api_names_sha != api_names_sha:
        raise ProbeValidationError("request plan API names hash does not match")
    if not any("gaps" in entry.scope_labels for entry in entries):
        raise ProbeValidationError("request plan gaps scope may not be empty")

    raw_counts = _mapping(root["counts"], "request plan counts")
    _exact_keys(
        raw_counts,
        frozenset(
            {
                "planned",
                "executable",
                "blocked",
                "ingest_contract_ready",
                "ingest_contract_blocked",
            }
        ),
        "request plan counts",
    )
    if any(type(value) is not int or value < 0 for value in raw_counts.values()):
        raise ProbeValidationError("request plan counts are invalid")
    computed_counts = {
        "planned": len(entries),
        "executable": sum(entry.probe_state == "executable" for entry in entries),
        "blocked": sum(entry.probe_state == "blocked" for entry in entries),
        "ingest_contract_ready": sum(
            entry.ingest_contract_state == "ready" for entry in entries
        ),
        "ingest_contract_blocked": sum(
            entry.ingest_contract_state == "blocked" for entry in entries
        ),
    }
    if raw_counts != computed_counts:
        raise ProbeValidationError("request plan counts do not match entries")

    return ProbePlan(
        sha256=hashlib.sha256(payload).hexdigest(),
        expected_commit=expected_commit,
        official_contract_sha256=official_sha,
        transport_observations_sha256=transport_sha,
        request_observations_sha256=request_sha,
        api_names_sha256=api_names_sha,
        scheduled_partition=scheduled_partition,
        run_clock=run_clock,
        seed_authorities=seed_authorities,
        counts=MappingProxyType(dict(computed_counts)),
        entries=entries,
    )


def _read_authority_bytes(path: Path, label: str) -> bytes:
    authority_path = _absolute_canonical_path(path, label)
    _assert_no_symlink_components(authority_path.parent, f"{label} parent")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(authority_path, flags)
    except OSError:
        raise ProbeValidationError(f"{label} is unavailable") from None
    try:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or before.st_size <= 0
            or before.st_size > MAX_PLAN_BYTES
        ):
            raise ProbeValidationError(f"{label} is not a regular authority file")
        chunks: list[bytes] = []
        remaining = MAX_PLAN_BYTES + 1
        while remaining:
            chunk = os.read(descriptor, min(remaining, 64 * 1024))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        payload = b"".join(chunks)
        after = os.fstat(descriptor)
        if (
            len(payload) != before.st_size
            or len(payload) > MAX_PLAN_BYTES
            or (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
            != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
        ):
            raise ProbeValidationError(f"{label} changed while being read")
    finally:
        os.close(descriptor)
    return payload


def _official_contract_api_names(payload: bytes) -> tuple[str, ...]:
    try:
        document = yaml.safe_load(payload.decode("utf-8"))
    except (UnicodeDecodeError, yaml.YAMLError):
        raise ProbeValidationError(
            "official contracts are not valid UTF-8 YAML"
        ) from None
    root = _mapping(document, "official contracts")
    raw_contracts = root.get("contracts")
    if (
        type(raw_contracts) is not list
        or not 1 <= len(raw_contracts) <= MAX_INTERFACE_COUNT
    ):
        raise ProbeValidationError("official contracts interface count is invalid")
    names: list[str] = []
    for index, value in enumerate(raw_contracts):
        contract = _mapping(value, f"official contracts[{index}]")
        api_name = contract.get("api_name")
        if type(api_name) is not str or _API_NAME.fullmatch(api_name) is None:
            raise ProbeValidationError("official contract API name is invalid")
        names.append(api_name)
    if len(set(names)) != len(names):
        raise ProbeValidationError("official contract API names must be unique")
    return tuple(sorted(names))


def validate_authority_sources(plan: ProbePlan) -> None:
    request_observations = _read_authority_bytes(
        REQUEST_OBSERVATIONS_PATH,
        "request observations",
    )
    transport_observations = _read_authority_bytes(
        TRANSPORT_OBSERVATIONS_PATH,
        "transport observations",
    )
    official_contracts = _read_authority_bytes(
        OFFICIAL_CONTRACTS_PATH,
        "official contracts",
    )
    if (
        hashlib.sha256(request_observations).hexdigest()
        != plan.request_observations_sha256
    ):
        raise ProbeValidationError("request observations SHA-256 does not match")
    if (
        hashlib.sha256(transport_observations).hexdigest()
        != plan.transport_observations_sha256
    ):
        raise ProbeValidationError("transport observations SHA-256 does not match")
    if hashlib.sha256(official_contracts).hexdigest() != plan.official_contract_sha256:
        raise ProbeValidationError("official contracts SHA-256 does not match")
    official_api_names = _official_contract_api_names(official_contracts)
    plan_api_names = tuple(entry.api_name for entry in plan.entries)
    if official_api_names != plan_api_names:
        raise ProbeValidationError("official contract API set does not match plan")
    official_api_names_sha256 = hashlib.sha256(
        ("\n".join(official_api_names) + "\n").encode("utf-8")
    ).hexdigest()
    if official_api_names_sha256 != plan.api_names_sha256:
        raise ProbeValidationError("official contract API names SHA-256 does not match")


def _current_commit() -> str:
    entry_root = _absolute_canonical_path(ENTRY_ROOT, "repository entry root")
    _assert_no_symlink_components(entry_root, "repository entry root")
    try:
        root = entry_root.resolve(strict=True)
    except OSError:
        raise ProbeValidationError("repository entry root is unavailable") from None
    if root != ROOT:
        raise ProbeValidationError("repository entry root identity is invalid")
    release_root = _absolute_canonical_path(
        IMMUTABLE_RELEASES_ROOT,
        "immutable releases root",
    )
    if root.parent == release_root:
        if _COMMIT.fullmatch(root.name) is None:
            raise ProbeValidationError("immutable release name is invalid")
        try:
            metadata = os.stat(root, follow_symlinks=False)
        except OSError:
            raise ProbeValidationError("immutable release is unavailable") from None
        if (
            not stat.S_ISDIR(metadata.st_mode)
            or metadata.st_uid != IMMUTABLE_RELEASE_OWNER_UID
            or stat.S_IMODE(metadata.st_mode) != 0o555
        ):
            raise ProbeValidationError("immutable release ownership or mode is invalid")
        try:
            os.lstat(root / ".git")
        except FileNotFoundError:
            pass
        except OSError:
            raise ProbeValidationError(
                "immutable release repository metadata is unavailable"
            ) from None
        else:
            raise ProbeValidationError(
                "immutable release may not contain repository metadata"
            )
        return root.name

    completed = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    commit = completed.stdout.strip()
    if completed.returncode != 0 or _COMMIT.fullmatch(commit) is None:
        raise ProbeValidationError("repository commit is unavailable")
    return commit


def validate_frozen_bindings(
    plan: ProbePlan,
    *,
    expected_plan_sha256: str | None = None,
) -> None:
    if _current_commit() != plan.expected_commit:
        raise ProbeValidationError("repository HEAD does not match request plan")
    validate_authority_sources(plan)
    if expected_plan_sha256 is not None:
        expected = _sha256(expected_plan_sha256, "expected plan SHA-256")
        if expected != plan.sha256:
            raise ProbeValidationError("request plan SHA-256 does not match")


def _validate_lock_binding(path: Path, descriptor: int) -> os.stat_result:
    try:
        opened = os.fstat(descriptor)
        published = os.stat(path, follow_symlinks=False)
    except OSError:
        raise ProbeValidationError("probe lock binding is unavailable") from None
    if (
        not stat.S_ISREG(opened.st_mode)
        or not stat.S_ISREG(published.st_mode)
        or opened.st_uid != os.geteuid()
        or published.st_uid != os.geteuid()
        or opened.st_nlink != 1
        or published.st_nlink != 1
        or stat.S_IMODE(opened.st_mode) != 0o600
        or stat.S_IMODE(published.st_mode) != 0o600
        or (opened.st_dev, opened.st_ino) != (published.st_dev, published.st_ino)
    ):
        raise ProbeValidationError("probe lock ownership or binding is invalid")
    return opened


def _safe_lock_descriptor(path: Path) -> ProbeLock:
    lock_path = _absolute_canonical_path(path, "probe lock")
    _assert_no_symlink_components(lock_path.parent, "probe lock parent")
    common_flags = (
        os.O_RDWR | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    )
    created = False
    try:
        descriptor = os.open(
            lock_path,
            common_flags | os.O_CREAT | os.O_EXCL,
            0o600,
        )
        created = True
    except FileExistsError:
        try:
            descriptor = os.open(lock_path, common_flags)
        except OSError:
            raise ProbeValidationError("probe lock is unavailable") from None
    except OSError:
        raise ProbeValidationError("probe lock is unavailable") from None
    try:
        _validate_lock_binding(lock_path, descriptor)
    except Exception:
        os.close(descriptor)
        raise
    return ProbeLock(path=lock_path, descriptor=descriptor, created=created)


@contextmanager
def exclusive_probe_lock(path: Path) -> Iterator[ProbeLock]:
    lock = _safe_lock_descriptor(path)
    try:
        try:
            fcntl.flock(lock.descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ProbeBusyError("another probe process is active") from exc
        _validate_lock_binding(lock.path, lock.descriptor)
        yield lock
    finally:
        try:
            fcntl.flock(lock.descriptor, fcntl.LOCK_UN)
        finally:
            os.close(lock.descriptor)


def _epoch_now() -> float:
    return time.time()


def _read_rate_budget_state(lock: ProbeLock, *, now: float) -> list[float]:
    metadata = _validate_lock_binding(lock.path, lock.descriptor)
    if lock.created and metadata.st_size == 0:
        return []
    if metadata.st_size <= 0 or metadata.st_size > MAX_RATE_BUDGET_BYTES:
        raise ProbeValidationError("probe budget state size is invalid")
    try:
        os.lseek(lock.descriptor, 0, os.SEEK_SET)
        chunks: list[bytes] = []
        remaining = MAX_RATE_BUDGET_BYTES + 1
        while remaining:
            chunk = os.read(lock.descriptor, min(remaining, 16 * 1024))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        payload = b"".join(chunks)
    except OSError:
        raise ProbeValidationError("probe budget state is unreadable") from None
    after = _validate_lock_binding(lock.path, lock.descriptor)
    if (
        len(payload) != metadata.st_size
        or len(payload) > MAX_RATE_BUDGET_BYTES
        or (metadata.st_size, metadata.st_mtime_ns)
        != (after.st_size, after.st_mtime_ns)
    ):
        raise ProbeValidationError("probe budget state changed while locked")
    try:
        document = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ProbeValidationError("probe budget state is invalid") from None
    root = _mapping(document, "probe budget state")
    _exact_keys(
        root,
        frozenset({"schema_version", "request_starts"}),
        "probe budget state",
    )
    if root["schema_version"] != RATE_BUDGET_SCHEMA_VERSION:
        raise ProbeValidationError("probe budget state schema is unsupported")
    raw_starts = root["request_starts"]
    if type(raw_starts) is not list or len(raw_starts) > MAX_REQUESTS_PER_WINDOW:
        raise ProbeValidationError("probe budget request starts are invalid")
    starts: list[float] = []
    for value in raw_starts:
        if type(value) not in {int, float}:
            raise ProbeValidationError("probe budget timestamp is invalid")
        timestamp = float(value)
        if not math.isfinite(timestamp) or timestamp < 0 or timestamp > now:
            raise ProbeValidationError("probe budget timestamp is invalid")
        starts.append(timestamp)
    if starts != sorted(starts):
        raise ProbeValidationError("probe budget timestamps are not ordered")
    return starts


def _write_rate_budget_state(lock: ProbeLock, request_starts: list[float]) -> None:
    document = {
        "schema_version": RATE_BUDGET_SCHEMA_VERSION,
        "request_starts": request_starts,
    }
    payload = (
        json.dumps(
            document,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")
    if not payload or len(payload) > MAX_RATE_BUDGET_BYTES:
        raise ProbeValidationError("probe budget state exceeds its byte budget")
    _validate_lock_binding(lock.path, lock.descriptor)
    try:
        os.lseek(lock.descriptor, 0, os.SEEK_SET)
        written = 0
        while written < len(payload):
            count = os.write(lock.descriptor, payload[written:])
            if count <= 0:
                raise OSError("short budget-state write")
            written += count
        os.ftruncate(lock.descriptor, len(payload))
        os.fsync(lock.descriptor)
    except OSError:
        raise ProbeValidationError(
            "probe budget state could not be persisted"
        ) from None
    metadata = _validate_lock_binding(lock.path, lock.descriptor)
    if metadata.st_size != len(payload):
        raise ProbeValidationError("probe budget state persistence is incomplete")
    try:
        os.lseek(lock.descriptor, 0, os.SEEK_SET)
        published = os.read(lock.descriptor, len(payload) + 1)
    except OSError:
        raise ProbeValidationError("probe budget state readback failed") from None
    if published != payload:
        raise ProbeValidationError("probe budget state readback does not match")


def _rate_budget_clock(now: float | None) -> float:
    observed_now = _epoch_now() if now is None else now
    if type(observed_now) not in {int, float}:
        raise ProbeValidationError("probe request-start clock is invalid")
    timestamp = float(observed_now)
    if not math.isfinite(timestamp) or timestamp < 0:
        raise ProbeValidationError("probe request-start clock is invalid")
    return timestamp


def _active_request_starts(lock: ProbeLock, *, now: float) -> list[float]:
    starts = _read_rate_budget_state(lock, now=now)
    cutoff = now - REQUEST_WINDOW_SECONDS
    # Starts exactly on the rolling-window boundary remain chargeable.  This
    # is intentionally conservative and prevents adjacent runs from jointly
    # exceeding the account-wide provider limit.
    return [timestamp for timestamp in starts if timestamp >= cutoff]


def check_request_start_capacity(
    lock: ProbeLock,
    request_count: int,
    *,
    now: float | None = None,
) -> int:
    if (
        type(request_count) is not int
        or not 1 <= request_count <= MAX_REQUESTS_PER_WINDOW
    ):
        raise ProbeValidationError("probe request capacity size is invalid")
    observed_at = _rate_budget_clock(now)
    active = _active_request_starts(lock, now=observed_at)
    active_before = len(active)
    if active_before + request_count > MAX_REQUESTS_PER_WINDOW:
        raise ProbeRateBudgetError("probe request-start budget is exhausted")
    if lock.created and _validate_lock_binding(lock.path, lock.descriptor).st_size == 0:
        # A capacity-only failure after this point (for example a missing
        # credential) must not leave an ambiguous zero-byte state behind.
        _write_rate_budget_state(lock, [])
    return active_before


def authorize_request_start(
    lock: ProbeLock,
    *,
    now: float | None = None,
) -> RequestStartReservation:
    authorized_at = _rate_budget_clock(now)
    active = _active_request_starts(lock, now=authorized_at)
    active_before = len(active)
    if active_before + 1 > MAX_REQUESTS_PER_WINDOW:
        raise ProbeRateBudgetError("probe request-start budget is exhausted")
    active.append(authorized_at)
    _write_rate_budget_state(lock, active)
    return RequestStartReservation(
        reserved_at_epoch=authorized_at,
        reserved=1,
        active_before=active_before,
        active_after=len(active),
    )


def _provider_class(outcome: ProviderCallOutcome) -> tuple[str, str]:
    if outcome.state in {"success", "empty"}:
        if outcome.provider_code not in {0, "0"} or outcome.error_code is not None:
            raise ProbeExecutionError("provider success envelope is inconsistent")
        return ("success" if outcome.state == "success" else "valid_empty"), "ok"
    if outcome.state != "failed":
        raise ProbeExecutionError("provider outcome state is invalid")
    if outcome.error_code == "rate_limited":
        raise ProbeExecutionError("provider rate limit was reached")
    if outcome.error_code == "resource_budget":
        raise ProbeExecutionError("provider response budget was exceeded")
    if outcome.error_code == "transport_error":
        raise ProbeExecutionError("provider transport failed")
    if type(outcome.error_message) is not str or "[REDACTED]" in outcome.error_message:
        return "provider_failed_unclassified", "provider_failed_unclassified"
    if outcome.error_code not in {"provider_error", "permission_denied"}:
        return "provider_failed_unclassified", "provider_failed_unclassified"
    normalized = " ".join(outcome.error_message.casefold().split())
    matches = [
        classification
        for classification, patterns in _PROVIDER_FAILURE_MESSAGES
        if any(pattern.fullmatch(normalized) for pattern in patterns)
    ]
    if len(matches) != 1:
        return "provider_failed_unclassified", "provider_failed_unclassified"
    classification = matches[0]
    if (
        outcome.error_code == "permission_denied"
        and classification != "permission_denied"
    ):
        return "provider_failed_unclassified", "provider_failed_unclassified"
    return classification, classification


def _call_entry(
    entry: ProbeEntry,
    *,
    token: str,
    max_response_bytes: int,
    authorize_request_start: Callable[[], RequestStartReservation],
    call: Callable[..., ProviderCallOutcome],
) -> tuple[dict[str, object], int]:
    observed: list[tuple[int, str | None]] = []

    def response_observer(size: int, digest: str | None) -> None:
        observed.append((size, digest))

    # This persisted authorization is deliberately the last stateful action
    # before the provider call.  Once issued it is never refunded, including
    # when the call raises or returns a fatal provider outcome.
    authorize_request_start()
    started = time.monotonic()
    try:
        outcome = call(
            entry.api_name,
            token,
            params=dict(entry.params),
            fields=",".join(entry.fields),
            max_response_bytes=max_response_bytes,
            response_observer=response_observer,
        )
    except Exception as exc:
        raise ProbeExecutionError("provider call raised unexpectedly") from exc
    elapsed_ms = round((time.monotonic() - started) * 1000, 3)
    if not isinstance(outcome, ProviderCallOutcome):
        raise ProbeExecutionError("provider call returned an invalid outcome")
    try:
        outcome.validate_invariants()
    except Exception as exc:
        raise ProbeExecutionError("provider outcome invariants failed") from exc
    state, provider_class = _provider_class(outcome)
    if state in {"success", "valid_empty"} and not set(entry.fields).issubset(
        outcome.response_fields
    ):
        state = "field_contract_mismatch"
        provider_class = "field_contract_mismatch"
    if state not in _RESULT_STATES or provider_class not in _RESULT_PROVIDER_CLASSES:
        raise ProbeExecutionError("provider evidence classification is invalid")

    if len(observed) != 1:
        raise ProbeExecutionError("provider response observation is incomplete")
    response_bytes, response_sha256 = observed[0]
    redacted_provider_failure = (
        response_sha256 is None
        and state in _PROVIDER_FAILURE_CLASSES
        and outcome.state == "failed"
        and not outcome.rows
        and not outcome.response_fields
    )
    if (
        type(response_bytes) is not int
        or response_bytes <= 0
        or response_bytes > max_response_bytes
        or (
            not redacted_provider_failure
            and (
                type(response_sha256) is not str
                or _HASH.fullmatch(response_sha256) is None
            )
        )
    ):
        raise ProbeExecutionError("provider response evidence is invalid")

    for field in outcome.response_fields:
        if type(field) is not str or _FIELD_NAME.fullmatch(field) is None:
            raise ProbeExecutionError("provider returned an invalid field name")

    return (
        {
            "api_name": entry.api_name,
            "state": state,
            "provider_class": provider_class,
            "fields": list(outcome.response_fields),
            "row_count": len(outcome.rows),
            "response_bytes": response_bytes,
            "response_sha256": response_sha256,
            "response_redacted": redacted_provider_failure,
            "elapsed_ms": elapsed_ms,
        },
        response_bytes,
    )


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def execute_probe(
    plan: ProbePlan,
    *,
    scope: str,
    token: str,
    concurrency: int,
    transport_scheme: str,
    endpoint_host: str,
    authorize_request_start: Callable[[], RequestStartReservation],
    selected_entries: tuple[ProbeEntry, ...] | None = None,
    call: Callable[..., ProviderCallOutcome] = tushare_rows_outcome,
) -> dict[str, object]:
    planned = plan.planned(scope)
    blocked = plan.blocked(scope)
    all_selected = plan.select(scope)
    selected = all_selected if selected_entries is None else selected_entries
    if scope == "all" and blocked:
        raise ProbeValidationError("all scope contains blocked probe entries")
    if (
        not isinstance(selected, tuple)
        or not selected
        or len(selected) > len(all_selected)
        or any(
            entry not in all_selected or not isinstance(entry, ProbeEntry)
            for entry in selected
        )
        or tuple(entry.api_name for entry in selected)
        != tuple(sorted(entry.api_name for entry in selected))
    ):
        raise ProbeValidationError("probe batch selection is invalid")
    if not planned or not selected:
        raise ProbeValidationError("selected probe scope is empty")
    if type(token) is not str or not token:
        raise ProbeExecutionError("provider token is unavailable")
    if type(concurrency) is not int or not 1 <= concurrency <= MAX_CONCURRENCY:
        raise ProbeValidationError("probe concurrency must be between 1 and 4")
    if transport_scheme != "https" or endpoint_host != "api.quicksync.cn":
        raise ProbeValidationError("probe transport identity is invalid")
    if len(selected) > MAX_REQUESTS_PER_WINDOW:
        raise ProbeValidationError("selected probe scope exceeds the request budget")
    if not callable(authorize_request_start):
        raise ProbeValidationError("probe request-start authorizer is invalid")

    started_at = _utc_now()
    results: list[dict[str, object]] = []
    authorizations: list[RequestStartReservation] = []
    authorization_mutex = threading.Lock()
    response_bytes_total = 0
    position = 0

    def authorize_and_record() -> RequestStartReservation:
        with authorization_mutex:
            authorization = authorize_request_start()
            if (
                not isinstance(authorization, RequestStartReservation)
                or type(authorization.reserved_at_epoch) not in {int, float}
                or not math.isfinite(float(authorization.reserved_at_epoch))
                or authorization.reserved_at_epoch < 0
                or authorization.reserved != 1
                or type(authorization.active_before) is not int
                or type(authorization.active_after) is not int
                or authorization.active_before < 0
                or authorization.active_after != authorization.active_before + 1
                or authorization.active_after > MAX_REQUESTS_PER_WINDOW
                or (
                    authorizations
                    and authorization.reserved_at_epoch
                    < authorizations[-1].reserved_at_epoch
                )
            ):
                raise ProbeValidationError(
                    "probe request-start authorization is invalid"
                )
            authorizations.append(authorization)
            return authorization

    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        while position < len(selected):
            remaining_budget = MAX_RESPONSE_BYTES_PER_RUN - response_bytes_total
            batch: list[tuple[ProbeEntry, int]] = []
            for entry in selected[position : position + concurrency]:
                # ``tushare_rows_outcome`` reads limit + 1 bytes to detect an
                # oversized response, so the extra byte is reserved too.
                if remaining_budget <= 1:
                    break
                allowance = min(MAX_RESPONSE_BYTES_PER_CALL, remaining_budget - 1)
                batch.append((entry, allowance))
                remaining_budget -= allowance + 1
            if not batch:
                raise ProbeExecutionError("run response budget is exhausted")
            futures = [
                executor.submit(
                    _call_entry,
                    entry,
                    token=token,
                    max_response_bytes=allowance,
                    authorize_request_start=authorize_and_record,
                    call=call,
                )
                for entry, allowance in batch
            ]
            batch_results: list[tuple[dict[str, object], int]] = []
            for future in futures:
                try:
                    batch_results.append(future.result())
                except Exception as exc:
                    for pending in futures:
                        pending.cancel()
                    if isinstance(exc, ProbeExecutionError):
                        raise
                    raise ProbeExecutionError("probe batch failed") from exc
            for result, response_bytes in batch_results:
                results.append(result)
                response_bytes_total += response_bytes
            position += len(batch)

    if response_bytes_total > MAX_RESPONSE_BYTES_PER_RUN:
        raise ProbeExecutionError("run response budget was exceeded")
    if len(authorizations) != len(results) or len(authorizations) != len(selected):
        raise ProbeExecutionError("request-start authorization evidence is incomplete")
    state_counts = Counter(str(item["state"]) for item in results)
    return {
        "schema_version": EVIDENCE_SCHEMA_VERSION,
        "production_ready": False,
        "raw_data_persisted": False,
        "credential_persisted": False,
        "request_values_persisted": False,
        "commit": plan.expected_commit,
        "request_plan_sha256": plan.sha256,
        "official_contract_sha256": plan.official_contract_sha256,
        "transport_observations_sha256": plan.transport_observations_sha256,
        "request_observations_sha256": plan.request_observations_sha256,
        "api_names_sha256": plan.api_names_sha256,
        "scheduled_partition": plan.scheduled_partition,
        "run_clock": plan.run_clock,
        "seed_authorities": [dict(item) for item in plan.seed_authorities],
        "scope": scope,
        "interface_count": len(results),
        "coverage": {
            "planned": len(planned),
            "executable": len(all_selected),
            "blocked": len(blocked),
            "selected": len(selected),
            "executed": len(results),
        },
        "started_at": started_at,
        "finished_at": _utc_now(),
        "retries": 0,
        "concurrency": concurrency,
        "rate_budget": {
            "max_requests": MAX_REQUESTS_PER_WINDOW,
            "window_seconds": REQUEST_WINDOW_SECONDS,
            "authorizations": {
                "authorized": len(authorizations),
                "first_authorized_at_epoch": float(authorizations[0].reserved_at_epoch),
                "last_authorized_at_epoch": float(authorizations[-1].reserved_at_epoch),
                "active_before_first": authorizations[0].active_before,
                "active_after_last": authorizations[-1].active_after,
            },
        },
        "response_budget": {
            "per_call_bytes": MAX_RESPONSE_BYTES_PER_CALL,
            "per_run_bytes": MAX_RESPONSE_BYTES_PER_RUN,
            "observed_bytes": response_bytes_total,
        },
        "transport": {
            "scheme": transport_scheme,
            "endpoint_host": endpoint_host,
        },
        "summary": {key: state_counts[key] for key in sorted(state_counts)},
        "results": results,
    }


def _validate_output_target(path: Path) -> Path:
    output = _absolute_canonical_path(path, "evidence output")
    _assert_no_symlink_components(output.parent, "evidence output parent")
    if not output.parent.is_dir() or os.path.lexists(output):
        raise ProbeValidationError("evidence output is unavailable")
    return output


def write_evidence_atomic(path: Path, evidence: Mapping[str, object]) -> None:
    output = _validate_output_target(path)
    try:
        payload = (
            json.dumps(
                evidence,
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
                sort_keys=True,
            )
            + "\n"
        ).encode("utf-8")
    except (TypeError, ValueError):
        raise ProbeValidationError("evidence payload is invalid") from None
    if not payload or len(payload) > MAX_EVIDENCE_BYTES:
        raise ProbeValidationError("evidence payload exceeds its byte budget")

    descriptor = -1
    temporary: Path | None = None
    linked = False
    published_successfully = False
    try:
        descriptor, raw_temporary = tempfile.mkstemp(
            prefix=f".{output.name}.", suffix=".tmp", dir=output.parent
        )
        temporary = Path(raw_temporary)
        os.fchmod(descriptor, 0o600)
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != os.geteuid()
            or metadata.st_nlink != 1
            or stat.S_IMODE(metadata.st_mode) != 0o600
        ):
            raise ProbeValidationError("temporary evidence file is invalid")
        offset = 0
        while offset < len(payload):
            offset += os.write(descriptor, payload[offset:])
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = -1
        try:
            os.link(temporary, output, follow_symlinks=False)
        except OSError:
            raise ProbeValidationError(
                "evidence output could not be published"
            ) from None
        linked = True
        temporary.unlink()
        temporary = None
        parent_descriptor = os.open(
            output.parent,
            os.O_RDONLY
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0),
        )
        try:
            os.fsync(parent_descriptor)
        finally:
            os.close(parent_descriptor)
        published = os.lstat(output)
        if (
            not stat.S_ISREG(published.st_mode)
            or published.st_uid != os.geteuid()
            or published.st_nlink != 1
            or stat.S_IMODE(published.st_mode) != 0o600
        ):
            raise ProbeValidationError("published evidence file is invalid")
        published_successfully = True
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        if linked and not published_successfully:
            output.unlink(missing_ok=True)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request-plan", type=Path, required=True)
    parser.add_argument(
        "--scope", choices=("gaps", "all", "executable"), default="gaps"
    )
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--expected-plan-sha256")
    parser.add_argument("--concurrency", type=int, default=MAX_CONCURRENCY)
    parser.add_argument("--start-index", type=int, default=0)
    parser.add_argument("--max-interfaces", type=int)
    return parser.parse_args(argv)


def select_probe_batch(
    plan: ProbePlan,
    *,
    scope: str,
    start_index: int,
    max_interfaces: int | None,
) -> tuple[ProbeEntry, ...]:
    """Return one deterministic contiguous batch from the frozen selection."""

    if (
        type(start_index) is not int
        or isinstance(start_index, bool)
        or start_index < 0
        or (
            max_interfaces is not None
            and (
                type(max_interfaces) is not int
                or isinstance(max_interfaces, bool)
                or not 1 <= max_interfaces <= MAX_INTERFACE_COUNT
            )
        )
    ):
        raise ProbeValidationError("probe batch range is invalid")
    selected = plan.select(scope)
    if start_index >= len(selected):
        raise ProbeValidationError("probe batch start is outside selected interfaces")
    stop = len(selected) if max_interfaces is None else start_index + max_interfaces
    batch = selected[start_index:stop]
    if not batch:
        raise ProbeValidationError("probe batch selection is empty")
    return batch


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        plan = load_probe_plan(args.request_plan)
        validate_frozen_bindings(
            plan,
            expected_plan_sha256=args.expected_plan_sha256,
        )
        if not args.execute:
            return 0
        if args.output is None or args.expected_plan_sha256 is None:
            raise ProbeValidationError(
                "execute requires output and expected plan SHA-256"
            )
        if args.scope == "all" and plan.blocked("all"):
            raise ProbeValidationError("all scope contains blocked probe entries")
        output = _validate_output_target(args.output)
        selected = select_probe_batch(
            plan,
            scope=args.scope,
            start_index=args.start_index,
            max_interfaces=args.max_interfaces,
        )
        selected_count = len(selected)
        if not 1 <= selected_count <= MAX_REQUESTS_PER_WINDOW:
            raise ProbeValidationError(
                "selected probe scope exceeds the request budget"
            )
        with exclusive_probe_lock(DEFAULT_LOCK_PATH) as lock:
            check_request_start_capacity(lock, selected_count)
            config = get_tushare_config()
            if config.get("api_url") != "https://api.quicksync.cn":
                raise ProbeValidationError("provider config transport is invalid")
            evidence = execute_probe(
                plan,
                scope=args.scope,
                token=config["token"],
                concurrency=args.concurrency,
                transport_scheme="https",
                endpoint_host="api.quicksync.cn",
                authorize_request_start=lambda: authorize_request_start(lock),
                selected_entries=selected,
                call=tushare_rows_outcome,
            )
            post_execution_plan = load_probe_plan(args.request_plan)
            if post_execution_plan.sha256 != plan.sha256:
                raise ProbeValidationError("request plan changed during execution")
            validate_frozen_bindings(
                post_execution_plan,
                expected_plan_sha256=args.expected_plan_sha256,
            )
            write_evidence_atomic(output, evidence)
        return 0
    except ProbeBusyError:
        return 75
    except Exception:
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

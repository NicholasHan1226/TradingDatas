#!/usr/bin/env python3
"""Shared helpers for the TradingDatas Tushare transport adapter."""

from __future__ import annotations

from collections import deque
import hashlib
import http.client
import json
import math
import os
import re
import socket
import ssl
import stat
import threading
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterable as IterableABC
from collections.abc import Mapping as MappingABC
from collections.abc import Callable
from dataclasses import InitVar, dataclass, field
from types import MappingProxyType
from typing import Any, Literal, Mapping

from provider_transport import (
    QUICKSYNC_TUSHARE_API_URL,
    TUSHARE_DATA_PROVIDER,
    provider_transport_profile,
)

TUSHARE_API_URL_ENV = "TUSHARE_API_URL"
TUSHARE_TOKEN_FILE_ENV = "TUSHARE_TOKEN_FILE"
_QUICKSYNC_TUSHARE_HOST = "api.quicksync.cn"
_MAX_TOKEN_FILE_BYTES = 4_096
_DEFAULT_PROVIDER_RESPONSE_BYTES = 16 * 1024 * 1024
_MAX_PROVIDER_RESPONSE_BYTES = 64 * 1024 * 1024
_QUICKSYNC_MAX_REQUESTS = 200
_QUICKSYNC_REQUEST_WINDOW_SECONDS = 60
_QUICKSYNC_MAX_CONCURRENCY = 4
_QUICKSYNC_NODE_COOLDOWN_SECONDS = 30

_REDACTION_MARKER = "[REDACTED]"
_CREDENTIAL_NAME_PATTERN = (
    r"(?:authorization|proxy[ _-]*authorization|"
    r"(?:x[ _-]*)?(?:access[ _-]*token|refresh[ _-]*token|id[ _-]*token|"
    r"auth[ _-]*token|token|api[ _-]*(?:key|token))|"
    r"password|passwd|credential(?:s)?|client[ _-]*secret|secret|"
    r"cookie|set[ _-]*cookie)"
)
_CREDENTIAL_INDICATOR_PATTERN = re.compile(
    rf"(?<![A-Za-z0-9_.-])(?:[bB](?=[\"']))?[\"']?"
    rf"{_CREDENTIAL_NAME_PATTERN}[\"']?(?![A-Za-z0-9_.-])",
    re.IGNORECASE,
)
_AUTH_SCHEME_INDICATOR_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_.-])(?:bearer|basic)\s+\S",
    re.IGNORECASE,
)
_CREDENTIAL_KEY_PATTERN = re.compile(
    _CREDENTIAL_NAME_PATTERN,
    re.IGNORECASE,
)
_SIMPLE_ESCAPES = {
    "\\": "\\",
    "/": "/",
    '"': '"',
    "'": "'",
    "b": "\b",
    "f": "\f",
    "n": "\n",
    "r": "\r",
    "t": "\t",
}
_HEX_DIGITS = frozenset("0123456789abcdefABCDEF")
_MAPPING_PROXY_TYPE = type(MappingProxyType({}))


@dataclass(frozen=True)
class SensitiveScanBudget:
    """Explicit fail-closed limits for recursive sensitive-value scans.

    ``max_nodes`` covers one recursive value traversal. ``max_views`` and
    ``max_decode_rounds`` apply to each scalar representation. Callers with a
    legitimately larger, trusted-shape response can opt into a larger budget.
    Exhaustion never means "clear": it makes the scanned value untrusted.
    """

    max_depth: int = 32
    max_nodes: int = 100_000
    max_decode_rounds: int = 16
    max_views: int = 256

    def __post_init__(self) -> None:
        limits = {
            "max_depth": (self.max_depth, 0),
            "max_nodes": (self.max_nodes, 1),
            "max_decode_rounds": (self.max_decode_rounds, 1),
            "max_views": (self.max_views, 1),
        }
        for name, (value, minimum) in limits.items():
            if type(value) is not int or value < minimum:
                raise ValueError(f"{name} must be an integer >= {minimum}")


_DEFAULT_SENSITIVE_SCAN_BUDGET = SensitiveScanBudget()


class _SensitiveScanFailure(Exception):
    """Internal marker: a value could not be proven free of known secrets."""


class _SensitiveScanState:
    __slots__ = ("active_containers", "budget", "nodes")

    def __init__(self, budget: SensitiveScanBudget) -> None:
        self.budget = budget
        self.nodes = 0
        self.active_containers: set[int] = set()

    def visit(self, depth: int) -> None:
        if depth > self.budget.max_depth:
            raise _SensitiveScanFailure from None
        self.nodes += 1
        if self.nodes > self.budget.max_nodes:
            raise _SensitiveScanFailure from None


def _resolve_scan_budget(
    scan_budget: SensitiveScanBudget | None,
) -> SensitiveScanBudget:
    if scan_budget is None:
        return _DEFAULT_SENSITIVE_SCAN_BUDGET
    if not isinstance(scan_budget, SensitiveScanBudget):
        raise _SensitiveScanFailure from None
    return scan_budget


def _normalize_utf16_surrogates(value: str) -> str:
    normalized: list[str] = []
    index = 0
    while index < len(value):
        code_unit = ord(value[index])
        if 0xD800 <= code_unit <= 0xDBFF:
            if index + 1 >= len(value):
                raise _SensitiveScanFailure from None
            low_surrogate = ord(value[index + 1])
            if not 0xDC00 <= low_surrogate <= 0xDFFF:
                raise _SensitiveScanFailure from None
            code_point = (
                0x10000 + ((code_unit - 0xD800) << 10) + (low_surrogate - 0xDC00)
            )
            normalized.append(chr(code_point))
            index += 2
            continue
        if 0xDC00 <= code_unit <= 0xDFFF:
            raise _SensitiveScanFailure from None
        normalized.append(value[index])
        index += 1
    return "".join(normalized)


def _decode_backslash_escapes(value: str) -> str:
    """Decode one representation layer and validate UTF-16 surrogates."""

    decoded: list[str] = []
    index = 0
    while index < len(value):
        character = value[index]
        if character != "\\" or index + 1 >= len(value):
            decoded.append(character)
            index += 1
            continue

        marker = value[index + 1]
        if marker == "\\":
            decoded.append("\\")
            index += 2
            continue
        if marker in ("u", "U", "x"):
            width = {"u": 4, "U": 8, "x": 2}[marker]
            start = index + 2
            encoded = value[start : start + width]
            if len(encoded) != width or any(
                digit not in _HEX_DIGITS for digit in encoded
            ):
                raise _SensitiveScanFailure from None
            try:
                decoded.append(chr(int(encoded, 16)))
            except (OverflowError, ValueError):
                raise _SensitiveScanFailure from None
            index = start + width
            continue
        if marker in _SIMPLE_ESCAPES:
            decoded.append(_SIMPLE_ESCAPES[marker])
            index += 2
            continue
        decoded.append("\\")
        index += 1

    return _normalize_utf16_surrogates("".join(decoded))


def _strip_repr_wrapper(value: str) -> str:
    prefix_length = 1 if len(value) >= 3 and value[0] in "bBrRuU" else 0
    if len(value) - prefix_length < 2:
        return value
    quote = value[prefix_length]
    if quote not in "\"'" or value[-1] != quote:
        return value
    return value[prefix_length + 1 : -1]


def _strip_singleton_tuple_repr(value: str) -> str:
    stripped = value.strip()
    if not stripped.startswith("(") or not stripped.endswith(",)"):
        return value
    inner = stripped[1:-2].strip()
    unwrapped = _strip_repr_wrapper(inner)
    return unwrapped if unwrapped != inner else value


def _safe_text_transform(transform: Any, value: str) -> str:
    try:
        candidate = transform(value)
    except Exception:
        raise _SensitiveScanFailure from None
    if not isinstance(candidate, str):
        raise _SensitiveScanFailure from None
    return candidate


def _strip_unicode_format_controls(value: str) -> str:
    return "".join(
        character for character in value if unicodedata.category(character) != "Cf"
    )


def _diagnostic_views(
    message: str,
    *,
    scan_budget: SensitiveScanBudget | None = None,
) -> tuple[str, ...]:
    """Return bounded representation views for guard checks, never for output."""

    budget = _resolve_scan_budget(scan_budget)
    if not isinstance(message, str):
        raise _SensitiveScanFailure from None
    views: list[str] = [message]
    seen = {message}
    pending = [message]
    for _ in range(budget.max_decode_rounds):
        next_pending: list[str] = []
        for value in pending:
            candidates = (
                _safe_text_transform(urllib.parse.unquote, value),
                _safe_text_transform(urllib.parse.unquote_plus, value),
                _safe_text_transform(_decode_backslash_escapes, value),
                _safe_text_transform(
                    lambda text: unicodedata.normalize("NFKC", text),
                    value,
                ),
                _safe_text_transform(_strip_unicode_format_controls, value),
                _strip_repr_wrapper(value),
                _strip_singleton_tuple_repr(value),
            )
            for candidate in candidates:
                if candidate in seen:
                    continue
                if len(views) >= budget.max_views:
                    raise _SensitiveScanFailure from None
                seen.add(candidate)
                views.append(candidate)
                next_pending.append(candidate)
        pending = next_pending
        if not pending:
            return tuple(views)
    raise _SensitiveScanFailure from None


def _coerce_sensitive_values(
    values: Any,
    *,
    scan_budget: SensitiveScanBudget | None = None,
) -> tuple[Any, ...]:
    budget = _resolve_scan_budget(scan_budget)
    if values is None:
        return ()
    if isinstance(values, (str, bytes, bytearray, memoryview)):
        return (values,)
    try:
        iterator = iter(values)
    except TypeError:
        return (values,)
    except Exception:
        raise _SensitiveScanFailure from None

    coerced: list[Any] = []
    while True:
        try:
            value = next(iterator)
        except StopIteration:
            return tuple(coerced)
        except Exception:
            raise _SensitiveScanFailure from None
        coerced.append(value)
        if len(coerced) > budget.max_nodes:
            raise _SensitiveScanFailure from None


def _scalar_texts(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,)
    if isinstance(value, (bytes, bytearray, memoryview)):
        try:
            raw = bytes(value)
        except Exception:
            raise _SensitiveScanFailure from None
        texts = [repr(raw)]
        for encoding in ("utf-8", "latin-1"):
            try:
                decoded = raw.decode(encoding)
            except UnicodeError:
                continue
            if decoded not in texts:
                texts.append(decoded)
        return tuple(texts)
    if value is None or isinstance(value, bool):
        return ()
    if isinstance(value, (int, float)):
        return (str(value),)
    texts: list[str] = []
    for convert in (str, repr):
        try:
            text = convert(value)
        except Exception:
            raise _SensitiveScanFailure from None
        if not isinstance(text, str):
            raise _SensitiveScanFailure from None
        if text not in texts:
            texts.append(text)
    return tuple(texts)


def _walk_scalar_texts(
    value: Any,
    *,
    scan_budget: SensitiveScanBudget | None = None,
    state: _SensitiveScanState | None = None,
    depth: int = 0,
):
    budget = _resolve_scan_budget(scan_budget)
    state = state if state is not None else _SensitiveScanState(budget)
    state.visit(depth)

    if isinstance(value, (str, bytes, bytearray, memoryview)):
        yield from _scalar_texts(value)
        return
    if value is None or isinstance(value, (bool, int, float)):
        yield from _scalar_texts(value)
        return

    if isinstance(value, MappingABC):
        identity = id(value)
        if identity in state.active_containers:
            raise _SensitiveScanFailure from None
        state.active_containers.add(identity)
        try:
            try:
                iterator = iter(value.items())
            except Exception:
                raise _SensitiveScanFailure from None
            while True:
                try:
                    pair = next(iterator)
                except StopIteration:
                    break
                except Exception:
                    raise _SensitiveScanFailure from None
                try:
                    key, item = pair
                except Exception:
                    raise _SensitiveScanFailure from None
                yield from _walk_scalar_texts(
                    key,
                    scan_budget=budget,
                    state=state,
                    depth=depth + 1,
                )
                yield from _walk_scalar_texts(
                    item,
                    scan_budget=budget,
                    state=state,
                    depth=depth + 1,
                )
        finally:
            state.active_containers.discard(identity)
        return

    if isinstance(value, IterableABC):
        identity = id(value)
        if identity in state.active_containers:
            raise _SensitiveScanFailure from None
        state.active_containers.add(identity)
        try:
            try:
                iterator = iter(value)
            except Exception:
                raise _SensitiveScanFailure from None
            while True:
                try:
                    item = next(iterator)
                except StopIteration:
                    break
                except Exception:
                    raise _SensitiveScanFailure from None
                yield from _walk_scalar_texts(
                    item,
                    scan_budget=budget,
                    state=state,
                    depth=depth + 1,
                )
        finally:
            state.active_containers.discard(identity)
        return

    yield from _scalar_texts(value)


def _sensitive_forms(
    sensitive_values: Any,
    *,
    scan_budget: SensitiveScanBudget | None = None,
) -> frozenset[str]:
    budget = _resolve_scan_budget(scan_budget)
    forms: set[str] = set()
    state = _SensitiveScanState(budget)
    for value in _coerce_sensitive_values(
        sensitive_values,
        scan_budget=budget,
    ):
        for text in _walk_scalar_texts(
            value,
            scan_budget=budget,
            state=state,
        ):
            views = _diagnostic_views(text, scan_budget=budget)
            if text and "" in views:
                raise _SensitiveScanFailure from None
            forms.update(view for view in views if view)
    return frozenset(forms)


def _contains_sensitive_value(
    value: Any,
    sensitive_values: Any,
    *,
    scan_budget: SensitiveScanBudget | None = None,
) -> bool:
    """Return true for a match *or* an incomplete/unreliable scan."""

    try:
        budget = _resolve_scan_budget(scan_budget)
        forms = _sensitive_forms(sensitive_values, scan_budget=budget)
        state = _SensitiveScanState(budget)
        for text in _walk_scalar_texts(
            value,
            scan_budget=budget,
            state=state,
        ):
            for view in _diagnostic_views(text, scan_budget=budget):
                if any(form in view for form in forms):
                    return True
        return False
    except Exception:
        return True


def _credential_detection_views(
    value: str,
    *,
    scan_budget: SensitiveScanBudget,
) -> tuple[str, ...]:
    return tuple(
        view.strip() for view in _diagnostic_views(value, scan_budget=scan_budget)
    )


def _text_is_credential_key(
    value: str,
    *,
    scan_budget: SensitiveScanBudget,
) -> bool:
    return any(
        _CREDENTIAL_KEY_PATTERN.fullmatch(view)
        for view in _credential_detection_views(
            value,
            scan_budget=scan_budget,
        )
    )


def _scan_structured_credentials(
    value: Any,
    *,
    scan_budget: SensitiveScanBudget,
    state: _SensitiveScanState,
    depth: int = 0,
) -> bool:
    """Scan exact credential keys without guessing from business-row prose.

    Caller-known secrets are handled separately by ``_contains_sensitive_value``.
    An unknown foreign secret hidden in a neutral business string has no reliable
    generic signature and is outside this classifier's contract; it requires a
    credential key/field or a diagnostic/metadata source boundary.
    """

    state.visit(depth)
    value_type = type(value)

    if value_type is str:
        return False
    if value is None or value_type in (bool, int, float):
        return False

    if value_type in (dict, _MAPPING_PROXY_TYPE):
        identity = id(value)
        if identity in state.active_containers:
            raise _SensitiveScanFailure from None
        state.active_containers.add(identity)
        try:
            for key, item in value.items():
                if type(key) is not str:
                    raise _SensitiveScanFailure from None
                if _text_is_credential_key(key, scan_budget=scan_budget):
                    return True

                if key == "fields" and "items" in value:
                    if type(item) not in (list, tuple):
                        raise _SensitiveScanFailure from None
                    for field in item:
                        if type(field) is not str:
                            raise _SensitiveScanFailure from None
                        if _text_is_credential_key(
                            field,
                            scan_budget=scan_budget,
                        ):
                            return True

                if _scan_structured_credentials(
                    item,
                    scan_budget=scan_budget,
                    state=state,
                    depth=depth + 1,
                ):
                    return True
        finally:
            state.active_containers.discard(identity)
        return False

    if value_type in (list, tuple):
        identity = id(value)
        if identity in state.active_containers:
            raise _SensitiveScanFailure from None
        state.active_containers.add(identity)
        try:
            return any(
                _scan_structured_credentials(
                    item,
                    scan_budget=scan_budget,
                    state=state,
                    depth=depth + 1,
                )
                for item in value
            )
        finally:
            state.active_containers.discard(identity)

    raise _SensitiveScanFailure from None


def _contains_structured_credential(
    value: Any,
    *,
    scan_budget: SensitiveScanBudget | None = None,
) -> bool:
    """Return true for credential structure or an unreliable strict scan."""

    try:
        budget = _resolve_scan_budget(scan_budget)
        return _scan_structured_credentials(
            value,
            scan_budget=budget,
            state=_SensitiveScanState(budget),
        )
    except Exception:
        return True


def _freeze_provider_value(
    value: Any,
    *,
    scan_budget: SensitiveScanBudget,
    state: _SensitiveScanState,
    depth: int = 0,
) -> Any:
    """Copy one exact JSON-native value into an immutable representation."""

    state.visit(depth)
    value_type = type(value)
    if value_type is str or value is None or value_type in (bool, int):
        return value
    if value_type is float:
        if not math.isfinite(value):
            raise _SensitiveScanFailure from None
        return value

    if value_type is dict:
        identity = id(value)
        if identity in state.active_containers:
            raise _SensitiveScanFailure from None
        state.active_containers.add(identity)
        try:
            frozen: dict[str, Any] = {}
            for key, item in value.items():
                if type(key) is not str:
                    raise _SensitiveScanFailure from None
                frozen[key] = _freeze_provider_value(
                    item,
                    scan_budget=scan_budget,
                    state=state,
                    depth=depth + 1,
                )
            return MappingProxyType(frozen)
        finally:
            state.active_containers.discard(identity)

    if value_type in (list, tuple):
        identity = id(value)
        if identity in state.active_containers:
            raise _SensitiveScanFailure from None
        state.active_containers.add(identity)
        try:
            return tuple(
                _freeze_provider_value(
                    item,
                    scan_budget=scan_budget,
                    state=state,
                    depth=depth + 1,
                )
                for item in value
            )
        finally:
            state.active_containers.discard(identity)

    raise _SensitiveScanFailure from None


def _freeze_provider_rows(
    rows: Any,
    *,
    scan_budget: SensitiveScanBudget,
) -> tuple[Mapping[str, Any], ...]:
    if type(rows) is not tuple or any(type(row) is not dict for row in rows):
        raise _SensitiveScanFailure from None
    frozen = _freeze_provider_value(
        rows,
        scan_budget=scan_budget,
        state=_SensitiveScanState(scan_budget),
    )
    if type(frozen) is not tuple or any(
        type(row) is not _MAPPING_PROXY_TYPE for row in frozen
    ):
        raise _SensitiveScanFailure from None
    return frozen


def _thaw_provider_value(
    value: Any,
    *,
    scan_budget: SensitiveScanBudget,
    state: _SensitiveScanState,
    depth: int = 0,
) -> Any:
    """Copy an immutable provider value back to plain JSON-native containers."""

    state.visit(depth)
    value_type = type(value)
    if value_type is str or value is None or value_type in (bool, int):
        return value
    if value_type is float:
        if not math.isfinite(value):
            raise _SensitiveScanFailure from None
        return value

    if value_type is _MAPPING_PROXY_TYPE:
        identity = id(value)
        if identity in state.active_containers:
            raise _SensitiveScanFailure from None
        state.active_containers.add(identity)
        try:
            mutable: dict[str, Any] = {}
            for key, item in value.items():
                if type(key) is not str:
                    raise _SensitiveScanFailure from None
                mutable[key] = _thaw_provider_value(
                    item,
                    scan_budget=scan_budget,
                    state=state,
                    depth=depth + 1,
                )
            return mutable
        finally:
            state.active_containers.discard(identity)

    if value_type is tuple:
        identity = id(value)
        if identity in state.active_containers:
            raise _SensitiveScanFailure from None
        state.active_containers.add(identity)
        try:
            return [
                _thaw_provider_value(
                    item,
                    scan_budget=scan_budget,
                    state=state,
                    depth=depth + 1,
                )
                for item in value
            ]
        finally:
            state.active_containers.discard(identity)

    raise _SensitiveScanFailure from None


def _contains_credential_indicator(
    message: str,
    *,
    scan_budget: SensitiveScanBudget | None = None,
) -> bool:
    try:
        budget = _resolve_scan_budget(scan_budget)
        return any(
            _CREDENTIAL_INDICATOR_PATTERN.search(view)
            or _AUTH_SCHEME_INDICATOR_PATTERN.search(view)
            for view in _credential_detection_views(
                message,
                scan_budget=budget,
            )
        )
    except Exception:
        return True


def _contains_provider_metadata_credential(
    metadata: Any,
    *,
    scan_budget: SensitiveScanBudget | None = None,
) -> bool:
    """Strictly scan diagnostic/metadata text, never successful row content."""

    try:
        budget = _resolve_scan_budget(scan_budget)
        state = _SensitiveScanState(budget)
        return any(
            _contains_credential_indicator(text, scan_budget=budget)
            for text in _walk_scalar_texts(
                metadata,
                scan_budget=budget,
                state=state,
            )
        )
    except Exception:
        return True


def _redacted_diagnostic_summary() -> str:
    return f"provider diagnostic {_REDACTION_MARKER}"


def _guard_provider_diagnostic(
    message: Any,
    *,
    sensitive_values: Any = (),
    scan_budget: SensitiveScanBudget | None = None,
) -> tuple[str, bool]:
    """Return safe text and whether it may influence derived classifications."""

    if type(message) is not str:
        return _redacted_diagnostic_summary(), False
    if _contains_sensitive_value(
        message,
        sensitive_values,
        scan_budget=scan_budget,
    ):
        return _redacted_diagnostic_summary(), False
    if _contains_credential_indicator(message, scan_budget=scan_budget):
        return _redacted_diagnostic_summary(), False
    return message, True


def _redact_sensitive_text(
    message: Any,
    *,
    sensitive_values: Any = (),
    scan_budget: SensitiveScanBudget | None = None,
) -> str:
    """Make one diagnostic safe before it crosses an outcome boundary.

    Known per-call secrets are checked across bounded representation views.
    Credential-shaped diagnostics are never parsed for suffixes or status:
    the whole value is replaced with a constant summary.
    """

    safe_message, _ = _guard_provider_diagnostic(
        message,
        sensitive_values=sensitive_values,
        scan_budget=scan_budget,
    )
    return safe_message


_PROVIDER_FIELD_NAME = re.compile(r"^[A-Za-z0-9_]{1,64}$")


def _validated_response_fields(value: Any) -> tuple[str, ...]:
    if type(value) is not tuple or any(
        type(field) is not str or _PROVIDER_FIELD_NAME.fullmatch(field) is None
        for field in value
    ):
        raise ValueError("provider outcome response fields are invalid")
    if len(set(value)) != len(value):
        raise ValueError("provider outcome response fields must be unique")
    return value


@dataclass(frozen=True)
class ProviderCallOutcome:
    """Provider truth preserved through provider-neutral row normalization."""

    state: Literal["success", "empty", "failed"]
    rows: tuple[Mapping[str, Any], ...]
    provider_code: int | str | None
    error_code: str | None
    error_message: str | None
    response_fields: tuple[str, ...] = ()
    sensitive_values: InitVar[Any] = ()
    scan_budget: InitVar[SensitiveScanBudget | None] = None
    _validation_scan_budget: SensitiveScanBudget = field(
        init=False,
        repr=False,
        compare=False,
    )

    def __post_init__(
        self,
        sensitive_values: Any,
        scan_budget: SensitiveScanBudget | None,
    ) -> None:
        try:
            budget = _resolve_scan_budget(scan_budget)
            guarded_values = _coerce_sensitive_values(
                sensitive_values,
                scan_budget=budget,
            )
            frozen_rows = _freeze_provider_rows(
                self.rows,
                scan_budget=budget,
            )
        except Exception:
            raise ValueError(
                "provider outcome contains sensitive or unscannable values"
            ) from None
        sensitive_values_unscannable = _contains_sensitive_value(
            (),
            guarded_values,
            scan_budget=budget,
        )
        if self.state != "failed" and sensitive_values_unscannable:
            raise ValueError(
                "provider outcome contains sensitive or unscannable values"
            )
        if _contains_structured_credential(
            frozen_rows,
            scan_budget=budget,
        ) or (
            frozen_rows
            and _contains_sensitive_value(
                frozen_rows,
                guarded_values,
                scan_budget=budget,
            )
        ):
            raise ValueError(
                "provider outcome contains sensitive or unscannable values"
            )
        object.__setattr__(self, "rows", frozen_rows)
        object.__setattr__(self, "_validation_scan_budget", budget)
        provider_code = _sanitize_provider_code(
            self.provider_code,
            guarded_values,
            scan_budget=budget,
        )
        error_code = _sanitize_error_code(
            self.error_code,
            guarded_values,
            scan_budget=budget,
        )
        error_message = None
        diagnostic_trusted = True
        if self.error_message is not None:
            error_message, diagnostic_trusted = _guard_provider_diagnostic(
                self.error_message,
                sensitive_values=guarded_values,
                scan_budget=budget,
            )
        if self.state == "failed" and (
            not diagnostic_trusted or provider_code == _UNTRUSTED_PROVIDER_CODE
        ):
            error_code = "provider_error"
        object.__setattr__(self, "provider_code", provider_code)
        object.__setattr__(self, "error_code", error_code)
        object.__setattr__(self, "error_message", error_message)
        object.__setattr__(
            self,
            "response_fields",
            _validated_response_fields(self.response_fields),
        )
        self.validate_invariants()

    def validate_invariants(self) -> None:
        if self.state not in ("success", "empty", "failed"):
            raise ValueError("provider outcome has an invalid state")
        if self.state == "success" and not self.rows:
            raise ValueError("provider outcome success requires non-empty rows")
        if self.state in ("empty", "failed") and self.rows:
            raise ValueError(f"provider outcome {self.state} must not contain rows")
        response_fields = _validated_response_fields(self.response_fields)
        if self.state == "failed" and response_fields:
            raise ValueError("provider outcome failed must not contain response fields")
        if (
            self.state == "success"
            and response_fields
            and any(tuple(row) != response_fields for row in self.rows)
        ):
            raise ValueError("provider outcome response fields do not match rows")
        try:
            budget = object.__getattribute__(self, "_validation_scan_budget")
            if type(self.rows) is not tuple or any(
                type(row) is not _MAPPING_PROXY_TYPE for row in self.rows
            ):
                raise _SensitiveScanFailure from None
            state = _SensitiveScanState(budget)
            for row in self.rows:
                thawed = _thaw_provider_value(
                    row,
                    scan_budget=budget,
                    state=state,
                )
                if type(thawed) is not dict:
                    raise _SensitiveScanFailure from None
            if _contains_structured_credential(
                self.rows,
                scan_budget=budget,
            ):
                raise _SensitiveScanFailure from None
        except Exception:
            raise ValueError("provider outcome contains invalid rows") from None

    def mutable_rows(self) -> list[dict[str, Any]]:
        """Return independent plain JSON-native rows for mutable consumers."""

        self.validate_invariants()
        try:
            budget = object.__getattribute__(self, "_validation_scan_budget")
            state = _SensitiveScanState(budget)
            rows = [
                _thaw_provider_value(
                    row,
                    scan_budget=budget,
                    state=state,
                )
                for row in self.rows
            ]
            if any(type(row) is not dict for row in rows):
                raise _SensitiveScanFailure from None
            return rows
        except Exception:
            raise ValueError("provider outcome contains invalid rows") from None


_SAFE_PROVIDER_CODE = re.compile(r"-?(?:0|[1-9][0-9]{0,15})")
_SAFE_ERROR_CODES = frozenset(
    (
        None,
        "provider_error",
        "rate_limited",
        "permission_denied",
        "resource_budget",
        "transport_error",
    )
)
_UNTRUSTED_PROVIDER_CODE = "<untrusted-provider-code>"
_UNTRUSTED_ERROR_CODE = "<untrusted-error-code>"


def _sanitize_provider_code(
    value: Any,
    sensitive_values: Any = (),
    *,
    scan_budget: SensitiveScanBudget | None = None,
) -> int | str | None:
    if _contains_sensitive_value(
        value,
        sensitive_values,
        scan_budget=scan_budget,
    ):
        return _UNTRUSTED_PROVIDER_CODE
    if value is None or type(value) is int:
        return value
    if isinstance(value, str):
        sanitized = _redact_sensitive_text(
            value,
            sensitive_values=sensitive_values,
            scan_budget=scan_budget,
        )
        if _SAFE_PROVIDER_CODE.fullmatch(sanitized):
            return sanitized
    return _UNTRUSTED_PROVIDER_CODE


def _sanitize_error_code(
    value: Any,
    sensitive_values: Any = (),
    *,
    scan_budget: SensitiveScanBudget | None = None,
) -> str | None:
    if _contains_sensitive_value(
        value,
        sensitive_values,
        scan_budget=scan_budget,
    ):
        return _UNTRUSTED_ERROR_CODE
    if value is None:
        return None
    if isinstance(value, str):
        sanitized = _redact_sensitive_text(
            value,
            sensitive_values=sensitive_values,
            scan_budget=scan_budget,
        )
        if sanitized in _SAFE_ERROR_CODES:
            return sanitized
    return _UNTRUSTED_ERROR_CODE


def provider_outcome_log_fields(
    outcome: ProviderCallOutcome,
    *,
    sensitive_values: Any = (),
    scan_budget: SensitiveScanBudget | None = None,
) -> dict[str, Any]:
    """Return diagnostic outcome fields with no untrusted log arguments."""

    provider_code = _sanitize_provider_code(
        outcome.provider_code,
        sensitive_values,
        scan_budget=scan_budget,
    )
    error_code = _sanitize_error_code(
        outcome.error_code,
        sensitive_values,
        scan_budget=scan_budget,
    )
    state = (
        outcome.state
        if outcome.state in ("success", "empty", "failed")
        else "<invalid-outcome-state>"
    )
    if outcome.error_message is not None:
        error_message, diagnostic_trusted = _guard_provider_diagnostic(
            outcome.error_message,
            sensitive_values=sensitive_values,
            scan_budget=scan_budget,
        )
    else:
        error_message = None
        diagnostic_trusted = True
    if outcome.state == "failed" and (
        not diagnostic_trusted or provider_code == _UNTRUSTED_PROVIDER_CODE
    ):
        error_code = "provider_error"
    return {
        "state": state,
        "provider_code": provider_code,
        "error_code": error_code,
        "error_message": error_message,
    }


def safe_provider_exception_message(
    exc: BaseException,
    *,
    invalid_outcome: bool = False,
) -> str:
    """Classify an exception without retaining its arbitrary text or repr."""

    reason: object = exc
    if isinstance(exc, urllib.error.HTTPError):
        code = exc.code
        if type(code) is int and 100 <= code <= 599:
            return f"provider transport HTTP failure (status={code})"
        return "provider transport HTTP failure"
    if isinstance(exc, urllib.error.URLError):
        reason = exc.reason
    if isinstance(reason, TimeoutError):
        return "provider transport timed out"
    if isinstance(exc, urllib.error.URLError) or isinstance(
        reason,
        (ConnectionError, OSError),
    ):
        return "provider transport unavailable"
    if invalid_outcome and isinstance(exc, (TypeError, ValueError)):
        return "provider outcome invalid"
    return "provider transport failed"


class _ProviderResponseValidationError(ValueError):
    """Internal-only response validation failure with a safe diagnostic."""


def _safe_provider_response_error_message(exc: BaseException) -> str:
    """Preserve only diagnostics generated by our own response validators."""

    if isinstance(exc, UnicodeError):
        return "Tushare response contains invalid UTF-8"
    if isinstance(exc, json.JSONDecodeError):
        return "Tushare response contains invalid JSON"
    if isinstance(exc, _ProviderResponseValidationError):
        return str(exc)
    return "Tushare response validation failed"


_CLASSIFIABLE_PROVIDER_CODES = frozenset(
    (-2001, "-2001", 40101, "40101", 40203, "40203")
)
_INTERNAL_ERROR_PATTERNS = (
    re.compile(
        r"\b(?:service|config(?:uration)?|classifier|cache|policy|limiter)\b"
        r".{0,80}\b(?:unavailable|failure|failed|error)\b"
    ),
    re.compile(
        r"\b(?:unavailable|failure|failed|error)\b"
        r".{0,80}\b(?:service|config(?:uration)?|classifier|cache|policy|limiter)\b"
    ),
    re.compile(r"(?:服务|配置|分类器|缓存|检测).{0,20}(?:异常|故障|失败|不可用)"),
)
_ENGLISH_RETRY_SUFFIX = (
    r"(?:[.!?]|[,.!:;]\s*"
    r"(?:please\s+(?:try|retry)\s+again\s+later|retry\s+later)[.!?]?)?"
)
_CHINESE_RETRY_SUFFIX = r"(?:[，,]\s*请稍后(?:再试|重试))?[。.!]?"
_RATE_LIMIT_PATTERNS = (
    re.compile(
        rf"(?:the\s+)?rate\s+limit\s+(?:has\s+been\s+)?exceeded"
        rf"{_ENGLISH_RETRY_SUFFIX}"
    ),
    re.compile(rf"too\s+many\s+requests?{_ENGLISH_RETRY_SUFFIX}"),
    re.compile(rf"requests?\s+(?:has\s+been\s+)?throttled{_ENGLISH_RETRY_SUFFIX}"),
    re.compile(
        rf"(?:抱歉[，,]\s*)?每(?:秒|分钟|小时|日|天).{{0,24}}"
        rf"最多(?:可)?(?:访问|调用).{{0,24}}\d+\s*次{_CHINESE_RETRY_SUFFIX}"
    ),
    re.compile(rf"(?:抱歉[，,]\s*)?(?:请求|访问)过于频繁{_CHINESE_RETRY_SUFFIX}"),
    re.compile(
        rf"(?:抱歉[，,]\s*)?(?:请求|访问)频率"
        rf"(?:太高|过高|超限|超过限制|超出限制|达到上限|已达上限)"
        rf"{_CHINESE_RETRY_SUFFIX}"
    ),
    re.compile(
        rf"(?:抱歉[，,]\s*)?(?:请求|访问)次数"
        rf"(?:太多|过多|超限|超过限制|超出限制|达到上限|已达上限)"
        rf"{_CHINESE_RETRY_SUFFIX}"
    ),
    re.compile(rf"(?:触发|已被)限流{_CHINESE_RETRY_SUFFIX}"),
)
_PERMISSION_DENIED_PATTERNS = (
    re.compile(
        rf"(?:permission|access)\s+denied"
        rf"(?:\s+(?:for|to)\s+(?:this|the)\s+(?:endpoint|api|interface|service))?"
        rf"{_ENGLISH_RETRY_SUFFIX}"
    ),
    re.compile(r"(?:not\s+authori[sz]ed|unauthorized|forbidden)[.!]?"),
    re.compile(
        rf"(?:you|the\s+user|this\s+account)\s+(?:are|is)\s+not\s+"
        rf"(?:authori[sz]ed|allowed)\s+to\s+(?:access|call|use)\s+"
        rf"(?:this|the)\s+(?:endpoint|api|interface|service)"
        rf"{_ENGLISH_RETRY_SUFFIX}"
    ),
    re.compile(
        rf"(?:you|the\s+user|this\s+account)\s+(?:do|does)\s+not\s+have\s+"
        rf"(?:the\s+)?(?:required\s+)?permission\s+to\s+"
        rf"(?:access|call|use)\s+(?:this|the)\s+"
        rf"(?:endpoint|api|interface|service){_ENGLISH_RETRY_SUFFIX}"
    ),
    re.compile(
        r"(?:抱歉[，,]\s*)?(?:您|你|用户|账户)"
        r"(?:"
        r"没有(?:访问|调用|使用)(?:该|此|这个)?(?:接口|api|服务)的?权限"
        r"|没有权限(?:访问|调用|使用)(?:该|此|这个)?(?:接口|api|服务)"
        r"|(?:无权|未授权)(?:访问|调用|使用)(?:该|此|这个)?(?:接口|api|服务)"
        rf"){_CHINESE_RETRY_SUFFIX}"
    ),
    re.compile(
        rf"(?:该|此)?(?:接口|访问|调用)?权限(?:不足|被拒绝|未开通)"
        rf"{_CHINESE_RETRY_SUFFIX}"
    ),
    re.compile(
        rf"(?:抱歉[，,]\s*)?(?:(?:您|你|用户|账户)的?)?积分(?:不足|不够)"
        rf"{_CHINESE_RETRY_SUFFIX}"
    ),
)


def _provider_error_code(provider_code: int | str | None, message: str) -> str:
    normalized = " ".join(message.casefold().split())
    if provider_code not in _CLASSIFIABLE_PROVIDER_CODES:
        return "provider_error"
    if any(pattern.search(normalized) for pattern in _INTERNAL_ERROR_PATTERNS):
        return "provider_error"
    if any(pattern.fullmatch(normalized) for pattern in _RATE_LIMIT_PATTERNS):
        return "rate_limited"
    if any(pattern.fullmatch(normalized) for pattern in _PERMISSION_DENIED_PATTERNS):
        return "permission_denied"
    return "provider_error"


def _reject_non_finite_json_constant(constant: str) -> None:
    raise _ProviderResponseValidationError(
        f"Tushare response contains non-finite JSON constant: {constant}"
    )


def _reject_duplicate_json_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _ProviderResponseValidationError(
                "Tushare response contains duplicate JSON object key"
            )
        result[key] = value
    return result


def _contains_non_finite_float(value: Any) -> bool:
    if isinstance(value, float):
        return not math.isfinite(value)
    if isinstance(value, dict):
        return any(
            _contains_non_finite_float(key) or _contains_non_finite_float(item)
            for key, item in value.items()
        )
    if isinstance(value, (list, tuple)):
        return any(_contains_non_finite_float(item) for item in value)
    return False


def _loads_provider_json(payload: str) -> Any:
    body = json.loads(
        payload,
        parse_constant=_reject_non_finite_json_constant,
        object_pairs_hook=_reject_duplicate_json_keys,
    )
    if _contains_non_finite_float(body):
        raise _ProviderResponseValidationError(
            "Tushare response contains a non-finite number"
        )
    return body


def _strict_provider_response(
    data: Any,
) -> tuple[tuple[str, ...], tuple[dict[str, Any], ...]]:
    if not isinstance(data, dict):
        raise _ProviderResponseValidationError(
            "Tushare response data must be a mapping"
        )
    if _contains_non_finite_float(data):
        raise _ProviderResponseValidationError(
            "Tushare response rows must contain only finite numbers"
        )
    if "fields" not in data or "items" not in data:
        raise _ProviderResponseValidationError(
            "Tushare response data must contain fields and items"
        )

    fields = data["fields"]
    if not isinstance(fields, list) or not fields:
        raise _ProviderResponseValidationError(
            "Tushare response fields must be a non-empty list"
        )
    if any(
        not isinstance(field, str) or _PROVIDER_FIELD_NAME.fullmatch(field) is None
        for field in fields
    ):
        raise _ProviderResponseValidationError(
            "Tushare response fields must contain valid field names"
        )
    if len(set(fields)) != len(fields):
        raise _ProviderResponseValidationError("Tushare response fields must be unique")

    items = data["items"]
    if not isinstance(items, list):
        raise _ProviderResponseValidationError("Tushare response items must be a list")

    rows: list[dict[str, Any]] = []
    for index, row in enumerate(items):
        if not isinstance(row, list):
            raise _ProviderResponseValidationError(
                f"Tushare response row {index} must be a list"
            )
        if len(row) != len(fields):
            raise _ProviderResponseValidationError(
                f"Tushare response row {index} must contain exactly "
                f"{len(fields)} values"
            )
        rows.append(dict(zip(fields, row)))
    return tuple(fields), tuple(rows)


def _strict_provider_rows(data: Any) -> tuple[dict[str, Any], ...]:
    return _strict_provider_response(data)[1]


def _provider_response_metadata(body: Mapping[str, Any]) -> dict[str, Any]:
    """Return every envelope value except the explicit row payload.

    ``data.fields`` and ``data.items`` are the only schema/row contract. Unknown
    sibling keys remain accepted for compatibility, but callers must strictly
    scan them as provider metadata before row conversion ignores them.
    """

    metadata = {key: value for key, value in body.items() if key != "data"}
    data = body.get("data")
    if type(data) is dict:
        data_metadata = {
            key: value for key, value in data.items() if key not in ("fields", "items")
        }
        if data_metadata:
            metadata["data"] = data_metadata
    return metadata


def _validated_api_url(raw_url: object) -> str:
    if type(raw_url) is not str or not raw_url or raw_url != raw_url.strip():
        raise RuntimeError("TUSHARE_API_URL is unavailable")
    parsed = urllib.parse.urlsplit(raw_url)
    try:
        port = parsed.port
    except ValueError:
        raise RuntimeError("TUSHARE_API_URL is invalid") from None
    if (
        parsed.scheme != "https"
        or parsed.hostname != _QUICKSYNC_TUSHARE_HOST
        or parsed.username is not None
        or parsed.password is not None
        or port not in {None, 443}
        or parsed.path != ""
        or bool(parsed.query)
        or bool(parsed.fragment)
    ):
        raise RuntimeError("TUSHARE_API_URL is invalid")
    return QUICKSYNC_TUSHARE_API_URL


def tushare_transport_profile() -> dict[str, object]:
    """Return the public, credential-free transport identity used by receipts."""

    return provider_transport_profile(TUSHARE_DATA_PROVIDER)


def _read_private_token_file(raw_path: object) -> str:
    if type(raw_path) is not str or not raw_path or raw_path != raw_path.strip():
        raise RuntimeError("TUSHARE_TOKEN_FILE is unavailable")
    path = os.path.abspath(raw_path)
    if path != raw_path:
        raise RuntimeError("TUSHARE_TOKEN_FILE must be an absolute canonical path")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError:
        raise RuntimeError("TUSHARE_TOKEN_FILE is unavailable") from None
    try:
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != os.geteuid()
            or metadata.st_nlink != 1
            or stat.S_IMODE(metadata.st_mode) != 0o600
            or metadata.st_size <= 0
            or metadata.st_size > _MAX_TOKEN_FILE_BYTES
        ):
            raise RuntimeError("TUSHARE_TOKEN_FILE ownership or mode is invalid")
        chunks: list[bytes] = []
        remaining = _MAX_TOKEN_FILE_BYTES + 1
        while remaining:
            chunk = os.read(descriptor, remaining)
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b"".join(chunks)
    finally:
        os.close(descriptor)
    if not raw or len(raw) > _MAX_TOKEN_FILE_BYTES:
        raise RuntimeError("TUSHARE_TOKEN_FILE size is invalid")
    try:
        token = raw.decode("utf-8").rstrip("\r\n")
    except UnicodeDecodeError:
        raise RuntimeError("TUSHARE_TOKEN_FILE must contain UTF-8") from None
    if (
        not token
        or token != token.strip()
        or "\n" in token
        or "\r" in token
        or any(ord(character) < 33 or ord(character) == 127 for character in token)
    ):
        raise RuntimeError("TUSHARE_TOKEN_FILE contains an invalid token")
    return token


def read_tushare_config(
    env: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Read the approved API URL and private token owned by this process user."""

    source = os.environ if env is None else env
    return {
        "api_url": _validated_api_url(source.get(TUSHARE_API_URL_ENV)),
        "token": _read_private_token_file(source.get(TUSHARE_TOKEN_FILE_ENV)),
    }


def get_tushare_config() -> dict[str, str]:
    return read_tushare_config()


def get_token() -> str:
    return get_tushare_config()["token"]


def get_api_url() -> str:
    return get_tushare_config()["api_url"]


class _RejectProviderRedirect(urllib.request.HTTPRedirectHandler):
    """Reject redirects so a credential-bearing POST never changes origin."""

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> None:
        del newurl
        raise urllib.error.HTTPError(req.full_url, code, msg, headers, fp)


@dataclass(frozen=True)
class _QuickSyncNode:
    """One address from the current canonical-host DNS snapshot."""

    family: int
    sockaddr: tuple[object, ...]

    @property
    def key(self) -> tuple[int, tuple[object, ...]]:
        return (self.family, self.sockaddr)


class _QuickSyncTransportGateError(RuntimeError):
    """The local account-wide QuickSync request gate rejected this attempt."""


class _QuickSyncRateLimitError(_QuickSyncTransportGateError):
    """The request stayed pre-send because the 200/60s window was full."""


def _quicksync_deadline(timeout: float) -> float:
    if (
        type(timeout) not in {int, float}
        or isinstance(timeout, bool)
        or not math.isfinite(timeout)
        or timeout < 0
    ):
        raise ValueError("QuickSync transport timeout is invalid")
    return time.monotonic() + timeout


def _quicksync_remaining(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("QuickSync request deadline exhausted")
    return remaining


class _QuickSyncTransportLease:
    def __init__(self, gate: _QuickSyncTransportGate) -> None:
        self._gate = gate
        self._released = False
        self._request_started = False
        self._lock = threading.Lock()

    def mark_request_started(self, timeout: float) -> None:
        """Consume one request token immediately before the first HTTP byte."""

        self.mark_request_started_until(_quicksync_deadline(timeout))

    def mark_request_started_until(self, deadline: float) -> None:
        """Consume one request token without extending the caller's deadline."""

        with self._lock:
            if self._released:
                raise RuntimeError("QuickSync transport lease is already released")
            if self._request_started:
                return
            self._gate.mark_request_started_until(deadline)
            self._request_started = True

    def release(self) -> None:
        with self._lock:
            if self._released:
                return
            self._released = True
        self._gate.release()


class _QuickSyncTransportGate:
    """Thread-safe account-wide rate and concurrency gate for real requests."""

    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._request_starts: deque[float] = deque()
        self._in_flight = 0

    @staticmethod
    def _deadline(timeout: float) -> float:
        return _quicksync_deadline(timeout)

    def acquire(self, timeout: float) -> _QuickSyncTransportLease:
        return self.acquire_until(self._deadline(timeout))

    def acquire_until(self, deadline: float) -> _QuickSyncTransportLease:
        with self._condition:
            while self._in_flight >= _QUICKSYNC_MAX_CONCURRENCY:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise _QuickSyncTransportGateError(
                        "QuickSync concurrency wait timed out"
                    )
                self._condition.wait(remaining)
            self._in_flight += 1
        return _QuickSyncTransportLease(self)

    def mark_request_started(self, timeout: float) -> None:
        self.mark_request_started_until(self._deadline(timeout))

    def mark_request_started_until(self, deadline: float) -> None:
        with self._condition:
            while True:
                now = time.monotonic()
                cutoff = now - _QUICKSYNC_REQUEST_WINDOW_SECONDS
                while self._request_starts and self._request_starts[0] <= cutoff:
                    self._request_starts.popleft()
                if now >= deadline:
                    if len(self._request_starts) >= _QUICKSYNC_MAX_REQUESTS:
                        raise _QuickSyncRateLimitError(
                            "QuickSync rate-limit wait timed out"
                        )
                    raise TimeoutError("QuickSync request deadline exhausted")
                if len(self._request_starts) < _QUICKSYNC_MAX_REQUESTS:
                    self._request_starts.append(now)
                    return
                remaining = deadline - now
                if remaining <= 0:
                    raise _QuickSyncRateLimitError(
                        "QuickSync rate-limit wait timed out"
                    )
                next_slot = self._request_starts[0] + _QUICKSYNC_REQUEST_WINDOW_SECONDS
                self._condition.wait(min(remaining, max(0.0, next_slot - now)))

    def release(self) -> None:
        with self._condition:
            if self._in_flight <= 0:
                raise RuntimeError("QuickSync transport lease underflow")
            self._in_flight -= 1
            self._condition.notify()


class _QuickSyncNodeState:
    """Thread-safe last-known-good and cooldown state for DNS snapshot nodes."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._last_known_good: tuple[int, tuple[object, ...]] | None = None
        self._cooldowns: dict[tuple[int, tuple[object, ...]], float] = {}

    def ordered(self, nodes: tuple[_QuickSyncNode, ...]) -> tuple[_QuickSyncNode, ...]:
        now = time.monotonic()
        with self._lock:
            self._cooldowns = {
                key: until for key, until in self._cooldowns.items() if until > now
            }
            live = tuple(node for node in nodes if node.key not in self._cooldowns)
            candidates = live or nodes
            return tuple(
                sorted(
                    candidates,
                    key=lambda node: (
                        0 if node.key == self._last_known_good else 1,
                        nodes.index(node),
                    ),
                )
            )

    def record_success(self, node: _QuickSyncNode) -> None:
        with self._lock:
            self._last_known_good = node.key
            self._cooldowns.pop(node.key, None)

    def record_pre_send_failure(self, node: _QuickSyncNode) -> None:
        with self._lock:
            self._cooldowns[node.key] = (
                time.monotonic() + _QUICKSYNC_NODE_COOLDOWN_SECONDS
            )
            if self._last_known_good == node.key:
                self._last_known_good = None


class _ManagedQuickSyncResponse:
    """Release the transport concurrency lease once the bounded response is read."""

    def __init__(
        self,
        response: Any,
        lease: _QuickSyncTransportLease,
        *,
        prepare_read: Callable[[], None],
    ) -> None:
        self._response = response
        self._lease = lease
        self._prepare_read = prepare_read
        self._closed = False

    def read(self, *args: Any, **kwargs: Any) -> Any:
        try:
            self._prepare_read()
            return self._response.read(*args, **kwargs)
        finally:
            self.close()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            close = getattr(self._response, "close", None)
            if callable(close):
                close()
        finally:
            self._lease.release()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._response, name)

    def __del__(self) -> None:
        self.close()


def _prepare_quicksync_response_read(response: Any, deadline: float) -> None:
    """Refresh the response socket timeout without extending the call deadline."""

    remaining = _quicksync_remaining(deadline)
    if not isinstance(response, http.client.HTTPResponse):
        return
    buffered = getattr(response, "fp", None)
    raw = getattr(buffered, "raw", None)
    response_socket = getattr(raw, "_sock", None)
    if response_socket is None:
        raise RuntimeError("QuickSync response socket is unavailable")
    response_socket.settimeout(remaining)


class _QuickSyncHTTPSConnection(http.client.HTTPSConnection):
    """HTTPS over a DNS-snapshot address while preserving canonical TLS identity."""

    def __init__(
        self,
        host: str,
        *,
        node: _QuickSyncNode,
        context: ssl.SSLContext,
        timeout: float,
        deadline: float,
        on_request_started: Callable[[], None],
    ) -> None:
        super().__init__(host=host, port=443, timeout=timeout, context=context)
        self._quicksync_node = node
        self._quicksync_deadline = deadline
        self._on_request_started = on_request_started
        self.request_started = False
        self.tls_established = False

    def connect(self) -> None:
        raw_socket: socket.socket | None = None
        try:
            raw_socket = socket.socket(
                self._quicksync_node.family,
                socket.SOCK_STREAM,
            )
            raw_socket.settimeout(_quicksync_remaining(self._quicksync_deadline))
            if self.source_address is not None:
                raw_socket.bind(self.source_address)
            raw_socket.connect(self._quicksync_node.sockaddr)
            raw_socket.settimeout(_quicksync_remaining(self._quicksync_deadline))
            self.sock = self._context.wrap_socket(
                raw_socket,
                server_hostname=_QUICKSYNC_TUSHARE_HOST,
            )
            self.sock.settimeout(_quicksync_remaining(self._quicksync_deadline))
            self.tls_established = True
        except Exception:
            if raw_socket is not None:
                raw_socket.close()
            self.sock = None
            raise

    def send(self, data: bytes) -> None:
        if self.sock is None:
            self.connect()
        if not self.request_started:
            self._on_request_started()
        self.request_started = True
        assert self.sock is not None
        self.sock.settimeout(_quicksync_remaining(self._quicksync_deadline))
        self.sock.sendall(data)

    def prepare_response_io(self) -> None:
        """Apply the one-call remaining deadline before header/body reads."""

        if self.sock is None:
            raise RuntimeError("QuickSync connection is unavailable")
        self.sock.settimeout(_quicksync_remaining(self._quicksync_deadline))


_QUICKSYNC_TRANSPORT_GATE = _QuickSyncTransportGate()
_QUICKSYNC_NODE_STATE = _QuickSyncNodeState()


def _resolve_quicksync_nodes() -> tuple[_QuickSyncNode, ...]:
    """Resolve one fresh canonical-host snapshot without storing an IP in code."""

    results = socket.getaddrinfo(
        _QUICKSYNC_TUSHARE_HOST,
        443,
        type=socket.SOCK_STREAM,
    )
    nodes: list[_QuickSyncNode] = []
    seen: set[tuple[int, tuple[object, ...]]] = set()
    for family, socktype, protocol, _canonical_name, sockaddr in results:
        del socktype, protocol
        if family not in {socket.AF_INET, socket.AF_INET6}:
            continue
        node = _QuickSyncNode(family=family, sockaddr=tuple(sockaddr))
        if node.key not in seen:
            seen.add(node.key)
            nodes.append(node)
    if not nodes:
        raise OSError("QuickSync DNS returned no usable address")
    return tuple(nodes)


def _provider_urlopen(
    request: urllib.request.Request,
    *,
    timeout: float,
) -> Any:
    """Open one verified QuickSync request without following redirects."""

    _validated_api_url(request.full_url)
    deadline = _quicksync_deadline(timeout)
    context = ssl.create_default_context()
    context.check_hostname = True
    context.verify_mode = ssl.CERT_REQUIRED
    context.minimum_version = ssl.TLSVersion.TLSv1_3
    context.maximum_version = ssl.TLSVersion.TLSv1_3
    lease = _QUICKSYNC_TRANSPORT_GATE.acquire_until(deadline)
    try:
        parsed = urllib.parse.urlsplit(request.full_url)
        target = parsed.path or "/"
        headers = {
            key: value for key, value in request.header_items() if key.lower() != "host"
        }
        headers["Host"] = _QUICKSYNC_TUSHARE_HOST
        last_error: Exception | None = None
        _quicksync_remaining(deadline)
        nodes = _resolve_quicksync_nodes()
        for node in _QUICKSYNC_NODE_STATE.ordered(nodes):
            remaining = _quicksync_remaining(deadline)
            connection = _QuickSyncHTTPSConnection(
                _QUICKSYNC_TUSHARE_HOST,
                node=node,
                context=context,
                timeout=remaining,
                deadline=deadline,
                on_request_started=lambda: lease.mark_request_started_until(deadline),
            )
            try:
                connection.request(
                    request.get_method(),
                    target,
                    request.data,
                    headers,
                )
                connection.prepare_response_io()
                response = connection.getresponse()
                if connection.tls_established:
                    _QUICKSYNC_NODE_STATE.record_success(node)
                status = getattr(response, "status", None)
                if isinstance(status, int) and status >= 300:
                    response.close()
                    raise urllib.error.HTTPError(
                        request.full_url,
                        status,
                        getattr(response, "reason", "HTTP response rejected"),
                        getattr(response, "headers", None),
                        None,
                    )
                return _ManagedQuickSyncResponse(
                    response,
                    lease,
                    prepare_read=lambda: _prepare_quicksync_response_read(
                        response,
                        deadline,
                    ),
                )
            except _QuickSyncTransportGateError:
                connection.close()
                raise
            except Exception as exc:
                connection.close()
                if connection.tls_established:
                    _QUICKSYNC_NODE_STATE.record_success(node)
                if connection.request_started:
                    raise
                _QUICKSYNC_NODE_STATE.record_pre_send_failure(node)
                last_error = exc
        assert last_error is not None
        raise last_error
    except Exception:
        lease.release()
        raise


def tushare_rows_outcome(
    api_name: str,
    token: str,
    *,
    params: Mapping[str, Any] | None = None,
    fields: str | None = None,
    scan_budget: SensitiveScanBudget | None = None,
    max_response_bytes: int = _DEFAULT_PROVIDER_RESPONSE_BYTES,
    response_observer: Callable[[int, str | None], None] | None = None,
) -> ProviderCallOutcome:
    """Call Tushare once and preserve success, empty, and failure truth."""

    provider_code: int | str | None = None
    sensitive_values = (token,)
    if (
        type(max_response_bytes) is not int
        or max_response_bytes <= 0
        or max_response_bytes > _MAX_PROVIDER_RESPONSE_BYTES
    ):
        return ProviderCallOutcome(
            state="failed",
            rows=(),
            provider_code=None,
            error_code="resource_budget",
            error_message="provider response byte budget is invalid",
            sensitive_values=sensitive_values,
            scan_budget=scan_budget,
        )
    try:
        request_payload = {
            "api_name": api_name,
            "token": token,
            "params": dict(params or {}),
        }
        if fields:
            request_payload["fields"] = fields
        payload = json.dumps(request_payload).encode("utf-8")
        request = urllib.request.Request(
            get_api_url(),
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        response_payload = _provider_urlopen(request, timeout=30).read(
            max_response_bytes + 1
        )
    except _QuickSyncRateLimitError:
        return ProviderCallOutcome(
            state="failed",
            rows=(),
            provider_code=None,
            error_code="rate_limited",
            error_message="QuickSync local request rate limit reached",
            sensitive_values=sensitive_values,
            scan_budget=scan_budget,
        )
    except Exception as exc:
        return ProviderCallOutcome(
            state="failed",
            rows=(),
            provider_code=None,
            error_code="transport_error",
            error_message=safe_provider_exception_message(exc),
            sensitive_values=sensitive_values,
            scan_budget=scan_budget,
        )

    response_observer_called = False
    if len(response_payload) > max_response_bytes:
        if response_observer is not None:
            response_observer_called = True
            try:
                response_observer(len(response_payload), None)
            except Exception:
                pass
        return ProviderCallOutcome(
            state="failed",
            rows=(),
            provider_code=None,
            error_code="resource_budget",
            error_message="provider response exceeded byte budget",
            sensitive_values=sensitive_values,
            scan_budget=scan_budget,
        )

    try:
        body = _loads_provider_json(response_payload.decode("utf-8"))
        if not isinstance(body, dict):
            raise _ProviderResponseValidationError("Tushare response must be a mapping")

        raw_provider_code = body.get("code")
        provider_code = (
            raw_provider_code
            if isinstance(raw_provider_code, (int, str))
            and not isinstance(raw_provider_code, bool)
            else None
        )
        provider_metadata = _provider_response_metadata(body)
        response_contains_credentials = (
            _contains_structured_credential(
                body,
                scan_budget=scan_budget,
            )
            or _contains_sensitive_value(
                body,
                sensitive_values,
                scan_budget=scan_budget,
            )
            or _contains_provider_metadata_credential(
                provider_metadata,
                scan_budget=scan_budget,
            )
        )
        response_sha256 = (
            None
            if response_contains_credentials
            else hashlib.sha256(response_payload).hexdigest()
        )
        if response_observer is not None:
            response_observer_called = True
            try:
                response_observer(len(response_payload), response_sha256)
            except Exception:
                pass
        if provider_code not in (0, "0"):
            raw_message = body.get("msg")
            safe_message, diagnostic_trusted = _guard_provider_diagnostic(
                raw_message,
                sensitive_values=sensitive_values,
                scan_budget=scan_budget,
            )
            safe_provider_code = _sanitize_provider_code(
                provider_code,
                sensitive_values,
                scan_budget=scan_budget,
            )
            classified_error_code = "provider_error"
            if diagnostic_trusted and safe_provider_code != _UNTRUSTED_PROVIDER_CODE:
                classified_error_code = _provider_error_code(
                    safe_provider_code,
                    safe_message,
                )
            return ProviderCallOutcome(
                state="failed",
                rows=(),
                provider_code=safe_provider_code,
                error_code=_sanitize_error_code(
                    classified_error_code,
                    sensitive_values,
                    scan_budget=scan_budget,
                ),
                error_message=safe_message,
                sensitive_values=sensitive_values,
                scan_budget=scan_budget,
            )

        if response_contains_credentials:
            raise _ProviderResponseValidationError(_redacted_diagnostic_summary())
        if "data" not in body:
            raise _ProviderResponseValidationError("Tushare response must contain data")
        response_fields, rows = _strict_provider_response(body["data"])
        return ProviderCallOutcome(
            state="success" if rows else "empty",
            rows=rows,
            provider_code=_sanitize_provider_code(
                provider_code,
                sensitive_values,
                scan_budget=scan_budget,
            ),
            error_code=None,
            error_message=None,
            response_fields=response_fields,
            sensitive_values=sensitive_values,
            scan_budget=scan_budget,
        )
    except Exception as exc:
        if response_observer is not None and not response_observer_called:
            try:
                response_observer(len(response_payload), None)
            except Exception:
                pass
        return ProviderCallOutcome(
            state="failed",
            rows=(),
            provider_code=_sanitize_provider_code(
                provider_code,
                sensitive_values,
                scan_budget=scan_budget,
            ),
            error_code="provider_error",
            error_message=_safe_provider_response_error_message(exc),
            sensitive_values=sensitive_values,
            scan_budget=scan_budget,
        )

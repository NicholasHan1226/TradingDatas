#!/usr/bin/env python3
"""Shared helpers for the SharedSignals Tushare collectors."""

from __future__ import annotations

import json
import math
import os
import re
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterable as IterableABC
from collections.abc import Mapping as MappingABC
from dataclasses import InitVar, dataclass, field
from datetime import datetime
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal, Mapping

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    try:
        import tomli as tomllib
    except ModuleNotFoundError:  # pragma: no cover
        tomllib = None

# Codex config is the canonical source for Tushare/QuickSync token and API URL.
# Environment variables (QUICKSYNC_TOKEN, QUICKSYNC_API_URL, etc.) can be used
# as an optional override; set them when you need to temporarily switch provider.
CONFIG = Path.home() / ".codex" / "config.toml"
DEFAULT_API_URL = "https://api.tushare.pro"
QUICKSYNC_API_URL = "https://api.quicksync.cn"
_TUSHARE_CONFIG_CACHE: dict[str, str] | None = None

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
                0x10000
                + ((code_unit - 0xD800) << 10)
                + (low_surrogate - 0xDC00)
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
            if (
                len(encoded) != width
                or any(digit not in _HEX_DIGITS for digit in encoded)
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
            forms.update(
                view
                for view in _diagnostic_views(text, scan_budget=budget)
                if view
            )
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
    candidates: list[str] = []
    for view in _diagnostic_views(value, scan_budget=scan_budget):
        stripped = view.strip()
        candidates.append(stripped)
        without_format_controls = "".join(
            character
            for character in stripped
            if unicodedata.category(character) != "Cf"
        )
        if without_format_controls != stripped:
            candidates.append(without_format_controls)
    return tuple(candidates)


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


@dataclass(frozen=True)
class ProviderCallOutcome:
    """Provider truth preserved before compatibility row conversion."""

    state: Literal["success", "empty", "failed"]
    rows: tuple[Mapping[str, Any], ...]
    provider_code: int | str | None
    error_code: str | None
    error_message: str | None
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
        if _contains_structured_credential(
            frozen_rows,
            scan_budget=budget,
        ) or _contains_sensitive_value(
            frozen_rows,
            guarded_values,
            scan_budget=budget,
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
            not diagnostic_trusted
            or provider_code == _UNTRUSTED_PROVIDER_CODE
        ):
            error_code = "provider_error"
        object.__setattr__(self, "provider_code", provider_code)
        object.__setattr__(self, "error_code", error_code)
        object.__setattr__(self, "error_message", error_message)
        self.validate_invariants()

    def validate_invariants(self) -> None:
        if self.state not in ("success", "empty", "failed"):
            raise ValueError("provider outcome has an invalid state")
        if self.state == "success" and not self.rows:
            raise ValueError("provider outcome success requires non-empty rows")
        if self.state in ("empty", "failed") and self.rows:
            raise ValueError(f"provider outcome {self.state} must not contain rows")
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
    (None, "provider_error", "rate_limited", "permission_denied")
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
        not diagnostic_trusted
        or provider_code == _UNTRUSTED_PROVIDER_CODE
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


_CLASSIFIABLE_PROVIDER_CODES = frozenset((-2001, "-2001"))
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
_PROVIDER_FIELD_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


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


def _strict_provider_rows(data: Any) -> tuple[dict[str, Any], ...]:
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
        raise _ProviderResponseValidationError(
            "Tushare response fields must be unique"
        )

    items = data["items"]
    if not isinstance(items, list):
        raise _ProviderResponseValidationError(
            "Tushare response items must be a list"
        )

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
    return tuple(rows)


def _parse_tushare_url(raw_url: str) -> dict[str, str]:
    parsed = urllib.parse.urlparse(raw_url)
    token = urllib.parse.parse_qs(parsed.query).get("token", [""])[0]
    if not token and "token=" in raw_url:
        token = raw_url.split("token=", 1)[1].split("&", 1)[0]
    api_url = urllib.parse.urlunparse(parsed._replace(query="", fragment="")).rstrip("/")
    return {"api_url": api_url or DEFAULT_API_URL, "token": token}


def _read_tushare_config_from_env(env: Mapping[str, str]) -> dict[str, str] | None:
    url_keys = ("TUSHARE_MCP_URL", "TUSHARE_API_URL", "QUICKSYNC_API_URL", "QUICKSYNC_URL")
    token_keys = ("TUSHARE_TOKEN", "TUSHARE_API_TOKEN", "QUICKSYNC_TOKEN", "QUICKSYNC_API_TOKEN")
    raw_url = next((str(env.get(key) or "") for key in url_keys if env.get(key)), "")
    token = next((str(env.get(key) or "") for key in token_keys if env.get(key)), "")
    if raw_url and "token=" in raw_url:
        parsed = _parse_tushare_url(raw_url)
        if parsed["token"]:
            return parsed
    if token:
        api_url = raw_url.rstrip("/") if raw_url else (
            QUICKSYNC_API_URL if any(env.get(key) for key in ("QUICKSYNC_TOKEN", "QUICKSYNC_API_TOKEN")) else DEFAULT_API_URL
        )
        return {"api_url": api_url, "token": token}
    return None


def _read_tushare_config_from_codex(path: Path = CONFIG) -> dict[str, str]:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    if tomllib is not None:
        try:
            with path.open("rb") as handle:
                config = tomllib.load(handle)
            raw_url = (
                config.get("mcp_servers", {})
                .get("tushareMcp", {})
                .get("url", "")
            )
            if raw_url and "token=" in raw_url:
                parsed = _parse_tushare_url(raw_url)
                if parsed["token"]:
                    return parsed
        except Exception:
            pass  # fall through to regex fallback
    match = re.search(r"\[mcp_servers\.tushareMcp\][\s\S]*?url\s*=\s*\"([^\"]+)\"", text)
    if not match or "token=" not in match.group(1):
        raise RuntimeError("Tushare token not found in Codex config")
    return _parse_tushare_url(match.group(1))


def decode_cn_quote_bytes(data: bytes) -> str:
    """Decode Chinese market quote payloads without letting codec drift break workflows."""
    for encoding in ("gbk", "gb18030", "gb2312", "utf-8", "latin-1"):
        try:
            return data.decode(encoding, "ignore")
        except LookupError:
            continue
    return data.decode("latin-1", "ignore")


def read_tushare_config() -> dict[str, str]:
    """Read Tushare/QuickSync config: codex config.toml is canonical;
    environment variables can be used as an optional override."""
    env_config = _read_tushare_config_from_env(os.environ)
    if env_config:
        return env_config
    return _read_tushare_config_from_codex(CONFIG)


def read_token() -> str:
    return read_tushare_config()["token"]


def get_tushare_config() -> dict[str, str]:
    global _TUSHARE_CONFIG_CACHE
    if _TUSHARE_CONFIG_CACHE is None:
        _TUSHARE_CONFIG_CACHE = read_tushare_config()
    return _TUSHARE_CONFIG_CACHE


def get_token() -> str:
    return get_tushare_config()["token"]


def get_api_url() -> str:
    return get_tushare_config()["api_url"]


def tushare_data(
    api_name: str,
    params: dict[str, Any] | None = None,
    fields: str = "",
    *,
    retries: int = 3,
    strict: bool = True,
    timeout: float = 30,
) -> dict[str, Any]:
    payload = json.dumps(
        {"api_name": api_name, "token": get_token(), "params": params or {}, "fields": fields}
    ).encode("utf-8")
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        req = urllib.request.Request(
            get_api_url(),
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            body = _loads_provider_json(
                urllib.request.urlopen(req, timeout=timeout).read().decode("utf-8")
            )
            if body.get("code") != 0:
                if not strict:
                    return {"fields": [], "items": [], "error": body.get("msg", ""), "code": body.get("code")}
                raise RuntimeError(body.get("msg", "Tushare request failed"))
            return body.get("data") or {"fields": [], "items": []}
        except Exception as exc:
            last_error = exc
            if attempt < retries:
                time.sleep(0.4 * attempt)
    if strict:
        raise RuntimeError(str(last_error))
    return {"fields": [], "items": [], "error": str(last_error), "code": "local_error"}


def rows_to_dicts(data: dict[str, Any]) -> list[dict[str, Any]]:
    fields = data.get("fields") or []
    return [dict(zip(fields, row)) for row in data.get("items") or []]


def tushare_rows_outcome(
    api_name: str,
    token: str,
    *,
    params: Mapping[str, Any] | None = None,
    fields: str = "",
    scan_budget: SensitiveScanBudget | None = None,
) -> ProviderCallOutcome:
    """Call Tushare once and preserve success, empty, and failure truth."""

    provider_code: int | str | None = None
    sensitive_values = (token,)
    try:
        payload = json.dumps(
            {
                "api_name": api_name,
                "token": token,
                "params": dict(params or {}),
                "fields": fields,
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            get_api_url(),
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        response_payload = urllib.request.urlopen(request, timeout=30).read()
    except Exception as exc:
        return ProviderCallOutcome(
            state="failed",
            rows=(),
            provider_code=None,
            error_code="provider_error",
            error_message=safe_provider_exception_message(exc),
            sensitive_values=sensitive_values,
            scan_budget=scan_budget,
        )

    try:
        body = _loads_provider_json(response_payload.decode("utf-8"))
        if not isinstance(body, dict):
            raise _ProviderResponseValidationError(
                "Tushare response must be a mapping"
            )

        raw_provider_code = body.get("code")
        provider_code = (
            raw_provider_code
            if isinstance(raw_provider_code, (int, str))
            and not isinstance(raw_provider_code, bool)
            else None
        )
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
            if (
                diagnostic_trusted
                and safe_provider_code != _UNTRUSTED_PROVIDER_CODE
            ):
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

        provider_metadata = {
            key: value for key, value in body.items() if key != "data"
        }
        if _contains_structured_credential(
            body,
            scan_budget=scan_budget,
        ) or _contains_sensitive_value(
            body,
            sensitive_values,
            scan_budget=scan_budget,
        ) or _contains_provider_metadata_credential(
            provider_metadata,
            scan_budget=scan_budget,
        ):
            raise _ProviderResponseValidationError(
                _redacted_diagnostic_summary()
            )
        if "data" not in body:
            raise _ProviderResponseValidationError(
                "Tushare response must contain data"
            )
        rows = _strict_provider_rows(body["data"])
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
            sensitive_values=sensitive_values,
            scan_budget=scan_budget,
        )
    except Exception as exc:
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


def tushare_rows(
    api_name: str,
    params: dict[str, Any] | None = None,
    fields: str = "",
    *,
    retries: int = 3,
    strict: bool = True,
    timeout: float = 30,
) -> list[dict[str, Any]]:
    return rows_to_dicts(tushare_data(api_name, params, fields, retries=retries, strict=strict, timeout=timeout))


def to_float(value: Any, default: float = 0.0, *, strict: bool = False) -> float:
    try:
        if value is None or value == "":
            if strict:
                raise ValueError(f"Cannot convert {value!r} to float")
            return default
        return float(value)
    except (TypeError, ValueError) as exc:
        if strict:
            raise ValueError(f"Cannot convert {value!r} to float") from exc
        return default


def today_yyyymmdd() -> str:
    return datetime.now().strftime("%Y%m%d")


def latest_trade_date(end_date: str | None = None) -> str:
    end = end_date or today_yyyymmdd()
    start = str(int(end[:4]) - 1) + end[4:]
    rows = tushare_rows("trade_cal", {"exchange": "", "start_date": start, "end_date": end}, "cal_date,is_open")
    dates = sorted(str(row["cal_date"]) for row in rows if str(row.get("is_open")) == "1")
    if not dates:
        raise RuntimeError("No open trade date found")
    return dates[-1]


def previous_trade_date(before_date: str) -> str | None:
    """Return the latest trade date strictly before `before_date`.

    Uses Tushare trade_cal to find the most recent open day.
    Returns None if no earlier trade date is found.
    """
    start = str(int(before_date[:4]) - 1) + before_date[4:]
    rows = tushare_rows("trade_cal", {"exchange": "", "start_date": start, "end_date": before_date}, "cal_date,is_open")
    dates = sorted(str(row["cal_date"]) for row in rows if str(row.get("is_open")) == "1")
    # Return the last date that is strictly before `before_date`
    for date in reversed(dates):
        if date < before_date:
            return date
    return None


def next_trade_date(after_date: str) -> str | None:
    end_year = str(int(after_date[:4]) + 1) + after_date[4:]
    rows = tushare_rows("trade_cal", {"exchange": "", "start_date": after_date, "end_date": end_year}, "cal_date,is_open")
    dates = sorted(str(row["cal_date"]) for row in rows if str(row.get("is_open")) == "1")
    for date in dates:
        if date > after_date:
            return date
    return None


def normalize_code(raw: str) -> str:
    text = raw.strip()
    if re.fullmatch(r"\d{6}\.(SH|SZ|BJ)", text, flags=re.I):
        code, suffix = text.split(".")
        return f"{code}.{suffix.upper()}"
    if re.fullmatch(r"(sh|sz|bj)\d{6}", text, flags=re.I):
        suffix = text[:2].upper()
        return f"{text[-6:]}.{suffix}"
    if re.fullmatch(r"\d{6}", text):
        if text.startswith(("6", "5")):
            return f"{text}.SH"
        if text.startswith(("8", "4", "9")):
            return f"{text}.BJ"
        return f"{text}.SZ"
    raise ValueError(f"Unsupported stock code: {raw}")


def to_tencent_symbol(ts_code: str) -> str:
    code = normalize_code(ts_code)
    number, suffix = code.split(".")
    return suffix.lower() + number


def daily_map(trade_date: str) -> dict[str, dict[str, Any]]:
    rows = tushare_rows(
        "daily",
        {"trade_date": trade_date},
        "ts_code,trade_date,open,high,low,close,pre_close,pct_chg,amount",
    )
    return {row["ts_code"]: row for row in rows}


def safe_round(value: Any, digits: int = 2) -> float:
    return round(to_float(value), digits)

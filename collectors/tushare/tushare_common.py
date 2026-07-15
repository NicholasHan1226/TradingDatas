#!/usr/bin/env python3
"""Shared helpers for the SharedSignals Tushare collectors."""

from __future__ import annotations

import json
import math
import os
import re
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
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
_URL_PATTERN = re.compile(
    r"\b[A-Za-z][A-Za-z0-9+.-]*://[^\s<>\"']+",
)
_COOKIE_HEADER_PATTERN = re.compile(
    r"(?P<prefix>\b(?:set-cookie|cookie)\s*:\s*)(?P<value>[^\r\n]+)",
    re.IGNORECASE,
)
_CREDENTIAL_FIELD_PATTERN = (
    r"(?:access[_ -]?token|refresh[_ -]?token|id[_ -]?token|token|"
    r"api[_ -]?key|password|passwd|credential(?:s)?|"
    r"client[_ -]?secret|secret|cookie|set[_ -]?cookie)"
)
_AUTHORIZATION_VALUE_PATTERN = re.compile(
    r"""
    (?P<prefix>
        (?<![A-Za-z0-9_])
        (?P<key_quote>["']?)authorization(?P=key_quote)\s*[:=]\s*
    )
    (?P<value_quote>["']?)
    (?:(?P<scheme>bearer|basic)\s+)?
    (?P<credential>
        (?!\[REDACTED\])
        [^"'\s,;&}<>)\]]+
    )
    (?P=value_quote)
    """,
    re.IGNORECASE | re.VERBOSE,
)
_QUOTED_CREDENTIAL_VALUE_PATTERN = re.compile(
    r"""
    (?P<prefix>
        (?<![A-Za-z0-9_])
        (?P<key_quote>["']?)
        """
    + _CREDENTIAL_FIELD_PATTERN
    + r"""
        (?P=key_quote)\s*[:=]\s*
    )
    (?P<value_quote>["'])
    (?P<credential>(?!\[REDACTED\]).*?)
    (?P=value_quote)
    """,
    re.IGNORECASE | re.VERBOSE,
)
_UNQUOTED_CREDENTIAL_VALUE_PATTERN = re.compile(
    r"""
    (?P<prefix>
        (?<![A-Za-z0-9_])
        (?P<key_quote>["']?)
        """
    + _CREDENTIAL_FIELD_PATTERN
    + r"""
        (?P=key_quote)
        \s*[:=]\s*
    )
    (?P<credential>
        (?!\[REDACTED\])
        [^"'\s,;&}<>)\]]+
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)
_BEARER_VALUE_PATTERN = re.compile(
    r"(?P<prefix>\bbearer\s+)(?P<credential>(?!\[REDACTED\])[^\"'\s,;&}<>)\]]+)",
    re.IGNORECASE,
)


def _redact_sensitive_text(message: str) -> str:
    """Remove credential values before an error can cross an outcome boundary."""

    decoded = message
    for _ in range(len(message) + 1):
        next_decoded = urllib.parse.unquote(decoded)
        if next_decoded == decoded:
            break
        decoded = next_decoded

    def _redact_url(match: re.Match[str]) -> str:
        raw_url = match.group(0)
        try:
            parsed = urllib.parse.urlsplit(raw_url)
        except ValueError:
            return _REDACTION_MARKER
        netloc = parsed.netloc
        if parsed.username is not None or parsed.password is not None:
            netloc = f"{_REDACTION_MARKER}@{netloc.rsplit('@', 1)[-1]}"
        return urllib.parse.urlunsplit(
            (
                parsed.scheme,
                netloc,
                parsed.path,
                _REDACTION_MARKER if parsed.query else "",
                _REDACTION_MARKER if parsed.fragment else "",
            )
        )

    def _redact_authorization(match: re.Match[str]) -> str:
        scheme = match.group("scheme")
        scheme_prefix = f"{scheme} " if scheme else ""
        quote = match.group("value_quote")
        return (
            f"{match.group('prefix')}{quote}{scheme_prefix}{_REDACTION_MARKER}{quote}"
        )

    def _redact_quoted(match: re.Match[str]) -> str:
        quote = match.group("value_quote")
        return f"{match.group('prefix')}{quote}{_REDACTION_MARKER}{quote}"

    def _redact_unquoted(match: re.Match[str]) -> str:
        return f"{match.group('prefix')}{_REDACTION_MARKER}"

    redacted = _URL_PATTERN.sub(_redact_url, decoded)
    redacted = _COOKIE_HEADER_PATTERN.sub(
        lambda match: f"{match.group('prefix')}{_REDACTION_MARKER}",
        redacted,
    )
    redacted = _AUTHORIZATION_VALUE_PATTERN.sub(_redact_authorization, redacted)
    redacted = _QUOTED_CREDENTIAL_VALUE_PATTERN.sub(_redact_quoted, redacted)
    redacted = _UNQUOTED_CREDENTIAL_VALUE_PATTERN.sub(_redact_unquoted, redacted)
    return _BEARER_VALUE_PATTERN.sub(_redact_unquoted, redacted)


@dataclass(frozen=True)
class ProviderCallOutcome:
    """Provider truth preserved before compatibility row conversion."""

    state: Literal["success", "empty", "failed"]
    rows: tuple[dict[str, Any], ...]
    provider_code: int | str | None
    error_code: str | None
    error_message: str | None

    def __post_init__(self) -> None:
        if self.error_message is not None:
            object.__setattr__(
                self,
                "error_message",
                _redact_sensitive_text(str(self.error_message)),
            )
        self.validate_invariants()

    def validate_invariants(self) -> None:
        if self.state not in ("success", "empty", "failed"):
            raise ValueError("provider outcome has an invalid state")
        if self.state == "success" and not self.rows:
            raise ValueError("provider outcome success requires non-empty rows")
        if self.state in ("empty", "failed") and self.rows:
            raise ValueError(f"provider outcome {self.state} must not contain rows")


_SAFE_PROVIDER_CODE = re.compile(r"-?(?:0|[1-9][0-9]{0,15})")
_SAFE_ERROR_CODES = frozenset(
    (None, "provider_error", "rate_limited", "permission_denied")
)


def provider_outcome_log_fields(outcome: ProviderCallOutcome) -> dict[str, Any]:
    """Return diagnostic outcome fields with no untrusted log arguments."""

    raw_provider_code = outcome.provider_code
    if raw_provider_code is None or type(raw_provider_code) is int:
        provider_code: int | str | None = raw_provider_code
    elif isinstance(raw_provider_code, str) and _SAFE_PROVIDER_CODE.fullmatch(
        raw_provider_code
    ):
        provider_code = raw_provider_code
    else:
        provider_code = "<untrusted-provider-code>"

    error_code = (
        outcome.error_code
        if outcome.error_code in _SAFE_ERROR_CODES
        else "<untrusted-error-code>"
    )
    state = (
        outcome.state
        if outcome.state in ("success", "empty", "failed")
        else "<invalid-outcome-state>"
    )
    error_message = (
        _redact_sensitive_text(str(outcome.error_message))
        if outcome.error_message is not None
        else None
    )
    return {
        "state": state,
        "provider_code": provider_code,
        "error_code": error_code,
        "error_message": error_message,
    }


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
    raise ValueError(f"Tushare response contains non-finite JSON constant: {constant}")


def _reject_duplicate_json_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Tushare response contains duplicate JSON object key")
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
        raise ValueError("Tushare response contains a non-finite number")
    return body


def _strict_provider_rows(data: Any) -> tuple[dict[str, Any], ...]:
    if not isinstance(data, dict):
        raise ValueError("Tushare response data must be a mapping")
    if _contains_non_finite_float(data):
        raise ValueError("Tushare response rows must contain only finite numbers")
    if "fields" not in data or "items" not in data:
        raise ValueError("Tushare response data must contain fields and items")

    fields = data["fields"]
    if not isinstance(fields, list) or not fields:
        raise ValueError("Tushare response fields must be a non-empty list")
    if any(
        not isinstance(field, str) or _PROVIDER_FIELD_NAME.fullmatch(field) is None
        for field in fields
    ):
        raise ValueError("Tushare response fields must contain valid field names")
    if len(set(fields)) != len(fields):
        raise ValueError("Tushare response fields must be unique")

    items = data["items"]
    if not isinstance(items, list):
        raise ValueError("Tushare response items must be a list")

    rows: list[dict[str, Any]] = []
    for index, row in enumerate(items):
        if not isinstance(row, list):
            raise ValueError(f"Tushare response row {index} must be a list")
        if len(row) != len(fields):
            raise ValueError(
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
) -> ProviderCallOutcome:
    """Call Tushare once and preserve success, empty, and failure truth."""

    provider_code: int | str | None = None
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
        body = _loads_provider_json(
            urllib.request.urlopen(request, timeout=30).read().decode("utf-8")
        )
        if not isinstance(body, dict):
            raise ValueError("Tushare response must be a mapping")

        raw_provider_code = body.get("code")
        provider_code = (
            raw_provider_code
            if isinstance(raw_provider_code, (int, str))
            and not isinstance(raw_provider_code, bool)
            else None
        )
        if provider_code not in (0, "0"):
            message = str(body.get("msg") or "Tushare request failed")
            return ProviderCallOutcome(
                state="failed",
                rows=(),
                provider_code=provider_code,
                error_code=_provider_error_code(provider_code, message),
                error_message=message,
            )

        if "data" not in body:
            raise ValueError("Tushare response must contain data")
        rows = _strict_provider_rows(body["data"])
        return ProviderCallOutcome(
            state="success" if rows else "empty",
            rows=rows,
            provider_code=provider_code,
            error_code=None,
            error_message=None,
        )
    except Exception as exc:
        return ProviderCallOutcome(
            state="failed",
            rows=(),
            provider_code=provider_code,
            error_code="provider_error",
            error_message=str(exc) or exc.__class__.__name__,
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

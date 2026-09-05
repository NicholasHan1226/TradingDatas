"""Firecrawl web-extraction provider adapter for the frozen news contract.

The adapter deliberately implements only the two allowlisted read APIs:
``scrape_page`` (``POST /v2/scrape`` with a registry-pinned JSON extraction
contract) and ``search_news`` (``POST /v2/search`` restricted to the ``news``
source).  There is no crawl/interact surface and no markdown/rawHtml retention:
production requests only declare structured JSON extraction, so the provider
payload is already the structured row material preserved losslessly.

Provider-neutral normalization is frozen to exactly two transformations:

1. ``published_at`` is normalized to RFC3339 with the Asia/Shanghai offset, and
   the partition field ``event_date`` (yyyymmdd) plus the windowed-completeness
   field ``published_local`` (``%Y-%m-%d %H:%M:%S`` Asia/Shanghai) are derived
   from the same parsed timestamp.
2. ``content_uid`` = sha256(canonical_url | title | published_at) is derived as
   the primary-key component and re-scan dedup identity.

Only ``scrape_page_global`` may explicitly enable ``raw_item_v1`` provenance.
It preserves the original item and publication text/precision alongside the
unchanged legacy anchors; date/time anchors do not prove publication instants.

The bearer key is read from ``FIRECRAWL_API_KEY_FILE`` (0600, outside the
repository) and is never placed into payloads, receipts, or log fields; every
outcome carries it as a sensitive value so the shared tushare_common scan
machinery fail-closes on any leak.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, datetime, timedelta
import hashlib
import json
import os
import re
import stat
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from zoneinfo import ZoneInfo

from collectors.tushare.tushare_common import (
    ProviderCallOutcome,
    SensitiveScanBudget,
    safe_provider_exception_message,
)
from provider_transport import FIRECRAWL_API_URL


FIRECRAWL_API_KEY_FILE_ENV = "FIRECRAWL_API_KEY_FILE"
_LOCAL_TIMEZONE = ZoneInfo("Asia/Shanghai")
_GLOBAL_TIMEZONE = ZoneInfo("America/New_York")
_MAX_KEY_FILE_BYTES = 4_096
_MAX_RESPONSE_BYTES = 16 * 1024 * 1024
_MAX_TIMEOUT_MS = 120_000
_MAX_AGE_MS_LIMIT = 86_400_000
_MAX_SEARCH_LIMIT = 100
_MAX_QUERY_CHARS = 500
_SCRAPE_PARAM_KEYS = frozenset(
    {
        "url",
        "extraction_schema",
        "prompt",
        "max_age_ms",
        "timeout_ms",
        "window_start",
        "window_end",
        "publication_provenance_mode",
    }
)
_SEARCH_PARAM_KEYS = frozenset({"query", "limit", "timeout_ms"})
_SEARCH_SOURCE_LABEL = "firecrawl.search_news"
_UPSTREAM_TIMEOUT_MARKERS = ("timeout", "timed out")
_UPSTREAM_REFUSAL_MARKERS = (
    "401",
    "403",
    "forbidden",
    "unauthorized",
    "captcha",
    "blocked",
)


class _FirecrawlLocalFailure(ValueError):
    """A local validation phase failed; never retain the original exception."""

    def __init__(self, safe_message: str) -> None:
        super().__init__(safe_message)
        self.safe_message = safe_message


@contextmanager
def _diagnostic_phase(safe_message: str) -> Iterator[None]:
    # Call sites pass literals, never provider data, paths or exception text.
    # These scopes contain only local validation, never provider requests.
    try:
        yield
    except Exception:
        raise _FirecrawlLocalFailure(safe_message) from None


def _safe_upstream_failure_message(payload: object) -> str:
    """Classify a firecrawl failure envelope without retaining its raw text.

    The upstream error string may embed arbitrary target-page content, so only
    whitelisted markers may select a fixed diagnostic; everything else stays
    generic and the original text never reaches logs or receipts.
    """
    error = payload.get("error") if isinstance(payload, dict) else None
    text = error.lower() if type(error) is str else ""
    if any(marker in text for marker in _UPSTREAM_TIMEOUT_MARKERS):
        return "firecrawl upstream extraction timed out"
    if any(marker in text for marker in _UPSTREAM_REFUSAL_MARKERS):
        return "firecrawl upstream extraction refused by the target site"
    return "firecrawl upstream extraction failed"


class _FirecrawlUpstreamFailure(ValueError):
    """Envelope-level upstream failure carrying only a fixed diagnostic."""

    def __init__(self, safe_message: str) -> None:
        super().__init__(safe_message)
        self.safe_message = safe_message


class _RejectRedirects(HTTPRedirectHandler):
    """Keep the credential-bearing origin pinned to the frozen endpoint."""

    def redirect_request(
        self,
        req: Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> Request | None:
        del req, fp, code, msg, headers, newurl
        raise OSError("firecrawl redirect rejected")


_OPENER = build_opener(_RejectRedirects)


def _read_private_key_file(raw_path: object) -> str:
    if type(raw_path) is not str or not raw_path or raw_path != raw_path.strip():
        raise RuntimeError("FIRECRAWL_API_KEY_FILE is unavailable")
    path = os.path.abspath(raw_path)
    if path != raw_path:
        raise RuntimeError("FIRECRAWL_API_KEY_FILE must be an absolute canonical path")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError:
        raise RuntimeError("FIRECRAWL_API_KEY_FILE is unavailable") from None
    try:
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != os.geteuid()
            or metadata.st_nlink != 1
            or stat.S_IMODE(metadata.st_mode) != 0o600
            or metadata.st_size <= 0
            or metadata.st_size > _MAX_KEY_FILE_BYTES
        ):
            raise RuntimeError("FIRECRAWL_API_KEY_FILE ownership or mode is invalid")
        raw = os.read(descriptor, _MAX_KEY_FILE_BYTES + 1)
    finally:
        os.close(descriptor)
    if not raw or len(raw) > _MAX_KEY_FILE_BYTES:
        raise RuntimeError("FIRECRAWL_API_KEY_FILE size is invalid")
    try:
        key = raw.decode("utf-8").rstrip("\r\n")
    except UnicodeDecodeError:
        raise RuntimeError("FIRECRAWL_API_KEY_FILE must contain UTF-8") from None
    if (
        not key
        or key != key.strip()
        or "\n" in key
        or "\r" in key
        or any(ord(character) < 33 or ord(character) == 127 for character in key)
    ):
        raise RuntimeError("FIRECRAWL_API_KEY_FILE contains an invalid key")
    return key


def _bounded_int(value: object, name: str, *, minimum: int, maximum: int) -> int:
    # Registry request_template values arrive as strings; request_variants may
    # carry native JSON scalars.  Accept a plain decimal string or an int.
    if type(value) is str:
        if re.fullmatch(r"[0-9]{1,9}", value) is None:
            raise ValueError(f"firecrawl {name} is outside the frozen bounds")
        value = int(value)
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f"firecrawl {name} is outside the frozen bounds")
    return value


def _non_empty_text(value: object, name: str, *, max_chars: int) -> str:
    if (
        type(value) is not str
        or not value
        or value != value.strip()
        or len(value) > max_chars
    ):
        raise ValueError(f"firecrawl {name} is invalid")
    return value


def _canonical_url(value: object) -> str:
    text = _non_empty_text(value, "url", max_chars=2048)
    parsed = urlsplit(text)
    # Chinese financial feeds mix https article links with http announcement
    # PDFs; both are ordinary web data.  Reject only malformed or non-web
    # schemes (relative, javascript:, etc.) and keep the string as-is.
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("firecrawl url must be an absolute http(s) URL")
    return parsed._replace(fragment="").geturl()


def _parse_published_at(
    value: object,
    *,
    timezone: ZoneInfo = _LOCAL_TIMEZONE,
    observed_at: datetime | None = None,
) -> datetime:
    if type(value) is not str or not value.strip():
        raise ValueError("firecrawl item is missing a parseable published time")
    text = value.strip()
    # Chinese financial list pages commonly emit dotted dates
    # ("2026.08.16 03:55:29") rather than ISO-8601.  Accept ISO-8601 and
    # the dotted local-date form; everything else still fails closed.
    candidates = (text, text.replace(".", "-", 2))
    parsed = None
    for candidate in candidates:
        try:
            parsed = datetime.fromisoformat(candidate.replace("Z", "+00:00"))
            break
        except ValueError:
            continue
    if parsed is None:
        # English regulator/list pages commonly emit month-name dates
        # ("Aug. 14, 2026") or US slash dates ("8/13/2026").  Accept a few
        # bounded forms; still fail closed on anything else.
        for fmt in ("%b. %d, %Y", "%B %d, %Y", "%b %d, %Y", "%m/%d/%Y"):
            try:
                parsed = datetime.strptime(text, fmt)
                break
            except ValueError:
                continue
    if parsed is None:
        # Realtime flash feeds sometimes emit a bare wall-clock time
        # ("08:09:28" / "08:09") with the date implied by the source
        # timezone.  Anchor it to the source timezone's current day, but roll
        # late-night entries back one day when a just-after-midnight scrape
        # would otherwise manufacture a future timestamp.
        source_now = observed_at or datetime.now(timezone)
        if source_now.tzinfo is None:
            source_now = source_now.replace(tzinfo=timezone)
        source_now = source_now.astimezone(timezone)
        for fmt in ("%H:%M:%S", "%H:%M"):
            try:
                wall = datetime.strptime(text, fmt).time()
                parsed = datetime.combine(source_now.date(), wall).replace(
                    tzinfo=timezone
                )
                if parsed > source_now + timedelta(minutes=5):
                    parsed -= timedelta(days=1)
                break
            except ValueError:
                continue
    if parsed is None:
        raise ValueError("firecrawl item published time is not a recognized format")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone)
    return parsed.astimezone(timezone)


def _publication_precision(value: object) -> str:
    """Classify the source string, never its normalized midnight/date anchor."""
    if type(value) is not str or not value.strip():
        return "unknown"
    text = value.strip()
    candidates = (text, text.replace(".", "-", 2))
    for candidate in candidates:
        try:
            date.fromisoformat(candidate)
            return "date"
        except ValueError:
            pass
    for fmt in ("%b. %d, %Y", "%B %d, %Y", "%b %d, %Y", "%m/%d/%Y"):
        try:
            datetime.strptime(text, fmt)
            return "date"
        except ValueError:
            pass
    for fmt in ("%H:%M:%S", "%H:%M"):
        try:
            datetime.strptime(text, fmt)
            return "time"
        except ValueError:
            pass
    for candidate in candidates:
        try:
            datetime.fromisoformat(candidate.replace("Z", "+00:00"))
            return "datetime"
        except ValueError:
            pass
    return "unknown"


def _normalize_item(
    item: object,
    *,
    source: str,
    time_key: str,
    summary_key: str | None,
    timezone: ZoneInfo = _LOCAL_TIMEZONE,
    observed_at: datetime | None = None,
    preserve_publication_provenance: bool = False,
) -> dict[str, Any]:
    if type(item) is not dict:
        raise ValueError("firecrawl extraction item must be an object")
    # Capture before replacing URLs, reserved fields, or publication anchors.
    raw_item_json = (
        json.dumps(
            item,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        if preserve_publication_provenance
        else None
    )
    raw_url = item.get("url")
    try:
        canonical_url = _canonical_url(raw_url)
    except ValueError:
        # The LLM occasionally emits empty, ":" or relative paths for items
        # without a usable link.  Keep the item and its title/time/source
        # identity; only the link itself is dropped.
        canonical_url = None
    title = _non_empty_text(item.get("title"), "title", max_chars=1024)
    local = _parse_published_at(
        item.get(time_key), timezone=timezone, observed_at=observed_at
    )
    published_at = local.isoformat(timespec="seconds")
    # Unlinkable flash items (empty URL in the source page) still carry a
    # valid title/time/source identity; the id falls back to that tuple.
    uid_identity = (
        canonical_url if canonical_url is not None else source
    )
    content_uid = hashlib.sha256(
        f"{uid_identity}|{title}|{published_at}".encode("utf-8")
    ).hexdigest()
    summary = item.get(summary_key) if summary_key is not None else item.get("summary")
    if summary is not None and type(summary) is not str:
        raise ValueError("firecrawl item summary must be text or null")
    row = dict(item)
    row["source"] = source
    row["url"] = canonical_url
    row["title"] = title
    row["published_at"] = published_at
    row["published_local"] = local.strftime("%Y-%m-%d %H:%M:%S")
    row["event_date"] = local.strftime("%Y%m%d")
    row["content_uid"] = content_uid
    row["summary"] = summary
    if preserve_publication_provenance:
        row["provider_published_at"] = item.get(time_key)
        row["raw_item_json"] = raw_item_json
        row["publication_precision"] = _publication_precision(item.get(time_key))
    return row


class FirecrawlWebCollector:
    """Bearer-key, serial, extraction-only adapter for the news contract."""

    name = "firecrawl"
    provider = "firecrawl"

    def __init__(
        self,
        *,
        request_gate: Callable[[str], None] | None = None,
    ) -> None:
        if request_gate is not None and not callable(request_gate):
            raise TypeError("request_gate must be callable")
        self._request_gate = request_gate

    def _consume_budget(self, api_name: str) -> None:
        if self._request_gate is not None:
            self._request_gate(api_name)

    def collect_outcome(
        self,
        api_name: str,
        params: dict[str, Any],
        fields: str | None = None,
        *,
        scan_budget: SensitiveScanBudget | None = None,
    ) -> ProviderCallOutcome:
        del fields
        api_key: str | None = None
        try:
            if api_name == "scrape_page":
                with _diagnostic_phase("firecrawl local access preflight failed"):
                    api_key = _read_private_key_file(
                        os.environ.get(FIRECRAWL_API_KEY_FILE_ENV)
                    )
                rows = self._scrape_page(
                    params, api_key=api_key, timezone=_LOCAL_TIMEZONE, api_name="scrape_page"
                )
            elif api_name == "scrape_page_global":
                with _diagnostic_phase("firecrawl local access preflight failed"):
                    api_key = _read_private_key_file(
                        os.environ.get(FIRECRAWL_API_KEY_FILE_ENV)
                    )
                rows = self._scrape_page(
                    params,
                    api_key=api_key,
                    timezone=_GLOBAL_TIMEZONE,
                    api_name="scrape_page_global",
                    scan_budget=scan_budget,
                )
            elif api_name == "search_news":
                with _diagnostic_phase("firecrawl local access preflight failed"):
                    api_key = _read_private_key_file(
                        os.environ.get(FIRECRAWL_API_KEY_FILE_ENV)
                    )
                rows = self._search_news(params, api_key=api_key)
            else:
                raise _FirecrawlLocalFailure("firecrawl request preflight failed")
            return ProviderCallOutcome(
                state="success" if rows else "empty",
                rows=tuple(rows),
                provider_code=0,
                error_code=None,
                error_message=None,
                sensitive_values=(api_key,),
                scan_budget=scan_budget,
            )
        except HTTPError as exc:
            status = exc.code if type(exc.code) is int else None
            if status in (402, 429):
                error_code = "rate_limited"
            elif status in (401, 403):
                error_code = "permission_denied"
            else:
                error_code = "provider_error"
            return ProviderCallOutcome(
                state="failed",
                rows=(),
                provider_code=status,
                error_code=error_code,
                error_message=(
                    f"firecrawl request failed with HTTP status {status}"
                    if status is not None
                    else "firecrawl request failed"
                ),
                sensitive_values=() if api_key is None else (api_key,),
                scan_budget=scan_budget,
            )
        except (_FirecrawlUpstreamFailure, _FirecrawlLocalFailure) as exc:
            return ProviderCallOutcome(
                state="failed",
                rows=(),
                provider_code=None,
                error_code="provider_error",
                error_message=exc.safe_message,
                sensitive_values=() if api_key is None else (api_key,),
                scan_budget=scan_budget,
            )
        except Exception as exc:
            transport = isinstance(exc, (URLError, TimeoutError, ConnectionError, OSError))
            return ProviderCallOutcome(
                state="failed",
                rows=(),
                provider_code=None,
                error_code="transport_error" if transport else "provider_error",
                error_message=(
                    safe_provider_exception_message(exc)
                    if transport else "firecrawl adapter internal failure"
                ),
                sensitive_values=() if api_key is None else (api_key,),
                scan_budget=scan_budget,
            )

    def _post(self, path: str, body: dict[str, Any], *, api_key: str) -> object:
        timeout_ms = _bounded_int(
            body.get("timeout"), "timeout_ms", minimum=1, maximum=_MAX_TIMEOUT_MS
        )
        request = Request(
            f"{FIRECRAWL_API_URL}{path}",
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "User-Agent": "TradingDatas-News-Contract/1",
            },
            method="POST",
        )
        with _OPENER.open(request, timeout=timeout_ms / 1000) as response:  # nosec B310
            if response.status != 200:
                raise OSError("unexpected firecrawl response status")
            if response.geturl() != request.full_url:
                raise OSError("firecrawl origin changed")
            payload = response.read(_MAX_RESPONSE_BYTES + 1)
        with _diagnostic_phase("firecrawl response structure invalid"):
            if len(payload) > _MAX_RESPONSE_BYTES:
                raise ValueError("firecrawl response exceeds the size budget")
            return json.loads(payload.decode("utf-8"))

    def _scrape_page(
        self,
        params: dict[str, Any],
        *,
        api_key: str,
        timezone: ZoneInfo = _LOCAL_TIMEZONE,
        api_name: str = "scrape_page",
        scan_budget: SensitiveScanBudget | None = None,
    ) -> list[dict[str, Any]]:
        with _diagnostic_phase("firecrawl request preflight failed"):
            if set(params) - _SCRAPE_PARAM_KEYS:
                raise ValueError("firecrawl scrape params do not match the registry")
            provenance_mode = params.get("publication_provenance_mode")
            if "publication_provenance_mode" in params and (
                api_name != "scrape_page_global" or provenance_mode != "raw_item_v1"
            ):
                raise ValueError("firecrawl publication provenance mode is unsupported")
            self._consume_budget(api_name)
            url = _canonical_url(params.get("url"))
            prompt = _non_empty_text(params.get("prompt"), "prompt", max_chars=4096)
            for key in ("window_start", "window_end"):
                _non_empty_text(params.get(key), key, max_chars=64)
            max_age_ms = _bounded_int(
                params.get("max_age_ms"), "max_age_ms", minimum=0, maximum=_MAX_AGE_MS_LIMIT
            )
            timeout_ms = _bounded_int(
                params.get("timeout_ms"), "timeout_ms", minimum=1, maximum=_MAX_TIMEOUT_MS
            )
            raw_schema = _non_empty_text(
                params.get("extraction_schema"), "extraction_schema", max_chars=16384
            )
            schema = json.loads(raw_schema)
            if type(schema) is not dict:
                raise ValueError("firecrawl extraction_schema must be a JSON object")
        payload = self._post(
            "/scrape",
            {
                "url": url,
                "formats": [{"type": "json", "prompt": prompt, "schema": schema}],
                "maxAge": max_age_ms,
                "timeout": timeout_ms,
            },
            api_key=api_key,
        )
        if type(payload) is not dict or payload.get("success") is not True:
            raise _FirecrawlUpstreamFailure(_safe_upstream_failure_message(payload))
        with _diagnostic_phase("firecrawl response structure invalid"):
            data = payload.get("data")
            if type(data) is not dict or type(data.get("json")) is not dict:
                raise ValueError("firecrawl scrape response lacks the json extraction")
            items = data["json"].get("items")
            if type(items) is not list:
                raise ValueError("firecrawl extraction must produce an items array")
            if provenance_mode == "raw_item_v1":
                # Validate the original tree before reserved keys are overwritten
                # or nested objects become JSON text. Reuse the caller's existing
                # credential/known-secret/depth/node guard without a larger budget.
                ProviderCallOutcome(
                    state="success" if items else "empty",
                    rows=tuple(items),
                    provider_code=0,
                    error_code=None,
                    error_message=None,
                    sensitive_values=(api_key,),
                    scan_budget=scan_budget,
                )
        with _diagnostic_phase("firecrawl response item invalid"):
            return [
                _normalize_item(
                    item,
                    source=url,
                    time_key="published_at",
                    summary_key=None,
                    timezone=timezone,
                    preserve_publication_provenance=provenance_mode == "raw_item_v1",
                )
                for item in items
            ]

    def _search_news(
        self, params: dict[str, Any], *, api_key: str
    ) -> list[dict[str, Any]]:
        with _diagnostic_phase("firecrawl request preflight failed"):
            if set(params) - _SEARCH_PARAM_KEYS:
                raise ValueError("firecrawl search params do not match the registry")
            self._consume_budget("search_news")
            query = _non_empty_text(params.get("query"), "query", max_chars=_MAX_QUERY_CHARS)
            limit = _bounded_int(
                params.get("limit", 10), "limit", minimum=1, maximum=_MAX_SEARCH_LIMIT
            )
            timeout_ms = _bounded_int(
                params.get("timeout_ms", 30_000),
                "timeout_ms",
                minimum=1,
                maximum=_MAX_TIMEOUT_MS,
            )
        payload = self._post(
            "/search",
            {
                "query": query,
                "sources": [{"type": "news"}],
                "limit": limit,
                "timeout": timeout_ms,
            },
            api_key=api_key,
        )
        if type(payload) is not dict or payload.get("success") is not True:
            raise _FirecrawlUpstreamFailure(_safe_upstream_failure_message(payload))
        with _diagnostic_phase("firecrawl response structure invalid"):
            data = payload.get("data")
            if type(data) is not dict or type(data.get("news")) is not list:
                raise ValueError("firecrawl search response lacks the news array")
        with _diagnostic_phase("firecrawl response item invalid"):
            return [
                _normalize_item(
                    item,
                    source=_SEARCH_SOURCE_LABEL,
                    time_key="date",
                    summary_key="snippet",
                )
                for item in data["news"]
            ]

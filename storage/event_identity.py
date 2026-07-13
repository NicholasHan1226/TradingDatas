from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping


# Contract: provider-local native IDs are namespaced by normalized provider.
# ``source_family`` is lineage metadata only and is never the identity namespace.

NATIVE_ID_FIELDS = (
    "event_id",
    "id",
    "accessionNumber",
    "accession_number",
    "ann_id",
    "report_id",
)

# These provider rows have no native ID or URL.  Their documented immutable
# business keys are therefore the narrow fallback identity.  Keep this mapping
# provider-specific: a broad "all available fields" hash would turn content
# edits into new logical events instead of revisions.
PROVIDER_COMPOSITE_IDENTITY_FIELDS = {
    # Tushare's convertible-bond issuance feed has no native event identifier.
    # ``ts_code`` is the provider's immutable issuance/security identity; issue
    # size, dates, price and online-allocation fields are revision content and
    # must not fork the logical event when they are corrected.
    "tushare_cb_issue": (
        ("ts_code",),
    ),
    "tushare_namechange": (
        ("ts_code", "start_date", "name"),
        ("ts_code", "ann_date", "name"),
    ),
    "tushare_report_rc": (
        ("ts_code", "report_date", "report_title"),
        ("ts_code", "report_date", "org_name", "author_name"),
    ),
}

# Strict providers must use their documented business key.  They may not fall
# through to URL/title/date heuristics, because those values are either absent
# from the feed or mutable and would silently create unstable logical events.
STRICT_PROVIDER_COMPOSITE_IDENTITIES = frozenset({"tushare_cb_issue"})


def _normalized_provider(provider: str) -> str:
    return str(provider or "").strip().lower() or "unknown"


def source_family(provider: str) -> str:
    value = _normalized_provider(provider)
    if value.startswith("tushare_"):
        return "tushare"
    return value


def _nested_mappings(value: Any):
    if isinstance(value, Mapping):
        yield value
        for nested in value.values():
            yield from _nested_mappings(nested)
    elif isinstance(value, (list, tuple)):
        for nested in value:
            yield from _nested_mappings(nested)


def _decoded_mapping(value: Any) -> Mapping[str, Any] | None:
    if isinstance(value, Mapping):
        return value
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        decoded = json.loads(value)
    except (TypeError, ValueError):
        return None
    return decoded if isinstance(decoded, Mapping) else None


def _identity_sources(row: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    sources = [row]
    for field in ("raw_json", "content"):
        decoded = _decoded_mapping(row.get(field))
        if decoded is not None:
            sources.extend(_nested_mappings(decoded))
    return sources


def _native_identity(row: Mapping[str, Any]) -> str:
    sources = _identity_sources(row)
    for source in sources:
        for key in NATIVE_ID_FIELDS:
            value = str(source.get(key) or "").strip()
            if value:
                return value
    return ""


def _provider_composite_identity(
    provider: str,
    row: Mapping[str, Any],
) -> str:
    field_sets = PROVIDER_COMPOSITE_IDENTITY_FIELDS.get(
        _normalized_provider(provider),
        (),
    )
    for source in _identity_sources(row):
        for fields in field_sets:
            values = [str(source.get(field) or "").strip() for field in fields]
            if all(values):
                return "|".join(values)
    return ""


def stable_event_id(provider: str, event_type: str, row: Mapping[str, Any]) -> str:
    normalized_provider = _normalized_provider(provider)
    provider_composite = _provider_composite_identity(provider, row)
    if normalized_provider in STRICT_PROVIDER_COMPOSITE_IDENTITIES:
        if not provider_composite:
            required = PROVIDER_COMPOSITE_IDENTITY_FIELDS[normalized_provider]
            rendered = " or ".join("+".join(fields) for fields in required)
            raise ValueError(
                f"cannot derive stable event identity for {normalized_provider}: "
                f"missing required business key {rendered}"
            )
        identity = provider_composite
    else:
        native = _native_identity(row)
        canonical_url = str(row.get("url") or row.get("link") or "").strip().split("#", 1)[0]
        fallback_parts = [
            str(row.get(key) or "").strip()
            for key in ("datetime", "pub_time", "date", "title")
        ]
        fallback = "|".join(fallback_parts) if any(fallback_parts) else ""
        identity = native or provider_composite or canonical_url or fallback
    if not identity:
        raise ValueError("cannot derive stable event identity from native id, URL, date, or title")
    digest = hashlib.sha256(
        f"{normalized_provider}|{event_type}|{identity}".encode()
    ).hexdigest()[:32]
    return f"evt:{digest}"


def event_content_fingerprint(row: Mapping[str, Any]) -> str:
    structured_cb_issue = (
        _normalized_provider(str(row.get("provider") or "")) == "tushare_cb_issue"
        or str(row.get("event_type") or "").strip() == "cb_issue"
    )
    if structured_cb_issue:
        decoded_raw = _decoded_mapping(row.get("raw_json"))
        source = dict(decoded_raw) if decoded_raw is not None else dict(row)
        # Stored rows reconstruct these canonical columns even when the provider
        # payload omitted them.  Add the same explicit null/default shape to the
        # incoming payload so a replay compares equal byte-for-byte.
        for key in (
            "title",
            "content",
            "url",
            "source",
            "src",
            "symbol",
            "event_time",
            "trade_date",
        ):
            source.setdefault(key, row.get(key))
        # Physical/ingestion metadata must not create a content revision.  The
        # full cb_issue provider facts remain, so corrected issue details append
        # a revision without changing the logical event id.
        for key in (
            "event_hash",
            "event_id",
            "revision",
            "source_family",
            "source_file",
            "collected_at",
            "created_at",
            "updated_at",
        ):
            source.pop(key, None)
        source.pop("raw_json", None)
        payload = source
    else:
        payload = {
            key: row.get(key)
            for key in (
                "title",
                "content",
                "url",
                "source",
                "src",
                "symbol",
                "event_time",
                "trade_date",
            )
        }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    ).encode()
    return hashlib.sha256(encoded).hexdigest()

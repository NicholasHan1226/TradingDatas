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

# All registry routes that write ``market_events`` have an explicit fallback
# identity. Only route-declared, top-level native IDs may take priority over it.
# The block-trade key deliberately contains every provider fact that identifies
# one trade: no narrower subset proves that two changed rows are the same event.
PROVIDER_COMPOSITE_IDENTITY_FIELDS = {
    "tushare_block_trade": (
        ("ts_code", "trade_date", "price", "vol", "buyer", "seller"),
    ),
    "tushare_limit_list": (("ts_code", "trade_date"),),
    "tushare_limit_list_d": (("ts_code", "trade_date"),),
    "tushare_broker_recommend": (("month", "broker", "ts_code"),),
    "tushare_suspend_d": (
        ("ts_code", "suspend_date"),
        ("ts_code", "trade_date"),
    ),
    "tushare_namechange": (
        ("ts_code", "start_date", "name"),
        ("ts_code", "ann_date", "name"),
    ),
    # One Tushare cb_issue row describes the issuance for one convertible bond.
    # Corrected size, dates, or price are revisions of that issuance.
    "tushare_cb_issue": (("ts_code",),),
    "tushare_news": (("datetime", "title"),),
    "tushare_major_news": (("pub_time", "title"),),
    "tushare_cctv_news": (
        ("date", "broadcast_time", "title"),
        ("date", "title"),
    ),
    "tushare_anns_d": (("ts_code", "ann_date", "title"),),
    "tushare_report_rc": (
        ("ts_code", "report_date", "report_title"),
        ("ts_code", "report_date", "org_name", "author_name"),
    ),
}

# Provider contracts for the twelve registered live event routes. An empty
# tuple is deliberate: the current Tushare response schemas expose no provider
# native event ID for these routes. In particular, a block-trade ``id`` is not
# a Tushare field and can never replace its six-field business key.
TRUSTED_NATIVE_ID_FIELDS = {
    "tushare_block_trade": (),
    "tushare_limit_list": (),
    "tushare_limit_list_d": (),
    "tushare_broker_recommend": (),
    "tushare_suspend_d": (),
    "tushare_namechange": (),
    "tushare_cb_issue": (),
    "tushare_news": (),
    "tushare_major_news": (),
    "tushare_cctv_news": (),
    "tushare_anns_d": (),
    "tushare_report_rc": (),
}

# Non-registry sources can declare their own provider-native fields and the
# payload containers in which the source contract places them. This is narrow
# by design: generic nested ``id`` / ``event_id`` claims are never trusted.
SOURCE_NATIVE_ID_FIELDS = {
    "sec_edgar": ("accessionNumber", "accession_number"),
}
SOURCE_NATIVE_ID_PAYLOAD_FIELDS = {
    "sec_edgar": ("raw_json", "content"),
}

EXPLICIT_ROUTE_IDENTITIES = frozenset(PROVIDER_COMPOSITE_IDENTITY_FIELDS)
COMPOSITE_ONLY_IDENTITIES = frozenset({"tushare_cb_issue"})
NO_URL_IDENTITIES = frozenset({"tushare_block_trade"})
LEGACY_TITLE_FALLBACK_IDENTITIES = frozenset({"tushare_news"})

_PROVIDER_CLAIM_SCHEMA = "provider-claim.v1"
_TRUSTED_CONTEXT_FIELDS = frozenset(
    {"provider", "event_type", "dataset", "dataset_id", "route", "api_name"}
)
_INGESTION_METADATA_FIELDS = frozenset(
    {
        "event_hash",
        "revision",
        "source_family",
        "source_file",
        "collected_at",
        "created_at",
        "updated_at",
        "raw_json",
        "_sharedsignals_provenance",
    }
)


def _normalized_provider(provider: str) -> str:
    return str(provider or "").strip().lower() or "unknown"


def source_family(provider: str) -> str:
    value = _normalized_provider(provider)
    if value.startswith("tushare_"):
        return "tushare"
    return value


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


def _sanitize_business_value(
    value: Any,
    *,
    drop_native_ids: bool = False,
) -> Any:
    if isinstance(value, Mapping):
        sanitized: dict[str, Any] = {}
        dropped = _TRUSTED_CONTEXT_FIELDS | _INGESTION_METADATA_FIELDS
        if drop_native_ids:
            dropped = dropped | frozenset(NATIVE_ID_FIELDS)
        for key, nested in value.items():
            normalized_key = str(key)
            if normalized_key in dropped:
                continue
            sanitized[normalized_key] = _sanitize_business_value(
                nested,
                drop_native_ids=drop_native_ids,
            )
        return sanitized
    if isinstance(value, (list, tuple)):
        return [
            _sanitize_business_value(item, drop_native_ids=drop_native_ids)
            for item in value
        ]
    return value


def _is_provider_claim_envelope(value: Mapping[str, Any]) -> bool:
    provenance = value.get("_sharedsignals_provenance")
    return (
        isinstance(provenance, Mapping)
        and provenance.get("schema") == _PROVIDER_CLAIM_SCHEMA
    )


def _raw_business_payload(value: Any) -> dict[str, Any]:
    decoded = _decoded_mapping(value)
    if decoded is None:
        return {}
    if not _is_provider_claim_envelope(decoded):
        sanitized = _sanitize_business_value(decoded)
        return dict(sanitized) if isinstance(sanitized, Mapping) else {}

    business = _raw_business_payload(decoded.get("raw_payload"))
    row_payload = _raw_business_payload(decoded.get("row_payload"))
    business.update(row_payload)
    return business


def canonical_event_business_payload(
    row: Mapping[str, Any],
    *,
    provider: str | None = None,
    event_type: str | None = None,
) -> dict[str, Any]:
    """Build one symmetric business view for incoming and stored event rows.

    Parseable raw JSON may fill business fields that have no read-model column,
    but current top-level facts win. Provider-claim envelopes and opaque raw
    text remain provenance only. Trusted route context is supplied explicitly
    by the caller, or read from canonical top-level columns; nested values can
    never override it.
    """

    raw_business = _raw_business_payload(row.get("raw_json"))
    raw_had_volume = "volume" in raw_business
    business = dict(raw_business)
    top_level = _sanitize_business_value(row)
    if isinstance(top_level, Mapping):
        for key, value in top_level.items():
            # Stored read-model rows contain NULL for absent canonical fields.
            # A NULL storage column must not erase a supplemental raw fact.
            if value is not None or key not in business:
                business[key] = value

    # ``read_model_store`` derives volume from vol for generic table routing,
    # but market_events has no volume column. Avoid hashing the transient alias
    # when provenance proves that only vol was present in the provider row.
    if (
        "raw_json" in row
        and "vol" in business
        and not raw_had_volume
        and business.get("volume") == business.get("vol")
    ):
        business.pop("volume", None)

    trusted_provider = provider if provider is not None else row.get("provider")
    trusted_event_type = (
        event_type if event_type is not None else row.get("event_type")
    )
    for key in (
        "market",
        "symbol",
        "title",
        "content",
        "url",
        "source",
        "event_time",
        "trade_date",
    ):
        business.setdefault(key, None)
    business["provider"] = _normalized_provider(str(trusted_provider or ""))
    business["event_type"] = str(trusted_event_type or "event").strip() or "event"
    return business


def _nested_mappings(value: Any):
    if isinstance(value, Mapping):
        yield value
        for nested in value.values():
            yield from _nested_mappings(nested)
    elif isinstance(value, (list, tuple)):
        for nested in value:
            yield from _nested_mappings(nested)


def _identity_sources(row: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    sources = list(_nested_mappings(row))
    for source in tuple(sources):
        decoded = _decoded_mapping(source.get("content"))
        if decoded is not None:
            sources.extend(_nested_mappings(decoded))
    return sources


def _native_value(row: Mapping[str, Any], fields: tuple[str, ...]) -> str:
    for key in fields:
        value = str(row.get(key) or "").strip()
        if key == "event_id" and value.startswith("evt:"):
            continue
        if value:
            return value
    return ""


def _native_identity(provider: str, row: Mapping[str, Any]) -> str:
    normalized_provider = _normalized_provider(provider)
    route_fields = TRUSTED_NATIVE_ID_FIELDS.get(normalized_provider)
    if route_fields is not None:
        # Registered live routes trust only fields from their top-level
        # provider response contract. Raw/content provenance cannot add one.
        return _native_value(row, route_fields)

    source_fields = SOURCE_NATIVE_ID_FIELDS.get(normalized_provider)
    if source_fields is not None:
        native = _native_value(row, source_fields)
        if native:
            return native
        for payload_field in SOURCE_NATIVE_ID_PAYLOAD_FIELDS.get(
            normalized_provider, ()
        ):
            decoded = _decoded_mapping(row.get(payload_field))
            if decoded is None:
                continue
            for source in _nested_mappings(decoded):
                native = _native_value(source, source_fields)
                if native:
                    return native
        return ""

    # Compatibility for unregistered providers is top-level only. Recursive
    # generic native-ID discovery would let provenance redefine identity.
    return _native_value(row, NATIVE_ID_FIELDS)


def _canonical_url(row: Mapping[str, Any]) -> str:
    for source in _identity_sources(row):
        for key in ("url", "link"):
            value = str(source.get(key) or "").strip().split("#", 1)[0]
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


def _fallback_identity(row: Mapping[str, Any]) -> str:
    for source in _identity_sources(row):
        values = [
            str(source.get(key) or "").strip()
            for key in ("datetime", "pub_time", "date", "title")
        ]
        if any(values):
            return "|".join(values)
    return ""


def _missing_business_key_error(provider: str) -> ValueError:
    required = PROVIDER_COMPOSITE_IDENTITY_FIELDS[provider]
    rendered = " or ".join("+".join(fields) for fields in required)
    return ValueError(
        f"cannot derive stable event identity for {provider}: "
        f"missing required business key {rendered}"
    )


def stable_event_id(
    provider: str,
    event_type: str,
    row: Mapping[str, Any],
    *,
    allow_legacy_fallback: bool = True,
) -> str:
    normalized_provider = _normalized_provider(provider)
    business = canonical_event_business_payload(
        row,
        provider=normalized_provider,
        event_type=event_type,
    )
    native = _native_identity(normalized_provider, row)
    provider_composite = _provider_composite_identity(normalized_provider, business)
    canonical_url = _canonical_url(business)

    if normalized_provider in COMPOSITE_ONLY_IDENTITIES:
        if not provider_composite:
            raise _missing_business_key_error(normalized_provider)
        identity = provider_composite
    elif normalized_provider in EXPLICIT_ROUTE_IDENTITIES:
        identity = native
        if not identity and normalized_provider not in NO_URL_IDENTITIES:
            identity = canonical_url
        identity = identity or provider_composite
        if (
            not identity
            and allow_legacy_fallback
            and normalized_provider in LEGACY_TITLE_FALLBACK_IDENTITIES
        ):
            # Historical news rows may contain only a title. Migration keeps
            # their established identity; live ingestion disables this fallback.
            identity = _fallback_identity(business)
        if not identity:
            raise _missing_business_key_error(normalized_provider)
    else:
        identity = native or canonical_url or provider_composite or _fallback_identity(
            business
        )
        if not identity:
            raise ValueError(
                "cannot derive stable event identity from native id, URL, date, or title"
            )

    digest = hashlib.sha256(
        f"{normalized_provider}|{event_type}|{identity}".encode()
    ).hexdigest()[:32]
    return f"evt:{digest}"


def event_content_fingerprint(
    row: Mapping[str, Any],
    *,
    provider: str | None = None,
    event_type: str | None = None,
) -> str:
    business = canonical_event_business_payload(
        row,
        provider=provider,
        event_type=event_type,
    )
    payload = _sanitize_business_value(business, drop_native_ids=True)
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    ).encode()
    return hashlib.sha256(encoded).hexdigest()

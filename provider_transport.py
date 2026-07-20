"""Provider-level transport identities shared by ingest and read-side lineage."""

from __future__ import annotations

import hashlib
import json


TUSHARE_DATA_PROVIDER = "tushare"
TUSHARE_TRANSPORT_SERVICE = "quicksync"
TUSHARE_TRANSPORT_PROFILE_ID = "quicksync-tushare-compatible.v1"
QUICKSYNC_TUSHARE_API_URL = "https://api.quicksync.cn"


def provider_transport_profile(provider: str) -> dict[str, object]:
    """Return one credential-free, code-pinned provider transport profile."""

    if provider != TUSHARE_DATA_PROVIDER:
        raise KeyError("provider transport profile is unavailable")
    payload: dict[str, object] = {
        "data_provider": TUSHARE_DATA_PROVIDER,
        "endpoint": QUICKSYNC_TUSHARE_API_URL,
        "profile_id": TUSHARE_TRANSPORT_PROFILE_ID,
        "redirects_allowed": False,
        "tls_minimum": "TLSv1.3",
        "tls_maximum": "TLSv1.3",
        "transport_service": TUSHARE_TRANSPORT_SERVICE,
    }
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return {
        **payload,
        "profile_sha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
    }

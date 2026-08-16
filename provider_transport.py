"""Provider-level transport identities shared by ingest and read-side lineage."""

from __future__ import annotations

import hashlib
import json


TUSHARE_DATA_PROVIDER = "tushare"
TUSHARE_TRANSPORT_SERVICE = "quicksync"
TUSHARE_TRANSPORT_PROFILE_ID = "quicksync-tushare-compatible.v2"
QUICKSYNC_TUSHARE_API_URL = "https://api.quicksync.cn"
BINANCE_SPOT_DATA_PROVIDER = "binance_spot"
BINANCE_SPOT_TRANSPORT_SERVICE = "binance_public_market_data"
BINANCE_SPOT_PUBLIC_API_URL = "https://data-api.binance.vision"
BINANCE_USDM_DATA_PROVIDER = "binance_usdm"
BINANCE_USDM_TRANSPORT_SERVICE = "binance_usdm_public_market_data"
BINANCE_USDM_PUBLIC_API_URL = "https://fapi.binance.com"
BINANCE_USDM_DUMP_DATA_PROVIDER = "binance_usdm_dump"
BINANCE_USDM_DUMP_TRANSPORT_SERVICE = "binance_usdm_public_metrics_dump"
BINANCE_USDM_DUMP_PUBLIC_DATA_URL = "https://data.binance.vision"
BINANCE_USDM_RELAY_DATA_PROVIDER = "binance_usdm_relay"
BINANCE_USDM_RELAY_TRANSPORT_SERVICE = "binance_usdm_sg_relay"
BINANCE_USDM_RELAY_SOCKS5_ENDPOINT = "socks5://127.0.0.1:17890"
FIRECRAWL_DATA_PROVIDER = "firecrawl"
FIRECRAWL_TRANSPORT_SERVICE = "firecrawl_web_scrape_api"
FIRECRAWL_API_URL = "https://api.firecrawl.dev/v2"


def provider_transport_profile(provider: str) -> dict[str, object]:
    """Return one credential-free, code-pinned provider transport profile."""

    if provider == FIRECRAWL_DATA_PROVIDER:
        payload: dict[str, object] = {
            "data_provider": FIRECRAWL_DATA_PROVIDER,
            "endpoint": FIRECRAWL_API_URL,
            "profile_id": "firecrawl-web-scrape-api.v1",
            "redirects_allowed": False,
            "connection_mode": "public_https",
            "canonical_host": "api.firecrawl.dev",
            "host_header": "api.firecrawl.dev",
            "sni_server_name": "api.firecrawl.dev",
            "certificate_hostname": "api.firecrawl.dev",
            "pre_send_node_failover": False,
            "post_send_replay": False,
            "credential_mode": "bearer_key_file",
            "max_concurrency": 1,
            "transport_service": FIRECRAWL_TRANSPORT_SERVICE,
        }
    elif provider == BINANCE_USDM_DATA_PROVIDER:
        payload: dict[str, object] = {
            "data_provider": BINANCE_USDM_DATA_PROVIDER,
            "endpoint": BINANCE_USDM_PUBLIC_API_URL,
            "profile_id": "binance-usdm-public-market-data.v1",
            "redirects_allowed": False,
            "connection_mode": "public_https",
            "canonical_host": "fapi.binance.com",
            "host_header": "fapi.binance.com",
            "sni_server_name": "fapi.binance.com",
            "certificate_hostname": "fapi.binance.com",
            "pre_send_node_failover": False,
            "post_send_replay": False,
            "credential_mode": "none",
            "market_data_only": True,
            "transport_service": BINANCE_USDM_TRANSPORT_SERVICE,
        }
    elif provider == BINANCE_USDM_RELAY_DATA_PROVIDER:
        payload = {
            "data_provider": BINANCE_USDM_RELAY_DATA_PROVIDER,
            "endpoint": BINANCE_USDM_PUBLIC_API_URL,
            "profile_id": "binance-usdm-via-sg-relay.v1",
            "redirects_allowed": False,
            "connection_mode": "loopback_socks5_relay",
            "relay_endpoint": BINANCE_USDM_RELAY_SOCKS5_ENDPOINT,
            "canonical_host": "fapi.binance.com",
            "host_header": "fapi.binance.com",
            "sni_server_name": "fapi.binance.com",
            "certificate_hostname": "fapi.binance.com",
            "pre_send_node_failover": False,
            "post_send_replay": False,
            "credential_mode": "none",
            "market_data_only": True,
            "relay_note": (
                "Owner-approved L4 SSH tunnel (sg-relay-tunnel.service); TLS is "
                "end-to-end to fapi.binance.com, the relay can only drop, never "
                "read or modify.  Direct egress is SNI-blocked; there is no "
                "silent fallback in either direction."
            ),
            "transport_service": BINANCE_USDM_RELAY_TRANSPORT_SERVICE,
        }
    elif provider == BINANCE_USDM_DUMP_DATA_PROVIDER:
        payload = {
            "data_provider": BINANCE_USDM_DUMP_DATA_PROVIDER,
            "endpoint": BINANCE_USDM_DUMP_PUBLIC_DATA_URL,
            "profile_id": "binance-usdm-public-metrics-dump.v1",
            "redirects_allowed": False,
            "connection_mode": "public_https",
            "canonical_host": "data.binance.vision",
            "host_header": "data.binance.vision",
            "sni_server_name": "data.binance.vision",
            "certificate_hostname": "data.binance.vision",
            "pre_send_node_failover": False,
            "post_send_replay": False,
            "credential_mode": "none",
            "market_data_only": True,
            "transport_service": BINANCE_USDM_DUMP_TRANSPORT_SERVICE,
        }
    elif provider == BINANCE_SPOT_DATA_PROVIDER:
        payload: dict[str, object] = {
            "data_provider": BINANCE_SPOT_DATA_PROVIDER,
            "endpoint": BINANCE_SPOT_PUBLIC_API_URL,
            "profile_id": "binance-spot-public-market-data.v1",
            "redirects_allowed": False,
            "connection_mode": "public_https",
            "canonical_host": "data-api.binance.vision",
            "host_header": "data-api.binance.vision",
            "sni_server_name": "data-api.binance.vision",
            "certificate_hostname": "data-api.binance.vision",
            "pre_send_node_failover": False,
            "post_send_replay": False,
            "credential_mode": "none",
            "market_data_only": True,
            "transport_service": BINANCE_SPOT_TRANSPORT_SERVICE,
        }
    elif provider == TUSHARE_DATA_PROVIDER:
        payload = {
        "data_provider": TUSHARE_DATA_PROVIDER,
        "endpoint": QUICKSYNC_TUSHARE_API_URL,
        "profile_id": TUSHARE_TRANSPORT_PROFILE_ID,
        "redirects_allowed": False,
        "connection_mode": "dns_snapshot_direct_connect",
        "canonical_host": "api.quicksync.cn",
        "host_header": "api.quicksync.cn",
        "sni_server_name": "api.quicksync.cn",
        "certificate_hostname": "api.quicksync.cn",
        "pre_send_node_failover": True,
        "post_send_replay": False,
        "request_rate_limit": {"max_requests": 200, "window_seconds": 60},
        "max_concurrency": 4,
        "node_cooldown_seconds": 30,
        "tls_minimum": "TLSv1.3",
        "tls_maximum": "TLSv1.3",
        "transport_service": TUSHARE_TRANSPORT_SERVICE,
        }
    else:
        raise KeyError("provider transport profile is unavailable")
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

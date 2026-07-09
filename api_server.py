#!/usr/bin/env python3

"""http.server based REST API for SharedSignals."""

from __future__ import annotations

import json
import os
import sys
import threading
from datetime import datetime, timezone
from email.utils import formatdate
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from env_bootstrap import env_float, env_int

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

auth: Any | None = None
reader: Any | None = None
_runtime_load_lock = threading.Lock()
HOST = os.environ.get("SHAREDSIGNALS_API_HOST", "127.0.0.1")
PORT = env_int("SHAREDSIGNALS_API_PORT", 8082, min_value=1, max_value=65535)
VERSION = os.environ.get("SHAREDSIGNALS_API_VERSION", "1.0.0")
REQUEST_TIMEOUT = env_float("SHAREDSIGNALS_REQUEST_TIMEOUT", 30.0, min_value=1.0, max_value=300.0)
MAX_THREADS = env_int("SHAREDSIGNALS_MAX_THREADS", 20, min_value=1, max_value=512)
CAPABILITY_PATH = ROOT / "tools" / "capability_registry.json"
HEALTH_CACHE_SECONDS = 60
HEALTH_DEEP_CHECKS_ENV = "SHAREDSIGNALS_HEALTH_DEEP_CHECKS"


def _ensure_runtime_loaded() -> None:
    """Bootstrap process env, then load modules that read os.environ."""
    global auth, reader, HOST, PORT, VERSION, REQUEST_TIMEOUT, MAX_THREADS
    if auth is not None and reader is not None:
        return

    with _runtime_load_lock:
        if auth is not None and reader is not None:
            return

        from env_bootstrap import bootstrap_sharedsignals_env

        bootstrap_sharedsignals_env()
        HOST = os.environ.get("SHAREDSIGNALS_API_HOST", HOST)
        PORT = env_int("SHAREDSIGNALS_API_PORT", PORT, min_value=1, max_value=65535)
        VERSION = os.environ.get("SHAREDSIGNALS_API_VERSION", VERSION)
        REQUEST_TIMEOUT = env_float("SHAREDSIGNALS_REQUEST_TIMEOUT", REQUEST_TIMEOUT, min_value=1.0, max_value=300.0)
        MAX_THREADS = env_int("SHAREDSIGNALS_MAX_THREADS", MAX_THREADS, min_value=1, max_value=512)

        import auth as auth_module  # noqa: WPS433
        import reader as reader_module  # noqa: WPS433

        auth = auth_module
        reader = reader_module
        Handler.server_version = f"SharedSignalsAPI/{VERSION}"

# ---- Health check (lazy import to avoid pulling in health_check at startup) ----
_health_cache: dict[str, Any] | None = None
_health_cache_time: float = 0.0
_health_cache_lock = threading.Lock()


def _health_deep_checks_enabled() -> bool:
    return str(os.environ.get(HEALTH_DEEP_CHECKS_ENV, "")).strip().lower() in {"1", "true", "yes", "on"}



def _get_health() -> dict[str, Any]:
    """Return cached health status, refreshing if older than HEALTH_CACHE_SECONDS."""
    global _health_cache, _health_cache_time
    now = datetime.now(timezone.utc).timestamp()
    with _health_cache_lock:
        if _health_cache is not None and (now - _health_cache_time) < HEALTH_CACHE_SECONDS:
            return _health_cache

    try:
        from tools.health_check import get_health_status
        deep_checks = _health_deep_checks_enabled()
        result = get_health_status(
            check_functions=deep_checks, check_data_freshness=deep_checks,
            check_cron=True, check_arch=False, check_compile=False,
        )
    except Exception:
        result = {"status": "error", "message": "health check failed", "timestamp": utc_now_iso()}

    result.setdefault("version", VERSION)
    with _health_cache_lock:
        _health_cache = result
        _health_cache_time = now
        return _health_cache


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()



def to_int(value: Any, default: int, *, min_val: int = 1, max_val: int = 10000) -> int:
    try:
        v = int(value)
        if v < min_val:
            return min_val
        if v > max_val:
            return max_val
        return v
    except (TypeError, ValueError):
        return default


def apply_row_limit(rows: Any, params: dict[str, str], *, default: int | None = None) -> Any:
    if not isinstance(rows, list):
        return rows
    raw_limit = params.get("limit")
    if raw_limit in (None, "") and default is None:
        return rows
    fallback = default if default is not None else len(rows)
    return rows[:to_int(raw_limit, fallback, min_val=1, max_val=10000)]


def validate_json_query_params(params: dict[str, str]) -> None:
    """Reject malformed JSON in query params that explicitly declare JSON content."""
    json_param_names = {"params", "filters", "payload"}
    for key, value in params.items():
        if key not in json_param_names and not key.endswith("_json"):
            continue
        if not value:
            continue
        try:
            json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError(f"malformed JSON in query parameter '{key}': {exc.msg}") from exc



def aggregate_metadata(rows: Any) -> tuple[Any, dict[str, Any], str | None]:
    if not isinstance(rows, list):
        return rows, {"freshness": None, "quality": None, "degraded": False, "degraded_reasons": [], "lineage": []}, None

    if not rows:
        return [], {"freshness": None, "quality": None, "degraded": False, "degraded_reasons": [], "lineage": []}, None

    if not all(isinstance(row, dict) and "data" in row for row in rows):
        return rows, {"freshness": None, "quality": None, "degraded": False, "degraded_reasons": [], "lineage": []}, None

    data_rows = [
        row.get("data")
        for row in rows
        if not (
            isinstance(row, dict)
            and bool(row.get("degraded"))
            and row.get("data") in ({}, None)
        )
    ]
    degraded = any(bool(row.get("degraded")) for row in rows)
    freshness_rows = [row.get("freshness") for row in rows if isinstance(row.get("freshness"), dict)]
    quality_rows = [row.get("quality") for row in rows if isinstance(row.get("quality"), dict)]
    degraded_reasons: list[str] = []
    lineages: list[dict[str, Any]] = []
    sources = []
    for row in rows:
        provenance = row.get("provenance") if isinstance(row, dict) else None
        if isinstance(provenance, dict) and provenance.get("source_id"):
            sources.append(str(provenance["source_id"]))
        lineage = row.get("lineage") if isinstance(row, dict) else None
        if isinstance(lineage, dict) and lineage:
            lineages.append(lineage)
            reason = lineage.get("reason")
            if reason:
                degraded_reasons.append(str(reason))
        row_reasons = row.get("degraded_reasons") if isinstance(row, dict) else None
        if isinstance(row_reasons, list):
            degraded_reasons.extend(str(reason) for reason in row_reasons if reason)
        elif row_reasons:
            degraded_reasons.append(str(row_reasons))
    source = sources[0] if sources else None

    freshness: dict[str, Any] | None = None
    if freshness_rows:
        age_hours = [float(item.get("age_hours", 0.0)) for item in freshness_rows if item.get("age_hours") is not None]
        scores = [float(item.get("score", 0.0)) for item in freshness_rows if item.get("score") is not None]
        freshness = {
            "stale": any(bool(item.get("stale")) for item in freshness_rows),
            "age_hours_max": max(age_hours) if age_hours else None,
            "age_hours_min": min(age_hours) if age_hours else None,
            "score_min": min(scores) if scores else None,
            "score_max": max(scores) if scores else None,
        }
        if len(freshness_rows) == 1:
            freshness = freshness_rows[0]

    quality: dict[str, Any] | None = None
    if quality_rows:
        scores = [float(item.get("score", 0.0)) for item in quality_rows if item.get("score") is not None]
        completeness = [float(item.get("completeness", 0.0)) for item in quality_rows if item.get("completeness") is not None]
        quality = {
            "score_min": min(scores) if scores else None,
            "score_avg": round(sum(scores) / len(scores), 4) if scores else None,
            "completeness_min": min(completeness) if completeness else None,
        }
        if len(quality_rows) == 1:
            quality = quality_rows[0]

    seen_reasons: set[str] = set()
    unique_reasons = []
    for reason in degraded_reasons:
        if reason not in seen_reasons:
            seen_reasons.add(reason)
            unique_reasons.append(reason)

    return data_rows, {
        "freshness": freshness,
        "quality": quality,
        "degraded": degraded,
        "degraded_reasons": unique_reasons,
        "lineage": lineages[0] if len(lineages) == 1 else lineages,
    }, source



def file_payload(path: Path) -> tuple[Any, dict[str, Any], str | None]:
    stat = path.stat()
    payload = json.loads(path.read_text())
    age_hours = max((datetime.now(timezone.utc).timestamp() - stat.st_mtime) / 3600.0, 0.0)
    metadata = {
        "freshness": {
            "stale": False,
            "age_hours": round(age_hours, 4),
            "score": 1.0,
            "last_modified": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
        },
        "quality": {"score": 1.0, "completeness": 1.0},
        "degraded": False,
    }
    return payload, metadata, path.name


def capability_fallback_payload() -> tuple[dict[str, Any], dict[str, Any], str]:
    """Return a deterministic capability summary when the generated registry is absent."""

    scope_map = getattr(auth, "SCOPE_ENDPOINTS", {}) if auth is not None else {}
    unique_endpoints = sorted(
        {
            endpoint
            for endpoints_for_scope in scope_map.values()
            for endpoint in endpoints_for_scope
            if endpoint != "*"
        }
    )
    payload = {
        "status": "degraded",
        "reason": f"missing generated registry: {CAPABILITY_PATH}",
        "next_action": "run tools/capability_scan.py; cron/capability_scan.sh keeps this file refreshed in production",
        "summary": {
            "total": len(unique_endpoints),
            "ok": 0,
            "degraded": len(unique_endpoints),
            "down": 0,
        },
        "endpoints": [
            {
                "name": endpoint.strip("/") or "root",
                "path": endpoint,
                "status": "degraded",
                "category": _endpoint_category(endpoint, scope_map),
                "description": "Generated registry missing; endpoint is listed from auth scope map.",
            }
            for endpoint in unique_endpoints
        ],
    }
    metadata = {
        "freshness": None,
        "quality": {"score": 0.5, "completeness": 0.5},
        "degraded": True,
        "degraded_reasons": [payload["reason"]],
        "lineage": {"source": "auth.SCOPE_ENDPOINTS", "registry_path": str(CAPABILITY_PATH)},
    }
    return payload, metadata, "capability_fallback"


def _endpoint_category(endpoint: str, scope_map: dict[str, set[str]]) -> str:
    for scope, endpoints in scope_map.items():
        if scope == "read":
            continue
        if endpoint in endpoints:
            return scope
    return "unknown"



def wrap_response(payload: Any, metadata: dict[str, Any], source: str | None) -> dict[str, Any]:
    metadata = dict(metadata or {})
    metadata.setdefault("degraded_reasons", [])
    metadata.setdefault("lineage", [])
    return {
        "data": payload,
        "metadata": metadata,
        "source": source,
        "timestamp": utc_now_iso(),
    }



class NotFoundError(ValueError):
    """Raised when an endpoint or resource is not found (maps to 404)."""
    pass


ALLOWED_TUSHARE_APIS = frozenset({
    "daily", "weekly", "monthly", "adj_factor", "daily_basic",
    "trade_cal", "namechange", "income", "balancesheet", "cashflow",
    "forecast", "express", "fina_indicator", "fina_audit", "fina_mainbz",
    "dividend", "margin", "margin_detail", "block_trade", "anns_d",
    "moneyflow", "moneyflow_hsgt", "stk_limit", "suspend_d", "top10_holders",
    "top10_floatholders", "stk_holdernumber", "stk_holdertrade",
    "share_float", "repurchase", "pledge_stat", "pledge_detail",
    "index_daily", "index_dailybasic", "index_weekly", "index_monthly",
    "index_classify", "index_member", "index_member_all", "index_basic",
    "index_weight",
    "ths_daily", "ths_index", "ths_member", "ths_hot",
    "dc_index", "dc_daily", "dc_member",
    "limit_list", "limit_list_d", "limit_step", "broker_recommend",
    "stk_factor", "stk_factor_pro", "stk_auction", "cyq_perf", "cyq_chips",
    "stk_mins", "rt_min", "rt_fut_min",
    "stk_surv", "fund_daily", "fund_basic", "fund_nav", "fund_adj",
    "fund_portfolio", "fund_share", "fund_div",
    "fut_basic", "fut_daily", "fut_holding", "ft_limit",
    "cb_basic", "cb_daily", "cb_issue", "opt_basic", "opt_daily",
    "stock_basic", "stock_company", "bak_basic", "stk_managers",
    "concept", "concept_detail", "hs_const", "etf_basic",
    "top_inst", "top_list", "hk_daily", "hk_basic", "index_global",
    "hk_income", "hk_balancesheet", "hk_cashflow", "us_daily", "us_basic",
    "major_news", "news", "cctv_news", "report_rc",
    "fx_daily", "repo_daily", "margin_secs",
    "cn_cpi", "cn_gdp", "cn_m", "cn_pmi", "cn_ppi", "sf_month",
    "shibor", "shibor_lpr", "hibor", "libor",
    "us_tbr", "us_tltr", "us_tycr",
})


class Handler(BaseHTTPRequestHandler):
    server_version = f"SharedSignalsAPI/{VERSION}"

    def _send_json(self, data: dict[str, Any], status: int = 200) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Date", formatdate(usegmt=True))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            import logging

            logging.getLogger("sharedsignals.api").debug(
                "client disconnected before response body was written"
            )

    def _error(self, status: int, message: str) -> None:
        self._send_json({"error": message, "timestamp": utc_now_iso()}, status)

    def log_message(self, fmt: str, *args: Any) -> None:
        import logging
        logger = logging.getLogger("sharedsignals.api")
        logger.info(fmt % args)

    def do_OPTIONS(self) -> None:
        """Handle CORS preflight requests."""
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type, X-API-Key")
        self.send_header("Access-Control-Max-Age", "86400")
        self.end_headers()

    def _discard_request_body(self) -> None:
        raw_length = self.headers.get("Content-Length", "0") or "0"
        try:
            length = int(raw_length)
        except ValueError:
            length = 0
        if length > 0:
            self.rfile.read(min(length, 1_000_000))

    def _cache_invalidate_response(self) -> dict[str, Any]:
        reader.clear_caches()
        return {"status": "ok", "message": "all caches cleared", "timestamp": utc_now_iso()}

    def do_POST(self) -> None:
        _ensure_runtime_loaded()
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        params = {key: values[-1] for key, values in parse_qs(parsed.query, keep_blank_values=True).items()}
        self._discard_request_body()
        try:
            validate_json_query_params(params)
        except ValueError as exc:
            return self._error(400, str(exc))
        if path != "/cache/invalidate":
            return self._error(404, f"unknown endpoint: {path}")
        try:
            account = auth.authenticate(self.headers, self.client_address[0])
        except auth.AuthError as exc:
            return self._error(401, str(exc))
        if not auth.check_endpoint_scope(account, path):
            return self._error(403, f"scope does not grant access to {path}")
        try:
            auth.enforce_rate_limit(account["tenant_id"], account["tier"])
        except auth.RateLimitError as exc:
            return self._error(429, str(exc))
        return self._send_json(self._cache_invalidate_response())

    def do_GET(self) -> None:
        _ensure_runtime_loaded()
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        params = {key: values[-1] for key, values in parse_qs(parsed.query, keep_blank_values=True).items()}
        try:
            validate_json_query_params(params)
        except ValueError as exc:
            return self._error(400, str(exc))

        if path == "/health":
            try:
                account = auth.authenticate(self.headers, self.client_address[0])
                if not auth.check_endpoint_scope(account, path):
                    return self._error(403, "scope does not grant access to /health")
            except auth.AuthError:
                return self._error(401, "authentication required")
            return self._send_json(_get_health())

        try:
            account = auth.authenticate(self.headers, self.client_address[0])
        except auth.AuthError as exc:
            return self._error(401, str(exc))

        if not auth.check_endpoint_scope(account, path):
            return self._error(403, f"scope does not grant access to {path}")

        fingerprint = auth.request_fingerprint(path, params)
        cached = auth.get_cached_response(fingerprint)
        if cached is not None:
            return self._send_json(cached)

        try:
            auth.enforce_rate_limit(account["tenant_id"], account["tier"])
        except auth.RateLimitError as exc:
            return self._error(429, str(exc))

        claim_concurrency = getattr(auth, "claim_concurrency", None)
        release_concurrency = getattr(auth, "release_concurrency", None)
        concurrency_error = getattr(auth, "ConcurrencyLimitError", Exception)
        concurrency_claimed = False
        if claim_concurrency is not None:
            try:
                claim_concurrency(account)
                concurrency_claimed = True
            except concurrency_error as exc:
                return self._error(429, str(exc))

        try:
            try:
                response = self._dispatch(path, params)
            except NotFoundError as exc:
                return self._error(404, str(exc))
            except ValueError as exc:
                return self._error(400, str(exc))
            except FileNotFoundError as exc:
                return self._error(404, str(exc))
            except Exception as exc:  # noqa: BLE001
                import logging
                logger = logging.getLogger("sharedsignals.api")
                logger.error("Unhandled error on %s: %s", path, exc, exc_info=True)
                return self._error(500, "internal error")
        finally:
            if concurrency_claimed and release_concurrency is not None:
                release_concurrency(account["tenant_id"])

        auth.store_cached_response(fingerprint, response)
        self._send_json(response)

    def _dispatch(self, path: str, params: dict[str, str]) -> dict[str, Any]:
        if path == "/capabilities":
            if CAPABILITY_PATH.exists():
                payload, metadata, source = file_payload(CAPABILITY_PATH)
            else:
                payload, metadata, source = capability_fallback_payload()
            return wrap_response(payload, metadata, source)

        if path == "/market_data":
            ts_code = params.get("ts_code", "").strip()
            if not ts_code:
                raise ValueError("ts_code is required")
            rows = reader.get_market_data(
                ts_code=ts_code,
                start=params.get("start"),
                end=params.get("end"),
                freq=params.get("freq") or "daily",
            )
            payload, metadata, source = aggregate_metadata(rows)
            return wrap_response(payload, metadata, source)

        if path == "/events":
            symbol = (
                params.get("symbol", "").strip()
                or params.get("ts_code", "").strip()
                or params.get("subject_code", "").strip()
            )
            rows = reader.get_events(
                start=params.get("start"),
                end=params.get("end"),
                event_type=params.get("event_type", "").strip() or None,
                market=params.get("market", "").strip() or None,
                symbol=symbol or None,
                subject_code=params.get("subject_code", "").strip() or symbol or None,
                subject_type=params.get("subject_type", "").strip() or None,
            )
            rows = apply_row_limit(rows, params)
            payload, metadata, source = aggregate_metadata(rows)
            return wrap_response(payload, metadata, source)

        if path == "/sentiment":
            rows = reader.get_sentiment(start=params.get("start"), end=params.get("end"))
            rows = apply_row_limit(rows, params)
            payload, metadata, source = aggregate_metadata(rows)
            return wrap_response(payload, metadata, source)

        if path == "/fundamentals":
            ts_code = (params.get("ts_code", "") or params.get("symbol", "")).strip()
            if not ts_code:
                raise ValueError("ts_code is required")
            rows = reader.get_fundamentals(ts_code=ts_code)
            payload, metadata, source = aggregate_metadata(rows)
            return wrap_response(payload, metadata, source)

        if path == "/capital_flow":
            date = params.get("date", "").strip()
            start = params.get("start", "").strip()
            end = params.get("end", "").strip()
            ts_code = params.get("ts_code", "").strip() or None
            if not date and not start and not ts_code:
                raise ValueError("date, start, or ts_code is required")
            call_kwargs: dict[str, Any] = {}
            if start:
                call_kwargs["start_date"] = start
            if end:
                call_kwargs["end_date"] = end
            rows = reader.get_capital_flow(date=date or start or None, ts_code=ts_code, **call_kwargs)
            payload, metadata, source = aggregate_metadata(rows)
            return wrap_response(payload, metadata, source)

        if path == "/macro":
            rows = reader.get_macro_factors(start=params.get("start"), end=params.get("end"))
            payload, metadata, source = aggregate_metadata(rows)
            return wrap_response(payload, metadata, source)

        if path == "/crypto":
            symbol = params.get("symbol", "").strip()
            if not symbol:
                raise ValueError("symbol is required")
            rows = reader.get_crypto_klines(symbol=symbol)
            rows = apply_row_limit(rows, params)
            payload, metadata, source = aggregate_metadata(rows)
            return wrap_response(payload, metadata, source)

        if path == "/pm_markets":
            rows = reader.get_pm_markets(limit=to_int(params.get("limit"), 100))
            payload, metadata, source = aggregate_metadata(rows)
            return wrap_response(payload, metadata, source)

        if path == "/pm_prices":
            market_id = params.get("market_id", "").strip() or None
            rows = reader.get_pm_prices(
                market_id=market_id,
                limit=to_int(params.get("limit"), 200),
            )
            payload, metadata, source = aggregate_metadata(rows)
            return wrap_response(payload, metadata, source)

        if path == "/reference":
            table = params.get("table", "").strip()
            if not table:
                raise ValueError("table is required")
            rows = reader.get_reference(table=table)
            payload, metadata, source = aggregate_metadata(rows)
            return wrap_response(payload, metadata, source)

        if path == "/industry":
            ts_code = params.get("ts_code", "").strip()
            if not ts_code:
                raise ValueError("ts_code is required")
            rows = reader.get_industry(ts_code=ts_code)
            payload, metadata, source = aggregate_metadata(rows)
            return wrap_response(payload, metadata, source)

        if path == "/associations":
            ts_code = params.get("ts_code", "").strip() or None
            event_id = params.get("event_id", "").strip() or None
            if not ts_code and not event_id:
                raise ValueError("ts_code or event_id is required")
            rows = reader.get_associations(ts_code=ts_code, event_id=event_id)
            payload, metadata, source = aggregate_metadata(rows)
            return wrap_response(payload, metadata, source)

        if path == "/impacts":
            event_type = params.get("event_type", "").strip() or None
            target = params.get("target", "").strip() or None
            rows = reader.get_impacts(event_type=event_type, target=target)
            payload, metadata, source = aggregate_metadata(rows)
            return wrap_response(payload, metadata, source)

        if path == "/tushare":
            api_name = params.get("api_name", "").strip()
            if not api_name:
                raise ValueError("api_name is required")
            if api_name not in ALLOWED_TUSHARE_APIS:
                raise ValueError(f"api_name '{api_name}' is not in the allowed list")
            ts_code = params.get("ts_code", "").strip() or None
            rows = reader.get_tushare(
                api_name=api_name,
                ts_code=ts_code,
                start_date=params.get("start_date") or None,
                end_date=params.get("end_date") or None,
                **{k: v for k, v in params.items() if k not in ("api_name", "ts_code", "start_date", "end_date")},
            )
            rows = apply_row_limit(rows, params)
            payload, metadata, source = aggregate_metadata(rows)
            return wrap_response(payload, metadata, source)

        if path == "/is_trading_day":
            date = params.get("date", "").strip()
            if not date:
                raise ValueError("date is required")
            rows = reader.is_trading_day(date)
            payload, metadata, source = aggregate_metadata(rows)
            return wrap_response(payload, metadata, source)

        if path == "/realtime_5min":
            ts_code = params.get("ts_code", "").strip()
            date = params.get("date", "").strip() or None
            market = params.get("market", "").strip() or "Ashare"
            if not ts_code and not market:
                raise ValueError("ts_code or market is required")
            rows = reader.get_realtime_5min(ts_code=ts_code, date=date, market=market)
            rows = apply_row_limit(rows, params)
            payload, metadata, source = aggregate_metadata(rows)
            return wrap_response(payload, metadata, source)

        if path == "/cache/invalidate":
            return self._cache_invalidate_response()

        if path == "/cache/status":
            return {
                "generation": getattr(reader, "_CACHE_GENERATION", 0),
                "ttl_seconds": getattr(reader, "CACHE_TTL_SECONDS", None),
                "estimated_bytes": reader.cache_byte_estimate() if hasattr(reader, "cache_byte_estimate") else 0,
                "max_bytes": getattr(reader, "CACHE_MAX_BYTES", None),
                "entry_count": reader._cache_entry_count() if hasattr(reader, "_cache_entry_count") else 0,
                "functions_registered": len(getattr(reader, "_CACHED_FUNCTIONS", ())),
                "auth": auth.cache_stats(),
                "timestamp": utc_now_iso(),
            }

        raise NotFoundError(f"unknown endpoint: {path}")


class SharedSignalsHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    request_queue_size = 256

    def __init__(
        self,
        server_address: tuple[str, int],
        RequestHandlerClass: type[BaseHTTPRequestHandler],
        *,
        request_timeout: float = 30.0,
        max_threads: int = 20,
    ) -> None:
        super().__init__(server_address, RequestHandlerClass)
        self.request_timeout = max(float(request_timeout), 1.0)
        self.max_threads = max(int(max_threads), 1)
        self._thread_limiter = threading.BoundedSemaphore(self.max_threads)

    def process_request(self, request: Any, client_address: Any) -> None:
        if not self._thread_limiter.acquire(blocking=False):
            self._send_capacity_response(request)
            return
        request.settimeout(self.request_timeout)
        super().process_request(request, client_address)

    def process_request_thread(self, request: Any, client_address: Any) -> None:
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._thread_limiter.release()

    def _send_capacity_response(self, request: Any) -> None:
        payload = json.dumps(
            {"error": "server at capacity", "timestamp": utc_now_iso()},
            ensure_ascii=False,
        ).encode("utf-8")
        response = (
            b"HTTP/1.1 503 Service Unavailable\r\n"
            b"Content-Type: application/json; charset=utf-8\r\n"
            + f"Content-Length: {len(payload)}\r\n".encode("ascii")
            + b"Cache-Control: no-store\r\n"
            + b"Connection: close\r\n"
            + f"Date: {formatdate(usegmt=True)}\r\n\r\n".encode("ascii")
            + payload
        )
        try:
            request.sendall(response)
        finally:
            request.close()



def main() -> None:
    _ensure_runtime_loaded()
    httpd = SharedSignalsHTTPServer(
        (HOST, PORT),
        Handler,
        request_timeout=REQUEST_TIMEOUT,
        max_threads=MAX_THREADS,
    )
    print(f"SharedSignals API listening on {HOST}:{PORT}", flush=True)
    httpd.serve_forever()


if __name__ == "__main__":
    main()

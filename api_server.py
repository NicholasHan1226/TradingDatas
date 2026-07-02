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

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

auth: Any | None = None
reader: Any | None = None
_runtime_load_lock = threading.Lock()
HOST = os.environ.get("SHAREDSIGNALS_API_HOST", "0.0.0.0")
PORT = int(os.environ.get("SHAREDSIGNALS_API_PORT", "8082"))
VERSION = os.environ.get("SHAREDSIGNALS_API_VERSION", "1.0.0")
REQUEST_TIMEOUT = float(os.environ.get("SHAREDSIGNALS_REQUEST_TIMEOUT", "30"))
MAX_THREADS = int(os.environ.get("SHAREDSIGNALS_MAX_THREADS", "20"))
CAPABILITY_PATH = ROOT / "tools" / "capability_registry.json"
HEALTH_CACHE_SECONDS = 60


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
        PORT = int(os.environ.get("SHAREDSIGNALS_API_PORT", str(PORT)))
        VERSION = os.environ.get("SHAREDSIGNALS_API_VERSION", VERSION)
        REQUEST_TIMEOUT = float(os.environ.get("SHAREDSIGNALS_REQUEST_TIMEOUT", str(REQUEST_TIMEOUT)))
        MAX_THREADS = int(os.environ.get("SHAREDSIGNALS_MAX_THREADS", str(MAX_THREADS)))

        import auth as auth_module  # noqa: WPS433
        import reader as reader_module  # noqa: WPS433

        auth = auth_module
        reader = reader_module
        Handler.server_version = f"SharedSignalsAPI/{VERSION}"

# ---- Health check (lazy import to avoid pulling in health_check at startup) ----
_health_cache: dict[str, Any] | None = None
_health_cache_time: float = 0.0
_health_cache_lock = threading.Lock()



def _get_health() -> dict[str, Any]:
    """Return cached health status, refreshing if older than HEALTH_CACHE_SECONDS."""
    global _health_cache, _health_cache_time
    now = datetime.now(timezone.utc).timestamp()
    with _health_cache_lock:
        if _health_cache is not None and (now - _health_cache_time) < HEALTH_CACHE_SECONDS:
            return _health_cache

    try:
        from tools.health_check import get_health_status
        result = get_health_status(
            check_functions=True, check_data_freshness=True,
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



def aggregate_metadata(rows: Any) -> tuple[Any, dict[str, Any], str | None]:
    if not isinstance(rows, list):
        return rows, {"freshness": None, "quality": None, "degraded": False}, None

    if not rows:
        return [], {"freshness": None, "quality": None, "degraded": False}, None

    if not all(isinstance(row, dict) and "data" in row for row in rows):
        return rows, {"freshness": None, "quality": None, "degraded": False}, None

    data_rows = [row.get("data") for row in rows]
    degraded = any(bool(row.get("degraded")) for row in rows)
    freshness_rows = [row.get("freshness") for row in rows if isinstance(row.get("freshness"), dict)]
    quality_rows = [row.get("quality") for row in rows if isinstance(row.get("quality"), dict)]
    sources = []
    for row in rows:
        provenance = row.get("provenance") if isinstance(row, dict) else None
        if isinstance(provenance, dict) and provenance.get("source_id"):
            sources.append(str(provenance["source_id"]))
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

    return data_rows, {"freshness": freshness, "quality": quality, "degraded": degraded}, source



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



def wrap_response(payload: Any, metadata: dict[str, Any], source: str | None) -> dict[str, Any]:
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
    "dividend", "margin", "margin_detail", "block_trade",
    "moneyflow", "stk_limit", "suspend_d", "top10_holders",
    "top10_floatholders", "stk_holdernumber", "stk_holdertrade",
    "share_float", "repurchase", "pledge_stat", "pledge_detail",
    "index_daily", "index_dailybasic", "index_weekly", "index_monthly",
    "index_classify", "index_member", "index_member_all",
    "ths_daily", "ths_index", "ths_member", "ths_hot",
    "dc_index", "dc_daily", "dc_member",
    "limit_list", "limit_list_d", "limit_step", "broker_recommend",
    "stk_factor", "stk_factor_pro", "cyq_perf", "cyq_chips",
    "stk_surv", "fund_daily", "fund_basic", "fund_nav", "fund_adj",
    "fund_portfolio", "fund_share", "fund_div",
    "fut_basic", "fut_daily", "fut_holding", "ft_limit",
    "cb_basic", "cb_daily", "cb_issue", "opt_basic", "opt_daily",
    "stock_basic", "stock_company", "bak_basic", "stk_managers",
    "top_inst", "top_list", "hk_daily", "hk_basic", "index_global",
    "us_daily", "us_basic", "major_news", "news", "cctv_news",
    "fx_daily", "repo_daily", "margin_secs",
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
        self.wfile.write(body)

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
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type, X-API-Key")
        self.send_header("Access-Control-Max-Age", "86400")
        self.end_headers()

    def do_GET(self) -> None:
        _ensure_runtime_loaded()
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        params = {key: values[-1] for key, values in parse_qs(parsed.query, keep_blank_values=True).items()}

        if path == "/health":
            try:
                account = auth.authenticate(self.headers, self.client_address[0])
                if not auth.check_endpoint_scope(account, path):
                    return self._error(403, "scope does not grant access to /health")
            except auth.AuthError:
                return self._send_json({"status": "ok", "version": VERSION, "detail": "authenticate for full health report"})
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

        auth.store_cached_response(fingerprint, response)
        self._send_json(response)

    def _dispatch(self, path: str, params: dict[str, str]) -> dict[str, Any]:
        if path == "/capabilities":
            payload, metadata, source = file_payload(CAPABILITY_PATH)
            return wrap_response(payload, metadata, source)

        if path == "/market_data":
            ts_code = params.get("ts_code", "").strip()
            if not ts_code:
                raise ValueError("ts_code is required")
            rows = reader.get_market_data(ts_code=ts_code, start=params.get("start"), end=params.get("end"))
            payload, metadata, source = aggregate_metadata(rows)
            return wrap_response(payload, metadata, source)

        if path == "/events":
            rows = reader.get_events(start=params.get("start"), end=params.get("end"))
            payload, metadata, source = aggregate_metadata(rows)
            return wrap_response(payload, metadata, source)

        if path == "/sentiment":
            rows = reader.get_sentiment(start=params.get("start"), end=params.get("end"))
            payload, metadata, source = aggregate_metadata(rows)
            return wrap_response(payload, metadata, source)

        if path == "/fundamentals":
            ts_code = params.get("ts_code", "").strip()
            if not ts_code:
                raise ValueError("ts_code is required")
            rows = reader.get_fundamentals(ts_code=ts_code)
            payload, metadata, source = aggregate_metadata(rows)
            return wrap_response(payload, metadata, source)

        if path == "/capital_flow":
            date = params.get("date", "").strip()
            if not date:
                raise ValueError("date is required")
            rows = reader.get_capital_flow(date=date)
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
            payload, metadata, source = aggregate_metadata(rows)
            return wrap_response(payload, metadata, source)

        if path == "/pm_markets":
            rows = reader.get_pm_markets(limit=to_int(params.get("limit"), 100))
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
            if not ts_code:
                raise ValueError("ts_code is required")
            date = params.get("date", "").strip()
            rows = reader.get_realtime_5min(ts_code=ts_code, date=date)
            payload, metadata, source = aggregate_metadata(rows)
            return wrap_response(payload, metadata, source)

        if path == "/cache/invalidate":
            reader.clear_caches()
            return {"status": "ok", "message": "all caches cleared", "timestamp": utc_now_iso()}

        if path == "/cache/status":
            return {
                "generation": reader._CACHE_GENERATION,
                "ttl_seconds": reader.CACHE_TTL_SECONDS,
                "functions_registered": len(reader._CACHED_FUNCTIONS),
                "auth": auth.cache_stats(),
                "timestamp": utc_now_iso(),
            }

        raise NotFoundError(f"unknown endpoint: {path}")


class SharedSignalsHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

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

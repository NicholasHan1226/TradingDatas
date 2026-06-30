#!/usr/bin/env python3

"""http.server based REST API for SharedSignals."""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from email.utils import formatdate
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse


# ---- Auto-load .env on import ----
import os as _os
_env_file = __import__("pathlib").Path(__file__).resolve().parent / ".env"
if _env_file.exists():
    with open(_env_file) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                if _line.startswith("export "):
                    _line = _line[7:]
                _key, _, _val = _line.partition("=")
                _os.environ[_key.strip()] = _val.strip().strip('"').strip("'")
# ---- end env loader ----
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import auth  # noqa: E402
import reader  # noqa: E402

HOST = os.environ.get("SHAREDSIGNALS_API_HOST", "0.0.0.0")
PORT = int(os.environ.get("SHAREDSIGNALS_API_PORT", "8082"))
VERSION = os.environ.get("SHAREDSIGNALS_API_VERSION", "1.0.0")
CAPABILITY_PATH = ROOT / "tools" / "capability_registry.json"



def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()



def to_int(value: Any, default: int) -> int:
    try:
        return int(value)
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
        return

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        params = {key: values[-1] for key, values in parse_qs(parsed.query, keep_blank_values=True).items()}

        if path == "/health":
            return self._send_json({"status": "ok", "version": VERSION})

        try:
            account = auth.authenticate(self.headers, self.client_address[0])
        except auth.AuthError as exc:
            return self._error(401, str(exc))

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
        except ValueError as exc:
            return self._error(400, str(exc))
        except FileNotFoundError as exc:
            return self._error(404, str(exc))
        except Exception as exc:  # noqa: BLE001
            return self._error(500, f"internal error: {exc}")

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

        if path == "/tushare":
            api_name = params.get("api_name", "").strip()
            if not api_name:
                raise ValueError("api_name is required")
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

        raise ValueError(f"unknown endpoint: {path}")



def main() -> None:
    httpd = HTTPServer((HOST, PORT), Handler)
    print(f"SharedSignals API listening on {HOST}:{PORT}", flush=True)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SharedSignals lightweight HTTP API server.

Provides read-only endpoints for SharedSignals capability and health data.
No write endpoints. No authentication for internal network use.

Usage:
  python3 tools/api_server.py [--port 8900] [--host 0.0.0.0]

Endpoints:
  GET /health          — Liveness check
  GET /capabilities    — Full capability registry (from capability_registry.json)
  GET /capabilities/summary — Summary only
  GET /capabilities/group/{group} — Filter by group
  GET /api_contract    — API_CONTRACT.md rendered as JSON
"""
from __future__ import annotations

import argparse
import json
import os
import socketserver
import sys
import threading
from datetime import datetime, timezone
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

SHARED_SIGNALS = Path(os.environ.get("SHARED_SIGNALS_ROOT", "/opt/investment/SharedSignals"))
REGISTRY_PATH = Path(os.environ.get("CAPABILITY_REGISTRY_PATH",
                                     str(SHARED_SIGNALS / "tools" / "capability_registry.json")))
CONTRACT_PATH = SHARED_SIGNALS / "docs" / "API_CONTRACT.md"

SERVER_VERSION = "1.0.0"


def load_registry() -> dict[str, Any] | None:
    """Load the latest capability registry."""
    if not REGISTRY_PATH.exists():
        return None
    try:
        with open(REGISTRY_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def load_contract_text() -> str | None:
    """Load the API contract as plain text."""
    if not CONTRACT_PATH.exists():
        return None
    try:
        return CONTRACT_PATH.read_text(encoding="utf-8")
    except OSError:
        return None


def json_response(handler: BaseHTTPRequestHandler, data: Any, status: int = 200) -> None:
    """Send a JSON response."""
    body = json.dumps(data, indent=2, ensure_ascii=False, default=str)
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.send_header("X-SharedSignals-Version", SERVER_VERSION)
    handler.end_headers()
    handler.wfile.write(body.encode("utf-8"))


def text_response(handler: BaseHTTPRequestHandler, text: str, status: int = 200,
                  content_type: str = "text/markdown; charset=utf-8") -> None:
    """Send a text response."""
    handler.send_response(status)
    handler.send_header("Content-Type", content_type)
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.end_headers()
    handler.wfile.write(text.encode("utf-8"))


class SharedSignalsHandler(BaseHTTPRequestHandler):
    """HTTP request handler for SharedSignals API."""

    def log_message(self, format: str, *args: Any) -> None:
        """Override to add timestamp."""
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        sys.stderr.write(f"[{ts}] {self.client_address[0]} - {format % args}\n")

    def _route(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"

        # GET /health
        if path == "/health":
            return self._handle_health()

        # GET /capabilities
        if path == "/capabilities":
            return self._handle_capabilities()

        # GET /capabilities/summary
        if path == "/capabilities/summary":
            return self._handle_capabilities_summary()

        # GET /capabilities/group/{group}
        if path.startswith("/capabilities/group/"):
            group = path[len("/capabilities/group/"):]
            return self._handle_capabilities_group(group)

        # GET /api_contract
        if path == "/api_contract":
            return self._handle_api_contract()

        # 404
        json_response(self, {"error": "not found", "path": path}, 404)

    def _handle_health(self) -> None:
        registry = load_registry()
        health = {
            "service": "SharedSignals",
            "version": SERVER_VERSION,
            "status": "ok",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "registry_available": registry is not None,
        }
        if registry:
            health["capabilities_summary"] = registry.get("summary", {})
        json_response(self, health)

    def _handle_capabilities(self) -> None:
        registry = load_registry()
        if registry is None:
            json_response(self, {"error": "capability registry not found", "hint": "Run tools/capability_scan.py first"}, 503)
            return
        json_response(self, registry)

    def _handle_capabilities_summary(self) -> None:
        registry = load_registry()
        if registry is None:
            json_response(self, {"error": "capability registry not found"}, 503)
            return
        json_response(self, registry.get("summary", {}))

    def _handle_capabilities_group(self, group: str) -> None:
        registry = load_registry()
        if registry is None:
            json_response(self, {"error": "capability registry not found"}, 503)
            return
        endpoints = registry.get("endpoints", [])
        filtered = [ep for ep in endpoints if ep.get("group") == group]
        json_response(self, {
            "group": group,
            "endpoints": filtered,
            "count": len(filtered),
        })

    def _handle_api_contract(self) -> None:
        text = load_contract_text()
        if text is None:
            json_response(self, {"error": "API contract not found", "hint": "Run tools/capability_scan.py first"}, 503)
            return
        # Support ?format=json
        parsed = urlparse(self.path)
        from urllib.parse import parse_qs
        qs = parse_qs(parsed.query)
        if qs.get("format", [""])[0] == "json":
            registry = load_registry()
            if registry:
                json_response(self, {"contract": text, "registry": registry})
                return
        text_response(self, text)

    def do_GET(self) -> None:
        try:
            self._route()
        except Exception as e:
            json_response(self, {"error": "internal server error", "detail": str(e)}, 500)

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()


class ThreadedHTTPServer(socketserver.ThreadingMixIn, HTTPServer):
    """Handle requests in separate threads."""
    daemon_threads = True
    allow_reuse_address = True


def main() -> int:
    parser = argparse.ArgumentParser(description="SharedSignals API Server")
    parser.add_argument("--port", type=int, default=8900, help="Listen port (default: 8900)")
    parser.add_argument("--host", type=str, default="0.0.0.0", help="Bind address (default: 0.0.0.0)")
    args = parser.parse_args()

    server = ThreadedHTTPServer((args.host, args.port), SharedSignalsHandler)
    print(f"[api_server] SharedSignals API v{SERVER_VERSION}")
    print(f"[api_server] Listening on http://{args.host}:{args.port}")
    print(f"[api_server] Endpoints:")
    print(f"  GET /health")
    print(f"  GET /capabilities")
    print(f"  GET /capabilities/summary")
    print(f"  GET /capabilities/group/{{group}}")
    print(f"  GET /api_contract")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[api_server] Shutting down...")
        server.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())

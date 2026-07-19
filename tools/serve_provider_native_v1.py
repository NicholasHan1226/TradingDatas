#!/usr/bin/env python3
"""Serve only the provider-neutral V1 catalog/query data plane."""

from __future__ import annotations

import os
from typing import NoReturn


EXPECTED_SURFACE = "provider-native-v1-only"
EXPECTED_PROFILE = "provider-native-v1-internal"


def _require_fixed_runtime_environment() -> None:
    expected = {
        "REAL_TRADING_ENABLED": "false",
        "SHAREDSIGNALS_API_HOST": "127.0.0.1",
        "SHAREDSIGNALS_API_PORT": "18082",
        "SHAREDSIGNALS_API_SURFACE": EXPECTED_SURFACE,
        "SHAREDSIGNALS_INTERNAL_RUNTIME_PROFILE": EXPECTED_PROFILE,
        "SHAREDSIGNALS_LOCALHOST_BYPASS": "0",
    }
    for name, value in expected.items():
        if os.environ.get(name) != value:
            raise SystemExit(f"invalid provider-native runtime setting: {name}")


_require_fixed_runtime_environment()

# Mark the legacy .env bootstrap as completed against an empty file before
# importing the shared V1 protocol implementation.  Runtime configuration is
# supplied only by the two systemd EnvironmentFile contracts.
import env_bootstrap  # noqa: E402

env_bootstrap.bootstrap_sharedsignals_env(path=os.devnull)

import api_server  # noqa: E402


class ProviderNativeV1Handler(api_server.Handler):
    """Route every HTTP verb through the bounded V1 protocol dispatcher."""

    def do_GET(self) -> None:  # noqa: N802
        self._handle_v1("GET")

    def do_POST(self) -> None:  # noqa: N802
        self._handle_v1("POST")

    def do_OPTIONS(self) -> None:  # noqa: N802
        self._handle_v1("OPTIONS")

    def do_HEAD(self) -> None:  # noqa: N802
        self._handle_v1("HEAD")

    def do_PUT(self) -> None:  # noqa: N802
        self._handle_v1("PUT")

    def do_PATCH(self) -> None:  # noqa: N802
        self._handle_v1("PATCH")

    def do_DELETE(self) -> None:  # noqa: N802
        self._handle_v1("DELETE")

    def send_error(
        self,
        code: int,
        message: str | None = None,
        explain: str | None = None,
    ) -> None:
        if code == 501:
            self._handle_v1(str(getattr(self, "command", "")))
            return
        super().send_error(code, message, explain)


def main() -> NoReturn:
    api_server._ensure_process_config_loaded()
    if api_server.HOST != "127.0.0.1" or api_server.PORT != 18082:
        raise SystemExit("provider-native V1 listener is not fixed to loopback")
    httpd = api_server.SharedSignalsHTTPServer(
        (api_server.HOST, api_server.PORT),
        ProviderNativeV1Handler,
        request_timeout=api_server.REQUEST_TIMEOUT,
        max_threads=api_server.MAX_THREADS,
    )
    print(
        "SharedSignals provider-native V1 API listening on 127.0.0.1:18082",
        flush=True,
    )
    httpd.serve_forever()
    raise AssertionError("serve_forever returned unexpectedly")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Alpaca paper credential resolution for quarantined US integration.

The integration is disabled unless US_ALPACA_PAPER_ENABLED=1 is set.
Only paper-specific environment variables are accepted:
  ALPACA_PAPER_API_KEY
  ALPACA_PAPER_SECRET_KEY

Generic or live Alpaca variables are rejected to avoid accidental live routing.
"""

from __future__ import annotations

import os

ENV_KEY_NAMES = ("ALPACA_PAPER_API_KEY",)
ENV_SECRET_NAMES = ("ALPACA_PAPER_SECRET_KEY",)
GENERIC_LIVE_ENV_NAMES = ("ALPACA_API_KEY", "ALPACA_SECRET_KEY", "APCA_API_KEY_ID", "APCA_API_SECRET_KEY")
ENABLE_FLAG = "US_ALPACA_PAPER_ENABLED"


def paper_integration_enabled() -> bool:
    """Return True only when the quarantined paper integration is explicitly enabled."""
    return os.environ.get(ENABLE_FLAG, "").strip() == "1"


def read_alpaca_config() -> dict[str, str]:
    """Resolve Alpaca paper credentials.

    Returns {"api_key": str, "secret_key": str}.
    Raises RuntimeError if integration is disabled or credentials are unsafe.
    """
    if not paper_integration_enabled():
        raise RuntimeError(f"Alpaca paper integration disabled. Set {ENABLE_FLAG}=1 only for isolated paper tests.")
    generic_present = [name for name in GENERIC_LIVE_ENV_NAMES if os.environ.get(name, "").strip()]
    if generic_present:
        raise RuntimeError(
            "Generic/live Alpaca environment variables are not accepted for US. "
            f"Unset {', '.join(generic_present)} and use ALPACA_PAPER_API_KEY + ALPACA_PAPER_SECRET_KEY."
        )

    api_key = _first_env(ENV_KEY_NAMES)
    secret_key = _first_env(ENV_SECRET_NAMES)
    if api_key and secret_key:
        return {"api_key": api_key, "secret_key": secret_key}

    raise RuntimeError(
        "Alpaca paper credentials not found. Set ALPACA_PAPER_API_KEY + "
        "ALPACA_PAPER_SECRET_KEY only after US_ALPACA_PAPER_ENABLED=1."
    )


def is_configured() -> bool:
    """Check if Alpaca credentials are available (non-fatal)."""
    try:
        read_alpaca_config()
        return True
    except RuntimeError:
        return False


def safe_read_alpaca_config() -> dict[str, str]:
    """Read credentials, return {"api_key": "", "secret_key": ""} if missing."""
    try:
        return read_alpaca_config()
    except RuntimeError:
        return {"api_key": "", "secret_key": ""}


# ---------------------------------------------------------------------------
# Internal
# ---------------------------------------------------------------------------

def _first_env(key_names: tuple[str, ...]) -> str:
    for name in key_names:
        val = os.environ.get(name, "").strip()
        if val:
            return val
    return ""

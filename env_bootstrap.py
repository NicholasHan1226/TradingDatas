#!/usr/bin/env python3
"""SharedSignals process-level environment bootstrap."""

from __future__ import annotations

import os
import threading
import logging
import math
from pathlib import Path
from typing import MutableMapping

_LOADED = False
_LOAD_LOCK = threading.Lock()
logger = logging.getLogger(__name__)


def parse_env_file(path: str | Path) -> dict[str, str]:
    """Parse a simple KEY=VALUE .env file without mutating os.environ."""
    env_path = Path(path)
    values: dict[str, str] = {}
    if not env_path.exists():
        return values

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        key, _, value = line.partition("=")
        key = key.strip()
        if not key:
            continue
        values[key] = value.strip().strip('"').strip("'")
    return values


def bootstrap_sharedsignals_env(
    path: str | Path | None = None,
    *,
    override: bool = False,
    environ: MutableMapping[str, str] | None = None,
) -> dict[str, str]:
    """Load SharedSignals .env once, setting only missing keys by default."""
    global _LOADED
    with _LOAD_LOCK:
        if _LOADED and not override:
            return {}

        env_path = Path(path) if path is not None else Path(__file__).resolve().parent / ".env"
        parsed = parse_env_file(env_path)
        target = os.environ if environ is None else environ
        applied: dict[str, str] = {}

        for key, value in parsed.items():
            if override or key not in target:
                target[key] = value
                applied[key] = value

        _LOADED = True
        return applied


def env_int(
    name: str,
    default: int,
    *,
    min_value: int | None = None,
    max_value: int | None = None,
    environ: MutableMapping[str, str] | None = None,
) -> int:
    """Read an integer env var with fallback and optional bounds."""
    source = os.environ if environ is None else environ
    raw = source.get(name)
    if raw is None or str(raw).strip() == "":
        return default
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        logger.warning("Invalid integer env %s=%r; using default %r", name, raw, default)
        return default
    if min_value is not None and value < min_value:
        return min_value
    if max_value is not None and value > max_value:
        return max_value
    return value


def env_float(
    name: str,
    default: float,
    *,
    min_value: float | None = None,
    max_value: float | None = None,
    environ: MutableMapping[str, str] | None = None,
) -> float:
    """Read a finite float env var with fallback and optional bounds."""
    source = os.environ if environ is None else environ
    raw = source.get(name)
    if raw is None or str(raw).strip() == "":
        return default
    try:
        value = float(str(raw).strip())
    except (TypeError, ValueError):
        logger.warning("Invalid float env %s=%r; using default %r", name, raw, default)
        return default
    if not math.isfinite(value):
        logger.warning("Non-finite float env %s=%r; using default %r", name, raw, default)
        return default
    if min_value is not None and value < min_value:
        return min_value
    if max_value is not None and value > max_value:
        return max_value
    return value


def env_bool(
    name: str,
    default: bool,
    *,
    environ: MutableMapping[str, str] | None = None,
) -> bool:
    """Read a boolean env var with common true/false spellings."""
    source = os.environ if environ is None else environ
    raw = source.get(name)
    if raw is None or str(raw).strip() == "":
        return default
    value = str(raw).strip().lower()
    if value in {"1", "true", "yes", "y", "on"}:
        return True
    if value in {"0", "false", "no", "n", "off"}:
        return False
    logger.warning("Invalid boolean env %s=%r; using default %r", name, raw, default)
    return default

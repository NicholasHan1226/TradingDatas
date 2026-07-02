#!/usr/bin/env python3
"""SharedSignals process-level environment bootstrap."""

from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import MutableMapping

_LOADED = False
_LOAD_LOCK = threading.Lock()


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

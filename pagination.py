"""Opaque keyset cursor helpers shared by read-only API endpoints."""

from __future__ import annotations

import base64
import json
from collections.abc import Sequence
from typing import Any


def encode_cursor(scope: str, snapshot_id: str, sort_key: Sequence[Any]) -> str:
    raw = json.dumps(
        {"v": 1, "scope": scope, "snapshot_id": snapshot_id, "key": list(sort_key)},
        separators=(",", ":"),
    ).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(cursor: str, *, scope: str, snapshot_id: str = "") -> tuple[Any, ...]:
    try:
        payload = json.loads(
            base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
        )
    except Exception as exc:
        raise ValueError("invalid cursor") from exc
    if (
        not isinstance(payload, dict)
        or payload.get("v") != 1
        or payload.get("scope") != scope
        or not isinstance(payload.get("key"), list)
    ):
        raise ValueError("invalid cursor")
    if snapshot_id and payload.get("snapshot_id") != snapshot_id:
        raise ValueError("cursor snapshot mismatch")
    return tuple(payload["key"])

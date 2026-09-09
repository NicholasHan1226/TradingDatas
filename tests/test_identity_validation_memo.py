"""Repeated request identities may share only one bounded validation pass."""

import copy
import json
from datetime import datetime, timezone

import pytest

from storage import receipt_projection as p
from tests import test_receipt_projection as fixtures


def identity(value=1):
    return {"request_identity": {
        "fanout_parameter": "symbol", "fanout_values": [value],
        "page_index": 0, "page_offset": None, "request_variant": {},
    }}


def test_identity_memo_preserves_primitive_types_and_complete_content():
    cache = {}
    for value in (1, 1.0, True, "1"):
        payload = identity(value)
        actual = p._validated_request_identity_cached(payload, cache)
        assert type(actual.fanout_values[0]) is type(value)
        assert actual.canonical_payload() == p._validate_request_identity(payload).canonical_payload()
    assert len(cache) == 4
    changed = identity()
    changed["request_identity"]["page_index"] = 2
    assert p._validated_request_identity_cached(changed, cache).page_index == 2
    assert len(cache) == 5


@pytest.mark.parametrize("change", ["bool_index", "extra", "missing", "cursor"])
def test_identity_memo_rejects_changed_invalid_identity(change):
    cache = {}
    payload = identity()
    p._validated_request_identity_cached(payload, cache)
    bad = copy.deepcopy(payload)
    raw = bad["request_identity"]
    if change == "bool_index":
        raw["page_index"] = True
    elif change == "extra":
        raw["unknown"] = "bad"
    elif change == "missing":
        del raw["fanout_values"]
    else:
        raw["batch_count"] = 1
    with pytest.raises(ValueError):
        p._validated_request_identity_cached(bad, cache)
    assert len(cache) == 1


def test_identity_memo_is_bounded(monkeypatch):
    monkeypatch.setattr(p, "_IDENTITY_VALIDATION_CACHE_LIMIT", 2)
    cache = {}
    for value in range(6):
        assert p._validated_request_identity_cached(identity(value), cache).fanout_values == (value,)
    assert len(cache) == 2


def test_projection_identity_cache_is_pass_local_and_tampering_fails(monkeypatch):
    conn, registry, ids = fixtures._catalog_retry_boundary(monkeypatch, calls=(), newer_count=10)
    dataset = registry.datasets[0]
    now = datetime(2026, 7, 15, 1, tzinfo=timezone.utc)
    calls = []
    original = p._validate_request_identity

    def count(payload):
        calls.append(payload["request_identity"])
        return original(payload)

    monkeypatch.setattr(p, "_validate_request_identity", count)
    try:
        first = p.project_dataset_runtime(conn, dataset, now=now, registry=registry)
        assert len(calls) == 1
        calls.clear()
        second = p.project_dataset_runtime(conn, dataset, now=now, registry=registry)
        assert first == second and len(calls) == 1
        notes, = conn.execute("SELECT notes FROM market_ingest_runs WHERE run_id=?", (ids[-1],)).fetchone()
        payload = json.loads(notes)
        payload["request_identity"]["page_index"] = True
        conn.execute("UPDATE market_ingest_runs SET notes=? WHERE run_id=?",
                     (json.dumps(payload, sort_keys=True, separators=(",", ":")), ids[-1]))
        conn.commit()
        assert p.project_dataset_runtime(conn, dataset, now=now, registry=registry).state == "failed"
    finally:
        conn.close()

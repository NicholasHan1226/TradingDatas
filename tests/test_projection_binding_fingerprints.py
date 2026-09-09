"""Per-projection binding digests never replace raw receipt authority."""

import builtins
from dataclasses import replace
from datetime import datetime, timezone

import storage.receipt_projection as projection
from dataset_registry import ProviderBinding
from tests import test_receipt_projection as existing

NOW = datetime(2026, 7, 15, 1, tzinfo=timezone.utc)


def _receipt(monkeypatch):
    conn = existing._memory_db()
    dataset = existing._dataset()
    receipt = existing._insert_receipt(
        monkeypatch,
        conn,
        status="success",
        attempt_id="fingerprint-case",
        started_at="2026-07-15T00:00:00+00:00",
        finished_at="2026-07-15T00:01:00+00:00",
        data_through="20260715",
    )
    row = projection._scan_ingest_run_rows_by_ids(conn, (receipt,))[0]
    return conn, dataset, receipt, row


def test_local_binding_fingerprint_preserves_new_instance_content_and_raw_keys(
    monkeypatch,
):
    conn, dataset, receipt, row = _receipt(monkeypatch)
    binding = dataset.provider_bindings[0]
    original = projection._validate_receipt_row
    calls = []

    def counted(*args):
        calls.append(args)
        return original(*args)

    monkeypatch.setattr(projection, "_validate_receipt_row", counted)
    cache = {}
    known = frozenset((dataset.dataset_id,))

    def read(d, b, r):
        fingerprints = projection._binding_validation_fingerprints(d, b)
        actual = projection._validate_receipt_row_memoized(
            r, d, known, NOW, b, cache, fingerprints
        )
        assert actual == original(r, d, known, NOW, b)
        return actual

    read(dataset, binding, row)
    equal_binding = replace(binding)
    equal_dataset = replace(dataset, provider_bindings=(equal_binding,))
    read(equal_dataset, equal_binding, row)
    read(equal_dataset, None, row)
    assert len(calls) == 1
    changed = replace(binding, adapter_version="different-adapter")
    read(dataset, changed, row)
    assert len(calls) == 2
    existing._tamper_notes(conn, receipt, "status", "failed")
    rewritten = projection._scan_ingest_run_rows_by_ids(conn, (receipt,))[0]
    read(dataset, binding, rewritten)
    assert len(calls) == 3
    conn.close()


def test_binding_repr_is_once_per_local_pass_and_not_cached_between_calls(monkeypatch):
    conn, dataset, _, row = _receipt(monkeypatch)
    binding = dataset.provider_bindings[0]
    seen = []

    def tracked_repr(value):
        if isinstance(value, ProviderBinding):
            seen.append(value)
        return builtins.repr(value)

    monkeypatch.setattr(projection, "repr", tracked_repr, raising=False)
    cache = {}

    def project(d):
        return projection._trusted_receipts_for_evidence(
            d,
            now=NOW,
            known_dataset_ids=frozenset((d.dataset_id,)),
            rows=(row,) * 25,
            expected_binding=d.provider_bindings[0],
            validation_cache=cache,
        )

    first = project(dataset)
    assert len(seen) == 1
    assert len(first[0]) == 25 and not first[1]
    second = project(dataset)
    assert len(seen) == 2
    assert second == first
    # A later projection recomputes every binding field, even if the registry
    # object is a new instance and the long-lived receipt validation memo stays.
    changed = replace(binding, adapter_version="later-version")
    project(replace(dataset, provider_bindings=(changed,)))
    assert len(seen) == 3
    conn.close()

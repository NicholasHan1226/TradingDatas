from __future__ import annotations

import json
import sqlite3

from dataset_registry import (
    BINANCE_SPOT_CANARY_REGISTRY_PATH,
    load_dataset_registry,
)
from tools.backfill_crypto_partition_value import (
    backfill_partition_values,
    canonical_rfc3339_milliseconds,
)


def _schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE TABLE provider_dataset_rows ("
        "dataset_id TEXT NOT NULL, provider TEXT NOT NULL, "
        "schema_major INTEGER NOT NULL, ingested_schema_version TEXT NOT NULL, "
        "row_key TEXT NOT NULL, observed_at TEXT, partition_value TEXT, "
        "payload_json TEXT NOT NULL, payload_hash TEXT NOT NULL, "
        "quality_state TEXT NOT NULL, quality_issues_json TEXT NOT NULL, "
        "collected_at TEXT NOT NULL, receipt_id TEXT NOT NULL, "
        "revision INTEGER NOT NULL, "
        "PRIMARY KEY(dataset_id, provider, schema_major, row_key)"
        ") WITHOUT ROWID"
    )


def _insert(
    conn: sqlite3.Connection,
    *,
    dataset_id: str,
    row_key: str,
    partition_value: str | None,
    open_time: str,
) -> None:
    payload = json.dumps(
        {
            "symbol": "BTCUSDT",
            "open_time": open_time,
            "close_time": "2026-07-28T08:44:59.999Z",
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    conn.execute(
        "INSERT INTO provider_dataset_rows VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,1)",
        (
            dataset_id,
            "binance_spot",
            1,
            "1.0.0",
            row_key,
            open_time,
            partition_value,
            payload,
            "a" * 64,
            "valid",
            "[]",
            "2026-07-28T08:50:00Z",
            f"receipt:{row_key}",
        ),
    )


def test_canonical_rfc3339_milliseconds_normalizes_aware_values() -> None:
    assert (
        canonical_rfc3339_milliseconds("2026-07-28T08:40:00+00:00")
        == "2026-07-28T08:40:00.000Z"
    )
    assert (
        canonical_rfc3339_milliseconds("2026-07-28T08:40:00.000Z")
        == "2026-07-28T08:40:00.000Z"
    )
    assert canonical_rfc3339_milliseconds("not-a-time") is None
    assert canonical_rfc3339_milliseconds(None) is None


def test_backfill_partition_values_is_idempotent_and_dataset_scoped() -> None:
    registry = load_dataset_registry(BINANCE_SPOT_CANARY_REGISTRY_PATH)
    bars = registry.resolve("crypto.spot.binance.btcusdt.5m")
    other = registry.resolve("crypto.spot.binance.btcusdt.book_ticker")

    conn = sqlite3.connect(":memory:")
    _schema(conn)
    _insert(
        conn,
        dataset_id=bars.dataset_id,
        row_key="null-partition",
        partition_value=None,
        open_time="2026-07-28T08:40:00.000Z",
    )
    _insert(
        conn,
        dataset_id=bars.dataset_id,
        row_key="alt-partition",
        partition_value="2026-07-28T08:40:00+00:00",
        open_time="2026-07-28T08:40:00.000Z",
    )
    _insert(
        conn,
        dataset_id=bars.dataset_id,
        row_key="canonical-partition",
        partition_value="2026-07-28T08:45:00.000Z",
        open_time="2026-07-28T08:45:00.000Z",
    )
    _insert(
        conn,
        dataset_id=bars.dataset_id,
        row_key="unparseable",
        partition_value=None,
        open_time="garbage",
    )
    _insert(
        conn,
        dataset_id=other.dataset_id,
        row_key="other-dataset",
        partition_value=None,
        open_time="2026-07-28T08:40:00.000Z",
    )
    conn.commit()

    summary = backfill_partition_values(conn, registry)
    assert summary["rows_updated"] == 2
    assert summary["datasets"][bars.dataset_id] == {
        "total": 4,
        "backfill": 2,
        "already_canonical": 1,
        "unparseable": 1,
    }
    assert (
        conn.execute(
            "SELECT partition_value FROM provider_dataset_rows WHERE row_key = ?",
            ("null-partition",),
        ).fetchone()[0]
        == "2026-07-28T08:40:00.000Z"
    )
    assert (
        conn.execute(
            "SELECT partition_value FROM provider_dataset_rows WHERE row_key = ?",
            ("alt-partition",),
        ).fetchone()[0]
        == "2026-07-28T08:40:00.000Z"
    )
    assert (
        conn.execute(
            "SELECT partition_value FROM provider_dataset_rows WHERE row_key = ?",
            ("canonical-partition",),
        ).fetchone()[0]
        == "2026-07-28T08:45:00.000Z"
    )
    assert (
        conn.execute(
            "SELECT partition_value FROM provider_dataset_rows WHERE row_key = ?",
            ("unparseable",),
        ).fetchone()[0]
        is None
    )
    assert (
        conn.execute(
            "SELECT partition_value FROM provider_dataset_rows WHERE row_key = ?",
            ("other-dataset",),
        ).fetchone()[0]
        is None
    )

    # Idempotent second run: nothing left to update.
    summary2 = backfill_partition_values(conn, registry)
    assert summary2["rows_updated"] == 0

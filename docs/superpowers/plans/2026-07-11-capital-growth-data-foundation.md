# Capital Growth Data Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make SharedSignals the authoritative, versioned source for complete SW2021 reference snapshots, stable revisioned events, keyset-paginated HTTP reads, and bounded SQLite maintenance without changing TradingAgent execution behavior.

**Architecture:** SQLite remains the authoritative SharedSignals write model and DuckDB remains its analytics mirror. Dedicated SW2021 tables are populated by a 31-partition collector and exposed only after one-transaction promotion; `market_events` gains a stable logical identity plus append-only revisions and keyset pagination. SharedSignals owns the maintenance wrapper, health evidence, authentication scopes, API contracts, and rollout gates; MarketGraph consumes HTTP later, while TradingAgent is unchanged.

**Tech Stack:** Python 3.11, SQLite, DuckDB, `http.server`, pytest, Bash/flock, Tushare/QuickSync HTTP API.

## Global Constraints

- Start from the verified local baseline: `368 passed`.
- SharedSignals only collects, validates, stores, and serves factual data; it does not compute alpha, trade direction, position size, capital allocation, or execution permission.
- Add exactly three SW2021 tables: `market_industry_snapshots`, `market_industry_taxonomy`, and `market_industry_memberships`.
- SW2021 collection must make exactly 31 bounded `index_member_all(l1_code=<code>, is_new=Y)` calls after reading the full `index_classify` hierarchy.
- A snapshot is current only when `status=promoted`; latest start time is never a promotion rule.
- Coverage is `unique_symbol_count / active_universe_count` and must be at least `0.90`, with a non-zero denominator.
- Dedicated SW2021 writes must not change `API_TO_TABLE_MAP` or route through generic `market_assets` / `market_relationships` writes.
- `/events` must expose stable `event_id`, integer `revision`, and `source_family`, and must add cursor pagination without changing its top-level `data: []` response shape.
- Industry list endpoints use default `limit=500`, maximum `limit=1000`, and opaque URL-safe keyset cursors pinned to one `snapshot_id`.
- No API reader calls Tushare, reads a sibling database, or falls back to CSV/NDJSON/Parquet.
- Do not delete generic table rows, event history, rejected snapshots, promoted snapshots, databases, or backups in this release.
- Deploy, schema migration, manual pilot, public token smoke, scheduling, and first scheduled refresh are separate gates and must be reported separately.

## File Map

- `storage/schema_contract.py`: canonical SQLite/DuckDB columns, keys, and indexes.
- `storage/migrate.py`: additive event-identity backfill for already-existing SQLite databases.
- `storage/storage_adapter.py`: authoritative DuckDB mirror classification.
- `storage/event_identity.py`: deterministic event identity and content-revision fingerprints.
- `storage/read_model_store.py`: transactionally assign event revisions during direct SQLite ingest.
- `pagination.py`: shared opaque cursor codec with endpoint/snapshot binding.
- `collectors/tushare/sw2021_reference.py`: provider collection, normalization, and promotion-gate validation.
- `storage/industry_snapshot_store.py`: snapshot lifecycle and one-transaction promotion.
- `reader.py`: DB-only event and industry keyset queries using existing safe-public/cache invalidation behavior.
- `api_server.py`, `api_response.py`, `auth.py`: route parsing, page metadata, least-privilege scopes, and degraded responses.
- `tools/sqlite_maintenance.py`, `cron/sqlite_maintenance.sh`: SharedSignals-owned routine checkpoint/optimize evidence.
- `cron/sw2021_reference_collect.sh`, `crontab.txt`: guarded reference refresh, installed only after a successful manual pilot.
- `tools/source_governance_monitor.py`, `config/external_agent_api_config.json`, `config/api_module_catalog.yaml`: endpoint, cadence, ownership, and health governance.
- `API_CONTRACT.md`, `README.md`, `STATUS.md`, `docs/market_capability_matrix.md`: durable public and operator contracts.

---

### Task 1: Add additive schema contracts, migration, and mirror classification

**Files:**
- Modify: `storage/schema_contract.py`
- Modify: `storage/migrate.py`
- Modify: `storage/storage_adapter.py`
- Modify: `tests/test_schema_contract_edge.py`
- Modify: `tests/test_migrate.py`
- Modify: `tests/test_storage_adapter.py`

**Interfaces:**
- Produces: nullable `market_events.event_id: TEXT`, `revision: INTEGER`, `source_family: TEXT` for safe additive migration.
- Produces: the three table contracts and their primary keys exactly as specified in the design.
- Produces: `_backfill_event_identity(conn: sqlite3.Connection) -> int` for deterministic legacy-row backfill.
- Produces: all three industry tables in `AUTHORITATIVE_SNAPSHOT_TABLES` so DuckDB deletes rows absent from authoritative SQLite during a full sync.

- [ ] **Step 1: Write schema and migration RED tests**

```python
# tests/test_schema_contract_edge.py
def test_capital_growth_tables_and_event_identity_are_in_contract() -> None:
    events = get_table("market_events")
    assert {column.name for column in events.columns} >= {"event_id", "revision", "source_family"}
    assert table_primary_keys()["market_industry_snapshots"] == ["snapshot_id"]
    assert table_primary_keys()["market_industry_taxonomy"] == ["taxonomy_node_key"]
    assert table_primary_keys()["market_industry_memberships"] == ["membership_key"]

# tests/test_migrate.py
def test_apply_migrations_backfills_legacy_event_identity(tmp_path: Path) -> None:
    db_path = tmp_path / "marketdata.sqlite"
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA_SQL)
    conn.execute(
        "INSERT INTO market_events (event_hash, provider, event_type, title) VALUES (?, ?, ?, ?)",
        ("legacy-hash", "tushare_news", "news", "legacy"),
    )
    conn.commit()
    conn.close()
    result = apply_migrations(db_path)
    conn = sqlite3.connect(db_path)
    row = conn.execute(
        "SELECT event_id, revision, source_family FROM market_events WHERE event_hash='legacy-hash'"
    ).fetchone()
    conn.close()
    assert result["event_identity_backfilled"] == 1
    assert row == ("legacy-hash", 1, "tushare")
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `./.venv/bin/python3 -m pytest tests/test_schema_contract_edge.py tests/test_migrate.py tests/test_storage_adapter.py -q`

Expected: FAIL because the three industry contracts, event columns, backfill result, and authoritative classifications do not exist.

- [ ] **Step 3: Add the exact contracts and additive backfill**

Add the three `Column` entries to `market_events`, add indexes on `("event_id", "revision")` and `("event_time", "event_id", "revision")`, and add these tables to `TABLES`:

```python
Table(
    name="market_industry_snapshots",
    columns=(
        Column("snapshot_id", "text", False), Column("taxonomy_system", "text", False),
        Column("taxonomy_version", "text", False), Column("provider", "text", False),
        Column("started_at", "text", False), Column("completed_at", "text"),
        Column("status", "text", False), Column("expected_partition_count", "integer", False),
        Column("successful_partition_count", "integer", False), Column("taxonomy_row_count", "integer", False),
        Column("membership_row_count", "integer", False), Column("unique_symbol_count", "integer", False),
        Column("active_universe_count", "integer", False), Column("coverage_ratio", "float", False),
        Column("validation_errors_json", "text", False), Column("source_run_id", "text", False),
        Column("promoted_at", "text"),
    ),
    primary_key=("snapshot_id",),
    indexes=(("idx_industry_snapshots_current", ("taxonomy_system", "taxonomy_version", "status")),),
),
Table(
    name="market_industry_taxonomy",
    columns=(
        Column("taxonomy_node_key", "text", False), Column("snapshot_id", "text", False),
        Column("taxonomy_system", "text", False), Column("taxonomy_version", "text", False),
        Column("level", "text", False), Column("index_code", "text", False),
        Column("industry_code", "text", False), Column("industry_name", "text", False),
        Column("parent_industry_code", "text"), Column("is_published", "text"),
        Column("provider", "text", False), Column("collected_at", "text", False),
        Column("raw_json", "text", False),
    ),
    primary_key=("taxonomy_node_key",),
    indexes=(
        ("idx_industry_taxonomy_page", ("snapshot_id", "level", "index_code", "taxonomy_node_key")),
        ("idx_industry_taxonomy_code", ("snapshot_id", "industry_code")),
        ("idx_industry_taxonomy_parent", ("snapshot_id", "parent_industry_code")),
    ),
),
Table(
    name="market_industry_memberships",
    columns=(
        Column("membership_key", "text", False), Column("snapshot_id", "text", False),
        Column("market", "text", False), Column("symbol", "text", False), Column("name", "text", False),
        Column("l1_code", "text", False), Column("l1_name", "text", False),
        Column("l2_code", "text", False), Column("l2_name", "text", False),
        Column("l3_code", "text", False), Column("l3_name", "text", False),
        Column("in_date", "text"), Column("out_date", "text"), Column("is_current", "text", False),
        Column("provider", "text", False), Column("collected_at", "text", False), Column("raw_json", "text", False),
    ),
    primary_key=("membership_key",),
    indexes=(
        ("idx_industry_memberships_page", ("snapshot_id", "symbol", "membership_key")),
        ("idx_industry_memberships_l1", ("snapshot_id", "l1_code")),
        ("idx_industry_memberships_l2", ("snapshot_id", "l2_code")),
        ("idx_industry_memberships_l3", ("snapshot_id", "l3_code")),
    ),
),
```

Implement the backfill in `storage/migrate.py` and call it in both current-hash and changed-hash branches before commit:

```python
def _backfill_event_identity(conn: sqlite3.Connection) -> int:
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='market_events'").fetchone():
        return 0
    cursor = conn.execute(
        """
        UPDATE market_events
        SET event_id = COALESCE(NULLIF(event_id, ''), event_hash),
            revision = COALESCE(revision, 1),
            source_family = COALESCE(
                NULLIF(source_family, ''),
                CASE WHEN provider LIKE 'tushare_%' THEN 'tushare'
                     WHEN provider = 'sec_edgar' THEN 'sec_edgar'
                     ELSE COALESCE(NULLIF(provider, ''), 'unknown') END
            )
        WHERE event_id IS NULL OR event_id = '' OR revision IS NULL OR source_family IS NULL OR source_family = ''
        """
    )
    return max(0, int(cursor.rowcount or 0))
```

Add all three industry table names to `AUTHORITATIVE_SNAPSHOT_TABLES`.

- [ ] **Step 4: Run GREEN tests and the schema-only full guard**

Run: `./.venv/bin/python3 -m pytest tests/test_schema_contract_edge.py tests/test_migrate.py tests/test_storage_adapter.py tests/test_duckdb_merge.py -q`

Expected: PASS; SQLite and DuckDB schemas contain the same columns and primary keys, legacy events are backfilled, and full mirror reconciliation removes stale industry rows.

- [ ] **Step 5: Commit this independently reviewable schema unit**

```bash
git add storage/schema_contract.py storage/migrate.py storage/storage_adapter.py tests/test_schema_contract_edge.py tests/test_migrate.py tests/test_storage_adapter.py
git commit -m "feat(sharedsignals): add capital growth schema contracts"
```

**Release/delete gate:** Deploy additive schema code before any collector or reader uses it. Run `storage/migrate.py --check` against a copied database first, then a backup-protected production migration. This task authorizes no table, row, snapshot, database, or backup deletion.

---

### Task 2: Make event identity stable and revisions append-only

**Files:**
- Create: `storage/event_identity.py`
- Modify: `storage/read_model_store.py`
- Modify: `tests/test_read_model_store.py`
- Modify: `tests/test_sec_edgar_filings.py`

**Interfaces:**
- Produces: `source_family(provider: str) -> str`.
- Produces: `stable_event_id(provider: str, event_type: str, row: Mapping[str, Any]) -> str`.
- Produces: `event_content_fingerprint(row: Mapping[str, Any]) -> str`.
- Preserves: `ingest_rows_to_sqlite(...) -> int`; unchanged events write zero new rows, changed content inserts `revision = previous + 1` with `event_hash = sha256(f"{event_id}|{revision}|{content_fingerprint}")`.

- [ ] **Step 1: Write RED tests for idempotency and revision creation**

```python
def test_event_ingest_keeps_logical_id_and_appends_changed_revision(tmp_path: Path) -> None:
    db_path = tmp_path / "marketdata.sqlite"
    _create_db(db_path)
    base = {"id": "provider-42", "datetime": "2026-07-11 09:00:00", "title": "A", "content": "v1"}
    assert ingest_rows_to_sqlite(db_path, "market_events", "news", [base]) == 1
    assert ingest_rows_to_sqlite(db_path, "market_events", "news", [base]) == 0
    changed = {**base, "content": "v2"}
    assert ingest_rows_to_sqlite(db_path, "market_events", "news", [changed]) == 1
    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        "SELECT event_id, revision, source_family FROM market_events ORDER BY revision"
    ).fetchall()
    conn.close()
    assert len({row[0] for row in rows}) == 1
    assert rows == [(rows[0][0], 1, "tushare"), (rows[0][0], 2, "tushare")]
```

Add a SEC test asserting `provider='sec_edgar'`, `source_family='sec_edgar'`, stable accession-based `event_id`, and revision `1`.

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `./.venv/bin/python3 -m pytest tests/test_read_model_store.py tests/test_sec_edgar_filings.py -q`

Expected: FAIL because event identity currently hashes mutable title/content and cannot append a revision under one logical ID.

- [ ] **Step 3: Implement deterministic identity and transactional revision assignment**

```python
# storage/event_identity.py
from __future__ import annotations
import hashlib
import json
from typing import Any, Mapping

NATIVE_ID_FIELDS = ("event_id", "id", "accessionNumber", "accession_number", "ann_id", "report_id")

def source_family(provider: str) -> str:
    value = str(provider or "").strip().lower()
    if value.startswith("tushare_"):
        return "tushare"
    return value or "unknown"

def stable_event_id(provider: str, event_type: str, row: Mapping[str, Any]) -> str:
    native = next((str(row.get(key) or "").strip() for key in NATIVE_ID_FIELDS if row.get(key)), "")
    canonical_url = str(row.get("url") or row.get("link") or "").strip().split("#", 1)[0]
    fallback = "|".join(str(row.get(key) or "").strip() for key in ("datetime", "pub_time", "date", "title"))
    identity = native or canonical_url or fallback
    digest = hashlib.sha256(f"{source_family(provider)}|{event_type}|{identity}".encode()).hexdigest()[:32]
    return f"evt:{digest}"

def event_content_fingerprint(row: Mapping[str, Any]) -> str:
    payload = {key: row.get(key) for key in ("title", "content", "url", "source", "src", "symbol", "event_time", "trade_date")}
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()
```

In `storage/read_model_store.py`, add `event_id`, `revision`, and `source_family` to derived event columns. During the existing `BEGIN IMMEDIATE` transaction, query the latest row for the logical ID. Skip insertion when its stored raw content fingerprint matches; otherwise assign the next integer revision and derive `event_hash` from logical ID, revision, and fingerprint. Keep legacy `event_hash` as the physical primary key and keep `market_events` append-only for DuckDB sync.

- [ ] **Step 4: Run GREEN tests and event regression coverage**

Run: `./.venv/bin/python3 -m pytest tests/test_read_model_store.py tests/test_sec_edgar_filings.py tests/test_ashare_evidence.py tests/test_duckdb_merge.py -q`

Expected: PASS; repeat ingestion is idempotent, corrected content appends a revision, and existing event consumers still receive rows.

- [ ] **Step 5: Commit the event identity unit**

```bash
git add storage/event_identity.py storage/read_model_store.py tests/test_read_model_store.py tests/test_sec_edgar_filings.py
git commit -m "feat(sharedsignals): version event identities"
```

**Release/delete gate:** Before production rollout, run a copied-database backfill and compare total `market_events` rows before/after; the count must not decrease. Do not collapse old revisions or rewrite historical `event_hash` values.

---

### Task 3: Add endpoint-bound keyset pagination to `/events`

**Files:**
- Create: `pagination.py`
- Modify: `reader.py`
- Modify: `api_server.py`
- Modify: `api_response.py`
- Modify: `tests/test_reader.py`
- Modify: `tests/test_api_server_edge.py`

**Interfaces:**
- Produces: `encode_cursor(scope: str, snapshot_id: str, sort_key: Sequence[Any]) -> str`.
- Produces: `decode_cursor(cursor: str, *, scope: str, snapshot_id: str = "") -> tuple[Any, ...]`, raising `ValueError("invalid cursor")` or `ValueError("cursor snapshot mismatch")`.
- Produces: `reader.get_events_page(..., limit: int = 500, cursor: str | None = None) -> dict[str, Any]` with keys `rows`, `next_cursor`, and `row_count`.
- Preserves: `/events` response `data` remains a list; `metadata.next_cursor` and `metadata.row_count` are additive.

- [ ] **Step 1: Write RED cursor and page-stability tests**

```python
def test_events_cursor_has_no_duplicates_across_equal_timestamps(event_db, monkeypatch) -> None:
    monkeypatch.setattr(reader, "SQLITE_PATH", event_db)
    first = reader.get_events_page(limit=2)
    second = reader.get_events_page(limit=2, cursor=first["next_cursor"])
    ids = [row["data"]["event_hash"] for row in first["rows"] + second["rows"]]
    assert ids == ["h4", "h3", "h2", "h1"]
    assert len(ids) == len(set(ids))

def test_events_rejects_cursor_from_another_endpoint(api_edge_server) -> None:
    cursor = encode_cursor("industry_taxonomy", "snap-1", ("L1", "801010.SI", "n1"))
    status, payload = _get_json(api_edge_server, f"/events?cursor={cursor}")
    assert status == 400
    assert payload["error"] == "invalid cursor"
```

- [ ] **Step 2: Run RED tests**

Run: `./.venv/bin/python3 -m pytest tests/test_reader.py tests/test_api_server_edge.py -q`

Expected: FAIL because `/events` accepts only a limit and the cursor codec/page reader do not exist.

- [ ] **Step 3: Implement the cursor codec and descending event query**

Use compact JSON plus URL-safe Base64 with no padding:

```python
# pagination.py
def encode_cursor(scope: str, snapshot_id: str, sort_key: Sequence[Any]) -> str:
    raw = json.dumps({"v": 1, "scope": scope, "snapshot_id": snapshot_id, "key": list(sort_key)}, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")

def decode_cursor(cursor: str, *, scope: str, snapshot_id: str = "") -> tuple[Any, ...]:
    try:
        payload = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
    except Exception as exc:
        raise ValueError("invalid cursor") from exc
    if payload.get("v") != 1 or payload.get("scope") != scope or not isinstance(payload.get("key"), list):
        raise ValueError("invalid cursor")
    if snapshot_id and payload.get("snapshot_id") != snapshot_id:
        raise ValueError("cursor snapshot mismatch")
    return tuple(payload["key"])
```

Query `limit + 1` event rows ordered by:

```sql
ORDER BY COALESCE(NULLIF(event_time, ''), collected_at) DESC,
         event_id DESC,
         revision DESC
```

For the next page add the lexicographic descending predicate over the same three keys. Emit a cursor only when the extra row exists. In `api_server.py`, pass the raw `cursor`, aggregate `page["rows"]`, then add `next_cursor` and `row_count` to metadata. Do not use offset pagination.

- [ ] **Step 4: Run GREEN tests and auth/API regressions**

Run: `./.venv/bin/python3 -m pytest tests/test_reader.py tests/test_api_server_edge.py tests/test_auth_security.py tests/test_ashare_evidence.py -q`

Expected: PASS; page traversal is deterministic, malformed/cross-endpoint cursors return HTTP 400, and empty/degraded responses remain `data: []`.

- [ ] **Step 5: Commit the event page contract**

```bash
git add pagination.py reader.py api_server.py api_response.py tests/test_reader.py tests/test_api_server_edge.py
git commit -m "feat(sharedsignals): paginate event reads"
```

**Release/delete gate:** This additive cursor is safe to deploy before consumers use it. Compare an uncursored first page with the legacy first-page fixture; ordering and filters must match. No event row may be deleted to make pagination tests pass.

---

### Task 4: Collect and validate a complete SW2021 candidate

**Files:**
- Create: `collectors/tushare/sw2021_reference.py`
- Create: `tests/test_sw2021_reference.py`

**Interfaces:**
- Produces: immutable `IndustryCandidate(snapshot_id, started_at, source_run_id, taxonomy_rows, membership_rows, partition_counts)`.
- Produces: `collect_candidate(fetch: Callable[..., list[dict[str, Any]]], *, snapshot_id: str, source_run_id: str) -> IndustryCandidate`.
- Produces: `eligible_ashare_universe(conn: sqlite3.Connection) -> set[str]` using only valid `market_assets` rows from the design.
- Produces: `validate_candidate(candidate: IndustryCandidate, active_symbols: set[str], *, min_rows: int, max_rows: int) -> SnapshotValidation`.

- [ ] **Step 1: Write RED tests for all promotion gates**

Build fixtures for 31 L1 taxonomy nodes and complete membership rows. Add distinct tests asserting rejection codes:

```python
@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        ("missing_partition", "partition_count"),
        ("partition_at_2000_rows", "possible_provider_truncation"),
        ("conflicting_symbol", "conflicting_current_assignment"),
        ("unresolved_l3", "unresolved_taxonomy_code"),
        ("missing_name", "missing_required_membership_field"),
        ("out_date_present", "non_current_membership"),
        ("coverage_89_percent", "coverage_below_0.90"),
        ("zero_universe", "empty_active_universe"),
    ],
)
def test_candidate_rejection_reasons(mutation: str, reason: str) -> None:
    candidate, active = candidate_fixture(mutation)
    result = validate_candidate(candidate, active, min_rows=1, max_rows=10000)
    assert result.accepted is False
    assert reason in result.errors
```

Add a call-capture test proving exactly 31 calls with `{"l1_code": code, "is_new": "Y"}` and the complete field string `l1_code,l1_name,l2_code,l2_name,l3_code,l3_name,ts_code,name,in_date,out_date,is_new`.

- [ ] **Step 2: Run RED tests**

Run: `./.venv/bin/python3 -m pytest tests/test_sw2021_reference.py -q`

Expected: FAIL because the dedicated collector and validation types do not exist.

- [ ] **Step 3: Implement normalization and fail-closed validation**

Use `collectors.tushare.tushare_common.tushare_rows` as the default fetcher. Normalize taxonomy `level` to `L1|L2|L3`, preserve `is_pub`, preserve raw provider JSON, and hash keys as:

```python
taxonomy_node_key = sha256(f"{snapshot_id}|SW2021|{level}|{index_code}".encode()).hexdigest()
membership_key = sha256(f"{snapshot_id}|SW2021|{symbol}".encode()).hexdigest()
```

Reject any partition whose call raises, any partition returning `>= 2000` rows, any duplicate stock with unequal L1/L2/L3 assignments, and any candidate that violates a listed gate. Derive the active universe only with:

```sql
SELECT symbol FROM market_assets
WHERE market='Ashare' AND provider='tushare_stock_basic' AND asset_type='stock'
  AND name IS NOT NULL AND TRIM(name) <> '' AND name NOT LIKE '%退%'
```

Then filter symbols in Python with `r"^\d{6}\.(SH|SZ|BJ)$"`.

- [ ] **Step 4: Run GREEN tests and prove no generic mapping changed**

Run: `./.venv/bin/python3 -m pytest tests/test_sw2021_reference.py tests/test_capability_coverage.py -q`

Expected: PASS, including an assertion that `API_TO_TABLE_MAP["index_classify"] == "market_assets"` and `API_TO_TABLE_MAP["index_member_all"] == "market_relationships"` remain unchanged while the dedicated collector bypasses those mappings.

- [ ] **Step 5: Commit the candidate collector**

```bash
git add collectors/tushare/sw2021_reference.py tests/test_sw2021_reference.py
git commit -m "feat(sharedsignals): validate SW2021 candidates"
```

**Release/delete gate:** The collector remains unscheduled and must support a no-write validation invocation against test fixtures before a production token is used. A rejected candidate must not replace the current promoted snapshot or delete generic rows.

---

### Task 5: Persist attempts and promote SW2021 atomically

**Files:**
- Create: `storage/industry_snapshot_store.py`
- Modify: `collectors/tushare/sw2021_reference.py`
- Create: `tests/test_industry_snapshot_store.py`
- Modify: `tests/test_sw2021_reference.py`

**Interfaces:**
- Produces: `start_snapshot(conn, *, snapshot_id: str, source_run_id: str, started_at: str) -> None`.
- Produces: `reject_snapshot(conn, candidate: IndustryCandidate, validation: SnapshotValidation, *, completed_at: str) -> None`.
- Produces: `promote_snapshot(conn, candidate: IndustryCandidate, validation: SnapshotValidation, *, completed_at: str) -> None`.
- Produces: CLI exit `0` only for a committed promoted snapshot; validation/provider/write failures exit non-zero after recording a rejected attempt when SQLite is available.

- [ ] **Step 1: Write RED transaction tests**

```python
def test_promotion_supersedes_previous_snapshot_in_one_transaction(db_path: Path) -> None:
    seed_promoted_snapshot(db_path, "old")
    candidate, validation = valid_candidate("new")
    with sqlite3.connect(db_path) as conn:
        promote_snapshot(conn, candidate, validation, completed_at="2026-07-11T02:00:00+00:00")
        statuses = dict(conn.execute("SELECT snapshot_id, status FROM market_industry_snapshots"))
    assert statuses == {"old": "superseded", "new": "promoted"}

def test_write_failure_rolls_back_new_rows_and_keeps_old_promoted(db_path: Path, monkeypatch) -> None:
    seed_promoted_snapshot(db_path, "old")
    monkeypatch.setattr(store, "_insert_memberships", lambda *args: (_ for _ in ()).throw(sqlite3.Error("boom")))
    with pytest.raises(sqlite3.Error, match="boom"):
        promote_snapshot(sqlite3.connect(db_path), *valid_candidate("new"), completed_at="2026-07-11T02:00:00+00:00")
    assert current_snapshot_id(db_path) == "old"
    assert snapshot_child_count(db_path, "new") == 0
```

Add rejection tests proving structured JSON errors are stored and the old promotion stays current.

- [ ] **Step 2: Run RED tests**

Run: `./.venv/bin/python3 -m pytest tests/test_industry_snapshot_store.py tests/test_sw2021_reference.py -q`

Expected: FAIL because lifecycle persistence and atomic promotion do not exist.

- [ ] **Step 3: Implement explicit transactions and invariant checks**

`promote_snapshot` must execute `BEGIN IMMEDIATE`, re-check `validation.accepted`, insert all taxonomy and membership rows, verify non-zero inserted counts, supersede only the prior promoted `SW/SW2021` row, promote the candidate, assert exactly one promoted row, and commit. On any exception, roll back and re-raise. Never commit partition-by-partition.

Use one process-level file lock derived from the SQLite path around the full collector run, in addition to SQLite `BEGIN IMMEDIATE`, so a manual pilot and cron cannot race. Do not call `/cache/invalidate`; reader `_maybe_invalidate` observes SQLite mtime.

- [ ] **Step 4: Run GREEN tests and concurrency regression**

Run: `./.venv/bin/python3 -m pytest tests/test_industry_snapshot_store.py tests/test_sw2021_reference.py tests/test_read_model_store.py tests/test_storage_adapter.py -q`

Expected: PASS; failed writes expose no partial children, exactly one snapshot is promoted, and the previous promotion survives rejection/failure.

- [ ] **Step 5: Commit the promotion unit**

```bash
git add storage/industry_snapshot_store.py collectors/tushare/sw2021_reference.py tests/test_industry_snapshot_store.py tests/test_sw2021_reference.py
git commit -m "feat(sharedsignals): promote SW2021 snapshots atomically"
```

**Release/delete gate:** Do not run the production writer until Task 1 schema is live and a current SQLite backup passes validation. Rollback disables collection and preserves all snapshot rows; it never drops the tables or removes the old promoted snapshot.

---

### Task 6: Serve pinned SW2021 pages with least-privilege authentication

**Files:**
- Modify: `reader.py`
- Modify: `api_server.py`
- Modify: `api_response.py`
- Modify: `auth.py`
- Modify: `tests/test_reader.py`
- Modify: `tests/test_api_server_edge.py`
- Modify: `tests/test_auth_security.py`

**Interfaces:**
- Produces: `get_industry_snapshot() -> list[dict[str, Any]]`.
- Produces: `get_industry_taxonomy(snapshot_id: str | None = None, level: str | None = None, parent_industry_code: str | None = None, index_code: str | None = None, limit: int = 500, cursor: str | None = None) -> dict[str, Any]`.
- Produces: `get_industry_memberships(snapshot_id: str | None = None, symbol: str | None = None, l1_code: str | None = None, l2_code: str | None = None, l3_code: str | None = None, limit: int = 500, cursor: str | None = None) -> dict[str, Any]`.
- Produces: auth scope `industry_reference` granting only `/industry/snapshot`, `/industry/taxonomy`, and `/industry/memberships`.
- Preserves: legacy `/industry?ts_code=` semantics and route.

- [ ] **Step 1: Write RED reader, API, and scope tests**

```python
def test_industry_scope_is_least_privilege() -> None:
    account = {"scopes": ["industry_reference"]}
    for path in ("/industry/snapshot", "/industry/taxonomy", "/industry/memberships"):
        assert auth.check_endpoint_scope(account, path)
    assert not auth.check_endpoint_scope(account, "/industry")
    assert not auth.check_endpoint_scope(account, "/cache/invalidate")

def test_taxonomy_cursor_is_pinned_to_snapshot(industry_db, monkeypatch) -> None:
    monkeypatch.setattr(reader, "SQLITE_PATH", industry_db)
    page = reader.get_industry_taxonomy(snapshot_id="snap-a", limit=1)
    with pytest.raises(ValueError, match="cursor snapshot mismatch"):
        reader.get_industry_taxonomy(snapshot_id="snap-b", cursor=page["next_cursor"])
```

Add API tests for filters, max-limit clamping to 1000, exact counts, lineage, missing-table degraded empty, no-promoted-snapshot degraded empty, and invalid cursor HTTP 400.

- [ ] **Step 2: Run RED tests**

Run: `./.venv/bin/python3 -m pytest tests/test_reader.py tests/test_api_server_edge.py tests/test_auth_security.py -q`

Expected: FAIL because readers, routes, and `industry_reference` scope are absent.

- [ ] **Step 3: Implement current-snapshot resolution and keyset queries**

Resolve the default snapshot with:

```sql
SELECT * FROM market_industry_snapshots
WHERE taxonomy_system='SW' AND taxonomy_version='SW2021' AND status='promoted'
LIMIT 1
```

Taxonomy sorts ascending by `(level, index_code, taxonomy_node_key)`; memberships sort ascending by `(symbol, membership_key)`. Decode cursors with scopes `industry_taxonomy` and `industry_memberships`, require their embedded snapshot to equal the resolved/requested snapshot, query `limit + 1`, and emit exact `total_rows`, coverage numerator/denominator/missing count, freshness, provider, source run ID, and snapshot ID in metadata/lineage.

Add these exact routes to `auth.SCOPE_ENDPOINTS["industry_reference"]`, then union that scope into `fundamentals`, `external_read`, and `read`. Do not add it to `status`, `health`, `events`, or operator control. Route all three paths explicitly in `api_server.py`.

- [ ] **Step 4: Run GREEN tests and full API surface guards**

Run: `./.venv/bin/python3 -m pytest tests/test_reader.py tests/test_api_server_edge.py tests/test_auth_security.py tests/test_capability_coverage.py -q`

Expected: PASS; page cursors remain pinned, degraded states return `data: []`, separate tokens can receive only industry access, and `/industry` is unchanged.

- [ ] **Step 5: Commit the industry API unit**

```bash
git add reader.py api_server.py api_response.py auth.py tests/test_reader.py tests/test_api_server_edge.py tests/test_auth_security.py
git commit -m "feat(sharedsignals): expose SW2021 reference API"
```

**Release/delete gate:** Deploy routes only after additive tables exist. Before an accepted pilot there is intentionally no current snapshot, so all three routes must fail closed with degraded metadata. Do not relabel legacy `/industry` or remove it.

---

### Task 7: Establish SharedSignals-owned SQLite maintenance, health evidence, and guarded schedules

**Files:**
- Create: `tools/sqlite_maintenance.py`
- Create: `cron/sqlite_maintenance.sh`
- Create: `cron/sw2021_reference_collect.sh`
- Modify: `cron/crontab.txt`
- Modify: `tools/source_governance_monitor.py`
- Create: `tests/test_sqlite_maintenance.py`
- Modify: `tests/test_deploy_scripts_safety.py`
- Modify: `tests/test_source_governance_monitor.py`

**Interfaces:**
- Produces: `run_maintenance(db_path: Path, *, deep_check: bool = False) -> dict[str, Any]` with `owner`, `status`, `wal_checkpoint`, `optimized`, `integrity`, `started_at`, and `completed_at`.
- Produces: `logs/watchdog_inputs/sqlite_maintenance.json`, written atomically by the wrapper.
- Produces: guarded `sw2021_reference_collect.sh` invoking the dedicated collector, never `sync_daily.py` generic mappings.
- Produces: governance states `active`, `rejected`, `stale`, and `disabled_by_operator`; `disabled_by_operator` is intentional yellow/disabled evidence and must not be restarted by heal.

- [ ] **Step 1: Write RED maintenance and cron ownership tests**

```python
def test_routine_sqlite_maintenance_is_bounded(tmp_path: Path) -> None:
    db = tmp_path / "marketdata.sqlite"
    create_db(db)
    result = run_maintenance(db, deep_check=False)
    assert result["owner"] == "SharedSignals"
    assert result["status"] == "green"
    assert result["integrity"] == "not_run"
    assert result["optimized"] is True

def test_reference_and_maintenance_wrappers_take_read_model_lock() -> None:
    for name in ("cron/sqlite_maintenance.sh", "cron/sw2021_reference_collect.sh"):
        script = (ROOT / name).read_text()
        assert 'source "${SCRIPT_DIR}/maintenance_lock.sh"' in script
        assert "acquire_sharedsignals_read_model_lock" in script
        assert "flock -n" in script
```

- [ ] **Step 2: Run RED tests**

Run: `./.venv/bin/python3 -m pytest tests/test_sqlite_maintenance.py tests/test_deploy_scripts_safety.py tests/test_source_governance_monitor.py -q`

Expected: FAIL because the SharedSignals maintenance tool, wrappers, state evidence, and cron ownership entries do not exist.

- [ ] **Step 3: Implement bounded maintenance and thin wrappers**

Routine maintenance opens the authoritative database directly and performs only:

```python
checkpoint = conn.execute("PRAGMA wal_checkpoint(PASSIVE)").fetchone()
conn.execute("PRAGMA optimize(0x10002)")
integrity = "not_run"
if deep_check:
    integrity = str(conn.execute("PRAGMA quick_check").fetchone()[0])
```

It never runs `VACUUM`, restores, deletes sidecars, or removes rows. Both wrappers must re-exec as `marketgraph` when started as root, source `.env`, take the shared deploy/rollback maintenance lock, then take a job-specific non-blocking flock. Write JSON via a same-directory temporary file plus atomic rename.

Add repository cron declarations only after the manual-pilot gate:

```cron
20 3 * * * /opt/investment/SharedSignals/cron/sqlite_maintenance.sh
25 6 * * 1-5 /opt/investment/SharedSignals/cron/sw2021_reference_collect.sh
```

`source_governance_monitor.py` must require the three industry endpoints, the maintenance evidence, and the scheduled SW2021 line only when the source state is `active`. A recent rejected run is red; stale is red; `disabled_by_operator` is yellow and does not request heal/restart.

- [ ] **Step 4: Run GREEN tests and cron capability guards**

Run: `./.venv/bin/python3 -m pytest tests/test_sqlite_maintenance.py tests/test_deploy_scripts_safety.py tests/test_source_governance_monitor.py tests/test_capability_coverage.py tests/test_patrol.py tests/test_watchdog_health_sla.py -q`

Expected: PASS; maintenance is bounded, wrappers are lock-protected, governance distinguishes intentional disablement from failure, and no sibling-system path is referenced.

- [ ] **Step 5: Commit the operations unit**

```bash
git add tools/sqlite_maintenance.py cron/sqlite_maintenance.sh cron/sw2021_reference_collect.sh cron/crontab.txt tools/source_governance_monitor.py tests/test_sqlite_maintenance.py tests/test_deploy_scripts_safety.py tests/test_source_governance_monitor.py
git commit -m "feat(sharedsignals): own reference and SQLite maintenance jobs"
```

**Release/delete gate:** Ship wrapper files before installing live cron. Compare the repository lines with `sudo -u marketgraph crontab -l`; merge only SharedSignals-owned lines and never overwrite MarketGraph/TradingAgent entries. Rollback removes/disables only these two schedule lines and records `disabled_by_operator`; it does not delete databases, tables, snapshots, WAL files, or backups.

---

### Task 8: Publish contracts, run full gates, pilot, and activate without destructive cleanup

**Files:**
- Modify: `config/external_agent_api_config.json`
- Modify: `config/api_module_catalog.yaml`
- Modify: `API_CONTRACT.md`
- Modify: `README.md`
- Modify: `STATUS.md`
- Modify: `docs/market_capability_matrix.md`
- Modify: `tests/test_source_expansion_priority.py`
- Modify: `tests/test_capability_coverage.py`

**Interfaces:**
- Documents: exact endpoint parameters, cursor semantics, auth scope, event identity/revision semantics, freshness/lineage, degraded-empty behavior, cadence, maintenance ownership, pilot evidence, and rollback state.
- Registers: three industry endpoints in agent config/capability governance and the SW2021 module/tables in `api_module_catalog.yaml`.
- Records: live rollout evidence without claiming GitHub, production files, runtime, external route, or scheduled refresh from local tests alone.

- [ ] **Step 1: Write RED contract-presence tests**

```python
def test_external_contract_lists_industry_reference_endpoints() -> None:
    config = json.loads((ROOT / "config/external_agent_api_config.json").read_text())
    paths = {item["path"] for item in config["primary_endpoints"]}
    assert {"/industry/snapshot", "/industry/taxonomy", "/industry/memberships"} <= paths

def test_capability_docs_state_event_revision_and_snapshot_pinning() -> None:
    contract = (ROOT / "API_CONTRACT.md").read_text()
    assert "event_id" in contract and "revision" in contract and "source_family" in contract
    assert "cursor snapshot mismatch" in contract
    assert "market_industry_snapshots" in contract
```

- [ ] **Step 2: Run RED tests**

Run: `./.venv/bin/python3 -m pytest tests/test_source_expansion_priority.py tests/test_capability_coverage.py -q`

Expected: FAIL until configuration and durable contracts describe the new surfaces.

- [ ] **Step 3: Update config and documentation with exact contracts**

Document request/response examples for all three industry endpoints and `/events?cursor=...`; list `industry_reference` separately from `fundamentals`; state that MarketGraph and TradingAgent use separate service-account tokens; state that `/industry` remains legacy `stock_basic.sector`; state that no endpoint performs live provider fallback. In `STATUS.md`, keep SW2021 as `implemented_unscheduled` until the pilot succeeds, then `pilot_promoted`, then `scheduled` only after live cron is installed and observed.

- [ ] **Step 4: Run the complete local verification gate**

Run:

```bash
./.venv/bin/python3 -m pytest -q
./.venv/bin/python3 tools/source_governance_monitor.py --json
./.venv/bin/python3 storage/migrate.py --check --db /path/to/copied/marketdata.sqlite
```

Expected: pytest reports at least `368 passed` with zero failures; governance is green or has only the explicitly documented unscheduled-pilot warning; copied-database migration reports the expected additive drift before apply and `status=ok` after applying to the copy.

- [ ] **Step 5: Commit the contract unit**

```bash
git add config/external_agent_api_config.json config/api_module_catalog.yaml API_CONTRACT.md README.md STATUS.md docs/market_capability_matrix.md tests/test_source_expansion_priority.py tests/test_capability_coverage.py
git commit -m "docs(sharedsignals): publish capital growth data contracts"
```

- [ ] **Step 6: Execute the staged production gates in order**

1. Preflight exact branch/HEAD, clean audited diff, target server, current production HEAD, SQLite owner `marketgraph:marketgraph`, free space, validated backup path, and rollback tag.
2. Deploy additive code with no SW2021 cron; verify production file HEAD, systemd runtime HEAD, `GET /health`, `GET /source_status`, and degraded-empty industry endpoints separately.
3. Run one manual collector pilot under the wrapper and capture: `31/31` partitions, taxonomy count, membership count, unique symbols, active-universe denominator, missing count, coverage `>=0.90`, zero conflicts, hierarchy closure, source run ID, promoted snapshot ID, and committed row counts.
4. Verify all three endpoints on localhost and through `https://signals.tradingagent.cc` with an approved `industry_reference` token; separately verify an events token cannot access industry and an industry token cannot invalidate cache.
5. Sync DuckDB and require zero count delta for all three tables.
6. Install only the two SharedSignals cron lines from Task 7, observe one scheduled SW2021 refresh plus one maintenance artifact, then require `/source_status` and Green Gate evidence to reflect the scheduled state.
7. If any gate fails, disable the new schedule, record `disabled_by_operator`, keep the previous promoted snapshot current, and use normal revert/rollback procedures. Do not drop tables or delete audit rows.

**Release/delete gate:** “Local tests passed”, “GitHub main updated”, “production files synced”, “runtime restarted”, “public route authenticated”, and “first scheduled refresh succeeded” are six separate truths. Formal activation requires all six plus pilot evidence. Snapshot retention and deletion remain outside this release; the current and immediately previous promoted snapshots are always preserved.

---

## Final Acceptance Matrix

| Layer | Required fresh evidence |
| --- | --- |
| Local | Full pytest at or above the 368-test baseline; focused schema, event, cursor, snapshot, auth, maintenance, and governance tests pass |
| Git | Eight scoped commits reviewed; no unrelated worktree changes; no database/cache/log artifacts tracked |
| Production file | Production HEAD and file hashes match the reviewed release commit |
| Production runtime | systemd uses the SharedSignals environment; `/health` and `/source_status` are live and current |
| SW2021 data | One promoted snapshot with 31/31 partitions, hierarchy closure, zero conflicts, and coverage at least 90% |
| Event data | Stable `event_id`, append-only integer revisions, `source_family`, and duplicate-free cursor traversal |
| Auth/API | Scoped localhost and public-route smokes; invalid/mismatched cursors fail closed; missing data is degraded-empty |
| SQLite ownership | SharedSignals-owned maintenance artifact is current; no sibling path or cron owns the database job |
| Schedule | One observed daily SW2021 refresh and maintenance run; rollback disables jobs without deleting data |
| Trading boundary | No TradingAgent queue, capital, account, callback, cron, strategy, or execution diff |

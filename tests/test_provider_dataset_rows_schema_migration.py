from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

import storage.provider_dataset_rows_migration as migration
from storage.migrate import apply_migrations
from storage.provider_dataset_rows_migration import (
    ProviderDatasetRowsMigrationError,
    ProviderDatasetRowsSchemaError,
    apply_provider_dataset_rows_migration,
    validate_provider_dataset_rows_schema,
)
from storage.schema import SCHEMA_SQL
from storage.schema_contract import (
    PROVIDER_DATASET_ROWS_CREATE_SQL,
    PROVIDER_DATASET_ROWS_INDEX_COLUMNS,
    PROVIDER_DATASET_ROWS_INDEX_SQL,
    PROVIDER_DATASET_ROWS_TABLE,
    render_schema,
)


def _touch_sqlite(path: Path) -> None:
    with sqlite3.connect(path):
        pass


def _table_sql(path: Path) -> str | None:
    with sqlite3.connect(path) as conn:
        row = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
            (PROVIDER_DATASET_ROWS_TABLE,),
        ).fetchone()
    return None if row is None else str(row[0])


def _contract_indexes(path: Path) -> dict[str, tuple[str, ...]]:
    with sqlite3.connect(path) as conn:
        rows = conn.execute(
            f"PRAGMA index_list({PROVIDER_DATASET_ROWS_TABLE})"
        ).fetchall()
        result: dict[str, tuple[str, ...]] = {}
        for row in rows:
            name = str(row[1])
            if name not in PROVIDER_DATASET_ROWS_INDEX_COLUMNS:
                continue
            result[name] = tuple(
                str(item[2])
                for item in conn.execute(f'PRAGMA index_xinfo("{name}")').fetchall()
                if int(item[5]) == 1
            )
    return result


def test_fresh_canonical_sqlite_schema_contains_exact_generic_contract(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "fresh.sqlite"
    with sqlite3.connect(db_path) as conn:
        conn.executescript(SCHEMA_SQL)
        validate_provider_dataset_rows_schema(conn)
        columns = conn.execute(
            f"PRAGMA table_xinfo({PROVIDER_DATASET_ROWS_TABLE})"
        ).fetchall()

    assert len(columns) == 14
    assert [str(row[1]) for row in columns] == [
        "dataset_id",
        "provider",
        "schema_major",
        "ingested_schema_version",
        "row_key",
        "observed_at",
        "partition_value",
        "payload_json",
        "payload_hash",
        "quality_state",
        "quality_issues_json",
        "collected_at",
        "receipt_id",
        "revision",
    ]
    assert [int(row[5]) for row in columns] == [
        1,
        2,
        3,
        0,
        4,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
    ]
    assert _contract_indexes(db_path) == PROVIDER_DATASET_ROWS_INDEX_COLUMNS
    assert "provider_dataset_rows" not in render_schema("duckdb")


def test_additive_migration_preserves_existing_tables_and_is_idempotent(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "legacy.sqlite"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "CREATE TABLE typed_v1 (id INTEGER PRIMARY KEY, value TEXT NOT NULL)"
        )
        conn.execute("INSERT INTO typed_v1 (id, value) VALUES (1, 'preserve-me')")

    first = apply_provider_dataset_rows_migration(db_path)
    first_sql = _table_sql(db_path)
    second = apply_provider_dataset_rows_migration(db_path)

    assert first.created is True
    assert second.created is False
    assert first_sql == _table_sql(db_path)
    assert first.indexes == tuple(PROVIDER_DATASET_ROWS_INDEX_COLUMNS)
    assert second.indexes == tuple(PROVIDER_DATASET_ROWS_INDEX_COLUMNS)
    with sqlite3.connect(db_path) as conn:
        validate_provider_dataset_rows_schema(conn)
        assert conn.execute("SELECT id, value FROM typed_v1").fetchall() == [
            (1, "preserve-me")
        ]


def test_migration_rejects_leaf_symlink_without_modifying_target(
    tmp_path: Path,
) -> None:
    target = tmp_path / "target.sqlite"
    _touch_sqlite(target)
    alias = tmp_path / "alias.sqlite"
    alias.symlink_to(target.name)

    with pytest.raises(ProviderDatasetRowsMigrationError, match="unsafe|binding"):
        apply_provider_dataset_rows_migration(alias)

    assert _table_sql(target) is None


def test_migration_rejects_symlinked_parent_without_modifying_target(
    tmp_path: Path,
) -> None:
    real_parent = tmp_path / "real"
    real_parent.mkdir()
    target = real_parent / "target.sqlite"
    _touch_sqlite(target)
    linked_parent = tmp_path / "linked"
    linked_parent.symlink_to(real_parent, target_is_directory=True)

    with pytest.raises(ProviderDatasetRowsMigrationError, match="unsafe|binding"):
        apply_provider_dataset_rows_migration(linked_parent / target.name)

    assert _table_sql(target) is None


@pytest.mark.parametrize("kind", ["directory", "fifo"])
def test_migration_rejects_non_regular_database_path(
    tmp_path: Path, kind: str
) -> None:
    target = tmp_path / "not-a-database"
    if kind == "directory":
        target.mkdir()
    else:
        target = target.with_suffix(".fifo")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.touch()
        target.unlink()
        os.mkfifo(target)

    with pytest.raises(ProviderDatasetRowsMigrationError, match="unsafe|regular"):
        apply_provider_dataset_rows_migration(target)


@pytest.mark.parametrize("binding_check", [1, 2, 4])
def test_migration_rolls_back_if_database_path_drifts_before_commit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    binding_check: int,
) -> None:
    db_path = tmp_path / "authority.sqlite"
    _touch_sqlite(db_path)
    retired = tmp_path / "retired.sqlite"
    original_check = migration._require_unchanged_database_binding
    calls = 0

    def replace_on_selected_check(binding: object) -> None:
        nonlocal calls
        calls += 1
        if calls == binding_check:
            db_path.rename(retired)
            _touch_sqlite(db_path)
        original_check(binding)

    monkeypatch.setattr(
        migration,
        "_require_unchanged_database_binding",
        replace_on_selected_check,
    )

    with pytest.raises(ProviderDatasetRowsMigrationError, match="binding"):
        apply_provider_dataset_rows_migration(db_path)

    assert _table_sql(db_path) is None
    assert _table_sql(retired) is None


def test_migration_rolls_back_if_parent_is_replaced_after_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    parent = tmp_path / "authority"
    parent.mkdir()
    db_path = parent / "marketdata.sqlite"
    _touch_sqlite(db_path)
    retired_parent = tmp_path / "retired-authority"
    original_check = migration._require_unchanged_database_binding
    calls = 0

    def replace_parent_after_open(binding: object) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            parent.rename(retired_parent)
            parent.mkdir()
            _touch_sqlite(parent / db_path.name)
        original_check(binding)

    monkeypatch.setattr(
        migration,
        "_require_unchanged_database_binding",
        replace_parent_after_open,
    )

    with pytest.raises(ProviderDatasetRowsMigrationError, match="binding"):
        apply_provider_dataset_rows_migration(db_path)

    assert _table_sql(parent / db_path.name) is None
    assert _table_sql(retired_parent / db_path.name) is None


def test_generic_migrate_does_not_apply_dedicated_provider_schema(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "generic-migrate.sqlite"
    _touch_sqlite(db_path)

    result = apply_migrations(db_path)

    assert result["status"] == "ok"
    assert result["provider_dataset_rows"].startswith("excluded_from_generic_migrate")
    assert "storage.provider_dataset_rows_migration" in result["provider_dataset_rows"]
    assert _table_sql(db_path) is None


def test_statement_failure_rolls_back_every_provider_schema_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = tmp_path / "statement-failure.sqlite"
    _touch_sqlite(db_path)
    monkeypatch.setattr(
        migration,
        "PROVIDER_DATASET_ROWS_MIGRATION_STATEMENTS",
        (
            *migration.PROVIDER_DATASET_ROWS_MIGRATION_STATEMENTS,
            "CREATE INDEX broken syntax",
        ),
    )

    with pytest.raises(ProviderDatasetRowsMigrationError):
        apply_provider_dataset_rows_migration(db_path)

    assert _table_sql(db_path) is None


def test_postflight_failure_rolls_back_every_provider_schema_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = tmp_path / "postflight-failure.sqlite"
    _touch_sqlite(db_path)

    def reject(_conn: sqlite3.Connection) -> None:
        raise ProviderDatasetRowsSchemaError("injected postflight failure")

    monkeypatch.setattr(migration, "validate_provider_dataset_rows_schema", reject)

    with pytest.raises(ProviderDatasetRowsSchemaError, match="injected postflight"):
        apply_provider_dataset_rows_migration(db_path)

    assert _table_sql(db_path) is None


def test_malformed_preexisting_table_fails_closed_without_partial_indexes(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "malformed.sqlite"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """CREATE TABLE provider_dataset_rows (
                dataset_id TEXT NOT NULL,
                provider TEXT NOT NULL,
                schema_major INTEGER NOT NULL,
                ingested_schema_version TEXT NOT NULL,
                row_key TEXT NOT NULL,
                observed_at TEXT,
                partition_value TEXT,
                payload_json TEXT NOT NULL,
                payload_hash TEXT NOT NULL,
                quality_state TEXT NOT NULL,
                quality_issues_json TEXT NOT NULL DEFAULT '[]',
                collected_at TEXT NOT NULL,
                receipt_id TEXT NOT NULL,
                revision INTEGER NOT NULL
            )"""
        )
    original_sql = _table_sql(db_path)

    with pytest.raises(ProviderDatasetRowsSchemaError):
        apply_provider_dataset_rows_migration(db_path)

    assert _table_sql(db_path) == original_sql
    assert _contract_indexes(db_path) == {}


def test_near_miss_check_constraints_fail_closed(tmp_path: Path) -> None:
    db_path = tmp_path / "near-miss-checks.sqlite"
    near_miss = PROVIDER_DATASET_ROWS_CREATE_SQL.replace(
        "schema_major >= 1", "schema_major != 0"
    ).replace("revision >= 1", "revision != 0")
    with sqlite3.connect(db_path) as conn:
        conn.execute(near_miss)
        for statement in PROVIDER_DATASET_ROWS_INDEX_SQL:
            conn.execute(statement)
    original_sql = _table_sql(db_path)

    with pytest.raises(ProviderDatasetRowsSchemaError, match="CHECK contract"):
        apply_provider_dataset_rows_migration(db_path)

    assert _table_sql(db_path) == original_sql
    assert _contract_indexes(db_path) == PROVIDER_DATASET_ROWS_INDEX_COLUMNS


def test_extra_unique_constraint_fails_closed(tmp_path: Path) -> None:
    db_path = tmp_path / "extra-unique.sqlite"
    drifted = PROVIDER_DATASET_ROWS_CREATE_SQL.replace(
        "    PRIMARY KEY (dataset_id, provider, schema_major, row_key)",
        "    UNIQUE (receipt_id),\n"
        "    PRIMARY KEY (dataset_id, provider, schema_major, row_key)",
    )
    with sqlite3.connect(db_path) as conn:
        conn.execute(drifted)
        for statement in PROVIDER_DATASET_ROWS_INDEX_SQL:
            conn.execute(statement)

    with pytest.raises(ProviderDatasetRowsSchemaError, match="unexpected index"):
        apply_provider_dataset_rows_migration(db_path)


def test_extra_non_unique_index_fails_closed(tmp_path: Path) -> None:
    db_path = tmp_path / "extra-index.sqlite"
    with sqlite3.connect(db_path) as conn:
        conn.execute(PROVIDER_DATASET_ROWS_CREATE_SQL)
        for statement in PROVIDER_DATASET_ROWS_INDEX_SQL:
            conn.execute(statement)
        conn.execute(
            "CREATE INDEX provider_dataset_rows_extra_idx "
            "ON provider_dataset_rows (payload_hash)"
        )

    with pytest.raises(ProviderDatasetRowsSchemaError, match="unexpected index"):
        apply_provider_dataset_rows_migration(db_path)


def test_primary_key_nocase_collation_fails_closed(tmp_path: Path) -> None:
    db_path = tmp_path / "pk-nocase.sqlite"
    drifted = PROVIDER_DATASET_ROWS_CREATE_SQL.replace(
        "dataset_id          TEXT NOT NULL",
        "dataset_id          TEXT COLLATE NOCASE NOT NULL",
    )
    with sqlite3.connect(db_path) as conn:
        conn.execute(drifted)
        for statement in PROVIDER_DATASET_ROWS_INDEX_SQL:
            conn.execute(statement)

    with pytest.raises(ProviderDatasetRowsSchemaError, match="collation or direction"):
        apply_provider_dataset_rows_migration(db_path)


@pytest.mark.parametrize(
    "observed_at_expression",
    ["observed_at COLLATE NOCASE", "observed_at DESC"],
)
def test_required_index_key_semantics_fail_closed(
    tmp_path: Path, observed_at_expression: str
) -> None:
    db_path = tmp_path / "index-key-drift.sqlite"
    observed_name = "provider_dataset_rows_observed_idx"
    with sqlite3.connect(db_path) as conn:
        conn.execute(PROVIDER_DATASET_ROWS_CREATE_SQL)
        for name, columns in PROVIDER_DATASET_ROWS_INDEX_COLUMNS.items():
            rendered_columns = list(columns)
            if name == observed_name:
                rendered_columns[3] = observed_at_expression
            conn.execute(
                f"CREATE INDEX {name} ON {PROVIDER_DATASET_ROWS_TABLE} "
                f"({', '.join(rendered_columns)})"
            )

    with pytest.raises(ProviderDatasetRowsSchemaError, match="collation or direction"):
        apply_provider_dataset_rows_migration(db_path)


@pytest.mark.parametrize(
    ("extra_args", "expected_code"),
    [((), 0), (("--check",), 2)],
)
def test_generic_migrate_cli_prints_dedicated_migration_hint(
    tmp_path: Path, extra_args: tuple[str, ...], expected_code: int
) -> None:
    db_path = tmp_path / "generic-cli.sqlite"
    _touch_sqlite(db_path)
    repo_root = Path(__file__).resolve().parents[1]

    completed = subprocess.run(
        [
            sys.executable,
            str(repo_root / "storage" / "migrate.py"),
            "--db",
            str(db_path),
            *extra_args,
        ],
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == expected_code
    output = completed.stdout + completed.stderr
    assert "python3 -m storage.provider_dataset_rows_migration" in output
    assert "--db <existing.sqlite> --apply" in output


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("schema_major", 0),
        ("payload_json", "{"),
        ("payload_json", "[]"),
        ("quality_state", "unknown"),
        ("quality_issues_json", "{"),
        ("quality_issues_json", "{}"),
        ("revision", 0),
    ],
)
def test_canonical_json_and_check_constraints_reject_invalid_rows(
    tmp_path: Path,
    column: str,
    value: object,
) -> None:
    db_path = tmp_path / f"check-{column}-{str(value).replace('/', '_')}.sqlite"
    with sqlite3.connect(db_path) as conn:
        conn.executescript(SCHEMA_SQL)
        row = {
            "dataset_id": "cn.equity.daily",
            "provider": "tushare",
            "schema_major": 1,
            "ingested_schema_version": "1.0.0",
            "row_key": "000001.SZ|20260717",
            "observed_at": "20260717",
            "partition_value": "20260717",
            "payload_json": '{"ts_code":"000001.SZ"}',
            "payload_hash": "a" * 64,
            "quality_state": "valid",
            "quality_issues_json": "[]",
            "collected_at": "2026-07-17T01:00:00+00:00",
            "receipt_id": "receipt-1",
            "revision": 1,
        }
        row[column] = value
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """INSERT INTO provider_dataset_rows (
                    dataset_id, provider, schema_major, ingested_schema_version,
                    row_key, observed_at, partition_value, payload_json,
                    payload_hash, quality_state, quality_issues_json,
                    collected_at, receipt_id, revision
                ) VALUES (
                    :dataset_id, :provider, :schema_major, :ingested_schema_version,
                    :row_key, :observed_at, :partition_value, :payload_json,
                    :payload_hash, :quality_state, :quality_issues_json,
                    :collected_at, :receipt_id, :revision
                )""",
                row,
            )

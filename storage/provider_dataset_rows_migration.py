#!/usr/bin/env python3
"""Dedicated additive migration for the provider-native SQLite fact table.

Fresh databases receive the same contract through ``storage.schema.SCHEMA_SQL``.
Existing databases must use this module instead of ``storage.migrate`` so all
DDL statements and the complete postflight either commit together or roll back
together.  This migration never deletes, renames, copies, or rewrites existing
tables or rows.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import stat
from dataclasses import asdict, dataclass
from pathlib import Path
from uuid import uuid4

from storage.schema_contract import (
    PROVIDER_DATASET_ROWS_COLUMNS,
    PROVIDER_DATASET_ROWS_CREATE_SQL,
    PROVIDER_DATASET_ROWS_INDEX_COLUMNS,
    PROVIDER_DATASET_ROWS_MIGRATION_STATEMENTS,
    PROVIDER_DATASET_ROWS_TABLE,
)


class ProviderDatasetRowsMigrationError(RuntimeError):
    """The additive provider-native schema migration did not commit."""


class ProviderDatasetRowsSchemaError(ProviderDatasetRowsMigrationError):
    """The live SQLite object does not satisfy the canonical contract."""


@dataclass(frozen=True)
class ProviderDatasetRowsMigrationResult:
    table: str
    created: bool
    indexes: tuple[str, ...]
    postflight: str = "ok"


_FileIdentity = tuple[int, int, int]


@dataclass(frozen=True)
class _DatabaseBinding:
    path: Path
    parent_identities: tuple[_FileIdentity, ...]
    database_identity: _FileIdentity


_PRIMARY_KEY = ("dataset_id", "provider", "schema_major", "row_key")
_INSERT_SQL = """INSERT INTO provider_dataset_rows (
    dataset_id, provider, schema_major, ingested_schema_version,
    row_key, observed_at, partition_value, payload_json,
    payload_hash, quality_state, quality_issues_json,
    collected_at, receipt_id, revision
) VALUES (
    :dataset_id, :provider, :schema_major, :ingested_schema_version,
    :row_key, :observed_at, :partition_value, :payload_json,
    :payload_hash, :quality_state, :quality_issues_json,
    :collected_at, :receipt_id, :revision
)"""


def _file_identity(metadata: os.stat_result) -> _FileIdentity:
    return metadata.st_dev, metadata.st_ino, metadata.st_mode


def _validated_parent_chain(db_path: Path) -> tuple[_FileIdentity, ...]:
    identities: list[_FileIdentity] = []
    for parent in reversed(db_path.parents):
        try:
            metadata = parent.lstat()
        except OSError:
            raise ProviderDatasetRowsMigrationError(
                "provider_dataset_rows database parent binding is unavailable"
            ) from None
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
            raise ProviderDatasetRowsMigrationError(
                "provider_dataset_rows database parent binding is unsafe"
            )
        identities.append(_file_identity(metadata))
    return tuple(identities)


def _bind_existing_database(db_path: Path) -> tuple[_DatabaseBinding, int]:
    path = Path(os.path.abspath(os.fspath(db_path)))
    parent_identities = _validated_parent_chain(path)
    try:
        pre_open = path.lstat()
    except OSError:
        raise ProviderDatasetRowsMigrationError(
            "provider_dataset_rows database is unavailable"
        ) from None
    if stat.S_ISLNK(pre_open.st_mode) or not stat.S_ISREG(pre_open.st_mode):
        raise ProviderDatasetRowsMigrationError(
            "provider_dataset_rows database path is unsafe or not a regular file"
        )

    nofollow = getattr(os, "O_NOFOLLOW", None)
    if nofollow is None:
        raise ProviderDatasetRowsMigrationError(
            "provider_dataset_rows no-follow database binding is unavailable"
        )
    flags = os.O_RDONLY | nofollow | getattr(os, "O_CLOEXEC", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError:
        raise ProviderDatasetRowsMigrationError(
            "provider_dataset_rows database binding is unavailable"
        ) from None
    try:
        opened = os.fstat(descriptor)
        observed = path.lstat()
        if (
            not stat.S_ISREG(opened.st_mode)
            or _file_identity(opened) != _file_identity(pre_open)
            or _file_identity(observed) != _file_identity(pre_open)
            or parent_identities != _validated_parent_chain(path)
        ):
            raise ProviderDatasetRowsMigrationError(
                "provider_dataset_rows database binding changed"
            )
    except ProviderDatasetRowsMigrationError:
        os.close(descriptor)
        raise
    except OSError:
        os.close(descriptor)
        raise ProviderDatasetRowsMigrationError(
            "provider_dataset_rows database binding changed"
        ) from None

    return (
        _DatabaseBinding(
            path=path,
            parent_identities=parent_identities,
            database_identity=_file_identity(opened),
        ),
        descriptor,
    )


def _require_unchanged_database_binding(binding: _DatabaseBinding) -> None:
    if binding.parent_identities != _validated_parent_chain(binding.path):
        raise ProviderDatasetRowsMigrationError(
            "provider_dataset_rows database binding changed"
        )
    try:
        observed = binding.path.lstat()
    except OSError:
        raise ProviderDatasetRowsMigrationError(
            "provider_dataset_rows database binding changed"
        ) from None
    if (
        stat.S_ISLNK(observed.st_mode)
        or not stat.S_ISREG(observed.st_mode)
        or _file_identity(observed) != binding.database_identity
    ):
        raise ProviderDatasetRowsMigrationError(
            "provider_dataset_rows database binding changed"
        )


def _quote_identifier(identifier: str) -> str:
    return '"' + str(identifier).replace('"', '""') + '"'


def _table_exists(conn: sqlite3.Connection) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (PROVIDER_DATASET_ROWS_TABLE,),
        ).fetchone()
        is not None
    )


def _validate_columns_and_primary_key(conn: sqlite3.Connection) -> None:
    rows = conn.execute(
        f"PRAGMA table_xinfo({_quote_identifier(PROVIDER_DATASET_ROWS_TABLE)})"
    ).fetchall()
    if len(rows) != len(PROVIDER_DATASET_ROWS_COLUMNS):
        raise ProviderDatasetRowsSchemaError(
            "provider_dataset_rows column count does not match canonical contract"
        )

    for actual, expected in zip(rows, PROVIDER_DATASET_ROWS_COLUMNS, strict=True):
        name, column_type, nullable, default_sql, pk_position = expected
        actual_contract = (
            str(actual[1]),
            str(actual[2]).upper(),
            bool(actual[3]),
            None if actual[4] is None else str(actual[4]),
            int(actual[5]),
            int(actual[6]),
        )
        expected_contract = (
            name,
            column_type,
            not nullable,
            default_sql,
            pk_position,
            0,
        )
        if actual_contract != expected_contract:
            raise ProviderDatasetRowsSchemaError(
                f"provider_dataset_rows column contract mismatch: {name}"
            )

    primary_key = tuple(
        str(row[1])
        for row in sorted(
            (row for row in rows if int(row[5]) > 0), key=lambda row: row[5]
        )
    )
    if primary_key != _PRIMARY_KEY:
        raise ProviderDatasetRowsSchemaError(
            "provider_dataset_rows primary key does not match canonical contract"
        )

    pk_indexes = [
        row
        for row in conn.execute(
            f"PRAGMA index_list({_quote_identifier(PROVIDER_DATASET_ROWS_TABLE)})"
        ).fetchall()
        if str(row[3]) == "pk"
    ]
    if len(pk_indexes) != 1 or not bool(pk_indexes[0][2]):
        raise ProviderDatasetRowsSchemaError(
            "provider_dataset_rows primary-key index is missing or non-unique"
        )
    pk_index_name = str(pk_indexes[0][1])
    pk_columns = _index_key_columns(conn, pk_index_name)
    if pk_columns != _PRIMARY_KEY:
        raise ProviderDatasetRowsSchemaError(
            "provider_dataset_rows primary-key index columns drifted"
        )
    _validate_index_key_semantics(conn, pk_index_name, _PRIMARY_KEY)


def _index_key_columns(conn: sqlite3.Connection, index_name: str) -> tuple[str, ...]:
    return tuple(
        str(row[2])
        for row in conn.execute(
            f"PRAGMA index_xinfo({_quote_identifier(index_name)})"
        ).fetchall()
        if int(row[5]) == 1
    )


def _index_key_semantics(
    conn: sqlite3.Connection, index_name: str
) -> tuple[tuple[str, str | None, int], ...]:
    """Return key column, collation and descending flag from index_xinfo."""

    return tuple(
        (
            str(row[2]),
            None if row[4] is None else str(row[4]).upper(),
            int(row[3]),
        )
        for row in conn.execute(
            f"PRAGMA index_xinfo({_quote_identifier(index_name)})"
        ).fetchall()
        if int(row[5]) == 1
    )


def _validate_index_key_semantics(
    conn: sqlite3.Connection, index_name: str, expected_columns: tuple[str, ...]
) -> None:
    expected = tuple((column, "BINARY", 0) for column in expected_columns)
    if _index_key_semantics(conn, index_name) != expected:
        raise ProviderDatasetRowsSchemaError(
            "provider_dataset_rows index key collation or direction drifted: "
            f"{index_name}"
        )


def _validate_indexes(conn: sqlite3.Connection) -> None:
    raw_index_rows = conn.execute(
        f"PRAGMA index_list({_quote_identifier(PROVIDER_DATASET_ROWS_TABLE)})"
    ).fetchall()
    index_rows = {str(row[1]): row for row in raw_index_rows}
    pk_index_names = {str(row[1]) for row in raw_index_rows if str(row[3]) == "pk"}
    expected_index_names = set(PROVIDER_DATASET_ROWS_INDEX_COLUMNS) | pk_index_names
    unexpected = set(index_rows) - expected_index_names
    if unexpected:
        raise ProviderDatasetRowsSchemaError(
            "provider_dataset_rows unexpected index or UNIQUE constraint: "
            + ", ".join(sorted(unexpected))
        )
    for index_name, expected_columns in PROVIDER_DATASET_ROWS_INDEX_COLUMNS.items():
        row = index_rows.get(index_name)
        if row is None:
            raise ProviderDatasetRowsSchemaError(
                f"provider_dataset_rows index is missing: {index_name}"
            )
        if bool(row[2]) or str(row[3]) != "c" or bool(row[4]):
            raise ProviderDatasetRowsSchemaError(
                f"provider_dataset_rows index attributes drifted: {index_name}"
            )
        if _index_key_columns(conn, index_name) != expected_columns:
            raise ProviderDatasetRowsSchemaError(
                f"provider_dataset_rows index columns drifted: {index_name}"
            )
        _validate_index_key_semantics(conn, index_name, expected_columns)


def _normalize_create_table_sql(sql: str) -> str:
    normalized = re.sub(r"\s+", " ", sql.strip().lower())
    return re.sub(
        r"^create table if not exists ",
        "create table ",
        normalized,
        count=1,
    )


def _validate_check_ddl(conn: sqlite3.Connection) -> None:
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
        (PROVIDER_DATASET_ROWS_TABLE,),
    ).fetchone()
    if row is None or row[0] is None:
        raise ProviderDatasetRowsSchemaError(
            "provider_dataset_rows canonical CREATE TABLE SQL is missing"
        )
    actual = _normalize_create_table_sql(str(row[0]))
    expected = _normalize_create_table_sql(PROVIDER_DATASET_ROWS_CREATE_SQL)
    if actual != expected:
        raise ProviderDatasetRowsSchemaError(
            "provider_dataset_rows table or CHECK contract does not match canonical DDL"
        )


def _probe_row(prefix: str) -> dict[str, object]:
    return {
        "dataset_id": f"__schema_probe__.{prefix}",
        "provider": "schema_probe",
        "schema_major": 1,
        "ingested_schema_version": "1.0.0",
        "row_key": prefix,
        "observed_at": None,
        "partition_value": None,
        "payload_json": '{"probe":true}',
        "payload_hash": "0" * 64,
        "quality_state": "valid",
        "quality_issues_json": "[]",
        "collected_at": "2000-01-01T00:00:00+00:00",
        "receipt_id": f"schema-probe-{prefix}",
        "revision": 1,
    }


def _validate_json_and_checks(conn: sqlite3.Connection) -> None:
    savepoint = "provider_dataset_rows_postflight"
    conn.execute(f"SAVEPOINT {savepoint}")
    try:
        prefix = uuid4().hex
        valid = _probe_row(f"{prefix}-valid")
        conn.execute(_INSERT_SQL, valid)

        probes: tuple[tuple[str, object], ...] = (
            ("schema_major", 0),
            ("payload_json", "{"),
            ("payload_json", "[]"),
            ("quality_state", "unknown"),
            ("quality_issues_json", "{"),
            ("quality_issues_json", "{}"),
            ("revision", 0),
        )
        for index, (column, value) in enumerate(probes):
            invalid = _probe_row(f"{prefix}-invalid-{index}")
            invalid[column] = value
            try:
                conn.execute(_INSERT_SQL, invalid)
            except sqlite3.IntegrityError:
                continue
            raise ProviderDatasetRowsSchemaError(
                f"provider_dataset_rows CHECK did not reject invalid {column}"
            )
    finally:
        conn.execute(f"ROLLBACK TO {savepoint}")
        conn.execute(f"RELEASE {savepoint}")


def validate_provider_dataset_rows_schema(conn: sqlite3.Connection) -> None:
    """Validate the exact SQLite table, PK, indexes, JSON and CHECK behavior."""

    if not _table_exists(conn):
        raise ProviderDatasetRowsSchemaError("provider_dataset_rows table is missing")
    _validate_columns_and_primary_key(conn)
    _validate_indexes(conn)
    _validate_check_ddl(conn)
    _validate_json_and_checks(conn)


def apply_provider_dataset_rows_migration(
    db_path: Path,
) -> ProviderDatasetRowsMigrationResult:
    """Create and postflight the generic table in one SQLite transaction.

    The target file must already exist.  This prevents a mistyped production
    path from creating a new empty authority.  Any DDL or postflight error is
    propagated after an explicit rollback; existing tables and rows are never
    modified by this migration.
    """

    if not isinstance(db_path, Path):
        raise TypeError("db_path must be pathlib.Path")
    binding, binding_descriptor = _bind_existing_database(db_path)
    conn: sqlite3.Connection | None = None
    created = False
    try:
        _require_unchanged_database_binding(binding)
        uri = f"{binding.path.as_uri()}?mode=rw&nofollow=1"
        conn = sqlite3.connect(uri, uri=True, timeout=10.0, isolation_level=None)
        _require_unchanged_database_binding(binding)
        conn.execute("PRAGMA busy_timeout = 10000")
        conn.execute("BEGIN IMMEDIATE")
        _require_unchanged_database_binding(binding)
        created = not _table_exists(conn)
        for statement in PROVIDER_DATASET_ROWS_MIGRATION_STATEMENTS:
            conn.execute(statement)
        validate_provider_dataset_rows_schema(conn)
        _require_unchanged_database_binding(binding)
        conn.execute("COMMIT")
    except BaseException as exc:
        if conn is not None and conn.in_transaction:
            try:
                conn.execute("ROLLBACK")
            except sqlite3.Error as rollback_exc:
                raise ProviderDatasetRowsMigrationError(
                    "provider_dataset_rows migration failed and rollback failed"
                ) from rollback_exc
        if isinstance(exc, ProviderDatasetRowsMigrationError):
            raise
        raise ProviderDatasetRowsMigrationError(
            f"provider_dataset_rows migration failed: {type(exc).__name__}"
        ) from exc
    finally:
        if conn is not None:
            conn.close()
        os.close(binding_descriptor)

    return ProviderDatasetRowsMigrationResult(
        table=PROVIDER_DATASET_ROWS_TABLE,
        created=created,
        indexes=tuple(PROVIDER_DATASET_ROWS_INDEX_COLUMNS),
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Atomically add the canonical provider_dataset_rows SQLite table"
    )
    parser.add_argument(
        "--db", type=Path, required=True, help="existing SQLite database"
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="required write acknowledgement; without it the command refuses to run",
    )
    args = parser.parse_args()
    if not args.apply:
        parser.error(
            "--apply is required; run only after a fresh safe-release preflight"
        )
    return args


def main() -> int:
    args = _parse_args()
    try:
        result = apply_provider_dataset_rows_migration(args.db)
    except (OSError, sqlite3.Error, ProviderDatasetRowsMigrationError) as exc:
        print(
            json.dumps(
                {"status": "error", "error_class": type(exc).__name__},
                sort_keys=True,
            )
        )
        return 1
    print(json.dumps({"status": "ok", **asdict(result)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

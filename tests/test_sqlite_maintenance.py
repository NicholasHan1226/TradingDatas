from __future__ import annotations

import sqlite3
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from tools import sqlite_maintenance


ROOT = Path(__file__).resolve().parents[1]


def _create_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("CREATE TABLE sample (id INTEGER PRIMARY KEY, value TEXT)")
    conn.execute("INSERT INTO sample(value) VALUES ('ok')")
    conn.commit()
    conn.close()


def test_routine_sqlite_maintenance_is_bounded(tmp_path: Path) -> None:
    db_path = tmp_path / "marketdata.sqlite"
    _create_db(db_path)

    result = sqlite_maintenance.run_maintenance(db_path, deep_check=False)

    assert result["owner"] == "SharedSignals"
    assert result["status"] == "green"
    assert result["integrity"] == "not_run"
    assert result["optimized"] is True
    assert result["wal_checkpoint"]["busy"] == 0
    assert isinstance(result["wal_checkpoint"]["log_frames"], int)
    assert isinstance(result["wal_checkpoint"]["checkpointed_frames"], int)
    assert datetime.fromisoformat(result["started_at"])
    assert datetime.fromisoformat(result["completed_at"])


def test_deep_sqlite_maintenance_runs_quick_check_only_on_request(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "marketdata.sqlite"
    _create_db(db_path)

    result = sqlite_maintenance.run_maintenance(db_path, deep_check=True)

    assert result["status"] == "green"
    assert result["integrity"] == "ok"
    assert result["deep_check"] is True


def test_missing_database_fails_closed_without_creating_a_file(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "missing.sqlite"

    result = sqlite_maintenance.run_maintenance(db_path)

    assert result["status"] == "red"
    assert result["optimized"] is False
    assert result["integrity"] == "not_run"
    assert result["error"] == "database_not_found"
    assert not db_path.exists()


def test_routine_maintenance_executes_only_bounded_pragmas(
    tmp_path: Path, monkeypatch
) -> None:
    db_path = tmp_path / "marketdata.sqlite"
    db_path.touch()
    statements: list[str] = []

    class _Cursor:
        def __init__(self, row=None) -> None:
            self._row = row

        def fetchone(self):
            return self._row

    class _Connection:
        def execute(self, statement: str):
            statements.append(statement)
            if statement == "PRAGMA wal_checkpoint(PASSIVE)":
                return _Cursor((0, 7, 7))
            return _Cursor()

        def close(self) -> None:
            return None

    monkeypatch.setattr(
        sqlite_maintenance.sqlite3,
        "connect",
        lambda *args, **kwargs: _Connection(),
    )

    result = sqlite_maintenance.run_maintenance(db_path, deep_check=False)

    assert result["status"] == "green"
    assert statements == [
        "PRAGMA wal_checkpoint(PASSIVE)",
        "PRAGMA optimize(0x10002)",
    ]
    assert all("VACUUM" not in statement.upper() for statement in statements)
    assert all("DELETE" not in statement.upper() for statement in statements)


def test_sqlite_maintenance_cli_runs_without_wrapper_pythonpath(
    tmp_path: Path,
) -> None:
    completed = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "sqlite_maintenance.py"), "--help"],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert "--deep-check" in completed.stdout

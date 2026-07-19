from __future__ import annotations

import os
from pathlib import Path
import sqlite3
import stat
import subprocess
import sys

import pytest

from storage.sqlite_authority_lock import sqlite_authority_lock_path
from tools.init_tradingdatas_store import StoreInitializationError, initialize_store


ROOT = Path(__file__).resolve().parents[1]


def _table_names(path: Path) -> list[str]:
    with sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True) as conn:
        return [
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )
        ]


def test_initialize_store_creates_only_clean_slate_authorities(tmp_path: Path) -> None:
    database = (tmp_path / "provider_native.sqlite").absolute()

    assert initialize_store(database) == "created"

    assert _table_names(database) == ["market_ingest_runs", "provider_dataset_rows"]
    assert stat.S_IMODE(database.stat().st_mode) == 0o600
    lock_path = sqlite_authority_lock_path(database)
    assert lock_path.is_file()
    assert stat.S_IMODE(lock_path.stat().st_mode) == 0o600


def test_initialize_store_validates_existing_without_rewriting(tmp_path: Path) -> None:
    database = (tmp_path / "provider_native.sqlite").absolute()
    assert initialize_store(database) == "created"
    before = (database.stat().st_dev, database.stat().st_ino, database.read_bytes())

    assert initialize_store(database) == "existing"

    after = (database.stat().st_dev, database.stat().st_ino, database.read_bytes())
    assert after == before


def test_initialize_store_rejects_relative_or_symlink_database(tmp_path: Path) -> None:
    with pytest.raises(StoreInitializationError, match="absolute canonical"):
        initialize_store(Path("provider_native.sqlite"))

    target = (tmp_path / "target.sqlite").absolute()
    target.touch(mode=0o600)
    link = (tmp_path / "provider_native.sqlite").absolute()
    link.symlink_to(target)
    with pytest.raises(StoreInitializationError, match="regular file"):
        initialize_store(link)


def test_initialize_store_rejects_non_clean_slate_existing_database(
    tmp_path: Path,
) -> None:
    database = (tmp_path / "provider_native.sqlite").absolute()
    assert initialize_store(database) == "created"
    with sqlite3.connect(database) as conn:
        conn.execute("CREATE TABLE legacy_business_state (id INTEGER PRIMARY KEY)")

    with pytest.raises(StoreInitializationError, match="table set"):
        initialize_store(database)


def test_initialize_store_rejects_unsafe_database_mode(tmp_path: Path) -> None:
    database = (tmp_path / "provider_native.sqlite").absolute()
    assert initialize_store(database) == "created"
    os.chmod(database, 0o666)

    with pytest.raises(StoreInitializationError, match="mode"):
        initialize_store(database)


def test_init_entrypoint_imports_from_an_arbitrary_working_directory(
    tmp_path: Path,
) -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools" / "init_tradingdatas_store.py"),
            "--help",
        ],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "--database" in result.stdout


def test_init_module_entrypoint_requires_repo_root_or_installed_context(
    tmp_path: Path,
) -> None:
    from_repo = subprocess.run(
        [sys.executable, "-m", "tools.init_tradingdatas_store", "--help"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    from_uninstalled_cwd = subprocess.run(
        [sys.executable, "-I", "-m", "tools.init_tradingdatas_store", "--help"],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        check=False,
    )

    assert from_repo.returncode == 0, from_repo.stderr
    assert from_uninstalled_cwd.returncode != 0
    assert "No module named" in from_uninstalled_cwd.stderr


def _run_init_cli(
    tmp_path: Path,
    raw_database: str,
    *,
    data_root: Path,
    configured_database: str,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools" / "init_tradingdatas_store.py"),
            "--database",
            raw_database,
        ],
        cwd=tmp_path,
        env={
            **os.environ,
            "TRADINGDATAS_DATA_MOUNT": str(tmp_path),
            "TRADINGDATAS_DATA_ROOT": str(data_root),
            "TRADINGDATAS_DB_PATH": configured_database,
        },
        text=True,
        capture_output=True,
        check=False,
    )


def test_init_cli_creates_configured_database_from_arbitrary_working_directory(
    tmp_path: Path,
) -> None:
    data_root = tmp_path / "data"
    read_model = data_root / "read_model"
    read_model.mkdir(parents=True)
    database = read_model / "provider_native.sqlite"

    result = _run_init_cli(
        tmp_path,
        str(database),
        data_root=data_root,
        configured_database=str(database),
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "created"
    assert database.is_file()


@pytest.mark.parametrize(
    "raw_database_factory",
    [
        lambda database: "provider_native.sqlite",
        lambda database: f"//{str(database).lstrip('/')}",
        lambda database: f"{database.parent}//{database.name}",
        lambda database: f"{database.parent}/./{database.name}",
        lambda database: f"{database.parent}/child/../{database.name}",
        lambda database: f"{database}/",
    ],
    ids=["relative", "double-leading", "double-slash", "dot", "dotdot", "trailing"],
)
def test_init_cli_rejects_noncanonical_raw_database_before_output(
    tmp_path: Path,
    raw_database_factory,
) -> None:
    data_root = tmp_path / "data"
    read_model = data_root / "read_model"
    read_model.mkdir(parents=True)
    database = read_model / "provider_native.sqlite"
    raw_database = raw_database_factory(database)

    result = _run_init_cli(
        tmp_path,
        raw_database,
        data_root=data_root,
        configured_database=str(database),
    )

    assert result.returncode != 0
    assert "absolute lexical canonical" in result.stderr
    assert not database.exists()
    assert not list(read_model.glob(".*.init-*"))


def test_init_cli_rejects_database_outside_configured_data_root_before_output(
    tmp_path: Path,
) -> None:
    data_root = tmp_path / "data"
    (data_root / "read_model").mkdir(parents=True)
    database = tmp_path / "outside.sqlite"

    result = _run_init_cli(
        tmp_path,
        str(database),
        data_root=data_root,
        configured_database=str(database),
    )

    assert result.returncode != 0
    assert "TRADINGDATAS_DATA_ROOT" in result.stderr
    assert not database.exists()

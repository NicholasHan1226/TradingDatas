from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import env_bootstrap


def test_no_import_time_env_mutation() -> None:
    root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["PYTHONPATH"] = f"{root}{os.pathsep}{env.get('PYTHONPATH', '')}"
    script = """
import json
import os
import sys
import warnings

warnings.simplefilter("ignore", FutureWarning)
before = dict(os.environ)

import env_bootstrap  # noqa: F401
import query_cursor  # noqa: F401
import runtime_paths  # noqa: F401

after = dict(os.environ)
added = sorted(set(after) - set(before))
changed = sorted(k for k in before if before[k] != after.get(k))
print(json.dumps({"added": added, "changed": changed}, sort_keys=True))
sys.exit(1 if added or changed else 0)
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=root,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    payload = json.loads(result.stdout or "{}")
    assert result.returncode == 0, payload


def test_parse_env_file_empty_values_comments_and_export(tmp_path: Path) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text(
        "\n".join(
            [
                "# comment only",
                "   # indented comment",
                "EMPTY_VALUE=",
                "export EXPORTED_KEY=exported",
                "QUOTED='quoted value'",
                "",
            ]
        ),
        encoding="utf-8",
    )

    parsed = env_bootstrap.parse_env_file(env_path)

    assert parsed == {
        "EMPTY_VALUE": "",
        "EXPORTED_KEY": "exported",
        "QUOTED": "quoted value",
    }


def test_parse_missing_env_file_returns_empty_dict(tmp_path: Path) -> None:
    assert env_bootstrap.parse_env_file(tmp_path / "missing.env") == {}


def test_repeated_bootstrap_calls_return_empty_second_time(
    tmp_path: Path, monkeypatch
) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text("TRADINGDATAS_TEST_KEY=value\n", encoding="utf-8")
    target: dict[str, str] = {}
    monkeypatch.setattr(env_bootstrap, "_LOADED", False)

    first = env_bootstrap.bootstrap_tradingdatas_env(env_path, environ=target)
    second = env_bootstrap.bootstrap_tradingdatas_env(env_path, environ=target)

    assert first == {"TRADINGDATAS_TEST_KEY": "value"}
    assert second == {}
    assert target == {"TRADINGDATAS_TEST_KEY": "value"}


def test_bootstrap_rejects_non_tradingdatas_environment_names(
    tmp_path: Path, monkeypatch
) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text(
        "TRADINGDATAS_API_HOST=127.0.0.1\nSHAREDSIGNALS_LOCALHOST_BYPASS=1\n",
        encoding="utf-8",
    )
    target: dict[str, str] = {}
    monkeypatch.setattr(env_bootstrap, "_LOADED", False)

    with pytest.raises(ValueError, match="TRADINGDATAS"):
        env_bootstrap.bootstrap_tradingdatas_env(env_path, environ=target)

    assert target == {}


def test_typed_env_helpers_fall_back_on_malformed_values(monkeypatch) -> None:
    monkeypatch.setenv("BAD_INT", "not-an-int")
    monkeypatch.setenv("TOO_HIGH_INT", "999")
    monkeypatch.setenv("BAD_FLOAT", "nan")
    monkeypatch.setenv("BOOL_TRUE", "yes")
    monkeypatch.setenv("BOOL_FALSE", "0")

    assert env_bootstrap.env_int("BAD_INT", 7) == 7
    assert env_bootstrap.env_int("TOO_HIGH_INT", 7, min_value=1, max_value=20) == 20
    assert (
        env_bootstrap.env_float("BAD_FLOAT", 2.5, min_value=1.0, max_value=5.0) == 2.5
    )
    assert env_bootstrap.env_bool("BOOL_TRUE", False) is True
    assert env_bootstrap.env_bool("BOOL_FALSE", True) is False


@pytest.mark.parametrize(
    "raw_path",
    [
        "/tmp/tradingdatas/../escape",
        "/tmp/tradingdatas//root",
        "/tmp/tradingdatas/./root",
        "/tmp/tradingdatas-data/",
    ],
)
def test_python_runtime_paths_reject_noncanonical_lexical_values(
    monkeypatch: pytest.MonkeyPatch,
    raw_path: str,
) -> None:
    import runtime_paths

    monkeypatch.setenv("TRADINGDATAS_DATA_ROOT", raw_path)
    monkeypatch.setenv("TRADINGDATAS_DATA_MOUNT", "/tmp")

    with pytest.raises(runtime_paths.RuntimePathError, match="canonical"):
        runtime_paths.data_root()


def test_python_runtime_paths_reject_symlinked_parents_and_physical_escape(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import runtime_paths

    data_root = tmp_path / "data"
    data_root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (data_root / "read_model").symlink_to(outside, target_is_directory=True)
    monkeypatch.setenv("TRADINGDATAS_DATA_MOUNT", str(tmp_path))
    monkeypatch.setenv("TRADINGDATAS_DATA_ROOT", str(data_root))
    monkeypatch.setenv(
        "TRADINGDATAS_DB_PATH",
        str(data_root / "read_model" / "provider_native.sqlite"),
    )

    with pytest.raises(runtime_paths.RuntimePathError, match="symlink"):
        runtime_paths.provider_native_sqlite_path()

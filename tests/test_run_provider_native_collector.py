from __future__ import annotations

from pathlib import Path

import pytest

import tools.run_provider_native_collector as runner


def _stage_selector(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> tuple[Path, Path, Path]:
    runtime = tmp_path / "runtime"
    runtime.mkdir(mode=0o700)
    env_file = runtime / "on-demand.env"
    batch_file = runtime / "on-demand-batch.json"
    lock_file = runtime / "collect.lock"
    env_file.write_text(
        f"TRADINGDATAS_ON_DEMAND_BATCH_FILE={batch_file}\n",
        encoding="utf-8",
    )
    batch_file.write_text('{"version":1,"items":[]}', encoding="utf-8")
    env_file.chmod(0o600)
    batch_file.chmod(0o600)
    monkeypatch.setattr(runner, "RUNTIME_DIRECTORY", runtime)
    monkeypatch.setattr(runner, "ON_DEMAND_ENV_FILE", env_file)
    monkeypatch.setattr(runner, "ON_DEMAND_BATCH_FILE", batch_file)
    monkeypatch.setattr(runner, "COLLECT_LOCK_FILE", lock_file)
    monkeypatch.setenv(runner.ON_DEMAND_BATCH_ENV, str(batch_file))
    return env_file, batch_file, lock_file


def test_default_dispatch_uses_unchanged_cadence_runner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []
    monkeypatch.delenv(runner.ON_DEMAND_BATCH_ENV, raising=False)
    monkeypatch.setattr(
        runner.run_provider_native_schedule,
        "provider_native_sqlite_path",
        lambda: Path("/data/provider_native.sqlite"),
    )
    monkeypatch.setattr(
        runner.run_provider_native_schedule,
        "main",
        lambda args: calls.append(args) or 0,
    )

    assert runner.main() == 0
    assert calls == [
        [
            "--db-path",
            "/data/provider_native.sqlite",
            "--lock-path",
            "/run/tradingdatas/collect.lock",
            "--execute",
        ]
    ]


def test_on_demand_dispatch_consumes_selector_and_uses_shared_lock(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    env_file, batch_file, lock_file = _stage_selector(monkeypatch, tmp_path)
    calls: list[list[str]] = []
    monkeypatch.setattr(
        runner.run_provider_native_schedule,
        "provider_native_sqlite_path",
        lambda: Path("/data/provider_native.sqlite"),
    )
    monkeypatch.setattr(
        runner.collect_provider_dataset,
        "main",
        lambda args: calls.append(args) or 3,
    )

    assert runner.main() == 3
    assert calls == [
        [
            "--db-path",
            "/data/provider_native.sqlite",
            "--batch-file",
            str(batch_file),
            "--execute",
        ]
    ]
    assert not env_file.exists()
    assert not batch_file.exists()
    assert lock_file.exists()


def test_on_demand_rejects_selector_outside_runtime_directory(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv(runner.ON_DEMAND_BATCH_ENV, "/tmp/untrusted.json")

    assert runner.main() == 2
    assert capsys.readouterr().out == '{"mode":"execute","state":"validation"}\n'


def test_on_demand_rejects_non_private_batch_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _, batch_file, _ = _stage_selector(monkeypatch, tmp_path)
    batch_file.chmod(0o644)

    assert runner.main() == 2
    assert capsys.readouterr().out == '{"mode":"execute","state":"validation"}\n'
    assert not batch_file.exists()

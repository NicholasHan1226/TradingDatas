from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_ci_uses_four_xdist_shards_and_a_nightly_full_suite() -> None:
    workflow = _read(".github/workflows/ci.yml")

    assert "schedule:" in workflow
    assert 'cron: "17 18 * * *"' in workflow
    assert "workflow_dispatch:" in workflow
    assert "Nightly full tests" in workflow
    assert "PR fast tests" in workflow
    assert "shard_id: [0, 1, 2, 3]" in workflow
    assert "--shard-id=${{ matrix.shard_id }} --num-shards=4" in workflow
    assert workflow.count("-n auto") == 2
    assert workflow.count("--dist=loadfile") == 2
    assert '-m "not slow"' in workflow


def test_canary_and_timing_runtime_suites_are_marked_slow() -> None:
    for path in (
        "tests/test_binance_oi_dump_canary.py",
        "tests/test_binance_premium_dump_canary.py",
        "tests/test_binance_spot_canary.py",
        "tests/test_binance_usdm_canary.py",
        "tests/test_crypto_loopback_runtime.py",
        "tests/test_v1_api.py",
    ):
        assert "pytestmark = pytest.mark.slow" in _read(path)

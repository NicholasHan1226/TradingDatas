from __future__ import annotations

from pathlib import Path

from collectors.tushare.collector import TushareCollector
from collectors.tushare.sync_daily import load_config
from storage.read_model_store import API_TO_TABLE_MAP


CRONTAB_FILES = (Path("crontab.txt"), Path("cron/crontab.txt"))
PRODUCTION_CODE_GLOBS = (
    "reader.py",
    "runtime_paths.py",
    "api_server.py",
    "patrol.py",
    "heal.py",
    "collectors/**/*.py",
    "cron/*.sh",
    "tools/*.py",
    "storage/*.py",
    "reference/*.py",
)


def _configured_tushare_apis() -> list[tuple[str, str, dict]]:
    config = load_config(Path("collectors/tushare/config.yaml"))
    return [
        (tier, api["api_name"], api)
        for tier, apis in config["priorities"].items()
        for api in apis
    ]


def test_all_configured_tushare_interfaces_are_db_mapped_and_api_visible() -> None:
    from api_server import ALLOWED_TUSHARE_APIS

    missing_db: list[str] = []
    missing_api: list[str] = []
    for tier, api_name, _api in _configured_tushare_apis():
        key = f"{tier}:{api_name}"
        if api_name not in API_TO_TABLE_MAP:
            missing_db.append(key)
        if api_name not in ALLOWED_TUSHARE_APIS:
            missing_api.append(key)

    assert missing_db == []
    assert missing_api == []


def test_configured_tushare_interfaces_declare_frequency_and_rate_guard() -> None:
    missing_frequency: list[str] = []
    for tier, api_name, api in _configured_tushare_apis():
        if not api.get("frequency") and tier in {
            "P0_trading_5min",
            "P1_eod_daily",
            "P2_financial_daily",
            "P3_reference_daily",
            "P4_macro_daily",
            "P5_hk_us_daily",
        }:
            missing_frequency.append(f"{tier}:{api_name}")

    assert missing_frequency == []
    assert TushareCollector._rate_window_sec == 60
    assert TushareCollector._rate_limit_per_window > 0


def test_tushare_collection_entrypoints_do_not_allow_csv_only_success() -> None:
    import collectors.tushare.sync_daily as sync_daily
    import collectors.tushare.backfill_fut_daily as backfill_fut_daily
    import tools.collect_cn_futures_daily as cn_futures_daily
    import tools.collect_cn_futures_5min as cn_futures_5min

    sync_daily_source = Path(sync_daily.__file__).read_text(encoding="utf-8")
    assert "--no-sqlite-bridge" not in sync_daily_source
    assert "--no-sqlite-bridge" not in Path(backfill_fut_daily.__file__).read_text(encoding="utf-8")
    assert "--no-sqlite-bridge" not in Path(cn_futures_daily.__file__).read_text(encoding="utf-8")
    assert "--no-sqlite-bridge" not in cn_futures_5min.parse_args.__code__.co_consts
    assert not hasattr(sync_daily, "STOCK_MASTER_PATH")
    assert "rt_k" not in API_TO_TABLE_MAP


def test_no_retired_bridge_or_orchestrator_entrypoints_remain() -> None:
    retired_paths = [
        Path("storage/ndjson_bridge.py"),
        Path("bridge/marketgraph_runtime_bridge.py"),
        Path("collectors/orchestrator.py"),
        Path("collectors/registry.yaml"),
        Path("collectors/run_collectors.sh"),
        Path("collectors/pm_parquet_loader.py"),
        Path("collectors/polymarket/collector.py"),
        Path("collectors/polymarket/parquet_loader.py"),
        Path("source_failover.py"),
    ]
    assert [str(path) for path in retired_paths if path.exists()] == []


def test_production_code_does_not_reference_retired_csv_or_bridge_paths() -> None:
    banned = (
        "--no-sqlite-bridge",
        "--no-bridge",
        "storage/ndjson_bridge.py",
        "source_failover.py",
        "event_candidates.csv",
        "sentiment_signals.csv",
        "collection_runs.csv",
        "MarketGraphRuntime/read_model/" + "marketdata.sqlite",
    )
    offenders: list[str] = []
    for pattern in PRODUCTION_CODE_GLOBS:
        for path in Path(".").glob(pattern):
            if path.is_dir() or not path.exists():
                continue
            text = path.read_text(encoding="utf-8")
            for token in banned:
                if token in text:
                    offenders.append(f"{path}:{token}")
    assert offenders == []


def test_external_api_output_endpoints_cover_configured_tushare_interfaces() -> None:
    from api_server import ALLOWED_TUSHARE_APIS

    configured = {api_name for _tier, api_name, _api in _configured_tushare_apis()}
    assert configured <= set(ALLOWED_TUSHARE_APIS)


def test_production_cron_declares_required_collection_and_health_cadence() -> None:
    required_lines = {
        "*/5 9-15 * * 1-5 /opt/investment/SharedSignals/cron/collectors.sh --tier P0_trading_5min",
        "*/5 9-15,21-23 * * 1-5 /opt/investment/SharedSignals/cron/cn_futures_5min.sh",
        "*/5 0-2 * * 2-6 /opt/investment/SharedSignals/cron/cn_futures_5min.sh",
        "2-59/5 * * * * /opt/investment/SharedSignals/cron/crypto_collect.sh",
        "*/5 * * * * /opt/investment/SharedSignals/cron/pm_collect.sh",
        "*/5 * * * * /opt/investment/SharedSignals/cron/watchdog.sh",
        "3-59/10 * * * * /opt/investment/SharedSignals/cron/health_sla.sh",
        "17 * * * * /opt/investment/SharedSignals/cron/capability_scan.sh",
    }
    tier_lines = {
        "P1_eod_daily",
        "P2_financial_daily",
        "P3_reference_daily",
        "P4_macro_daily",
        "P5_hk_us_daily",
        "P6_other_daily",
    }

    for crontab_path in CRONTAB_FILES:
        text = crontab_path.read_text(encoding="utf-8")
        missing = sorted(line for line in required_lines if line not in text)
        missing_tiers = sorted(
            tier for tier in tier_lines if f"/opt/investment/SharedSignals/cron/collectors.sh --tier {tier}" not in text
        )
        assert missing == []
        assert missing_tiers == []

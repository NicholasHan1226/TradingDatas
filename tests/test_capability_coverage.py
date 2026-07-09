from __future__ import annotations

import json
import subprocess
from pathlib import Path

from collectors.tushare.collector import TushareCollector
from collectors.tushare.sync_daily import load_config
from storage.read_model_store import API_TO_TABLE_MAP


CRONTAB_FILES = (Path("crontab.txt"), Path("cron/crontab.txt"))
TUSHARE_CAPABILITY_PLAN = Path("config/tushare_capability_plan.yaml")
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


def _planned_tushare_apis() -> list[dict]:
    import yaml

    payload = yaml.safe_load(TUSHARE_CAPABILITY_PLAN.read_text(encoding="utf-8"))
    rows: list[dict] = []
    for module in payload.get("modules", []):
        for api in module.get("apis", []):
            item = dict(api)
            item["module"] = module["module"]
            item["market"] = module["market"]
            rows.append(item)
    return rows


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
        if not api.get("frequency"):
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
        Path("storage/archive_manager.py"),
        Path("storage/query_router.py"),
        Path("storage/cold"),
    ]
    assert [str(path) for path in retired_paths if path.exists()] == []


def test_repo_data_directory_contains_no_production_fallback_files() -> None:
    forbidden_suffixes = {".csv", ".ndjson", ".sqlite", ".db", ".parquet"}
    offenders = [
        str(path)
        for path in Path("data").rglob("*")
        if path.is_file() and path.suffix.lower() in forbidden_suffixes
    ]

    assert offenders == []


def test_repository_contains_no_tracked_runtime_data_artifacts() -> None:
    forbidden_suffixes = {".csv", ".ndjson", ".sqlite", ".db", ".parquet"}
    allowed_prefixes = ("tests/",)
    tracked = subprocess.check_output(["git", "ls-files"], text=True).splitlines()
    offenders = [
        path
        for path in tracked
        if Path(path).suffix.lower() in forbidden_suffixes
        and not path.startswith(allowed_prefixes)
    ]

    assert offenders == []


def test_polymarket_config_has_no_retired_parquet_loader_settings() -> None:
    config_path = Path("collectors/polymarket/config.yaml")
    if not config_path.exists():
        return
    text = config_path.read_text(encoding="utf-8")
    assert "parquet:" not in text
    assert "glob_pattern" not in text


def test_read_model_store_has_no_file_bridge_ingestion_entrypoints() -> None:
    text = Path("storage/read_model_store.py").read_text(encoding="utf-8")
    banned = [
        "import csv",
        "ingest_csv_to_sqlite",
        "ingest_date_partition",
        "CSV_BRIDGE",
        "CSV_ADDITIONAL_TABLES",
        "read_csv",
        "glob(\"*.csv\")",
    ]
    offenders = [token for token in banned if token in text]

    assert offenders == []


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
        "ingest_csv_to_sqlite",
        "ingest_date_partition",
        "CSV_BRIDGE",
        "storage/archive_manager.py",
        "storage/query_router.py",
        "storage/cold",
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


def test_tushare_capability_plan_covers_every_allowlisted_api() -> None:
    from api_server import ALLOWED_TUSHARE_APIS

    planned_rows = _planned_tushare_apis()
    planned = [row["api_name"] for row in planned_rows]
    allowed = set(ALLOWED_TUSHARE_APIS)
    allowed_modes = {"scheduled", "independent", "event_lane", "planned"}

    assert sorted(name for name in set(planned) if planned.count(name) > 1) == []
    assert set(planned) == allowed
    for row in planned_rows:
        assert row.get("module")
        assert row.get("market")
        assert row.get("cadence")
        assert row.get("mode") in allowed_modes


def test_tushare_capability_plan_marks_current_collection_paths() -> None:
    configured = {api_name for _tier, api_name, _api in _configured_tushare_apis()}
    planned_rows = _planned_tushare_apis()
    by_name = {row["api_name"]: row for row in planned_rows}

    missing = sorted(name for name in configured if by_name[name]["mode"] not in {"scheduled", "event_lane"})
    assert missing == []
    assert by_name["rt_fut_min"]["mode"] == "independent"


def test_relationship_member_apis_are_scheduled_and_mapped_to_relationships() -> None:
    configured = {api_name for _tier, api_name, _api in _configured_tushare_apis()}
    planned_rows = _planned_tushare_apis()
    by_name = {row["api_name"]: row for row in planned_rows}
    relationship_apis = {"ths_member", "dc_member", "index_member", "index_member_all"}

    assert relationship_apis <= configured
    for api_name in relationship_apis:
        assert API_TO_TABLE_MAP[api_name] == "market_relationships"
        assert by_name[api_name]["mode"] == "scheduled"
        assert by_name[api_name]["cadence"] == "daily_reference"


def test_b2_daily_supporting_apis_are_scheduled_and_mapped() -> None:
    configured = {api_name for _tier, api_name, _api in _configured_tushare_apis()}
    planned_rows = _planned_tushare_apis()
    by_name = {row["api_name"]: row for row in planned_rows}

    expected = {
        "ths_daily": ("market_bars_daily", "daily_reference"),
        "dc_daily": ("market_bars_daily", "postclose_daily"),
        "opt_daily": ("market_bars_daily", "postclose_daily"),
        "fut_holding": ("market_factors", "futures_settlement_daily"),
    }

    assert set(expected) <= configured
    for api_name, (table, cadence) in expected.items():
        assert API_TO_TABLE_MAP[api_name] == table
        assert by_name[api_name]["mode"] == "scheduled"
        assert by_name[api_name]["cadence"] == cadence


def test_final_planned_tushare_batch_is_scheduled_and_mapped() -> None:
    configured = {api_name for _tier, api_name, _api in _configured_tushare_apis()}
    planned_rows = _planned_tushare_apis()
    by_name = {row["api_name"]: row for row in planned_rows}

    expected = {
        "bak_basic": ("market_factors", "daily_reference"),
        "cyq_perf": ("market_factors", "postclose_daily"),
        "cyq_chips": ("market_factors", "postclose_daily"),
        "fina_audit": ("market_factors", "daily_reporting_window"),
        "fina_mainbz": ("market_factors", "daily_reporting_window"),
        "fund_adj": ("market_factors", "daily_nav"),
        "fund_portfolio": ("market_fund_portfolio", "reporting_window"),
        "ths_hot": ("market_factors", "intraday_or_daily_pilot"),
    }

    assert set(expected) <= configured
    for api_name, (table, cadence) in expected.items():
        assert API_TO_TABLE_MAP[api_name] == table
        assert by_name[api_name]["mode"] == "scheduled"
        assert by_name[api_name]["cadence"] == cadence


def test_tushare_event_wrapper_runs_only_event_apis() -> None:
    wrapper = Path("cron/tushare_events_collect.sh").read_text(encoding="utf-8")

    assert "P6_other_daily" in wrapper
    assert "--only-api" in wrapper
    assert "SHAREDSIGNALS_EVENT_APIS" in wrapper
    assert "anns_d,news,major_news,cctv_news,report_rc" in wrapper
    assert "--no-sqlite-bridge" not in wrapper


def test_tushare_low_frequency_wrapper_runs_only_low_frequency_apis() -> None:
    wrapper = Path("cron/tushare_low_frequency_collect.sh").read_text(encoding="utf-8")

    assert "P7_low_frequency" in wrapper
    assert "--only-api" in wrapper
    assert "SHAREDSIGNALS_LOW_FREQ_APIS" in wrapper
    assert "weekly,monthly,index_weekly,index_monthly" in wrapper
    assert "--no-sqlite-bridge" not in wrapper


def test_production_cron_declares_required_collection_and_health_cadence() -> None:
    required_lines = {
        "*/5 9-15 * * 1-5 /opt/investment/SharedSignals/cron/collectors.sh --tier P0_trading_5min",
        "*/5 9-15,21-23 * * 1-5 /opt/investment/SharedSignals/cron/cn_futures_5min.sh",
        "*/5 0-2 * * 2-6 /opt/investment/SharedSignals/cron/cn_futures_5min.sh",
        "2,32 * * * * /opt/investment/SharedSignals/cron/crypto_collect.sh",
        "7 */6 * * * SHAREDSIGNALS_CRYPTO_MODE=klines SHAREDSIGNALS_CRYPTO_INTERVALS=1d /opt/investment/SharedSignals/cron/crypto_collect.sh",
        "1,31 * * * * /opt/investment/SharedSignals/cron/pm_collect.sh",
        "*/30 8-23 * * 1-6 /opt/investment/SharedSignals/cron/tushare_events_collect.sh",
        "15,45 8-23 * * 1-6 SHAREDSIGNALS_EVENT_APIS=news,major_news /opt/investment/SharedSignals/cron/tushare_events_collect.sh",
        "40 7 * * 0 /opt/investment/SharedSignals/cron/tushare_low_frequency_collect.sh",
        "*/5 * * * * /opt/investment/SharedSignals/cron/watchdog.sh",
        "12,42 * * * * /opt/investment/SharedSignals/cron/patrol.sh",
        "7-59/15 * * * * /opt/investment/SharedSignals/cron/health_sla.sh",
        "5 8 * * * /opt/investment/SharedSignals/cron/source_governance_monitor.sh",
        "10 8 * * * /opt/investment/SharedSignals/cron/green_gate_report.sh",
        "17 0-8,16-23 * * * /opt/investment/SharedSignals/cron/duckdb_sync.sh",
        "52 0-8,16-23 * * * /opt/investment/SharedSignals/cron/capability_scan.sh",
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
        assert text.count("*/30 8-23 * * 1-6 /opt/investment/SharedSignals/cron/tushare_events_collect.sh") == 1
        assert text.count("15,45 8-23 * * 1-6 SHAREDSIGNALS_EVENT_APIS=news,major_news /opt/investment/SharedSignals/cron/tushare_events_collect.sh") == 1


def test_production_cron_keeps_heavy_jobs_out_of_trading_hot_path() -> None:
    forbidden_lines = {
        "2-59/5 * * * * /opt/investment/SharedSignals/cron/crypto_collect.sh",
        "*/5 * * * * /opt/investment/SharedSignals/cron/pm_collect.sh",
        "17 * * * * /opt/investment/SharedSignals/cron/duckdb_sync.sh",
        "*/10 * * * * /opt/investment/SharedSignals/cron/patrol.sh",
        "3-59/10 * * * * /opt/investment/SharedSignals/cron/health_sla.sh",
        "17 * * * * /opt/investment/SharedSignals/cron/capability_scan.sh",
    }

    for crontab_path in CRONTAB_FILES:
        text = crontab_path.read_text(encoding="utf-8")
        offenders = sorted(line for line in forbidden_lines if line in text)
        assert offenders == []


def test_core_docs_use_current_tushare_capability_and_agent_boundaries() -> None:
    docs = {
        "AGENTS.md": Path("AGENTS.md").read_text(encoding="utf-8"),
        "README.md": Path("README.md").read_text(encoding="utf-8"),
        "API_CONTRACT.md": Path("API_CONTRACT.md").read_text(encoding="utf-8"),
        "STATUS.md": Path("STATUS.md").read_text(encoding="utf-8"),
        "docs/market_capability_matrix.md": Path("docs/market_capability_matrix.md").read_text(encoding="utf-8"),
        "docs/external_agent_api_prompt.md": Path("docs/external_agent_api_prompt.md").read_text(encoding="utf-8"),
        "docs/tushare_activation_backlog.md": Path("docs/tushare_activation_backlog.md").read_text(encoding="utf-8"),
        "docs/event_lane.md": Path("docs/event_lane.md").read_text(encoding="utf-8"),
        "docs/data_source_onboarding.md": Path("docs/data_source_onboarding.md").read_text(encoding="utf-8"),
    }

    combined = "\n".join(docs.values())
    stale_tokens = [
        "83 个唯一接口",
        "83 configured interfaces",
        "P0-P6 分层 83",
        "P0-P6 Tushare 接口必须",
        "Tushare(P0-P6",
        "SharedSignals collector + staging/bridge 契约",
    ]
    offenders = [token for token in stale_tokens if token in combined]

    assert offenders == []
    assert "P0-P7" in docs["README.md"]
    assert "5 分钟级" in docs["AGENTS.md"]
    assert "外部 agent" in docs["API_CONTRACT.md"]
    assert "/agent_config" in docs["API_CONTRACT.md"]
    assert "不要绕过 SharedSignals" in docs["docs/external_agent_api_prompt.md"]
    assert "0 planned" in docs["docs/tushare_activation_backlog.md"]
    assert "event lane" in docs["docs/event_lane.md"]
    assert "新增数据源" in docs["docs/data_source_onboarding.md"]


def test_external_agent_config_matches_current_capability_counts() -> None:
    from api_server import ALLOWED_TUSHARE_APIS

    config = json.loads(Path("config/external_agent_api_config.json").read_text(encoding="utf-8"))
    planned_rows = _planned_tushare_apis()
    configured = {api_name for _tier, api_name, _api in _configured_tushare_apis()}
    planned = {row["api_name"] for row in planned_rows if row["mode"] == "planned"}
    active = {row["api_name"] for row in planned_rows if row["mode"] in {"scheduled", "independent", "event_lane"}}

    assert config["contract_version"] == "1.1.35"
    assert config["market_frequency_labels"]["Crypto"] == "30min ticker/intraday and 6-hour daily-bar support refresh"
    assert config["market_frequency_labels"]["PredictionMarkets"] == "30min markets/prices"
    assert config["market_frequency_labels"]["Events"] == "30min full event lane plus 15min news/major_news pilot refresh"
    cadence_by_path = {item["path"]: item["cadence_class"] for item in config["primary_endpoints"]}
    assert cadence_by_path["/crypto"] == "30min_crypto"
    assert cadence_by_path["/pm_markets"] == "30min_prediction_market"
    assert cadence_by_path["/pm_prices"] == "30min_prediction_market"
    assert config["tushare_status"]["allowlisted_api_names"] == len(ALLOWED_TUSHARE_APIS)
    assert config["tushare_status"]["configured_in_production_tiers"] == len(configured)
    assert config["tushare_status"]["planned_activation_backlog"] == len(planned)
    assert config["tushare_status"]["scheduled_or_independent_or_event_lane"] == len(active)
    assert config["data_source_onboarding"]["source_expansion_priority_plan"] == "config/source_expansion_priority.yaml"
    assert config["data_source_onboarding"]["api_module_catalog"] == "config/api_module_catalog.yaml"
    assert config["data_source_onboarding"]["horizontal_expansion_status"].startswith("planned_only")
    endpoint_paths = {item["path"] for item in config["primary_endpoints"]}
    required_paths = {
        "/health",
        "/capabilities",
        "/agent_config",
        "/source_status",
        "/cache/status",
        "/cache/invalidate",
        "/market_data",
        "/realtime_5min",
        "/is_trading_day",
        "/events",
        "/sentiment",
        "/fundamentals",
        "/reference",
        "/industry",
        "/macro",
        "/capital_flow",
        "/crypto",
        "/pm_markets",
        "/pm_prices",
        "/associations",
        "/impacts",
        "/tushare",
    }
    assert required_paths <= endpoint_paths
    assert config["data_source_onboarding"]["mandatory_fields"]
    assert "docs/data_source_onboarding.md" in config["data_source_onboarding"]["doc"]
    assert "Do not call Tushare" in " ".join(config["boundary"]["hard_forbidden"])


def test_production_config_matches_current_frequency_policy() -> None:
    import yaml

    prod = yaml.safe_load(Path("config/prod.yaml").read_text(encoding="utf-8"))
    collectors = prod["collectors"]

    assert "P7_low_frequency" in collectors["tushare"]["tiers"]
    assert collectors["binance"]["frequency"] == "30min"
    assert collectors["binance"]["daily_bar_frequency"] == "6h"
    assert collectors["polymarket"]["frequency"] == "30min"
    assert "rss" not in collectors
    assert "tavily" not in collectors
    assert "deepseek" not in collectors
    assert collectors["retired_or_deferred_sources"]["rss_rsshub"].startswith("retired")

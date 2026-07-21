from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SERVICE = ROOT / "deploy/systemd/tradingdatas-provider-native-collect.service"
TIMER = ROOT / "deploy/systemd/tradingdatas-provider-native-collect.timer"


def test_collector_unit_runs_only_the_generic_registry_scheduler() -> None:
    source = SERVICE.read_text(encoding="utf-8")

    assert "Type=oneshot" in source
    assert "User=tradingdatas" in source
    assert "Group=tradingdatas" in source
    assert "RuntimeDirectory=tradingdatas" in source
    assert "RuntimeDirectoryMode=0700" in source
    assert "SuccessExitStatus=75" in source
    assert source.count("ExecStart=") == 1
    assert (
        "ExecStart=/opt/tradingdatas/venv/bin/python3 "
        "/opt/investment/releases/tradingdatas/current/"
        "tools/run_provider_native_schedule.py "
    ) in source
    for argument in (
        "--db-path /opt/investment-data/tradingdatas/read_model/provider_native.sqlite",
        "--lock-path /run/tradingdatas/collect.lock",
        "--execute",
    ):
        assert argument in source
    for forbidden in (
        "TRADINGDATAS_ROOT",
        "TRADINGDATAS_REGISTRY_PATH",
        "TRADINGDATAS_SCHEDULE_PATH",
        "--schedule-config",
    ):
        assert forbidden not in source


def test_collector_unit_requires_private_file_backed_quicksync_credentials() -> None:
    source = SERVICE.read_text(encoding="utf-8")

    assert "ConditionPathExists=/etc/tradingdatas/quicksync.token" in source
    assert 'Environment="TUSHARE_API_URL=https://api.quicksync.cn"' in source
    assert (
        'Environment="TUSHARE_TOKEN_FILE=/etc/tradingdatas/quicksync.token"' in source
    )
    for forbidden in (
        "TUSHARE_TOKEN=",
        "QUICKSYNC_TOKEN=",
        "EnvironmentFile=/etc/sharedsignals",
        "SHAREDSIGNALS",
    ):
        assert forbidden not in source


def test_collector_unit_has_narrow_write_and_runtime_boundaries() -> None:
    source = SERVICE.read_text(encoding="utf-8")

    for required in (
        "NoNewPrivileges=true",
        "PrivateTmp=true",
        "PrivateDevices=true",
        "ProtectSystem=strict",
        "ProtectHome=true",
        "ReadOnlyPaths=/etc/tradingdatas",
        "ReadWritePaths=/opt/investment-data/tradingdatas",
        "RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6",
    ):
        assert required in source
    assert "IPAddressAllow=localhost" not in source
    assert "IPAddressDeny=any" not in source


def test_timer_only_wakes_the_registry_cadence_planner_every_five_minutes() -> None:
    source = TIMER.read_text(encoding="utf-8")

    assert "OnCalendar=*-*-* *:0/5:00" in source
    assert "RandomizedDelaySec=15s" in source
    assert "Persistent=true" in source
    assert "Unit=tradingdatas-provider-native-collect.service" in source
    assert "WantedBy=timers.target" in source
    assert "dataset" not in source.lower()
    assert "tushare" not in source.lower()

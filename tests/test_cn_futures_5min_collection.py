from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

from tools.collect_cn_futures_5min import (
    DEFAULT_PRODUCTS,
    SINA_PROVIDER,
    TUSHARE_PROVIDER,
    _normalize_sina_bar_time,
    _to_china_time,
    build_params,
    collect_sina_futures_minute_rows,
    load_recent_futures_symbols,
    main,
    normalize_product,
    run_collection,
)
from storage.schema import SCHEMA_SQL


def _create_universe_db(path: Path) -> None:
    conn = sqlite3.connect(str(path))
    try:
        conn.execute(
            """
            CREATE TABLE market_assets (
                market TEXT,
                symbol TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE market_bars_daily (
                market TEXT,
                symbol TEXT,
                trade_date TEXT
            )
            """
        )
        conn.executemany(
            "INSERT INTO market_assets VALUES (?, ?)",
            [
                ("Futures", "CU0001.SHF"),
                ("Futures", "CU2609.SHF"),
                ("Futures", "RB2609.SHF"),
                ("Futures", "IF2609.CFFEX"),
                ("Futures", "AU2609.SHF"),
            ],
        )
        conn.executemany(
            "INSERT INTO market_bars_daily VALUES (?, ?, ?)",
            [
                ("Futures", "CU2609.SHF", "20260703"),
                ("Futures", "RB2609.SHF", "20260703"),
                ("Futures", "IF2609.CFFEX", "20260703"),
                ("Futures", "AU2609.SHF", "20260703"),
            ],
        )
        conn.commit()
    finally:
        conn.close()


def _create_read_model_db(path: Path) -> None:
    conn = sqlite3.connect(str(path))
    try:
        conn.executescript(SCHEMA_SQL)
        conn.commit()
    finally:
        conn.close()


def test_normalize_product_handles_exchange_suffix() -> None:
    assert normalize_product("RB2609.SHF") == "rb"
    assert normalize_product("I2509.DCE") == "i"
    assert normalize_product("IF2609.CFFEX") == "if"
    assert "if" in DEFAULT_PRODUCTS
    assert "im" in DEFAULT_PRODUCTS


def test_load_recent_futures_symbols_prefers_daily_bars_and_filters_products(tmp_path: Path) -> None:
    db_path = tmp_path / "marketdata.sqlite"
    _create_universe_db(db_path)

    symbols = load_recent_futures_symbols(
        db_path,
        trade_date="20260704",
        products={"rb", "cu"},
        max_symbols=5,
    )

    assert symbols == ["CU2609.SHF", "RB2609.SHF"]


def test_load_recent_futures_symbols_default_products_include_stock_index_futures(tmp_path: Path) -> None:
    db_path = tmp_path / "marketdata.sqlite"
    _create_universe_db(db_path)

    symbols = load_recent_futures_symbols(
        db_path,
        trade_date="20260704",
        products=set(DEFAULT_PRODUCTS),
        max_symbols=10,
    )

    assert "IF2609.CFFEX" in symbols


def test_load_recent_futures_symbols_round_robins_products_before_truncating(tmp_path: Path) -> None:
    db_path = tmp_path / "marketdata.sqlite"
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            """
            CREATE TABLE market_bars_daily (
                market TEXT,
                symbol TEXT,
                trade_date TEXT
            )
            """
        )
        rows = []
        for product in ("CU", "I"):
            for month in range(1, 13):
                rows.append(("Futures", f"{product}26{month:02d}.SHF", "20260703"))
        rows.extend(
            [
                ("Futures", "IF2609.CFFEX", "20260703"),
                ("Futures", "IH2609.CFFEX", "20260703"),
                ("Futures", "IC2609.CFX", "20260703"),
                ("Futures", "IM2609.CFFEX", "20260703"),
            ]
        )
        conn.executemany("INSERT INTO market_bars_daily VALUES (?, ?, ?)", rows)
        conn.commit()
    finally:
        conn.close()

    symbols = load_recent_futures_symbols(
        db_path,
        trade_date="20260704",
        products=set(DEFAULT_PRODUCTS),
        max_symbols=8,
    )

    products = {normalize_product(symbol) for symbol in symbols}
    assert {"if", "ih", "ic", "im"}.issubset(products)


def test_build_params_uses_comma_separated_symbols() -> None:
    assert build_params(["CU2609.SHF", "RB2609.SHF"], freq="5MIN") == {
        "ts_code": "CU2609.SHF,RB2609.SHF",
        "freq": "5MIN",
    }


def test_rt_fut_min_is_allowed_for_api_self_checks() -> None:
    from api_server import ALLOWED_TUSHARE_APIS

    assert "rt_fut_min" in ALLOWED_TUSHARE_APIS


def test_run_collection_dry_run_does_not_call_tushare(tmp_path: Path) -> None:
    summary = run_collection(
        trade_date="20260703",
        symbols=["RB2609.SHF"],
        freq="5MIN",
        dry_run=True,
        sqlite_db_path=tmp_path / "marketdata.sqlite",
    )

    assert summary["state"] == "dry_run"
    assert summary["params"] == {"ts_code": "RB2609.SHF", "freq": "5MIN"}


def test_run_collection_surfaces_provider_errors(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def fail_provider(_params, *, fields: str = ""):
        raise RuntimeError("Tushare rt_fut_min failed code=40203: permission denied")

    monkeypatch.setattr("tools.collect_cn_futures_5min.collect_rt_fut_min_rows", fail_provider)
    summary = run_collection(
        trade_date="20260703",
        symbols=["RB2609.SHF"],
        freq="5MIN",
        dry_run=False,
        sqlite_db_path=tmp_path / "marketdata.sqlite",
    )

    assert summary["state"] == "failed"
    assert "permission denied" in summary["error"]


def test_run_collection_does_not_fallback_for_provider_errors(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        "tools.collect_cn_futures_5min.collect_rt_fut_min_rows",
        lambda _params, *, fields="": (_ for _ in ()).throw(RuntimeError("Tushare rt_fut_min failed code=40101: 权限不足")),
    )

    summary = run_collection(
        trade_date="20260703",
        symbols=["RB2609.SHF"],
        freq="5MIN",
        dry_run=False,
        sqlite_db_path=tmp_path / "marketdata.sqlite",
    )

    assert summary["state"] == "failed"
    assert "权限不足" in summary["error"]
    assert "fallback_from" not in summary


def test_run_collection_returns_empty_without_fallback_for_empty_tushare_rows(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        "tools.collect_cn_futures_5min.collect_rt_fut_min_rows",
        lambda _params, *, fields="": [],
    )

    summary = run_collection(
        trade_date="20260703",
        symbols=["RB2609.SHF"],
        freq="5MIN",
        dry_run=False,
        sqlite_db_path=tmp_path / "marketdata.sqlite",
    )

    assert summary["state"] == "empty"
    assert summary["source"] == "tushare_rt_fut_min"
    assert summary["rows"] == 0
    assert "fallback_from" not in summary


def test_tushare_collection_ignores_row_claiming_sina_provider(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    class FakeTushareCollector:
        def _rate_limit(self, _api_name: str) -> None:
            return None

    db_path = tmp_path / "marketdata.sqlite"
    _create_read_model_db(db_path)
    monkeypatch.setattr(
        "tools.collect_cn_futures_5min.TushareCollector",
        FakeTushareCollector,
    )
    monkeypatch.setattr(
        "tools.collect_cn_futures_5min.collect_rt_fut_min_rows",
        lambda _params, *, fields="": [
            {
                "code": "RB2609.SHF",
                "time": "2026-07-03 09:05:00",
                "provider": SINA_PROVIDER,
                "close": 3505,
                "vol": 120,
            }
        ],
    )

    summary = run_collection(
        trade_date="20260703",
        symbols=["RB2609.SHF"],
        freq="5MIN",
        provider=TUSHARE_PROVIDER,
        dry_run=False,
        sqlite_db_path=db_path,
    )

    assert summary["state"] == "ok"
    conn = sqlite3.connect(str(db_path))
    try:
        stored_provider = conn.execute(
            "SELECT provider FROM market_bars_intraday"
        ).fetchone()[0]
    finally:
        conn.close()
    assert stored_provider == TUSHARE_PROVIDER


def test_sina_collection_ignores_row_claiming_tushare_provider(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "marketdata.sqlite"
    _create_read_model_db(db_path)
    monkeypatch.setattr(
        "tools.collect_cn_futures_5min.collect_sina_futures_minute_rows",
        lambda symbols, *, period, max_rows_per_symbol, reference_time: [
            {
                "code": symbols[0],
                "time": "2026-07-03 09:10:00",
                "provider": TUSHARE_PROVIDER,
                "close": 3510,
                "vol": 125,
            }
        ],
    )

    summary = run_collection(
        trade_date="20260703",
        symbols=["RB2609.SHF"],
        freq="5MIN",
        provider=SINA_PROVIDER,
        dry_run=False,
        sqlite_db_path=db_path,
    )

    assert summary["state"] == "ok"
    conn = sqlite3.connect(str(db_path))
    try:
        stored_provider = conn.execute(
            "SELECT provider FROM market_bars_intraday"
        ).fetchone()[0]
    finally:
        conn.close()
    assert stored_provider == SINA_PROVIDER


def test_run_collection_fails_when_non_empty_rows_do_not_reach_sqlite(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        "tools.collect_cn_futures_5min.collect_rt_fut_min_rows",
        lambda _params, *, fields="": [
            {
                "code": "RB2609.SHF",
                "time": "2026-07-03 09:05:00",
                "close": "3505",
                "vol": "120",
            }
        ],
    )
    monkeypatch.setattr("tools.collect_cn_futures_5min.ingest_rows_to_sqlite", lambda *_args, **_kwargs: 0)

    summary = run_collection(
        trade_date="20260703",
        symbols=["RB2609.SHF"],
        freq="5MIN",
        dry_run=False,
        sqlite_db_path=tmp_path / "marketdata.sqlite",
    )

    assert summary["state"] == "failed"
    assert summary["sqlite_status"] == "failed"
    assert "direct sqlite write produced 0 rows" in summary["error"]


def test_main_rejects_empty_symbol_selection(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["--trade-date", "20260703", "--sqlite-db", str(tmp_path / "missing.sqlite"), "--dry-run"])

    assert code == 2
    assert "no futures symbols selected" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# Sina bar_time normalization — unit tests
# ---------------------------------------------------------------------------


def test_normalize_past_bar_unchanged() -> None:
    """Past bar: returned unchanged, no trade_date."""
    ref = _to_china_time(datetime(2026, 7, 10, 15, 0, 0))
    bar, td = _normalize_sina_bar_time("2026-07-10 14:55:00", ref)
    assert bar == "2026-07-10 14:55:00"
    assert td is None


def test_normalize_within_5min_future_allowed() -> None:
    """Bar ≤ reference + 5 min: allowed unchanged."""
    ref = _to_china_time(datetime(2026, 7, 10, 14, 30, 0))
    bar, td = _normalize_sina_bar_time("2026-07-10 14:35:00", ref)
    assert bar == "2026-07-10 14:35:00"
    assert td is None


def test_normalize_ordinary_future_rejected() -> None:
    """Ordinary bar > 5 min ahead (not night-early): invalid."""
    ref = _to_china_time(datetime(2026, 7, 10, 14, 30, 0))
    bar, td = _normalize_sina_bar_time("2026-07-10 14:37:00", ref)
    assert bar is None
    assert td is None


def test_normalize_friday_midnight_monday_label_corrected() -> None:
    """Friday night 00:00 labelled Monday → corrected to Saturday, trade_date preserved."""
    # Collection at Saturday 2026-07-11 00:05 Asia/Shanghai.
    ref = _to_china_time(datetime(2026, 7, 11, 0, 5, 0))
    bar, td = _normalize_sina_bar_time("2026-07-13 00:00:00", ref)
    assert bar == "2026-07-11 00:00:00"
    assert td == "20260713"


def test_normalize_friday_0130_rollover_corrected() -> None:
    """Friday night 01:30 rollover bar corrected."""
    ref = _to_china_time(datetime(2026, 7, 11, 1, 35, 0))
    bar, td = _normalize_sina_bar_time("2026-07-13 01:30:00", ref)
    assert bar == "2026-07-11 01:30:00"
    assert td == "20260713"


def test_normalize_monday_2355_rejected() -> None:
    """Monday 23:55 label with night-early ref: bar outside 00:00-02:30 → invalid."""
    ref = _to_china_time(datetime(2026, 7, 11, 0, 5, 0))
    bar, td = _normalize_sina_bar_time("2026-07-13 23:55:00", ref)
    assert bar is None
    assert td is None


def test_normalize_aware_utc_reference_to_china_local() -> None:
    """Aware UTC reference 2026-07-10T16:05Z (China 2026-07-11 00:05)
    with provider 2026-07-13 00:00:00 normalizes to 2026-07-11 00:00:00."""
    ref = _to_china_time(datetime(2026, 7, 10, 16, 5, 0, tzinfo=timezone.utc))
    bar, td = _normalize_sina_bar_time("2026-07-13 00:00:00", ref)
    assert bar == "2026-07-11 00:00:00"
    assert td == "20260713"


# ---------------------------------------------------------------------------
# Integration: collector skips invalid rows; corrected rows reach SQLite
# ---------------------------------------------------------------------------


def _install_minimal_fake_akshare(monkeypatch, records):
    """Install a fake akshare module returning *records* without pandas."""
    import sys
    import types

    class _FakeFrame:
        def __init__(self, recs):
            self._recs = recs
            self.empty = len(recs) == 0

        def tail(self, _n):
            return _FakeFrame(self._recs[-_n:])

        def to_dict(self, _orient):
            return list(self._recs)

    mod = types.ModuleType("akshare")
    mod.futures_zh_minute_sina = lambda symbol, period: _FakeFrame(records)
    monkeypatch.setitem(sys.modules, "akshare", mod)


def test_collector_skips_invalid_ingests_corrected(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Friday night collection: invalid bars skipped, corrected bars stored
    with natural bar_time + exchange trade_date."""
    from storage.read_model_store import ingest_rows_to_sqlite
    from storage.schema import SCHEMA_SQL

    _install_minimal_fake_akshare(
        monkeypatch,
        [
            {"datetime": "2026-07-13 00:00:00", "open": 72000, "high": 72100,
             "low": 71950, "close": 72050, "volume": 120, "hold": 5000},
            {"datetime": "2026-07-13 23:55:00", "open": 71900, "high": 72000,
             "low": 71850, "close": 71980, "volume": 200, "hold": 5000},
            {"datetime": "2026-07-10 23:55:00", "open": 71800, "high": 71900,
             "low": 71750, "close": 71850, "volume": 150, "hold": 5000},
        ],
    )

    # Collection at Saturday 2026-07-11 00:05 Asia/Shanghai
    ref = datetime(2026, 7, 11, 0, 5, 0)
    rows = collect_sina_futures_minute_rows(
        ["CU2608.SHF"], period="5", reference_time=ref
    )

    # Bar 1: Monday 00:00 → corrected (night-early rollover)
    # Bar 2: Monday 23:55 → rejected (outside 00:00-02:30)
    # Bar 3: Friday 23:55 → unchanged (past bar)
    assert len(rows) == 2

    assert rows[0]["time"] == "2026-07-11 00:00:00"
    assert rows[0]["trade_date"] == "20260713"
    assert rows[1]["time"] == "2026-07-10 23:55:00"
    assert "trade_date" not in rows[1]

    # Ingest into SQLite and verify stored values
    db_path = tmp_path / "marketdata.sqlite"
    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript(SCHEMA_SQL)
        conn.commit()
    finally:
        conn.close()

    written = ingest_rows_to_sqlite(
        db_path, "market_bars_intraday", "rt_fut_min", rows,
        source_name="rt_fut_min_normalization_test",
        provider_discriminator=SINA_PROVIDER,
    )
    assert written == 2

    conn = sqlite3.connect(str(db_path))
    try:
        corrected = conn.execute(
            "SELECT bar_time, trade_date, provider FROM market_bars_intraday"
            " WHERE bar_time = '2026-07-11 00:00:00'"
        ).fetchone()
        unchanged = conn.execute(
            "SELECT bar_time, trade_date FROM market_bars_intraday"
            " WHERE bar_time = '2026-07-10 23:55:00'"
        ).fetchone()
    finally:
        conn.close()

    assert corrected is not None
    assert corrected[0] == "2026-07-11 00:00:00"  # natural bar_time
    assert corrected[1] == "20260713"               # exchange trade_date
    assert corrected[2] == "sina_futures_minute"

    assert unchanged is not None
    assert unchanged[0] == "2026-07-10 23:55:00"
    assert unchanged[1] == "20260710"  # derived from bar_time


def test_run_collection_passes_reference_time_to_sina(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Prove run_collection injects reference_time into Sina collector."""
    captured_ref: list[datetime | None] = []

    def fake_collect(symbols, *, period, max_rows_per_symbol, reference_time=None):
        captured_ref.append(reference_time)
        return [
            {
                "ts_code": symbols[0],
                "code": symbols[0],
                "time": "2026-07-10 14:55:00",
                "open": 3500,
                "high": 3520,
                "low": 3490,
                "close": 3510,
                "vol": 100,
                "hold": 5000,
                "provider": "sina_futures_minute",
            }
        ]

    monkeypatch.setattr(
        "tools.collect_cn_futures_5min.collect_sina_futures_minute_rows",
        fake_collect,
    )
    monkeypatch.setattr(
        "tools.collect_cn_futures_5min.ingest_rows_to_sqlite",
        lambda *_args, **_kwargs: 1,
    )

    summary = run_collection(
        trade_date="20260710",
        symbols=["CU2608.SHF"],
        freq="5MIN",
        provider="sina_futures_minute",
        dry_run=False,
        sqlite_db_path=tmp_path / "marketdata.sqlite",
    )

    assert summary["state"] == "ok"
    assert len(captured_ref) == 1
    assert captured_ref[0] is not None
    assert isinstance(captured_ref[0], datetime)

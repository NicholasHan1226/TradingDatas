from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from tools.collect_cn_futures_5min import (
    DEFAULT_PRODUCTS,
    build_params,
    load_recent_futures_symbols,
    main,
    normalize_product,
    run_collection,
)


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

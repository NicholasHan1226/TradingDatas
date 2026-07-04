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


def test_build_params_uses_comma_separated_symbols() -> None:
    assert build_params(["CU2609.SHF", "RB2609.SHF"], freq="5MIN") == {
        "ts_code": "CU2609.SHF,RB2609.SHF",
        "freq": "5MIN",
    }


def test_run_collection_dry_run_does_not_call_tushare(tmp_path: Path) -> None:
    summary = run_collection(
        trade_date="20260703",
        symbols=["RB2609.SHF"],
        freq="5MIN",
        dry_run=True,
        sqlite_bridge_enabled=True,
        sqlite_db_path=tmp_path / "marketdata.sqlite",
    )

    assert summary["state"] == "dry_run"
    assert summary["params"] == {"ts_code": "RB2609.SHF", "freq": "5MIN"}


def test_main_rejects_empty_symbol_selection(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["--trade-date", "20260703", "--sqlite-db", str(tmp_path / "missing.sqlite"), "--dry-run"])

    assert code == 2
    assert "no futures symbols selected" in capsys.readouterr().out

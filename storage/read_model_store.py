"""SQLite read-model writer and historical CSV migration helper.

现役采集使用 `ingest_rows_to_sqlite()` 直接写入 read model。`ingest_csv_to_sqlite()`
及 CSV 相关 helper 仅保留为历史迁移/审计工具，不得作为生产采集成功路径。
"""

from __future__ import annotations

import csv
import fcntl
import hashlib
import json
import logging
import os
import time
from contextlib import contextmanager
from datetime import datetime, timezone
import sqlite3
from pathlib import Path
from typing import Any

from storage.schema_contract import get_table, table_primary_keys
from env_bootstrap import env_int
from runtime_paths import marketdata_sqlite_path

logger = logging.getLogger(__name__)
CHUNK_SIZE = 1000
MAX_TRANSACTION_ROWS = env_int("SHAREDSIGNALS_CSV_BRIDGE_MAX_TRANSACTION_ROWS", 0, min_value=0)
DB_BUSY_RETRIES = env_int("SHAREDSIGNALS_CSV_BRIDGE_DB_RETRIES", 3, min_value=1)

DEFAULT_SQLITE_PATH = marketdata_sqlite_path()


def _bridge_lock_path(db_path: Path) -> Path:
    return db_path.parent / f".{db_path.name}.read_model_store.lock"


@contextmanager
def _sqlite_bridge_lock(db_path: Path):
    timeout = env_int("SHAREDSIGNALS_CSV_BRIDGE_LOCK_TIMEOUT", 180, min_value=0)
    lock_path = _bridge_lock_path(db_path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + timeout
    with lock_path.open("a+") as handle:
        while True:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError as exc:
                if timeout <= 0 or time.monotonic() >= deadline:
                    raise TimeoutError(f"timed out waiting for read model store lock: {lock_path}") from exc
                time.sleep(min(1.0, max(0.05, deadline - time.monotonic())))
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


API_TO_TABLE_MAP = {
    "adj_factor": "market_bars_daily",
    "anns_d": "market_events",
    "balancesheet": "market_factors",
    "block_trade": "market_events",
    "broker_recommend": "market_events",
    "cashflow": "market_factors",
    "cb_basic": "market_assets",
    "cb_daily": "market_bars_daily",
    "cb_issue": "market_events",
    "cctv_news": "market_events",
    "cn_cpi": "market_factors",
    "cn_m": "market_factors",
    "cn_pmi": "market_factors",
    "cn_ppi": "market_factors",
    "libor": "market_factors",
    "hibor": "market_factors",
    "us_tltr": "market_factors",
    "us_tbr": "market_factors",
    "us_tycr": "market_factors",
    "sf_month": "market_factors",
    "cn_gdp": "market_factors",
    "daily": "market_bars_daily",
    "daily_basic": "market_factors",
    "dividend": "market_factors",
    "express": "market_factors",
    "fina_indicator": "market_factors",
    "forecast": "market_factors",
    "etf_basic": "market_assets",
    "fund_basic": "market_assets",
    "fund_daily": "market_bars_daily",
    "fund_div": "market_factors",
    "fund_nav": "market_assets",
    "fund_share": "market_factors",
    "fut_basic": "market_assets",
    "fut_daily": "market_bars_daily",
    "fx_daily": "market_bars_daily",
    "hk_balancesheet": "market_factors",
    "hk_basic": "market_assets",
    "hk_cashflow": "market_factors",
    "hk_daily": "market_bars_daily",
    "hk_income": "market_factors",
    "income": "market_factors",
    "index_basic": "market_bars_daily",
    "index_daily": "market_bars_daily",
    "index_dailybasic": "market_bars_daily",
    "index_classify": "market_assets",
    "index_global": "market_bars_daily",
    "index_monthly": "market_bars_intraday",
    "index_weekly": "market_bars_intraday",
    "index_weight": "market_bars_daily",
    "limit_list": "market_events",
    "limit_list_d": "market_events",
    "major_news": "market_events",
    "margin": "market_factors",
    "margin_detail": "market_factors",
    "margin_secs": "market_factors",
    "moneyflow": "market_factors",
    "moneyflow_hsgt": "market_factors",
    "monthly": "market_bars_intraday",
    "namechange": "market_events",
    "news": "market_events",
    "opt_basic": "market_assets",
    "pledge_detail": "market_factors",
    "pledge_stat": "market_factors",
    "repo_daily": "market_factors",
    "report_rc": "market_events",
    "repurchase": "market_factors",
    "concept": "market_assets",
    "concept_detail": "market_assets",
    "dc_index": "market_assets",
    "ft_limit": "market_factors",
    "hs_const": "market_assets",
    "share_float": "market_assets",
    "shibor": "market_factors",
    "shibor_lpr": "market_factors",
    "limit_step": "market_factors",
    "stk_auction": "market_factors",
    "stk_factor": "market_bars_daily",
    "stk_factor_pro": "market_factors",
    "stk_limit": "market_factors",
    "stk_mins": "market_bars_intraday",
    "rt_min": "market_bars_intraday",
    "rt_fut_min": "market_bars_intraday",
    "stk_holdernumber": "market_assets",
    "stk_holdertrade": "market_assets",
    "stk_managers": "market_assets",
    "stk_surv": "market_factors",
    "stock_basic": "market_assets",
    "stock_company": "market_assets",
    "suspend_d": "market_events",
    "ths_index": "market_assets",
    "top_list": "market_factors",
    "top10_floatholders": "market_assets",
    "top10_holders": "market_assets",
    "top_inst": "market_assets",
    "trade_cal": "market_assets",
    "us_basic": "market_assets",
    "us_daily": "market_bars_daily",
    "weekly": "market_bars_intraday",
}

CSV_ADDITIONAL_TABLES = {
    "repo_daily": ("market_bars_daily",),
    "stk_factor": ("market_factors",),
}


def _quote_identifier(identifier):
    return '"' + str(identifier).replace('"', '""') + '"'


def _table_columns(conn, table):
    rows = conn.execute(f"PRAGMA table_info({_quote_identifier(table)})").fetchall()
    return [row[1] for row in rows]


def _api_name_from_path(csv_path):
    parent = csv_path.parent.parent.name
    return parent if parent in API_TO_TABLE_MAP else ""


def _market_for(api_name, symbol):
    if api_name in (
        "daily",
        "stock_basic",
        "weekly",
        "monthly",
        "index_classify",
        "index_weekly",
        "index_monthly",
        "stk_mins",
        "rt_min",
        "repo_daily",
        "concept",
        "concept_detail",
        "hs_const",
        "ths_index",
        "dc_index",
    ):
        return "Ashare"
    if api_name in ("hk_daily", "hk_basic"):
        return "HK"
    if api_name in ("us_daily", "us_basic"):
        return "US"
    if api_name == "index_global":
        return "Global"
    if api_name in ("fut_basic", "fut_daily", "rt_fut_min"):
        return "Futures"
    if api_name in ("ft_limit",):
        return "Futures"
    if api_name in ("fund_share", "fund_div"):
        return "Fund"
    if api_name in ("opt_basic",):
        return "Options"
    if api_name == "etf_basic":
        return "ETF"

    symbol = str(symbol or "")
    if symbol.endswith((".SZ", ".SH", ".BJ")):
        return "Ashare"
    if symbol.endswith(".HK"):
        return "HK"
    return ""



_FACTOR_BASE_COLUMNS = {
    "ts_code",
    "symbol",
    "market",
    "trade_date",
    "ann_date",
    "end_date",
    "report_date",
    "date",
    "period",
    "month",
    "quarter",
    "year",
    "update_flag",
    "provider",
    "source_file",
    "collected_at",
    "raw_json",
}
_FACTOR_PRICE_COLUMNS = {"open", "high", "low", "close", "pre_close", "change", "pct_chg", "vol", "volume", "amount"}
_FACTOR_DATE_COLUMNS = ("trade_date", "ann_date", "end_date", "report_date", "date", "period", "month", "quarter", "year")
_FACTOR_INSERT_COLUMNS = (
    "factor_hash",
    "market",
    "symbol",
    "factor_name",
    "event_time",
    "value",
    "provider",
    "source_file",
    "collected_at",
    "raw_json",
)

_INTRADAY_ALIAS_COLUMNS = {
    "bid_price": ("bid_price", "bid1", "best_bid"),
    "ask_price": ("ask_price", "ask1", "best_ask"),
    "bid_size": ("bid_size", "bid_volume", "bid1_volume"),
    "ask_size": ("ask_size", "ask_volume", "ask1_volume"),
    "last_trade_date": ("last_trade_date",),
    "expiry_date": ("expiry_date", "expiration_date", "delist_date", "delivery_date"),
}


def _first_present(row, *keys):
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return value
    return None


def _coerce_float(value):
    if value in (None, ""):
        return None
    text = str(value).strip().replace(",", "")
    if not text or text in {"--", "None", "nan", "NaN", "null"}:
        return None
    if text.endswith("%"):
        text = text[:-1]
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def _factor_event_time(row):
    for col in _FACTOR_DATE_COLUMNS:
        value = str(row.get(col) or "").strip()
        if value:
            return value
    return str(row.get("collected_at") or "").strip()


def _factor_hash(api_name, symbol, event_time, factor_name, raw_json):
    payload = "|".join(str(part or "") for part in (api_name, symbol, event_time, factor_name, raw_json))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _factor_rows(row, api_name, csv_path):
    row = _canonical_row("market_factors", dict(row), api_name, csv_path)
    raw_json = json.dumps(row, ensure_ascii=False, sort_keys=True)
    symbol = row.get("symbol") or row.get("ts_code") or ""
    event_time = _factor_event_time(row) or _csv_collected_at(csv_path)
    collected_at = row.get("collected_at") or _csv_collected_at(csv_path)
    provider = row.get("provider") or (f"tushare_{api_name}" if api_name else "")
    source_file = row.get("source_file") or Path(csv_path).name
    market = row.get("market") or _market_for(api_name, symbol)

    metrics = []
    for key, value in row.items():
        if key in _FACTOR_BASE_COLUMNS or key.startswith("_"):
            continue
        if api_name == "stk_factor" and key in _FACTOR_PRICE_COLUMNS:
            continue
        numeric = _coerce_float(value)
        if numeric is not None:
            metrics.append((key, numeric))

    if not metrics:
        metrics = [(api_name or "row", None)]

    expanded = []
    for metric, numeric in metrics:
        factor_name = f"{api_name}:{metric}" if api_name else str(metric)
        expanded.append(
            {
                "factor_hash": _factor_hash(api_name, symbol, event_time, factor_name, raw_json),
                "market": market,
                "symbol": symbol,
                "factor_name": factor_name,
                "event_time": event_time,
                "value": numeric,
                "provider": provider,
                "source_file": source_file,
                "collected_at": collected_at,
                "raw_json": raw_json,
            }
        )
    return expanded


def _columns_for_insert(table, csv_columns, target_columns, api_name):
    columns = [col for col in csv_columns if col in target_columns]
    csv_column_set = set(csv_columns)

    derived_columns = []
    if {"ts_code", "symbol", "code"} & csv_column_set and "symbol" in target_columns:
        derived_columns.append("symbol")
    if "vol" in csv_column_set and "volume" in target_columns:
        derived_columns.append("volume")
    if "market" in target_columns and (
        api_name or "ts_code" in csv_column_set or "symbol" in csv_column_set
    ):
        derived_columns.append("market")
    if table == "market_bars_intraday":
        if "trade_date" in csv_column_set and "bar_time" in target_columns:
            derived_columns.append("bar_time")
        if "trade_time" in csv_column_set:
            if "bar_time" in target_columns:
                derived_columns.append("bar_time")
            if "trade_date" in target_columns:
                derived_columns.append("trade_date")
        if "time" in csv_column_set:
            if "bar_time" in target_columns:
                derived_columns.append("bar_time")
            if "trade_date" in target_columns:
                derived_columns.append("trade_date")
        if api_name in ("weekly", "monthly", "stk_mins", "rt_min", "rt_fut_min") and "interval" in target_columns:
            derived_columns.append("interval")
        if api_name == "rt_fut_min":
            for canonical, aliases in _INTRADAY_ALIAS_COLUMNS.items():
                if canonical in target_columns and (set(aliases) & csv_column_set or canonical in {"last_trade_date", "expiry_date"}):
                    derived_columns.append(canonical)
    if table == "market_assets":
        for col in ("name", "asset_type", "sector", "status", "updated_at", "raw_json", "last_trade_date", "expiry_date"):
            if col in target_columns:
                derived_columns.append(col)
    if table == "market_events":
        for col in ("event_hash", "event_type", "event_time", "trade_date", "source", "raw_json"):
            if col in target_columns:
                derived_columns.append(col)
    if api_name and "provider" in target_columns:
        derived_columns.append("provider")
    if "collected_at" in target_columns:
        derived_columns.append("collected_at")
    if "source_file" in target_columns:
        derived_columns.append("source_file")

    for col in derived_columns:
        if col not in columns:
            columns.append(col)
    return columns


def _csv_collected_at(csv_path):
    try:
        return datetime.fromtimestamp(Path(csv_path).stat().st_mtime, tz=timezone.utc).replace(microsecond=0).isoformat()
    except OSError:
        return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _trade_date_from_trade_time(trade_time):
    value = str(trade_time or "").strip()
    if len(value) >= 10:
        return value[:10].replace("-", "")
    return ""


_EVENT_TIME_COLUMNS = ("event_time", "datetime", "pub_time", "date", "trade_date", "ann_date")


def _event_time_from_row(row):
    for col in _EVENT_TIME_COLUMNS:
        value = str(row.get(col) or "").strip()
        if value:
            return value
    return ""


def _trade_date_from_event_time(event_time):
    value = str(event_time or "").strip()
    if not value:
        return ""
    first_part = value[:10]
    digits = "".join(ch for ch in first_part if ch.isdigit())
    if len(digits) >= 8:
        return digits[:8]
    digits = "".join(ch for ch in value if ch.isdigit())
    return digits[:8] if len(digits) >= 8 else ""


def _event_hash(provider, event_type, event_time, row):
    payload = "|".join(
        str(part or "")
        for part in (
            provider,
            event_type,
            event_time,
            row.get("title"),
            row.get("content"),
            row.get("url"),
            row.get("source") or row.get("src"),
        )
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _canonical_row(table, row, api_name, csv_path):
    symbol = row.get("ts_code") or row.get("symbol") or row.get("code") or row.get("index_code")
    if symbol:
        row["symbol"] = symbol
        if not row.get("ts_code") and api_name == "rt_fut_min":
            row["ts_code"] = symbol

    if "vol" in row and "volume" not in row:
        row["volume"] = row.get("vol")

    market = _market_for(api_name, symbol)
    if market:
        row["market"] = market

    if table == "market_bars_intraday":
        if row.get("trade_date") and not row.get("bar_time"):
            row["bar_time"] = row.get("trade_date")
        if row.get("trade_time"):
            row["bar_time"] = row.get("trade_time")
            if not row.get("trade_date"):
                row["trade_date"] = _trade_date_from_trade_time(row.get("trade_time"))
        if row.get("time"):
            row["bar_time"] = row.get("time")
            if not row.get("trade_date"):
                row["trade_date"] = _trade_date_from_trade_time(row.get("time"))
        if api_name in ("weekly", "monthly", "index_weekly", "index_monthly"):
            row["interval"] = api_name
        elif api_name in ("stk_mins", "rt_min", "rt_fut_min"):
            row["interval"] = "5min"
        if api_name == "rt_fut_min":
            for canonical, aliases in _INTRADAY_ALIAS_COLUMNS.items():
                value = _first_present(row, *aliases)
                if value not in (None, ""):
                    row[canonical] = value

    if table == "market_assets":
        if not row.get("name"):
            for name_col in ("name", "csname", "cname", "extname", "index_name", "industry_name", "bond_short_name"):
                if row.get(name_col):
                    row["name"] = row.get(name_col)
                    break
        if not row.get("sector") and row.get("industry"):
            row["sector"] = row.get("industry")
        if not row.get("asset_type"):
            asset_type_map = {
                "concept": "concept",
                "concept_detail": "concept_member",
                "cb_basic": "convertible_bond",
                "dc_index": "thematic_index",
                "etf_basic": "etf",
                "fut_basic": "future",
                "fund_basic": "fund",
                "hs_const": "index_constituent",
                "hk_basic": "stock",
                "index_classify": "index_classification",
                "opt_basic": "option",
                "stock_basic": "stock",
                "ths_index": "thematic_index",
                "us_basic": "stock",
            }
            if api_name in asset_type_map:
                row["asset_type"] = asset_type_map[api_name]
        if not row.get("status") and row.get("list_status"):
            row["status"] = row.get("list_status")
        if not row.get("last_trade_date"):
            row["last_trade_date"] = _first_present(row, "last_trade_date", "last_ddate")
        if not row.get("expiry_date"):
            row["expiry_date"] = _first_present(row, "expiry_date", "delist_date", "delivery_date", "end_date")
        if not row.get("updated_at"):
            row["updated_at"] = _csv_collected_at(csv_path)
        if not row.get("raw_json"):
            row["raw_json"] = json.dumps(row, ensure_ascii=False, sort_keys=True)

    if table == "market_events":
        provider = row.get("provider") or (f"tushare_{api_name}" if api_name else "")
        event_type = row.get("event_type") or api_name or "event"
        event_time = row.get("event_time") or _event_time_from_row(row)
        trade_date = row.get("trade_date") or _trade_date_from_event_time(event_time)
        if provider and not row.get("provider"):
            row["provider"] = provider
        if event_type and not row.get("event_type"):
            row["event_type"] = event_type
        if event_time and not row.get("event_time"):
            row["event_time"] = event_time
        if trade_date and not row.get("trade_date"):
            row["trade_date"] = trade_date
        if row.get("src") and not row.get("source"):
            row["source"] = row.get("src")
        if not row.get("source") and provider:
            row["source"] = provider
        if not row.get("raw_json"):
            row["raw_json"] = json.dumps(row, ensure_ascii=False, sort_keys=True)
        if not row.get("event_hash"):
            row["event_hash"] = _event_hash(provider, event_type, event_time, row)

    if api_name and not row.get("provider"):
        row["provider"] = f"tushare_{api_name}"
    if not row.get("collected_at"):
        row["collected_at"] = _csv_collected_at(csv_path)
    if not row.get("source_file"):
        row["source_file"] = csv_path.name

    return _normalize_numeric_values(table, row)


def _normalize_numeric_values(table, row):
    column_types = {col.name: col.logical_type for col in get_table(table).columns}
    normalized = dict(row)
    for col, logical_type in column_types.items():
        if logical_type not in {"float", "integer"}:
            continue
        value = normalized.get(col)
        if value is None:
            continue
        text = str(value).strip()
        if text == "":
            normalized[col] = None
        elif logical_type == "float":
            coerced = _coerce_float(text)
            if coerced is not None:
                normalized[col] = coerced
        elif logical_type == "integer":
            coerced = _coerce_float(text)
            if coerced is not None:
                normalized[col] = int(coerced)
    return normalized


def _insert_sql(table, columns, pk_columns):
    quoted_table = _quote_identifier(table)
    col_sql = ", ".join(_quote_identifier(col) for col in columns)
    placeholders = ", ".join("?" for _ in columns)

    if pk_columns:
        conflict_sql = ", ".join(_quote_identifier(col) for col in pk_columns)
        update_columns = [col for col in columns if col not in pk_columns]
        if update_columns:
            if table == "market_assets":
                preserve_existing_when_empty = {
                    "name",
                    "asset_type",
                    "exchange",
                    "sector",
                    "list_date",
                    "last_trade_date",
                    "expiry_date",
                    "status",
                }
                assignments = []
                for col in update_columns:
                    quoted_col = _quote_identifier(col)
                    if col in preserve_existing_when_empty:
                        assignments.append(
                            f"{quoted_col} = COALESCE(NULLIF(excluded.{quoted_col}, ''), {quoted_table}.{quoted_col})"
                        )
                    else:
                        assignments.append(f"{quoted_col} = excluded.{quoted_col}")
                update_sql = ", ".join(assignments)
                return (
                    f"INSERT INTO {quoted_table} ({col_sql}) VALUES ({placeholders}) "
                    f"ON CONFLICT ({conflict_sql}) DO UPDATE SET {update_sql}"
                )
            update_sql = ", ".join(
                f"{_quote_identifier(col)} = excluded.{_quote_identifier(col)}"
                for col in update_columns
            )
            return (
                f"INSERT INTO {quoted_table} ({col_sql}) VALUES ({placeholders}) "
                f"ON CONFLICT ({conflict_sql}) DO UPDATE SET {update_sql}"
            )
        return (
            f"INSERT INTO {quoted_table} ({col_sql}) VALUES ({placeholders}) "
            f"ON CONFLICT ({conflict_sql}) DO NOTHING"
        )

    return f"INSERT OR IGNORE INTO {quoted_table} ({col_sql}) VALUES ({placeholders})"


def _required_columns(table, target_columns):
    return [
        col
        for col in table_primary_keys().get(table, [])
        if col in target_columns
    ]


def _row_values(row, columns, required_columns, csv_path, row_number):
    missing = [col for col in required_columns if row.get(col) in (None, "")]
    if missing:
        logger.warning(
            "read model store skipped bad row: file=%s row=%s missing required columns=%s",
            csv_path,
            row_number,
            ",".join(missing),
        )
        return None
    return [row.get(col) for col in columns]


def _asset_expiry_metadata(conn, symbol):
    if not symbol:
        return {}
    try:
        rows = conn.execute(
            "SELECT last_trade_date, expiry_date FROM market_assets WHERE market=? AND symbol=?",
            ("Futures", str(symbol)),
        ).fetchone()
    except sqlite3.OperationalError:
        return {}
    if not rows:
        return {}
    return {
        "last_trade_date": rows[0],
        "expiry_date": rows[1],
    }


def _enrich_futures_intraday_from_assets(conn, row):
    if row.get("last_trade_date") and row.get("expiry_date"):
        return row
    metadata = _asset_expiry_metadata(conn, row.get("symbol"))
    if not row.get("last_trade_date") and metadata.get("last_trade_date"):
        row["last_trade_date"] = metadata["last_trade_date"]
    if not row.get("expiry_date") and metadata.get("expiry_date"):
        row["expiry_date"] = metadata["expiry_date"]
    return row


def _flush_chunk(conn, sql, chunk):
    if not chunk:
        return 0
    before = conn.total_changes
    conn.executemany(sql, chunk)
    return conn.total_changes - before


def _sqlite_lock_error(exc: Exception) -> bool:
    return isinstance(exc, sqlite3.OperationalError) and any(
        marker in str(exc).lower() for marker in ("locked", "busy")
    )


def _prepare_sqlite_connection(conn: sqlite3.Connection) -> None:
    conn.execute("PRAGMA busy_timeout=30000")
    try:
        mode = conn.execute("PRAGMA journal_mode").fetchone()
        if mode and str(mode[0]).lower() != "wal":
            conn.execute("PRAGMA journal_mode=WAL")
    except sqlite3.OperationalError as exc:
        if not _sqlite_lock_error(exc):
            raise
    conn.execute("PRAGMA synchronous=NORMAL")


def _ingest_csv_to_sqlite_once(db_path, table, csv_path, encoding="utf-8-sig", max_transaction_rows: int | None = None):
    """Ingest one CSV file into an existing SQLite table (migration-only).

    The helper is defensive: it never creates target tables. If the database or
    table is missing, it logs and returns 0. CSV ingestion is retained only for
    historical migration/audit; production collectors must use
    `ingest_rows_to_sqlite()`.
    """
    db_path = Path(db_path)
    csv_path = Path(csv_path)

    if not csv_path.exists():
        raise FileNotFoundError(str(csv_path))

    if not db_path.exists():
        logger.warning("read model store skipped: database does not exist: %s", db_path)
        return 0

    rows_written = 0
    transaction_open = False
    transaction_rows = 0
    max_rows_per_transaction = MAX_TRANSACTION_ROWS if max_transaction_rows is None else int(max_transaction_rows)
    conn = sqlite3.connect(str(db_path), timeout=30)
    try:
        _prepare_sqlite_connection(conn)

        target_columns = _table_columns(conn, table)
        if not target_columns:
            logger.warning("read model store skipped: table does not exist: %s", table)
            return 0

        with csv_path.open("r", encoding=encoding, newline="") as fh:
            reader = csv.DictReader(line.replace("\0", "") for line in fh)
            csv_columns = reader.fieldnames or []
            api_name = _api_name_from_path(csv_path)
            if table == "market_factors":
                columns = [col for col in _FACTOR_INSERT_COLUMNS if col in target_columns]
                skipped = [col for col in csv_columns if col in _FACTOR_BASE_COLUMNS]
            else:
                columns = _columns_for_insert(table, csv_columns, target_columns, api_name)
                skipped = [col for col in csv_columns if col not in target_columns]
            if skipped:
                logger.debug(
                    "read model store skipped unknown columns for %s: %s",
                    table,
                    ", ".join(skipped),
                )
            if not columns:
                logger.warning("read model store skipped: no matching columns for %s in %s", table, csv_path)
                return 0

            pk_columns = [
                col
                for col in table_primary_keys().get(table, [])
                if col in target_columns
            ]
            for pk_col in pk_columns:
                if pk_col not in columns:
                    columns.append(pk_col)
            required_columns = _required_columns(table, target_columns)
            sql = _insert_sql(table, columns, pk_columns)
            chunk: list[list[Any]] = []
            conn.execute("BEGIN IMMEDIATE")
            transaction_open = True

            for row_number, row in enumerate(reader, start=2):
                canonical_rows = _factor_rows(row, api_name, csv_path) if table == "market_factors" else [_canonical_row(table, row, api_name, csv_path)]
                for canonical_row in canonical_rows:
                    if table == "market_bars_intraday" and api_name == "rt_fut_min":
                        canonical_row = _enrich_futures_intraday_from_assets(conn, canonical_row)
                    values = _row_values(canonical_row, columns, required_columns, csv_path, row_number)
                    if values is None:
                        continue
                    chunk.append(values)
                    if len(chunk) >= CHUNK_SIZE:
                        chunk_written = _flush_chunk(conn, sql, chunk)
                        rows_written += chunk_written
                        transaction_rows += len(chunk)
                        chunk.clear()
                        if max_rows_per_transaction > 0 and transaction_rows >= max_rows_per_transaction:
                            conn.commit()
                            transaction_open = False
                            conn.execute("BEGIN IMMEDIATE")
                            transaction_open = True
                            transaction_rows = 0

            if chunk:
                chunk_written = _flush_chunk(conn, sql, chunk)
                rows_written += chunk_written
                transaction_rows += len(chunk)
            conn.commit()
            transaction_open = False
    except Exception:
        if transaction_open:
            conn.rollback()
        raise
    finally:
        conn.close()

    return rows_written


def _ingest_rows_to_sqlite_once(
    db_path,
    table,
    api_name,
    rows,
    *,
    source_name: str,
    max_transaction_rows: int | None = None,
):
    """Ingest provider rows directly into an existing SQLite read-model table."""

    db_path = Path(db_path)
    if not db_path.exists():
        raise FileNotFoundError(f"sqlite db not found: {db_path}")

    clean_rows = [dict(row) for row in (rows or []) if isinstance(row, dict)]
    if not clean_rows:
        return 0

    source_path = Path(str(source_name or f"{api_name}_direct"))
    rows_written = 0
    transaction_open = False
    transaction_rows = 0
    max_rows_per_transaction = MAX_TRANSACTION_ROWS if max_transaction_rows is None else int(max_transaction_rows)
    conn = sqlite3.connect(str(db_path), timeout=30)
    try:
        _prepare_sqlite_connection(conn)

        target_columns = _table_columns(conn, table)
        if not target_columns:
            raise RuntimeError(f"sqlite table does not exist: {table}")

        row_columns: list[str] = []
        seen_columns: set[str] = set()
        for row in clean_rows:
            for col in row.keys():
                if col not in seen_columns:
                    row_columns.append(str(col))
                    seen_columns.add(str(col))
        if table == "market_factors":
            columns = [col for col in _FACTOR_INSERT_COLUMNS if col in target_columns]
        else:
            columns = _columns_for_insert(table, row_columns, target_columns, str(api_name))
        if not columns:
            raise RuntimeError(f"no matching sqlite columns for table={table} api_name={api_name}")

        pk_columns = [
            col
            for col in table_primary_keys().get(table, [])
            if col in target_columns
        ]
        for pk_col in pk_columns:
            if pk_col not in columns:
                columns.append(pk_col)
        required_columns = _required_columns(table, target_columns)
        sql = _insert_sql(table, columns, pk_columns)
        chunk: list[list[Any]] = []
        conn.execute("BEGIN IMMEDIATE")
        transaction_open = True

        for row_number, row in enumerate(clean_rows, start=1):
            canonical_rows = (
                _factor_rows(row, str(api_name), source_path)
                if table == "market_factors"
                else [_canonical_row(table, row, str(api_name), source_path)]
            )
            for canonical_row in canonical_rows:
                if table == "market_bars_intraday" and api_name == "rt_fut_min":
                    canonical_row = _enrich_futures_intraday_from_assets(conn, canonical_row)
                values = _row_values(canonical_row, columns, required_columns, source_path, row_number)
                if values is None:
                    continue
                chunk.append(values)
                if len(chunk) >= CHUNK_SIZE:
                    chunk_written = _flush_chunk(conn, sql, chunk)
                    rows_written += chunk_written
                    transaction_rows += len(chunk)
                    chunk.clear()
                    if max_rows_per_transaction > 0 and transaction_rows >= max_rows_per_transaction:
                        conn.commit()
                        transaction_open = False
                        conn.execute("BEGIN IMMEDIATE")
                        transaction_open = True
                        transaction_rows = 0

        if chunk:
            chunk_written = _flush_chunk(conn, sql, chunk)
            rows_written += chunk_written
            transaction_rows += len(chunk)
        conn.commit()
        transaction_open = False
    except Exception:
        if transaction_open:
            conn.rollback()
        raise
    finally:
        conn.close()

    return rows_written


def _ingest_csv_to_sqlite_unlocked(db_path, table, csv_path, encoding="utf-8-sig", max_transaction_rows: int | None = None):
    last_error: Exception | None = None
    for attempt in range(1, DB_BUSY_RETRIES + 1):
        try:
            return _ingest_csv_to_sqlite_once(
                db_path,
                table,
                csv_path,
                encoding=encoding,
                max_transaction_rows=max_transaction_rows,
            )
        except sqlite3.OperationalError as exc:
            last_error = exc
            if attempt < DB_BUSY_RETRIES and _sqlite_lock_error(exc):
                time.sleep(min(2.0 * attempt, 5.0))
                continue
            raise
    raise RuntimeError(f"read model store sqlite write failed after {DB_BUSY_RETRIES} attempts: {last_error}") from last_error


def ingest_csv_to_sqlite(db_path, table, csv_path, encoding="utf-8-sig", max_transaction_rows: int | None = None):
    db_path_obj = Path(db_path)
    with _sqlite_bridge_lock(db_path_obj):
        rows_written = _ingest_csv_to_sqlite_unlocked(
            db_path_obj,
            table,
            csv_path,
            encoding=encoding,
            max_transaction_rows=max_transaction_rows,
        )
        api_name = _api_name_from_path(Path(csv_path))
        if API_TO_TABLE_MAP.get(api_name) == table:
            for additional_table in CSV_ADDITIONAL_TABLES.get(api_name, ()):
                rows_written += _ingest_csv_to_sqlite_unlocked(
                    db_path_obj,
                    additional_table,
                    csv_path,
                    encoding=encoding,
                    max_transaction_rows=max_transaction_rows,
                )
        return rows_written


def ingest_rows_to_sqlite(
    db_path,
    table,
    api_name,
    rows,
    *,
    source_name: str | None = None,
    max_transaction_rows: int | None = None,
):
    db_path_obj = Path(db_path)
    source = source_name or f"{api_name}_direct"
    with _sqlite_bridge_lock(db_path_obj):
        rows_written = _ingest_rows_to_sqlite_once(
            db_path_obj,
            table,
            api_name,
            rows,
            source_name=source,
            max_transaction_rows=max_transaction_rows,
        )
        if API_TO_TABLE_MAP.get(api_name) == table:
            for additional_table in CSV_ADDITIONAL_TABLES.get(api_name, ()):
                rows_written += _ingest_rows_to_sqlite_once(
                    db_path_obj,
                    additional_table,
                    api_name,
                    rows,
                    source_name=source,
                    max_transaction_rows=max_transaction_rows,
                )
        return rows_written


def ingest_date_partition(db_path, api_name, trade_date, data_dir):
    """Ingest CSV files for one Tushare API/date partition."""
    table = API_TO_TABLE_MAP.get(api_name)
    summary = {
        "api_name": api_name,
        "trade_date": trade_date,
        "files_processed": 0,
        "total_rows": 0,
    }
    if not table:
        logger.warning("read model store skipped: no table mapping for api_name=%s", api_name)
        return summary

    partition_dir = Path(data_dir) / "tushare" / api_name / str(trade_date)
    if not partition_dir.exists():
        logger.warning("read model store skipped: partition does not exist: %s", partition_dir)
        return summary

    for csv_file in sorted(partition_dir.glob("*.csv")):
        rows = ingest_csv_to_sqlite(db_path, table, csv_file)
        summary["files_processed"] += 1
        summary["total_rows"] += rows

    return summary

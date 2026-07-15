"""SQLite read-model writer.

Production collectors pass validated provider rows to `ingest_rows_to_sqlite()`.
CSV/NDJSON/parquet file bridges are retired and must not be restored here.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import logging
import re
import time
from collections.abc import Mapping, Sequence
from contextlib import contextmanager
from datetime import datetime, timezone
import sqlite3
from pathlib import Path
from typing import Any

from storage.event_identity import (
    event_content_fingerprint,
    source_family,
    stable_event_id,
)
from storage.ingest_receipts import (
    IngestContext,
    IngestCounts,
    IngestResult,
    _require_unchanged_sqlite_binding,
    _validated_existing_sqlite_binding,
    insert_ingest_receipt,
)
from storage.schema_contract import get_table, table_primary_keys
from env_bootstrap import env_int
from runtime_paths import marketdata_sqlite_path

logger = logging.getLogger(__name__)
CHUNK_SIZE = 1000
MAX_TRANSACTION_ROWS = env_int("SHAREDSIGNALS_READ_MODEL_MAX_TRANSACTION_ROWS", 0, min_value=0)
DB_BUSY_RETRIES = env_int("SHAREDSIGNALS_READ_MODEL_DB_RETRIES", 3, min_value=1)

DEFAULT_SQLITE_PATH = marketdata_sqlite_path()


def _read_model_lock_path(db_path: Path) -> Path:
    return db_path.parent / f".{db_path.name}.read_model_store.lock"


@contextmanager
def _read_model_lock(db_path: Path):
    timeout = env_int("SHAREDSIGNALS_READ_MODEL_LOCK_TIMEOUT", 180, min_value=0)
    lock_path = _read_model_lock_path(db_path)
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
    "bak_basic": "market_factors",
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
    "cyq_chips": "market_factors",
    "cyq_perf": "market_factors",
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
    "fina_audit": "market_factors",
    "fina_indicator": "market_factors",
    "fina_mainbz": "market_factors",
    "forecast": "market_factors",
    "etf_basic": "market_assets",
    "fund_adj": "market_factors",
    "fund_basic": "market_assets",
    "fund_daily": "market_bars_daily",
    "fund_div": "market_factors",
    "fund_nav": "market_factors",
    "fund_portfolio": "market_fund_portfolio",
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
    "index_basic": "market_assets",
    "index_daily": "market_bars_daily",
    "index_dailybasic": "market_factors",
    "index_classify": "market_assets",
    "index_global": "market_bars_daily",
    "index_member": "market_relationships",
    "index_member_all": "market_relationships",
    "index_monthly": "market_bars_intraday",
    "index_weekly": "market_bars_intraday",
    "index_weight": "market_relationships",
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
    "concept_detail": "market_relationships",
    "dc_index": "market_assets",
    "ft_limit": "market_factors",
    "hs_const": "market_relationships",
    "share_float": "market_factors",
    "shibor": "market_factors",
    "shibor_lpr": "market_factors",
    "limit_step": "market_factors",
    "stk_auction": "market_factors",
    "stk_factor": "market_bars_daily",
    "stk_factor_pro": "market_factors",
    "stk_limit": "market_factors",
    "rt_min": "market_bars_intraday",
    "rt_fut_min": "market_bars_intraday",
    "stk_holdernumber": "market_factors",
    "stk_holdertrade": "market_factors",
    "stk_managers": "market_factors",
    "stk_surv": "market_factors",
    "stock_basic": "market_assets",
    "stock_company": "market_factors",
    "suspend_d": "market_events",
    "ths_hot": "market_factors",
    "ths_index": "market_assets",
    "ths_member": "market_relationships",
    "dc_member": "market_relationships",
    "top_list": "market_factors",
    "top10_floatholders": "market_factors",
    "top10_holders": "market_factors",
    "top_inst": "market_factors",
    "trade_cal": "market_factors",
    "ths_daily": "market_bars_daily",
    "dc_daily": "market_bars_daily",
    "opt_daily": "market_bars_daily",
    "fut_holding": "market_factors",
    "us_basic": "market_assets",
    "us_daily": "market_bars_daily",
    "weekly": "market_bars_intraday",
}

ADDITIONAL_TABLES = {
    "repo_daily": ("market_bars_daily",),
    "stk_factor": ("market_factors",),
}


def _quote_identifier(identifier):
    return '"' + str(identifier).replace('"', '""') + '"'


def _table_columns(conn, table):
    rows = conn.execute(f"PRAGMA table_info({_quote_identifier(table)})").fetchall()
    return [row[1] for row in rows]


def _market_for(api_name, symbol):
    if api_name in (
        "daily",
        "stock_basic",
        "weekly",
        "monthly",
        "index_classify",
        "index_weekly",
        "index_monthly",
        "rt_min",
        "repo_daily",
        "concept",
        "concept_detail",
        "bak_basic",
        "cyq_chips",
        "cyq_perf",
        "fina_audit",
        "fina_mainbz",
        "hs_const",
        "ths_index",
        "dc_index",
        "ths_member",
        "ths_hot",
        "dc_member",
        "index_member",
        "index_member_all",
        "trade_cal",
        "ths_daily",
        "dc_daily",
    ):
        return "Ashare"
    if api_name in ("hk_daily", "hk_basic"):
        return "HK"
    if api_name in ("us_daily", "us_basic"):
        return "US"
    if api_name == "index_global":
        return "Global"
    if api_name in ("fut_basic", "fut_daily", "fut_holding", "rt_fut_min"):
        return "Futures"
    if api_name in ("ft_limit",):
        return "Futures"
    if api_name in ("fund_adj", "fund_nav", "fund_portfolio", "fund_share", "fund_div"):
        return "Fund"
    if api_name in ("opt_basic", "opt_daily"):
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
_REPORTING_PERIOD_APIS = {"fina_audit", "fina_mainbz"}
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

_RELATIONSHIP_APIS = {"ths_member", "dc_member", "index_member", "index_member_all"}


def _relationship_hash(api_name, parent_symbol, child_symbol, relationship_type, trade_date, raw_json):
    payload = "|".join(str(part or "") for part in (api_name, parent_symbol, child_symbol, relationship_type, trade_date, raw_json))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()

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


def _factor_event_time(row, api_name=""):
    date_columns = _FACTOR_DATE_COLUMNS
    if api_name in _REPORTING_PERIOD_APIS:
        date_columns = ("end_date", "period", "report_date", "ann_date", "trade_date", "date", "month", "quarter", "year")
    for col in date_columns:
        value = str(row.get(col) or "").strip()
        if value:
            return value
    return str(row.get("collected_at") or "").strip()


def _factor_hash(api_name, symbol, event_time, factor_name, raw_json):
    payload = "|".join(str(part or "") for part in (api_name, symbol, event_time, factor_name, raw_json))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _fund_portfolio_hash(api_name, symbol, holding_symbol, ann_date, end_date, raw_json):
    payload = "|".join(str(part or "") for part in (api_name, symbol, holding_symbol, ann_date, end_date, raw_json))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _factor_rows(row, api_name, source_ref):
    row = _canonical_row("market_factors", dict(row), api_name, source_ref)
    raw_json = json.dumps(row, ensure_ascii=False, sort_keys=True)
    symbol = row.get("symbol") or row.get("ts_code") or ""
    event_time = _factor_event_time(row, api_name) or _source_collected_at(source_ref)
    collected_at = row.get("collected_at") or _source_collected_at(source_ref)
    provider = row.get("provider") or (f"tushare_{api_name}" if api_name else "")
    source_file = row.get("source_file") or Path(source_ref).name
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


def _columns_for_insert(table, row_columns, target_columns, api_name):
    columns = [col for col in row_columns if col in target_columns]
    row_column_set = set(row_columns)

    derived_columns = []
    if {"ts_code", "symbol", "code"} & row_column_set and "symbol" in target_columns:
        derived_columns.append("symbol")
    if "vol" in row_column_set and "volume" in target_columns:
        derived_columns.append("volume")
    if "market" in target_columns and (
        api_name or "ts_code" in row_column_set or "symbol" in row_column_set
    ):
        derived_columns.append("market")
    if table == "market_bars_intraday":
        if "trade_date" in row_column_set and "bar_time" in target_columns:
            derived_columns.append("bar_time")
        if "trade_time" in row_column_set:
            if "bar_time" in target_columns:
                derived_columns.append("bar_time")
            if "trade_date" in target_columns:
                derived_columns.append("trade_date")
        if "time" in row_column_set:
            if "bar_time" in target_columns:
                derived_columns.append("bar_time")
            if "trade_date" in target_columns:
                derived_columns.append("trade_date")
        if api_name in ("weekly", "monthly", "rt_min", "rt_fut_min") and "interval" in target_columns:
            derived_columns.append("interval")
        if api_name == "rt_fut_min":
            for canonical, aliases in _INTRADAY_ALIAS_COLUMNS.items():
                if canonical in target_columns and (set(aliases) & row_column_set or canonical in {"last_trade_date", "expiry_date"}):
                    derived_columns.append(canonical)
    if table == "market_assets":
        for col in ("name", "asset_type", "sector", "status", "updated_at", "raw_json", "last_trade_date", "expiry_date"):
            if col in target_columns:
                derived_columns.append(col)
    if table == "market_events":
        for col in (
            "event_hash",
            "event_id",
            "revision",
            "source_family",
            "event_type",
            "event_time",
            "trade_date",
            "source",
            "raw_json",
        ):
            if col in target_columns:
                derived_columns.append(col)
    if table == "market_relationships":
        for col in (
            "relationship_hash",
            "relationship_type",
            "market",
            "parent_symbol",
            "parent_name",
            "child_symbol",
            "child_name",
            "start_date",
            "end_date",
            "trade_date",
            "weight",
            "raw_json",
        ):
            if col in target_columns:
                derived_columns.append(col)
    if table == "market_fund_portfolio":
        for col in (
            "portfolio_hash",
            "market",
            "symbol",
            "holding_symbol",
            "ann_date",
            "end_date",
            "market_value",
            "amount",
            "stk_mkv_ratio",
            "stk_float_ratio",
            "raw_json",
        ):
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


def _source_collected_at(source_ref):
    try:
        return datetime.fromtimestamp(Path(source_ref).stat().st_mtime, tz=timezone.utc).replace(microsecond=0).isoformat()
    except OSError:
        return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _trade_date_from_trade_time(trade_time):
    value = str(trade_time or "").strip()
    if len(value) >= 10:
        return value[:10].replace("-", "")
    return ""


_EVENT_TIME_COLUMNS = (
    "event_time",
    "datetime",
    "pub_time",
    "date",
    "trade_date",
    "ann_date",
    "report_date",
)


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


def _canonical_row(table, row, api_name, source_ref):
    original_symbol = row.get("symbol")
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
            bar_time = str(row.get("bar_time") or "")
            if re.fullmatch(r"\d{8}", bar_time):
                row["bar_time"] = (
                    f"{bar_time[0:4]}-{bar_time[4:6]}-{bar_time[6:8]} 00:00:00"
                )
        elif api_name in ("rt_min", "rt_fut_min"):
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
                "index_basic": "index",
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
            row["updated_at"] = _source_collected_at(source_ref)
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

    if table == "market_relationships":
        provider = row.get("provider") or (f"tushare_{api_name}" if api_name else "")
        parent_symbol = _first_present(row, "parent_symbol", "parent_code", "index_code", "ts_code", "index_id", "id")
        child_symbol = _first_present(row, "child_symbol", "child_code", "con_code", "stock_code", "member_code", "symbol", "code")
        if child_symbol == parent_symbol:
            child_symbol = _first_present(row, "con_code", "stock_code", "member_code", "child_code")
        parent_name = _first_present(row, "parent_name", "index_name", "name", "industry_name")
        child_name = _first_present(row, "child_name", "con_name", "stock_name", "member_name")
        trade_date = _first_present(row, "trade_date", "ann_date", "date")
        start_date = _first_present(row, "start_date", "in_date", "begin_date")
        end_date = _first_present(row, "end_date", "out_date", "end_date")
        raw_json = row.get("raw_json") or json.dumps(row, ensure_ascii=False, sort_keys=True)
        if provider and not row.get("provider"):
            row["provider"] = provider
        row["relationship_type"] = row.get("relationship_type") or api_name or "membership"
        row["market"] = row.get("market") or _market_for(api_name, parent_symbol or child_symbol)
        row["parent_symbol"] = parent_symbol
        row["parent_name"] = parent_name
        row["child_symbol"] = child_symbol
        row["child_name"] = child_name
        row["trade_date"] = trade_date or start_date or end_date or row.get("collected_at")
        row["start_date"] = start_date
        row["end_date"] = end_date
        row["weight"] = _coerce_float(row.get("weight"))
        row["raw_json"] = raw_json
        row["relationship_hash"] = row.get("relationship_hash") or _relationship_hash(
            api_name,
            row.get("parent_symbol"),
            row.get("child_symbol"),
            row.get("relationship_type"),
            row.get("trade_date"),
            raw_json,
        )

    if table == "market_fund_portfolio":
        provider = row.get("provider") or (f"tushare_{api_name}" if api_name else "")
        fund_symbol = _first_present(row, "ts_code", "fund_code", "symbol")
        holding_symbol = _first_present(row, "holding_symbol", "holding_code", "stock_code", "stk_code") or original_symbol
        ann_date = _first_present(row, "ann_date", "trade_date", "date")
        end_date = _first_present(row, "end_date", "period", "report_date")
        raw_json = row.get("raw_json") or json.dumps(
            {**row, "holding_symbol": holding_symbol},
            ensure_ascii=False,
            sort_keys=True,
        )
        if provider and not row.get("provider"):
            row["provider"] = provider
        row["market"] = row.get("market") or "Fund"
        row["symbol"] = fund_symbol
        row["holding_symbol"] = holding_symbol
        row["ann_date"] = ann_date
        row["end_date"] = end_date
        row["market_value"] = _coerce_float(_first_present(row, "market_value", "mkv"))
        row["amount"] = _coerce_float(row.get("amount"))
        row["stk_mkv_ratio"] = _coerce_float(row.get("stk_mkv_ratio"))
        row["stk_float_ratio"] = _coerce_float(row.get("stk_float_ratio"))
        row["raw_json"] = raw_json
        row["portfolio_hash"] = row.get("portfolio_hash") or _fund_portfolio_hash(
            api_name,
            row.get("symbol"),
            row.get("holding_symbol"),
            row.get("ann_date"),
            row.get("end_date"),
            raw_json,
        )

    if api_name and not row.get("provider"):
        row["provider"] = f"tushare_{api_name}"
    if not row.get("collected_at"):
        row["collected_at"] = _source_collected_at(source_ref)
    if not row.get("source_file"):
        row["source_file"] = Path(source_ref).name

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
        if table == "market_events":
            return (
                f"INSERT INTO {quoted_table} ({col_sql}) VALUES ({placeholders}) "
                f"ON CONFLICT ({conflict_sql}) DO NOTHING"
            )
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


def _row_values(row, columns, required_columns, source_ref, row_number):
    missing = [col for col in required_columns if row.get(col) in (None, "")]
    if missing:
        logger.warning(
            "read model store skipped bad row: source=%s row=%s missing required columns=%s",
            source_ref,
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


def _stored_event_fingerprint(row: sqlite3.Row) -> str:
    stored = {
        "title": row[1],
        "content": row[2],
        "url": row[3],
        "source": row[4],
        "symbol": row[5],
        "event_time": row[6],
        "trade_date": row[7],
    }
    try:
        raw = json.loads(row[8] or "{}")
    except (TypeError, ValueError):
        raw = {}
    if isinstance(raw, dict):
        for key, value in stored.items():
            raw.setdefault(key, value)
        stored = raw
    return event_content_fingerprint(stored)


def _assign_event_revision_outcome(
    conn: sqlite3.Connection,
    row: dict[str, Any],
) -> str:
    provider = str(row.get("provider") or "")
    event_type = str(row.get("event_type") or "event")
    event_id = stable_event_id(provider, event_type, row)
    fingerprint = event_content_fingerprint(row)
    latest = conn.execute(
        """
        SELECT revision, title, content, url, source, symbol, event_time, trade_date, raw_json
        FROM market_events
        WHERE event_id = ?
        ORDER BY revision DESC
        LIMIT 1
        """,
        (event_id,),
    ).fetchone()
    if latest is not None and _stored_event_fingerprint(latest) == fingerprint:
        return "unchanged"

    revision = int(latest[0] or 0) + 1 if latest is not None else 1
    row["event_id"] = event_id
    row["revision"] = revision
    row["source_family"] = source_family(provider)
    row["event_hash"] = hashlib.sha256(
        f"{event_id}|{revision}|{fingerprint}".encode()
    ).hexdigest()
    return "updated" if latest is not None else "inserted"


def _assign_event_revision(conn: sqlite3.Connection, row: dict[str, Any]) -> bool:
    return _assign_event_revision_outcome(conn, row) != "unchanged"


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
                if table == "market_events" and not _assign_event_revision(conn, canonical_row):
                    continue
                values = _row_values(canonical_row, columns, required_columns, source_path, row_number)
                if values is None:
                    continue
                if table == "market_events":
                    rows_written += _flush_chunk(conn, sql, [values])
                    transaction_rows += 1
                    if max_rows_per_transaction > 0 and transaction_rows >= max_rows_per_transaction:
                        conn.commit()
                        transaction_open = False
                        conn.execute("BEGIN IMMEDIATE")
                        transaction_open = True
                        transaction_rows = 0
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


def _ingest_rows_to_sqlite_unlocked(
    db_path,
    table,
    api_name,
    rows,
    *,
    source_name: str,
    max_transaction_rows: int | None = None,
):
    last_error: Exception | None = None
    for attempt in range(1, DB_BUSY_RETRIES + 1):
        try:
            return _ingest_rows_to_sqlite_once(
                db_path,
                table,
                api_name,
                rows,
                source_name=source_name,
                max_transaction_rows=max_transaction_rows,
            )
        except sqlite3.OperationalError as exc:
            last_error = exc
            if attempt < DB_BUSY_RETRIES and _sqlite_lock_error(exc):
                time.sleep(min(2.0 * attempt, 5.0))
                continue
            raise
    raise RuntimeError(f"read model store sqlite write failed after {DB_BUSY_RETRIES} attempts: {last_error}") from last_error


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
    with _read_model_lock(db_path_obj):
        rows_written = _ingest_rows_to_sqlite_unlocked(
            db_path_obj,
            table,
            api_name,
            rows,
            source_name=source,
            max_transaction_rows=max_transaction_rows,
        )
        if API_TO_TABLE_MAP.get(api_name) == table:
            for additional_table in ADDITIONAL_TABLES.get(api_name, ()):
                rows_written += _ingest_rows_to_sqlite_unlocked(
                    db_path_obj,
                    additional_table,
                    api_name,
                    rows,
                    source_name=source,
                    max_transaction_rows=max_transaction_rows,
                )
        return rows_written


def _validated_receipt_rows(
    rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    if isinstance(rows, (str, bytes)) or not isinstance(rows, Sequence):
        raise TypeError("rows must be a non-string sequence of mappings")
    clean_rows: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, Mapping):
            raise TypeError("every row must be a mapping")
        clean_rows.append(dict(row))
    if not clean_rows:
        raise ValueError("empty provider results require a terminal empty receipt")
    return clean_rows


def _validated_transaction_limit(max_transaction_rows: int | None) -> int:
    if max_transaction_rows is None:
        return MAX_TRANSACTION_ROWS
    if isinstance(max_transaction_rows, bool) or not isinstance(
        max_transaction_rows, int
    ):
        raise TypeError("max_transaction_rows must be an integer or None")
    if max_transaction_rows < 0:
        raise ValueError("max_transaction_rows must be non-negative")
    return max_transaction_rows


def _receipt_row_chunks(
    rows: Sequence[dict[str, Any]],
    max_transaction_rows: int,
) -> list[list[dict[str, Any]]]:
    if max_transaction_rows == 0:
        return [list(rows)]
    return [
        list(rows[start : start + max_transaction_rows])
        for start in range(0, len(rows), max_transaction_rows)
    ]


def _receipt_payload_fingerprint(rows: Sequence[Mapping[str, Any]]) -> str:
    payload = json.dumps(
        [dict(row) for row in rows],
        ensure_ascii=False,
        allow_nan=False,
        default=str,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _receipt_insert_statement(
    conn: sqlite3.Connection,
    *,
    table: str,
    api_name: str,
    rows: Sequence[Mapping[str, Any]],
) -> tuple[list[str], list[str], str]:
    target_columns = _table_columns(conn, table)
    if not target_columns:
        raise RuntimeError(f"sqlite table does not exist: {table}")

    row_columns: list[str] = []
    seen_columns: set[str] = set()
    for row in rows:
        for column in row:
            normalized = str(column)
            if normalized not in seen_columns:
                row_columns.append(normalized)
                seen_columns.add(normalized)
    if table == "market_factors":
        columns = [
            column for column in _FACTOR_INSERT_COLUMNS if column in target_columns
        ]
    else:
        columns = _columns_for_insert(table, row_columns, target_columns, api_name)
    if not columns:
        raise RuntimeError(
            f"no matching sqlite columns for table={table} api_name={api_name}"
        )

    primary_keys = [
        column
        for column in table_primary_keys().get(table, [])
        if column in target_columns
    ]
    for primary_key in primary_keys:
        if primary_key not in columns:
            columns.append(primary_key)
    return (
        columns,
        _required_columns(table, target_columns),
        _insert_sql(table, columns, primary_keys),
    )


def _write_receipt_chunk(
    conn: sqlite3.Connection,
    *,
    table: str,
    api_name: str,
    rows: Sequence[Mapping[str, Any]],
    source_path: Path,
    columns: Sequence[str],
    required_columns: Sequence[str],
    sql: str,
) -> IngestCounts:
    values_to_write: list[list[Any]] = []
    validated = 0
    rejected = 0
    inserted = 0
    updated = 0
    unchanged = 0

    for row_number, provider_row in enumerate(rows, start=1):
        canonical_rows = (
            _factor_rows(dict(provider_row), api_name, source_path)
            if table == "market_factors"
            else [_canonical_row(table, dict(provider_row), api_name, source_path)]
        )
        provider_row_validated = False
        for canonical_row in canonical_rows:
            if table == "market_bars_intraday" and api_name == "rt_fut_min":
                canonical_row = _enrich_futures_intraday_from_assets(
                    conn, canonical_row
                )
            if table == "market_events":
                outcome = _assign_event_revision_outcome(conn, canonical_row)
                if outcome == "unchanged":
                    provider_row_validated = True
                    unchanged += 1
                    continue
                values = _row_values(
                    canonical_row,
                    columns,
                    required_columns,
                    source_path,
                    row_number,
                )
                if values is None:
                    continue
                provider_row_validated = True
                _flush_chunk(conn, sql, [values])
                if outcome == "inserted":
                    inserted += 1
                else:
                    updated += 1
            else:
                values = _row_values(
                    canonical_row,
                    columns,
                    required_columns,
                    source_path,
                    row_number,
                )
                if values is None:
                    continue
                provider_row_validated = True
                values_to_write.append(values)

        if provider_row_validated:
            validated += 1
        else:
            rejected += 1

    if values_to_write:
        _flush_chunk(conn, sql, values_to_write)
    if validated == 0:
        raise ValueError("no provider rows passed read-model validation")

    exact_event_outcomes = table == "market_events"
    return IngestCounts(
        returned=len(rows),
        validated=validated,
        inserted=inserted if exact_event_outcomes else None,
        updated=updated if exact_event_outcomes else None,
        unchanged=unchanged if exact_event_outcomes else None,
        rejected=rejected,
        committed=validated,
        count_semantics=(
            "event_revision_outcomes_exact"
            if exact_event_outcomes
            else "generic_upsert_outcomes_unavailable"
        ),
    )


def ingest_rows_with_receipts(
    db_path: Path,
    table: str,
    rows: Sequence[Mapping[str, Any]],
    *,
    context: IngestContext,
    source_name: str | None = None,
    max_transaction_rows: int | None = None,
) -> IngestResult:
    """Commit provider rows and one success receipt per real SQLite transaction."""

    if not isinstance(db_path, Path):
        raise TypeError("db_path must be pathlib.Path")
    if not isinstance(context, IngestContext):
        raise TypeError("context must be IngestContext")
    db_binding = _validated_existing_sqlite_binding(db_path)

    clean_rows = _validated_receipt_rows(rows)
    transaction_limit = _validated_transaction_limit(max_transaction_rows)
    source_path = Path(source_name or f"{context.provider_api}_direct")
    receipt_ids: list[str] = []
    aggregate_counts: list[IngestCounts] = []

    with _read_model_lock(db_binding.canonical_path):
        _require_unchanged_sqlite_binding(db_binding)
        conn = sqlite3.connect(
            f"{db_binding.canonical_path.as_uri()}?mode=rw",
            uri=True,
            timeout=30,
        )
        try:
            _require_unchanged_sqlite_binding(db_binding)
            _prepare_sqlite_connection(conn)
            _require_unchanged_sqlite_binding(db_binding)
            columns, required_columns, sql = _receipt_insert_statement(
                conn,
                table=table,
                api_name=context.provider_api,
                rows=clean_rows,
            )
            for transaction_index, chunk in enumerate(
                _receipt_row_chunks(clean_rows, transaction_limit)
            ):
                try:
                    conn.execute("BEGIN IMMEDIATE")
                    _require_unchanged_sqlite_binding(db_binding)
                    counts = _write_receipt_chunk(
                        conn,
                        table=table,
                        api_name=context.provider_api,
                        rows=chunk,
                        source_path=source_path,
                        columns=columns,
                        required_columns=required_columns,
                        sql=sql,
                    )
                    receipt_id = insert_ingest_receipt(
                        conn,
                        context=context,
                        target_table=table,
                        transaction_index=transaction_index,
                        status="success",
                        counts=counts,
                        errors=(),
                        payload_fingerprint=_receipt_payload_fingerprint(chunk),
                    )
                    _require_unchanged_sqlite_binding(db_binding)
                    conn.commit()
                except Exception:
                    conn.rollback()
                    raise
                aggregate_counts.append(counts)
                receipt_ids.append(receipt_id)
        finally:
            conn.close()

    exact_event_outcomes = table == "market_events"
    result_counts = IngestCounts(
        returned=sum(count.returned for count in aggregate_counts),
        validated=sum(count.validated for count in aggregate_counts),
        inserted=(
            sum(count.inserted or 0 for count in aggregate_counts)
            if exact_event_outcomes
            else None
        ),
        updated=(
            sum(count.updated or 0 for count in aggregate_counts)
            if exact_event_outcomes
            else None
        ),
        unchanged=(
            sum(count.unchanged or 0 for count in aggregate_counts)
            if exact_event_outcomes
            else None
        ),
        rejected=sum(count.rejected for count in aggregate_counts),
        committed=sum(count.committed for count in aggregate_counts),
        count_semantics=(
            "event_revision_outcomes_exact"
            if exact_event_outcomes
            else "generic_upsert_outcomes_unavailable"
        ),
    )
    return IngestResult(
        status="success",
        counts=result_counts,
        receipt_ids=tuple(receipt_ids),
        errors=(),
    )

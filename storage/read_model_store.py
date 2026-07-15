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
from contextlib import contextmanager
from datetime import datetime, timezone
import sqlite3
from pathlib import Path
from typing import Any

import dataset_registry as dataset_registry_contract
from storage.event_identity import (
    event_content_fingerprint,
    source_family,
    stable_event_id,
)
from storage.schema_contract import get_table, table_primary_keys
from env_bootstrap import env_int
from runtime_paths import marketdata_sqlite_path

logger = logging.getLogger(__name__)
CHUNK_SIZE = 1000
MAX_TRANSACTION_ROWS = env_int(
    "SHAREDSIGNALS_READ_MODEL_MAX_TRANSACTION_ROWS", 0, min_value=0
)
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
                    raise TimeoutError(
                        f"timed out waiting for read model store lock: {lock_path}"
                    ) from exc
                time.sleep(min(1.0, max(0.05, deadline - time.monotonic())))
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


TUSHARE_API_TO_TABLE_MAP = dataset_registry_contract.TUSHARE_API_TO_TABLE_MAP
TUSHARE_ALLOWED_API_NAMES = dataset_registry_contract.TUSHARE_ALLOWED_API_NAMES
API_TO_TABLE_MAP = TUSHARE_API_TO_TABLE_MAP
_DATASET_REGISTRY = dataset_registry_contract.load_dataset_registry()
_PROVIDER_CLAIM_SCHEMA = "provider-claim.v1"


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
    payload = "|".join(
        str(part or "")
        for part in (api_name, symbol, event_time, factor_name, raw_json)
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def tushare_provider_discriminator(api_name: str) -> str:
    dataset = _DATASET_REGISTRY.resolve(f"tushare.{api_name}")
    return _DATASET_REGISTRY.provider_binding(
        dataset.dataset_id,
        "tushare",
    ).read_discriminator_value


def _resolve_provider_discriminator(
    api_name: str,
    provider_discriminator: str | None,
) -> str:
    api_name = str(api_name or "").strip()
    requested = str(provider_discriminator or "").strip()
    if api_name not in TUSHARE_ALLOWED_API_NAMES:
        if not requested:
            raise ValueError(
                "provider_discriminator is required for unregistered "
                f"api_name={api_name!r}"
            )
        return requested

    dataset = _DATASET_REGISTRY.resolve(f"tushare.{api_name}")
    registered_values = tuple(
        binding.read_discriminator_value for binding in dataset.provider_bindings
    )
    if not requested:
        if len(registered_values) != 1:
            raise ValueError(
                "provider_discriminator is required for multi-binding "
                f"api_name={api_name!r}"
            )
        return registered_values[0]
    if requested not in registered_values:
        raise ValueError(
            f"unknown provider_discriminator {requested!r} for api_name={api_name!r}"
        )
    return requested


def _registry_target_tables(
    api_name: str,
    provider_discriminator: str,
) -> tuple[str, ...]:
    if api_name not in TUSHARE_ALLOWED_API_NAMES:
        return ()
    dataset = _DATASET_REGISTRY.resolve(f"tushare.{api_name}")
    for binding in dataset.provider_bindings:
        if binding.read_discriminator_value == provider_discriminator:
            return binding.target_tables
    raise ValueError(
        f"unknown provider_discriminator {provider_discriminator!r} "
        f"for api_name={api_name!r}"
    )


def _json_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _canonical_raw_json(row: dict[str, Any]) -> str:
    original = dict(row)
    has_raw_payload = "raw_json" in original
    raw_payload = original.get("raw_json") if has_raw_payload else original
    has_context_claim = "provider" in original or "event_type" in original

    if has_raw_payload or has_context_claim:
        provenance: dict[str, Any] = {
            "raw_payload_source": "raw_json" if has_raw_payload else "row",
            "schema": _PROVIDER_CLAIM_SCHEMA,
        }
        if "provider" in original:
            provenance["provider_claim"] = original.get("provider")
        if "event_type" in original:
            provenance["event_type_claim"] = original.get("event_type")
        envelope: dict[str, Any] = {
            "_sharedsignals_provenance": provenance,
            "raw_payload": raw_payload,
        }
        if has_raw_payload:
            envelope["row_payload"] = {
                key: value for key, value in original.items() if key != "raw_json"
            }
        return json.dumps(
            envelope,
            ensure_ascii=False,
            sort_keys=True,
        )
    return _json_text(raw_payload)


def _fund_portfolio_hash(
    api_name, symbol, holding_symbol, ann_date, end_date, raw_json
):
    payload = "|".join(
        str(part or "")
        for part in (api_name, symbol, holding_symbol, ann_date, end_date, raw_json)
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _factor_rows(
    row,
    api_name,
    source_ref,
    *,
    provider_discriminator: str,
):
    row = _canonical_row(
        "market_factors",
        dict(row),
        api_name,
        source_ref,
        provider_discriminator=provider_discriminator,
    )
    raw_json = row.get("raw_json") or json.dumps(
        row,
        ensure_ascii=False,
        sort_keys=True,
    )
    symbol = row.get("symbol") or row.get("ts_code") or ""
    event_time = _factor_event_time(row, api_name) or _source_collected_at(source_ref)
    collected_at = row.get("collected_at") or _source_collected_at(source_ref)
    provider = str(row.get("provider") or "")
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
    if "raw_json" in target_columns:
        derived_columns.append("raw_json")
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


def _canonical_row(
    table,
    row,
    api_name,
    source_ref,
    *,
    provider_discriminator: str,
):
    provider_discriminator = str(provider_discriminator or "").strip()
    if not provider_discriminator:
        raise ValueError("provider_discriminator is required for canonical rows")
    if "provider" in row or table in {
        "market_events",
        "market_bars_daily",
        "market_bars_intraday",
    }:
        row["raw_json"] = _canonical_raw_json(row)
    row["provider"] = provider_discriminator
    original_symbol = row.get("symbol")
    symbol = (
        row.get("ts_code")
        or row.get("symbol")
        or row.get("code")
        or row.get("index_code")
    )
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
            for name_col in (
                "name",
                "csname",
                "cname",
                "extname",
                "index_name",
                "industry_name",
                "bond_short_name",
            ):
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
            row["last_trade_date"] = _first_present(
                row, "last_trade_date", "last_ddate"
            )
        if not row.get("expiry_date"):
            row["expiry_date"] = _first_present(
                row, "expiry_date", "delist_date", "delivery_date", "end_date"
            )
        if not row.get("updated_at"):
            row["updated_at"] = _source_collected_at(source_ref)
        if not row.get("raw_json"):
            row["raw_json"] = json.dumps(row, ensure_ascii=False, sort_keys=True)

    if table == "market_events":
        provider = provider_discriminator
        event_type = (
            api_name
            if api_name in TUSHARE_ALLOWED_API_NAMES
            else row.get("event_type") or api_name or "event"
        )
        event_time = row.get("event_time") or _event_time_from_row(row)
        trade_date = row.get("trade_date") or _trade_date_from_event_time(event_time)
        row["provider"] = provider
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
        provider = provider_discriminator
        parent_symbol = _first_present(
            row,
            "parent_symbol",
            "parent_code",
            "index_code",
            "ts_code",
            "index_id",
            "id",
        )
        child_symbol = _first_present(
            row,
            "child_symbol",
            "child_code",
            "con_code",
            "stock_code",
            "member_code",
            "symbol",
            "code",
        )
        if child_symbol == parent_symbol:
            child_symbol = _first_present(
                row, "con_code", "stock_code", "member_code", "child_code"
            )
        parent_name = _first_present(
            row, "parent_name", "index_name", "name", "industry_name"
        )
        child_name = _first_present(
            row, "child_name", "con_name", "stock_name", "member_name"
        )
        trade_date = _first_present(row, "trade_date", "ann_date", "date")
        start_date = _first_present(row, "start_date", "in_date", "begin_date")
        end_date = _first_present(row, "end_date", "out_date", "end_date")
        raw_json = row.get("raw_json") or json.dumps(
            row, ensure_ascii=False, sort_keys=True
        )
        if provider and not row.get("provider"):
            row["provider"] = provider
        row["relationship_type"] = (
            row.get("relationship_type") or api_name or "membership"
        )
        row["market"] = row.get("market") or _market_for(
            api_name, parent_symbol or child_symbol
        )
        row["parent_symbol"] = parent_symbol
        row["parent_name"] = parent_name
        row["child_symbol"] = child_symbol
        row["child_name"] = child_name
        row["trade_date"] = (
            trade_date or start_date or end_date or row.get("collected_at")
        )
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
        provider = provider_discriminator
        fund_symbol = _first_present(row, "ts_code", "fund_code", "symbol")
        holding_symbol = (
            _first_present(
                row, "holding_symbol", "holding_code", "stock_code", "stk_code"
            )
            or original_symbol
        )
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

    row["provider"] = provider_discriminator
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
        "provider": row[1],
        "event_type": row[2],
        "title": row[3],
        "content": row[4],
        "url": row[5],
        "source": row[6],
        "market": row[7],
        "symbol": row[8],
        "event_time": row[9],
        "trade_date": row[10],
        "raw_json": row[11],
    }
    return event_content_fingerprint(
        stored,
        provider=str(stored["provider"] or ""),
        event_type=str(stored["event_type"] or "event"),
    )


def _assign_event_revision(conn: sqlite3.Connection, row: dict[str, Any]) -> bool:
    provider = str(row.get("provider") or "")
    event_type = str(row.get("event_type") or "event")
    event_id = stable_event_id(
        provider,
        event_type,
        row,
        allow_legacy_fallback=False,
    )
    fingerprint = event_content_fingerprint(
        row,
        provider=provider,
        event_type=event_type,
    )
    latest = conn.execute(
        """
        SELECT revision, provider, event_type, title, content, url, source,
               market, symbol, event_time, trade_date, raw_json
        FROM market_events
        WHERE event_id = ?
        ORDER BY revision DESC
        LIMIT 1
        """,
        (event_id,),
    ).fetchone()
    if latest is not None and _stored_event_fingerprint(latest) == fingerprint:
        return False

    revision = int(latest[0] or 0) + 1 if latest is not None else 1
    row["event_id"] = event_id
    row["revision"] = revision
    row["source_family"] = source_family(provider)
    row["event_hash"] = hashlib.sha256(
        f"{event_id}|{revision}|{fingerprint}".encode()
    ).hexdigest()
    return True


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
    provider_discriminator: str,
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
                _factor_rows(
                    row,
                    str(api_name),
                    source_path,
                    provider_discriminator=provider_discriminator,
                )
                if table == "market_factors"
                else [
                    _canonical_row(
                        table,
                        row,
                        str(api_name),
                        source_path,
                        provider_discriminator=provider_discriminator,
                    )
                ]
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
    provider_discriminator: str | None = None,
    max_transaction_rows: int | None = None,
):
    trusted_provider = _resolve_provider_discriminator(
        str(api_name),
        provider_discriminator,
    )
    last_error: Exception | None = None
    for attempt in range(1, DB_BUSY_RETRIES + 1):
        try:
            return _ingest_rows_to_sqlite_once(
                db_path,
                table,
                api_name,
                rows,
                source_name=source_name,
                provider_discriminator=trusted_provider,
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
    provider_discriminator: str | None = None,
    max_transaction_rows: int | None = None,
):
    db_path_obj = Path(db_path)
    source = source_name or f"{api_name}_direct"
    trusted_provider = _resolve_provider_discriminator(
        str(api_name),
        provider_discriminator,
    )
    with _read_model_lock(db_path_obj):
        rows_written = _ingest_rows_to_sqlite_unlocked(
            db_path_obj,
            table,
            api_name,
            rows,
            source_name=source,
            provider_discriminator=trusted_provider,
            max_transaction_rows=max_transaction_rows,
        )
        if API_TO_TABLE_MAP.get(api_name) == table:
            for additional_table in _registry_target_tables(
                str(api_name),
                trusted_provider,
            ):
                if additional_table == table:
                    continue
                rows_written += _ingest_rows_to_sqlite_unlocked(
                    db_path_obj,
                    additional_table,
                    api_name,
                    rows,
                    source_name=source,
                    provider_discriminator=trusted_provider,
                    max_transaction_rows=max_transaction_rows,
                )
        return rows_written

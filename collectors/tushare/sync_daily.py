#!/usr/bin/env python3
"""SharedSignals Tushare daily sync — multi-tier collector.

Usage:
    sync_daily.py --tier P0_trading_5min         # 5-min trading data
    sync_daily.py --tier P1_eod_daily            # EOD after close
    sync_daily.py --tier P2_financial_daily      # financial statements
    sync_daily.py --tier P3_reference_daily      # reference/master
    sync_daily.py --tier P4_macro_daily          # macro indicators
    sync_daily.py --tier P5_hk_us_daily          # HK/US markets
    sync_daily.py --tier P6_other_daily          # futures/funds/news
    sync_daily.py --test --tier P0_trading_5min  # quick test on 3 stocks

Reads config.yaml for tier definitions, iterates over stock assets already in
the SharedSignals read model, calls each API, and writes provider rows directly
into the SQLite read model.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sqlite3
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import yaml

# Bootstrap: add SharedSignals root to sys.path so package imports work
_BASE_DIR = Path(__file__).resolve().parents[2]  # SharedSignals root
if str(_BASE_DIR) not in sys.path:
    sys.path.insert(0, str(_BASE_DIR))

from collectors.tushare.collector import TushareCollector  # noqa: E402
from storage.read_model_store import (  # noqa: E402
    API_TO_TABLE_MAP,
    DEFAULT_SQLITE_PATH,
    ingest_rows_to_sqlite,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

CONFIG_PATH = _BASE_DIR / "collectors" / "tushare" / "config.yaml"
DEFAULT_LOOKBACK_DAYS = 7
DEFAULT_P0_STOCK_BATCH_SIZE = 30
DEFAULT_P0_STOCK_BATCH_STATE = _BASE_DIR / "memory" / "p0_stock_batch_cursor.json"
ASHARE_TZ = ZoneInfo("Asia/Shanghai")

DEFAULT_TIERS = [
    "P0_trading_5min",
    "P1_eod_daily",
    "P2_financial_daily",
    "P3_reference_daily",
    "P4_macro_daily",
    "P5_hk_us_daily",
    "P6_other_daily",
]
VALID_TIERS = DEFAULT_TIERS


def load_config(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def valid_tiers(config_path: Path = CONFIG_PATH) -> list[str]:
    config = load_config(config_path)
    return list(config.get("priorities", {}).keys())


def _looks_like_ashare_stock_code(code: str) -> bool:
    """Return True for supported沪深 A股股票代码形态."""
    return bool(re.match(r"^(00|30|60|68)\d{4}\.(SZ|SH)$", code))


def _load_stock_codes_from_sqlite(sqlite_path: Path) -> list[str]:
    """Read A股 stock symbols from the SharedSignals read model."""
    if not sqlite_path.exists():
        return []
    try:
        conn = sqlite3.connect(f"file:{sqlite_path}?mode=ro", uri=True, timeout=5.0)
    except sqlite3.Error as exc:
        logger.warning("failed to open stock code sqlite source %s: %s", sqlite_path, exc)
        return []
    try:
        rows = conn.execute(
            """
            SELECT DISTINCT symbol, name
            FROM market_assets
            WHERE market = ?
              AND COALESCE(asset_type, 'stock') != ?
            ORDER BY symbol
            """,
            ("Ashare", "fund"),
        ).fetchall()
    except sqlite3.Error as exc:
        logger.warning("failed to load stock codes from %s: %s", sqlite_path, exc)
        return []
    finally:
        conn.close()
    codes = [
        str(row[0] or "").strip()
        for row in rows
        if _looks_like_ashare_stock_code(str(row[0] or "").strip())
        and str(row[1] or "").strip()
        and "退" not in str(row[1] or "")
    ]
    logger.info("Loaded %d A-share stock codes from sqlite market_assets: %s", len(codes), sqlite_path)
    return codes


def load_stock_codes(sqlite_path: Path = DEFAULT_SQLITE_PATH) -> list[str]:
    """Read stock codes from the SQLite read model only."""
    return _load_stock_codes_from_sqlite(sqlite_path)


def date_range(lookback_days: int, end_date_override: str | None = None) -> tuple[str, str, str]:
    """Return (trade_date, start_date, end_date) for a lookback window."""
    if end_date_override:
        today = datetime.strptime(end_date_override, "%Y%m%d")
    else:
        today = datetime.now()
    trade_date = today.strftime("%Y%m%d")
    start_date = (today - timedelta(days=lookback_days)).strftime("%Y%m%d")
    end_date = trade_date
    return trade_date, start_date, end_date


def is_ashare_intraday_session(now: datetime | None = None) -> bool:
    """Return True during A-share continuous/open auction intraday windows."""

    current = now or datetime.now(ASHARE_TZ)
    if current.tzinfo is None:
        current = current.replace(tzinfo=ASHARE_TZ)
    else:
        current = current.astimezone(ASHARE_TZ)
    if current.weekday() >= 5:
        return False
    minute = current.hour * 60 + current.minute
    morning = 9 * 60 + 30 <= minute <= 11 * 60 + 30
    afternoon = 13 * 60 <= minute <= 15 * 60
    return morning or afternoon


def resolve_api_window(
    api_def: dict[str, Any],
    trade_date: str,
    start_date: str,
    end_date: str,
) -> tuple[str, str, str]:
    """Return per-API date window, honoring optional lookback_days."""
    raw_lookback = api_def.get("lookback_days")
    if raw_lookback in (None, ""):
        return trade_date, start_date, end_date
    try:
        lookback_days = int(raw_lookback)
    except (TypeError, ValueError):
        logger.warning("invalid lookback_days for %s: %r", api_def.get("api_name"), raw_lookback)
        return trade_date, start_date, end_date
    if lookback_days <= 0:
        return trade_date, start_date, end_date
    try:
        end_dt = datetime.strptime(end_date, "%Y%m%d")
    except ValueError:
        logger.warning("invalid end_date for %s: %s", api_def.get("api_name"), end_date)
        return trade_date, start_date, end_date
    api_start_date = (end_dt - timedelta(days=lookback_days)).strftime("%Y%m%d")
    return trade_date, api_start_date, end_date


def fill_params(
    template: dict,
    ts_code: str | None,
    trade_date: str,
    start_date: str,
    end_date: str,
) -> dict:
    """Substitute placeholders in a params template dict.

    Uses data-level key-value substitution to avoid YAML injection via
    unescaped placeholder values (no string → YAML re-parse round-trip).
    """
    import copy
    result = copy.deepcopy(template)
    start_datetime = _datetime_start_bound(start_date)
    end_datetime = _datetime_end_bound(end_date)

    def _replace(val: Any) -> Any:
        if isinstance(val, str):
            if ts_code:
                val = val.replace("{ts_code}", ts_code)
            val = val.replace("{trade_date}", trade_date)
            val = val.replace("{start_date}", start_date)
            val = val.replace("{end_date}", end_date)
            val = val.replace("{start_datetime}", start_datetime)
            val = val.replace("{end_datetime}", end_datetime)
            return val
        if isinstance(val, dict):
            return {k: _replace(v) for k, v in val.items()}
        if isinstance(val, list):
            return [_replace(item) for item in val]
        return val

    return _replace(result)


def _datetime_start_bound(value: str) -> str:
    text = str(value or "").strip()
    if " " in text:
        return text
    if "-" in text:
        return f"{text} 00:00:00"
    return f"{text[:4]}-{text[4:6]}-{text[6:]} 00:00:00"


def _datetime_end_bound(value: str) -> str:
    text = str(value or "").strip()
    if " " in text:
        return text
    if "-" in text:
        return f"{text} 23:59:59"
    return f"{text[:4]}-{text[4:6]}-{text[6:]} 23:59:59"


def filter_apis(apis: list[dict[str, Any]], only_api: str | None) -> list[dict[str, Any]]:
    """Return APIs filtered by name when requested."""

    if not only_api:
        return apis
    names = {item.strip() for item in only_api.split(",") if item.strip()}
    if not names:
        return apis
    return [api for api in apis if str(api.get("api_name") or "") in names]


def parse_positive_int(value: str | int | None, default: int = 0) -> int:
    """Parse an optional positive integer setting."""

    if value in (None, ""):
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        logger.warning("invalid positive integer setting: %r; using %d", value, default)
        return default
    return parsed if parsed > 0 else default


def normalize_ashare_code(value: Any) -> str:
    """Return canonical A-share ts_code or empty string for unsupported symbols."""

    raw = str(value or "").strip().upper()
    if not raw:
        return ""
    match = re.search(r"(?<!\d)(\d{6})(?:\.(SH|SZ))?(?!\d)", raw)
    if not match:
        return ""
    digits, exchange = match.group(1), match.group(2) or ""
    if exchange == "SZ" and digits.startswith(("000", "001", "002", "003", "300", "301")):
        return f"{digits}.SZ"
    if exchange == "SH" and digits.startswith(("600", "601", "603", "605", "688", "689")):
        return f"{digits}.SH"
    if not exchange:
        if digits.startswith(("000", "001", "002", "003", "300", "301")):
            return f"{digits}.SZ"
        if digits.startswith(("600", "601", "603", "605", "688", "689")):
            return f"{digits}.SH"
    return ""


def load_priority_stock_codes(
    *,
    allowed_codes: set[str] | None = None,
    explicit_codes: str | None = None,
) -> tuple[list[str], dict[str, Any]]:
    """Load the P0 hot pool from explicit environment symbols only."""

    seen: set[str] = set()
    codes: list[str] = []
    sources: list[dict[str, Any]] = []

    def add(code: str, source: str) -> None:
        normalized = normalize_ashare_code(code)
        if not normalized or normalized in seen:
            return
        if allowed_codes is not None and normalized not in allowed_codes:
            return
        seen.add(normalized)
        codes.append(normalized)
        sources.append({"code": normalized, "source": source})

    for raw in (explicit_codes or os.environ.get("SHAREDSIGNALS_P0_PRIORITY_STOCKS", "")).split(","):
        add(raw, "env")

    return codes, {
        "enabled": bool(codes),
        "selected": len(codes),
        "sources": sources[:50],
        "source_count": len({item["source"] for item in sources}),
    }

def select_rotating_stock_batch(
    stock_codes: list[str],
    *,
    batch_size: int,
    state_path: Path,
    trade_date: str | None = None,
) -> tuple[list[str], dict[str, Any]]:
    """Return a stable rotating slice of stock codes and persist the next cursor."""

    total = len(stock_codes)
    if total == 0 or batch_size <= 0 or batch_size >= total:
        return stock_codes, {
            "enabled": False,
            "batch_size": batch_size,
            "total": total,
            "start_index": 0,
            "next_index": 0,
            "selected": total,
            "state_path": str(state_path),
        }

    start_index = 0
    if state_path.exists():
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
            if trade_date and str(state.get("trade_date") or "") != str(trade_date):
                start_index = 0
            else:
                start_index = int(state.get("next_index", 0)) % total
        except Exception as exc:
            logger.warning("failed to read P0 stock batch state %s: %s", state_path, exc)
            start_index = 0

    end_index = start_index + batch_size
    if end_index <= total:
        selected = stock_codes[start_index:end_index]
    else:
        selected = stock_codes[start_index:] + stock_codes[: end_index % total]
    next_index = end_index % total

    state_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = state_path.with_name(f".{state_path.name}.{os.getpid()}.tmp")
    tmp_path.write_text(
        json.dumps(
            {
                "next_index": next_index,
                "updated_at": datetime.now().isoformat(timespec="seconds"),
                "trade_date": trade_date or "",
                "batch_size": batch_size,
                "total": total,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    tmp_path.replace(state_path)

    return selected, {
        "enabled": True,
        "batch_size": batch_size,
        "total": total,
        "start_index": start_index,
        "next_index": next_index,
        "selected": len(selected),
        "state_path": str(state_path),
    }


def select_priority_rotating_stock_batch(
    stock_codes: list[str],
    *,
    batch_size: int,
    state_path: Path,
    priority_codes: list[str],
    trade_date: str | None = None,
) -> tuple[list[str], dict[str, Any]]:
    """Select priority symbols first, then fill remaining slots by rotating the market."""

    allowed = set(stock_codes)
    priority: list[str] = []
    seen: set[str] = set()
    for code in priority_codes:
        normalized = normalize_ashare_code(code)
        if normalized and normalized in allowed and normalized not in seen:
            seen.add(normalized)
            priority.append(normalized)

    if not priority:
        selected, meta = select_rotating_stock_batch(
            stock_codes,
            batch_size=batch_size,
            state_path=state_path,
            trade_date=trade_date,
        )
        meta["priority_count"] = 0
        return selected, meta

    if batch_size <= 0 or batch_size >= len(stock_codes):
        ordered = priority + [code for code in stock_codes if code not in seen]
        return ordered, {
            "enabled": False,
            "batch_size": batch_size,
            "total": len(stock_codes),
            "start_index": 0,
            "next_index": 0,
            "selected": len(ordered),
            "priority_count": len(priority),
            "priority_overflow": 0,
            "state_path": str(state_path),
        }

    priority_selected = priority[:batch_size]
    remaining_slots = max(batch_size - len(priority_selected), 0)
    rotating_universe = [code for code in stock_codes if code not in set(priority_selected)]
    if remaining_slots > 0:
        rotating, meta = select_rotating_stock_batch(
            rotating_universe,
            batch_size=remaining_slots,
            state_path=state_path,
            trade_date=trade_date,
        )
    else:
        rotating, meta = [], {
            "enabled": True,
            "batch_size": batch_size,
            "total": len(stock_codes),
            "start_index": 0,
            "next_index": 0,
            "selected": len(priority_selected),
            "state_path": str(state_path),
        }
    selected = priority_selected + [code for code in rotating if code not in set(priority_selected)]
    meta.update(
        {
            "enabled": True,
            "total": len(stock_codes),
            "selected": len(selected),
            "priority_count": len(priority_selected),
            "priority_overflow": max(len(priority) - len(priority_selected), 0),
        }
    )
    return selected, meta


# ---------------------------------------------------------------------------
# sync_tier — core sync logic for a single tier
# ---------------------------------------------------------------------------

def sync_tier(
    collector: TushareCollector,
    tier_name: str,
    apis: list[dict],
    stock_codes: list[str],
    trade_date: str,
    start_date: str,
    end_date: str,
    hk_stock_codes: list[str] | None = None,
    sqlite_db_path: Path = DEFAULT_SQLITE_PATH,
) -> dict[str, dict]:
    """Run all APIs in a tier. Returns {api_name: {"rows": N, "duration_s": t}}."""
    stats: dict[str, dict] = {}
    sqlite_errors: list[str] = []
    tier_start = time.time()

    # Split APIs: global, A-share per-stock, HK per-stock
    per_stock_ashare = [a for a in apis if a.get("per_stock", True) and a.get("stock_list") != "hk"]
    per_stock_hk = [a for a in apis if a.get("per_stock", True) and a.get("stock_list") == "hk"]
    global_apis = [a for a in apis if not a.get("per_stock", True)]

    # Resolve HK stock codes
    hk_codes = hk_stock_codes or []

    total_calls = (
        len(per_stock_ashare) * len(stock_codes)
        + len(per_stock_hk) * len(hk_codes)
        + len(global_apis)
    )
    call_idx = 0

    logger.info("[%s] %d APIs (%d A-share per-stock, %d HK per-stock, %d global) x (%d A / %d HK stocks) = %d calls",
                tier_name, len(apis), len(per_stock_ashare), len(per_stock_hk), len(global_apis),
                len(stock_codes), len(hk_codes), total_calls)

    def _write_sqlite(api_name: str, rows: list[dict[str, Any]], source_name: str) -> dict[str, Any]:
        if not rows:
            return {"rows": 0, "status": "empty", "error": ""}
        table = API_TO_TABLE_MAP.get(api_name)
        if not table:
            error = f"{api_name}:no sqlite table mapping"
            sqlite_errors.append(error)
            return {"rows": 0, "status": "unmapped", "error": error}
        try:
            written = ingest_rows_to_sqlite(sqlite_db_path, table, api_name, rows, source_name=source_name)
            if written == 0:
                error = f"{api_name}:{source_name}:direct sqlite write produced 0 rows for non-empty collection"
                sqlite_errors.append(error)
                logger.warning("direct sqlite write failed for %s from %s: %s", api_name, source_name, error)
                return {"rows": 0, "status": "failed", "error": error}
            logger.info("direct sqlite %s -> %s: %d rows from %s", api_name, table, written, source_name)
            return {"rows": written, "status": "ok", "error": ""}
        except Exception as exc:
            error = f"{api_name}:{source_name}:{exc}"
            sqlite_errors.append(error)
            logger.warning("direct sqlite write failed for %s from %s: %s", api_name, source_name, exc, exc_info=True)
            return {"rows": 0, "status": "failed", "error": error}

    def _sqlite_status(statuses: list[str]) -> str:
        if not statuses:
            return "empty"
        for status in ("failed", "ok", "empty", "unmapped"):
            if status in statuses:
                return status
        return "empty"

    def _run_per_stock(api_defs: list[dict], codes: list[str], label: str) -> None:
        nonlocal call_idx
        for api_def in api_defs:
            api_name = api_def["api_name"]
            template = api_def.get("params", {})
            fields = api_def.get("fields")
            _api_trade_date, api_start_date, api_end_date = resolve_api_window(
                api_def, trade_date, start_date, end_date
            )
            api_start = time.time()
            api_total = 0
            api_calls = 0
            api_failures = 0
            sqlite_total = 0
            sqlite_statuses: list[str] = []
            api_sqlite_errors: list[str] = []

            for ts_code in codes:
                call_idx += 1
                api_calls += 1
                params = fill_params(template, ts_code, trade_date, api_start_date, api_end_date)
                rows = collector.collect(api_name, params, fields)
                if getattr(collector, "last_collect_failed", False):
                    api_failures += 1
                api_total += len(rows)
                sqlite_result = _write_sqlite(api_name, rows, source_name=f"{api_name}_{ts_code}_{trade_date}")
                sqlite_total += int(sqlite_result["rows"])
                sqlite_statuses.append(str(sqlite_result["status"]))
                if sqlite_result.get("error"):
                    api_sqlite_errors.append(str(sqlite_result["error"]))
                logger.info("[%s] [%d/%d] %s %s → %d rows",
                            tier_name, call_idx, total_calls,
                            api_name, ts_code, len(rows))

            duration = time.time() - api_start
            stats[api_name] = {
                "rows": api_total,
                "calls": api_calls,
                "failure_count": api_failures,
                "duration_s": round(duration, 1),
                "sqlite_rows": sqlite_total,
                "sqlite_status": _sqlite_status(sqlite_statuses),
                "sqlite_errors": api_sqlite_errors,
            }
            logger.info("[%s] %s (%s): %d rows, api_failures=%d/%d, sqlite=%s/%d rows in %.1fs",
                        tier_name, api_name, label, api_total, api_failures, api_calls,
                        stats[api_name]["sqlite_status"], sqlite_total, duration)

    # ── Per-stock: A-share ──
    _run_per_stock(per_stock_ashare, stock_codes, "A-share")

    # ── Per-stock: HK ──
    _run_per_stock(per_stock_hk, hk_codes, "HK")

    # ── Global (non-per-stock) APIs ──
    for api_def in global_apis:
        api_name = api_def["api_name"]
        template = api_def.get("params", {})
        fields = api_def.get("fields")
        _api_trade_date, api_start_date, api_end_date = resolve_api_window(
            api_def, trade_date, start_date, end_date
        )
        api_start = time.time()

        call_idx += 1
        params = fill_params(template, None, trade_date, api_start_date, api_end_date)
        rows = collector.collect(api_name, params, fields)
        api_failures = 1 if getattr(collector, "last_collect_failed", False) else 0
        sqlite_result = _write_sqlite(api_name, rows, source_name=f"{api_name}_{trade_date}")
        sqlite_total = int(sqlite_result["rows"])

        duration = time.time() - api_start
        stats[api_name] = {
            "rows": len(rows),
            "calls": 1,
            "failure_count": api_failures,
            "duration_s": round(duration, 1),
            "sqlite_rows": sqlite_total,
            "sqlite_status": str(sqlite_result["status"]),
            "sqlite_errors": [str(sqlite_result["error"])] if sqlite_result.get("error") else [],
        }
        logger.info("[%s] [%d/%d] %s (global) → %d rows, api_failures=%d/1, sqlite=%s/%d rows in %.1fs",
                    tier_name, call_idx, total_calls,
                    api_name, len(rows), api_failures, stats[api_name]["sqlite_status"], sqlite_total, duration)

    tier_duration = time.time() - tier_start
    total_failures = sum(int(s.get("failure_count", 0)) for s in stats.values())
    counted_calls = sum(int(s.get("calls", 0)) for s in stats.values())
    stats["_tier_summary"] = {
        "tier": tier_name,
        "apis": len(apis),
        "calls": counted_calls,
        "failure_count": total_failures,
        "sqlite_failure_count": len(sqlite_errors),
        "failure_ratio": round(total_failures / counted_calls, 4) if counted_calls else 0.0,
        "duration_s": round(tier_duration, 1),
        "sqlite_errors": sqlite_errors,
    }
    logger.info("[%s] COMPLETE: %d APIs, api_failures=%d/%d, sqlite_errors=%d, %.1fs total",
                tier_name, len(apis), total_failures, counted_calls, len(sqlite_errors), tier_duration)
    return stats


def _failure_exit_code(summary: dict[str, Any], *, threshold: float, exit_on_failure: bool) -> int:
    if not exit_on_failure:
        return 0
    failure_count = int(summary.get("failure_count", 0))
    sqlite_failure_count = int(summary.get("sqlite_failure_count", 0))
    calls = int(summary.get("calls", 0))
    failure_ratio = (failure_count / calls) if calls else 0.0
    if sqlite_failure_count > 0 or (calls and failure_ratio > threshold):
        return 2
    return 0


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    valid_tier_names = valid_tiers()
    parser = argparse.ArgumentParser(description="SharedSignals Tushare multi-tier sync")
    parser.add_argument(
        "--tier",
        required=True,
        choices=valid_tier_names,
        help="Which tier to sync",
    )
    parser.add_argument(
        "--lookback",
        type=int,
        default=DEFAULT_LOOKBACK_DAYS,
        help=f"Lookback window in days (default: {DEFAULT_LOOKBACK_DAYS})",
    )
    parser.add_argument(
        "--test",
        action="store_true",
        help="Limit to 3 stocks for speed testing",
    )
    parser.add_argument(
        "--trade-date",
        default="",
        help="Override trade_date/end_date as YYYYMMDD for targeted backfill",
    )
    parser.add_argument(
        "--only-api",
        default="",
        help="Comma-separated API names to run within the selected tier",
    )
    parser.add_argument(
        "--exit-on-failure",
        action="store_true",
        help="Exit non-zero when failed Tushare calls exceed --failure-threshold",
    )
    parser.add_argument(
        "--failure-threshold",
        type=float,
        default=0.5,
        help="Failed-call ratio threshold for --exit-on-failure (default: 0.5)",
    )
    parser.add_argument(
        "--stock-batch-size",
        type=int,
        default=0,
        help=(
            "Limit P0 per-stock A-share calls to a rotating batch. "
            "Defaults to SHAREDSIGNALS_P0_STOCK_BATCH_SIZE or 100 for P0 production runs."
        ),
    )
    parser.add_argument(
        "--stock-batch-state",
        default="",
        help="Cursor file for P0 rotating stock batches",
    )
    parser.add_argument(
        "--allow-off-session",
        action="store_true",
        help="Allow P0 to run outside A-share intraday windows for manual backfill/smoke runs",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    # Load config + stocks
    config = load_config(CONFIG_PATH)
    stock_codes = load_stock_codes(sqlite_path=DEFAULT_SQLITE_PATH)

    if not stock_codes:
        logger.error("No A-share stock codes in SQLite market_assets — aborting")
        sys.exit(1)

    tier_name = args.tier
    if tier_name not in config.get("priorities", {}):
        logger.error("Tier %s not found in config.yaml priorities", tier_name)
        sys.exit(1)

    apis = filter_apis(config["priorities"][tier_name], args.only_api)
    if not apis:
        logger.error("No APIs selected for tier=%s only_api=%s", tier_name, args.only_api)
        sys.exit(1)

    # Detect if any API in this tier needs HK stock codes
    needs_hk = any(a.get("stock_list") == "hk" for a in apis)
    hk_stock_codes: list[str] = []
    if needs_hk:
        logger.warning("HK per-stock Tushare collection is disabled until HK assets are sourced from the read model")

    if args.test:
        stock_codes = stock_codes[:3]
        hk_stock_codes = hk_stock_codes[:3] if hk_stock_codes else []
        logger.info("TEST MODE: using %d A-share / %d HK stocks", len(stock_codes), len(hk_stock_codes))

    trade_date, start_date, end_date = date_range(args.lookback, args.trade_date or None)
    if (
        tier_name == "P0_trading_5min"
        and not args.test
        and not args.allow_off_session
        and os.environ.get("SHAREDSIGNALS_P0_ALLOW_OFF_SESSION", "").strip() != "1"
        and not is_ashare_intraday_session()
    ):
        logger.info("SKIP P0_trading_5min outside A-share intraday session; cursor not advanced")
        return

    batch_meta: dict[str, Any] = {"enabled": False}
    if tier_name == "P0_trading_5min" and not args.test:
        batch_size = args.stock_batch_size or parse_positive_int(
            os.environ.get("SHAREDSIGNALS_P0_STOCK_BATCH_SIZE"),
            DEFAULT_P0_STOCK_BATCH_SIZE,
        )
        state_path = Path(
            args.stock_batch_state
            or os.environ.get("SHAREDSIGNALS_P0_STOCK_BATCH_STATE")
            or DEFAULT_P0_STOCK_BATCH_STATE
        )
        priority_codes, priority_meta = load_priority_stock_codes(allowed_codes=set(stock_codes))
        stock_codes, batch_meta = select_priority_rotating_stock_batch(
            stock_codes,
            batch_size=batch_size,
            state_path=state_path,
            priority_codes=priority_codes,
            trade_date=trade_date,
        )
        batch_meta["priority_sources"] = priority_meta.get("sources", [])
        batch_meta["priority_source_count"] = priority_meta.get("source_count", 0)
        if batch_meta.get("enabled"):
            logger.info(
                "P0 priority rotating stock batch: selected %d/%d stocks, priority=%d, batch_size=%d, cursor %d→%d, state=%s",
                batch_meta["selected"],
                batch_meta["total"],
                batch_meta.get("priority_count", 0),
                batch_meta["batch_size"],
                batch_meta["start_index"],
                batch_meta["next_index"],
                batch_meta["state_path"],
            )

    logger.info("=" * 60)
    logger.info("TIER: %s  |  A-Stocks: %d  |  HK-Stocks: %d  |  APIs: %d",
                tier_name, len(stock_codes), len(hk_stock_codes), len(apis))
    if batch_meta.get("enabled"):
        logger.info("P0 batch mode: %s", batch_meta)
    logger.info("Window: %s → %s (trade_date=%s, lookback=%d days)",
                start_date, end_date, trade_date, args.lookback)
    logger.info("=" * 60)

    collector = TushareCollector()
    start_time = time.time()

    stats = sync_tier(
        collector, tier_name, apis, stock_codes,
        trade_date, start_date, end_date,
        hk_stock_codes=hk_stock_codes,
    )

    # Summary
    elapsed = time.time() - start_time
    logger.info("=" * 60)
    logger.info("SYNC SUMMARY [%s] — %.1fs total", tier_name, elapsed)
    total_rows = 0
    total_sqlite_rows = 0
    sqlite_errors: list[str] = []
    for api_name, s in stats.items():
        if api_name.startswith("_"):
            continue
        total_rows += s["rows"]
        total_sqlite_rows += s.get("sqlite_rows", 0)
        sqlite_errors.extend(s.get("sqlite_errors", []))
        logger.info("  %-25s %6d rows  api_failures=%4d/%-4d  sqlite=%-8s %6d  %6.1fs",
                    api_name, s["rows"], s.get("failure_count", 0), s.get("calls", 0),
                    s.get("sqlite_status", "empty"), s.get("sqlite_rows", 0), s["duration_s"])
    tier_summary = stats.get("_tier_summary", {})
    logger.info("  %-25s %6d rows", "TOTAL", total_rows)
    logger.info("  %-25s %6d rows", "SQLITE_TOTAL", total_sqlite_rows)
    logger.info("  %-25s %6d/%-6d", "TUSHARE_FAILURES", tier_summary.get("failure_count", 0), tier_summary.get("calls", 0))
    if sqlite_errors:
        logger.warning("SQLITE_ERRORS: %s", sqlite_errors)
    logger.info("=" * 60)

    exit_code = _failure_exit_code(
        tier_summary,
        threshold=args.failure_threshold,
        exit_on_failure=args.exit_on_failure,
    )
    if exit_code:
        failure_count = int(tier_summary.get("failure_count", 0))
        sqlite_failure_count = int(tier_summary.get("sqlite_failure_count", 0))
        calls = int(tier_summary.get("calls", 0))
        failure_ratio = (failure_count / calls) if calls else 0.0
        logger.error(
            "Tushare sync failed threshold: api_failures=%d sqlite_failures=%d calls=%d ratio=%.2f threshold=%.2f",
            failure_count,
            sqlite_failure_count,
            calls,
            failure_ratio,
            args.failure_threshold,
        )
        sys.exit(exit_code)


if __name__ == "__main__":
    main()

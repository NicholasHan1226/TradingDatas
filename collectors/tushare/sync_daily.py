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

Reads config.yaml for tier definitions, iterates over stocks in
reference/stock_master.csv (for per_stock APIs), calls each API,
and writes date-partitioned CSV output to data/tushare/.
"""

from __future__ import annotations

import argparse
import csv
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

from collectors.tushare.collector import SaveError, TushareCollector  # noqa: E402
from storage.csv_bridge import (  # noqa: E402
    CSV_TO_TABLE_MAP,
    DEFAULT_SQLITE_PATH,
    ingest_csv_to_sqlite,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

CONFIG_PATH = _BASE_DIR / "collectors" / "tushare" / "config.yaml"
STOCK_MASTER_PATH = _BASE_DIR / "reference" / "stock_master.csv"
HK_STOCK_MASTER_PATH = _BASE_DIR / "reference" / "hk_stock_master.csv"
DEFAULT_LOOKBACK_DAYS = 7
DEFAULT_P0_STOCK_BATCH_SIZE = 30
DEFAULT_P0_STOCK_BATCH_STATE = _BASE_DIR / "memory" / "p0_stock_batch_cursor.json"
ASHARE_TZ = ZoneInfo("Asia/Shanghai")
DEFAULT_P0_PRIORITY_STOCK_FILES = [
    _BASE_DIR.parent / "TradingAgent" / "signals" / "positions" / "simulated_ashare_positions.json",
    _BASE_DIR.parent / "TradingAgent" / "shared" / "logs" / "local_sim" / "local_sim_positions.json",
    _BASE_DIR.parent / "TradingAgent" / "shared" / "logs" / "ashare_no_trade_explanations.jsonl",
    _BASE_DIR.parent / "TradingAgent" / "shared" / "runtime_test" / "ashare_preopen_dry_run_latest.json",
    _BASE_DIR.parent / "TradingAgent" / "shared" / "review" / "ashare" / "execution_exclusions_*.jsonl",
    _BASE_DIR.parent / "MarketGraph" / "outputs" / "ashare_closing_buy_candidates.json",
    Path("/opt/investment/tradingagent/signals/positions/simulated_ashare_positions.json"),
    Path("/opt/investment/tradingagent/shared/logs/local_sim/local_sim_positions.json"),
    Path("/opt/investment/tradingagent/shared/logs/ashare_no_trade_explanations.jsonl"),
    Path("/opt/investment/tradingagent/shared/runtime_test/ashare_preopen_dry_run_latest.json"),
    Path("/opt/investment/tradingagent/shared/review/ashare/execution_exclusions_*.jsonl"),
    Path("/opt/investment/MarketGraph/outputs/ashare_closing_buy_candidates.json"),
]
DEFAULT_PRIORITY_JSONL_MAX_LINES = 500

VALID_TIERS = [
    "P0_trading_5min",
    "P1_eod_daily",
    "P2_financial_daily",
    "P3_reference_daily",
    "P4_macro_daily",
    "P5_hk_us_daily",
    "P6_other_daily",
]


def load_config(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


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


def load_stock_codes(
    path: Path,
    *,
    prefer_sqlite_assets: bool = False,
    sqlite_path: Path = DEFAULT_SQLITE_PATH,
) -> list[str]:
    """Read ts_code column from stock_master.csv."""
    if prefer_sqlite_assets:
        sqlite_codes = _load_stock_codes_from_sqlite(sqlite_path)
        if sqlite_codes:
            return sqlite_codes

    codes: list[str] = []
    with path.open("r", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            code = (row.get("ts_code") or "").strip()
            if code:
                codes.append(code)
    logger.info("Loaded %d stock codes from %s", len(codes), path)
    return codes


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

    def _replace(val: Any) -> Any:
        if isinstance(val, str):
            if ts_code:
                val = val.replace("{ts_code}", ts_code)
            val = val.replace("{trade_date}", trade_date)
            val = val.replace("{start_date}", start_date)
            val = val.replace("{end_date}", end_date)
            return val
        if isinstance(val, dict):
            return {k: _replace(v) for k, v in val.items()}
        if isinstance(val, list):
            return [_replace(item) for item in val]
        return val

    return _replace(result)


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


def _extract_ashare_codes(payload: Any) -> list[str]:
    """Extract A-share codes from nested JSON-like payloads."""

    codes: list[str] = []
    if isinstance(payload, dict):
        for key in ("ts_code", "symbol", "code", "ticker"):
            code = normalize_ashare_code(payload.get(key))
            if code:
                codes.append(code)
        for value in payload.values():
            codes.extend(_extract_ashare_codes(value))
    elif isinstance(payload, list):
        for item in payload:
            codes.extend(_extract_ashare_codes(item))
    elif isinstance(payload, str):
        codes.extend(normalize_ashare_code(match.group(0)) for match in re.finditer(r"\d{6}(?:\.(?:SH|SZ))?", payload.upper()))
    return [code for code in codes if code]


def _priority_stock_paths() -> list[Path]:
    values = [
        item.strip()
        for item in os.environ.get("SHAREDSIGNALS_P0_PRIORITY_STOCK_FILES", "").replace(",", os.pathsep).split(os.pathsep)
        if item.strip()
    ]
    if values:
        return [Path(value).expanduser() for value in values]
    return list(DEFAULT_P0_PRIORITY_STOCK_FILES)


def _expand_priority_stock_paths(paths: list[Path]) -> list[Path]:
    expanded: list[Path] = []
    for path in paths:
        text = str(path)
        if any(char in text for char in "*?[]"):
            matches = sorted(
                path.parent.glob(path.name),
                key=lambda item: item.stat().st_mtime if item.exists() else 0,
                reverse=True,
            )
            expanded.extend(item for item in matches if item.is_file())
        else:
            expanded.append(path)
    return expanded


def _read_priority_stock_payloads(path: Path) -> list[Any]:
    if path.suffix.lower() != ".jsonl":
        return [json.loads(path.read_text(encoding="utf-8"))]

    max_lines = parse_positive_int(
        os.environ.get("SHAREDSIGNALS_P0_PRIORITY_JSONL_MAX_LINES"),
        DEFAULT_PRIORITY_JSONL_MAX_LINES,
    )
    lines = path.read_text(encoding="utf-8").splitlines()
    payloads: list[Any] = []
    for line in lines[-max_lines:]:
        stripped = line.strip()
        if not stripped:
            continue
        try:
            payloads.append(json.loads(stripped))
        except json.JSONDecodeError as exc:
            logger.warning("failed to parse P0 priority jsonl line from %s: %s", path, exc)
    return payloads


def load_priority_stock_codes(
    *,
    paths: list[Path] | None = None,
    allowed_codes: set[str] | None = None,
    explicit_codes: str | None = None,
) -> tuple[list[str], dict[str, Any]]:
    """Load the P0 hot pool from holdings/candidate JSON files and env symbols."""

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

    for path in _expand_priority_stock_paths(paths if paths is not None else _priority_stock_paths()):
        if not path.exists() or not path.is_file():
            continue
        try:
            payloads = _read_priority_stock_payloads(path)
        except Exception as exc:
            logger.warning("failed to read P0 priority stock file %s: %s", path, exc)
            continue
        before = len(codes)
        for payload in payloads:
            for code in _extract_ashare_codes(payload):
                add(code, str(path))
        if len(codes) > before:
            logger.info("Loaded %d P0 priority stocks from %s", len(codes) - before, path)

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
    sqlite_bridge_enabled: bool = True,
    sqlite_db_path: Path = DEFAULT_SQLITE_PATH,
) -> dict[str, dict]:
    """Run all APIs in a tier. Returns {api_name: {"rows": N, "duration_s": t}}."""
    stats: dict[str, dict] = {}
    bridge_errors: list[str] = []
    save_errors: list[str] = []
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

    def _bridge_csv(api_name: str, path: Path | None) -> dict[str, Any]:
        if not sqlite_bridge_enabled or path is None:
            return {
                "rows": 0,
                "status": "disabled" if not sqlite_bridge_enabled else "empty",
                "error": "",
            }
        table = CSV_TO_TABLE_MAP.get(api_name)
        if not table:
            return {"rows": 0, "status": "unmapped", "error": ""}
        try:
            rows = ingest_csv_to_sqlite(sqlite_db_path, table, path)
            logger.info("sqlite bridge %s -> %s: %d rows from %s", api_name, table, rows, path)
            return {"rows": rows, "status": "ok", "error": ""}
        except Exception as exc:
            error = f"{api_name}:{path}:{exc}"
            bridge_errors.append(error)
            logger.warning("sqlite bridge failed for %s from %s: %s", api_name, path, exc, exc_info=True)
            return {"rows": 0, "status": "failed", "error": error}

    def _bridge_status(statuses: list[str]) -> str:
        if not sqlite_bridge_enabled:
            return "disabled"
        if not statuses:
            return "empty"
        for status in ("failed", "ok", "empty", "unmapped", "disabled"):
            if status in statuses:
                return status
        return "empty"

    def _save_csv(
        api_name: str,
        rows: list[dict[str, Any]],
        filename: str | None = None,
    ) -> tuple[Path | None, str]:
        if not rows:
            return None, ""
        try:
            return collector.save(api_name, rows, trade_date, filename=filename), ""
        except SaveError as exc:
            error = str(exc)
            logger.warning("csv save failed for %s: %s", api_name, error, exc_info=True)
        except Exception as exc:
            error = f"save failed for {api_name}: {exc}"
            logger.warning("csv save failed for %s: %s", api_name, error, exc_info=True)
        save_errors.append(error)
        return None, error

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
            save_failures = 0
            bridge_total = 0
            bridge_statuses: list[str] = []
            api_bridge_errors: list[str] = []
            api_save_errors: list[str] = []

            for ts_code in codes:
                call_idx += 1
                api_calls += 1
                params = fill_params(template, ts_code, trade_date, api_start_date, api_end_date)
                rows = collector.collect(api_name, params, fields)
                if getattr(collector, "last_collect_failed", False):
                    api_failures += 1
                api_total += len(rows)
                save_path, save_error = _save_csv(api_name, rows, filename=ts_code)
                if save_error:
                    save_failures += 1
                    api_save_errors.append(save_error)
                bridge_result = _bridge_csv(api_name, save_path)
                bridge_total += int(bridge_result["rows"])
                bridge_statuses.append(str(bridge_result["status"]))
                if bridge_result.get("error"):
                    api_bridge_errors.append(str(bridge_result["error"]))
                logger.info("[%s] [%d/%d] %s %s → %d rows",
                            tier_name, call_idx, total_calls,
                            api_name, ts_code, len(rows))

            duration = time.time() - api_start
            stats[api_name] = {
                "rows": api_total,
                "calls": api_calls,
                "failure_count": api_failures,
                "save_failure_count": save_failures,
                "duration_s": round(duration, 1),
                "sqlite_bridge_rows": bridge_total,
                "bridge_status": _bridge_status(bridge_statuses),
                "bridge_errors": api_bridge_errors,
                "save_errors": api_save_errors,
            }
            logger.info("[%s] %s (%s): %d rows, api_failures=%d/%d, save_failures=%d, bridge=%s/%d rows in %.1fs",
                        tier_name, api_name, label, api_total, api_failures, api_calls, save_failures,
                        stats[api_name]["bridge_status"], bridge_total, duration)

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
        save_path, save_error = _save_csv(api_name, rows)
        save_failures = 1 if save_error else 0
        bridge_result = _bridge_csv(api_name, save_path)
        bridge_total = int(bridge_result["rows"])

        duration = time.time() - api_start
        stats[api_name] = {
            "rows": len(rows),
            "calls": 1,
            "failure_count": api_failures,
            "save_failure_count": save_failures,
            "duration_s": round(duration, 1),
            "sqlite_bridge_rows": bridge_total,
            "bridge_status": str(bridge_result["status"]),
            "bridge_errors": [str(bridge_result["error"])] if bridge_result.get("error") else [],
            "save_errors": [save_error] if save_error else [],
        }
        logger.info("[%s] [%d/%d] %s (global) → %d rows, api_failures=%d/1, save_failures=%d, bridge=%s/%d rows in %.1fs",
                    tier_name, call_idx, total_calls,
                    api_name, len(rows), api_failures, save_failures, stats[api_name]["bridge_status"], bridge_total, duration)

    tier_duration = time.time() - tier_start
    total_failures = sum(int(s.get("failure_count", 0)) for s in stats.values())
    total_save_failures = sum(int(s.get("save_failure_count", 0)) for s in stats.values())
    counted_calls = sum(int(s.get("calls", 0)) for s in stats.values())
    stats["_tier_summary"] = {
        "tier": tier_name,
        "apis": len(apis),
        "calls": counted_calls,
        "failure_count": total_failures,
        "save_failure_count": total_save_failures,
        "bridge_failure_count": len(bridge_errors),
        "failure_ratio": round(total_failures / counted_calls, 4) if counted_calls else 0.0,
        "duration_s": round(tier_duration, 1),
        "bridge_errors": bridge_errors,
        "save_errors": save_errors,
    }
    logger.info("[%s] COMPLETE: %d APIs, api_failures=%d/%d, save_failures=%d, bridge_errors=%d, %.1fs total",
                tier_name, len(apis), total_failures, counted_calls, total_save_failures, len(bridge_errors), tier_duration)
    return stats


def _failure_exit_code(summary: dict[str, Any], *, threshold: float, exit_on_failure: bool) -> int:
    if not exit_on_failure:
        return 0
    failure_count = int(summary.get("failure_count", 0))
    save_failure_count = int(summary.get("save_failure_count", 0))
    bridge_failure_count = int(summary.get("bridge_failure_count", 0))
    calls = int(summary.get("calls", 0))
    combined_failure_count = failure_count + save_failure_count
    failure_ratio = (combined_failure_count / calls) if calls else 0.0
    if bridge_failure_count > 0 or save_failure_count > 0 or (calls and failure_ratio > threshold):
        return 2
    return 0


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="SharedSignals Tushare multi-tier sync")
    parser.add_argument(
        "--tier",
        required=True,
        choices=VALID_TIERS,
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
        "--no-sqlite-bridge",
        action="store_true",
        help="Disable additive CSV-to-SQLite bridge and keep CSV-only mode",
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
    stock_codes = load_stock_codes(STOCK_MASTER_PATH, prefer_sqlite_assets=True)

    if not stock_codes:
        logger.error("No stock codes in %s — aborting", STOCK_MASTER_PATH)
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
        if HK_STOCK_MASTER_PATH.exists():
            hk_stock_codes = load_stock_codes(HK_STOCK_MASTER_PATH)
            if not hk_stock_codes:
                logger.warning("HK stock master file exists but is empty: %s", HK_STOCK_MASTER_PATH)
        else:
            logger.warning("HK stock master file not found: %s — HK per-stock APIs will be skipped", HK_STOCK_MASTER_PATH)

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
        sqlite_bridge_enabled=not args.no_sqlite_bridge,
    )

    # Summary
    elapsed = time.time() - start_time
    logger.info("=" * 60)
    logger.info("SYNC SUMMARY [%s] — %.1fs total", tier_name, elapsed)
    total_rows = 0
    total_bridge_rows = 0
    bridge_errors: list[str] = []
    save_errors: list[str] = []
    for api_name, s in stats.items():
        if api_name.startswith("_"):
            continue
        total_rows += s["rows"]
        total_bridge_rows += s.get("sqlite_bridge_rows", 0)
        bridge_errors.extend(s.get("bridge_errors", []))
        save_errors.extend(s.get("save_errors", []))
        logger.info("  %-25s %6d rows  api_failures=%4d/%-4d  save_failures=%4d  bridge=%-8s %6d  %6.1fs",
                    api_name, s["rows"], s.get("failure_count", 0), s.get("calls", 0), s.get("save_failure_count", 0),
                    s.get("bridge_status", "empty"), s.get("sqlite_bridge_rows", 0), s["duration_s"])
    tier_summary = stats.get("_tier_summary", {})
    logger.info("  %-25s %6d rows", "TOTAL", total_rows)
    logger.info("  %-25s %6d rows", "SQLITE_BRIDGE_TOTAL", total_bridge_rows)
    logger.info("  %-25s %6d/%-6d", "TUSHARE_FAILURES", tier_summary.get("failure_count", 0), tier_summary.get("calls", 0))
    logger.info("  %-25s %6d", "SAVE_FAILURES", tier_summary.get("save_failure_count", 0))
    if bridge_errors:
        logger.warning("SQLITE_BRIDGE_ERRORS: %s", bridge_errors)
    if save_errors:
        logger.warning("SAVE_ERRORS: %s", save_errors)
    logger.info("=" * 60)

    exit_code = _failure_exit_code(
        tier_summary,
        threshold=args.failure_threshold,
        exit_on_failure=args.exit_on_failure,
    )
    if exit_code:
        failure_count = int(tier_summary.get("failure_count", 0))
        save_failure_count = int(tier_summary.get("save_failure_count", 0))
        bridge_failure_count = int(tier_summary.get("bridge_failure_count", 0))
        calls = int(tier_summary.get("calls", 0))
        failure_ratio = ((failure_count + save_failure_count) / calls) if calls else 0.0
        logger.error(
            "Tushare sync failed threshold: api_failures=%d save_failures=%d bridge_failures=%d calls=%d ratio=%.2f threshold=%.2f",
            failure_count,
            save_failure_count,
            bridge_failure_count,
            calls,
            failure_ratio,
            args.failure_threshold,
        )
        sys.exit(exit_code)


if __name__ == "__main__":
    main()

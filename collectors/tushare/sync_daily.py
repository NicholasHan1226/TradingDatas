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
import hashlib
import json
import logging
import os
import re
import sqlite3
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import yaml

# Bootstrap: add SharedSignals root to sys.path so package imports work
_BASE_DIR = Path(__file__).resolve().parents[2]  # SharedSignals root
if str(_BASE_DIR) not in sys.path:
    sys.path.insert(0, str(_BASE_DIR))

from collectors.tushare.collector import TushareCollector  # noqa: E402
from collectors.tushare.tushare_common import (  # noqa: E402
    ProviderCallOutcome,
    provider_outcome_log_fields,
)
from storage.read_model_store import (  # noqa: E402
    API_TO_TABLE_MAP,
    DEFAULT_SQLITE_PATH,
    ingest_rows_to_sqlite,
)
from tools.interface_runtime_ledger import record_tushare_stats  # noqa: E402

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

CONFIG_PATH = _BASE_DIR / "collectors" / "tushare" / "config.yaml"
DEFAULT_LOOKBACK_DAYS = 7
ASHARE_TZ = ZoneInfo("Asia/Shanghai")
DEFAULT_P2_EVIDENCE_PATH = _BASE_DIR / "logs" / "watchdog_inputs" / "p2_financial_budget.json"
DEFAULT_P2_HISTORY_PATH = _BASE_DIR / "logs" / "p2_financial_budget.jsonl"

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


@dataclass
class ResourceBudget:
    """Conservative provider/write/deadline budget for one collector run."""

    max_provider_calls: int = 0
    max_rows_admitted: int = 0
    deadline_seconds: float = 0.0
    started_monotonic: float = field(default_factory=time.monotonic)
    provider_calls: int = 0
    rows_admitted: int = 0
    exceeded_reason: str = ""

    @property
    def exceeded(self) -> bool:
        return bool(self.exceeded_reason)

    def _check_deadline(self) -> bool:
        if self.exceeded:
            return False
        if self.deadline_seconds > 0 and self.elapsed_seconds() >= self.deadline_seconds:
            self.exceeded_reason = "deadline_seconds_exceeded"
            return False
        return True

    def admit_provider_call(self) -> bool:
        if not self._check_deadline():
            return False
        if self.max_provider_calls > 0 and self.provider_calls >= self.max_provider_calls:
            self.exceeded_reason = "provider_call_budget_exceeded"
            return False
        self.provider_calls += 1
        return True

    def admit_rows_for_write(self, count: int) -> bool:
        if not self._check_deadline():
            return False
        count = max(0, int(count))
        if self.max_rows_admitted > 0 and self.rows_admitted + count > self.max_rows_admitted:
            self.exceeded_reason = "sqlite_row_budget_exceeded"
            return False
        self.rows_admitted += count
        return True

    def elapsed_seconds(self) -> float:
        return max(0.0, time.monotonic() - self.started_monotonic)

    def checkpoint(self) -> bool:
        return self._check_deadline()

    def evidence(self) -> dict[str, Any]:
        return {
            "status": "degraded" if self.exceeded else "ok",
            "max_provider_calls": self.max_provider_calls,
            "provider_calls": self.provider_calls,
            "max_rows_admitted": self.max_rows_admitted,
            "rows_admitted": self.rows_admitted,
            "deadline_seconds": self.deadline_seconds,
            "elapsed_seconds": round(self.elapsed_seconds(), 3),
            "exceeded_reason": self.exceeded_reason or None,
        }


def load_config(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def valid_tiers(config_path: Path = CONFIG_PATH) -> list[str]:
    config = load_config(config_path)
    return list(config.get("priorities", {}).keys())


def _looks_like_ashare_stock_code(code: str) -> bool:
    """Return True for supported沪深 A股股票代码形态."""
    return bool(re.match(r"^(?:(?:00|30)\d{4}\.SZ|(?:60|68)\d{4}\.SH)$", code))


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


def p2_collection_window_allowed(now: datetime | None = None) -> bool:
    """Keep heavy P2 work outside the A-share opening/day-session envelope."""

    current = now or datetime.now(ASHARE_TZ)
    if current.tzinfo is None:
        current = current.replace(tzinfo=ASHARE_TZ)
    else:
        current = current.astimezone(ASHARE_TZ)
    if current.weekday() >= 5:
        return True
    minute = current.hour * 60 + current.minute
    return not (8 * 60 + 30 <= minute <= 16 * 60 + 30)


def write_p2_resource_evidence(
    stats: dict[str, Any],
    *,
    started_at: str,
    finished_at: str,
    output_path: Path = DEFAULT_P2_EVIDENCE_PATH,
    history_path: Path = DEFAULT_P2_HISTORY_PATH,
) -> dict[str, Any]:
    """Atomically publish P2 latest state and preserve append-only run history."""

    summary = dict(stats.get("_tier_summary") or {})
    status = "degraded" if (
        summary.get("completion_status") != "ok"
        or int(summary.get("failure_count") or 0) > 0
        or int(summary.get("critical_failure_count") or 0) > 0
        or int(summary.get("sqlite_failure_count") or 0) > 0
    ) else "ok"
    report = {
        "status": status,
        "tier": "P2_financial_daily",
        "started_at": started_at,
        "finished_at": finished_at,
        "resource_budget": summary.get("resource_budget") or {},
        "failure_count": int(summary.get("failure_count") or 0),
        "critical_failure_count": int(summary.get("critical_failure_count") or 0),
        "sqlite_failure_count": int(summary.get("sqlite_failure_count") or 0),
        "rollback_boundary": (
            "retain committed idempotent/append-only rows; disable the P2 cron and "
            "roll back code only; rerun the same window after review"
        ),
    }
    encoded = json.dumps(report, ensure_ascii=False, sort_keys=True)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    history_path.parent.mkdir(parents=True, exist_ok=True)
    temp = output_path.with_suffix(f".{os.getpid()}.tmp")
    temp.write_text(encoded + "\n", encoding="utf-8")
    temp.replace(output_path)
    with history_path.open("a", encoding="utf-8") as handle:
        handle.write(encoded + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    return report


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
    resource_budget: ResourceBudget | None = None,
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

    def _rotation_codes(api_def: dict, codes: list[str]) -> tuple[list[str], dict[str, Any]]:
        size = max(0, int(api_def.get("bounded_rotation_size") or 0))
        if size <= 0 or size >= len(codes):
            return codes, {
                "collection_mode": "full_universe",
                "universe_symbols": len(codes),
                "scheduled_symbols": len(codes),
                "rotation_offset": 0,
            }
        cycle_count = (len(codes) + size - 1) // size
        day_ordinal = datetime.strptime(trade_date, "%Y%m%d").date().toordinal()
        api_offset = int(hashlib.sha256(str(api_def.get("api_name") or "").encode()).hexdigest()[:8], 16)
        cycle_index = (day_ordinal + api_offset) % cycle_count
        offset = cycle_index * size
        selected = codes[offset:offset + size]
        return selected, {
            "collection_mode": "bounded_rotation",
            "universe_symbols": len(codes),
            "scheduled_symbols": len(selected),
            "rotation_offset": offset,
            "rotation_cycle_runs": cycle_count,
        }

    def _stock_call_count(api_defs: list[dict], codes: list[str]) -> int:
        total = 0
        for api_def in api_defs:
            batch_size = max(1, int(api_def.get("stock_batch_size") or 1))
            selected, _rotation = _rotation_codes(api_def, codes)
            total += (len(selected) + batch_size - 1) // batch_size
        return total

    total_calls = (
        _stock_call_count(per_stock_ashare, stock_codes)
        + _stock_call_count(per_stock_hk, hk_codes)
        + len(global_apis)
    )
    call_idx = 0

    logger.info("[%s] %d APIs (%d A-share per-stock, %d HK per-stock, %d global) x (%d A / %d HK stocks) = %d calls",
                tier_name, len(apis), len(per_stock_ashare), len(per_stock_hk), len(global_apis),
                len(stock_codes), len(hk_codes), total_calls)

    def _write_sqlite(api_name: str, rows: list[dict[str, Any]], source_name: str) -> dict[str, Any]:
        if not rows:
            return {"rows": 0, "status": "empty", "error": ""}
        if resource_budget is not None and not resource_budget.admit_rows_for_write(len(rows)):
            error = f"{api_name}:{source_name}:{resource_budget.exceeded_reason}"
            sqlite_errors.append(error)
            return {"rows": 0, "status": "failed", "error": error}
        table = API_TO_TABLE_MAP.get(api_name)
        if not table:
            error = f"{api_name}:no sqlite table mapping"
            sqlite_errors.append(error)
            return {"rows": 0, "status": "unmapped", "error": error}
        try:
            written = ingest_rows_to_sqlite(sqlite_db_path, table, api_name, rows, source_name=source_name)
            if written == 0:
                if table == "market_events":
                    logger.info(
                        "direct sqlite %s -> %s: idempotent no-change for %d rows from %s",
                        api_name,
                        table,
                        len(rows),
                        source_name,
                    )
                    return {
                        "rows": 0,
                        "status": "ok",
                        "error": "",
                        "idempotent_no_change": True,
                    }
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

    def _collect_provider_outcome(
        api_name: str,
        params: dict[str, Any],
        fields: str | None,
    ) -> ProviderCallOutcome:
        candidate: Any = None
        try:
            candidate = collector.collect_outcome(api_name, params, fields)
            if not isinstance(candidate, ProviderCallOutcome):
                raise TypeError("collector returned an invalid provider outcome type")
            candidate.validate_invariants()
            outcome = candidate
        except Exception as exc:
            outcome = ProviderCallOutcome(
                state="failed",
                rows=(),
                provider_code=getattr(candidate, "provider_code", None),
                error_code="provider_error",
                error_message=str(exc) or exc.__class__.__name__,
            )
        if outcome.state == "failed":
            logger.error(
                "[%s] %s provider failed: outcome=%s",
                tier_name,
                api_name,
                provider_outcome_log_fields(outcome),
            )
        return outcome

    def _run_per_stock(api_defs: list[dict], codes: list[str], label: str) -> None:
        nonlocal call_idx
        for api_def in api_defs:
            api_name = api_def["api_name"]
            template = api_def.get("params", {})
            fields = api_def.get("fields")
            batch_size = max(1, int(api_def.get("stock_batch_size") or 1))
            row_limit_guard = max(0, int(api_def.get("row_limit_guard") or 0))
            api_codes, rotation = _rotation_codes(api_def, codes)
            empty_is_failure = bool(api_def.get("empty_is_failure"))
            failed_batch_retry_rounds = max(0, int(api_def.get("failed_batch_retry_rounds") or 0))
            failed_batch_retry_delay_seconds = max(
                0.0, float(api_def.get("failed_batch_retry_delay_seconds") or 0)
            )
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
            failed_batches: list[tuple[int, list[str]]] = []
            possible_truncation_batches: set[int] = set()

            def _collect_batch(batch_index: int, code_batch: list[str], *, retry_round: int = 0) -> bool | None:
                nonlocal call_idx, api_calls, api_total, sqlite_total
                if resource_budget is not None and not resource_budget.admit_provider_call():
                    return None
                ts_code = ",".join(code_batch)
                if retry_round == 0:
                    call_idx += 1
                api_calls += 1
                params = fill_params(template, ts_code, trade_date, api_start_date, api_end_date)
                outcome = _collect_provider_outcome(api_name, params, fields)
                rows = [] if outcome.state == "failed" else list(outcome.rows)
                call_failed = outcome.state == "failed"
                if empty_is_failure and not rows:
                    call_failed = True
                    logger.error(
                        "[%s] %s batch %d returned no rows for %d requested symbols",
                        tier_name,
                        api_name,
                        batch_index,
                        len(code_batch),
                    )
                if row_limit_guard and len(rows) >= row_limit_guard:
                    call_failed = True
                    possible_truncation_batches.add(batch_index)
                    logger.error(
                        "[%s] %s batch %d reached provider row limit guard %d",
                        tier_name,
                        api_name,
                        batch_index,
                        row_limit_guard,
                    )
                api_total += len(rows)
                source_name = (
                    f"{api_name}_batch_{batch_index}_{trade_date}"
                    if batch_size > 1
                    else f"{api_name}_{ts_code}_{trade_date}"
                )
                sqlite_result = _write_sqlite(api_name, rows, source_name=source_name)
                sqlite_total += int(sqlite_result["rows"])
                sqlite_statuses.append(str(sqlite_result["status"]))
                if sqlite_result.get("error"):
                    api_sqlite_errors.append(str(sqlite_result["error"]))
                if retry_round:
                    logger.info(
                        "[%s] RETRY %d/%d %s batch=%d symbols=%d → %d rows",
                        tier_name,
                        retry_round,
                        failed_batch_retry_rounds,
                        api_name,
                        batch_index,
                        len(code_batch),
                        len(rows),
                    )
                else:
                    logger.info("[%s] [%d/%d] %s symbols=%d → %d rows",
                                tier_name, call_idx, total_calls,
                                api_name, len(code_batch), len(rows))
                return call_failed

            for batch_index, offset in enumerate(range(0, len(api_codes), batch_size), start=1):
                code_batch = api_codes[offset:offset + batch_size]
                batch_failed = _collect_batch(batch_index, code_batch)
                if batch_failed is None:
                    break
                if batch_failed:
                    failed_batches.append((batch_index, code_batch))

            for retry_round in range(1, failed_batch_retry_rounds + 1):
                if not failed_batches:
                    break
                delay = failed_batch_retry_delay_seconds * retry_round
                if delay:
                    time.sleep(delay)
                retry_failures: list[tuple[int, list[str]]] = []
                for batch_index, code_batch in failed_batches:
                    batch_failed = _collect_batch(batch_index, code_batch, retry_round=retry_round)
                    if batch_failed is None:
                        break
                    if batch_failed:
                        retry_failures.append((batch_index, code_batch))
                failed_batches = retry_failures
                if resource_budget is not None and resource_budget.exceeded:
                    break

            api_failures = len(failed_batches)

            duration = time.time() - api_start
            stats[api_name] = {
                "rows": api_total,
                "calls": api_calls,
                "failure_count": api_failures,
                "critical_failure_count": api_failures if (empty_is_failure or row_limit_guard) else 0,
                "duration_s": round(duration, 1),
                "sqlite_rows": sqlite_total,
                "sqlite_status": _sqlite_status(sqlite_statuses),
                "sqlite_errors": api_sqlite_errors,
                "possible_truncation": bool(possible_truncation_batches),
                **rotation,
            }
            logger.info("[%s] %s (%s): %d rows, api_failures=%d/%d, sqlite=%s/%d rows in %.1fs",
                        tier_name, api_name, label, api_total, api_failures, api_calls,
                        stats[api_name]["sqlite_status"], sqlite_total, duration)
            if resource_budget is not None and resource_budget.exceeded:
                break

    # ── Per-stock: A-share ──
    _run_per_stock(per_stock_ashare, stock_codes, "A-share")

    # ── Per-stock: HK ──
    _run_per_stock(per_stock_hk, hk_codes, "HK")

    # ── Global (non-per-stock) APIs ──
    for api_def in global_apis:
        if resource_budget is not None and not resource_budget.admit_provider_call():
            break
        api_name = api_def["api_name"]
        template = api_def.get("params", {})
        fields = api_def.get("fields")
        _api_trade_date, api_start_date, api_end_date = resolve_api_window(
            api_def, trade_date, start_date, end_date
        )
        api_start = time.time()

        call_idx += 1
        params = fill_params(template, None, trade_date, api_start_date, api_end_date)
        outcome = _collect_provider_outcome(api_name, params, fields)
        rows = [] if outcome.state == "failed" else list(outcome.rows)
        provider_failed = outcome.state == "failed"
        row_limit_guard = max(0, int(api_def.get("row_limit_guard") or 0))
        possible_truncation = bool(row_limit_guard and len(rows) >= row_limit_guard)
        coverage_key = str(api_def.get("coverage_key") or "")
        min_coverage = float(api_def.get("min_universe_coverage_ratio") or 0.0)
        unique_symbols = len({str(row.get(coverage_key) or "") for row in rows if coverage_key and row.get(coverage_key)})
        universe_size = len(stock_codes)
        coverage_ratio = round(unique_symbols / universe_size, 4) if universe_size else 0.0
        coverage_failed = bool(min_coverage and (not universe_size or coverage_ratio < min_coverage))
        guard_failed = possible_truncation or coverage_failed
        api_failures = 1 if provider_failed or guard_failed else 0
        if possible_truncation:
            logger.error(
                "[%s] %s reached provider row limit guard %d; possible silent truncation",
                tier_name,
                api_name,
                row_limit_guard,
            )
        if coverage_failed:
            logger.error(
                "[%s] %s coverage %.4f below %.4f (%d/%d unique symbols)",
                tier_name,
                api_name,
                coverage_ratio,
                min_coverage,
                unique_symbols,
                universe_size,
            )
        sqlite_result = _write_sqlite(api_name, rows, source_name=f"{api_name}_{trade_date}")
        sqlite_total = int(sqlite_result["rows"])

        duration = time.time() - api_start
        stats[api_name] = {
            "rows": len(rows),
            "calls": 1,
            "failure_count": api_failures,
            "critical_failure_count": 1 if guard_failed else 0,
            "duration_s": round(duration, 1),
            "sqlite_rows": sqlite_total,
            "sqlite_status": str(sqlite_result["status"]),
            "sqlite_errors": [str(sqlite_result["error"])] if sqlite_result.get("error") else [],
            "possible_truncation": possible_truncation,
            "coverage_status": "failed" if coverage_failed else ("ok" if min_coverage else "not_configured"),
            "coverage_key": coverage_key or None,
            "unique_symbols": unique_symbols,
            "universe_symbols": universe_size,
            "universe_coverage_ratio": coverage_ratio if min_coverage else None,
        }
        logger.info("[%s] [%d/%d] %s (global) → %d rows, api_failures=%d/1, sqlite=%s/%d rows in %.1fs",
                    tier_name, call_idx, total_calls,
                    api_name, len(rows), api_failures, stats[api_name]["sqlite_status"], sqlite_total, duration)

    tier_duration = time.time() - tier_start
    total_failures = sum(int(s.get("failure_count", 0)) for s in stats.values())
    critical_failures = sum(int(s.get("critical_failure_count", 0)) for s in stats.values())
    counted_calls = sum(int(s.get("calls", 0)) for s in stats.values())
    if resource_budget is not None:
        resource_budget.checkpoint()
    budget_evidence = resource_budget.evidence() if resource_budget is not None else None
    budget_critical_failure = 1 if resource_budget is not None and resource_budget.exceeded else 0
    stats["_tier_summary"] = {
        "tier": tier_name,
        "apis": len(apis),
        "calls": counted_calls,
        "failure_count": total_failures,
        "critical_failure_count": critical_failures + budget_critical_failure,
        "sqlite_failure_count": len(sqlite_errors),
        "failure_ratio": round(total_failures / counted_calls, 4) if counted_calls else 0.0,
        "duration_s": round(tier_duration, 1),
        "sqlite_errors": sqlite_errors,
        "completion_status": "degraded" if budget_critical_failure else "ok",
        "resource_budget": budget_evidence,
    }
    logger.info("[%s] COMPLETE: %d APIs, api_failures=%d/%d, sqlite_errors=%d, %.1fs total",
                tier_name, len(apis), total_failures, counted_calls, len(sqlite_errors), tier_duration)
    return stats


def _failure_exit_code(summary: dict[str, Any], *, threshold: float, exit_on_failure: bool) -> int:
    if not exit_on_failure:
        return 0
    failure_count = int(summary.get("failure_count", 0))
    critical_failure_count = int(summary.get("critical_failure_count", 0))
    sqlite_failure_count = int(summary.get("sqlite_failure_count", 0))
    calls = int(summary.get("calls", 0))
    failure_ratio = (failure_count / calls) if calls else 0.0
    if critical_failure_count > 0 or sqlite_failure_count > 0 or (calls and failure_ratio > threshold):
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
        "--allow-off-session",
        action="store_true",
        help="Allow P0 to run outside A-share intraday windows for manual backfill/smoke runs",
    )
    parser.add_argument("--max-provider-calls", type=int, default=0)
    parser.add_argument("--max-rows-admitted", type=int, default=0)
    parser.add_argument("--deadline-seconds", type=float, default=0.0)
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

    resource_budget: ResourceBudget | None = None
    if tier_name == "P2_financial_daily":
        if not p2_collection_window_allowed():
            logger.error("P2_financial_daily is forbidden during the A-share opening/day-session envelope")
            sys.exit(2)
        if args.max_provider_calls <= 0 or args.max_rows_admitted <= 0 or args.deadline_seconds <= 0:
            logger.error(
                "P2_financial_daily requires positive --max-provider-calls, "
                "--max-rows-admitted and --deadline-seconds budgets"
            )
            sys.exit(2)
        resource_budget = ResourceBudget(
            max_provider_calls=args.max_provider_calls,
            max_rows_admitted=args.max_rows_admitted,
            deadline_seconds=args.deadline_seconds,
        )

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
        logger.info("SKIP P0_trading_5min outside A-share intraday session")
        return

    logger.info("=" * 60)
    logger.info("TIER: %s  |  A-Stocks: %d  |  HK-Stocks: %d  |  APIs: %d",
                tier_name, len(stock_codes), len(hk_stock_codes), len(apis))
    logger.info("Window: %s → %s (trade_date=%s, lookback=%d days)",
                start_date, end_date, trade_date, args.lookback)
    logger.info("=" * 60)

    collector = TushareCollector()
    started_at = datetime.now(timezone.utc).isoformat()
    start_time = time.time()

    stats = sync_tier(
        collector, tier_name, apis, stock_codes,
        trade_date, start_date, end_date,
        hk_stock_codes=hk_stock_codes,
        resource_budget=resource_budget,
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

    finished_at = datetime.now(timezone.utc).isoformat()
    record_tushare_stats(
        stats,
        tier=tier_name,
        started_at=started_at,
        finished_at=finished_at,
    )
    if tier_name == "P2_financial_daily":
        write_p2_resource_evidence(
            stats,
            started_at=started_at,
            finished_at=finished_at,
        )

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

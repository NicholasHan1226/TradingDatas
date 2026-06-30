#!/usr/bin/env python3
"""Unified read-only data entry API for SharedSignals consumers.

Every public function returns list[dict]. Each item is wrapped as:
{
  "data": {...},
  "provenance": {"source_id": "...", "source_tier": "...", "collected_at": "..."},
  "freshness": {"score": 0.0-1.0, "stale": bool, "age_hours": float|None},
  "quality": {"score": 0.0-1.0, "completeness": 0.0-1.0},
  "degraded": bool,
  "lineage": {...}
}

Missing files, missing tables, empty result sets, and parser errors are returned
as degraded empty wrappers instead of raising.
"""

from __future__ import annotations

import csv
import json
import os
import sqlite3
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Iterable


INVESTMENT_ROOT = Path(os.environ.get("INVESTMENT_ROOT", "/opt/investment"))

# ---- Auto-load .env on import ----
import os as _os
_env_file = __import__("pathlib").Path(__file__).resolve().parent / ".env"
if _env_file.exists():
    with open(_env_file) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                if _line.startswith("export "):
                    _line = _line[7:]
                _key, _, _val = _line.partition("=")
                _os.environ[_key.strip()] = _val.strip().strip('"').strip("'")
# ---- end env loader ----
SHAREDSIGNALS_ROOT = Path(os.environ.get("SHAREDSIGNALS_ROOT", INVESTMENT_ROOT / "SharedSignals"))
MARKETGRAPH_ROOT = Path(os.environ.get("MARKETGRAPH_ROOT", INVESTMENT_ROOT / "MarketGraph"))
RUNTIME_ROOT = Path(os.environ.get("MARKETGRAPH_RUNTIME_ROOT", INVESTMENT_ROOT / "MarketGraphRuntime"))
ASHARE_ROOT = Path(os.environ.get("ASHARE_ROOT", INVESTMENT_ROOT / "Ashare"))
CRYPTO_ROOT = Path(os.environ.get("CRYPTO_ROOT", INVESTMENT_ROOT / "Crypto"))

SQLITE_PATH = Path(
    os.environ.get(
        "MARKETDATA_SQLITE",
        RUNTIME_ROOT / "read_model" / "marketdata.sqlite",
    )
)
INTAKE_ROOT = Path(
    os.environ.get(
        "SHAREDSIGNALS_INTAKE_ROOT",
        SHAREDSIGNALS_ROOT / "data" / "intake",
    )
)
REFERENCE_ROOT = Path(os.environ.get("SHAREDSIGNALS_REFERENCE_ROOT", SHAREDSIGNALS_ROOT / "reference"))
MONEYFLOW_ROOT = Path(os.environ.get("ASHARE_MONEYFLOW_ROOT", SHAREDSIGNALS_ROOT / "data" / "moneyflow"))  # TODO: build native moneyflow collector
# TODO: build native Tushare macro collector; for now symlink/copy macro_factors.csv from MG
MACRO_FACTORS_PATH = Path(os.environ.get("MACRO_FACTORS_PATH", SHAREDSIGNALS_ROOT / "data" / "macro_factors.csv"))
CRYPTO_KLINES_PATH = Path(os.environ.get("CRYPTO_KLINES_PATH", CRYPTO_ROOT / "data" / "market" / "klines.csv"))
REALTIME_5M_ROOT = Path(os.environ.get("REALTIME_5M_ROOT", RUNTIME_ROOT / "staging" / "tushare_rt_min_5m"))

LEGACY_RECOMMENDATIONS = SHAREDSIGNALS_ROOT / "data" / "legacy" / "recommendations.csv"  # LEGACY: migrate to SS-native
LEGACY_REVIEWS = SHAREDSIGNALS_ROOT / "data" / "legacy" / "reviews.csv"  # LEGACY
LEGACY_DIRECTION_HITS = SHAREDSIGNALS_ROOT / "data" / "legacy" / "direction_hit_reviews.csv"  # LEGACY
LEGACY_SHADOW_TRADES = SHAREDSIGNALS_ROOT / "data" / "legacy" / "shadow_sim_trades.csv"  # LEGACY
LEGACY_SHADOW_POSITIONS = SHAREDSIGNALS_ROOT / "data" / "legacy" / "latest_shadow_positions.csv"  # LEGACY
LEGACY_PAPER_POSITIONS = SHAREDSIGNALS_ROOT / "data" / "legacy" / "paper_positions.csv"  # LEGACY
LEGACY_SIM_EXECUTION_LOG = SHAREDSIGNALS_ROOT / "data" / "legacy" / "simulated_execution_log.jsonl"  # LEGACY


def _json_cached(fn: Callable[..., list[dict[str, Any]]], *args: Any) -> str:
    return json.dumps(fn(*args), ensure_ascii=False, sort_keys=True, default=str)


def _clone_cached(payload: str) -> list[dict[str, Any]]:
    return deepcopy(json.loads(payload))


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().isoformat(timespec="seconds")


def _parse_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.isdigit() and len(text) == 8:
        try:
            return datetime.strptime(text, "%Y%m%d").replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    normalized = text.replace("Z", "+00:00")
    for candidate in (normalized, normalized.replace("/", "-")):
        try:
            dt = datetime.fromisoformat(candidate)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except ValueError:
            continue
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y%m%d", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _date_key(value: Any) -> str:
    dt = _parse_datetime(value)
    if dt is None:
        raise ValueError(f"Cannot parse date: {value!r}")
    return dt.strftime("%Y%m%d")


def _file_collected_at(path: Path) -> str | None:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat(timespec="seconds")
    except OSError:
        return None


def _age_hours(collected_at: Any) -> float | None:
    dt = _parse_datetime(collected_at)
    if dt is None:
        return None
    return max(0.0, (_now() - dt).total_seconds() / 3600.0)


def _freshness(collected_at: Any, *, stale_after_hours: float = 24.0) -> dict[str, Any]:
    age = _age_hours(collected_at)
    if age is None:
        return {"score": 0.0, "stale": True, "age_hours": None}
    if age <= stale_after_hours:
        score = 1.0
    elif age <= stale_after_hours * 3:
        score = 0.7
    elif age <= stale_after_hours * 7:
        score = 0.4
    else:
        score = 0.1
    return {"score": score, "stale": age > stale_after_hours, "age_hours": round(age, 4)}


def _quality(data: dict[str, Any]) -> dict[str, Any]:
    if not data:
        return {"score": 0.0, "completeness": 0.0}
    total = len(data)
    present = sum(1 for value in data.values() if value not in (None, ""))
    completeness = present / total if total else 0.0
    return {"score": round(completeness, 4), "completeness": round(completeness, 4)}


def _clean_row(row: dict[str, Any]) -> dict[str, Any]:
    cleaned: dict[str, Any] = {}
    for key, value in row.items():
        if key is None:
            continue
        name = str(key).lstrip("\ufeff")
        cleaned[name] = value
    return cleaned


def _wrap(
    data: dict[str, Any],
    *,
    source_id: str,
    source_tier: str = "unknown",
    collected_at: Any = None,
    degraded: bool = False,
    lineage: dict[str, Any] | None = None,
    stale_after_hours: float = 24.0,
) -> dict[str, Any]:
    collected = collected_at or data.get("collected_at") or _now_iso()
    return {
        "data": data,
        "provenance": {
            "source_id": source_id,
            "source_tier": source_tier or "unknown",
            "collected_at": str(collected),
        },
        "freshness": _freshness(collected, stale_after_hours=stale_after_hours),
        "quality": _quality(data),
        "degraded": bool(degraded),
        "lineage": lineage or {},
    }


def _degraded_empty(source_id: str, reason: str, *, lineage: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    details = dict(lineage or {})
    details["reason"] = reason
    return [
        _wrap(
            {},
            source_id=source_id,
            source_tier="unavailable",
            collected_at=_now_iso(),
            degraded=True,
            lineage=details,
        )
    ]


def _safe_public(source_id: str, lineage: dict[str, Any], producer: Callable[[], str]) -> list[dict[str, Any]]:
    try:
        return _clone_cached(producer())
    except Exception as exc:  # pragma: no cover - final public boundary
        return _degraded_empty(source_id, f"reader failed: {exc}", lineage=lineage)


def _read_csv(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        return [_clean_row(row) for row in csv.DictReader(fh)]


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            item = json.loads(line)
            if isinstance(item, dict):
                rows.append(_clean_row(item))
    return rows


def _legacy_wrapped_rows(rows: list[dict[str, Any]], *, source_id: str, source_tier: str, collected_at: Any, lineage: dict[str, Any], stale_after_hours: float = 24.0) -> list[dict[str, Any]]:
    return _rows_to_wrappers(rows, source_id=source_id, source_tier=source_tier, collected_at=collected_at, lineage=lineage, stale_after_hours=stale_after_hours)


def _legacy_market_dataset(dataset: str, **kwargs: Any) -> list[dict[str, Any]] | None:
    name = str(dataset or "").strip()
    if name == "market_factors":
        symbols = [str(s) for s in kwargs.get("symbols", []) if s] or [str(kwargs.get("symbol") or "")]
        symbols = [s for s in symbols if s]
        for symbol in symbols:
            rows = get_fundamentals(symbol)
            if rows and not rows[0].get("degraded"):
                return rows
        return _degraded_empty("sqlite:market_factors", "no rows matched", lineage={"reader": "legacy_market_dataset", "dataset": name, "filters": kwargs})

    if name == "market_bars_daily":
        symbols = [str(s) for s in kwargs.get("symbols", []) if s] or [str(kwargs.get("symbol") or "")]
        limit = int(kwargs.get("limit", 60))
        for symbol in [s for s in symbols if s]:
            query = """
                SELECT * FROM market_bars_daily
                WHERE symbol = ?
                ORDER BY trade_date DESC
                LIMIT ?
            """
            rows, degraded = _sqlite_rows(query, (symbol, limit), "market_bars_daily")
            if degraded is not None:
                return degraded
            if rows:
                rows = list(reversed(rows))
                lineage = {"reader": "legacy_market_dataset", "dataset": name, "filters": {**kwargs, "symbol": symbol}}
                return _legacy_wrapped_rows(rows, source_id="sqlite:market_bars_daily", source_tier="marketdata", collected_at=None, lineage=lineage, stale_after_hours=48.0)
        return _degraded_empty("sqlite:market_bars_daily", "no rows matched", lineage={"reader": "legacy_market_dataset", "dataset": name, "filters": kwargs})

    file_map = {
        "recommendations": (LEGACY_RECOMMENDATIONS, _read_csv, "legacy:recommendations", "recommendation", 24.0),
        "reviews": (LEGACY_REVIEWS, _read_csv, "legacy:reviews", "review", 24.0),
        "direction_hit_reviews": (LEGACY_DIRECTION_HITS, _read_csv, "legacy:direction_hit_reviews", "review", 24.0),
        "shadow_sim_trades": (LEGACY_SHADOW_TRADES, _read_csv, "legacy:shadow_sim_trades", "tradebook", 24.0),
        "latest_shadow_positions": (LEGACY_SHADOW_POSITIONS, _read_csv, "legacy:latest_shadow_positions", "portfolio", 24.0),
        "paper_positions": (LEGACY_PAPER_POSITIONS, _read_csv, "legacy:paper_positions", "portfolio", 24.0),
        "simulated_execution_log": (LEGACY_SIM_EXECUTION_LOG, _read_jsonl, "legacy:simulated_execution_log", "tradebook", 24.0),
    }
    config = file_map.get(name)
    if config is None:
        return None
    path, loader, source_id, source_tier, stale_after_hours = config
    lineage = {"reader": "legacy_market_dataset", "dataset": name, "source_path": str(path)}
    try:
        if not path.exists():
            return _degraded_empty(source_id, f"missing file: {path}", lineage=lineage)
        rows = loader(path)
        return _legacy_wrapped_rows(rows, source_id=source_id, source_tier=source_tier, collected_at=_file_collected_at(path), lineage=lineage, stale_after_hours=stale_after_hours)
    except Exception as exc:
        return _degraded_empty(source_id, f"legacy dataset read failed: {exc}", lineage=lineage)


def _safe_csv(path: Path, source_id: str, lineage: dict[str, Any]) -> tuple[list[dict[str, Any]] | None, list[dict[str, Any]] | None]:
    try:
        if not path.exists():
            return None, _degraded_empty(source_id, f"missing file: {path}", lineage=lineage)
        return _read_csv(path), None
    except Exception as exc:  # pragma: no cover - defensive reader boundary
        return None, _degraded_empty(source_id, f"csv read failed: {exc}", lineage=lineage)


def _sqlite_rows(query: str, params: tuple[Any, ...], table: str) -> tuple[list[dict[str, Any]] | None, list[dict[str, Any]] | None]:
    lineage = {"reader": "sqlite", "db_path": str(SQLITE_PATH), "table": table}
    try:
        if not SQLITE_PATH.exists():
            return None, _degraded_empty(f"sqlite:{table}", f"missing sqlite db: {SQLITE_PATH}", lineage=lineage)
        conn = sqlite3.connect(f"file:{SQLITE_PATH}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        try:
            rows = [_clean_row(dict(row)) for row in conn.execute(query, params).fetchall()]
        finally:
            conn.close()
        return rows, None
    except Exception as exc:  # pragma: no cover - defensive reader boundary
        return None, _degraded_empty(f"sqlite:{table}", f"sqlite read failed: {exc}", lineage=lineage)


def _filter_date_range(rows: Iterable[dict[str, Any]], start: Any, end: Any, fields: tuple[str, ...]) -> list[dict[str, Any]]:
    start_key = _date_key(start)
    end_key = _date_key(end)
    if start_key > end_key:
        start_key, end_key = end_key, start_key
    matched = []
    for row in rows:
        row_key = None
        for field in fields:
            if row.get(field):
                try:
                    row_key = _date_key(row[field])
                    break
                except ValueError:
                    continue
        if row_key and start_key <= row_key <= end_key:
            matched.append(row)
    return matched


def _row_source_id(row: dict[str, Any], fallback: str) -> str:
    return str(row.get("source_id") or row.get("provider") or row.get("source") or row.get("source_name") or fallback)


def _row_source_tier(row: dict[str, Any], fallback: str = "unknown") -> str:
    return str(row.get("source_tier") or row.get("evidence_tier") or row.get("tier") or fallback)


def _rows_to_wrappers(
    rows: list[dict[str, Any]],
    *,
    source_id: str,
    source_tier: str = "unknown",
    collected_at: Any = None,
    lineage: dict[str, Any],
    stale_after_hours: float = 24.0,
) -> list[dict[str, Any]]:
    if not rows:
        return _degraded_empty(source_id, "no rows matched", lineage=lineage)
    wrapped = []
    for row in rows:
        wrapped.append(
            _wrap(
                row,
                source_id=_row_source_id(row, source_id),
                source_tier=_row_source_tier(row, source_tier),
                collected_at=row.get("collected_at") or row.get("collected_at_dt") or collected_at,
                degraded=False,
                lineage=lineage,
                stale_after_hours=stale_after_hours,
            )
        )
    return wrapped


@lru_cache(maxsize=512)
def _get_market_data_cached(ts_code: str, start: str, end: str, freq: str, adjusted: bool) -> str:
    if freq != "daily":
        return _json_cached(
            lambda: _degraded_empty(
                "sqlite:market_bars_daily",
                f"unsupported freq: {freq}",
                lineage={"reader": "get_market_data", "freq": freq, "adjusted": adjusted},
            )
        )
    start_key, end_key = _date_key(start), _date_key(end)
    if start_key > end_key:
        start_key, end_key = end_key, start_key
    query = """
        SELECT * FROM market_bars_daily
        WHERE symbol = ? AND trade_date >= ? AND trade_date <= ?
        ORDER BY trade_date ASC
    """
    rows, degraded = _sqlite_rows(query, (ts_code, start_key, end_key), "market_bars_daily")
    if degraded is not None:
        return _json_cached(lambda: degraded)
    lineage = {
        "reader": "get_market_data",
        "db_path": str(SQLITE_PATH),
        "table": "market_bars_daily",
        "filters": {"ts_code": ts_code, "start": start_key, "end": end_key, "freq": freq, "adjusted": adjusted},
        "adjustment_note": "market_bars_daily has no separate adjustment column; adjusted is preserved as lineage only",
    }
    return _json_cached(lambda: _rows_to_wrappers(rows or [], source_id="sqlite:market_bars_daily", source_tier="marketdata", lineage=lineage, stale_after_hours=48.0))



def _as_of_filter(rows: list[dict[str, Any]], as_of: str) -> list[dict[str, Any]]:
    """Filter rows by available_at <= as_of for point-in-time correctness."""
    if not as_of:
        return rows
    from datetime import datetime
    try:
        cutoff = datetime.strptime(as_of, "%Y%m%d")
    except ValueError:
        try:
            cutoff = datetime.strptime(as_of, "%Y%m%d_%H%M%S")
        except ValueError:
            return rows  # can't parse, return all
    filtered = []
    for row in rows:
        data = row.get("data", {})
        if isinstance(data, dict):
            trade_date = data.get("trade_date", "")
            if trade_date:
                try:
                    avail = datetime.strptime(trade_date + "160000", "%Y%m%d%H%M%S")
                    if avail <= cutoff:
                        filtered.append(row)
                except ValueError:
                    filtered.append(row)  # can't parse date, include
            else:
                filtered.append(row)
        else:
            filtered.append(row)
    return filtered if filtered else rows  # don't return empty if all filtered


def get_market_data(ts_code: str, start: Any = None, end: Any = None, freq: str = "daily", adjusted: bool = True, **kwargs: Any) -> list[dict[str, Any]]:
    if start is None and end is None:
        legacy_rows = _legacy_market_dataset(str(ts_code), **kwargs)
        if legacy_rows is not None:
            return legacy_rows
    lineage = {"reader": "get_market_data", "filters": {"ts_code": ts_code, "start": start, "end": end, "freq": freq, "adjusted": adjusted}}
    return _safe_public("sqlite:market_bars_daily", lineage, lambda: _get_market_data_cached(str(ts_code), str(start), str(end), str(freq), bool(adjusted)))


@lru_cache(maxsize=512)
def _get_events_cached(start: str, end: str, event_type: str | None) -> str:
    path = INTAKE_ROOT / "event_candidates.csv"
    lineage = {"reader": "get_events", "source_path": str(path), "filters": {"start": start, "end": end, "event_type": event_type}}
    rows, degraded = _safe_csv(path, "csv:event_candidates", lineage)
    if degraded is not None:
        return _json_cached(lambda: degraded)
    matched = _filter_date_range(rows or [], start, end, ("candidate_date", "collected_at_dt", "collected_at"))
    if event_type:
        matched = [row for row in matched if str(row.get("proposed_event_type", "")).lower() == event_type.lower()]
    return _json_cached(lambda: _rows_to_wrappers(matched, source_id="csv:event_candidates", source_tier="event_candidate", collected_at=_file_collected_at(path), lineage=lineage, stale_after_hours=24.0))


def get_events(start: Any = None, end: Any = None, event_type: str | None = None, **kwargs: Any) -> list[dict[str, Any]]:
    if start is None and "date" in kwargs:
        start = kwargs.get("date")
    if end is None:
        end = start
    lineage = {"reader": "get_events", "filters": {"start": start, "end": end, "event_type": event_type, **kwargs}}
    rows = _safe_public("csv:event_candidates", lineage, lambda: _get_events_cached(str(start), str(end), event_type))
    subject_code = kwargs.get("subject_code")
    subject_type = kwargs.get("subject_type")
    if subject_code:
        rows = [row for row in rows if isinstance(row, dict) and isinstance(row.get("data"), dict) and row["data"].get("subject_code") == subject_code]
    if subject_type:
        rows = [row for row in rows if isinstance(row, dict) and isinstance(row.get("data"), dict) and row["data"].get("subject_type") == subject_type]
    return rows


@lru_cache(maxsize=512)
def _get_sentiment_cached(start: str, end: str, tier: str | None) -> str:
    path = INTAKE_ROOT / "sentiment_signals.csv"
    lineage = {"reader": "get_sentiment", "source_path": str(path), "filters": {"start": start, "end": end, "tier": tier}}
    rows, degraded = _safe_csv(path, "csv:sentiment_signals", lineage)
    if degraded is not None:
        return _json_cached(lambda: degraded)
    matched = _filter_date_range(rows or [], start, end, ("source_date", "collected_at_dt", "collected_at"))
    if tier:
        matched = [row for row in matched if str(row.get("source_tier") or row.get("evidence_tier") or "").lower() == tier.lower()]
    return _json_cached(lambda: _rows_to_wrappers(matched, source_id="csv:sentiment_signals", source_tier="sentiment", collected_at=_file_collected_at(path), lineage=lineage, stale_after_hours=24.0))


def get_sentiment(start: Any = None, end: Any = None, tier: str | None = None, **kwargs: Any) -> list[dict[str, Any]]:
    if start is None and "date" in kwargs:
        start = kwargs.get("date")
    if end is None:
        end = start
    lineage = {"reader": "get_sentiment", "filters": {"start": start, "end": end, "tier": tier, **kwargs}}
    rows = _safe_public("csv:sentiment_signals", lineage, lambda: _get_sentiment_cached(str(start), str(end), tier))
    subject_code = kwargs.get("subject_code")
    if subject_code:
        rows = [row for row in rows if isinstance(row, dict) and isinstance(row.get("data"), dict) and row["data"].get("subject_code") == subject_code]
    return rows


@lru_cache(maxsize=512)
def _get_fundamentals_cached(ts_code: str, end_date: str = "") -> str:
    ts_upper = ts_code.upper()
    if ts_upper.endswith(('.SH', '.SZ', '.BJ')):
        try:
            import sys
            ashare_tools = str(ASHARE_ROOT / "tools")
            if ashare_tools not in sys.path:
                sys.path.insert(0, ashare_tools)
            from a_share_tushare_api import _call as tushare_call
            ed = end_date or _now().strftime("%Y%m%d")
            rows = tushare_call('fina_indicator', {'ts_code': ts_code, 'start_date': '20250101', 'end_date': ed})
            lineage = {"reader": "get_fundamentals", "source": "tushare:fina_indicator", "filters": {"ts_code": ts_code, "start_date": "20250101", "end_date": ed}}
            return _json_cached(lambda: _rows_to_wrappers(rows or [], source_id="tushare:fina_indicator", source_tier="tushare", lineage=lineage, stale_after_hours=168.0))
        except Exception as exc:
            lineage = {"reader": "get_fundamentals", "filters": {"ts_code": ts_code}}
            return _json_cached(lambda: _degraded_empty("tushare:fina_indicator", f"Tushare fina_indicator failed: {exc}", lineage=lineage))
    query = """
        SELECT * FROM market_factors
        WHERE symbol = ?
        ORDER BY event_time DESC, collected_at DESC
    """
    rows, degraded = _sqlite_rows(query, (ts_code,), "market_factors")
    if degraded is not None:
        return _json_cached(lambda: degraded)
    lineage = {"reader": "get_fundamentals", "db_path": str(SQLITE_PATH), "table": "market_factors", "filters": {"ts_code": ts_code}}
    return _json_cached(lambda: _rows_to_wrappers(rows or [], source_id="sqlite:market_factors", source_tier="marketdata", lineage=lineage, stale_after_hours=168.0))


def get_fundamentals(ts_code: str, end_date: str | None = None) -> list[dict[str, Any]]:
    lineage = {"reader": "get_fundamentals", "filters": {"ts_code": ts_code}}
    ed = end_date or _now().strftime("%Y%m%d")
    return _safe_public("sqlite:market_factors", lineage, lambda: _get_fundamentals_cached(str(ts_code), ed))


@lru_cache(maxsize=512)
def _get_capital_flow_cached(date_value: str, ts_code: str | None) -> str:
    date_key = _date_key(date_value)
    path = MONEYFLOW_ROOT / f"{date_key}.csv"
    lineage = {"reader": "get_capital_flow", "source_path": str(path), "filters": {"date": date_key, "ts_code": ts_code}}
    rows, degraded = _safe_csv(path, "csv:moneyflow", lineage)
    if degraded is not None:
        return _json_cached(lambda: degraded)
    matched = rows or []
    if ts_code:
        matched = [row for row in matched if row.get("ts_code") == ts_code]
    return _json_cached(lambda: _rows_to_wrappers(matched, source_id="csv:moneyflow", source_tier="tushare", collected_at=_file_collected_at(path), lineage=lineage, stale_after_hours=48.0))


def get_capital_flow(date: Any = None, ts_code: str | None = None, **kwargs: Any) -> list[dict[str, Any]]:
    if date is None and "trade_date" in kwargs:
        date = kwargs.get("trade_date")
    if ts_code is None and kwargs.get("symbol"):
        ts_code = kwargs.get("symbol")
    lookback_days = max(int(kwargs.get("lookback_days", kwargs.get("window", 1)) or 1), 1)
    if lookback_days <= 1:
        lineage = {"reader": "get_capital_flow", "filters": {"date": date, "ts_code": ts_code, **kwargs}}
        return _safe_public("csv:moneyflow", lineage, lambda: _get_capital_flow_cached(str(date), ts_code))

    merged: list[dict[str, Any]] = []
    base = _parse_datetime(date)
    if base is None:
        return _degraded_empty("csv:moneyflow", f"invalid date: {date}", lineage={"reader": "get_capital_flow", "filters": {"date": date, "ts_code": ts_code, **kwargs}})
    for offset in range(lookback_days):
        day = (base - timedelta(days=offset)).strftime("%Y%m%d")
        merged.extend(_safe_public("csv:moneyflow", {"reader": "get_capital_flow", "filters": {"date": day, "ts_code": ts_code, **kwargs}}, lambda day=day: _get_capital_flow_cached(day, ts_code)))
    return merged


@lru_cache(maxsize=512)
def _get_macro_factors_cached(start: str, end: str) -> str:
    path = MACRO_FACTORS_PATH
    lineage = {"reader": "get_macro_factors", "source_path": str(path), "filters": {"start": start, "end": end}}
    rows, degraded = _safe_csv(path, "csv:macro_factors", lineage)
    if degraded is not None:
        return _json_cached(lambda: degraded)
    matched = _filter_date_range(rows or [], start, end, ("last_updated",))
    return _json_cached(lambda: _rows_to_wrappers(matched, source_id="csv:macro_factors", source_tier="macro", collected_at=_file_collected_at(path), lineage=lineage, stale_after_hours=168.0))


def get_macro_factors(start: Any = None, end: Any = None, **kwargs: Any) -> list[dict[str, Any]]:
    if start is None and "date" in kwargs:
        start = kwargs.get("date")
    if end is None:
        end = start
    if "date" in kwargs:
        path = SHAREDSIGNALS_ROOT / "data" / "all_weather_regime.csv"
        lineage = {"reader": "get_macro_factors", "filters": {"start": start, "end": end, **kwargs}, "compat_mode": "all_weather_regime"}
        rows, degraded = _safe_csv(path, "csv:all_weather_regime", lineage)
        if degraded is not None:
            return degraded
        return _legacy_wrapped_rows(rows or [], source_id="csv:all_weather_regime", source_tier="macro", collected_at=_file_collected_at(path), lineage=lineage, stale_after_hours=168.0)
    lineage = {"reader": "get_macro_factors", "filters": {"start": start, "end": end, **kwargs}}
    return _safe_public("csv:macro_factors", lineage, lambda: _get_macro_factors_cached(str(start), str(end)))


@lru_cache(maxsize=512)
def _get_crypto_klines_cached(symbol: str, limit: int) -> str:
    path = CRYPTO_KLINES_PATH
    lineage = {"reader": "get_crypto_klines", "source_path": str(path), "filters": {"symbol": symbol, "limit": limit}}
    rows, degraded = _safe_csv(path, "csv:crypto_klines", lineage)
    if degraded is not None:
        return _json_cached(lambda: degraded)
    matched = [row for row in (rows or []) if str(row.get("symbol", "")).upper() == symbol.upper()]
    matched.sort(key=lambda row: str(row.get("open_time") or ""))
    if limit > 0:
        matched = matched[-limit:]
    return _json_cached(lambda: _rows_to_wrappers(matched, source_id="csv:crypto_klines", source_tier="binance", collected_at=_file_collected_at(path), lineage=lineage, stale_after_hours=24.0))


def get_crypto_klines(symbol: str, limit: int = 50) -> list[dict[str, Any]]:
    lineage = {"reader": "get_crypto_klines", "filters": {"symbol": symbol, "limit": limit}}
    return _safe_public("csv:crypto_klines", lineage, lambda: _get_crypto_klines_cached(str(symbol), int(limit)))


@lru_cache(maxsize=512)
def _get_pm_markets_cached(limit: int) -> str:
    query = """
        SELECT * FROM market_pm_markets
        ORDER BY collected_at DESC, volume DESC
        LIMIT ?
    """
    rows, degraded = _sqlite_rows(query, (int(limit),), "market_pm_markets")
    if degraded is not None:
        return _json_cached(lambda: degraded)
    lineage = {"reader": "get_pm_markets", "db_path": str(SQLITE_PATH), "table": "market_pm_markets", "filters": {"limit": limit}}
    return _json_cached(lambda: _rows_to_wrappers(rows or [], source_id="sqlite:market_pm_markets", source_tier="polymarket", lineage=lineage, stale_after_hours=24.0))


def get_pm_markets(limit: int = 100) -> list[dict[str, Any]]:
    lineage = {"reader": "get_pm_markets", "filters": {"limit": limit}}
    return _safe_public("sqlite:market_pm_markets", lineage, lambda: _get_pm_markets_cached(int(limit)))


def _safe_reference_path(table: str) -> Path | None:
    name = table.strip()
    if not name:
        return None
    if name.endswith(".csv"):
        name = name[:-4]
    if "/" in name or "\\" in name or name in {".", ".."}:
        return None
    path = (REFERENCE_ROOT / f"{name}.csv").resolve()
    try:
        path.relative_to(REFERENCE_ROOT.resolve())
    except ValueError:
        return None
    return path


@lru_cache(maxsize=512)
def _get_reference_cached(table: str) -> str:
    path = _safe_reference_path(table)
    lineage = {"reader": "get_reference", "reference_root": str(REFERENCE_ROOT), "filters": {"table": table}}
    if path is None:
        return _json_cached(lambda: _degraded_empty("csv:reference", f"invalid reference table: {table}", lineage=lineage))
    lineage["source_path"] = str(path)
    rows, degraded = _safe_csv(path, f"csv:reference:{path.stem}", lineage)
    if degraded is not None:
        return _json_cached(lambda: degraded)
    return _json_cached(lambda: _rows_to_wrappers(rows or [], source_id=f"csv:reference:{path.stem}", source_tier="reference", collected_at=_file_collected_at(path), lineage=lineage, stale_after_hours=720.0))


def get_reference(table: str) -> list[dict[str, Any]]:
    lineage = {"reader": "get_reference", "filters": {"table": table}}
    return _safe_public("csv:reference", lineage, lambda: _get_reference_cached(str(table)))


@lru_cache(maxsize=512)
def _is_trading_day_cached(date_value: str) -> str:
    lineage = {"reader": "is_trading_day", "source_path": str(REFERENCE_ROOT / "market_calendar.py"), "filters": {"date": date_value}}
    try:
        import sys

        ref = str(REFERENCE_ROOT)
        if ref not in sys.path:
            sys.path.insert(0, ref)
        from market_calendar import is_trading_day as calendar_is_trading_day  # type: ignore

        result = bool(calendar_is_trading_day(date_value))
        data = {"date": _date_key(date_value), "is_trading_day": result}
        return _json_cached(lambda: [_wrap(data, source_id="reference:market_calendar", source_tier="calendar", collected_at=_now_iso(), lineage=lineage, stale_after_hours=24.0)])
    except Exception as exc:  # pragma: no cover - defensive reader boundary
        return _json_cached(lambda: _degraded_empty("reference:market_calendar", f"calendar read failed: {exc}", lineage=lineage))


def is_trading_day(date: Any) -> list[dict[str, Any]]:
    lineage = {"reader": "is_trading_day", "filters": {"date": date}}
    return _safe_public("reference:market_calendar", lineage, lambda: _is_trading_day_cached(str(date)))


@lru_cache(maxsize=512)
def _get_realtime_5min_cached(ts_code: str, date_value: str) -> str:
    date_key = _date_key(date_value)
    day_dir = REALTIME_5M_ROOT / date_key
    lineage = {"reader": "get_realtime_5min", "source_path": str(day_dir), "filters": {"ts_code": ts_code, "date": date_key}}
    try:
        if not day_dir.exists():
            return _json_cached(lambda: _degraded_empty("csv:rt_min_5m", f"missing directory: {day_dir}", lineage=lineage))
        matched: list[dict[str, Any]] = []
        for path in sorted(day_dir.glob("*.csv")):
            rows = _read_csv(path)
            for row in rows:
                if row.get("ts_code") == ts_code:
                    row["_source_file"] = str(path)
                    matched.append(row)
        matched.sort(key=lambda row: str(row.get("time") or ""))
        return _json_cached(lambda: _rows_to_wrappers(matched, source_id="csv:rt_min_5m", source_tier="tushare", collected_at=_file_collected_at(day_dir), lineage=lineage, stale_after_hours=2.0))
    except Exception as exc:  # pragma: no cover - defensive reader boundary
        return _json_cached(lambda: _degraded_empty("csv:rt_min_5m", f"realtime read failed: {exc}", lineage=lineage))


def get_realtime_5min(ts_code: str, date: Any) -> list[dict[str, Any]]:
    lineage = {"reader": "get_realtime_5min", "filters": {"ts_code": ts_code, "date": date}}
    return _safe_public("csv:rt_min_5m", lineage, lambda: _get_realtime_5min_cached(str(ts_code), str(date)))


def _summary(name: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    degraded = sum(1 for row in rows if row.get("degraded"))
    first = rows[0] if rows else {}
    return {
        "name": name,
        "rows": len(rows),
        "degraded_rows": degraded,
        "first_data_keys": sorted((first.get("data") or {}).keys())[:8],
        "first_reason": (first.get("lineage") or {}).get("reason"),
    }


def _self_test() -> list[dict[str, Any]]:
    checks = [
        ("market_data", lambda: get_market_data("000001.SZ", "20260626", "20260629")[:3]),
        ("events", lambda: get_events("20260628", "20260629")[:3]),
        ("sentiment", lambda: get_sentiment("20260628", "20260629")[:3]),
        ("fundamentals", lambda: get_fundamentals("BTCUSDT")[:3]),
        ("capital_flow", lambda: get_capital_flow("20260629", "000001.SZ")[:3]),
        ("macro_factors", lambda: get_macro_factors("20260601", "20260630")[:3]),
        ("crypto_klines", lambda: get_crypto_klines("BTCUSDT", 3)),
        ("pm_markets", lambda: get_pm_markets(3)),
        ("reference", lambda: get_reference("stock_master")[:3]),
        ("is_trading_day", lambda: is_trading_day("20260629")),
        ("realtime_5min", lambda: get_realtime_5min("600276.SH", "20260629")[:3]),
    ]
    results = []
    for name, fn in checks:
        try:
            results.append(_summary(name, fn()))
        except Exception as exc:  # pragma: no cover - __main__ guard
            results.append({"name": name, "rows": 0, "degraded_rows": 1, "error": str(exc)})
    wrapped = results
    if as_of and wrapped and not wrapped[0].get("degraded"):
        wrapped = _as_of_filter(wrapped, as_of)
    return wrapped


if __name__ == "__main__":
    print(json.dumps(_self_test(), ensure_ascii=False, indent=2, sort_keys=True))
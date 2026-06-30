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
from threading import Lock
from typing import Any, Callable, Iterable

try:
    import yaml
except ImportError:
    yaml = None


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

# ---- freshness config loader ----
_freshness_config = None
_freshness_config_lock = Lock()

def _load_freshness_config():
    cfg_path = REFERENCE_ROOT / "freshness_config.yaml"
    global _freshness_config
    if _freshness_config is not None:
        return _freshness_config
    with _freshness_config_lock:
        if _freshness_config is not None:
            return _freshness_config
        if yaml is None or not cfg_path.exists():
            _freshness_config = {"sources": {}, "fallback_default_hours": 24.0}
        else:
            try:
                with open(cfg_path, "r") as f:
                    cfg = yaml.safe_load(f) or {}
                _freshness_config = {
                    "sources": cfg.get("sources", {}),
                    "fallback_default_hours": float(cfg.get("fallback_default_hours", 24.0)),
                }
            except Exception:
                _freshness_config = {"sources": {}, "fallback_default_hours": 24.0}
        return _freshness_config

def _freshness_threshold(source_id):
    cfg = _load_freshness_config()
    if source_id and source_id in cfg["sources"]:
        return float(cfg["sources"][source_id].get("stale_after_hours", cfg["fallback_default_hours"]))
    return float(cfg["fallback_default_hours"])

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
STOCK_INDUSTRY_MAP_PATH = Path(os.environ.get("STOCK_INDUSTRY_MAP_PATH", SHAREDSIGNALS_ROOT / "data" / "association" / "stock_industry_map.csv"))
EVENT_SIGNAL_ASSOC_PATH = Path(os.environ.get("EVENT_SIGNAL_ASSOC_PATH", SHAREDSIGNALS_ROOT / "data" / "association" / "event_signal_associations.csv"))
IMPACT_RELATIONS_PATH = Path(os.environ.get("IMPACT_RELATIONS_PATH", SHAREDSIGNALS_ROOT / "data" / "association" / "impact_relations.csv"))
TARGET_STOCK_MAP_PATH = Path(os.environ.get("TARGET_STOCK_MAP_PATH", SHAREDSIGNALS_ROOT / "data" / "association" / "target_stock_map.csv"))

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


def _freshness(collected_at: Any, *, stale_after_hours: float = 24.0, source_id: str | None = None) -> dict[str, Any]:
    age = _age_hours(collected_at)
    if age is None:
        return {"score": 0.0, "stale": True, "age_hours": None}
    """Compute freshness score. Uses configurable threshold from freshness_config.yaml
    when source_id is provided; otherwise falls back to stale_after_hours.
    """
    threshold = stale_after_hours
    if source_id:
        try:
            threshold = _freshness_threshold(source_id)
        except Exception:
            pass
    if age <= threshold:
        score = 1.0
    elif age <= threshold * 3:
        score = 0.7
    elif age <= threshold * 7:
        score = 0.4
    else:
        score = 0.1
    return {"score": score, "stale": age > threshold, "age_hours": round(age, 4)}


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
        "freshness": _freshness(collected, stale_after_hours=stale_after_hours, source_id=source_id),
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

@lru_cache(maxsize=512)
def _get_tushare_cached(api_name: str, ts_code: str | None, start_date: str | None, end_date: str | None, params_json: str) -> str:
    """Route to Tushare API via a_share_tushare_api._call()."""
    try:
        import sys
        ashare_tools = str(ASHARE_ROOT / "tools")
        if ashare_tools not in sys.path:
            sys.path.insert(0, ashare_tools)
        from a_share_tushare_api import _call as tushare_call

        params = json.loads(params_json) if params_json else {}
        if ts_code:
            params["ts_code"] = ts_code
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date

        rows = tushare_call(api_name, params)
        lineage = {
            "reader": "get_tushare",
            "source": f"tushare:{api_name}",
            "filters": {"api_name": api_name, "ts_code": ts_code, "start_date": start_date, "end_date": end_date, **params},
        }
        return _json_cached(lambda: _rows_to_wrappers(
            rows or [],
            source_id=f"tushare:{api_name}",
            source_tier="tushare",
            lineage=lineage,
            stale_after_hours=48.0,
        ))
    except Exception as exc:
        lineage = {"reader": "get_tushare", "filters": {"api_name": api_name, "ts_code": ts_code}}
        return _json_cached(lambda: _degraded_empty(
            f"tushare:{api_name}",
            f"Tushare {api_name} failed: {exc}",
            lineage=lineage,
        ))


def get_tushare(api_name: str, ts_code: str | None = None, start_date: str | None = None, end_date: str | None = None, **params: Any) -> list[dict[str, Any]]:
    """Read Tushare API data through SharedSignals reader, returning metadata-wrapped rows.

    Routes to Tushare API via a_share_tushare_api._call().  Returns the same
    wrapped shape as every other reader function (data / provenance / freshness /
    quality / degraded / lineage).  Results are LRU-cached (maxsize=512).

    Args:
        api_name: Tushare API name, e.g. "daily", "moneyflow", "fina_indicator",
                  "income", "balancesheet", "adj_factor", "margin", "limit_list",
                  "hk_hold", "stock_minutes", "news_list", etc.
        ts_code: Optional stock code; auto-added to params as "ts_code".
        start_date: Optional start date (YYYYMMDD); auto-added as "start_date".
        end_date: Optional end date (YYYYMMDD); auto-added as "end_date".
        **params: Additional Tushare API parameters passed through directly.

    Returns:
        list[dict]: Metadata-wrapped rows with source_id="tushare:{api_name}".
    """
    lineage = {
        "reader": "get_tushare",
        "filters": {"api_name": api_name, "ts_code": ts_code, "start_date": start_date, "end_date": end_date, **params},
    }
    extra = {k: v for k, v in params.items() if k not in ("ts_code", "start_date", "end_date")}
    params_json = json.dumps(extra, sort_keys=True, default=str) if extra else ""
    return _safe_public(
        f"tushare:{api_name}",
        lineage,
        lambda: _get_tushare_cached(str(api_name), ts_code, start_date, end_date, params_json),
    )
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


def get_capital_flow(date: str | None = None, ts_code: str | None = None, **kwargs: Any) -> list[dict[str, Any]]:
    """Get A-share moneyflow data. Wraps Tushare moneyflow API."""
    start = kwargs.get("start_date", date)
    end = kwargs.get("end_date", date)
    if not start and not ts_code:
        from datetime import datetime
        start = datetime.now().strftime("%Y%m%d")
    return get_tushare("moneyflow", ts_code=ts_code, start_date=start, end_date=end or start)

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

@lru_cache(maxsize=512)
def _get_industry_cached(ts_code: str) -> str:
    path = STOCK_INDUSTRY_MAP_PATH
    lineage = {"reader": "get_industry", "source_path": str(path), "filters": {"ts_code": ts_code}}
    rows, degraded = _safe_csv(path, "csv:stock_industry_map", lineage)
    if degraded is not None:
        return _json_cached(lambda: degraded)
    matched = [row for row in (rows or []) if row.get("ts_code") == ts_code]
    return _json_cached(lambda: _rows_to_wrappers(matched, source_id="csv:stock_industry_map", source_tier="reference", collected_at=_file_collected_at(path), lineage=lineage, stale_after_hours=720.0))


def get_industry(ts_code: str) -> list[dict[str, Any]]:
    """Return stock industry / chain / sector / concept info for a given ts_code.

    Reads from MarketGraph stock_industry_map.csv (5,611 stocks).
    Returns degraded empty wrapper if ts_code not found or file missing.
    """
    lineage = {"reader": "get_industry", "filters": {"ts_code": ts_code}}
    return _safe_public("csv:stock_industry_map", lineage, lambda: _get_industry_cached(str(ts_code)))


@lru_cache(maxsize=512)
def _get_associations_cached(ts_code: str, event_id: str) -> str:
    """Build lookup: ts_code -> target_stock_map -> associations, or event_id -> associations."""
    lineage_base = {"reader": "get_associations", "filters": {"ts_code": ts_code, "event_id": event_id}}

    assoc_path = EVENT_SIGNAL_ASSOC_PATH
    assoc_rows, assoc_degraded = _safe_csv(assoc_path, "csv:event_signal_associations", {**lineage_base, "source_path": str(assoc_path)})
    if assoc_degraded is not None:
        return _json_cached(lambda: assoc_degraded)

    tsm_path = TARGET_STOCK_MAP_PATH
    tsm_rows, tsm_degraded = _safe_csv(tsm_path, "csv:target_stock_map", {**lineage_base, "source_path": str(tsm_path)})
    if tsm_degraded is not None:
        return _json_cached(lambda: tsm_degraded)

    if event_id:
        # event_id -> associations where source_reference_id matches
        matched_assoc = [row for row in (assoc_rows or []) if row.get("source_reference_id") == event_id]
        if not matched_assoc:
            return _json_cached(lambda: _degraded_empty("csv:event_signal_associations", f"no associations for event_id={event_id}", lineage=lineage_base))
        # Enrich with ts_codes from target_stock_map
        result: list[dict[str, Any]] = []
        for assoc in matched_assoc:
            target_id = assoc.get("target_id", "")
            tsm_matches = [row for row in (tsm_rows or []) if row.get("target_id") == target_id]
            if tsm_matches:
                for tsm in tsm_matches:
                    merged = dict(assoc)
                    merged["ts_codes"] = tsm.get("ts_codes", "")
                    merged["target_stock_source"] = tsm.get("source", "")
                    result.append(merged)
            else:
                result.append(assoc)
        return _json_cached(lambda: _rows_to_wrappers(result, source_id="csv:event_signal_associations", source_tier="association", collected_at=_file_collected_at(assoc_path), lineage=lineage_base, stale_after_hours=720.0))

    if ts_code:
        # ts_code -> target_stock_map -> targets -> associations
        tsm_matches = [row for row in (tsm_rows or []) if ts_code in str(row.get("ts_codes", "")).split("|")]
        if not tsm_matches:
            return _json_cached(lambda: _degraded_empty("csv:target_stock_map", f"ts_code {ts_code} not found in target_stock_map", lineage=lineage_base))
        target_ids = set(row.get("target_id", "") for row in tsm_matches if row.get("target_id"))
        matched_assoc = [row for row in (assoc_rows or []) if row.get("target_id") in target_ids or row.get("target_id") == ts_code or row.get("subject_id") == ts_code]
        if not matched_assoc:
            return _json_cached(lambda: _degraded_empty("csv:event_signal_associations", f"no associations for ts_code={ts_code}", lineage=lineage_base))
        return _json_cached(lambda: _rows_to_wrappers(matched_assoc, source_id="csv:event_signal_associations", source_tier="association", collected_at=_file_collected_at(assoc_path), lineage=lineage_base, stale_after_hours=720.0))

    # Neither ts_code nor event_id provided -> return all associations
    return _json_cached(lambda: _rows_to_wrappers(assoc_rows or [], source_id="csv:event_signal_associations", source_tier="association", collected_at=_file_collected_at(assoc_path), lineage=lineage_base, stale_after_hours=720.0))


def get_associations(ts_code: str | None = None, event_id: str | None = None) -> list[dict[str, Any]]:
    """Return event<->stock associations.

    If ts_code given: look up via target_stock_map which events affect this stock.
    If event_id given: look up which stocks are affected by this event.
    Returns degraded empty wrapper when nothing found or errors occur.
    """
    lineage = {"reader": "get_associations", "filters": {"ts_code": ts_code, "event_id": event_id}}
    return _safe_public("csv:event_signal_associations", lineage, lambda: _get_associations_cached(str(ts_code or ""), str(event_id or "")))


@lru_cache(maxsize=512)
def _get_impacts_cached(event_type: str, target: str) -> str:
    path = IMPACT_RELATIONS_PATH
    lineage = {"reader": "get_impacts", "source_path": str(path), "filters": {"event_type": event_type, "target": target}}
    rows, degraded = _safe_csv(path, "csv:impact_relations", lineage)
    if degraded is not None:
        return _json_cached(lambda: degraded)
    matched = rows or []
    if event_type:
        matched = [row for row in matched if str(row.get("impact_type", "")).lower() == event_type.lower()]
    if target:
        target_lower = target.lower()
        matched = [row for row in matched if target_lower in str(row.get("target_id", "")).lower() or target_lower in str(row.get("target_name", "")).lower() or target_lower in str(row.get("target_type", "")).lower()]
    return _json_cached(lambda: _rows_to_wrappers(matched, source_id="csv:impact_relations", source_tier="association", collected_at=_file_collected_at(path), lineage=lineage, stale_after_hours=720.0))


def get_impacts(event_type: str | None = None, target: str | None = None) -> list[dict[str, Any]]:
    """Return impact relation edges (31,206 edges).

    Filter by event_type (impact_type column) and/or target (target_id/name/type).
    Returns degraded empty wrapper when nothing found or errors occur.
    """
    lineage = {"reader": "get_impacts", "filters": {"event_type": event_type, "target": target}}
    return _safe_public("csv:impact_relations", lineage, lambda: _get_impacts_cached(str(event_type or ""), str(target or "")))


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
        ("tushare", lambda: get_tushare("daily", ts_code="000001.SZ", start_date="20260626", end_date="20260629")[:3]),
        ("capital_flow", lambda: get_capital_flow("20260629", "000001.SZ")[:3]),
        ("macro_factors", lambda: get_macro_factors("20260601", "20260630")[:3]),
        ("crypto_klines", lambda: get_crypto_klines("BTCUSDT", 3)),
        ("pm_markets", lambda: get_pm_markets(3)),
        ("reference", lambda: get_reference("stock_master")[:3]),
        ("is_trading_day", lambda: is_trading_day("20260629")),
        ("realtime_5min", lambda: get_realtime_5min("600276.SH", "20260629")[:3]),
        ("industry", lambda: get_industry("600519.SH")),
        ("associations", lambda: get_associations(event_id="evt:ee78c0c3ad7b4fbf")[:5]),
        ("impacts", lambda: get_impacts(event_type="liquidity")[:5]),
    ]
    results = []
    for name, fn in checks:
        try:
            results.append(_summary(name, fn()))
        except Exception as exc:  # pragma: no cover - __main__ guard
            results.append({"name": name, "rows": 0, "degraded_rows": 1, "error": str(exc)})
    return results


if __name__ == "__main__":
    print(json.dumps(_self_test(), ensure_ascii=False, indent=2, sort_keys=True))
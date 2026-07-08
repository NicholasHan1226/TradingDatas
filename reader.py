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

import json
import os
import sqlite3
import time
from copy import deepcopy
from collections import OrderedDict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Lock, RLock
from typing import Any, Callable, Iterable

try:
    import yaml
except ImportError:
    yaml = None

import warnings as _warnings
from env_bootstrap import env_float, env_int
from runtime_paths import marketdata_sqlite_path, runtime_root, sharedsignals_root


class _LazyPath:
    """Resolve an environment-backed path only when it is first used."""

    def __init__(self, resolver: Callable[[], Path]):
        self._resolver = resolver
        self._path: Path | None = None

    def get(self) -> Path:
        if self._path is None:
            self._path = Path(self._resolver()).expanduser()
        return self._path

    def __fspath__(self) -> str:
        return os.fspath(self.get())

    def __str__(self) -> str:
        return str(self.get())

    def __repr__(self) -> str:
        return repr(self.get())

    def __truediv__(self, key: str) -> "_LazyPath":
        return _LazyPath(lambda: self.get() / key)

    def __getattr__(self, name: str) -> Any:
        return getattr(self.get(), name)


_env_file = Path(__file__).resolve().parent / ".env"
if _env_file.exists():
    _warnings.warn(
        f"reader.py: .env exists at {_env_file}, but reader no longer loads it "
        "at import time. Call bootstrap_sharedsignals_env() before importing "
        "reader when process-local .env values are required.",
        FutureWarning,
        stacklevel=2,
    )

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

SHAREDSIGNALS_ROOT = _LazyPath(sharedsignals_root)
RUNTIME_ROOT = _LazyPath(runtime_root)
SQLITE_PATH = _LazyPath(marketdata_sqlite_path)
REFERENCE_ROOT = _LazyPath(lambda: Path(os.environ.get("SHAREDSIGNALS_REFERENCE_ROOT") or SHAREDSIGNALS_ROOT.get() / "reference"))

# -- Cache invalidation --------------------------------------------------------

CACHE_TTL_SECONDS = env_float("SHAREDSIGNALS_CACHE_TTL", 300.0, min_value=1.0, max_value=86400.0)
CACHE_MAX_BYTES = env_int("SHAREDSIGNALS_CACHE_MAX_BYTES", 50 * 1024 * 1024, min_value=0)
_CACHE_GENERATION = 0
_CACHE_LAST_RESET = 0.0
_CACHE_TOTAL_BYTES = 0
# Guards cache generation, byte accounting, and per-function cache dictionaries.
_CACHE_LOCK = RLock()

# All cached functions that should be cleared together
_CACHED_FUNCTIONS: list[Callable[..., Any]] = []


def _register_cached(fn: Callable[..., Any]) -> Callable[..., Any]:
    """Register a function for bulk cache clearing."""
    _CACHED_FUNCTIONS.append(fn)
    return fn


def _cache_key(args: tuple[Any, ...], kwargs: dict[str, Any]) -> tuple[Any, ...]:
    if not kwargs:
        return args
    return args + tuple(sorted(kwargs.items()))


def _payload_size_bytes(payload: Any) -> int:
    if isinstance(payload, str):
        return len(payload.encode("utf-8", errors="replace"))
    try:
        return len(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8"))
    except Exception:
        return len(str(payload).encode("utf-8", errors="replace"))


def cache_byte_estimate() -> int:
    """Return the current estimated byte size for all reader caches."""
    with _CACHE_LOCK:
        return int(_CACHE_TOTAL_BYTES)


def _cache_entry_count() -> int:
    with _CACHE_LOCK:
        total = 0
        for fn in _CACHED_FUNCTIONS:
            cache = getattr(fn, "_cache", None)
            if isinstance(cache, OrderedDict):
                total += len(cache)
        return total


def _evict_global_cache_locked() -> None:
    """Evict cached payloads until the shared byte budget is back under limit."""
    global _CACHE_TOTAL_BYTES
    if CACHE_MAX_BYTES <= 0:
        return
    while _CACHE_TOTAL_BYTES > CACHE_MAX_BYTES:
        evicted = False
        for fn in _CACHED_FUNCTIONS:
            cache = getattr(fn, "_cache", None)
            if not isinstance(cache, OrderedDict) or not cache:
                continue
            _, (_, evicted_size) = cache.popitem(last=False)
            _CACHE_TOTAL_BYTES = max(0, _CACHE_TOTAL_BYTES - evicted_size)
            evicted = True
            break
        if not evicted:
            _CACHE_TOTAL_BYTES = 0
            break


def _bounded_lru_cache(
    *,
    maxsize: int = 512,
    should_cache: Callable[[tuple[Any, ...], str], bool] | None = None,
) -> Callable[[Callable[..., str]], Callable[..., str]]:
    """LRU cache for JSON payload strings with shared byte accounting."""

    def decorate(fn: Callable[..., str]) -> Callable[..., str]:
        cache: OrderedDict[tuple[Any, ...], tuple[str, int]] = OrderedDict()

        def cache_clear() -> None:
            global _CACHE_TOTAL_BYTES
            with _CACHE_LOCK:
                for _, size in cache.values():
                    _CACHE_TOTAL_BYTES = max(0, _CACHE_TOTAL_BYTES - size)
                cache.clear()

        def wrapper(*args: Any, **kwargs: Any) -> str:
            global _CACHE_TOTAL_BYTES
            key = _cache_key(args, kwargs)
            with _CACHE_LOCK:
                cached = cache.get(key)
                if cached is not None:
                    value, size = cached
                    cache.move_to_end(key)
                    return value

            value = fn(*args, **kwargs)
            size = _payload_size_bytes(value)
            if maxsize <= 0 or CACHE_MAX_BYTES <= 0 or size > CACHE_MAX_BYTES:
                with _CACHE_LOCK:
                    previous = cache.pop(key, None)
                    if previous is not None:
                        _CACHE_TOTAL_BYTES = max(0, _CACHE_TOTAL_BYTES - previous[1])
                return value
            if should_cache is not None and not should_cache(args, value):
                with _CACHE_LOCK:
                    previous = cache.pop(key, None)
                    if previous is not None:
                        _CACHE_TOTAL_BYTES = max(0, _CACHE_TOTAL_BYTES - previous[1])
                return value

            with _CACHE_LOCK:
                previous = cache.pop(key, None)
                if previous is not None:
                    _CACHE_TOTAL_BYTES = max(0, _CACHE_TOTAL_BYTES - previous[1])
                cache[key] = (value, size)
                _CACHE_TOTAL_BYTES += size

                while len(cache) > maxsize:
                    _, (_, evicted_size) = cache.popitem(last=False)
                    _CACHE_TOTAL_BYTES = max(0, _CACHE_TOTAL_BYTES - evicted_size)
                _evict_global_cache_locked()
            return value

        def cache_info() -> dict[str, Any]:
            with _CACHE_LOCK:
                return {"maxsize": maxsize, "currsize": len(cache)}

        wrapper.cache_clear = cache_clear  # type: ignore[attr-defined]
        wrapper.cache_info = cache_info  # type: ignore[attr-defined]
        wrapper._cache = cache  # type: ignore[attr-defined]
        wrapper.__name__ = fn.__name__
        wrapper.__doc__ = fn.__doc__
        return wrapper

    return decorate


def _resolved_path(pathlike: Any) -> Path:
    return Path(os.fspath(pathlike))


def _sqlite_watch_paths(pathlike: Any) -> list[Path]:
    base = _resolved_path(pathlike)
    return [base, Path(str(base) + "-wal"), Path(str(base) + "-shm")]


def _watched_paths() -> list[Path]:
    """Return paths whose writes invalidate read-side caches.

    SQLite WAL mode can keep fresh writes in ``marketdata.sqlite-wal`` before the
    main database file mtime changes, so the sidecar files are part of the
    fingerprint for 5-minute trading reads.
    """
    return [
        *_sqlite_watch_paths(SQLITE_PATH),
    ]


def _files_changed(last_reset: float) -> bool:
    """Check if any watched path has been modified since last cache reset."""
    # last_reset is a caller-owned snapshot read while holding _CACHE_LOCK.
    if last_reset == 0.0:
        return False
    for path in _watched_paths():
        try:
            if path.exists() and path.stat().st_mtime > last_reset:
                return True
        except OSError:
            continue
    return False


def _maybe_invalidate() -> bool:
    """Invalidate caches if TTL expired or underlying files changed. Returns True if cleared."""
    now = time.time()
    with _CACHE_LOCK:
        last_reset = _CACHE_LAST_RESET
        if last_reset > 0 and now - last_reset < CACHE_TTL_SECONDS and not _files_changed(last_reset):
            return False
        _clear_caches_locked(reset_time=now)
        return True


def _clear_caches_locked(reset_time: float | None = None) -> None:
    """Clear caches while _CACHE_LOCK is already held."""
    global _CACHE_GENERATION, _CACHE_LAST_RESET
    for fn in _CACHED_FUNCTIONS:
        try:
            fn.cache_clear()
        except Exception:
            pass
    _CACHE_GENERATION += 1
    _CACHE_LAST_RESET = reset_time if reset_time is not None else time.time()


def clear_caches() -> None:
    """Clear all LRU caches and reset the cache generation counter."""
    with _CACHE_LOCK:
        _clear_caches_locked()


def _cache_generation_snapshot() -> int:
    with _CACHE_LOCK:
        return _CACHE_GENERATION


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


def _blank_date_value(value: Any) -> bool:
    if value is None:
        return True
    text = str(value).strip()
    return not text or text.lower() in {"none", "null"}


def _optional_date_key(value: Any) -> str | None:
    if _blank_date_value(value):
        return None
    return _date_key(value)


def _canonical_market_key(market: Any) -> str:
    raw = str(market or "Ashare").strip()
    normalized = raw.replace("-", "_").replace(" ", "_").lower()
    aliases = {
        "ashare": "Ashare",
        "a_share": "Ashare",
        "a股": "Ashare",
        "cn": "Ashare",
        "china": "Ashare",
        "china_a": "Ashare",
        "mainland": "Ashare",
        "hk": "HK",
        "hongkong": "HK",
        "hong_kong": "HK",
        "us": "US",
        "usa": "US",
        "united_states": "US",
        "us_market": "US",
        "crypto": "Crypto",
        "cryptos": "Crypto",
        "cryptocurrency": "Crypto",
        "futures": "Futures",
        "future": "Futures",
        "cn_futures": "Futures",
        "cnfutures": "Futures",
        "cn_future": "Futures",
        "cnfuture": "Futures",
        "predictionmarkets": "PredictionMarkets",
        "prediction_markets": "PredictionMarkets",
        "pm": "PredictionMarkets",
        "polymarket": "PredictionMarkets",
    }
    return aliases.get(normalized, raw)


def _market_match_key(market: Any) -> str:
    canonical = _canonical_market_key(market)
    return str(canonical or "").strip().replace("-", "_").replace(" ", "_").lower()


def _file_collected_at(path: Path) -> str | None:
    try:
        st = path.stat()
        # Reject empty files — st_mtime is set at open() time, so a still-writing
        # file could report a stale timestamp while containing only partial data.
        if st.st_size == 0:
            return None
        return datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).isoformat(timespec="seconds")
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
    collected = collected_at or data.get("collected_at")
    if collected is None and (data or not degraded):
        collected = _now_iso()
    return {
        "data": data,
        "provenance": {
            "source_id": source_id,
            "source_tier": source_tier or "unknown",
            "collected_at": str(collected or ""),
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
            degraded=True,
            lineage=details,
        )
    ]


def _safe_public(source_id: str, lineage: dict[str, Any], producer: Callable[[int], str]) -> list[dict[str, Any]]:
    _maybe_invalidate()
    generation_snapshot = _cache_generation_snapshot()
    try:
        return _clone_cached(producer(generation_snapshot))
    except Exception as exc:  # pragma: no cover - final public boundary
        return _degraded_empty(source_id, f"reader failed: {exc}", lineage=lineage)


def _sqlite_rows(query: str, params: tuple[Any, ...], table: str) -> tuple[list[dict[str, Any]] | None, list[dict[str, Any]] | None]:
    lineage = {"reader": "sqlite", "db_path": str(SQLITE_PATH), "table": table}
    try:
        if not SQLITE_PATH.exists():
            return None, _degraded_empty(f"sqlite:{table}", f"missing sqlite db: {SQLITE_PATH}", lineage=lineage)
        conn = sqlite3.connect(f"file:{SQLITE_PATH}?mode=ro", uri=True)
        conn.execute("PRAGMA busy_timeout = 5000")
        conn.row_factory = sqlite3.Row
        try:
            rows = [_clean_row(dict(row)) for row in conn.execute(query, params).fetchall()]
        finally:
            conn.close()
        return rows, None
    except Exception as exc:  # pragma: no cover - defensive reader boundary
        return None, _degraded_empty(f"sqlite:{table}", f"sqlite read failed: {exc}", lineage=lineage)


def _sqlite_rows_by_symbols(table: str, symbols: list[str], limit: int) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, Any]] | None]:
    lineage = {"reader": "sqlite", "db_path": str(SQLITE_PATH), "table": table}
    if not symbols:
        return {}, None
    if table != "market_bars_daily":
        return {}, _degraded_empty(f"sqlite:{table}", f"unsupported batch table: {table}", lineage=lineage)

    deduped_symbols = list(dict.fromkeys(str(symbol).strip() for symbol in symbols if str(symbol).strip()))
    if not deduped_symbols:
        return {}, None
    per_symbol_limit = max(1, int(limit))
    placeholders = ",".join("?" for _ in deduped_symbols)
    query = f"""
        SELECT * FROM (
            SELECT
                *,
                ROW_NUMBER() OVER (PARTITION BY symbol ORDER BY trade_date DESC) AS _row_num
            FROM market_bars_daily
            WHERE symbol IN ({placeholders})
        )
        WHERE _row_num <= ?
        ORDER BY symbol, trade_date DESC
    """
    params: tuple[Any, ...] = (*deduped_symbols, per_symbol_limit)

    rows, degraded = _sqlite_rows(query, params, table)
    if degraded is not None:
        return {}, degraded

    grouped: dict[str, list[dict[str, Any]]] = {symbol: [] for symbol in deduped_symbols}
    for row in rows or []:
        row.pop("_row_num", None)
        symbol = str(row.get("symbol") or "")
        grouped.setdefault(symbol, []).append(row)
    return grouped, None


def _filter_date_range(rows: Iterable[dict[str, Any]], start: Any, end: Any, fields: tuple[str, ...]) -> list[dict[str, Any]]:
    start_key = _optional_date_key(start)
    end_key = _optional_date_key(end)
    if start_key is None and end_key is None:
        return list(rows)
    if start_key is None:
        start_key = end_key
    if end_key is None:
        end_key = start_key
    if start_key is None or end_key is None:
        return []
    if start_key > end_key:
        start_key, end_key = end_key, start_key
    matched: list[dict[str, Any]] = []
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


@_register_cached
@_bounded_lru_cache(maxsize=512)
def _get_market_data_cached(_generation: int, ts_code: str, start: str, end: str, freq: str, adjusted: bool) -> str:
    freq_key = _canonical_market_data_freq(freq)
    market, symbols = _market_symbols_for_code(ts_code)
    if freq_key != "daily":
        return _get_market_intraday_cached(ts_code, start, end, freq_key, adjusted, market, symbols)
    start_key = _date_key(start)
    end_key = _date_key(end)
    if start_key > end_key:
        start_key, end_key = end_key, start_key
    if market == "US":
        base = ts_code[:-3] if ts_code.endswith(".US") else ts_code
        symbols = [base, f"{base}.US"]
        if ts_code.endswith(".US"):
            symbols = [f"{base}.US", base]
    placeholders = ",".join("?" for _ in symbols)
    query = """
        SELECT * FROM market_bars_daily
        WHERE market = ? AND symbol IN ({placeholders}) AND trade_date >= ? AND trade_date <= ?
        ORDER BY trade_date ASC
    """.format(placeholders=placeholders)
    rows, degraded = _sqlite_rows(query, (market, *symbols, start_key, end_key), "market_bars_daily")
    if degraded is not None:
        return _json_cached(lambda: degraded)
    lineage = {
        "reader": "get_market_data",
        "db_path": str(SQLITE_PATH),
        "table": "market_bars_daily",
        "filters": {"ts_code": ts_code, "symbols": symbols, "start": start_key, "end": end_key, "freq": freq, "adjusted": adjusted},
        "adjustment_note": "market_bars_daily has no separate adjustment column; adjusted is preserved as lineage only",
    }
    return _json_cached(lambda: _rows_to_wrappers(rows or [], source_id="sqlite:market_bars_daily", source_tier="marketdata", lineage=lineage, stale_after_hours=48.0))


def _canonical_market_data_freq(freq: Any) -> str:
    value = str(freq or "daily").strip().lower()
    aliases = {
        "d": "daily",
        "day": "daily",
        "1d": "daily",
        "daily": "daily",
        "1m": "1min",
        "1min": "1min",
        "5m": "5min",
        "5min": "5min",
        "15m": "15min",
        "15min": "15min",
        "30m": "30min",
        "30min": "30min",
        "60m": "60min",
        "60min": "60min",
        "1h": "60min",
    }
    return aliases.get(value, value)


def _market_symbols_for_code(ts_code: str) -> tuple[str, list[str]]:
    symbol = str(ts_code or "").strip()
    upper = symbol.upper()
    if upper.endswith((".SH", ".SZ", ".BJ")):
        return "Ashare", [symbol]
    if upper.endswith(".HK"):
        return "HK", [symbol]
    if upper.endswith((".USDT", "USDT", ".USDC", "USDC", ".BUSD", "BUSD")):
        return "Crypto", [upper.replace(".USDT", "USDT").replace(".USDC", "USDC").replace(".BUSD", "BUSD")]
    if "." not in symbol or upper.endswith(".US"):
        base = symbol[:-3] if upper.endswith(".US") else symbol
        return "US", ([f"{base}.US", base] if upper.endswith(".US") else [base, f"{base}.US"])
    return "Crypto", [symbol]


def _get_market_intraday_cached(
    ts_code: str,
    start: str,
    end: str,
    freq: str,
    adjusted: bool,
    market: str,
    symbols: list[str],
) -> str:
    if freq not in {"1min", "5min", "15min", "30min", "60min", "24h_ticker"}:
        return _json_cached(
            lambda: _degraded_empty(
                "sqlite:market_bars_intraday",
                f"unsupported freq: {freq}",
                lineage={"reader": "get_market_data", "freq": freq, "adjusted": adjusted},
            )
        )
    start_key = _optional_date_key(start)
    end_key = _optional_date_key(end)
    if start_key and end_key and start_key > end_key:
        start_key, end_key = end_key, start_key
    placeholders = ",".join("?" for _ in symbols)
    latest_trade_date = None
    if not start_key and not end_key:
        latest_query = f"""
            SELECT MAX(trade_date) AS trade_date
            FROM market_bars_intraday
            WHERE market = ? AND symbol IN ({placeholders}) AND (interval = ? OR interval IS NULL OR interval = '')
        """
        latest_rows, latest_degraded = _sqlite_rows(latest_query, (market, *symbols, freq), "market_bars_intraday")
        if latest_degraded is not None:
            return _json_cached(lambda: latest_degraded)
        latest_trade_date = latest_rows[0].get("trade_date") if latest_rows else None
        if not latest_trade_date:
            return _json_cached(
                lambda: _degraded_empty(
                    "sqlite:market_bars_intraday",
                    f"no intraday trade_date for ts_code={ts_code} freq={freq}",
                    lineage={"reader": "get_market_data", "filters": {"ts_code": ts_code, "freq": freq}},
                )
            )
        start_key = end_key = str(latest_trade_date)

    params: list[Any] = [market, *symbols, freq]
    date_filters = []
    if start_key:
        date_filters.append("trade_date >= ?")
        params.append(start_key)
    if end_key:
        date_filters.append("trade_date <= ?")
        params.append(end_key)
    date_sql = (" AND " + " AND ".join(date_filters)) if date_filters else ""
    query = f"""
        SELECT * FROM market_bars_intraday
        WHERE market = ? AND symbol IN ({placeholders}) AND (interval = ? OR interval IS NULL OR interval = ''){date_sql}
        ORDER BY bar_time ASC
    """
    rows, degraded = _sqlite_rows(query, tuple(params), "market_bars_intraday")
    if degraded is not None:
        return _json_cached(lambda: degraded)
    lineage = {
        "reader": "get_market_data",
        "db_path": str(SQLITE_PATH),
        "table": "market_bars_intraday",
        "filters": {
            "ts_code": ts_code,
            "symbols": symbols,
            "start": start_key,
            "end": end_key,
            "freq": freq,
            "adjusted": adjusted,
        },
        "adjustment_note": "market_bars_intraday has no separate adjustment column; adjusted is preserved as lineage only",
    }
    return _json_cached(lambda: _rows_to_wrappers(rows or [], source_id="sqlite:market_bars_intraday", source_tier="marketdata", lineage=lineage, stale_after_hours=2.0))



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
    return filtered  # return empty if all filtered — avoid look-ahead bias in backtests


def get_market_data(ts_code: str, start: Any = None, end: Any = None, freq: str = "daily", adjusted: bool = True, **kwargs: Any) -> list[dict[str, Any]]:
    lineage = {"reader": "get_market_data", "filters": {"ts_code": ts_code, "start": start, "end": end, "freq": freq, "adjusted": adjusted}}
    return _safe_public("sqlite:market_bars_daily", lineage, lambda generation: _get_market_data_cached(generation, str(ts_code), str(start), str(end), str(freq), bool(adjusted)))


@_register_cached
@_bounded_lru_cache(maxsize=512)
def _get_events_cached(_generation: int, start: str, end: str, event_type: str | None) -> str:
    start_key = _optional_date_key(start)
    end_key = _optional_date_key(end)
    if start_key and end_key and start_key > end_key:
        start_key, end_key = end_key, start_key

    where = ["1=1"]
    params: list[Any] = []
    date_expr = "REPLACE(SUBSTR(COALESCE(NULLIF(trade_date, ''), event_time, collected_at), 1, 10), '-', '')"
    if start_key:
        where.append(f"{date_expr} >= ?")
        params.append(start_key)
    if end_key:
        where.append(f"{date_expr} <= ?")
        params.append(end_key)
    if event_type:
        where.append("LOWER(event_type) = ?")
        params.append(event_type.lower())

    db_lineage = {
        "reader": "get_events",
        "source": "sqlite:market_events",
        "filters": {"start": start, "end": end, "event_type": event_type},
    }
    rows, db_degraded = _sqlite_rows(
        "SELECT * FROM market_events "
        f"WHERE {' AND '.join(where)} "
        "ORDER BY COALESCE(trade_date, event_time, collected_at) DESC LIMIT 5000",
        tuple(params),
        "market_events",
    )
    if db_degraded is None and rows:
        collected_at = max((str(row.get("collected_at") or "") for row in rows), default="") or None
        return _json_cached(
            lambda: _rows_to_wrappers(
                rows,
                source_id="sqlite:market_events",
                source_tier="events",
                collected_at=collected_at,
                lineage=db_lineage,
                stale_after_hours=168.0,
            )
        )

    if db_degraded is not None:
        return _json_cached(lambda: db_degraded)
    return _json_cached(lambda: _degraded_empty("sqlite:market_events", "no rows matched", lineage=db_lineage))


def _event_code_variants(value: Any) -> set[str]:
    raw = str(value or "").strip().upper()
    if not raw:
        return set()
    compact = raw.replace("-", "").replace("_", "")
    variants = {raw, compact}
    if "." in compact:
        base, suffix = compact.split(".", 1)
        variants.update({base, f"{suffix}{base}"})
    elif len(compact) >= 8 and compact[:2] in {"SH", "SZ", "BJ"}:
        base = compact[2:]
        variants.update({base, f"{base}.{compact[:2]}"})
    elif len(compact) == 6 and compact.isdigit():
        if compact.startswith(("5", "6", "9")):
            variants.update({f"{compact}.SH", f"SH{compact}"})
        elif compact.startswith(("0", "1", "2", "3")):
            variants.update({f"{compact}.SZ", f"SZ{compact}"})
        elif compact.startswith(("4", "8")):
            variants.update({f"{compact}.BJ", f"BJ{compact}"})
    return {item for item in variants if item}


def _event_row_matches_code(data: dict[str, Any], wanted: set[str]) -> bool:
    if not wanted:
        return True
    for field in ("subject_code", "ts_code", "symbol", "code", "asset_code"):
        if _event_code_variants(data.get(field)) & wanted:
            return True
    return False


def _event_row_matches_market(data: dict[str, Any], market: Any) -> bool:
    wanted = _market_match_key(market)
    if not wanted:
        return True
    values = [
        data.get("market"),
        data.get("target_market"),
        data.get("market_scope"),
        data.get("subject_market"),
    ]
    for value in values:
        normalized = _market_match_key(value)
        if normalized and normalized == wanted:
            return True
    return False


def get_events(start: Any = None, end: Any = None, event_type: str | None = None, **kwargs: Any) -> list[dict[str, Any]]:
    if start is None and "date" in kwargs:
        start = kwargs.get("date")
    if end is None:
        end = start
    lineage = {"reader": "get_events", "filters": {"start": start, "end": end, "event_type": event_type, **kwargs}}
    rows = _safe_public("sqlite:market_events", lineage, lambda generation: _get_events_cached(generation, str(start), str(end), event_type))
    if rows and all(
        isinstance(row, dict) and bool(row.get("degraded")) and row.get("data") in ({}, None)
        for row in rows
    ):
        return rows
    market = kwargs.get("market")
    symbol = kwargs.get("symbol")
    subject_code = kwargs.get("subject_code") or symbol
    subject_type = kwargs.get("subject_type")
    wanted_codes = _event_code_variants(subject_code)
    if market:
        rows = [
            row for row in rows
            if isinstance(row, dict)
            and isinstance(row.get("data"), dict)
            and _event_row_matches_market(row["data"], market)
        ]
    if wanted_codes:
        rows = [
            row for row in rows
            if isinstance(row, dict)
            and isinstance(row.get("data"), dict)
            and _event_row_matches_code(row["data"], wanted_codes)
        ]
    if subject_type:
        rows = [
            row for row in rows
            if isinstance(row, dict)
            and isinstance(row.get("data"), dict)
            and (
                not row["data"].get("subject_type")
                or str(row["data"].get("subject_type")) == str(subject_type)
            )
        ]
    return rows


@_register_cached
@_bounded_lru_cache(maxsize=512)
def _get_sentiment_cached(_generation: int, start: str, end: str, tier: str | None) -> str:
    start_key = _optional_date_key(start)
    end_key = _optional_date_key(end)
    if start_key and end_key and start_key > end_key:
        start_key, end_key = end_key, start_key
    where = ["LOWER(event_type) = ?"]
    params: list[Any] = ["sentiment"]
    date_expr = "REPLACE(SUBSTR(COALESCE(NULLIF(trade_date, ''), event_time, collected_at), 1, 10), '-', '')"
    if start_key:
        where.append(f"{date_expr} >= ?")
        params.append(start_key)
    if end_key:
        where.append(f"{date_expr} <= ?")
        params.append(end_key)
    lineage = {"reader": "get_sentiment", "source": "sqlite:market_events", "filters": {"start": start, "end": end, "tier": tier}}
    rows, degraded = _sqlite_rows(
        "SELECT * FROM market_events "
        f"WHERE {' AND '.join(where)} "
        "ORDER BY COALESCE(trade_date, event_time, collected_at) DESC LIMIT 5000",
        tuple(params),
        "market_events",
    )
    if degraded is not None:
        return _json_cached(lambda: degraded)
    if tier:
        rows = [row for row in rows or [] if str(row.get("source_tier") or row.get("tier") or "").lower() == tier.lower()]
    return _json_cached(lambda: _rows_to_wrappers(rows or [], source_id="sqlite:market_events", source_tier="sentiment", lineage=lineage, stale_after_hours=48.0))


def get_sentiment(start: Any = None, end: Any = None, tier: str | None = None, **kwargs: Any) -> list[dict[str, Any]]:
    if start is None and "date" in kwargs:
        start = kwargs.get("date")
    if end is None:
        end = start
    lineage = {"reader": "get_sentiment", "filters": {"start": start, "end": end, "tier": tier, **kwargs}}
    rows = _safe_public("sqlite:market_events", lineage, lambda generation: _get_sentiment_cached(generation, str(start), str(end), tier))
    subject_code = kwargs.get("subject_code")
    if subject_code:
        rows = [row for row in rows if isinstance(row, dict) and isinstance(row.get("data"), dict) and row["data"].get("subject_code") == subject_code]
    return rows


@_register_cached
@_bounded_lru_cache(maxsize=512)
def _get_fundamentals_cached(_generation: int, ts_code: str, end_date: str = "") -> str:
    clauses = ["symbol = ?"]
    values: list[Any] = [ts_code]
    if end_date:
        clauses.append("event_time <= ?")
        values.append(end_date)
    query = (
        "SELECT * FROM market_factors "
        f"WHERE {' AND '.join(clauses)} "
        "ORDER BY event_time DESC, collected_at DESC"
    )
    rows, degraded = _sqlite_rows(query, tuple(values), "market_factors")
    if degraded is not None:
        return _json_cached(lambda: degraded)
    lineage = {"reader": "get_fundamentals", "db_path": str(SQLITE_PATH), "table": "market_factors", "filters": {"ts_code": ts_code, "end_date": end_date}}
    if not rows:
        return _json_cached(lambda: _degraded_empty("sqlite:market_factors", f"no fundamentals in SharedSignals read model for {ts_code}", lineage=lineage))
    return _json_cached(lambda: _rows_to_wrappers(rows or [], source_id="sqlite:market_factors", source_tier="marketdata", lineage=lineage, stale_after_hours=168.0))


def get_fundamentals(ts_code: str, end_date: str | None = None) -> list[dict[str, Any]]:
    lineage = {"reader": "get_fundamentals", "filters": {"ts_code": ts_code}}
    ed = end_date or _now().strftime("%Y%m%d")
    return _safe_public("sqlite:market_factors", lineage, lambda generation: _get_fundamentals_cached(generation, str(ts_code), ed))


@_register_cached
@_bounded_lru_cache(maxsize=512)
def _get_tushare_cached(_generation: int, api_name: str, ts_code: str | None, start_date: str | None, end_date: str | None, params_json: str) -> str:
    """Read Tushare-backed data from the SharedSignals read model only."""
    from storage.read_model_store import API_TO_TABLE_MAP
    table = API_TO_TABLE_MAP.get(api_name)
    params = json.loads(params_json) if params_json else {}
    lineage = {"reader": "get_tushare", "source": f"db:{table or 'unmapped'}", "filters": {"api_name": api_name, "ts_code": ts_code, "start_date": start_date, "end_date": end_date, **params}}
    if not table:
        return _json_cached(lambda: _degraded_empty(f"db:tushare:{api_name}", f"Tushare api_name={api_name} is not mapped to a SharedSignals read-model table", lineage=lineage))
    if not SQLITE_PATH.exists():
        return _json_cached(lambda: _degraded_empty(f"db:{table}", f"missing sqlite db: {SQLITE_PATH}", lineage=lineage))
    try:
        import sqlite3
        conn = sqlite3.connect(f"file:{SQLITE_PATH}?mode=ro", uri=True)
        conn.execute("PRAGMA busy_timeout = 5000")
        cols = [row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()]
        code = ts_code or params.get("ts_code", "") or params.get("symbol", "")
        start = start_date or params.get("start_date", "") or params.get("trade_date", "")
        end = end_date or params.get("end_date", "")
        where: list[str] = []
        vals: list[Any] = []
        if code and "symbol" in cols:
            where.append("symbol = ?")
            vals.append(code)
        date_col = "trade_date" if "trade_date" in cols else "event_time" if "event_time" in cols else "updated_at" if "updated_at" in cols else "collected_at" if "collected_at" in cols else ""
        if start and date_col:
            where.append(f"{date_col} >= ?")
            vals.append(start)
        if end and date_col:
            where.append(f"{date_col} <= ?")
            vals.append(end)
        if table == "market_assets" and "market" in cols:
            market_filter = str(params.get("market") or "").strip()
            if not market_filter:
                market_filter = {
                    "stock_basic": "Ashare",
                    "stock_company": "Ashare",
                    "concept": "Ashare",
                    "concept_detail": "Ashare",
                    "hs_const": "Ashare",
                    "trade_cal": "Ashare",
                    "fut_basic": "Futures",
                    "hk_basic": "HK",
                    "us_basic": "US",
                    "etf_basic": "ETF",
                    "fund_basic": "Fund",
                    "fund_nav": "Fund",
                }.get(api_name, "Ashare")
            market_filter = _canonical_market_key(market_filter)
            where.append("market = ?")
            vals.append(market_filter)
        if "provider" in cols:
            if table == "market_assets":
                providers = ["tushare", f"tushare_{api_name}"]
                if api_name == "stock_basic":
                    providers.append("tushare_stock_company")
                placeholders = " OR ".join("provider = ?" for _ in providers)
                where.append(f"({placeholders})")
                vals.extend(providers)
            else:
                where.append("provider = ?")
                vals.append(f"tushare_{api_name}")
        where_sql = " AND ".join(where) if where else "1=1"
        order_col = date_col or cols[0]
        sql = f"SELECT * FROM {table} WHERE {where_sql} ORDER BY {order_col} DESC LIMIT 5000"
        rows_raw = conn.execute(sql, vals).fetchall()
        conn.close()
        if rows_raw:
            rows = [dict(zip(cols, row)) for row in rows_raw]
            return _json_cached(lambda: _rows_to_wrappers(rows, source_id=f"db:{table}", source_tier="collector", lineage=lineage, stale_after_hours=48.0))
        return _json_cached(lambda: _degraded_empty(f"db:{table}", f"no rows in SharedSignals read model for Tushare api_name={api_name}", lineage=lineage))
    except Exception as exc:
        return _json_cached(lambda: _degraded_empty(f"db:{table}", f"read-model lookup failed for Tushare api_name={api_name}: {exc}", lineage=lineage))


def get_tushare(api_name: str, ts_code: str | None = None, start_date: str | None = None, end_date: str | None = None, **params: Any) -> list[dict[str, Any]]:
    """Read Tushare API data through SharedSignals reader, returning metadata-wrapped rows.

    Reads from the SharedSignals read-model tables populated by collectors. It
    never calls the live Tushare provider path from the HTTP API layer. Results
    are LRU-cached (maxsize=512).

    Args:
        api_name: Tushare API name, e.g. "daily", "moneyflow", "fina_indicator",
                  "income", "balancesheet", "adj_factor", "margin", "limit_list",
                  "stk_mins", "news", "major_news", "cctv_news", "anns_d", etc.
        ts_code: Optional stock code; auto-added to params as "ts_code".
        start_date: Optional start date (YYYYMMDD); auto-added as "start_date".
        end_date: Optional end date (YYYYMMDD); auto-added as "end_date".
        **params: Additional filters used only for read-model lookup.

    Returns:
        list[dict]: Metadata-wrapped rows with source_id="db:{table}" or a degraded wrapper if the collector has not populated the table.
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
        lambda generation: _get_tushare_cached(generation, str(api_name), ts_code, start_date, end_date, params_json),
    )
def get_capital_flow(date: str | None = None, ts_code: str | None = None, **kwargs: Any) -> list[dict[str, Any]]:
    """Get A-share moneyflow rows from the SharedSignals read model."""
    start = kwargs.get("start_date", date)
    end = kwargs.get("end_date", date)
    if not start and not ts_code:
        from datetime import datetime
        start = datetime.now().strftime("%Y%m%d")
    return get_tushare("moneyflow", ts_code=ts_code, start_date=start, end_date=end or start)

@_register_cached
@_bounded_lru_cache(maxsize=512)
def _get_macro_factors_cached(_generation: int, start: str, end: str) -> str:
    start_key = _optional_date_key(start)
    end_key = _optional_date_key(end)
    if start_key and end_key and start_key > end_key:
        start_key, end_key = end_key, start_key
    where = [
        "("
        "market IN ('Macro', 'Global', 'Rates', 'FX', 'Commodity') "
        "OR provider IN ("
        "'tushare_cn_cpi','tushare_cn_pmi','tushare_cn_m','tushare_cn_ppi','tushare_cn_gdp',"
        "'tushare_sf_month','tushare_shibor','tushare_shibor_lpr','tushare_us_tycr','tushare_us_tbr','tushare_us_tltr',"
        "'tushare_repo_daily'"
        ")"
        ")"
    ]
    params: list[Any] = []
    if start_key:
        where.append("REPLACE(SUBSTR(event_time, 1, 10), '-', '') >= ?")
        params.append(start_key)
    if end_key:
        where.append("REPLACE(SUBSTR(event_time, 1, 10), '-', '') <= ?")
        params.append(end_key)
    lineage = {"reader": "get_macro_factors", "source": "sqlite:market_factors", "filters": {"start": start, "end": end}}
    rows, degraded = _sqlite_rows(
        "SELECT * FROM market_factors "
        f"WHERE {' AND '.join(where)} "
        "ORDER BY event_time DESC, collected_at DESC LIMIT 5000",
        tuple(params),
        "market_factors",
    )
    if degraded is not None:
        return _json_cached(lambda: degraded)
    return _json_cached(lambda: _rows_to_wrappers(rows or [], source_id="sqlite:market_factors", source_tier="macro", lineage=lineage, stale_after_hours=168.0))


def get_macro_factors(start: Any = None, end: Any = None, **kwargs: Any) -> list[dict[str, Any]]:
    if start is None and "date" in kwargs:
        start = kwargs.get("date")
    if end is None:
        end = start
    lineage = {"reader": "get_macro_factors", "filters": {"start": start, "end": end, **kwargs}}
    return _safe_public("sqlite:market_factors", lineage, lambda generation: _get_macro_factors_cached(generation, str(start), str(end)))


@_register_cached
@_bounded_lru_cache(maxsize=512)
def _get_crypto_klines_cached(_generation: int, symbol: str, limit: int) -> str:
    query = """
        SELECT * FROM market_bars_intraday
        WHERE market = 'Crypto' AND symbol = ?
        ORDER BY bar_time DESC, collected_at DESC
        LIMIT ?
    """
    lineage = {"reader": "get_crypto_klines", "source": "sqlite:market_bars_intraday", "filters": {"symbol": symbol, "limit": limit}}
    rows, degraded = _sqlite_rows(query, (symbol.upper(), max(1, int(limit))), "market_bars_intraday")
    if degraded is not None:
        return _json_cached(lambda: degraded)
    if rows:
        rows = list(reversed(rows))
        return _json_cached(lambda: _rows_to_wrappers(rows, source_id="sqlite:market_bars_intraday", source_tier="binance", lineage=lineage, stale_after_hours=1.0))

    daily_query = """
        SELECT * FROM market_bars_daily
        WHERE market = 'Crypto' AND symbol = ?
        ORDER BY trade_date DESC, collected_at DESC
        LIMIT ?
    """
    daily_lineage = {"reader": "get_crypto_klines", "source": "sqlite:market_bars_daily", "filters": {"symbol": symbol, "limit": limit}}
    daily_rows, daily_degraded = _sqlite_rows(daily_query, (symbol.upper(), max(1, int(limit))), "market_bars_daily")
    if daily_degraded is not None:
        return _json_cached(lambda: daily_degraded)
    daily_rows = list(reversed(daily_rows or []))
    return _json_cached(lambda: _rows_to_wrappers(daily_rows, source_id="sqlite:market_bars_daily", source_tier="binance", lineage=daily_lineage, stale_after_hours=24.0))


def get_crypto_klines(symbol: str, limit: int = 50) -> list[dict[str, Any]]:
    lineage = {"reader": "get_crypto_klines", "filters": {"symbol": symbol, "limit": limit}}
    return _safe_public("sqlite:market_bars_intraday", lineage, lambda generation: _get_crypto_klines_cached(generation, str(symbol), int(limit)))


@_register_cached
@_bounded_lru_cache(maxsize=512)
def _get_pm_markets_cached(_generation: int, limit: int) -> str:
    query = """
        SELECT
            m.*,
            lp.price AS latest_price,
            lp.price AS price,
            lp.price_time AS latest_price_time,
            lp.token_id AS latest_token_id
        FROM market_pm_markets m
        LEFT JOIN market_pm_prices lp ON lp.price_hash = (
            SELECT p.price_hash
            FROM market_pm_prices p
            WHERE p.market_id = m.market_id
            ORDER BY p.price_time DESC, p.collected_at DESC, p.price DESC
            LIMIT 1
        )
        ORDER BY
            CASE WHEN lp.price IS NULL THEN 1 ELSE 0 END,
            lp.price_time DESC,
            m.collected_at DESC,
            m.volume DESC
        LIMIT ?
    """
    rows, degraded = _sqlite_rows(query, (int(limit),), "market_pm_markets")
    if degraded is not None:
        return _json_cached(lambda: degraded)
    lineage = {"reader": "get_pm_markets", "db_path": str(SQLITE_PATH), "table": "market_pm_markets+market_pm_prices", "filters": {"limit": limit}}
    return _json_cached(lambda: _rows_to_wrappers(rows or [], source_id="sqlite:market_pm_markets", source_tier="polymarket", lineage=lineage, stale_after_hours=24.0))


def get_pm_markets(limit: int = 100) -> list[dict[str, Any]]:
    lineage = {"reader": "get_pm_markets", "filters": {"limit": limit}}
    return _safe_public("sqlite:market_pm_markets", lineage, lambda generation: _get_pm_markets_cached(generation, int(limit)))


@_register_cached
@_bounded_lru_cache(maxsize=512)
def _get_pm_prices_cached(_generation: int, market_id: str, limit: int) -> str:
    bounded_limit = max(1, min(int(limit), 1000))
    normalized_market_id = str(market_id or "").strip()
    if normalized_market_id:
        query = """
            SELECT *
            FROM market_pm_prices
            WHERE market_id = ?
            ORDER BY price_time DESC, collected_at DESC, price_hash DESC
            LIMIT ?
        """
        params: tuple[Any, ...] = (normalized_market_id, bounded_limit)
    else:
        query = """
            SELECT *
            FROM market_pm_prices
            ORDER BY rowid DESC
            LIMIT ?
        """
        params = (bounded_limit,)
    rows, degraded = _sqlite_rows(query, params, "market_pm_prices")
    if degraded is not None:
        return _json_cached(lambda: degraded)
    lineage = {
        "reader": "get_pm_prices",
        "db_path": str(SQLITE_PATH),
        "table": "market_pm_prices",
        "filters": {"market_id": normalized_market_id, "limit": bounded_limit},
    }
    return _json_cached(
        lambda: _rows_to_wrappers(
            rows or [],
            source_id="sqlite:market_pm_prices",
            source_tier="polymarket",
            lineage=lineage,
            stale_after_hours=2.0,
        )
    )


def get_pm_prices(market_id: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
    normalized_market_id = str(market_id or "").strip()
    lineage = {"reader": "get_pm_prices", "filters": {"market_id": normalized_market_id, "limit": limit}}
    return _safe_public(
        "sqlite:market_pm_prices",
        lineage,
        lambda generation: _get_pm_prices_cached(generation, normalized_market_id, int(limit)),
    )


@_register_cached
@_bounded_lru_cache(maxsize=512)
def _get_reference_cached(_generation: int, table: str) -> str:
    lineage = {"reader": "get_reference", "filters": {"table": table}}
    return _json_cached(
        lambda: _degraded_empty(
            "sqlite:reference",
            "reference CSV endpoints are retired; use explicit read-model tables or /tushare",
            lineage=lineage,
        )
    )


def get_reference(table: str) -> list[dict[str, Any]]:
    lineage = {"reader": "get_reference", "filters": {"table": table}}
    return _safe_public("sqlite:reference", lineage, lambda generation: _get_reference_cached(generation, str(table)))


@_register_cached
@_bounded_lru_cache(maxsize=512)
def _is_trading_day_cached(_generation: int, date_value: str) -> str:
    date_key = _date_key(date_value)
    lineage = {"reader": "is_trading_day", "source": "sqlite:market_bars_daily", "filters": {"date": date_key}}
    rows, degraded = _sqlite_rows(
        "SELECT 1 AS is_trading_day FROM market_bars_daily WHERE market = ? AND trade_date = ? LIMIT 1",
        ("Ashare", date_key),
        "market_bars_daily",
    )
    if degraded is not None:
        return _json_cached(lambda: degraded)
    if rows:
        data = {"date": date_key, "is_trading_day": True, "calendar_method": "read_model_daily_bar"}
        return _json_cached(lambda: [_wrap(data, source_id="sqlite:market_bars_daily", source_tier="calendar", collected_at=_now_iso(), lineage=lineage, stale_after_hours=24.0)])

    latest_rows, latest_degraded = _sqlite_rows(
        "SELECT MAX(trade_date) AS latest_trade_date FROM market_bars_daily WHERE market = ?",
        ("Ashare",),
        "market_bars_daily",
    )
    latest = ""
    if latest_degraded is None and latest_rows:
        latest = str(latest_rows[0].get("latest_trade_date") or "")
    weekday = datetime.strptime(date_key, "%Y%m%d").weekday()
    if latest and date_key <= latest:
        result = False
        method = "read_model_gap_before_latest"
    else:
        result = weekday < 5
        method = "weekday_fallback_after_latest_read_model"
    data = {"date": date_key, "is_trading_day": result, "calendar_method": method, "latest_trade_date": latest}
    return _json_cached(lambda: [_wrap(data, source_id="sqlite:market_bars_daily", source_tier="calendar", collected_at=_now_iso(), lineage=lineage, stale_after_hours=24.0)])


def is_trading_day(date: Any) -> list[dict[str, Any]]:
    lineage = {"reader": "is_trading_day", "filters": {"date": date}}
    return _safe_public("reference:market_calendar", lineage, lambda generation: _is_trading_day_cached(generation, str(date)))


@_register_cached
@_bounded_lru_cache(maxsize=512)
def _get_realtime_5min_cached(_generation: int, market: str, ts_code: str, date_value: str) -> str:
    market_key = _canonical_market_key(market)
    symbol_key = str(ts_code or "").strip()
    date_key = _optional_date_key(date_value)
    if date_key is None:
        if symbol_key:
            latest_query = "SELECT MAX(trade_date) AS trade_date FROM market_bars_intraday WHERE market = ? AND symbol = ?"
            latest_params: tuple[Any, ...] = (market_key, symbol_key)
        else:
            latest_query = "SELECT MAX(trade_date) AS trade_date FROM market_bars_intraday WHERE market = ?"
            latest_params = (market_key,)
        latest_rows, latest_degraded = _sqlite_rows(latest_query, latest_params, "market_bars_intraday")
        if latest_degraded is not None:
            return _json_cached(lambda: latest_degraded)
        latest = latest_rows[0].get("trade_date") if latest_rows else None
        date_key = _optional_date_key(latest)
        if date_key is None:
            lineage = {"reader": "get_realtime_5min", "source": "sqlite:market_bars_intraday", "filters": {"market": market_key, "ts_code": symbol_key, "date": None}}
            return _json_cached(lambda: _degraded_empty("sqlite:market_bars_intraday", f"no intraday trade_date for market={market_key} ts_code={symbol_key or '*'}", lineage=lineage))
    lineage = {"reader": "get_realtime_5min", "source": "sqlite:market_bars_intraday", "filters": {"market": market_key, "ts_code": symbol_key, "date": date_key}}
    if symbol_key:
        query = (
            "SELECT * FROM market_bars_intraday "
            "WHERE market = ? AND symbol = ? AND trade_date = ? "
            "AND (interval = ? OR interval = ? OR interval IS NULL OR interval = '') "
            "ORDER BY bar_time ASC LIMIT 5000"
        )
        params: tuple[Any, ...] = (market_key, symbol_key, date_key, "5min", "5m")
    else:
        query = (
            "WITH scoped AS ("
            "SELECT * FROM market_bars_intraday "
            "WHERE market = ? AND trade_date = ? "
            "AND (interval = ? OR interval = ? OR interval IS NULL OR interval = '')"
            "), latest AS (SELECT MAX(COALESCE(bar_time, '')) AS latest_bar_time FROM scoped) "
            "SELECT scoped.* FROM scoped, latest "
            "WHERE COALESCE(scoped.bar_time, '') = latest.latest_bar_time "
            "ORDER BY scoped.symbol ASC LIMIT 5000"
        )
        params = (market_key, date_key, "5min", "5m")
    rows, degraded = _sqlite_rows(query, params, "market_bars_intraday")
    if degraded is None and rows:
        collected_at = max((str(row.get("collected_at") or "") for row in rows), default="") or None
        return _json_cached(lambda: _rows_to_wrappers(rows, source_id="sqlite:market_bars_intraday", source_tier="marketdata", collected_at=collected_at, lineage=lineage, stale_after_hours=48.0))

    reason = f"no rows in sqlite market_bars_intraday for market={market_key} ts_code={symbol_key or '*'}"
    if degraded is not None:
        reason = f"sqlite degraded for market={market_key} ts_code={symbol_key or '*'}"
    return _json_cached(lambda: _degraded_empty("sqlite:market_bars_intraday", reason, lineage=lineage))


def get_realtime_5min(ts_code: str = "", date: Any = None, market: str = "Ashare") -> list[dict[str, Any]]:
    market_key = _canonical_market_key(market)
    lineage = {"reader": "get_realtime_5min", "filters": {"market": market_key, "ts_code": ts_code, "date": date}}
    return _safe_public("sqlite:market_bars_intraday", lineage, lambda generation: _get_realtime_5min_cached(generation, market_key, str(ts_code), str(date)))

@_register_cached
@_bounded_lru_cache(maxsize=512)
def _get_industry_cached(_generation: int, ts_code: str) -> str:
    db_lineage = {"reader": "get_industry", "source": "sqlite:market_assets", "filters": {"ts_code": ts_code}}
    asset_rows, asset_degraded = _sqlite_rows(
        "SELECT market, symbol, symbol AS ts_code, name, asset_type, exchange, "
        "sector, sector AS industry, sector AS sw_l1_name, "
        "list_date, status, provider, source_file, updated_at, raw_json "
        "FROM market_assets WHERE market = ? AND symbol = ? LIMIT 1",
        ("Ashare", ts_code),
        "market_assets",
    )
    if asset_degraded is not None:
        return _json_cached(lambda: asset_degraded)
    if asset_rows:
        collected_at = max((str(row.get("updated_at") or row.get("collected_at") or "") for row in asset_rows), default="") or None
        return _json_cached(lambda: _rows_to_wrappers(asset_rows, source_id="sqlite:market_assets", source_tier="reference", collected_at=collected_at, lineage=db_lineage, stale_after_hours=720.0))
    return _json_cached(lambda: _degraded_empty("sqlite:market_assets", f"no industry rows matched for {ts_code}", lineage=db_lineage))


def get_industry(ts_code: str) -> list[dict[str, Any]]:
    """Return stock industry / chain / sector / concept info for a given ts_code.

    Reads only from the SharedSignals SQLite read model.
    Returns degraded empty wrapper if ts_code is not present in market_assets.
    """
    lineage = {"reader": "get_industry", "filters": {"ts_code": ts_code}}
    return _safe_public("sqlite:market_assets", lineage, lambda generation: _get_industry_cached(generation, str(ts_code)))


@_register_cached
@_bounded_lru_cache(maxsize=64, should_cache=lambda args, _value: bool(args[1] or args[2]))
def _get_associations_cached(_generation: int, ts_code: str, event_id: str) -> str:
    lineage_base = {"reader": "get_associations", "filters": {"ts_code": ts_code, "event_id": event_id}}
    return _json_cached(
        lambda: _degraded_empty(
            "marketgraph:associations_api",
            "association CSV reads are retired; consume MarketGraph public API",
            lineage=lineage_base,
        )
    )


def get_associations(ts_code: str | None = None, event_id: str | None = None) -> list[dict[str, Any]]:
    """Return event<->stock associations.

    If ts_code given: look up via target_stock_map which events affect this stock.
    If event_id given: look up which stocks are affected by this event.
    Returns degraded empty wrapper when nothing found or errors occur.
    """
    lineage = {"reader": "get_associations", "filters": {"ts_code": ts_code, "event_id": event_id}}
    return _safe_public("marketgraph:associations_api", lineage, lambda generation: _get_associations_cached(generation, str(ts_code or ""), str(event_id or "")))


@_register_cached
@_bounded_lru_cache(maxsize=64, should_cache=lambda args, _value: bool(args[1] or args[2]))
def _get_impacts_cached(_generation: int, event_type: str, target: str) -> str:
    lineage = {"reader": "get_impacts", "filters": {"event_type": event_type, "target": target}}
    return _json_cached(
        lambda: _degraded_empty(
            "marketgraph:impacts_api",
            "impact CSV reads are retired; consume MarketGraph public API",
            lineage=lineage,
        )
    )


def get_impacts(event_type: str | None = None, target: str | None = None) -> list[dict[str, Any]]:
    """Return impact relation edges (31,206 edges).

    Filter by event_type (impact_type column) and/or target (target_id/name/type).
    Returns degraded empty wrapper when nothing found or errors occur.
    """
    lineage = {"reader": "get_impacts", "filters": {"event_type": event_type, "target": target}}
    return _safe_public("marketgraph:impacts_api", lineage, lambda generation: _get_impacts_cached(generation, str(event_type or ""), str(target or "")))


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
        ("pm_prices", lambda: get_pm_prices(limit=3)),
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

#!/usr/bin/env python3
"""Shared helpers for the Investment A-share workflow."""

from __future__ import annotations

import csv
import json
import logging
import os
import re
import tempfile
import time
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    try:
        import tomli as tomllib
    except ModuleNotFoundError:  # pragma: no cover
        tomllib = None

csv.field_size_limit(10_000_000)


# tushare_common.py lives at SharedSignals/collectors/tushare/
# parents[3] = /opt/investment/ (or ~/Projects/Finance locally)
_INVESTMENT_ROOT = Path(__file__).resolve().parents[3]
ROOT = _INVESTMENT_ROOT
INVESTMENT_ROOT = _INVESTMENT_ROOT
MARKETGRAPH_ENV_KEYS = ("MARKETGRAPH_ROOT", "MARKETGRAPH_REPO")


def _looks_like_marketgraph_root(path: Path) -> bool:
    return (
        (path / "08-Market-Interfaces").exists()
        and (path / "data").exists()
        and (path / "AGENTS.md").exists()
    )


def resolve_marketgraph_root(
    env: Mapping[str, str] | None = None,
    candidates: list[Path] | None = None,
) -> Path:
    """Resolve the standalone MarketGraph repo used by A-share consumers.

    `../MarketGraph` is a local compatibility layout. The explicit environment
    path wins so server or MCP-adjacent runners can mount MarketGraph elsewhere
    without changing A-share tools.
    """
    source_env = os.environ if env is None else env
    for key in MARKETGRAPH_ENV_KEYS:
        raw = str(source_env.get(key) or "").strip()
        if raw:
            return Path(raw).expanduser().resolve()

    search_paths = candidates or [
        INVESTMENT_ROOT / "MarketGraph",
        Path("/Users/nicholashan/Desktop/Investment/MarketGraph"),
    ]
    for candidate in search_paths:
        expanded = candidate.expanduser()
        if _looks_like_marketgraph_root(expanded):
            return expanded.resolve()
    return (INVESTMENT_ROOT / "MarketGraph").resolve()


MARKETGRAPH_ROOT = resolve_marketgraph_root()
# 关联层数据已统一到 MarketGraph（跨市场单一真相源）。
# _ASSOCIATION_DIR 是内部路径常量，仅用于需要直接写文件的内部 helper（如种子回填、事件写入）。
# A 股各工具的读操作应通过 a_share_marketgraph_interface.py 进行，以接受合同校验、安全上下文和使用审计。
_ASSOCIATION_DIR = MARKETGRAPH_ROOT / "data" / "association"
# Codex config is the canonical source for Tushare/QuickSync token and API URL.
# Environment variables (QUICKSYNC_TOKEN, QUICKSYNC_API_URL, etc.) can be used
# as an optional override; set them when you need to temporarily switch provider.
CONFIG = Path.home() / ".codex" / "config.toml"
DEFAULT_API_URL = "https://api.tushare.pro"
QUICKSYNC_API_URL = "https://api.quicksync.cn"
STOCK_BASIC_CACHE_FILE = ROOT / "data" / "tushare_cache" / "stock_basic_latest.csv"
STOCK_BASIC_CACHE_MAX_AGE_SECONDS = 24 * 60 * 60
STOCK_BASIC_REFRESH_TIMEOUT = 8
STOCK_BASIC_FIELDS = ["ts_code", "name", "industry", "market"]
STRATEGY_LIBRARY = ROOT / "strategy_library.csv"
_TUSHARE_CONFIG_CACHE: dict[str, str] | None = None
_STOCK_BASIC_MEMORY_CACHE: dict[str, dict[str, Any]] | None = None
_STOCK_BASIC_MEMORY_CACHE_DATE = ""
_STOCK_BASIC_MEMORY_CACHE_FILE = ""
_STOCK_BASIC_LAST_STATUS: dict[str, Any] = {}
_DEFAULT_STRATEGY_ALIASES: dict[str, set[str]] = {
    "STRAT_BREAKOUT_CONTINUATION": {"突破延续策略", "板块轮动首强策略"},
    "STRAT_SECTOR_ROTATION_FRONT": {"板块轮动首强策略"},
    "STRAT_HIGH_OPEN_NO_CHASE": {"高开禁追策略"},
    "STRAT_WEAK_MARKET_DEFENSE": {"弱市防守策略"},
}


def _parse_tushare_url(raw_url: str) -> dict[str, str]:
    parsed = urllib.parse.urlparse(raw_url)
    token = urllib.parse.parse_qs(parsed.query).get("token", [""])[0]
    if not token and "token=" in raw_url:
        token = raw_url.split("token=", 1)[1].split("&", 1)[0]
    api_url = urllib.parse.urlunparse(parsed._replace(query="", fragment="")).rstrip("/")
    return {"api_url": api_url or DEFAULT_API_URL, "token": token}


def _read_tushare_config_from_env(env: Mapping[str, str]) -> dict[str, str] | None:
    url_keys = ("TUSHARE_MCP_URL", "TUSHARE_API_URL", "QUICKSYNC_API_URL", "QUICKSYNC_URL")
    token_keys = ("TUSHARE_TOKEN", "TUSHARE_API_TOKEN", "QUICKSYNC_TOKEN", "QUICKSYNC_API_TOKEN")
    raw_url = next((str(env.get(key) or "") for key in url_keys if env.get(key)), "")
    token = next((str(env.get(key) or "") for key in token_keys if env.get(key)), "")
    if raw_url and "token=" in raw_url:
        parsed = _parse_tushare_url(raw_url)
        if parsed["token"]:
            return parsed
    if token:
        api_url = raw_url.rstrip("/") if raw_url else (
            QUICKSYNC_API_URL if any(env.get(key) for key in ("QUICKSYNC_TOKEN", "QUICKSYNC_API_TOKEN")) else DEFAULT_API_URL
        )
        return {"api_url": api_url, "token": token}
    return None


def _read_tushare_config_from_codex(path: Path = CONFIG) -> dict[str, str]:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    if tomllib is not None:
        try:
            with path.open("rb") as handle:
                config = tomllib.load(handle)
            raw_url = (
                config.get("mcp_servers", {})
                .get("tushareMcp", {})
                .get("url", "")
            )
            if raw_url and "token=" in raw_url:
                parsed = _parse_tushare_url(raw_url)
                if parsed["token"]:
                    return parsed
        except Exception:
            pass  # fall through to regex fallback
    match = re.search(r"\[mcp_servers\.tushareMcp\][\s\S]*?url\s*=\s*\"([^\"]+)\"", text)
    if not match or "token=" not in match.group(1):
        raise RuntimeError("Tushare token not found in Codex config")
    return _parse_tushare_url(match.group(1))


def decode_cn_quote_bytes(data: bytes) -> str:
    """Decode Chinese market quote payloads without letting codec drift break workflows."""
    for encoding in ("gbk", "gb18030", "gb2312", "utf-8", "latin-1"):
        try:
            return data.decode(encoding, "ignore")
        except LookupError:
            continue
    return data.decode("latin-1", "ignore")


def read_tushare_config() -> dict[str, str]:
    """Read Tushare/QuickSync config: codex config.toml is canonical;
    environment variables can be used as an optional override."""
    env_config = _read_tushare_config_from_env(os.environ)
    if env_config:
        return env_config
    return _read_tushare_config_from_codex(CONFIG)


def read_token() -> str:
    return read_tushare_config()["token"]


def get_tushare_config() -> dict[str, str]:
    global _TUSHARE_CONFIG_CACHE
    if _TUSHARE_CONFIG_CACHE is None:
        _TUSHARE_CONFIG_CACHE = read_tushare_config()
    return _TUSHARE_CONFIG_CACHE


def get_token() -> str:
    return get_tushare_config()["token"]


def get_api_url() -> str:
    return get_tushare_config()["api_url"]


def tushare_data(
    api_name: str,
    params: dict[str, Any] | None = None,
    fields: str = "",
    *,
    retries: int = 3,
    strict: bool = True,
    timeout: float = 30,
) -> dict[str, Any]:
    payload = json.dumps(
        {"api_name": api_name, "token": get_token(), "params": params or {}, "fields": fields}
    ).encode("utf-8")
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        req = urllib.request.Request(
            get_api_url(),
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            body = json.loads(urllib.request.urlopen(req, timeout=timeout).read().decode("utf-8"))
            if body.get("code") != 0:
                if not strict:
                    return {"fields": [], "items": [], "error": body.get("msg", ""), "code": body.get("code")}
                raise RuntimeError(body.get("msg", "Tushare request failed"))
            return body.get("data") or {"fields": [], "items": []}
        except Exception as exc:
            last_error = exc
            if attempt < retries:
                time.sleep(0.4 * attempt)
    if strict:
        raise RuntimeError(str(last_error))
    return {"fields": [], "items": [], "error": str(last_error), "code": "local_error"}


def rows_to_dicts(data: dict[str, Any]) -> list[dict[str, Any]]:
    fields = data.get("fields") or []
    return [dict(zip(fields, row)) for row in data.get("items") or []]


def tushare_rows(
    api_name: str,
    params: dict[str, Any] | None = None,
    fields: str = "",
    *,
    retries: int = 3,
    strict: bool = True,
    timeout: float = 30,
) -> list[dict[str, Any]]:
    return rows_to_dicts(tushare_data(api_name, params, fields, retries=retries, strict=strict, timeout=timeout))


def to_float(value: Any, default: float = 0.0, *, strict: bool = False) -> float:
    try:
        if value is None or value == "":
            if strict:
                raise ValueError(f"Cannot convert {value!r} to float")
            return default
        return float(value)
    except (TypeError, ValueError) as exc:
        if strict:
            raise ValueError(f"Cannot convert {value!r} to float") from exc
        return default


def today_yyyymmdd() -> str:
    return datetime.now().strftime("%Y%m%d")


def latest_trade_date(end_date: str | None = None) -> str:
    end = end_date or today_yyyymmdd()
    start = str(int(end[:4]) - 1) + end[4:]
    rows = tushare_rows("trade_cal", {"exchange": "", "start_date": start, "end_date": end}, "cal_date,is_open")
    dates = sorted(str(row["cal_date"]) for row in rows if str(row.get("is_open")) == "1")
    if not dates:
        raise RuntimeError("No open trade date found")
    return dates[-1]


def previous_trade_date(before_date: str) -> str | None:
    """Return the latest trade date strictly before `before_date`.

    Uses Tushare trade_cal to find the most recent open day.
    Returns None if no earlier trade date is found.
    """
    start = str(int(before_date[:4]) - 1) + before_date[4:]
    rows = tushare_rows("trade_cal", {"exchange": "", "start_date": start, "end_date": before_date}, "cal_date,is_open")
    dates = sorted(str(row["cal_date"]) for row in rows if str(row.get("is_open")) == "1")
    # Return the last date that is strictly before `before_date`
    for date in reversed(dates):
        if date < before_date:
            return date
    return None


def next_trade_date(after_date: str) -> str | None:
    end_year = str(int(after_date[:4]) + 1) + after_date[4:]
    rows = tushare_rows("trade_cal", {"exchange": "", "start_date": after_date, "end_date": end_year}, "cal_date,is_open")
    dates = sorted(str(row["cal_date"]) for row in rows if str(row.get("is_open")) == "1")
    for date in dates:
        if date > after_date:
            return date
    return None


def normalize_code(raw: str) -> str:
    text = raw.strip()
    if re.fullmatch(r"\d{6}\.(SH|SZ|BJ)", text, flags=re.I):
        code, suffix = text.split(".")
        return f"{code}.{suffix.upper()}"
    if re.fullmatch(r"(sh|sz|bj)\d{6}", text, flags=re.I):
        suffix = text[:2].upper()
        return f"{text[-6:]}.{suffix}"
    if re.fullmatch(r"\d{6}", text):
        if text.startswith(("6", "5")):
            return f"{text}.SH"
        if text.startswith(("8", "4", "9")):
            return f"{text}.BJ"
        return f"{text}.SZ"
    raise ValueError(f"Unsupported stock code: {raw}")


def to_tencent_symbol(ts_code: str) -> str:
    code = normalize_code(ts_code)
    number, suffix = code.split(".")
    return suffix.lower() + number


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def strategy_aliases(path: Path | None = None) -> dict[str, set[str]]:
    aliases = {key: set(values) for key, values in _DEFAULT_STRATEGY_ALIASES.items()}
    strategy_path = path or STRATEGY_LIBRARY
    if strategy_path.exists():
        for row in read_csv(strategy_path):
            strategy_id = str(row.get("strategy_id") or "").strip()
            strategy_name = str(row.get("strategy_name") or "").strip()
            if strategy_id and strategy_name:
                aliases.setdefault(strategy_id, set()).add(strategy_name)
                aliases.setdefault(strategy_name, set()).add(strategy_id)
    return aliases


def strategy_filter_values(raw: str | None, path: Path | None = None) -> set[str]:
    if not raw:
        return set()
    tokens = [item.strip() for item in raw.split(",") if item.strip()]
    if not tokens or any(item.upper() == "ALL" for item in tokens):
        return set()
    aliases = strategy_aliases(path)
    allowed: set[str] = set()
    for token in tokens:
        allowed.add(token)
        allowed.update(aliases.get(token, set()))
    return allowed


def matches_strategy_filter(
    row: dict[str, Any],
    raw_filter: str | None,
    path: Path | None = None,
) -> bool:
    allowed = strategy_filter_values(raw_filter, path)
    if not allowed:
        return True
    row_values = {
        str(row.get("strategy") or "").strip(),
        str(row.get("strategy_id") or "").strip(),
        str(row.get("strategy_name") or "").strip(),
        str(row.get("source") or "").strip(),
    }
    return bool(row_values & allowed)


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Atomic write: render to a temp file in the same directory, fsync, then
    # os.replace() onto the target. This guarantees concurrent readers and a
    # second writer never observe a half-written ledger (truncated header /
    # orphan row fragment) if a run is interrupted or two writers overlap.
    fd, tmp_name = tempfile.mkstemp(
        dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def append_unique_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str], key_fields: list[str]) -> int:
    existing = read_csv(path)
    seen = {tuple(str(row.get(key, "")) for key in key_fields) for row in existing}
    added = 0
    for row in rows:
        key = tuple(str(row.get(field, "")) for field in key_fields)
        if key in seen:
            continue
        existing.append({field: row.get(field, "") for field in fieldnames})
        seen.add(key)
        added += 1
    write_csv(path, existing, fieldnames)
    return added


def pending_review_event_ids(association_dir: Path | None = None) -> set[str]:
    """Return event_ids whose event_signal_associations review_status is pending_review_sample.

    These associations are derived event-source links that are still under review;
    they may be used for research and attribution, but must not flow into actionable
    impact relations or concentration-risk decisions until review_status changes.

    Defaults to the MarketGraph stable read gateway per contract. When callers
    pass an explicit directory, use that directory so tests, local replays and
    temporary recovery runs can remain isolated.
    """
    if association_dir is not None:
        path = association_dir / "event_signal_associations.csv"
        rows = read_csv(path) if path.exists() else []
    else:
        # Lazy import to avoid circular dependency (a_share_marketgraph_interface imports a_share_common).
        from a_share_marketgraph_interface import _rows_from_result, read_marketgraph_table  # noqa: PLC0415

        rows = _rows_from_result(read_marketgraph_table("association_event_signal_associations"))
    return {
        str(row.get("review_event_id", "")).strip()
        for row in rows
        if row.get("review_status") == "pending_review_sample" and row.get("review_event_id")
    }


def _copy_stock_basic_map(rows_by_code: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {code: dict(row) for code, row in rows_by_code.items()}


def _stock_basic_rows_to_map(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        code = str(row.get("ts_code") or "").strip()
        if not code:
            continue
        result[code] = {field: row.get(field, "") for field in STOCK_BASIC_FIELDS}
    return result


def _read_stock_basic_cache(path: Path | None = None) -> dict[str, dict[str, Any]]:
    path = path or STOCK_BASIC_CACHE_FILE
    if not path.exists():
        return {}
    try:
        return _stock_basic_rows_to_map(read_csv(path))
    except Exception:
        return {}


def _write_stock_basic_cache(rows_by_code: dict[str, dict[str, Any]], path: Path | None = None) -> None:
    path = path or STOCK_BASIC_CACHE_FILE
    rows = [rows_by_code[code] for code in sorted(rows_by_code)]
    write_csv(path, rows, STOCK_BASIC_FIELDS)


def _stock_basic_cache_is_fresh(path: Path | None = None, *, max_age_seconds: int = STOCK_BASIC_CACHE_MAX_AGE_SECONDS) -> bool:
    path = path or STOCK_BASIC_CACHE_FILE
    if max_age_seconds <= 0 or not path.exists():
        return False
    try:
        return time.time() - path.stat().st_mtime <= max_age_seconds
    except OSError:
        return False


def _set_stock_basic_memory_cache(rows_by_code: dict[str, dict[str, Any]], path: Path | None = None) -> None:
    global _STOCK_BASIC_MEMORY_CACHE, _STOCK_BASIC_MEMORY_CACHE_DATE, _STOCK_BASIC_MEMORY_CACHE_FILE
    _STOCK_BASIC_MEMORY_CACHE = _copy_stock_basic_map(rows_by_code)
    _STOCK_BASIC_MEMORY_CACHE_DATE = today_yyyymmdd()
    _STOCK_BASIC_MEMORY_CACHE_FILE = str(path or STOCK_BASIC_CACHE_FILE)


def stock_basic_cache_status() -> dict[str, Any]:
    return dict(_STOCK_BASIC_LAST_STATUS)


def stock_basic_map(
    *,
    force_refresh: bool = False,
    max_cache_age_seconds: int = STOCK_BASIC_CACHE_MAX_AGE_SECONDS,
) -> dict[str, dict[str, Any]]:
    """Return listed A-share stock basics with disk cache fallback.

    stock_basic changes slowly. Prefer today's local cache and fall back to the
    latest usable cache when the provider stalls, so slow basic metadata cannot
    block the daily workflow.
    """
    global _STOCK_BASIC_LAST_STATUS
    cache_file = STOCK_BASIC_CACHE_FILE
    today_key = today_yyyymmdd()

    if (
        not force_refresh
        and _STOCK_BASIC_MEMORY_CACHE is not None
        and _STOCK_BASIC_MEMORY_CACHE_DATE == today_key
        and _STOCK_BASIC_MEMORY_CACHE_FILE == str(cache_file)
    ):
        _STOCK_BASIC_LAST_STATUS = {
            "source": "memory_cache",
            "cache_file": str(cache_file),
            "row_count": len(_STOCK_BASIC_MEMORY_CACHE),
            "stale": False,
            "error": "",
        }
        return _copy_stock_basic_map(_STOCK_BASIC_MEMORY_CACHE)

    if not force_refresh and _stock_basic_cache_is_fresh(cache_file, max_age_seconds=max_cache_age_seconds):
        cached = _read_stock_basic_cache(cache_file)
        if cached:
            _set_stock_basic_memory_cache(cached, cache_file)
            _STOCK_BASIC_LAST_STATUS = {
                "source": "disk_cache",
                "cache_file": str(cache_file),
                "row_count": len(cached),
                "stale": False,
                "error": "",
            }
            return _copy_stock_basic_map(cached)

    last_error = ""
    try:
        rows = tushare_rows(
            "stock_basic",
            {"exchange": "", "list_status": "L"},
            ",".join(STOCK_BASIC_FIELDS),
            retries=1,
            timeout=STOCK_BASIC_REFRESH_TIMEOUT,
        )
        live = _stock_basic_rows_to_map(rows)
        if not live:
            raise RuntimeError("stock_basic returned empty rows")
        _write_stock_basic_cache(live, cache_file)
        _set_stock_basic_memory_cache(live, cache_file)
        _STOCK_BASIC_LAST_STATUS = {
            "source": "live_refresh",
            "cache_file": str(cache_file),
            "row_count": len(live),
            "stale": False,
            "error": "",
        }
        return _copy_stock_basic_map(live)
    except Exception as exc:
        last_error = str(exc)

    cached = _read_stock_basic_cache(cache_file)
    if cached:
        _set_stock_basic_memory_cache(cached, cache_file)
        _STOCK_BASIC_LAST_STATUS = {
            "source": "disk_cache_fallback",
            "cache_file": str(cache_file),
            "row_count": len(cached),
            "stale": True,
            "error": last_error,
        }
        return _copy_stock_basic_map(cached)

    _STOCK_BASIC_LAST_STATUS = {
        "source": "failed",
        "cache_file": str(cache_file),
        "row_count": 0,
        "stale": True,
        "error": last_error,
    }
    raise RuntimeError(f"stock_basic refresh failed and no usable cache is available: {last_error}")


def daily_map(trade_date: str) -> dict[str, dict[str, Any]]:
    rows = tushare_rows(
        "daily",
        {"trade_date": trade_date},
        "ts_code,trade_date,open,high,low,close,pre_close,pct_chg,amount",
    )
    return {row["ts_code"]: row for row in rows}


def safe_round(value: Any, digits: int = 2) -> float:
    return round(to_float(value), digits)


_IMPACT_RELATION_LOGGER = logging.getLogger(__name__)


def filter_impact_relations(
    rows: list[dict[str, Any]],
    *,
    logger: logging.Logger | None = None,
    min_confidence: float = 0.3,
    exclude_event_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Return impact_relations rows that are safe for downstream A-share consumers.

    Filters out rows with confidence below ``min_confidence`` or with a
    ``reference_status`` indicating the row is still a hypothesis or under
    review.  When ``reference_status`` is absent we treat the row as acceptable
    so existing files without that column are not silently dropped.

    If ``exclude_event_ids`` is provided, impact relations whose ``event_id`` is
    in the set are also skipped. This is used to keep ``pending_review_sample``
    event-signal associations out of actionable decisions while still allowing
    them in research/attribution paths.
    """
    logger = logger or _IMPACT_RELATION_LOGGER
    exclude_event_ids = exclude_event_ids or set()
    kept: list[dict[str, Any]] = []
    skipped = 0
    for row in rows:
        confidence = to_float(row.get("confidence"), 0.0)
        if confidence < min_confidence:
            logger.warning(
                "Skipping impact relation %s/%s/%s: confidence %.2f below %.2f",
                row.get("event_id", ""),
                row.get("target_type", ""),
                row.get("target_id", ""),
                confidence,
                min_confidence,
            )
            skipped += 1
            continue
        reference_status = str(row.get("reference_status", "")).strip().lower()
        if reference_status in {"hypothesis", "needs_review"}:
            logger.warning(
                "Skipping impact relation %s/%s/%s: reference_status=%r",
                row.get("event_id", ""),
                row.get("target_type", ""),
                row.get("target_id", ""),
                reference_status,
            )
            skipped += 1
            continue
        event_id = str(row.get("event_id", "")).strip()
        if event_id and event_id in exclude_event_ids:
            logger.warning(
                "Skipping impact relation %s/%s/%s: event_id in pending_review exclusion set",
                event_id,
                row.get("target_type", ""),
                row.get("target_id", ""),
            )
            skipped += 1
            continue
        kept.append(row)
    if skipped:
        logger.warning(
            "Filtered impact_relations: %d loaded, %d kept, %d skipped",
            len(rows),
            len(kept),
            skipped,
        )
    return kept

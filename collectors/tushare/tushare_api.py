#!/usr/bin/env python3
"""Unified Tushare API wrapper with in-memory LRU caching.

All functions return list[dict]; empty on error or no results (strict=False).
Import from the current SharedSignals Tushare modules; do not restore legacy
A-share compatibility module names.
"""

from __future__ import annotations

import logging
import os
import sys
import threading
from collections import OrderedDict
from typing import Any

# Ensure this directory is on sys.path so absolute imports work both as a
# package submodule and when the collector is invoked as a standalone script.
_current_dir = os.path.dirname(os.path.realpath(__file__))
if _current_dir not in sys.path:
    sys.path.insert(0, _current_dir)

from tushare_common import to_float, tushare_rows

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Simple LRU cache (functools.lru_cache can't hash dict kwargs reliably)
# ---------------------------------------------------------------------------

_MAX_CACHE = 512

_cache_lock = threading.Lock()
_cache: OrderedDict[str, list[dict[str, Any]]] = OrderedDict()


def _make_key(func_name: str, args: tuple, kwargs: dict) -> str:
    """Build a stable cache key: 'func_name:(arg1,arg2,...):{k=v,...}'."""
    args_str = ",".join(str(a) for a in args)
    kwargs_str = ",".join(f"{k}={v}" for k, v in sorted(kwargs.items()))
    return f"{func_name}:({args_str}):{{{kwargs_str}}}"


def _cached_call(func_name: str, args: tuple, kwargs: dict) -> list[dict[str, Any]]:
    """Return cached result or call Tushare and store."""
    key = _make_key(func_name, args, kwargs)
    with _cache_lock:
        if key in _cache:
            _cache.move_to_end(key)
            return _cache[key]
    result = tushare_rows(func_name, *args, **kwargs)
    if not result:
        return result
    with _cache_lock:
        _cache[key] = result
        _cache.move_to_end(key)
        while len(_cache) > _MAX_CACHE:
            _cache.popitem(last=False)
    return result


def _clear_cache() -> None:
    """Clear the module-level API cache (useful for testing or forced refresh)."""
    with _cache_lock:
        _cache.clear()


# ---------------------------------------------------------------------------
# Helper: call tushare_rows with strict=False, use _cached_call for caching
# ---------------------------------------------------------------------------

def _call(api_name: str, params: dict, fields: str = "") -> list[dict[str, Any]]:
    """Single line bridge: cache-aware call to tushare_rows(…, strict=False)."""
    return _cached_call(api_name, (params, fields), {"strict": False})


def _as_code_list(ts_code: str | None = None, ts_codes: list[str] | tuple[str, ...] | None = None) -> list[str]:
    if ts_codes is not None:
        return [str(code) for code in ts_codes if str(code)]
    if ts_code:
        return [str(ts_code)]
    return []


def _concat(rows_by_code: list[list[dict[str, Any]]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for chunk in rows_by_code:
        rows.extend(chunk)
    return rows


def _quicksync_datetime_window(start_date: str, end_date: str | None = None) -> tuple[str, str]:
    """Accept YYYYMMDD or full datetime and return QuickSync-compatible bounds."""
    raw_start = str(start_date or "").strip()
    raw_end = str(end_date or start_date or "").strip()

    def start_bound(value: str) -> str:
        if " " in value:
            return value
        if "-" in value:
            return f"{value} 00:00:00"
        return f"{value[:4]}-{value[4:6]}-{value[6:]} 00:00:00"

    def end_bound(value: str) -> str:
        if " " in value:
            return value
        if "-" in value:
            return f"{value} 23:59:59"
        return f"{value[:4]}-{value[4:6]}-{value[6:]} 23:59:59"

    return start_bound(raw_start), end_bound(raw_end)


# ===========================================================================
# 行情 / 日线
# ===========================================================================


def get_daily(
    ts_code: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    *,
    ts_codes: list[str] | tuple[str, ...] | None = None,
    trade_date: str | None = None,
) -> list[dict[str, Any]]:
    """A股日线行情（OHLCV）。

    Tushare API: daily
    Fields: ts_code, trade_date, open, high, low, close, vol, amount
    """
    if trade_date:
        start_date = end_date = trade_date
    codes = _as_code_list(ts_code, ts_codes)
    if len(codes) > 1:
        return _concat([get_daily(code, start_date, end_date) for code in codes])
    params: dict[str, Any] = {}
    if codes:
        params["ts_code"] = codes[0]
    if start_date:
        params["start_date"] = start_date
    if end_date:
        params["end_date"] = end_date
    return _call(
        "daily",
        params,
        "ts_code,trade_date,open,high,low,close,vol,amount",
    )


def get_adj_factor(ts_code: str, start_date: str, end_date: str) -> list[dict[str, Any]]:
    """复权因子。

    Tushare API: adj_factor
    """
    return _call(
        "adj_factor",
        {"ts_code": ts_code, "start_date": start_date, "end_date": end_date},
    )


def get_suspend_d(ts_code: str, start_date: str, end_date: str) -> list[dict[str, Any]]:
    """停复牌信息（日频）。

    Tushare API: suspend_d
    """
    return _call(
        "suspend_d",
        {"ts_code": ts_code, "start_date": start_date, "end_date": end_date},
    )


# ===========================================================================
# 分钟 / 集合竞价
# ===========================================================================


def get_rt_min(
    ts_code: str | None = None,
    freq: str = "5MIN",
    *,
    ts_codes: list[str] | tuple[str, ...] | None = None,
) -> list[dict[str, Any]]:
    """A股实时分钟行情。

    Tushare API: rt_min
    """
    codes = [
        part.strip()
        for code in _as_code_list(ts_code, ts_codes)
        for part in str(code).split(",")
        if part.strip()
    ]
    params: dict[str, Any] = {"freq": freq}
    if codes:
        params["ts_code"] = ",".join(codes)
    return _call("rt_min", params, "ts_code,freq,time,open,close,high,low,vol,amount")


def get_rt_min_daily(ts_code: str, freq: str = "1MIN") -> list[dict[str, Any]]:
    """A股当日分钟明细。

    Tushare API: rt_min_daily
    """
    return _call("rt_min_daily", {"ts_code": ts_code, "freq": freq}, "ts_code,time,open,close,high,low,vol,amount")


def get_stk_auction(ts_code: str = "", trade_date: str = "") -> list[dict[str, Any]]:
    """集合竞价数据。

    Tushare API: stk_auction
    """
    params: dict[str, Any] = {}
    if ts_code:
        params["ts_code"] = ts_code
    if trade_date:
        params["trade_date"] = trade_date
    return _call(
        "stk_auction",
        params,
        "ts_code,trade_date,open,close,price,pct_chg,vol,volume,amount,turnover_rate,match_amount,match_volume",
    )


# ===========================================================================
# 资金流 / 涨跌停
# ===========================================================================


def get_moneyflow(trade_date: str) -> list[dict[str, Any]]:
    """个股资金流向（按交易日全市场）。

    Tushare API: moneyflow.
    """
    return _call("moneyflow", {"trade_date": trade_date})


def get_limit_list_d(trade_date: str, limit_type: str = "U") -> list[dict[str, Any]]:
    """涨跌停列表（日频）。

    Tushare API: limit_list_d.
    limit_type: U=涨停, D=跌停, Z=炸板
    """
    return _call(
        "limit_list_d",
        {"trade_date": trade_date, "limit_type": limit_type},
    )


def get_stk_limit(ts_code: str, trade_date: str) -> list[dict[str, Any]]:
    """个股涨跌停价格。

    Tushare API: stk_limit
    """
    return _call("stk_limit", {"ts_code": ts_code, "trade_date": trade_date})


def get_block_trade(
    start_date: str | None = None,
    end_date: str | None = None,
    *,
    ts_code: str | None = None,
    ts_codes: list[str] | tuple[str, ...] | None = None,
    trade_date: str | None = None,
) -> list[dict[str, Any]]:
    """大宗交易。

    Tushare API: block_trade
    """
    if trade_date:
        start_date = end_date = trade_date
    codes = _as_code_list(ts_code, ts_codes)
    if len(codes) > 1:
        return _concat([get_block_trade(start_date, end_date, ts_code=code) for code in codes])
    params: dict[str, Any] = {}
    if codes:
        params["ts_code"] = codes[0]
    if start_date:
        params["start_date"] = start_date
    if end_date:
        params["end_date"] = end_date
    return _call("block_trade", params)


# ===========================================================================
# 两融 / 北向
# ===========================================================================


def get_margin(trade_date: str) -> list[dict[str, Any]]:
    """融资融券交易汇总（按交易日全市场）。

    Tushare API: margin.
    """
    return _call("margin", {"trade_date": trade_date})


def get_margin_detail(ts_code: str, start_date: str, end_date: str) -> list[dict[str, Any]]:
    """融资融券交易明细。

    Tushare API: margin_detail
    """
    return _call(
        "margin_detail",
        {"ts_code": ts_code, "start_date": start_date, "end_date": end_date},
    )


def get_hk_hold(
    ts_code: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    *,
    ts_codes: list[str] | tuple[str, ...] | None = None,
    trade_date: str | None = None,
) -> list[dict[str, Any]]:
    """沪深港通持股明细（北向资金）。

    Tushare API: hk_hold
    """
    if trade_date:
        start_date = end_date = trade_date
    codes = _as_code_list(ts_code, ts_codes)
    if len(codes) > 1:
        return _concat([get_hk_hold(code, start_date, end_date) for code in codes])
    params: dict[str, Any] = {}
    if codes:
        params["ts_code"] = codes[0]
    if start_date:
        params["start_date"] = start_date
    if end_date:
        params["end_date"] = end_date
    return _call(
        "hk_hold",
        params,
    )


# ===========================================================================
# 财务
# ===========================================================================


def get_fina_indicator(ts_code: str, start_date: str, end_date: str) -> list[dict[str, Any]]:
    """财务指标（ROE/ROA/毛利率/净利率/资产负债率）。

    Tushare API: fina_indicator
    Fields: end_date, roe, roa, grossprofit_margin, netprofit_margin, debt_to_assets
    """
    return _call(
        "fina_indicator",
        {"ts_code": ts_code, "start_date": start_date, "end_date": end_date},
        "end_date,roe,roa,grossprofit_margin,netprofit_margin,debt_to_assets",
    )


def get_income(ts_code: str, start_date: str, end_date: str) -> list[dict[str, Any]]:
    """利润表。

    Tushare API: income
    """
    return _call(
        "income",
        {"ts_code": ts_code, "start_date": start_date, "end_date": end_date},
    )


def get_balancesheet(ts_code: str, start_date: str, end_date: str) -> list[dict[str, Any]]:
    """资产负债表。

    Tushare API: balancesheet
    """
    return _call(
        "balancesheet",
        {"ts_code": ts_code, "start_date": start_date, "end_date": end_date},
    )


def get_cashflow(ts_code: str, start_date: str, end_date: str) -> list[dict[str, Any]]:
    """现金流量表。

    Tushare API: cashflow
    """
    return _call(
        "cashflow",
        {"ts_code": ts_code, "start_date": start_date, "end_date": end_date},
    )


# ===========================================================================
# 股东 / 质押 / 股本
# ===========================================================================


def get_stk_holdernumber(ts_code: str, start_date: str, end_date: str) -> list[dict[str, Any]]:
    """股东人数。

    Tushare API: stk_holdernumber
    """
    return _call(
        "stk_holdernumber",
        {"ts_code": ts_code, "start_date": start_date, "end_date": end_date},
    )


def get_top10_holders(ts_code: str, start_date: str, end_date: str) -> list[dict[str, Any]]:
    """前十大股东。

    Tushare API: top10_holders
    """
    return _call(
        "top10_holders",
        {"ts_code": ts_code, "start_date": start_date, "end_date": end_date},
    )


def get_top10_floatholders(ts_code: str, start_date: str, end_date: str) -> list[dict[str, Any]]:
    """前十大流通股东。

    Tushare API: top10_floatholders
    """
    return _call(
        "top10_floatholders",
        {"ts_code": ts_code, "start_date": start_date, "end_date": end_date},
    )


def get_pledge_stat(ts_code: str) -> list[dict[str, Any]]:
    """股权质押统计。

    Tushare API: pledge_stat
    """
    return _call("pledge_stat", {"ts_code": ts_code})


def get_share_float(ts_code: str, start_date: str, end_date: str) -> list[dict[str, Any]]:
    """限售股解禁 / 流通股本。

    Tushare API: share_float
    """
    return _call(
        "share_float",
        {"ts_code": ts_code, "start_date": start_date, "end_date": end_date},
    )


# ===========================================================================
# 指数 / 基金
# ===========================================================================


def get_index_daily(
    ts_code: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    *,
    ts_codes: list[str] | tuple[str, ...] | None = None,
    trade_date: str | None = None,
) -> list[dict[str, Any]]:
    """指数日线行情。

    Tushare API: index_daily
    Fields: ts_code, trade_date, close, vol, amount
    """
    if trade_date:
        start_date = end_date = trade_date
    codes = _as_code_list(ts_code, ts_codes)
    if len(codes) > 1:
        return _concat([get_index_daily(code, start_date, end_date) for code in codes])
    params: dict[str, Any] = {}
    if codes:
        params["ts_code"] = codes[0]
    if start_date:
        params["start_date"] = start_date
    if end_date:
        params["end_date"] = end_date
    return _call(
        "index_daily",
        params,
        "ts_code,trade_date,close,vol,amount",
    )


def get_index_weight(index_code: str, trade_date: str) -> list[dict[str, Any]]:
    """指数成分权重。

    Tushare API: index_weight
    """
    return _call("index_weight", {"index_code": index_code, "trade_date": trade_date})


def get_fund_daily(ts_code: str, start_date: str, end_date: str) -> list[dict[str, Any]]:
    """基金日线行情。

    Tushare API: fund_daily
    """
    return _call(
        "fund_daily",
        {"ts_code": ts_code, "start_date": start_date, "end_date": end_date},
    )


def get_index_global(
    ts_code: str = "HSI",
    start_date: str | None = None,
    end_date: str | None = None,
) -> list[dict[str, Any]]:
    """全球指数日线行情。

    Tushare API: index_global
    """
    params: dict[str, Any] = {"ts_code": ts_code}
    if start_date:
        params["start_date"] = start_date
    if end_date:
        params["end_date"] = end_date
    return _call("index_global", params)


# ===========================================================================
# 概念 / 板块
# ===========================================================================


def get_concept(src: str = "ts") -> list[dict[str, Any]]:
    """概念板块列表。

    Tushare API: concept
    src: 'ts' (东方财富) 或 'ths' (同花顺)
    """
    return _call("concept", {"src": src})


def get_ths_index(ts_code: str, start_date: str, end_date: str) -> list[dict[str, Any]]:
    """同花顺概念指数日线。

    Tushare API: ths_index
    """
    return _call(
        "ths_index",
        {"ts_code": ts_code, "start_date": start_date, "end_date": end_date},
    )


def get_ths_member(ts_code: str) -> list[dict[str, Any]]:
    """同花顺概念板块成分股。

    Tushare API: ths_member
    """
    return _call("ths_member", {"ts_code": ts_code})


# ===========================================================================
# 事件 / 公告 / 新闻
# ===========================================================================


def get_news(start_date: str, end_date: str) -> list[dict[str, Any]]:
    """新闻快讯。

    日期格式: YYYY-MM-DD HH:MM:SS
    Tushare API: news
    """
    start_at, end_at = _quicksync_datetime_window(start_date, end_date)
    return _call("news", {"start_date": start_at, "end_date": end_at}, "datetime,title,content,src,url")


def get_major_news(start_date: str, end_date: str) -> list[dict[str, Any]]:
    """重大新闻。

    日期格式: YYYY-MM-DD HH:MM:SS
    Tushare API: major_news
    """
    start_at, end_at = _quicksync_datetime_window(start_date, end_date)
    return _call("major_news", {"start_date": start_at, "end_date": end_at}, "pub_time,title,src")


def get_cctv_news(start_date: str, end_date: str) -> list[dict[str, Any]]:
    """新闻联播文字稿。

    Tushare API: cctv_news
    """
    return _call("cctv_news", {"start_date": start_date, "end_date": end_date}, "date,title,content")


def get_anns_d(ts_code: str, start_date: str, end_date: str) -> list[dict[str, Any]]:
    """上市公司公告（日频）。

    Tushare API: anns_d
    """
    return _call(
        "anns_d",
        {"ts_code": ts_code, "start_date": start_date, "end_date": end_date},
    )


def get_report_rc(ts_code: str, start_date: str, end_date: str) -> list[dict[str, Any]]:
    """券商研报盈利预测。

    Tushare API: report_rc
    """
    return _call(
        "report_rc",
        {"ts_code": ts_code, "start_date": start_date, "end_date": end_date},
    )


def get_broker_recommend(month: str) -> list[dict[str, Any]]:
    """券商月度金股/推荐股票。

    Tushare API: broker_recommend
    """
    return _call("broker_recommend", {"month": month})


# ===========================================================================
# 筹码
# ===========================================================================


def get_cyq_perf(
    ts_code: str | None = None,
    trade_date: str = "",
    *,
    ts_codes: list[str] | tuple[str, ...] | None = None,
) -> list[dict[str, Any]]:
    """筹码分布（CYQ）绩效数据。

    Tushare API: cyq_perf
    """
    codes = _as_code_list(ts_code, ts_codes)
    if len(codes) > 1:
        return _concat([get_cyq_perf(code, trade_date) for code in codes])
    params: dict[str, Any] = {"trade_date": trade_date}
    if codes:
        params["ts_code"] = codes[0]
    return _call("cyq_perf", params)


# ===========================================================================
# 额外（备用行情 / 每日指标 / 技术因子）
# ===========================================================================


def get_bak_daily(ts_code: str, start_date: str, end_date: str) -> list[dict[str, Any]]:
    """备用行情（复权后行情）。

    Tushare API: bak_daily
    """
    return _call(
        "bak_daily",
        {"ts_code": ts_code, "start_date": start_date, "end_date": end_date},
    )


def get_daily_basic(ts_code: str, trade_date: str) -> list[dict[str, Any]]:
    """每日指标（换手率/PE/PB/总市值等）。

    Tushare API: daily_basic
    """
    return _call("daily_basic", {"ts_code": ts_code, "trade_date": trade_date})


def get_stk_factor(ts_code: str, start_date: str, end_date: str) -> list[dict[str, Any]]:
    """每日技术因子（MACD/KDJ/RSI/BOLL等）。

    Tushare API: stk_factor
    """
    return _call(
        "stk_factor",
        {"ts_code": ts_code, "start_date": start_date, "end_date": end_date},
    )


# ===========================================================================
# 跨市场行情（港股/美股/期货）—填补 gateway 的 _call 缺口
# ===========================================================================


def get_stock_basic() -> list[dict[str, Any]]:
    """A股股票列表（代码/名称/行业/上市日期/退市日期）。

    Tushare API: stock_basic. Results are cacheable (列表几乎不变).
    """
    return _call("stock_basic", {})


def get_hk_daily(ts_code: str, start_date: str, end_date: str) -> list[dict[str, Any]]:
    """港股日线行情。

    Tushare API: hk_daily
    """
    return _call(
        "hk_daily",
        {"ts_code": ts_code, "start_date": start_date, "end_date": end_date},
    )


def get_us_daily(ts_code: str, start_date: str, end_date: str) -> list[dict[str, Any]]:
    """美股日线行情。

    Tushare API: us_daily
    """
    return _call(
        "us_daily",
        {"ts_code": ts_code, "start_date": start_date, "end_date": end_date},
    )


def get_fut_daily(trade_date: str) -> list[dict[str, Any]]:
    """期货日线行情（按交易日全品种）。

    Tushare API: fut_daily
    """
    return _call("fut_daily", {"trade_date": trade_date})


# ===========================================================================
# Export
# ===========================================================================

__all__ = [
    "get_daily",
    "get_adj_factor",
    "get_suspend_d",
    "get_rt_min",
    "get_rt_min_daily",
    "get_stk_auction",
    "get_moneyflow",
    "get_limit_list_d",
    "get_stk_limit",
    "get_block_trade",
    "get_margin",
    "get_margin_detail",
    "get_hk_hold",
    "get_fina_indicator",
    "get_income",
    "get_balancesheet",
    "get_cashflow",
    "get_stk_holdernumber",
    "get_top10_holders",
    "get_top10_floatholders",
    "get_pledge_stat",
    "get_share_float",
    "get_index_daily",
    "get_index_weight",
    "get_fund_daily",
    "get_index_global",
    "get_concept",
    "get_ths_index",
    "get_ths_member",
    "get_news",
    "get_major_news",
    "get_cctv_news",
    "get_anns_d",
    "get_report_rc",
    "get_broker_recommend",
    "get_cyq_perf",
    "get_bak_daily",
    "get_daily_basic",
    "get_stk_factor",
    "get_stock_basic",
    "get_hk_daily",
    "get_us_daily",
    "get_fut_daily",
    "_clear_cache",
]

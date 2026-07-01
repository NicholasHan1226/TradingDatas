"""Deduplication mixin — PK-based and semantic (news/events)."""

from __future__ import annotations

import hashlib
import re
from typing import Any


class DeduplicatorMixin:
    """Row deduplication by primary key and by semantic similarity (events)."""

    @staticmethod
    def _dedup_key(api_name: str, row: dict[str, Any]) -> tuple:
        """Generate dedup key per API type."""
        keys: dict[str, tuple[str, ...]] = {
            "daily": ("ts_code", "trade_date"),
            "moneyflow": ("ts_code", "trade_date"),
            "adj_factor": ("ts_code", "trade_date"),
            "daily_basic": ("ts_code", "trade_date"),
            "fina_indicator": ("ts_code", "end_date"),
            "income": ("ts_code", "end_date"),
            "balancesheet": ("ts_code", "end_date"),
            "margin_detail": ("ts_code", "trade_date"),
            "stock_basic": ("ts_code",),
            "stk_factor": ("ts_code", "trade_date"),
            "index_daily": ("ts_code", "trade_date"),
            "fund_daily": ("ts_code", "trade_date"),
            "moneyflow_hsgt": ("trade_date",),
            "limit_list": ("ts_code", "trade_date"),
            "top_list": ("ts_code", "trade_date"),
            "block_trade": ("ts_code", "trade_date"),
            "hk_daily": ("ts_code", "trade_date"),
            "us_daily": ("ts_code", "trade_date"),
            "cn_cpi": ("month",),
            "cn_pmi": ("month",),
            "shibor": ("date",),
            # Crypto / PM
            "klines": ("symbol", "trade_date", "interval"),
            "pm_markets": ("market_id",),
            "pm_prices": ("market_id", "price_time"),
        }
        key_fields = keys.get(api_name, ("ts_code", "trade_date"))
        return tuple(str(row.get(f, "")) for f in key_fields)

    def deduplicate(self, api_name: str, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        seen: dict[tuple, dict] = {}
        for row in rows:
            key = self._dedup_key(api_name, row)
            seen[key] = row  # last wins
        return list(seen.values())

    @staticmethod
    def _text_fingerprint(title: str, content: str = "") -> str:
        clean = re.sub(r"\s+", "", (title + content)[:500])
        return hashlib.sha256(clean.encode()).hexdigest()[:16]

    @staticmethod
    def _title_similar(a: str, b: str) -> float:
        if not a or not b:
            return 0.0
        ta = set(re.findall(r"[一-鿿\w]+", a.lower()))
        tb = set(re.findall(r"[一-鿿\w]+", b.lower()))
        if not ta or not tb:
            return 0.0
        return len(ta & tb) / len(ta | tb)

    def event_deduplicate(self, rows: list[dict[str, Any]], time_window_h: int = 24) -> list[dict[str, Any]]:
        seen_urls: set[str] = set()
        seen_hashes: set[str] = set()
        seen_titles: dict[str, tuple[str, str]] = {}
        result: list[dict[str, Any]] = []
        for row in rows:
            url = str(row.get("source_url", row.get("url", ""))).strip()
            title = str(row.get("title", "")).strip()
            summary = str(row.get("summary", row.get("content", ""))).strip()
            event_time = str(row.get("event_time", row.get("trade_date", ""))).strip()

            if url and url in seen_urls:
                continue
            if url:
                seen_urls.add(url)

            fprint = self._text_fingerprint(title, summary)
            if fprint in seen_hashes:
                continue
            seen_hashes.add(fprint)

            for seen_title, _ in seen_titles.items():
                if self._title_similar(title, seen_title) > 0.85:
                    break
            else:
                seen_titles[title] = (fprint, event_time)
                result.append(row)
        return result

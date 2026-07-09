"""Contract tests for the A-share macro / sentiment / capital-flow evidence loop.

These tests verify that SharedSignals reader and HTTP API return real ingested
read-model rows for the three evidence dimensions without calling providers or
falling back to CSV/NDJSON/legacy directories.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path
from typing import Any

import pytest

_SHARED = Path(__file__).resolve().parents[1]
if str(_SHARED) not in sys.path:
    sys.path.insert(0, str(_SHARED))


class _FakeAuth:
    """Minimal auth shim for API-dispatch tests."""

    def authenticate(self, headers: Any, client_host: str) -> dict[str, Any]:
        return {"tenant_id": "test", "tier": "internal", "scopes": ["*"]}

    def check_endpoint_scope(self, account: dict[str, Any], path: str) -> bool:
        return True

    def enforce_rate_limit(self, tenant_id: str, tier: str) -> None:
        return None

    def cache_stats(self) -> dict[str, Any]:
        return {}


@pytest.fixture
def evidence_db(tmp_path: Path, monkeypatch: Any):
    """Create a temporary read-model DB with macro/sentiment/flow sample rows."""
    from storage.schema import SCHEMA_SQL
    import reader

    db_path = tmp_path / "marketdata.sqlite"
    conn = sqlite3.connect(str(db_path))
    conn.executescript(SCHEMA_SQL)

    collected_at = "2026-07-09T10:00:00+00:00"

    # Macro factors: monthly (cn_cpi), quarterly (cn_gdp), daily rates/FX/global
    macro_rows = [
        ("h1", "", "cn_cpi:nt_val", "202606", 100.4, "tushare_cn_cpi"),
        ("h2", "", "cn_gdp:gdp", "2026Q3", 28.5, "tushare_cn_gdp"),
        ("h3", "", "shibor_lpr:1y", "20260708", 3.35, "tushare_shibor_lpr"),
        ("h4", "", "fx_daily:bid", "20260708", 7.23, "tushare_fx_daily"),
        ("h5", "", "hibor:1w", "20260708", 1.12, "tushare_hibor"),
        ("h6", "", "libor:1m", "20260708", 2.34, "tushare_libor"),
        ("h7", "Global", "index_global:close", "20260708", 5200.0, "tushare_index_global"),
        ("h8", "", "index_dailybasic:pe", "20260708", 15.6, "tushare_index_dailybasic"),
        ("h9", "", "repo_daily:close", "20260708", 1.88, "tushare_repo_daily"),
    ]
    conn.executemany(
        """
        INSERT INTO market_factors (
            factor_hash, market, symbol, factor_name, event_time, value,
            provider, source_file, collected_at, raw_json
        ) VALUES (?, ?, '', ?, ?, ?, ?, 'evidence_test', ?, '{}')
        """,
        [(h, m, f, e, v, p, collected_at) for h, m, f, e, v, p in macro_rows],
    )

    # Capital-flow factors: moneyflow + northbound + margin
    flow_rows = [
        ("c1", "Ashare", "000001.SZ", "moneyflow:net_mf_amount", "20260708", 1e6, "tushare_moneyflow"),
        ("c2", "Ashare", "000001.SZ", "moneyflow_hsgt:net_mf_amount", "20260708", 2e6, "tushare_moneyflow_hsgt"),
        ("c3", "Ashare", "000001.SZ", "margin:rzye", "20260708", 3e6, "tushare_margin"),
        ("c4", "Ashare", "000001.SZ", "margin_detail:rzye", "20260708", 3.1e6, "tushare_margin_detail"),
    ]
    conn.executemany(
        """
        INSERT INTO market_factors (
            factor_hash, market, symbol, factor_name, event_time, value,
            provider, source_file, collected_at, raw_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, 'evidence_test', ?, '{}')
        """,
        [(h, m, s, f, e, v, p, collected_at) for h, m, s, f, e, v, p in flow_rows],
    )

    # Sentiment-style events from the event lane
    sentiment_rows = [
        ("e1", "tushare_major_news", "major_news", "20260708", "20260708", "Ashare", "600519.SH", "茅台利好", "content", "tushare_major_news"),
        ("e2", "tushare_news", "news", "20260708", "20260708", "Ashare", "000001.SZ", "市场震荡", "content", "tushare_news"),
        ("e3", "tushare_cctv_news", "cctv_news", "20260708", "20260708", "Ashare", "", "央视报道", "content", "tushare_cctv_news"),
    ]
    conn.executemany(
        """
        INSERT INTO market_events (
            event_hash, provider, event_type, event_time, trade_date, market,
            symbol, title, content, url, source, source_file, collected_at, raw_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, '', ?, 'evidence_test', ?, '{}')
        """,
        [(h, p, et, etime, td, m, s, title, content, src, collected_at)
         for h, p, et, etime, td, m, s, title, content, src in sentiment_rows],
    )

    conn.commit()
    conn.close()

    monkeypatch.setattr(reader, "SQLITE_PATH", db_path)
    reader.clear_caches()
    yield db_path


class TestMacroEvidence:
    """Macro factors must include monthly/quarterly/daily P4 rows."""

    def test_reader_macro_returns_all_p4_rows(self, evidence_db: Path) -> None:
        import reader

        rows = reader.get_macro_factors("20260601", "20260709")
        providers = {row["data"]["provider"] for row in rows if not row.get("degraded")}
        expected = {
            "tushare_cn_cpi",
            "tushare_cn_gdp",
            "tushare_shibor_lpr",
            "tushare_fx_daily",
            "tushare_hibor",
            "tushare_libor",
            "tushare_index_global",
            "tushare_index_dailybasic",
            "tushare_repo_daily",
        }
        assert expected <= providers, f"missing macro providers: {expected - providers}"

    def test_reader_macro_honors_limit(self, evidence_db: Path) -> None:
        import reader

        rows = reader.get_macro_factors("20260601", "20260709", limit=3)
        assert len(rows) == 3

    def test_api_macro_returns_ingested_rows(self, evidence_db: Path, monkeypatch: Any) -> None:
        import api_server
        import reader

        monkeypatch.setattr(api_server, "auth", _FakeAuth())
        monkeypatch.setattr(api_server, "reader", reader)

        handler = api_server.Handler.__new__(api_server.Handler)
        response = handler._dispatch("/macro", {"start": "20260601", "end": "20260709", "limit": "50"})

        assert response["metadata"]["degraded"] is False
        providers = {row["provider"] for row in response["data"]}
        assert "tushare_cn_cpi" in providers
        assert "tushare_index_global" in providers


class TestCapitalFlowEvidence:
    """Capital-flow read surface must cover moneyflow, northbound and margin."""

    def test_reader_capital_flow_returns_all_flow_rows(self, evidence_db: Path) -> None:
        import reader

        rows = reader.get_capital_flow(date="20260708", ts_code="000001.SZ")
        providers = {row["data"]["provider"] for row in rows if not row.get("degraded")}
        expected = {
            "tushare_moneyflow",
            "tushare_moneyflow_hsgt",
            "tushare_margin",
            "tushare_margin_detail",
        }
        assert expected <= providers, f"missing capital-flow providers: {expected - providers}"

    def test_reader_capital_flow_honors_date_range(self, evidence_db: Path) -> None:
        import reader

        rows = reader.get_capital_flow(ts_code="000001.SZ", start_date="20260708", end_date="20260708")
        assert len(rows) == 4

    def test_api_capital_flow_returns_ingested_rows(self, evidence_db: Path, monkeypatch: Any) -> None:
        import api_server
        import reader

        monkeypatch.setattr(api_server, "auth", _FakeAuth())
        monkeypatch.setattr(api_server, "reader", reader)

        handler = api_server.Handler.__new__(api_server.Handler)
        response = handler._dispatch(
            "/capital_flow", {"ts_code": "000001.SZ", "start": "20260708", "end": "20260708"}
        )

        assert response["metadata"]["degraded"] is False
        providers = {row["provider"] for row in response["data"]}
        assert "tushare_moneyflow_hsgt" in providers
        assert "tushare_margin" in providers


class TestSentimentEvidence:
    """Sentiment must surface real event-lane rows when no dedicated sentiment source exists."""

    def test_reader_sentiment_returns_event_lane_rows(self, evidence_db: Path) -> None:
        import reader

        rows = reader.get_sentiment("20260708", "20260708")
        titles = {row["data"]["title"] for row in rows if not row.get("degraded")}
        expected = {"茅台利好", "市场震荡", "央视报道"}
        assert expected <= titles, f"missing sentiment rows: {expected - titles}"

    def test_reader_sentiment_returns_degraded_when_no_sources(self, evidence_db: Path, monkeypatch: Any) -> None:
        import reader

        monkeypatch.setattr(reader, "_sentiment_event_types", lambda: frozenset())
        rows = reader.get_sentiment("20260708", "20260708")
        assert all(row.get("degraded") for row in rows)

    def test_api_sentiment_returns_ingested_rows(self, evidence_db: Path, monkeypatch: Any) -> None:
        import api_server
        import reader

        monkeypatch.setattr(api_server, "auth", _FakeAuth())
        monkeypatch.setattr(api_server, "reader", reader)

        handler = api_server.Handler.__new__(api_server.Handler)
        response = handler._dispatch("/sentiment", {"start": "20260708", "end": "20260708", "limit": "10"})

        assert response["metadata"]["degraded"] is False
        titles = {row["title"] for row in response["data"]}
        assert "央视报道" in titles

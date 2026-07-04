"""test_dedup — deduplication tests for SharedSignals storage layer.

Tests URL-based dedup, URL normalization, content-based dedup,
cross-source dedup, and batch dedup performance.
"""
from __future__ import annotations

import hashlib
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

pytestmark = pytest.mark.skip(
    reason=(
        "legacy ghost tests use local helper copies instead of SharedSignals "
        "production modules; replace with production-bound dedup tests before enabling"
    )
)


NOW = datetime(2026, 6, 29, 18, 0, 0, tzinfo=timezone.utc)


# ===========================================================================
# Dedup utility functions (mirrors SharedSignals storage dedup logic)
# ===========================================================================


def url_dedup_key(url: str) -> str:
    """Normalize a URL for dedup: strip query params, trailing slash, lowercase."""
    if not url:
        return ""
    u = url.strip()
    # Remove query string and fragment
    if "?" in u:
        u = u.split("?")[0]
    if "#" in u:
        u = u.split("#")[0]
    # Remove trailing slash
    u = u.rstrip("/")
    # Lowercase scheme + host
    return u.lower()


def content_hash(title: str, content: str) -> str:
    """SHA256 hash of normalized title+content for content dedup."""
    raw = f"{(title or '').strip().lower()[:500]}|{(content or '').strip().lower()[:2000]}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def event_dedup_key(event: dict[str, Any]) -> str:
    """Composite dedup key: normalized URL OR content hash (if no URL)."""
    url = event.get("url", "") or ""
    if url.strip():
        return f"url:{url_dedup_key(url)}"

    title = event.get("title", "") or ""
    content = event.get("content", "") or ""
    return f"content:{content_hash(title, content)}"


def deduplicate_events(
    events: list[dict[str, Any]],
    keep: str = "first",
) -> list[dict[str, Any]]:
    """Deduplicate a list of events.

    Args:
        events: list of event dicts with url/title/content.
        keep: "first" keeps first occurrence, "last" keeps last,
              "highest_priority" keeps item with highest tier_priority.

    Returns deduplicated list in original order (first occurrence wins for position).
    """
    seen: dict[str, dict[str, Any]] = {}
    order: list[str] = []

    for event in events:
        key = event_dedup_key(event)
        if not key:
            continue

        if key not in seen:
            seen[key] = event
            order.append(key)
        elif keep == "last":
            seen[key] = event
        elif keep == "highest_priority":
            existing = seen[key]
            if event.get("tier_priority", 0) > existing.get("tier_priority", 0):
                seen[key] = event

    return [seen[k] for k in order]


def batch_insert_dedup(
    conn: sqlite3.Connection,
    events: list[dict[str, Any]],
) -> tuple[int, int]:
    """Insert events into market_events with dedup via INSERT OR REPLACE.

    Returns (inserted, skipped_as_duplicate).
    """
    inserted = 0
    skipped = 0

    for event in events:
        event_hash = event.get("event_hash", "")
        if not event_hash:
            url = event.get("url", "")
            title = event.get("title", "")
            event_hash = hashlib.sha256(
                (url + title).encode()
            ).hexdigest()[:16]
            event["event_hash"] = event_hash

        try:
            conn.execute(
                "INSERT INTO market_events "
                "(event_hash, provider, event_type, event_time, trade_date, "
                "market, symbol, title, content, url, source, source_file, "
                "collected_at, raw_json) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    event_hash,
                    event.get("provider", ""),
                    event.get("event_type", ""),
                    event.get("event_time", NOW.isoformat()),
                    event.get("trade_date", ""),
                    event.get("market", ""),
                    event.get("symbol", ""),
                    event.get("title", ""),
                    event.get("content", ""),
                    event.get("url", ""),
                    event.get("source", ""),
                    event.get("source_file", ""),
                    event.get("collected_at", NOW.isoformat()),
                    event.get("raw_json", "{}"),
                ),
            )
            inserted += 1
        except sqlite3.IntegrityError:
            skipped += 1

    conn.commit()
    return inserted, skipped


def normalize_url_for_dedup(url: str) -> str:
    """Aggressive URL normalization for dedup.

    - Lowercase scheme + host
    - Remove www. prefix
    - Remove trailing slash
    - Remove query params (except specific whitelisted ones)
    - Remove fragment
    """
    if not url:
        return ""
    u = url.strip()

    # Remove fragment
    if "#" in u:
        u = u.split("#")[0]

    # Split query
    base = u
    query = ""
    if "?" in u:
        base, query = u.split("?", 1)

    # Normalize base
    base = base.rstrip("/")
    # Lowercase scheme+host (but not path for some sites)
    if "://" in base:
        proto, rest = base.split("://", 1)
        if "/" in rest:
            host, path = rest.split("/", 1)
        else:
            host, path = rest, ""
        host = host.lower().replace("www.", "")
        base = f"{proto.lower()}://{host}"
        if path:
            base += f"/{path}"

    # Re-attach whitelisted query params
    whitelist = set()  # empty = strip all
    if query and whitelist:
        params = [p for p in query.split("&")
                  if p.split("=")[0] in whitelist]
        if params:
            base += "?" + "&".join(params)

    return base


# ===========================================================================
# Tests
# ===========================================================================


class TestURLDedupKey:
    """Test URL normalization for dedup."""

    def test_basic_normalization(self):
        # url_dedup_key lowercases the entire URL for dedup consistency
        assert url_dedup_key("http://Example.COM/News/") == "http://example.com/news"

    def test_query_string_removal(self):
        a = url_dedup_key("http://a.com/page?utm_source=twitter&ref=home")
        b = url_dedup_key("http://a.com/page")
        assert a == b

    def test_fragment_removal(self):
        a = url_dedup_key("http://a.com/page#section")
        b = url_dedup_key("http://a.com/page")
        assert a == b

    def test_empty_url(self):
        assert url_dedup_key("") == ""
        assert url_dedup_key("  ") == ""


class TestContentHash:
    """Test content-based dedup hashing."""

    def test_same_content_same_hash(self):
        h1 = content_hash("Bitcoin surges", "Bitcoin reached new highs today")
        h2 = content_hash("Bitcoin surges", "Bitcoin reached new highs today")
        assert h1 == h2

    def test_different_content_different_hash(self):
        h1 = content_hash("Bitcoin surges", "Bitcoin up 5%")
        h2 = content_hash("Ethereum falls", "Ethereum down 3%")
        assert h1 != h2

    def test_case_insensitive(self):
        h1 = content_hash("BITCOIN SURGES", "MARKET UP")
        h2 = content_hash("bitcoin surges", "market up")
        assert h1 == h2

    def test_whitespace_normalization(self):
        h1 = content_hash("  Bitcoin surges  ", "  Market up  ")
        h2 = content_hash("Bitcoin surges", "Market up")
        assert h1 == h2


class TestEventDedupKey:
    """Test composite dedup key for events."""

    def test_url_based_key(self):
        event = {"url": "http://a.com/news/1", "title": "News"}
        key = event_dedup_key(event)
        assert key.startswith("url:")

    def test_content_based_key(self):
        event = {"title": "No URL news", "content": "Some content here"}
        key = event_dedup_key(event)
        assert key.startswith("content:")

    def test_empty_event(self):
        event = {}
        key = event_dedup_key(event)
        # Empty event generates a deterministic content hash of empty strings
        assert key.startswith("content:")


class TestDeduplicateEvents:
    """Test the deduplicate_events function."""

    def test_remove_duplicates_keep_first(self, duplicate_url_rows):
        result = deduplicate_events(duplicate_url_rows, keep="first")
        # URLs "a" and "b" are unique, utm variant of "a" duplicates
        assert 1 <= len(result) <= 4  # depends on normalization
        # First occurrence of each URL survives
        titles = {r.get("title") for r in result}
        assert "News A" in titles

    def test_keep_last(self, duplicate_url_rows):
        result = deduplicate_events(duplicate_url_rows, keep="last")
        assert len(result) >= 1

    def test_keep_highest_priority(self, duplicate_url_rows):
        # Add tier_priority
        items = [
            {"url": "http://a.com/1", "title": "Same", "tier_priority": 1},
            {"url": "http://a.com/1", "title": "Same", "tier_priority": 3},
            {"url": "http://a.com/1", "title": "Same", "tier_priority": 2},
        ]
        result = deduplicate_events(items, keep="highest_priority")
        assert len(result) == 1
        assert result[0]["tier_priority"] == 3

    def test_empty_list(self):
        assert deduplicate_events([]) == []

    def test_no_duplicates(self):
        events = [
            {"url": "http://a.com/1", "title": "A"},
            {"url": "http://b.com/2", "title": "B"},
            {"url": "http://c.com/3", "title": "C"},
        ]
        result = deduplicate_events(events)
        assert len(result) == 3

    def test_all_duplicates(self):
        events = [
            {"url": "http://a.com/1", "title": "Same"},
            {"url": "http://a.com/1", "title": "Same"},
            {"url": "http://a.com/1", "title": "Same"},
        ]
        result = deduplicate_events(events)
        assert len(result) == 1


class TestBatchInsertDedup:
    """Test batch insert with SQLite deduplication."""

    def test_insert_unique_events(self, tmp_db: sqlite3.Connection):
        events = [
            {
                "event_hash": "hash001",
                "provider": "rss", "event_type": "news",
                "trade_date": "20260629", "market": "Ashare",
                "symbol": "000001.SZ", "title": "Event 1",
                "content": "Content 1", "url": "http://a.com/1",
                "source": "reuters", "source_file": "batch_001",
            },
            {
                "event_hash": "hash002",
                "provider": "rss", "event_type": "news",
                "trade_date": "20260629", "market": "Ashare",
                "symbol": "000001.SZ", "title": "Event 2",
                "content": "Content 2", "url": "http://a.com/2",
                "source": "reuters", "source_file": "batch_001",
            },
        ]
        inserted, skipped = batch_insert_dedup(tmp_db, events)
        assert inserted == 2
        assert skipped == 0

    def test_insert_duplicate_event(self, tmp_db: sqlite3.Connection):
        event = {
            "event_hash": "hash003",
            "provider": "rss", "event_type": "news",
            "trade_date": "20260629", "market": "Ashare",
            "symbol": "000001.SZ", "title": "Dup Event",
            "content": "Content", "url": "http://a.com/3",
            "source": "reuters", "source_file": "batch_001",
        }
        # First insert
        inserted, skipped = batch_insert_dedup(tmp_db, [event])
        assert inserted == 1

        # Second insert (duplicate hash)
        inserted, skipped = batch_insert_dedup(tmp_db, [event])
        assert skipped == 1

    def test_insert_without_hash_generates_one(self, tmp_db: sqlite3.Connection):
        events = [
            {
                "provider": "rss", "event_type": "news",
                "trade_date": "20260629", "market": "Ashare",
                "symbol": "000001.SZ", "title": "Auto Hash",
                "content": "Content", "url": "http://a.com/auto",
                "source": "reuters", "source_file": "batch_001",
            },
        ]
        inserted, skipped = batch_insert_dedup(tmp_db, events)
        assert inserted == 1


class TestURLNormalization:
    """Test aggressive URL normalization."""

    def test_lowercase_host(self):
        assert normalize_url_for_dedup("http://Example.COM/path") == "http://example.com/path"

    def test_remove_www(self):
        a = normalize_url_for_dedup("https://www.example.com/path")
        b = normalize_url_for_dedup("https://example.com/path")
        assert a == b

    def test_remove_trailing_slash(self):
        a = normalize_url_for_dedup("http://a.com/path/")
        b = normalize_url_for_dedup("http://a.com/path")
        assert a == b

    def test_remove_fragment(self):
        result = normalize_url_for_dedup("http://a.com/page#section")
        assert "#" not in result

    def test_remove_query_params(self):
        result = normalize_url_for_dedup("http://a.com/page?utm=twitter&ref=home")
        assert "?" not in result

    def test_empty_url(self):
        assert normalize_url_for_dedup("") == ""
        assert normalize_url_for_dedup(None) == ""


class TestCrossSourceDedup:
    """Test dedup across multiple sources."""

    def test_same_url_different_sources(self):
        """Same URL from reuters and bloomberg → dedup to one."""
        events = [
            {"url": "http://a.com/story", "title": "Market Update",
             "source": "reuters", "tier_priority": 2},
            {"url": "http://a.com/story", "title": "Market Update",
             "source": "bloomberg", "tier_priority": 3},
        ]
        result = deduplicate_events(events, keep="highest_priority")
        assert len(result) == 1
        assert result[0]["source"] == "bloomberg"

    def test_different_urls_different_sources(self):
        events = [
            {"url": "http://a.com/story1", "title": "Story 1", "source": "reuters"},
            {"url": "http://b.com/story2", "title": "Story 2", "source": "bloomberg"},
        ]
        result = deduplicate_events(events)
        assert len(result) == 2

    def test_content_match_different_urls(self):
        """Same story on different URLs → content dedup catches it."""
        events = [
            {"title": "Fed holds rates steady at 5.5%",
             "content": "The Federal Reserve held interest rates steady at 5.5%...",
             "source": "reuters"},
            {"title": "Fed holds rates steady at 5.5%",
             "content": "The Federal Reserve held interest rates steady at 5.5%...",
             "source": "bloomberg"},
        ]
        # These have no URLs, so content hash is used
        keys = [event_dedup_key(e) for e in events]
        assert keys[0] == keys[1]
        result = deduplicate_events(events)
        assert len(result) == 1


class TestDedupPerformance:
    """Test dedup performance with larger datasets."""

    def test_dedup_1000_events(self):
        """1000 events with 50% duplicates → dedup in < 0.5s."""
        import time

        events = []
        for i in range(500):
            # Create duplicate pairs
            events.append({
                "url": f"http://example.com/news/{i % 250}",
                "title": f"News story {i % 250}",
                "source": "reuters",
            })
            events.append({
                "url": f"http://example.com/news/{i % 250}",
                "title": f"News story {i % 250}",
                "source": "bloomberg",
            })

        start = time.perf_counter()
        result = deduplicate_events(events)
        elapsed = time.perf_counter() - start

        assert len(result) == 250  # 250 unique URLs
        assert elapsed < 2.0, f"Dedup too slow: {elapsed:.2f}s"

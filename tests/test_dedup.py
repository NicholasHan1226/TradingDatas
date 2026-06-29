"""test_dedup.py — duplicate URLs, test deduplication logic.
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

import pytest

_SHARED = Path(__file__).resolve().parents[1]
if str(_SHARED) not in sys.path:
    sys.path.insert(0, str(_SHARED))


# ============================================================================
# Dedup utilities
# ============================================================================

def normalize_url(url: str) -> str:
    """Normalize a URL for dedup comparison.

    - Lowercase scheme and host
    - Remove default ports (80, 443)
    - Remove fragment
    - Sort query params
    - Strip trailing slash
    - Remove common tracking params (utm_*, ref, source, etc.)
    """
    TRACKING_PARAMS = {"utm_source", "utm_medium", "utm_campaign", "utm_term",
                       "utm_content", "ref", "source", "fbclid", "gclid",
                       "_ga", "mc_cid", "mc_eid"}

    parsed = urlparse(url)
    scheme = parsed.scheme.lower()
    netloc = parsed.netloc.lower()

    # Remove default port
    if (scheme == "http" and netloc.endswith(":80")):
        netloc = netloc[:-3]
    elif (scheme == "https" and netloc.endswith(":443")):
        netloc = netloc[:-4]

    # Normalize path: strip trailing slash unless root
    path = parsed.path
    if path.endswith("/") and path != "/":
        path = path.rstrip("/")

    # Sort and filter query params
    qs = parse_qs(parsed.query, keep_blank_values=True)
    clean_qs = {k: v for k, v in qs.items() if k.lower() not in TRACKING_PARAMS}
    query = urlencode(sorted(clean_qs.items()), doseq=True)

    # Rebuild without fragment
    return urlunparse((scheme, netloc, path, parsed.params, query, ""))


def dedup_by_url(
    rows: list[dict[str, Any]],
    url_field: str = "url",
    keep: str = "first",
) -> list[dict[str, Any]]:
    """Deduplicate rows by URL (after normalization).

    keep: "first" keeps first occurrence, "last" keeps last.
    """
    seen: dict[str, dict[str, Any]] = {}
    for row in rows:
        raw_url = row.get(url_field, "")
        if not raw_url:
            continue
        norm = normalize_url(raw_url)
        if norm not in seen or keep == "last":
            seen[norm] = row
    return list(seen.values())


def compute_event_hash(row: dict[str, Any]) -> str:
    """Compute a content-based hash for event dedup."""
    key = f"{row.get(title, )}|{row.get(url, )}|{row.get(source, )}"
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def dedup_by_hash(
    rows: list[dict[str, Any]],
    keep: str = "first",
) -> tuple[list[dict[str, Any]], int]:
    """Deduplicate rows by content hash. Returns (unique_rows, dup_count)."""
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    dup_count = 0
    for row in rows:
        h = compute_event_hash(row)
        if h not in seen:
            seen.add(h)
            unique.append(row)
        else:
            dup_count += 1
    return unique, dup_count


class TestURLNormalization:
    """Test URL normalization for dedup."""

    def test_identical_urls(self):
        url = "https://example.com/news/article"
        assert normalize_url(url) == normalize_url(url)

    def test_trailing_slash(self):
        a = normalize_url("https://example.com/news/")
        b = normalize_url("https://example.com/news")
        assert a == b

    def test_www_vs_non_www(self):
        """www vs non-www are NOT normalized (they could be different)."""
        a = normalize_url("https://www.example.com/news")
        b = normalize_url("https://example.com/news")
        assert a != b

    def test_tracking_params_stripped(self):
        a = normalize_url("https://example.com/news?utm_source=twitter")
        b = normalize_url("https://example.com/news")
        assert a == b

    def test_tracking_params_mixed(self):
        a = normalize_url("https://example.com/news?utm_source=fb&id=123")
        b = normalize_url("https://example.com/news?id=123&utm_campaign=launch")
        assert a == b

    def test_meaningful_params_preserved(self):
        a = normalize_url("https://example.com/news?id=123")
        b = normalize_url("https://example.com/news?id=456")
        assert a != b

    def test_fragment_removed(self):
        a = normalize_url("https://example.com/news#section1")
        b = normalize_url("https://example.com/news#section2")
        assert a == b

    def test_default_http_port_removed(self):
        a = normalize_url("http://example.com:80/news")
        b = normalize_url("http://example.com/news")
        assert a == b

    def test_default_https_port_removed(self):
        a = normalize_url("https://example.com:443/news")
        b = normalize_url("https://example.com/news")
        assert a == b

    def test_scheme_case_normalized(self):
        a = normalize_url("HTTPS://Example.COM/News")
        b = normalize_url("https://example.com/News")
        assert a == b

    def test_query_param_order_normalized(self):
        a = normalize_url("https://example.com?a=1&b=2")
        b = normalize_url("https://example.com?b=2&a=1")
        assert a == b

    def test_root_path(self):
        a = normalize_url("https://example.com/")
        b = normalize_url("https://example.com")
        # "/" is the root path so only the path-less case should match
        assert a == b  # netloc + empty path match


class TestURLDedup:
    """Test URL-based deduplication."""

    def test_exact_duplicate_urls(self, duplicate_url_rows):
        result = dedup_by_url(duplicate_url_rows)
        assert len(result) == 2  # News A (2 variants) merge to 1, + News B

    def test_first_occurrence_kept(self, duplicate_url_rows):
        result = dedup_by_url(duplicate_url_rows, keep="first")
        # First News A should be kept (source=rss_a)
        news_a = [r for r in result if "News A" in r["title"]]
        assert len(news_a) == 1
        assert news_a[0]["source"] == "rss_a"

    def test_last_occurrence_kept(self, duplicate_url_rows):
        result = dedup_by_url(duplicate_url_rows, keep="last")
        # Last News A should be kept (source=rss_c with tracking params)
        news_a = [r for r in result if "News A" in r["title"]]
        assert len(news_a) == 1
        assert news_a[0]["source"] == "rss_c"

    def test_normalized_duplicates_merged(self):
        rows = [
            {"url": "https://example.com/news/1?utm_source=x", "title": "T1"},
            {"url": "https://example.com/news/1", "title": "T2"},
        ]
        result = dedup_by_url(rows)
        assert len(result) == 1

    def test_different_urls_kept_separate(self):
        rows = [
            {"url": "https://example.com/a", "title": "A"},
            {"url": "https://example.com/b", "title": "B"},
            {"url": "https://other.com/c", "title": "C"},
        ]
        result = dedup_by_url(rows)
        assert len(result) == 3

    def test_empty_url_skipped(self):
        rows = [
            {"url": "", "title": "No URL"},
            {"url": "https://example.com/a", "title": "A"},
        ]
        result = dedup_by_url(rows)
        assert len(result) == 1  # empty URL row skipped

    def test_missing_url_field_skipped(self):
        rows = [
            {"title": "No URL field"},
            {"url": "https://example.com/a", "title": "A"},
        ]
        result = dedup_by_url(rows)
        assert len(result) == 1

    def test_empty_input(self):
        result = dedup_by_url([])
        assert result == []


class TestHashDedup:
    """Test content-hash-based deduplication."""

    def test_identical_content_produces_same_hash(self):
        row1 = {"title": "Same", "url": "https://a.com", "source": "rss1"}
        row2 = {"title": "Same", "url": "https://a.com", "source": "rss2"}
        assert compute_event_hash(row1) == compute_event_hash(row2)

    def test_different_content_different_hash(self):
        row1 = {"title": "A", "url": "https://a.com", "source": "rss"}
        row2 = {"title": "B", "url": "https://a.com", "source": "rss"}
        assert compute_event_hash(row1) != compute_event_hash(row2)

    def test_dedup_removes_duplicates(self):
        rows = [
            {"title": "Same", "url": "https://a.com", "source": "rss1"},
            {"title": "Same", "url": "https://a.com", "source": "rss2"},
            {"title": "Different", "url": "https://b.com", "source": "rss1"},
        ]
        unique, dup_count = dedup_by_hash(rows)
        assert len(unique) == 2
        assert dup_count == 1

    def test_dedup_empty_list(self):
        unique, dup_count = dedup_by_hash([])
        assert unique == []
        assert dup_count == 0

    def test_dedup_all_unique(self):
        rows = [
            {"title": "A", "url": "https://a.com", "source": "rss"},
            {"title": "B", "url": "https://b.com", "source": "rss"},
            {"title": "C", "url": "https://c.com", "source": "rss"},
        ]
        unique, dup_count = dedup_by_hash(rows)
        assert len(unique) == 3
        assert dup_count == 0

    def test_dedup_all_same(self):
        row = {"title": "Same", "url": "https://a.com", "source": "rss"}
        unique, dup_count = dedup_by_hash([row] * 10)
        assert len(unique) == 1
        assert dup_count == 9

    def test_dedup_cross_source(self):
        """Same content from different sources should be deduped."""
        rows = [
            {"title": "Event X", "url": "https://a.com/x", "source": "reuters"},
            {"title": "Event X", "url": "https://a.com/x", "source": "bloomberg"},
            {"title": "Event X", "url": "https://b.com/x", "source": "reuters"},
        ]
        unique, dup_count = dedup_by_hash(rows)
        assert len(unique) == 2  # row1==row2 deduped, row3 has different URL
        assert dup_count == 1

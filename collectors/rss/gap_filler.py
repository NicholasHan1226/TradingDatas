#!/usr/bin/env python3
"""Gap Filler — detect data gaps in S/A-tier sources, fill via Tavily search.

Reads the feed_fetch_history SQLite table to find date ranges where a source
(S-tier or A-tier) has zero items. For each gap, queries the Tavily Search API
to retrieve relevant news/articles, then writes filled items to the
market_events staging table with `confidence *= 0.7` and a source tag of
`gap_fill_tavily`.

Gap detection:
  - S-tier sources: gap if 0 items on a trading day
  - A-tier sources: gap if < 3 items on a trading day AND consecutive empty days >= 2

Output: gap_fill.json with fill results, per-source gap stats.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
import time
import urllib.request
import urllib.parse
import urllib.error
from datetime import datetime, date, timezone, timedelta
from pathlib import Path
from typing import Any, Optional

ROOT = Path(os.environ.get("MARKETGRAPH_ROOT", "/opt/investment/MarketGraph"))
INVEST = ROOT.parent
SHARED_SIGNALS = Path(os.environ.get("SHARED_SIGNALS_ROOT", "/opt/investment/SharedSignals"))
RUNTIME = Path(os.environ.get("MARKETGRAPH_RUNTIME", "/opt/investment/MarketGraphRuntime"))
LOG_DIR = SHARED_SIGNALS / "logs"
OUTPUT_DIR = SHARED_SIGNALS / "collectors" / "rss"

DEFAULT_DB = RUNTIME / "rss_collector.db"
DEFAULT_OUTPUT = OUTPUT_DIR / "gap_fill.json"
DEFAULT_GAP_CONFIG = OUTPUT_DIR / "gap_fill_config.json"

# Tavily API
TAVILY_API_URL = "https://api.tavily.com/search"
TAVILY_API_KEY = os.environ.get("TAVILY_API_KEY", "")
DEFAULT_SEARCH_DEPTH = "basic"
MAX_RESULTS_PER_GAP = 5
GAP_FILL_CONFIDENCE = 0.70

# Tier definitions for gap thresholds
TIER_GAP_THRESHOLDS = {
    "S": {"min_items_per_day": 1, "consecutive_empty_for_gap": 1},
    "A": {"min_items_per_day": 3, "consecutive_empty_for_gap": 2},
}

# Sources and their tiers / search queries for Tavily
DEFAULT_SOURCE_QUERIES: dict[str, dict[str, Any]] = {
    "cn_cls_telegraph": {
        "tier": "S",
        "name": "财联社电报",
        "query_template": "{name} 中国股市 财经快讯 site:cls.cn",
        "market_scope": "Ashare",
    },
    "cn_wallstreetcn_live": {
        "tier": "A",
        "name": "华尔街见闻",
        "query_template": "{name} 财经新闻 快讯 site:wallstreetcn.com",
        "market_scope": "Ashare",
    },
    "cn_caixin_rss": {
        "tier": "A",
        "name": "财新网",
        "query_template": "{name} 财经要闻 site:caixin.com",
        "market_scope": "Ashare",
    },
    "cn_gelonghui_live": {
        "tier": "A",
        "name": "格隆汇",
        "query_template": "{name} 财经快讯 site:gelonghui.com",
        "market_scope": "Ashare",
    },
    "cn_sina_rollnews": {
        "tier": "A",
        "name": "新浪财经",
        "query_template": "{name} 滚动新闻 site:finance.sina.com.cn",
        "market_scope": "Ashare",
    },
    "cn_10jqka_rtnews": {
        "tier": "A",
        "name": "同花顺",
        "query_template": "{name} 实时快讯 site:10jqka.com.cn",
        "market_scope": "Ashare",
    },
}


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


# ─── gap detection ─────────────────────────────────────────────────────────


def detect_gaps(
    db_path: Path = DEFAULT_DB,
    lookback_days: int = 14,
    source_queries: Optional[dict[str, dict[str, Any]]] = None,
) -> list[dict[str, Any]]:
    """Detect gaps in feed_fetch_history for S/A-tier sources.

    Returns list of gaps: {source_id, tier, gap_start, gap_end, gap_days, ...}
    """
    if source_queries is None:
        source_queries = DEFAULT_SOURCE_QUERIES

    gaps: list[dict[str, Any]] = []
    today = date.today()
    start_date = today - timedelta(days=lookback_days)

    try:
        conn = _connect(db_path)
    except Exception:
        return gaps

    for source_id, cfg in source_queries.items():
        tier = cfg.get("tier", "A")
        threshold = TIER_GAP_THRESHOLDS.get(tier, TIER_GAP_THRESHOLDS["A"])

        # Get daily item counts for this source
        # We need to map source_id → feed_url. Feed URLs are stored in feed_health.
        rows = conn.execute(
            "SELECT fh.feed_url FROM feed_health fh "
            "JOIN (SELECT 1) ON 1=1 "
            "WHERE fh.feed_url IN (SELECT feed_url FROM feed_fetch_history)"
        ).fetchall()

        # Build feed_url → source_id mapping from config knowledge
        # For now, use a simple heuristic: look for source_id patterns in config
        source_feeds = _find_feed_urls_for_source(conn, source_id)

        if not source_feeds:
            continue

        # For each feed URL, check daily coverage
        for feed_url in source_feeds:
            history_rows = conn.execute(
                "SELECT fetch_date, items_received, attempts, successes "
                "FROM feed_fetch_history "
                "WHERE feed_url = ? AND fetch_date >= ? AND fetch_date <= ? "
                "ORDER BY fetch_date",
                (feed_url, start_date.isoformat(), today.isoformat()),
            ).fetchall()

            existing_dates = {row["fetch_date"]: row for row in history_rows}

            # Walk date range and find gaps
            consecutive_empty = 0
            gap_start: Optional[str] = None

            d = start_date
            while d <= today:
                d_str = d.isoformat()
                row = existing_dates.get(d_str)
                items = row["items_received"] if row else 0

                if items < threshold["min_items_per_day"]:
                    consecutive_empty += 1
                    if gap_start is None:
                        gap_start = d_str
                else:
                    if consecutive_empty >= threshold["consecutive_empty_for_gap"] and gap_start:
                        gaps.append({
                            "source_id": source_id,
                            "feed_url": feed_url,
                            "tier": tier,
                            "source_name": cfg.get("name", source_id),
                            "gap_start": gap_start,
                            "gap_end": (d - timedelta(days=1)).isoformat(),
                            "gap_days": consecutive_empty,
                            "search_query": cfg.get("query_template", "").format(
                                name=cfg.get("name", source_id)
                            ),
                            "market_scope": cfg.get("market_scope", "Ashare"),
                        })
                    consecutive_empty = 0
                    gap_start = None

                d += timedelta(days=1)

            # Handle gap at end of range
            if consecutive_empty >= threshold["consecutive_empty_for_gap"] and gap_start:
                gaps.append({
                    "source_id": source_id,
                    "feed_url": feed_url,
                    "tier": tier,
                    "source_name": cfg.get("name", source_id),
                    "gap_start": gap_start,
                    "gap_end": today.isoformat(),
                    "gap_days": consecutive_empty,
                    "search_query": cfg.get("query_template", "").format(
                        name=cfg.get("name", source_id)
                    ),
                    "market_scope": cfg.get("market_scope", "Ashare"),
                })

    conn.close()
    return gaps


def _find_feed_urls_for_source(
    conn: sqlite3.Connection, source_id: str
) -> list[str]:
    """Find feed URLs associated with a source_id in the DB.

    Uses source_id patterns in feed_url or a source_map table.
    """
    # Strategy 1: Check if there's a source_map table
    try:
        rows = conn.execute(
            "SELECT feed_url FROM feed_health WHERE feed_url LIKE ?",
            (f"%{source_id}%",),
        ).fetchall()
        if rows:
            return [r["feed_url"] for r in rows]
    except Exception:
        pass

    # Strategy 2: Look for source_id patterns in known feed URLs
    # Map source_id to likely feed_url patterns
    known_patterns = {
        "cn_cls_telegraph": ["cls/telegraph", "cls"],
        "cn_wallstreetcn_live": ["wallstreetcn/live", "wallstreetcn"],
        "cn_caixin_rss": ["caixin/latest", "caixin"],
        "cn_gelonghui_live": ["gelonghui/live", "gelonghui"],
        "cn_sina_rollnews": ["sina/rollnews", "sina"],
        "cn_10jqka_rtnews": ["10jqka/realtimenews", "10jqka"],
    }
    patterns = known_patterns.get(source_id, [source_id])
    urls: list[str] = []
    for p in patterns:
        try:
            rows = conn.execute(
                "SELECT feed_url FROM feed_health WHERE feed_url LIKE ?",
                (f"%{p}%",),
            ).fetchall()
            urls.extend(r["feed_url"] for r in rows)
        except Exception:
            pass

    return list(set(urls))


# ─── Tavily search fill ─────────────────────────────────────────────────────


def tavily_search(
    query: str,
    api_key: str = "",
    max_results: int = MAX_RESULTS_PER_GAP,
    search_depth: str = DEFAULT_SEARCH_DEPTH,
) -> list[dict[str, Any]]:
    """Query Tavily Search API and return results."""
    if not api_key:
        api_key = TAVILY_API_KEY
    if not api_key:
        return []

    payload = json.dumps({
        "query": query,
        "search_depth": search_depth,
        "max_results": max_results,
        "include_answer": False,
        "include_raw_content": False,
        "include_images": False,
    }).encode("utf-8")

    req = urllib.request.Request(
        TAVILY_API_URL,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data.get("results", [])
    except Exception:
        return []


def fill_gap(
    gap: dict[str, Any],
    api_key: str = "",
    dry_run: bool = False,
) -> dict[str, Any]:
    """Fill a single gap using Tavily search.

    Returns fill result with items and metadata.
    """
    ts = datetime.now(timezone.utc).isoformat()
    result: dict[str, Any] = {
        "source_id": gap["source_id"],
        "gap_start": gap["gap_start"],
        "gap_end": gap["gap_end"],
        "gap_days": gap["gap_days"],
        "filled_at": ts,
        "items_filled": 0,
        "items": [],
        "error": "",
    }

    if dry_run:
        result["items_filled"] = 0
        result["note"] = "dry_run"
        return result

    search_query = gap.get("search_query", gap.get("source_name", ""))
    if not search_query:
        result["error"] = "no_search_query"
        return result

    search_results = tavily_search(
        query=search_query,
        api_key=api_key,
        max_results=MAX_RESULTS_PER_GAP,
    )

    for item in search_results:
        title = item.get("title", "")
        content = item.get("content", "")
        url = item.get("url", "")
        if not title:
            continue

        item_hash = hashlib.sha256(
            f"{url}|{title}".encode("utf-8")
        ).hexdigest()[:16]

        filled_item = {
            "event_hash": f"gapfill_{item_hash}",
            "title": title,
            "content": content[:500] if content else "",
            "url": url,
            "source": "tavily_gap_fill",
            "source_confidence": GAP_FILL_CONFIDENCE,
            "original_source_id": gap["source_id"],
            "original_source_name": gap.get("source_name", ""),
            "gap_period": f"{gap['gap_start']}→{gap['gap_end']}",
            "market_scope": gap.get("market_scope", "Ashare"),
            "collected_at": ts,
        }
        result["items"].append(filled_item)

    result["items_filled"] = len(result["items"])
    return result


# ─── main gap fill workflow ────────────────────────────────────────────────


def compute_gap_fill(
    db_path: Path = DEFAULT_DB,
    output_path: Optional[Path] = None,
    lookback_days: int = 14,
    api_key: str = "",
    dry_run: bool = False,
    max_gaps_to_fill: int = 10,
    log_results: bool = True,
) -> dict[str, Any]:
    """Detect gaps and fill them via Tavily.

    Returns summary dict with gaps found, filled, and per-source stats.
    """
    log_lines: list[str] = []
    now = datetime.now(timezone.utc)
    ts = now.isoformat()

    # Detect gaps
    try:
        gaps = detect_gaps(db_path=db_path, lookback_days=lookback_days)
    except Exception as e:
        log_lines.append(
            json.dumps({"ts": ts, "level": "ERROR", "module": "gap_filler",
                        "msg": f"gap_detection_failed: {e}"})
        )
        if log_results:
            _write_log(log_lines, "gap_filler")
        return {"gaps_found": 0, "gaps_filled": 0, "total_items_filled": 0, "results": []}

    if not gaps:
        log_lines.append(
            json.dumps({"ts": ts, "level": "INFO", "module": "gap_filler",
                        "msg": "no_gaps_detected"})
        )
        if log_results:
            _write_log(log_lines, "gap_filler")
        return {"gaps_found": 0, "gaps_filled": 0, "total_items_filled": 0, "results": []}

    log_lines.append(
        json.dumps({"ts": ts, "level": "INFO", "module": "gap_filler",
                    "msg": f"gaps_detected: {len(gaps)}"})
    )

    # Fill gaps (limit to max_gaps_to_fill)
    gaps_to_fill = gaps[:max_gaps_to_fill]
    fill_results: list[dict[str, Any]] = []
    total_items = 0

    for gap in gaps_to_fill:
        try:
            result = fill_gap(gap, api_key=api_key, dry_run=dry_run)
            fill_results.append(result)
            total_items += result["items_filled"]
            if result["error"]:
                log_lines.append(
                    json.dumps({
                        "ts": ts, "level": "WARN", "module": "gap_filler",
                        "source_id": gap["source_id"],
                        "msg": f"fill_error: {result[error]}"
                    })
                )
            else:
                log_lines.append(
                    json.dumps({
                        "ts": ts, "level": "INFO", "module": "gap_filler",
                        "source_id": gap["source_id"],
                        "gap_days": gap["gap_days"],
                        "msg": f"filled: {result[items_filled]} items"
                    })
                )
        except Exception as e:
            fill_results.append({
                "source_id": gap["source_id"],
                "gap_start": gap["gap_start"],
                "gap_end": gap["gap_end"],
                "items_filled": 0,
                "items": [],
                "error": str(e)[:200],
            })
            log_lines.append(
                json.dumps({"ts": ts, "level": "ERROR", "module": "gap_filler",
                            "source_id": gap["source_id"],
                            "msg": f"fill_exception: {e}"})
            )

    summary = {
        "generated_at": ts,
        "lookback_days": lookback_days,
        "dry_run": dry_run,
        "gaps_found": len(gaps),
        "gaps_filled": len(gaps_to_fill),
        "total_items_filled": total_items,
        "confidence_multiplier": GAP_FILL_CONFIDENCE,
        "results": fill_results,
    }

    # Write output
    if output_path:
        try:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, "w") as f:
                json.dump(summary, f, ensure_ascii=False, indent=2)
        except Exception as e:
            log_lines.append(
                json.dumps({"ts": ts, "level": "ERROR", "module": "gap_filler",
                            "msg": f"write_output_failed: {e}"})
            )

    if log_results:
        _write_log(log_lines, "gap_filler")

    return summary


def _write_log(lines: list[str], module_name: str) -> None:
    if not lines:
        return
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOG_DIR / f"{module_name}.jsonl"
    try:
        with open(log_path, "a") as f:
            for line in lines:
                f.write(line + "\n")
    except Exception:
        pass


# ─── self-test ─────────────────────────────────────────────────────────────


def _self_test() -> None:
    """Run self-test with synthetic feed_fetch_history data and verify gap detection."""
    import tempfile

    tmpdir = Path(tempfile.mkdtemp(prefix="gf_test_"))
    print("=== Gap Filler Self-Test ===")

    # Create test DB with feed_health and feed_fetch_history
    test_db = tmpdir / "test.db"
    conn = sqlite3.connect(str(test_db))
    conn.row_factory = sqlite3.Row

    conn.executescript("""
        CREATE TABLE IF NOT EXISTS feed_health (
            feed_url TEXT PRIMARY KEY, feed_name TEXT, tier TEXT DEFAULT \"warm\",
            last_success TEXT, last_failure TEXT,
            consecutive_failures INTEGER DEFAULT 0, status TEXT DEFAULT \"active\",
            items_seen INTEGER DEFAULT 0, items_filtered INTEGER DEFAULT 0,
            last_error TEXT
        );
        CREATE TABLE IF NOT EXISTS feed_fetch_history (
            feed_url TEXT NOT NULL, fetch_date TEXT NOT NULL,
            attempts INTEGER DEFAULT 0, successes INTEGER DEFAULT 0,
            items_received INTEGER DEFAULT 0,
            total_latency_ms REAL DEFAULT 0,
            latency_samples INTEGER DEFAULT 0,
            PRIMARY KEY (feed_url, fetch_date)
        );
    """)
    conn.commit()

    today = date.today()

    # Insert S-tier feed (cls/telegraph)
    conn.execute(
        "INSERT INTO feed_health (feed_url, feed_name, tier, status) VALUES (?, ?, ?, ?)",
        ("http://localhost:1200/cls/telegraph", "财联社电报", "hot", "active"),
    )

    # Insert A-tier feed (wallstreetcn)
    conn.execute(
        "INSERT INTO feed_health (feed_url, feed_name, tier, status) VALUES (?, ?, ?, ?)",
        ("http://localhost:1200/wallstreetcn/live", "华尔街见闻", "warm", "active"),
    )

    # Populate fetch history: S-tier has gaps on 3 consecutive days
    for i in range(14):
        d = (today - timedelta(days=i)).isoformat()
        # Days 3,4,5 ago → empty (gap of 3 days)
        if i in (3, 4, 5):
            conn.execute(
                "INSERT OR REPLACE INTO feed_fetch_history "
                "(feed_url, fetch_date, attempts, successes, items_received) VALUES (?,?,1,0,0)",
                ("http://localhost:1200/cls/telegraph", d),
            )
        else:
            conn.execute(
                "INSERT OR REPLACE INTO feed_fetch_history "
                "(feed_url, fetch_date, attempts, successes, items_received) VALUES (?,?,1,1,8)",
                ("http://localhost:1200/cls/telegraph", d),
            )

    # A-tier has 2 empty days → gap
    for i in range(14):
        d = (today - timedelta(days=i)).isoformat()
        if i in (6, 7):
            conn.execute(
                "INSERT OR REPLACE INTO feed_fetch_history "
                "(feed_url, fetch_date, attempts, successes, items_received) VALUES (?,?,1,0,0)",
                ("http://localhost:1200/wallstreetcn/live", d),
            )
        else:
            conn.execute(
                "INSERT OR REPLACE INTO feed_fetch_history "
                "(feed_url, fetch_date, attempts, successes, items_received) VALUES (?,?,1,1,5)",
                ("http://localhost:1200/wallstreetcn/live", d),
            )

    conn.commit()
    conn.close()

    # Detect gaps
    gaps = detect_gaps(db_path=test_db, lookback_days=14)

    print(f"  Gaps detected: {len(gaps)}")
    for g in gaps:
        print(f"  - {g['source_id']}: {g['gap_start']}→{g['gap_end']} ({g['gap_days']}d) "
              f"tier={g['tier']}")

    # Verify: S-tier gap should exist
    s_gaps = [g for g in gaps if "cls" in g["source_id"]]
    assert len(s_gaps) > 0, "Should detect S-tier gap"
    assert s_gaps[0]["gap_days"] >= 3, f"S-tier gap should be >= 3 days, got {s_gaps[0]['gap_days']}"
    print(f"  ✓ S-tier gap detected: {s_gaps[0]['gap_days']} days")

    # Verify: A-tier gap should exist
    a_gaps = [g for g in gaps if "wallstreetcn" in g["source_id"]]
    assert len(a_gaps) > 0, "Should detect A-tier gap"
    assert a_gaps[0]["gap_days"] >= 2, f"A-tier gap should be >= 2 days, got {a_gaps[0]['gap_days']}"
    print(f"  ✓ A-tier gap detected: {a_gaps[0]['gap_days']} days")

    # Test fill (dry run)
    if gaps:
        fill_result = fill_gap(gaps[0], dry_run=True)
        assert fill_result["items_filled"] == 0
        assert fill_result.get("note") == "dry_run"
        print(f"  ✓ Dry-run fill: {fill_result['items_filled']} items")

    # Test compute_gap_fill with dry_run
    output_path = tmpdir / "gap_fill.json"
    summary = compute_gap_fill(
        db_path=test_db,
        output_path=output_path,
        lookback_days=14,
        dry_run=True,
        max_gaps_to_fill=2,
    )
    assert summary["gaps_found"] > 0
    assert summary["dry_run"] is True
    print(f"  ✓ compute_gap_fill: {summary['gaps_found']} gaps found, "
          f"{summary['gaps_filled']} filled (dry_run)")

    # Verify output file
    with open(output_path) as f:
        output = json.load(f)
    assert output["gaps_found"] > 0
    print(f"  ✓ Output JSON written")

    print("=== Self-test PASSED ===")

    import shutil
    shutil.rmtree(tmpdir)


# ─── CLI ───────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Gap Filler — detect and fill data gaps in S/A-tier RSS sources"
    )
    parser.add_argument("--db", type=Path, default=DEFAULT_DB,
                        help="Path to rss_collector.db")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT,
                        help="Output JSON path")
    parser.add_argument("--lookback-days", type=int, default=14,
                        help="Days to look back for gaps")
    parser.add_argument("--tavily-key", type=str, default="",
                        help="Tavily API key (or set TAVILY_API_KEY env var)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Detect gaps only, do not search Tavily")
    parser.add_argument("--max-fills", type=int, default=10,
                        help="Max gaps to fill in one run")
    parser.add_argument("--self-test", action="store_true",
                        help="Run self-test with synthetic data")
    parser.add_argument("--json", action="store_true",
                        help="Output results as JSON to stdout")
    args = parser.parse_args()

    if args.self_test:
        _self_test()
        return

    try:
        api_key = args.tavily_key or TAVILY_API_KEY
        summary = compute_gap_fill(
            db_path=args.db,
            output_path=args.output,
            lookback_days=args.lookback_days,
            api_key=api_key,
            dry_run=args.dry_run,
            max_gaps_to_fill=args.max_fills,
        )
        if args.json:
            print(json.dumps(summary, ensure_ascii=False, indent=2))
        else:
            print(f"Gap Filler: {summary['gaps_found']} gaps found, "
                  f"{summary['gaps_filled']} filled, "
                  f"{summary['total_items_filled']} items → {args.output}")
            for r in summary.get("results", []):
                flag = f" ({r['items_filled']} items)" if r.get("items_filled") else " (0 items)"
                err = f" ERROR: {r.get('error', '')}" if r.get("error") else ""
                print(f"  {r.get('source_id', '?'):30s} "
                      f"{r.get('gap_start', '')}→{r.get('gap_end', '')}"
                      f" ({r.get('gap_days', 0)}d){flag}{err}")
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

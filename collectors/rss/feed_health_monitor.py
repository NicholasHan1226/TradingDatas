#!/usr/bin/env python3
"""Feed Health Monitor — per-feed success tracking, auto-classification, adaptive retry.

Reads the existing feed_health SQLite table (populated by RSSCollector/feed_store.py)
and enriches it with rolling 7-day metrics, feed grade, adaptive retry policy, and
suspicious-empty detection. Writes feed_health.json for downstream consumers.

Feed grades:
  healthy      >90% success rate (7d)  → 1 retry, full frequency
  intermittent 50-90%                  → 3 retries with exponential backoff
  degraded     10-50%                  → halved frequency, alert
  dead         <10%                    → paused, daily probe only

Suspicious empty: during A-share trading hours, 0 items when expected >5 → flag.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
from datetime import datetime, date, timezone, timedelta
from pathlib import Path
from typing import Any, Optional

ROOT = Path(os.environ.get("MARKETGRAPH_ROOT", "/opt/investment/MarketGraph"))
INVEST = ROOT.parent
SHARED_SIGNALS = Path(os.environ.get("SHARED_SIGNALS_ROOT", "/opt/investment/SharedSignals"))
RUNTIME = Path(os.environ.get("MARKETGRAPH_RUNTIME", "/opt/investment/MarketGraphRuntime"))
LOG_DIR = SHARED_SIGNALS / "logs"
OUTPUT_DIR = SHARED_SIGNALS / "collectors" / "rss"

# Default DB (same as RSSCollector)
DEFAULT_DB = RUNTIME / "rss_collector.db"
DEFAULT_OUTPUT = OUTPUT_DIR / "feed_health.json"

# A-share trading session times (Beijing time, Mon-Fri)
TRADING_START_HOUR = 9
TRADING_END_HOUR = 15
TRADING_LUNCH_START = 11
TRADING_LUNCH_END = 13

# Expected items per fetch, by tier (minimum for suspicious-empty check)
TIER_EXPECTED_ITEMS = {
    "hot": 5,    # financial wires should deliver consistently
    "warm": 3,
    "cold": 1,
}

# Feed grade thresholds
GRADE_THRESHOLDS = {
    "healthy": 0.90,
    "intermittent": 0.50,
    "degraded": 0.10,
    # below 0.10 → dead
}

# Retry policy by grade
RETRY_POLICY = {
    "healthy":      {"max_retries": 1, "backoff_base": 1.0},
    "intermittent": {"max_retries": 3, "backoff_base": 2.0},
    "degraded":     {"max_retries": 2, "backoff_base": 3.0, "halve_frequency": True},
    "dead":         {"max_retries": 0, "probe_only": True, "probe_interval_hours": 24},
}

# ─── sqlite helpers ────────────────────────────────────────────────────────


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def _ensure_schema(conn: sqlite3.Connection) -> None:
    """Extend feed_health table with latency tracking if not present."""
    # Check if feed_health table exists (created by feed_store.py)
    cur = conn.execute(
        "SELECT name FROM sqlite_master WHERE type=\"table\" AND name=\"feed_health\""
    )
    if not cur.fetchone():
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS feed_health (
                feed_url TEXT PRIMARY KEY,
                feed_name TEXT,
                tier TEXT DEFAULT \"warm\",
                last_success TEXT,
                last_failure TEXT,
                consecutive_failures INTEGER DEFAULT 0,
                status TEXT DEFAULT \"active\",
                items_seen INTEGER DEFAULT 0,
                items_filtered INTEGER DEFAULT 0,
                last_error TEXT
            );
            """
        )
    # Add latency columns if missing
    existing = {row["name"] for row in conn.execute("PRAGMA table_info(feed_health)")}
    if "avg_latency_ms" not in existing:
        conn.execute("ALTER TABLE feed_health ADD COLUMN avg_latency_ms REAL DEFAULT 0")
    if "latency_samples" not in existing:
        conn.execute("ALTER TABLE feed_health ADD COLUMN latency_samples INTEGER DEFAULT 0")
    if "last_latency_ms" not in existing:
        conn.execute("ALTER TABLE feed_health ADD COLUMN last_latency_ms REAL DEFAULT 0")
    if "history_days" not in existing:
        conn.execute("ALTER TABLE feed_health ADD COLUMN history_days INTEGER DEFAULT 0")
    conn.commit()

    # Create feed_fetch_history if not exists (daily aggregated stats)
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS feed_fetch_history (
            feed_url TEXT NOT NULL,
            fetch_date TEXT NOT NULL,
            attempts INTEGER DEFAULT 0,
            successes INTEGER DEFAULT 0,
            items_received INTEGER DEFAULT 0,
            total_latency_ms REAL DEFAULT 0,
            latency_samples INTEGER DEFAULT 0,
            PRIMARY KEY (feed_url, fetch_date)
        );
        """
    )
    conn.commit()


# ─── trading hours detection ───────────────────────────────────────────────


def _is_trading_hours(dt: Optional[datetime] = None) -> bool:
    """Check if current time is within A-share continuous trading (no lunch)."""
    if dt is None:
        dt = datetime.now()
    if dt.weekday() >= 5:  # Sat/Sun
        return False
    hour = dt.hour
    # Pre-market + morning session + afternoon session
    if TRADING_START_HOUR <= hour < TRADING_LUNCH_START:
        return True
    if TRADING_LUNCH_END <= hour < TRADING_END_HOUR:
        return True
    return False


def _is_trading_day(dt: Optional[datetime] = None) -> bool:
    """Check if today is a trading day, via market_calendar."""
    if dt is None:
        dt = datetime.now()
    try:
        sys.path.insert(0, str(SHARED_SIGNALS / "reference"))
        from market_calendar import is_trading_day as _cal_is_trading
        return _cal_is_trading(dt.date())
    except Exception:
        # Fallback: Mon-Fri
        return dt.weekday() < 5


# ─── feed grade classification ─────────────────────────────────────────────


def classify_feed(success_rate_7d: float) -> str:
    """Classify feed into grade based on 7-day success rate."""
    if success_rate_7d >= GRADE_THRESHOLDS["healthy"]:
        return "healthy"
    if success_rate_7d >= GRADE_THRESHOLDS["intermittent"]:
        return "intermittent"
    if success_rate_7d >= GRADE_THRESHOLDS["degraded"]:
        return "degraded"
    return "dead"


# ─── main health check ─────────────────────────────────────────────────────


def compute_feed_health(
    db_path: Path = DEFAULT_DB,
    lookback_days: int = 7,
    output_path: Optional[Path] = None,
    log_results: bool = True,
) -> list[dict[str, Any]]:
    """Compute health for all feeds and return list of feed health dicts.

    Errors are logged and skipped; this function never raises.
    """
    results: list[dict[str, Any]] = []
    log_lines: list[str] = []
    now = datetime.now(timezone.utc)
    today_str = now.strftime("%Y-%m-%d")
    ts = now.isoformat()

    try:
        conn = _connect(db_path)
        _ensure_schema(conn)
    except Exception as e:
        log_lines.append(
            json.dumps({"ts": ts, "level": "ERROR", "module": "feed_health_monitor",
                        "msg": f"db_connect_failed: {e}"})
        )
        if log_results:
            _write_log(log_lines, "feed_health_monitor")
        return results

    # Fetch all feeds
    try:
        feeds = conn.execute(
            "SELECT feed_url, feed_name, tier, last_success, last_failure, "
            "consecutive_failures, status, items_seen, items_filtered, last_error, "
            "avg_latency_ms, latency_samples, last_latency_ms "
            "FROM feed_health"
        ).fetchall()
    except Exception as e:
        log_lines.append(
            json.dumps({"ts": ts, "level": "ERROR", "module": "feed_health_monitor",
                        "msg": f"query_feeds_failed: {e}"})
        )
        if log_results:
            _write_log(log_lines, "feed_health_monitor")
        conn.close()
        return results

    # Compute start date for lookback
    start_date = (now - timedelta(days=lookback_days)).strftime("%Y-%m-%d")

    is_trading = _is_trading_day()
    is_trading_hrs = _is_trading_hours()

    for feed in feeds:
        feed_url = feed["feed_url"]
        feed_name = feed.get("feed_name", feed_url)
        tier = feed.get("tier", "warm")

        try:
            # --- 7-day success rate ---
            history_rows = conn.execute(
                "SELECT COALESCE(SUM(attempts),0) AS total_attempts, "
                "COALESCE(SUM(successes),0) AS total_successes, "
                "COALESCE(SUM(items_received),0) AS total_items, "
                "COALESCE(SUM(total_latency_ms),0) AS sum_latency, "
                "COALESCE(SUM(latency_samples),0) AS sum_latency_samples "
                "FROM feed_fetch_history "
                "WHERE feed_url = ? AND fetch_date >= ?",
                (feed_url, start_date),
            ).fetchone()

            total_attempts = history_rows["total_attempts"]
            total_successes = history_rows["total_successes"]
            total_items = history_rows["total_items"]
            sum_latency = history_rows["sum_latency"]
            sum_latency_samples = history_rows["sum_latency_samples"]

            success_rate_7d = (
                total_successes / total_attempts if total_attempts > 0 else 1.0
            )

            avg_latency = (
                sum_latency / sum_latency_samples if sum_latency_samples > 0 else 0
            )

            # --- feed grade ---
            grade = classify_feed(success_rate_7d)

            # --- consecutive failures (from feed_health) ---
            consecutive_failures = feed.get("consecutive_failures", 0) or 0

            # --- last success ---
            last_success = feed.get("last_success", "") or ""

            # --- adaptive retry policy ---
            policy = RETRY_POLICY.get(grade, RETRY_POLICY["healthy"])

            # --- suspicious empty ---
            suspicious_empty = False
            suspicious_reason = ""

            if is_trading and is_trading_hrs:
                expected = TIER_EXPECTED_ITEMS.get(tier, 3)
                if total_attempts > 0 and total_items == 0:
                    # Check if individual recent fetches returned 0
                    last_item_count = _get_last_fetch_items(conn, feed_url)
                    if last_item_count == 0 and expected > 0:
                        suspicious_empty = True
                        suspicious_reason = (
                            f"trading_hours_zero_items: expected>={expected}, got 0"
                        )

            # --- build result ---
            result = {
                "feed_url": feed_url,
                "feed_name": feed_name,
                "tier": tier,
                "grade": grade,
                "success_rate_7d": round(success_rate_7d, 4),
                "consecutive_failures": consecutive_failures,
                "last_success": last_success,
                "avg_latency_ms": round(avg_latency, 1),
                "total_attempts_7d": total_attempts,
                "total_successes_7d": total_successes,
                "total_items_7d": total_items,
                "retry_policy": policy,
                "suspicious_empty": suspicious_empty,
                "suspicious_reason": suspicious_reason,
                "checked_at": ts,
            }
            results.append(result)

        except Exception as e:
            log_lines.append(
                json.dumps({
                    "ts": ts, "level": "WARN", "module": "feed_health_monitor",
                    "feed_url": feed_url, "feed_name": feed_name,
                    "msg": f"compute_health_skip: {e}"
                })
            )
            # Still emit a degraded entry so consumers know the feed exists
            results.append({
                "feed_url": feed_url,
                "feed_name": feed_name,
                "tier": tier,
                "grade": "unknown",
                "success_rate_7d": 0,
                "consecutive_failures": feed.get("consecutive_failures", 0) or 0,
                "last_success": feed.get("last_success", "") or "",
                "avg_latency_ms": 0,
                "total_attempts_7d": 0,
                "total_successes_7d": 0,
                "total_items_7d": 0,
                "retry_policy": {"max_retries": 1, "backoff_base": 1.0},
                "suspicious_empty": False,
                "suspicious_reason": "",
                "checked_at": ts,
                "error": str(e)[:200],
            })

    conn.close()

    # Write output JSON
    if output_path:
        try:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output = {
                "generated_at": ts,
                "lookback_days": lookback_days,
                "is_trading_day": is_trading,
                "is_trading_hours": is_trading_hrs,
                "total_feeds": len(results),
                "feeds": results,
            }
            with open(output_path, "w") as f:
                json.dump(output, f, ensure_ascii=False, indent=2)
        except Exception as e:
            log_lines.append(
                json.dumps({"ts": ts, "level": "ERROR", "module": "feed_health_monitor",
                            "msg": f"write_output_failed: {e}"})
            )

    if log_results:
        _write_log(log_lines, "feed_health_monitor")

    return results


def _get_last_fetch_items(conn: sqlite3.Connection, feed_url: str) -> int:
    """Get items count from most recent fetch_history entry."""
    row = conn.execute(
        "SELECT items_received FROM feed_fetch_history "
        "WHERE feed_url = ? ORDER BY fetch_date DESC LIMIT 1",
        (feed_url,),
    ).fetchone()
    return row["items_received"] if row else -1


def _write_log(lines: list[str], module_name: str) -> None:
    """Append JSON log lines to log file."""
    if not lines:
        return
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOG_DIR / f"{module_name}.jsonl"
    try:
        with open(log_path, "a") as f:
            for line in lines:
                f.write(line + "\n")
    except Exception:
        pass  # Fail silently — logging is best-effort


# ─── self-test ─────────────────────────────────────────────────────────────


def _self_test() -> None:
    """Run self-test: create test DB, insert synthetic history, verify grades."""
    import tempfile

    tmpdir = Path(tempfile.mkdtemp(prefix="fh_test_"))
    test_db = tmpdir / "test.db"

    print("=== Feed Health Monitor Self-Test ===")

    # Init DB
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

    # Test feed: healthy (6/7 days success)
    conn.execute(
        "INSERT INTO feed_health (feed_url, feed_name, tier, last_success, consecutive_failures) "
        "VALUES (?, ?, ?, ?, ?)",
        ("http://localhost:1200/test/healthy", "Test Healthy", "hot",
         today.isoformat(), 0),
    )
    for i in range(7):
        d = (today - timedelta(days=i)).isoformat()
        success = 1 if i < 6 else 0
        conn.execute(
            "INSERT OR REPLACE INTO feed_fetch_history "
            "(feed_url, fetch_date, attempts, successes, items_received) VALUES (?,?,1,?,5)",
            ("http://localhost:1200/test/healthy", d, success),
        )

    # Test feed: intermittent (4/7 days = ~57%)
    conn.execute(
        "INSERT INTO feed_health (feed_url, feed_name, tier, last_failure, consecutive_failures) "
        "VALUES (?, ?, ?, ?, ?)",
        ("http://localhost:1200/test/intermittent", "Test Intermittent", "warm",
         today.isoformat(), 2),
    )
    for i in range(7):
        d = (today - timedelta(days=i)).isoformat()
        success = 1 if i < 4 else 0
        conn.execute(
            "INSERT OR REPLACE INTO feed_fetch_history "
            "(feed_url, fetch_date, attempts, successes, items_received) VALUES (?,?,1,?,3)",
            ("http://localhost:1200/test/intermittent", d, success),
        )

    # Test feed: dead (0/7 days)
    conn.execute(
        "INSERT INTO feed_health (feed_url, feed_name, tier, last_failure, consecutive_failures) "
        "VALUES (?, ?, ?, ?, ?)",
        ("http://localhost:1200/test/dead", "Test Dead", "cold",
         today.isoformat(), 10),
    )
    for i in range(7):
        d = (today - timedelta(days=i)).isoformat()
        conn.execute(
            "INSERT OR REPLACE INTO feed_fetch_history "
            "(feed_url, fetch_date, attempts, successes, items_received) VALUES (?,?,1,0,0)",
            ("http://localhost:1200/test/dead", d),
        )

    # Test feed: degraded (2/7 = ~28%)
    conn.execute(
        "INSERT INTO feed_health (feed_url, feed_name, tier, last_success, consecutive_failures) "
        "VALUES (?, ?, ?, ?, ?)",
        ("http://localhost:1200/test/degraded", "Test Degraded", "warm",
         today.isoformat(), 3),
    )
    for i in range(7):
        d = (today - timedelta(days=i)).isoformat()
        success = 1 if i < 2 else 0
        conn.execute(
            "INSERT OR REPLACE INTO feed_fetch_history "
            "(feed_url, fetch_date, attempts, successes, items_received) VALUES (?,?,1,?,1)",
            ("http://localhost:1200/test/degraded", d, success),
        )

    conn.commit()
    conn.close()

    # Run health check
    results = compute_feed_health(
        db_path=test_db, lookback_days=7, output_path=tmpdir / "feed_health.json",
        log_results=True,
    )

    # Verify
    grade_map = {r["feed_url"]: r["grade"] for r in results}
    print(f"  Feeds checked: {len(results)}")
    for url, grade in grade_map.items():
        rate = [r for r in results if r["feed_url"] == url][0]["success_rate_7d"]
        print(f"  {url.split('/')[-1]}: grade={grade}, rate={rate}")

    # Assertions
    assert grade_map.get("http://localhost:1200/test/healthy") == "healthy", \
        f"Expected healthy, got {grade_map.get(http://localhost:1200/test/healthy)}"
    assert grade_map.get("http://localhost:1200/test/intermittent") == "intermittent", \
        f"Expected intermittent, got {grade_map.get(http://localhost:1200/test/intermittent)}"
    assert grade_map.get("http://localhost:1200/test/degraded") == "degraded", \
        f"Expected degraded, got {grade_map.get(http://localhost:1200/test/degraded)}"
    assert grade_map.get("http://localhost:1200/test/dead") == "dead", \
        f"Expected dead, got {grade_map.get(http://localhost:1200/test/dead)}"

    # Verify retry policies
    assert results[0]["retry_policy"]["max_retries"] == 1  # healthy
    assert results[1]["retry_policy"]["max_retries"] == 3  # intermittent
    assert results[2]["retry_policy"]["max_retries"] == 0  # dead

    # Check output file
    with open(tmpdir / "feed_health.json") as f:
        output = json.load(f)
    assert output["total_feeds"] == 4
    assert "feeds" in output

    print("  ✓ All assertions passed")
    print("=== Self-test PASSED ===")

    # Cleanup
    import shutil
    shutil.rmtree(tmpdir)


# ─── CLI ───────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Feed Health Monitor — compute per-feed health grades"
    )
    parser.add_argument("--db", type=Path, default=DEFAULT_DB,
                        help="Path to rss_collector.db")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT,
                        help="Output JSON path")
    parser.add_argument("--lookback-days", type=int, default=7,
                        help="Days for success rate calculation")
    parser.add_argument("--self-test", action="store_true",
                        help="Run self-test with synthetic data")
    parser.add_argument("--json", action="store_true",
                        help="Output results as JSON to stdout")
    args = parser.parse_args()

    if args.self_test:
        _self_test()
        return

    try:
        results = compute_feed_health(
            db_path=args.db,
            lookback_days=args.lookback_days,
            output_path=args.output,
        )
        if args.json:
            print(json.dumps({
                "total_feeds": len(results),
                "feeds": results,
            }, ensure_ascii=False, indent=2))
        else:
            print(f"Feed Health Monitor: {len(results)} feeds checked → {args.output}")
            for r in results:
                flag = " ⚠" if r.get("suspicious_empty") else ""
                print(f"  {r[feed_name]:30s} {r[grade]:14s} rate={r[success_rate_7d]:.2%}{flag}")
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

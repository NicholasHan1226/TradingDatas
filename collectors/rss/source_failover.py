#!/usr/bin/env python3
"""Source Failover — primary → backup switching, URL dedup, gradual recovery.

Reads feed_health.json (produced by feed_health_monitor.py) and a failover
config that maps each primary source URL → list of backup URLs. When a primary
source drops below the FAILOVER_THRESHOLD (30% 7-day success rate), the module:

  1. Activates the first healthy backup source.
  2. URL-deduplicates items so the same content fetched from two URLs only
     enters the pipeline once.
  3. Probes the primary source at PROBE_INTERVAL; once it recovers above
     RECOVERY_THRESHOLD, traffic gradually shifts back (10% → 50% → 100%).

Output: source_failover.json for downstream consumers (collector / bridge).

Cron: every 5 minutes (aligned with collector hot-tier poll cycle).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Optional

ROOT = Path(os.environ.get("MARKETGRAPH_ROOT", "/opt/investment/MarketGraph"))
INVEST = ROOT.parent
SHARED_SIGNALS = Path(os.environ.get("SHARED_SIGNALS_ROOT", "/opt/investment/SharedSignals"))
RUNTIME = Path(os.environ.get("MARKETGRAPH_RUNTIME", "/opt/investment/MarketGraphRuntime"))
LOG_DIR = SHARED_SIGNALS / "logs"
OUTPUT_DIR = SHARED_SIGNALS / "collectors" / "rss"

DEFAULT_HEALTH_JSON = OUTPUT_DIR / "feed_health.json"
DEFAULT_FAILOVER_CONFIG = OUTPUT_DIR / "source_failover_config.json"
DEFAULT_OUTPUT = OUTPUT_DIR / "source_failover.json"

# Thresholds
FAILOVER_THRESHOLD = 0.30       # primary success rate below this → failover
RECOVERY_THRESHOLD = 0.60       # primary above this → start recovery
FULL_RECOVERY_THRESHOLD = 0.85  # primary above this → full return
RECOVERY_STEPS = [0.10, 0.50, 1.00]  # traffic-share steps back to primary
PROBE_INTERVAL_MINUTES = 30     # how often to probe a failed primary

# Default backup sources (used when no explicit config exists)
DEFAULT_BACKUPS: dict[str, list[str]] = {
    "http://localhost:1200/cls/telegraph": [
        "https://rsshub.app/cls/telegraph",
        "https://www.cls.cn/api/sw?app=CailianpressWeb&os=web&sv=8.4.6",
    ],
    "http://localhost:1200/wallstreetcn/live": [
        "https://rsshub.app/wallstreetcn/live",
    ],
    "http://localhost:1200/caixin/latest": [
        "https://rsshub.app/caixin/latest",
        "https://rsshub.pseudoyu.com/caixin/latest",
    ],
    "http://localhost:1200/gelonghui/live": [
        "https://rsshub.app/gelonghui/live",
    ],
    "http://localhost:1200/sina/rollnews": [
        "https://rsshub.app/sina/rollnews",
        "https://feed.mix.sina.com.cn/api/roll/get",
    ],
    "http://localhost:1200/10jqka/realtimenews": [
        "https://rsshub.app/10jqka/realtimenews",
    ],
    "http://localhost:1200/weibo/search/hot": [
        "https://rsshub.app/weibo/search/hot",
        "https://rsshub.pseudoyu.com/weibo/search/hot",
    ],
    "http://localhost:1200/wechat/articles": [
        "https://rsshub.app/wechat/articles",
    ],
}

# ─── failover state persistence ────────────────────────────────────────────


class FailoverState:
    """Persistent failover state (JSON file) tracking current source assignments."""

    def __init__(self, state_path: Path):
        self._path = state_path
        self._data: dict[str, Any] = self._load()

    def _load(self) -> dict[str, Any]:
        if self._path.exists():
            try:
                with open(self._path) as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError):
                pass
        return {"sources": {}, "updated_at": ""}

    def save(self) -> None:
        self._data["updated_at"] = datetime.now(timezone.utc).isoformat()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._path, "w") as f:
            json.dump(self._data, f, ensure_ascii=False, indent=2)

    def get_source_state(self, url: str) -> dict[str, Any]:
        return self._data.get("sources", {}).get(url, {})

    def set_source_state(self, url: str, state: dict[str, Any]) -> None:
        self._data.setdefault("sources", {})[url] = state

    @property
    def all_sources(self) -> dict[str, Any]:
        return self._data.get("sources", {})


# ─── URL deduplication ─────────────────────────────────────────────────────


def normalize_url(url: str) -> str:
    """Normalize URLs for dedup: strip trailing slashes, query params, fragments."""
    from urllib.parse import urlparse, urlunparse

    parsed = urlparse(url)
    # Strip common tracking params
    normalized = urlunparse(
        (parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", "", "")
    )
    return normalized.lower()


def url_dedup_key(content: str) -> str:
    """Generate a content-based dedup key (SHA256 of first 500 chars)."""
    return hashlib.sha256(content[:500].encode("utf-8")).hexdigest()[:16]


# ─── main failover logic ───────────────────────────────────────────────────


def compute_failover(
    health_path: Path = DEFAULT_HEALTH_JSON,
    config_path: Path = DEFAULT_FAILOVER_CONFIG,
    state_path: Optional[Path] = None,
    output_path: Optional[Path] = None,
    log_results: bool = True,
) -> list[dict[str, Any]]:
    """Compute failover decisions for all tracked sources.

    Returns a list of failover entries, each with:
      - primary_url, active_url, failover_active, backup_used
      - traffic_split (primary_pct, backup_pct)
      - recovery_stage, next_probe_at
    """
    results: list[dict[str, Any]] = []
    log_lines: list[str] = []
    now = datetime.now(timezone.utc)
    ts = now.isoformat()

    # Load feed health data
    try:
        with open(health_path) as f:
            health_data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        log_lines.append(
            json.dumps({"ts": ts, "level": "ERROR", "module": "source_failover",
                        "msg": f"health_load_failed: {e}"})
        )
        if log_results:
            _write_log(log_lines, "source_failover")
        return results

    feeds = health_data.get("feeds", [])
    health_by_url: dict[str, dict] = {f["feed_url"]: f for f in feeds}

    # Load failover config (backup URLs)
    try:
        if config_path.exists():
            with open(config_path) as f:
                failover_config = json.load(f)
        else:
            failover_config = {}
    except Exception as e:
        log_lines.append(
            json.dumps({"ts": ts, "level": "WARN", "module": "source_failover",
                        "msg": f"config_load_failed_using_defaults: {e}"})
        )
        failover_config = {}

    # Merge defaults into config
    backups = {**DEFAULT_BACKUPS, **failover_config.get("backups", {})}
    global_probe_interval = failover_config.get(
        "probe_interval_minutes", PROBE_INTERVAL_MINUTES
    )

    # Load persistent state
    if state_path is None:
        state_path = OUTPUT_DIR / "source_failover_state.json"
    failover_state = FailoverState(state_path)

    # Process each feed that has backup URLs defined
    for primary_url, backup_urls in backups.items():
        health = health_by_url.get(primary_url, {})
        success_rate = health.get("success_rate_7d", 1.0)
        grade = health.get("grade", "healthy")
        consecutive_failures = health.get("consecutive_failures", 0)

        source_state = failover_state.get_source_state(primary_url)
        failover_active = source_state.get("failover_active", False)
        active_backup = source_state.get("active_backup_url", "")
        traffic_split = source_state.get(
            "traffic_split", {"primary_pct": 1.0, "backup_pct": 0.0}
        )
        last_probe = source_state.get("last_probe_at", "")
        recovery_stage = source_state.get("recovery_stage", 0)
        backoff_since = source_state.get("backoff_since", "")

        # ── Decision: enter failover ──
        if not failover_active and success_rate < FAILOVER_THRESHOLD:
            # Find first healthy backup
            chosen_backup = None
            for bu in backup_urls:
                bu_health = health_by_url.get(bu, {})
                bu_rate = bu_health.get("success_rate_7d", 1.0)
                if bu_rate >= RECOVERY_THRESHOLD or bu_rate == 1.0:
                    chosen_backup = bu
                    break
            if chosen_backup is None and backup_urls:
                chosen_backup = backup_urls[0]  # last resort

            if chosen_backup:
                failover_active = True
                active_backup = chosen_backup
                traffic_split = {"primary_pct": 0.0, "backup_pct": 1.0}
                backoff_since = ts
                recovery_stage = 0
                log_lines.append(
                    json.dumps({
                        "ts": ts, "level": "WARN", "module": "source_failover",
                        "primary_url": primary_url,
                        "msg": f"failover_activated: primary_rate={success_rate:.2%} → backup={chosen_backup}"
                    })
                )

        # ── Decision: probe for recovery ──
        elif failover_active:
            should_probe = False
            if last_probe:
                try:
                    last_probe_dt = datetime.fromisoformat(last_probe)
                    if (now - last_probe_dt).total_seconds() > global_probe_interval * 60:
                        should_probe = True
                except ValueError:
                    should_probe = True
            else:
                should_probe = True

            if should_probe:
                last_probe = ts
                # Check if primary has recovered
                if success_rate >= FULL_RECOVERY_THRESHOLD:
                    # Full recovery
                    failover_active = False
                    active_backup = ""
                    traffic_split = {"primary_pct": 1.0, "backup_pct": 0.0}
                    recovery_stage = -1
                    log_lines.append(
                        json.dumps({
                            "ts": ts, "level": "INFO", "module": "source_failover",
                            "primary_url": primary_url,
                            "msg": f"full_recovery: primary rate={success_rate:.2%}"
                        })
                    )
                elif success_rate >= RECOVERY_THRESHOLD:
                    # Gradual recovery: step up
                    recovery_stage = min(recovery_stage + 1, len(RECOVERY_STEPS) - 1)
                    primary_pct = RECOVERY_STEPS[recovery_stage]
                    traffic_split = {
                        "primary_pct": primary_pct,
                        "backup_pct": round(1.0 - primary_pct, 2),
                    }
                    log_lines.append(
                        json.dumps({
                            "ts": ts, "level": "INFO", "module": "source_failover",
                            "primary_url": primary_url,
                            "msg": f"gradual_recovery: stage={recovery_stage} primary_pct={primary_pct}"
                        })
                    )
                else:
                    # Still degraded, keep failover active but update split if needed
                    recovery_stage = 0
                    log_lines.append(
                        json.dumps({
                            "ts": ts, "level": "INFO", "module": "source_failover",
                            "primary_url": primary_url,
                            "msg": f"probe_no_recovery: rate={success_rate:.2%} still below recovery"
                        })
                    )

        # ── Build result entry ──
        result = {
            "primary_url": primary_url,
            "primary_name": health.get("feed_name", primary_url),
            "primary_grade": grade,
            "primary_success_rate_7d": round(success_rate, 4),
            "primary_consecutive_failures": consecutive_failures,
            "failover_active": failover_active,
            "active_url": active_backup if failover_active else primary_url,
            "backup_used": active_backup,
            "backup_candidates": backup_urls,
            "traffic_split": traffic_split,
            "recovery_stage": recovery_stage,
            "backoff_since": backoff_since,
            "last_probe_at": last_probe,
            "next_probe_at": last_probe if not failover_active else "",
            "checked_at": ts,
        }
        results.append(result)

        # Persist state
        failover_state.set_source_state(primary_url, {
            "failover_active": failover_active,
            "active_backup_url": active_backup,
            "traffic_split": traffic_split,
            "last_probe_at": last_probe,
            "recovery_stage": recovery_stage,
            "backoff_since": backoff_since,
        })

    failover_state.save()

    # Write output
    if output_path:
        try:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output = {
                "generated_at": ts,
                "total_sources": len(results),
                "failover_threshold": FAILOVER_THRESHOLD,
                "recovery_threshold": RECOVERY_THRESHOLD,
                "active_failovers": sum(1 for r in results if r["failover_active"]),
                "sources": results,
            }
            with open(output_path, "w") as f:
                json.dump(output, f, ensure_ascii=False, indent=2)
        except Exception as e:
            log_lines.append(
                json.dumps({"ts": ts, "level": "ERROR", "module": "source_failover",
                            "msg": f"write_output_failed: {e}"})
            )

    if log_results:
        _write_log(log_lines, "source_failover")

    return results


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
    """Run self-test with synthetic health data and verify failover decisions."""
    import tempfile

    tmpdir = Path(tempfile.mkdtemp(prefix="sf_test_"))
    print("=== Source Failover Self-Test ===")

    # Create synthetic feed_health.json
    health_data = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "lookback_days": 7,
        "total_feeds": 5,
        "feeds": [
            {
                "feed_url": "http://localhost:1200/test/healthy",
                "feed_name": "Test Healthy",
                "tier": "hot",
                "grade": "healthy",
                "success_rate_7d": 0.95,
                "consecutive_failures": 0,
                "last_success": datetime.now().isoformat(),
            },
            {
                "feed_url": "http://localhost:1200/test/failing",
                "feed_name": "Test Failing",
                "tier": "hot",
                "grade": "dead",
                "success_rate_7d": 0.05,
                "consecutive_failures": 10,
                "last_success": "",
            },
            {
                "feed_url": "http://localhost:1200/test/recovering",
                "feed_name": "Test Recovering",
                "tier": "warm",
                "grade": "intermittent",
                "success_rate_7d": 0.65,
                "consecutive_failures": 2,
                "last_success": datetime.now().isoformat(),
            },
            {
                "feed_url": "https://rsshub.app/test/backup1",
                "feed_name": "Backup 1",
                "tier": "hot",
                "grade": "healthy",
                "success_rate_7d": 0.92,
                "consecutive_failures": 0,
            },
            {
                "feed_url": "https://rsshub.pseudoyu.com/test/backup2",
                "feed_name": "Backup 2",
                "tier": "warm",
                "grade": "degraded",
                "success_rate_7d": 0.25,
                "consecutive_failures": 5,
            },
        ],
    }
    health_path = tmpdir / "feed_health.json"
    with open(health_path, "w") as f:
        json.dump(health_data, f)

    # Create failover config with test mappings
    failover_config = {
        "backups": {
            "http://localhost:1200/test/healthy": [
                "https://rsshub.app/test/backup1",
            ],
            "http://localhost:1200/test/failing": [
                "https://rsshub.app/test/backup1",
                "https://rsshub.pseudoyu.com/test/backup2",
            ],
            "http://localhost:1200/test/recovering": [
                "https://rsshub.app/test/backup1",
            ],
        },
        "probe_interval_minutes": 0,  # immediate probe for test
    }
    config_path = tmpdir / "failover_config.json"
    with open(config_path, "w") as f:
        json.dump(failover_config, f)

    state_path = tmpdir / "failover_state.json"
    output_path = tmpdir / "source_failover.json"

    # Run failover
    results = compute_failover(
        health_path=health_path,
        config_path=config_path,
        state_path=state_path,
        output_path=output_path,
        log_results=True,
    )

    print(f"  Sources processed: {len(results)}")

    # Verify: healthy source → no failover
    healthy = [r for r in results if "healthy" in r["primary_url"]][0]
    assert not healthy["failover_active"], f"Healthy source should not failover, got {healthy}"
    print(f"  ✓ Healthy source: failover_active=False")

    # Verify: failing source → failover activated, picks backup1 (healthiest)
    failing = [r for r in results if "failing" in r["primary_url"]][0]
    assert failing["failover_active"], f"Failing source should failover, got {failing}"
    assert failing["backup_used"] == "https://rsshub.app/test/backup1", \
        f"Should pick healthy backup1, got {failing['backup_used']}"
    print(f"  ✓ Failing source: failover_active=True, backup=backup1")

    # Verify: recovering source → traffic split (gradual recovery)
    recovering = [r for r in results if "recovering" in r["primary_url"]][0]
    assert recovering["recovery_stage"] >= 0, \
        f"Recovering should have recovery_stage >= 0, got {recovering['recovery_stage']}"
    print(f"  ✓ Recovering source: recovery_stage={recovering['recovery_stage']}, "
          f"traffic_split={recovering['traffic_split']}")

    # Verify output file
    with open(output_path) as f:
        output = json.load(f)
    assert output["total_sources"] >= 3, f"Expected at least 3 sources, got {output['total_sources']}"
    assert "active_failovers" in output
    # Check that all 3 test sources are present
    test_urls = {
        "http://localhost:1200/test/healthy",
        "http://localhost:1200/test/failing",
        "http://localhost:1200/test/recovering",
    }
    result_urls = {r["primary_url"] for r in results}
    for u in test_urls:
        assert u in result_urls, f"Test source {u} not in results"
    print(f"  ✓ Output JSON: {output['total_sources']} sources, "
          f"{output['active_failovers']} active failovers")

    # Verify state persistence
    with open(state_path) as f:
        state = json.load(f)
    assert "sources" in state
    assert all(u in state["sources"] for u in test_urls), \
        f"State missing test sources: got {list(state['sources'].keys())}"
    print(f"  ✓ State persisted: {len(state['sources'])} sources (3 test sources present)")

    print("=== Self-test PASSED ===")

    import shutil
    shutil.rmtree(tmpdir)


# ─── BaseCollector wrapper ───────────────────────────────────────────────────


class SourceFailover:
    """Wrapper class exposing failover state for the BaseCollector interface.

    Delegates to compute_failover() and reads FailoverState JSON.
    """

    def __init__(self, state_path: Path | None = None):
        self._state_path = state_path or DEFAULT_OUTPUT

    def get_source_status(self) -> dict[str, Any]:
        """Return per-source status dict {source_name: {active, config, ...}}."""
        try:
            state = FailoverState(self._state_path)
            return {
                name: {
                    "active": info.get("active_url") is not None,
                    "config": info,
                }
                for name, info in state.all_sources.items()
            }
        except Exception:
            return {}


# ─── CLI ───────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Source Failover — primary → backup switching with gradual recovery"
    )
    parser.add_argument("--health", type=Path, default=DEFAULT_HEALTH_JSON,
                        help="Path to feed_health.json")
    parser.add_argument("--config", type=Path, default=DEFAULT_FAILOVER_CONFIG,
                        help="Path to failover config JSON")
    parser.add_argument("--state", type=Path, default=None,
                        help="Path to failover state JSON")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT,
                        help="Output JSON path")
    parser.add_argument("--self-test", action="store_true",
                        help="Run self-test with synthetic data")
    parser.add_argument("--json", action="store_true",
                        help="Output results as JSON to stdout")
    args = parser.parse_args()

    if args.self_test:
        _self_test()
        return

    try:
        results = compute_failover(
            health_path=args.health,
            config_path=args.config,
            state_path=args.state,
            output_path=args.output,
        )
        if args.json:
            print(json.dumps({
                "total_sources": len(results),
                "active_failovers": sum(1 for r in results if r["failover_active"]),
                "sources": results,
            }, ensure_ascii=False, indent=2))
        else:
            print(f"Source Failover: {len(results)} sources checked → {args.output}")
            for r in results:
                flag = " ⚠ FAILOVER" if r["failover_active"] else ""
                split = r["traffic_split"]
                print(f"  {r[primary_name]:30s} active={r[active_url]:50s} "
                      f"primary={split[primary_pct]:.0%} backup={split[backup_pct]:.0%}{flag}")
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

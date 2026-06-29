#!/usr/bin/env python3
"""RSSHub Route Healer — detect bad routes, switch nodes, fall back to direct fetch.

Monitors RSSHub routes (e.g. /cls/telegraph, /wallstreetcn/live) across multiple
RSSHub nodes. When a route fails consecutively on the active node, the module:

  1. Marks the route as `degraded` on the current node.
  2. Switches to the next healthy RSSHub node.
  3. If all nodes are degraded for a route, falls back to direct fetch (bypassing
     RSSHub entirely, fetching the original source URL directly).
  4. Periodically probes degraded routes to check for recovery.

Route health states: healthy / degraded(consecutive_failures) / dead_all_nodes / fallback_direct

RSSHub node hierarchy (priority order):
  primary   → http://localhost:1200          (local proxy)
  secondary → https://rsshub.app             (public instance)
  tertiary  → https://rsshub.pseudoyu.com    (community mirror)
  quaternary→ https://rsshub.rss3.io         (RSS3 instance)

Output: rsshub_route_health.json for downstream consumers (collector / proxy).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Optional

ROOT = Path(os.environ.get("MARKETGRAPH_ROOT", "/opt/investment/MarketGraph"))
INVEST = ROOT.parent
SHARED_SIGNALS = Path(os.environ.get("SHARED_SIGNALS_ROOT", "/opt/investment/SharedSignals"))
RUNTIME = Path(os.environ.get("MARKETGRAPH_RUNTIME", "/opt/investment/MarketGraphRuntime"))
LOG_DIR = SHARED_SIGNALS / "logs"
OUTPUT_DIR = SHARED_SIGNALS / "collectors" / "rss"

DEFAULT_OUTPUT = OUTPUT_DIR / "rsshub_route_health.json"
DEFAULT_STATE_PATH = OUTPUT_DIR / "rsshub_route_state.json"

# RSSHub nodes in priority order
RSSHUB_NODES: list[dict[str, str]] = [
    {"id": "local",       "url": "http://localhost:1200",          "label": "Local Proxy"},
    {"id": "rsshub_app",  "url": "https://rsshub.app",            "label": "RSSHub.app"},
    {"id": "pseudoyu",    "url": "https://rsshub.pseudoyu.com",   "label": "Pseudoyu Mirror"},
    {"id": "rss3",        "url": "https://rsshub.rss3.io",        "label": "RSS3 Mirror"},
]

# Routes to monitor (from collector config)
MONITORED_ROUTES: list[dict[str, Any]] = [
    {"route": "/cls/telegraph",       "name": "财联社电报",    "tier": "hot",
     "direct_url": "https://www.cls.cn/api/sw?app=CailianpressWeb&os=web&sv=8.4.6"},
    {"route": "/wallstreetcn/live",   "name": "华尔街见闻",    "tier": "hot",
     "direct_url": "https://api-one.wallstcn.com/apiv1/content/lives"},
    {"route": "/caixin/latest",       "name": "财新网",        "tier": "hot",
     "direct_url": "https://rsshub.app/caixin/latest"},
    {"route": "/gelonghui/live",      "name": "格隆汇",        "tier": "hot",
     "direct_url": "https://www.gelonghui.com/api/live"},
    {"route": "/sina/rollnews",       "name": "新浪滚动新闻",  "tier": "warm",
     "direct_url": "https://feed.mix.sina.com.cn/api/roll/get"},
    {"route": "/10jqka/realtimenews", "name": "同花顺快讯",    "tier": "warm",
     "direct_url": "https://rsshub.app/10jqka/realtimenews"},
    {"route": "/weibo/search/hot",    "name": "微博热搜",      "tier": "warm",
     "direct_url": "https://m.weibo.cn/api/container/getIndex?containerid=106003type%3D25"},
    {"route": "/wechat/articles",     "name": "微信公众号",    "tier": "warm",
     "direct_url": ""},
]

# Thresholds
DEGRADE_CONSECUTIVE_FAILURES = 3   # consecutive failures → mark route degraded
PROBE_INTERVAL_SECONDS = 300       # how often to probe degraded routes (5 min)
REQUEST_TIMEOUT_SECONDS = 15       # timeout for health check requests
RECOVERY_REQUIRED_SUCCESSES = 2    # consecutive successes needed to mark recovered


class RouteStateManager:
    """Persistent route health state (JSON)."""

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
        return {"routes": {}, "updated_at": ""}

    def save(self) -> None:
        self._data["updated_at"] = datetime.now(timezone.utc).isoformat()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._path, "w") as f:
            json.dump(self._data, f, ensure_ascii=False, indent=2)

    def get_route_state(self, route: str) -> dict[str, Any]:
        return self._data.get("routes", {}).get(route, {})

    def set_route_state(self, route: str, state: dict[str, Any]) -> None:
        self._data.setdefault("routes", {})[route] = state

    @property
    def all_routes(self) -> dict[str, Any]:
        return self._data.get("routes", {})


# ─── health check ──────────────────────────────────────────────────────────


def _probe_route(node_url: str, route: str, timeout: int = REQUEST_TIMEOUT_SECONDS) -> dict[str, Any]:
    """Probe a single route on a single node.

    Returns {ok, status_code, latency_ms, items_count, error}.
    """
    url = f"{node_url.rstrip('/')}{route}"
    start = time.monotonic()

    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "MarketGraph-RouteHealer/1.0",
                "Accept": "application/rss+xml, application/xml, application/json, */*",
            },
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            latency_ms = round((time.monotonic() - start) * 1000, 1)

            # Rough item count: count <item> tags or JSON array elements
            items_count = body.count("<item>") or body.count('"title"')

            return {
                "ok": True,
                "status_code": resp.status,
                "latency_ms": latency_ms,
                "items_count": items_count,
                "error": "",
            }
    except urllib.error.HTTPError as e:
        return {
            "ok": False,
            "status_code": e.code,
            "latency_ms": round((time.monotonic() - start) * 1000, 1),
            "items_count": 0,
            "error": f"HTTP {e.code}",
        }
    except urllib.error.URLError as e:
        return {
            "ok": False,
            "status_code": 0,
            "latency_ms": round((time.monotonic() - start) * 1000, 1),
            "items_count": 0,
            "error": str(e.reason)[:200],
        }
    except Exception as e:
        return {
            "ok": False,
            "status_code": 0,
            "latency_ms": round((time.monotonic() - start) * 1000, 1),
            "items_count": 0,
            "error": str(e)[:200],
        }


# ─── main route healing logic ──────────────────────────────────────────────


def compute_route_health(
    routes: Optional[list[dict[str, Any]]] = None,
    nodes: Optional[list[dict[str, str]]] = None,
    state_path: Optional[Path] = None,
    output_path: Optional[Path] = None,
    probe_all: bool = False,
    log_results: bool = True,
) -> list[dict[str, Any]]:
    """Check health of all routes across all nodes and compute healing decisions.

    Returns list of route health entries.
    """
    if routes is None:
        routes = MONITORED_ROUTES
    if nodes is None:
        nodes = RSSHUB_NODES
    if state_path is None:
        state_path = DEFAULT_STATE_PATH

    results: list[dict[str, Any]] = []
    log_lines: list[str] = []
    now = datetime.now(timezone.utc)
    ts = now.isoformat()

    state_mgr = RouteStateManager(state_path)

    for route_cfg in routes:
        route_path = route_cfg["route"]
        route_name = route_cfg.get("name", route_path)
        tier = route_cfg.get("tier", "warm")
        direct_url = route_cfg.get("direct_url", "")

        prev_state = state_mgr.get_route_state(route_path)
        active_node_id = prev_state.get("active_node_id", nodes[0]["id"] if nodes else "")
        degraded_nodes: dict[str, dict] = prev_state.get("degraded_nodes", {})
        consecutive_ok = prev_state.get("consecutive_ok", 0)
        fallback_direct = prev_state.get("fallback_direct", False)

        # Probe active node (unless probing all)
        if probe_all:
            nodes_to_probe = nodes
        else:
            nodes_to_probe = [n for n in nodes if n["id"] == active_node_id]
            # Also probe degraded nodes to check recovery
            for node in nodes:
                if node["id"] in degraded_nodes and node["id"] != active_node_id:
                    last_probe = degraded_nodes[node["id"]].get("last_probe_at", "")
                    if last_probe:
                        try:
                            last_probe_dt = datetime.fromisoformat(last_probe)
                            if (now - last_probe_dt).total_seconds() > PROBE_INTERVAL_SECONDS:
                                nodes_to_probe.append(node)
                        except ValueError:
                            nodes_to_probe.append(node)
                    else:
                        nodes_to_probe.append(node)

        node_results: list[dict[str, Any]] = []

        for node in nodes_to_probe:
            probe = _probe_route(node["url"], route_path)
            node_result = {
                "node_id": node["id"],
                "node_url": node["url"],
                "ok": probe["ok"],
                "status_code": probe["status_code"],
                "latency_ms": probe["latency_ms"],
                "items_count": probe["items_count"],
                "error": probe["error"],
            }
            node_results.append(node_result)

            # Update degraded node tracking
            if probe["ok"]:
                if node["id"] in degraded_nodes:
                    del degraded_nodes[node["id"]]
                    log_lines.append(
                        json.dumps({
                            "ts": ts, "level": "INFO", "module": "rsshub_route_healer",
                            "route": route_path, "node_id": node["id"],
                            "msg": f"node_recovered: {node[id]}"
                        })
                    )
            else:
                if node["id"] not in degraded_nodes:
                    degraded_nodes[node["id"]] = {
                        "consecutive_failures": 1,
                        "first_failure_at": ts,
                        "last_probe_at": ts,
                        "last_error": probe["error"],
                    }
                else:
                    degraded_nodes[node["id"]]["consecutive_failures"] += 1
                    degraded_nodes[node["id"]]["last_probe_at"] = ts
                    degraded_nodes[node["id"]]["last_error"] = probe["error"]

        # ── Determine active node / fallback decision ──
        active_node = next((n for n in node_results if n["node_id"] == active_node_id), None)

        if active_node and active_node["ok"]:
            # Active node is healthy
            consecutive_ok += 1
        elif active_node and not active_node["ok"]:
            # Active node failed
            consecutive_ok = 0
            failures = degraded_nodes.get(active_node_id, {}).get("consecutive_failures", 0)

            if failures >= DEGRADE_CONSECUTIVE_FAILURES:
                log_lines.append(
                    json.dumps({
                        "ts": ts, "level": "WARN", "module": "rsshub_route_healer",
                        "route": route_path, "node_id": active_node_id,
                        "msg": f"node_degraded: {failures} consecutive failures"
                    })
                )
                # Switch to next healthy node
                new_active = None
                for node in nodes:
                    if node["id"] not in degraded_nodes:
                        node_probe = next(
                            (n for n in node_results if n["node_id"] == node["id"]), None
                        )
                        if node_probe is None:
                            # Need to probe this node
                            node_probe_raw = _probe_route(node["url"], route_path)
                            node_probe = {
                                "node_id": node["id"],
                                "node_url": node["url"],
                                "ok": node_probe_raw["ok"],
                                "status_code": node_probe_raw["status_code"],
                                "latency_ms": node_probe_raw["latency_ms"],
                                "items_count": node_probe_raw["items_count"],
                                "error": node_probe_raw["error"],
                            }
                            node_results.append(node_probe)

                        if node_probe["ok"]:
                            new_active = node
                            break

                if new_active:
                    active_node_id = new_active["id"]
                    consecutive_ok = 0
                    fallback_direct = False
                    log_lines.append(
                        json.dumps({
                            "ts": ts, "level": "WARN", "module": "rsshub_route_healer",
                            "route": route_path,
                            "msg": f"switched_node: {active_node_id}→{new_active[id]}"
                        })
                    )
                else:
                    # All nodes degraded → fall back to direct fetch
                    if direct_url:
                        fallback_direct = True
                        active_node_id = ""
                        log_lines.append(
                            json.dumps({
                                "ts": ts, "level": "ERROR", "module": "rsshub_route_healer",
                                "route": route_path,
                                "msg": "all_nodes_degraded: activating direct fetch fallback"
                            })
                        )
                    else:
                        log_lines.append(
                            json.dumps({
                                "ts": ts, "level": "ERROR", "module": "rsshub_route_healer",
                                "route": route_path,
                                "msg": "all_nodes_degraded_no_direct_url: route is dead"
                            })
                        )

        # ── Check recovery from fallback_direct ──
        if fallback_direct:
            # Periodically probe nodes to see if any recovered
            for node in nodes:
                if node["id"] not in degraded_nodes:
                    probe = _probe_route(node["url"], route_path)
                    if probe["ok"]:
                        active_node_id = node["id"]
                        fallback_direct = False
                        consecutive_ok = 1
                        log_lines.append(
                            json.dumps({
                                "ts": ts, "level": "INFO", "module": "rsshub_route_healer",
                                "route": route_path, "node_id": node["id"],
                                "msg": "recovered_from_fallback: node healthy again"
                            })
                        )
                        break

        # ── Determine overall state ──
        if fallback_direct:
            health_state = "fallback_direct"
        elif len(degraded_nodes) >= len(nodes):
            health_state = "dead_all_nodes"
        elif degraded_nodes:
            health_state = "degraded"
        else:
            health_state = "healthy"

        # ── Build result ──
        result = {
            "route": route_path,
            "name": route_name,
            "tier": tier,
            "direct_url": direct_url,
            "health_state": health_state,
            "active_node_id": active_node_id,
            "fallback_direct": fallback_direct,
            "consecutive_ok": consecutive_ok,
            "degraded_nodes": {
                nid: {
                    "consecutive_failures": d["consecutive_failures"],
                    "last_error": d.get("last_error", ""),
                }
                for nid, d in degraded_nodes.items()
            },
            "node_results": node_results,
            "total_nodes": len(nodes),
            "healthy_nodes": len(nodes) - len(degraded_nodes),
            "checked_at": ts,
        }
        results.append(result)

        # Persist state
        state_mgr.set_route_state(route_path, {
            "active_node_id": active_node_id,
            "degraded_nodes": degraded_nodes,
            "consecutive_ok": consecutive_ok,
            "fallback_direct": fallback_direct,
            "last_checked_at": ts,
        })

    state_mgr.save()

    # Write output
    if output_path:
        try:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output = {
                "generated_at": ts,
                "total_routes": len(results),
                "healthy_routes": sum(1 for r in results if r["health_state"] == "healthy"),
                "degraded_routes": sum(1 for r in results if r["health_state"] == "degraded"),
                "fallback_routes": sum(1 for r in results if r["health_state"] == "fallback_direct"),
                "dead_routes": sum(1 for r in results if r["health_state"] == "dead_all_nodes"),
                "nodes_available": len(nodes),
                "routes": results,
            }
            with open(output_path, "w") as f:
                json.dump(output, f, ensure_ascii=False, indent=2)
        except Exception as e:
            log_lines.append(
                json.dumps({"ts": ts, "level": "ERROR", "module": "rsshub_route_healer",
                            "msg": f"write_output_failed: {e}"})
            )

    if log_results:
        _write_log(log_lines, "rsshub_route_healer")

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
    """Run self-test with localhost probe and verify state transitions."""
    import tempfile

    tmpdir = Path(tempfile.mkdtemp(prefix="rrh_test_"))
    print("=== RSSHub Route Healer Self-Test ===")

    # Test routes (use real localhost route that may or may not exist)
    test_routes = [
        {
            "route": "/cls/telegraph",
            "name": "财联社电报",
            "tier": "hot",
            "direct_url": "https://www.cls.cn/api/sw",
        },
        {
            "route": "/nonexistent/test/route/xyz",
            "name": "Bad Route",
            "tier": "warm",
            "direct_url": "https://example.com",
        },
    ]

    # Test nodes — only probe localhost (which may or may not be running)
    test_nodes = [{"id": "local", "url": "http://localhost:1200", "label": "Local"}]

    state_path = tmpdir / "route_state.json"
    output_path = tmpdir / "route_health.json"

    results = compute_route_health(
        routes=test_routes,
        nodes=test_nodes,
        state_path=state_path,
        output_path=output_path,
        probe_all=True,
        log_results=True,
    )

    print(f"  Routes checked: {len(results)}")
    for r in results:
        print(f"  - {r['name']} ({r['route']}): state={r['health_state']}, "
              f"active_node={r['active_node_id']}, healthy_nodes={r['healthy_nodes']}")

    # Verify: results should exist with valid structure
    assert len(results) == 2, f"Expected 2 routes, got {len(results)}"
    for r in results:
        assert "health_state" in r
        assert "active_node_id" in r
        assert "node_results" in r
        assert len(r["node_results"]) > 0

    print(f"  ✓ All routes have valid health_state and node_results")

    # Verify output file
    with open(output_path) as f:
        output = json.load(f)
    assert output["total_routes"] == 2
    print(f"  ✓ Output JSON: {output['total_routes']} routes")

    # Verify state persistence
    with open(state_path) as f:
        state = json.load(f)
    assert "routes" in state
    print(f"  ✓ State persisted: {len(state['routes'])} routes")

    # Verify probe results for the bad route
    bad_route = [r for r in results if "nonexistent" in r["route"]][0]
    bad_probe = bad_route["node_results"][0]
    # The bad route should fail (404 or connection error)
    assert not bad_probe["ok"], f"Bad route should fail, got ok={bad_probe['ok']}"
    print(f"  ✓ Bad route correctly identified as failing: error={bad_probe['error']}")

    # Test consecutive failure tracking
    # Run again to increment failures
    results2 = compute_route_health(
        routes=test_routes,
        nodes=test_nodes,
        state_path=state_path,
        probe_all=True,
        log_results=False,
    )
    bad_route2 = [r for r in results2 if "nonexistent" in r["route"]][0]
    failed_nodes = bad_route2.get("degraded_nodes", {})
    # After 2 probes with failures, should have 2+ consecutive failures
    local_fails = failed_nodes.get("local", {}).get("consecutive_failures", 0)
    assert local_fails >= 2, f"Should have >=2 consecutive failures, got {local_fails}"
    print(f"  ✓ Consecutive failure tracking: {local_fails} failures for bad route")

    # Verify that with 3+ failures, state transitions from fallback_direct
    # (since we only have 1 node and it's bad, after DEGRADE threshold)
    if bad_route2.get("fallback_direct"):
        print(f"  ✓ Fallback to direct fetch activated (single node degraded)")

    print("=== Self-test PASSED ===")

    # Cleanup
    import shutil
    shutil.rmtree(tmpdir)


# ─── CLI ───────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(
        description="RSSHub Route Healer — detect bad routes, switch nodes, fallback to direct"
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT,
                        help="Output JSON path")
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE_PATH,
                        help="State persistence JSON path")
    parser.add_argument("--probe-all", action="store_true",
                        help="Probe all nodes (not just active)")
    parser.add_argument("--self-test", action="store_true",
                        help="Run self-test with real localhost probes")
    parser.add_argument("--json", action="store_true",
                        help="Output results as JSON to stdout")
    args = parser.parse_args()

    if args.self_test:
        _self_test()
        return

    try:
        results = compute_route_health(
            routes=MONITORED_ROUTES,
            nodes=RSSHUB_NODES,
            state_path=args.state,
            output_path=args.output,
            probe_all=args.probe_all,
        )
        if args.json:
            print(json.dumps({
                "total_routes": len(results),
                "healthy_routes": sum(1 for r in results if r["health_state"] == "healthy"),
                "degraded_routes": sum(1 for r in results if r["health_state"] == "degraded"),
                "fallback_routes": sum(1 for r in results if r["health_state"] == "fallback_direct"),
                "routes": results,
            }, ensure_ascii=False, indent=2))
        else:
            state_counts = {}
            for r in results:
                s = r["health_state"]
                state_counts[s] = state_counts.get(s, 0) + 1
            print(f"RSSHub Route Healer: {len(results)} routes checked → {args.output}")
            for state, count in sorted(state_counts.items()):
                print(f"  {state}: {count}")
            for r in results:
                flag = ""
                if r["health_state"] == "fallback_direct":
                    flag = " ⚠ FALLBACK"
                elif r["health_state"] == "degraded":
                    flag = " ⚡ DEGRADED"
                elif r["health_state"] == "dead_all_nodes":
                    flag = " ☠ DEAD"
                print(f"  {r[route]:35s} {r[name]:20s} {r[health_state]:20s} "
                      f"node={r[active_node_id] or 'direct':15s}{flag}")
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""SharedSignals unified scheduler — runs merge + patrol + heal on a single cadence.

Usage:
    python3 scheduler.py                    # run once: merge → patrol → heal
    python3 scheduler.py --interval 300     # continuous loop every 300s
    python3 scheduler.py --dry-run          # preview only

Replaces the need for separate cron entries — one process, one cadence.
Still compatible with individual cron wrappers for production fine-tuning.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

_THIS = Path(__file__).resolve().parent
_LOG_DIR = _THIS / "logs"

logger = logging.getLogger("scheduler")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )


def run_step(name: str, args: list[str], timeout: int = 120) -> dict:
    """Run a subprocess step, return result dict."""
    started = time.monotonic()
    result = {
        "step": name,
        "started_at": utc_now(),
        "rc": -1,
        "elapsed_s": 0,
        "ok": False,
        "output": "",
    }
    try:
        proc = subprocess.run(
            [sys.executable] + args,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(_THIS),
        )
        result["rc"] = proc.returncode
        result["output"] = (proc.stdout + proc.stderr)[:2000]
        result["ok"] = proc.returncode == 0
    except subprocess.TimeoutExpired:
        result["output"] = f"timed out after {timeout}s"
    except Exception as exc:
        result["output"] = str(exc)
    result["elapsed_s"] = round(time.monotonic() - started, 1)
    return result


def _run_step_direct(name: str, started: float, ok: bool, output: str, elapsed_override: float | None = None) -> dict:
    """Build a result dict for a direct-import step."""
    return {
        "step": name,
        "started_at": utc_now(),
        "rc": 0 if ok else 1,
        "elapsed_s": elapsed_override if elapsed_override is not None else round(time.monotonic() - started, 1),
        "ok": ok,
        "output": output,
    }


def run_cycle(dry_run: bool = False, use_subprocess: bool = False) -> dict:
    """Run one full cycle: merge → patrol → (conditional) heal.

    Defaults to direct Python imports. Pass use_subprocess=True for the
    legacy subprocess approach (e.g. from --use-subprocess CLI flag).
    """
    results: dict = {}
    total_started = time.monotonic()

    # ---- 1. DuckDB merge ----
    if not use_subprocess:
        try:
            t0 = time.monotonic()
            from duckdb_merge import run_merge
            merge_result = run_merge(table="", dry_run=dry_run)
            ok = merge_result.get("status") == "ok" or merge_result.get("status") == "dry_run"
            output = json.dumps(merge_result, ensure_ascii=False)
            results["merge"] = _run_step_direct("merge", t0, ok, output)
        except Exception as exc:
            logger.warning("direct merge failed (%s), falling back to subprocess", exc)
            use_subprocess = True

    if use_subprocess:
        merge_args = ["duckdb_merge.py", "--json", "--no-record"]
        if dry_run:
            merge_args.append("--dry-run")
        results["merge"] = run_step("merge", merge_args, timeout=300)

    # ---- 2. Patrol ----
    if not use_subprocess:
        try:
            t0 = time.monotonic()
            from patrol import run_checks, CHECKS_MAP
            patrol_result = run_checks(list(CHECKS_MAP.keys()))
            output = json.dumps(patrol_result, ensure_ascii=False)
            ok = True  # run_checks always returns a dict (no exceptions means ok)
            results["patrol"] = _run_step_direct("patrol", t0, ok, output)
        except Exception as exc:
            logger.warning("direct patrol failed (%s), falling back to subprocess", exc)
            use_subprocess = True

    if use_subprocess:
        patrol_args = ["patrol.py", "--json", "--check", "all"]
        if dry_run:
            patrol_args.append("--no-record")
        results["patrol"] = run_step("patrol", patrol_args, timeout=60)

    # ---- 3. Heal (only if patrol found issues) ----
    patrol_output = results["patrol"]["output"]
    patrol_data: dict = {}
    try:
        patrol_data = json.loads(
            patrol_output.split("\n")[0]
            if "\n" in patrol_output
            else patrol_output
        )
    except Exception:
        pass

    score = patrol_data.get("overall_score", 0)
    max_score_p = patrol_data.get("max_score", 1)  # avoid div-by-zero

    if results["patrol"]["ok"] and score < max_score_p * 0.6:
        if not use_subprocess:
            try:
                t0 = time.monotonic()
                from heal import heal_from_patrol
                heal_actions = heal_from_patrol(patrol_data, dry_run=dry_run)
                output = json.dumps({"heal_actions": heal_actions, "heal_at": utc_now()}, ensure_ascii=False)
                results["heal"] = _run_step_direct("heal", t0, True, output)
            except Exception as exc:
                logger.warning("direct heal failed (%s), falling back to subprocess", exc)
                use_subprocess = True

        if use_subprocess:
            # Bug #1 fix: write patrol output to disk so heal --patrol-result can read it.
            patrol_file = _LOG_DIR / "patrol_last.json"
            _LOG_DIR.mkdir(parents=True, exist_ok=True)
            patrol_file.write_text(patrol_output, encoding="utf-8")
            heal_args = ["heal.py", "--patrol-result", str(patrol_file)]
            if dry_run:
                heal_args.append("--dry-run")
            results["heal"] = run_step("heal", heal_args, timeout=120)
    else:
        reason = f"skipped (score={score}, threshold={max_score_p * 0.6})"
        results["heal"] = {
            "step": "heal",
            "started_at": utc_now(),
            "rc": 0,
            "elapsed_s": 0,
            "ok": True,
            "output": reason if results["patrol"]["ok"] else "skipped (patrol failed)",
        }

    results["cycle_elapsed_s"] = round(time.monotonic() - total_started, 1)
    return results


def run_loop(interval_sec: int, dry_run: bool = False) -> None:
    """Run cycles continuously."""
    shutdown_requested = False

    def _handle_signal(signum: int, frame: object) -> None:
        nonlocal shutdown_requested
        sig_name = signal.Signals(signum).name
        logger.info("received %s, shutting down", sig_name)
        print("shutting down")
        shutdown_requested = True

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    logger.info("scheduler loop started, interval=%ds", interval_sec)
    cycle = 0
    while not shutdown_requested:
        cycle_started = time.monotonic()
        cycle += 1
        logger.info("cycle %d starting", cycle)
        try:
            outcome = run_cycle(dry_run=dry_run)
            ok_count = sum(1 for v in outcome.values() if isinstance(v, dict) and v.get("ok"))
            total = sum(1 for v in outcome.values() if isinstance(v, dict))
            logger.info(
                "cycle %d done: %d/%d steps ok in %.1fs",
                cycle, ok_count, total, outcome.get("cycle_elapsed_s", 0),
            )
        except Exception:
            logger.exception("cycle %d crashed", cycle)
        if not shutdown_requested:
            elapsed = time.monotonic() - cycle_started
            time.sleep(max(0, interval_sec - elapsed))
    sys.exit(0)


def main():
    parser = argparse.ArgumentParser(description="SharedSignals unified scheduler")
    parser.add_argument("--interval", type=int, metavar="SEC", help="Run continuously every SEC seconds")
    parser.add_argument("--dry-run", action="store_true", help="Preview only")
    parser.add_argument("--use-subprocess", action="store_true", help="Use subprocess instead of direct imports")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    setup_logging(args.verbose)

    if args.interval:
        run_loop(args.interval, dry_run=args.dry_run)
    else:
        outcome = run_cycle(dry_run=args.dry_run, use_subprocess=args.use_subprocess)
        ok = all(
            v.get("ok") if isinstance(v, dict) and "ok" in v else True
            for v in outcome.values()
        )
        if ok:
            print(f"OK — all steps passed in {outcome['cycle_elapsed_s']:.1f}s")
        else:
            print(f"FAIL — {outcome['cycle_elapsed_s']:.1f}s")
            for name, r in outcome.items():
                if isinstance(r, dict):
                    icon = "OK" if r.get("ok") else "FAIL"
                    print(f"  [{icon}] {name}: {r.get('output', '')[:200]}")
            sys.exit(1)


if __name__ == "__main__":
    main()

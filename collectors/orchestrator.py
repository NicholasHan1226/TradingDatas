"""Collector Orchestrator — unified scheduler for all SharedSignals collectors.

Reads collector registry (registry.yaml) and runs enabled collectors
according to their priority and schedule. Handles parallel execution
with a configurable max parallelism.
"""

from __future__ import annotations

import importlib
import json
import logging
import threading
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class Orchestrator:
    """Unified collector scheduler.

    Usage::

        orch = Orchestrator(registry_path="collectors/registry.yaml")
        orch.run_once()         # run all enabled collectors once
        orch.run_loop()         # run continuously, respecting schedules
    """

    def __init__(self, registry_path: str = "", max_parallel: int = 4, dry_run: bool = False):
        self._base = Path(__file__).resolve().parent
        self._registry_path = Path(registry_path) if registry_path else self._base / "registry.yaml"
        self._max_parallel = max_parallel
        self._dry_run = dry_run
        self._semaphore = threading.Semaphore(max_parallel)
        self._registry: dict[str, Any] = {}
        self._running_collectors: set[str] = set()
        self._lock = threading.Lock()
        self._load_registry()

    def _load_registry(self) -> None:
        import yaml
        with open(self._registry_path) as f:
            self._registry = yaml.safe_load(f)

    @property
    def collectors(self) -> dict[str, Any]:
        return self._registry.get("collectors", {})

    # ------------------------------------------------------------------
    # Run once
    # ------------------------------------------------------------------

    def run_once(self, names: list[str] | None = None) -> dict[str, Any]:
        """Run all enabled collectors once. Set names to run a subset."""
        results: dict[str, Any] = {}
        targets = names or [n for n, c in self.collectors.items() if c.get("enabled", True)]

        threads = []
        for name in targets:
            t = threading.Thread(target=self._run_one, args=(name, results), daemon=True)
            t.start()
            threads.append(t)

        for t in threads:
            t.join()

        return results

    def _run_one(self, name: str, results: dict[str, Any]) -> None:
        with self._semaphore:
            cfg = self.collectors.get(name)
            if not cfg:
                results[name] = {"status": "error", "error": "not found in registry"}
                return

            started = datetime.now(timezone.utc).isoformat()
            try:
                module = importlib.import_module(cfg["module"])
                cls = getattr(module, cfg["class"])
                instance = cls(config=self._load_config(cfg.get("config")))
                if self._dry_run:
                    instance._dry_run = True
                result = instance.run()
                result["priority"] = cfg.get("priority", "")
                results[name] = result
            except Exception:
                results[name] = {
                    "status": "failed",
                    "error": traceback.format_exc(),
                    "started_at": started,
                    "finished_at": datetime.now(timezone.utc).isoformat(),
                    "collector": name,
                }
                logger.exception("orchestrator: %s failed", name)
            finally:
                with self._lock:
                    self._running_collectors.discard(name)

    # ------------------------------------------------------------------
    # Run loop (continuous)
    # ------------------------------------------------------------------

    def run_loop(self, interval_sec: int = 60) -> None:
        """Run continuously, checking schedule every interval_sec."""
        logger.info("orchestrator loop started, interval=%ds", interval_sec)
        while True:
            cycle_started = time.monotonic()
            try:
                self._tick()
            except Exception:
                logger.exception("orchestrator tick failed")
            elapsed = time.monotonic() - cycle_started
            # Minimum 1s sleep to avoid tightloop on zero-duration ticks
            time.sleep(max(1.0, interval_sec - elapsed))

    def _tick(self) -> None:
        """Check which collectors are due and run them."""
        now = datetime.now(timezone.utc)
        for name, cfg in self.collectors.items():
            if not cfg.get("enabled", True):
                continue
            if name in self._running_collectors:
                continue  # skip if already running from a previous tick
            if self._is_due(cfg.get("schedule", ""), now):
                logger.info("orchestrator: triggering %s", name)
                self._running_collectors.add(name)
                results: dict[str, Any] = {}
                self._run_one(name, results)
                if results.get(name):
                    status = results[name].get("status", "unknown")
                    logger.info("orchestrator: %s → %s", name, status)

    @staticmethod
    def _is_due(schedule: str, now: datetime) -> bool:
        """Check if now matches a 5-field cron expression.

        Supports: *, */N, exact values, comma-separated lists, and ranges (1-5).
        Does NOT support: month/day names, L/W/# special chars.
        """
        if not schedule:
            return True
        parts = schedule.strip().split()
        if len(parts) != 5:
            return True

        minute_spec, hour_spec, dom_spec, month_spec, dow_spec = parts
        now_bits = {
            "minute": now.minute,
            "hour": now.hour,
            "dom": now.day,
            "month": now.month,
            "dow": (now.weekday() + 1) % 7,  # Sunday=0 -> Sunday=7
        }
        spec_map = {
            "minute": minute_spec,
            "hour": hour_spec,
            "dom": dom_spec,
            "month": month_spec,
            "dow": dow_spec,
        }

        return all(
            Orchestrator._cron_field_match(spec, now_bits[field], field)
            for field, spec in spec_map.items()
        )

    @staticmethod
    def _cron_field_match(spec: str, value: int, field: str = "") -> bool:
        """Check if a single cron field spec matches a numeric value.

        field is "minute", "hour", "dom", "month", or "dow" — used for
        DOW normalization (7 = Sunday = 0).
        """
        if spec == "*":
            return True
        if spec.startswith("*/"):
            interval = int(spec[2:])
            return value % interval == 0
        # comma-separated list
        if "," in spec:
            return any(
                Orchestrator._cron_field_match(s.strip(), value, field)
                for s in spec.split(",")
            )
        # range (e.g. 1-5, or 1-7 for DOW wrapping Mon→Sun)
        if "-" in spec:
            lo, hi = spec.split("-", 1)
            try:
                lo_v, hi_v = int(lo), int(hi)
                if field == "dow":
                    if lo_v == 7: lo_v = 0
                    if hi_v == 7: hi_v = 0
                    if lo_v > hi_v:  # wrap-around (e.g. 5-0 = Fri→Sun)
                        return value >= lo_v or value <= hi_v
                return lo_v <= value <= hi_v
            except ValueError:
                return True
        # exact value
        try:
            v = int(spec)
            # DOW: 7 is alternate notation for Sunday (0)
            if field == "dow":
                if v == 7 and value == 0:
                    return True
                if v == 0 and value == 7:
                    return True
            return value == v
        except ValueError:
            return True

    @staticmethod
    def _load_config(config_path: str) -> dict[str, Any]:
        if not config_path or config_path == "{}":
            return {}
        path = Path(__file__).resolve().parent.parent / config_path
        if not path.exists():
            return {}
        import yaml
        with open(path) as f:
            return yaml.safe_load(f) or {}

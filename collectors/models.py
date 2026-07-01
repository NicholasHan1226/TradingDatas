"""Shared data models for collector lifecycle."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class CollectorHealth:
    """Health check result for a collector."""

    name: str
    provider: str
    status: str  # available, degraded, unavailable
    message: str = ""
    last_success: str = ""
    consecutive_failures: int = 0
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class CollectTask:
    """A single unit of collection work."""

    dataset: str
    api_name: str
    params: dict[str, Any]
    symbol: str = ""
    trade_date: str = ""
    priority: int = 5
    target_table: str = ""
    fields: str | None = None


@dataclass
class CollectBatch:
    """Result of a collect call: raw rows from provider."""

    rows: list[dict[str, Any]]
    raw_count: int
    provider: str
    dataset: str
    source_file: str = ""
    collected_at: str = ""
    task: CollectTask | None = None


@dataclass
class ValidationReport:
    """Validation result for a batch of rows."""

    total: int
    valid: int
    invalid: int
    score: float  # 0.0-1.0 average quality
    issues: list[dict[str, Any]] = field(default_factory=list)
    rows: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class SaveResult:
    """Result of saving a batch to storage."""

    rows_read: int
    rows_written: int
    tables: list[str]
    source_files: list[str] = field(default_factory=list)
    coverage_keys: list[dict[str, str]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


@dataclass
class RunResult:
    """Audit trail for a single collector run."""

    run_id: str
    collector_name: str
    started_at: str
    finished_at: str = ""
    status: str = "running"  # running, success, partial_success, failed
    rows_read: int = 0
    rows_written: int = 0
    tables_written: list[str] = field(default_factory=list)
    error: str = ""
    notes: dict[str, Any] = field(default_factory=dict)

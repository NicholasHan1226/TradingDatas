#!/usr/bin/env python3
"""Refresh basic A-share industry map from SharedSignals read model.

This builds a conservative reference CSV from market_assets.sector. It does not
claim full Shenwan/CSRC/CNI taxonomy coverage; richer taxonomy can overwrite the
same file when a verified source is available.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import sqlite3
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = Path(os.environ.get("MARKETDATA_SQLITE") or "/opt/investment/MarketGraphRuntime/read_model/marketdata.sqlite")
DEFAULT_OUTPUT = ROOT / "data" / "association" / "stock_industry_map.csv"
DEFAULT_BACKUP_DIR = ROOT / "data" / "association" / "backups"

FIELDNAMES = [
    "ts_code",
    "name",
    "market",
    "sw_l1_code",
    "sw_l1_name",
    "sw_l2_code",
    "sw_l2_name",
    "sw_l3_code",
    "sw_l3_name",
    "chain_id",
    "chain_name",
    "segment_id",
    "segment_name",
    "csrc_code",
    "csrc_name",
    "cni_code",
    "cni_name",
    "gics_sector",
    "taxonomy_id",
    "source",
    "source_date",
    "confidence",
    "status",
    "notes",
]


@dataclass(frozen=True)
class RefreshResult:
    rows_written: int
    output_path: str
    backup_path: str | None
    source_db: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "rows_written": self.rows_written,
            "output_path": self.output_path,
            "backup_path": self.backup_path,
            "source_db": self.source_db,
        }


def _source_date(updated_at: Any, source_file: Any) -> str:
    text = str(updated_at or "").strip()
    if text:
        normalized = text.replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(normalized).strftime("%Y%m%d")
        except ValueError:
            pass
    file_text = str(source_file or "")
    digit_runs = "".join(ch if ch.isdigit() else " " for ch in file_text).split()
    for value in digit_runs:
        if len(value) == 8:
            return value
    return datetime.now(timezone.utc).strftime("%Y%m%d")


def _load_rows(db_path: Path) -> list[dict[str, str]]:
    if not db_path.exists():
        raise FileNotFoundError(f"read model not found: {db_path}")
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT symbol, name, market, sector, status, provider, source_file, updated_at
            FROM market_assets
            WHERE market = 'Ashare' AND COALESCE(TRIM(sector), '') != ''
            ORDER BY symbol
            """
        ).fetchall()
    finally:
        conn.close()

    mapped: list[dict[str, str]] = []
    for row in rows:
        sector = str(row["sector"] or "").strip()
        symbol = str(row["symbol"] or "").strip()
        if not sector or not symbol:
            continue
        mapped.append(
            {
                "ts_code": symbol,
                "name": str(row["name"] or "").strip(),
                "market": "Ashare",
                "sw_l1_code": "",
                "sw_l1_name": sector,
                "sw_l2_code": "",
                "sw_l2_name": "",
                "sw_l3_code": "",
                "sw_l3_name": "",
                "chain_id": "",
                "chain_name": "",
                "segment_id": "",
                "segment_name": "",
                "csrc_code": "",
                "csrc_name": "",
                "cni_code": "",
                "cni_name": "",
                "gics_sector": "",
                "taxonomy_id": "market_assets_sector",
                "source": "market_assets",
                "source_date": _source_date(row["updated_at"], row["source_file"]),
                "confidence": "0.60",
                "status": str(row["status"] or "active").strip() or "active",
                "notes": "basic sector from market_assets; not verified Shenwan/CSRC/CNI taxonomy",
            }
        )
    return mapped


def _apply_reference_file_permissions(path: Path, parent: Path) -> None:
    try:
        parent_stat = parent.stat()
    except OSError:
        parent_stat = None
    try:
        os.chmod(path, 0o664)
    except OSError:
        pass
    if parent_stat is None:
        return
    try:
        os.chown(path, parent_stat.st_uid, parent_stat.st_gid)
    except (AttributeError, PermissionError, OSError):
        pass


def _backup_existing(output_path: Path, backup_dir: Path | None) -> str | None:
    if backup_dir is None or not output_path.exists():
        return None
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_path = backup_dir / f"{output_path.stem}_before_refresh_{stamp}{output_path.suffix}"
    shutil.copy2(output_path, backup_path)
    _apply_reference_file_permissions(backup_path, output_path.parent)
    return str(backup_path)


def _write_atomic(output_path: Path, rows: list[dict[str, str]]) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8-sig", newline="", dir=str(output_path.parent), delete=False) as handle:
        tmp_path = Path(handle.name)
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    _apply_reference_file_permissions(tmp_path, output_path.parent)
    os.replace(tmp_path, output_path)
    _apply_reference_file_permissions(output_path, output_path.parent)


def refresh_stock_industry_map(
    db_path: Path = DEFAULT_DB,
    output_path: Path = DEFAULT_OUTPUT,
    backup_dir: Path | None = DEFAULT_BACKUP_DIR,
    min_rows: int = 1000,
) -> RefreshResult:
    rows = _load_rows(db_path)
    if len(rows) < min_rows:
        raise RuntimeError(f"industry map refresh produced too few rows: {len(rows)} < {min_rows}")
    backup_path = _backup_existing(output_path, backup_dir)
    _write_atomic(output_path, rows)
    return RefreshResult(
        rows_written=len(rows),
        output_path=str(output_path),
        backup_path=backup_path,
        source_db=str(db_path),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Refresh stock_industry_map.csv from market_assets.sector")
    parser.add_argument("--db-path", type=Path, default=DEFAULT_DB)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--backup-dir", type=Path, default=DEFAULT_BACKUP_DIR)
    parser.add_argument("--no-backup", action="store_true")
    parser.add_argument("--min-rows", type=int, default=1000)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    result = refresh_stock_industry_map(
        db_path=args.db_path,
        output_path=args.output,
        backup_dir=None if args.no_backup else args.backup_dir,
        min_rows=args.min_rows,
    )
    if args.json:
        print(json.dumps(result.as_dict(), ensure_ascii=False, sort_keys=True))
    else:
        print(f"wrote {result.rows_written} rows to {result.output_path}")
        if result.backup_path:
            print(f"backup: {result.backup_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

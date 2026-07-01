"""Row-level validation for collected data."""

from __future__ import annotations

from typing import Any


class ValidatorMixin:
    """Field completeness and OHLCV sanity checks."""

    def _validate_row(self, api_name: str, row: dict[str, Any]) -> dict[str, Any]:
        quality: dict[str, Any] = {"score": 1.0, "issues": []}

        # OHLCV sanity for bar-like APIs
        if api_name in ("daily", "hk_daily", "us_daily", "klines", "index_daily"):
            for f in ("open", "high", "low", "close"):
                if f in row and row.get(f) is not None:
                    try:
                        v = float(row[f])
                        if v <= 0:
                            quality["issues"].append(f"{f}_zero_or_negative")
                            quality["score"] = max(0, quality["score"] - 0.2)
                    except (ValueError, TypeError):
                        quality["issues"].append(f"{f}_non_numeric")
                        quality["score"] = max(0, quality["score"] - 0.3)
            try:
                high = float(row.get("high", 0))
                low = float(row.get("low", 0))
                if high < low:
                    quality["issues"].append("high_less_than_low")
                    quality["score"] = 0.0
            except (ValueError, TypeError):
                pass

        # Missing key identifier fields
        for f in ("ts_code", "symbol"):
            if f in row and not row.get(f):
                quality["issues"].append(f"missing_{f}")
                quality["score"] = max(0, quality["score"] - 0.5)

        row["_quality"] = quality
        return row

    def validate(self, api_name: str, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [self._validate_row(api_name, r) for r in rows]

    @staticmethod
    def validation_report(rows: list[dict[str, Any]]) -> dict[str, Any]:
        total = len(rows)
        scores = [r.get("_quality", {}).get("score", 1.0) for r in rows]
        valid = sum(1 for s in scores if s >= 0.5)
        return {
            "total": total,
            "valid": valid,
            "invalid": total - valid,
            "avg_score": sum(scores) / total if total else 1.0,
        }

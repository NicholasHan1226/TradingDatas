def adjust_prices(rows, anchor_date):
    """Normalize one synthetic price series to the selected factor anchor."""
    from datetime import date
    import math

    if not rows:
        raise ValueError("empty_input")
    seen = set()
    security = rows[0].get("security")
    for row in rows:
        if not security or row.get("security") != security:
            raise ValueError("one_security_required")
        day = row.get("date", "")
        try:
            valid_date = date.fromisoformat(day).isoformat() == day
        except (ValueError, TypeError):
            valid_date = False
        if not valid_date or day in seen:
            raise ValueError("invalid_or_duplicate_date")
        for field in ("close", "factor"):
            value = row.get(field)
            if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
                raise ValueError("invalid_price_or_factor")
        seen.add(day)
    anchor = next((row for row in rows if row["date"] == anchor_date), None)
    if anchor is None:
        raise ValueError("missing_anchor")
    return [dict(row, anchorDate=anchor_date,
                 adjustedClose=round(row["close"] * row["factor"] / anchor["factor"], 6))
            for row in sorted(rows, key=lambda item: item["date"])]

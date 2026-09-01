from datetime import datetime, timezone
import math


def align_spot_and_open_interest(bars, observations, max_age_seconds, expected_unit):
    def parse(value):
        try:
            parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            if parsed.strftime("%Y-%m-%dT%H:%M:%SZ") != value:
                raise ValueError()
            return int(parsed.timestamp())
        except (ValueError, TypeError):
            raise ValueError("utc_seconds_required")

    def finite(value):
        return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)

    if not finite(max_age_seconds) or int(max_age_seconds) != max_age_seconds or not 0 <= max_age_seconds <= 86400 or not isinstance(expected_unit, str) or not expected_unit:
        raise ValueError("invalid_alignment_contract")
    oi_times, oi = set(), []
    for row in observations:
        time = parse(row.get("observedAt"))
        available = max(time, parse(row.get("firstSeenAt")))
        if time in oi_times:
            raise ValueError("duplicate_observation")
        oi_times.add(time)
        if not finite(row.get("value")) or row["value"] < 0 or row.get("unit") != expected_unit:
            raise ValueError("invalid_open_interest_unit_or_value")
        oi.append((row, time, available))
    oi.sort(key=lambda item: -item[1])
    bar_times, result = set(), []
    for bar in sorted(bars, key=lambda row: parse(row.get("endExclusive"))):
        start, end = parse(bar.get("openTime")), parse(bar.get("endExclusive"))
        if end - start != 300 or start % 300 != 0 or start in bar_times:
            raise ValueError("invalid_or_duplicate_bar")
        bar_times.add(start)
        if not finite(bar.get("close")) or bar["close"] <= 0:
            raise ValueError("invalid_close")
        candidate = next((item for item in oi if item[1] <= end and item[2] <= end), None)
        age = end - candidate[1] if candidate else None
        status = "no_available_observation" if not candidate else "stale" if age > max_age_seconds else "aligned"
        result.append({**bar, "oiObservedAt": candidate[0]["observedAt"] if candidate else None, "ageSeconds": age, "openInterest": candidate[0]["value"] if status == "aligned" else None, "unit": expected_unit, "status": status})
    return result

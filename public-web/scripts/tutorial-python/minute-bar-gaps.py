from datetime import datetime, timedelta, timezone
import math


def audit_bar_grid(rows, expected_opens, interval_minutes):
    def parse(value):
        try:
            parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            if parsed.strftime("%Y-%m-%dT%H:%M:%SZ") != value:
                raise ValueError()
            return parsed
        except (ValueError, TypeError):
            raise ValueError("utc_seconds_required")

    if isinstance(interval_minutes, bool) or not isinstance(interval_minutes, (int, float)) or not math.isfinite(interval_minutes) or int(interval_minutes) != interval_minutes or not 0 < interval_minutes <= 1440:
        raise ValueError("invalid_interval")
    if not expected_opens or len(expected_opens) > 10000:
        raise ValueError("invalid_grid")
    grid = sorted(map(parse, expected_opens))
    interval = timedelta(minutes=interval_minutes)
    if any(current - previous < interval for previous, current in zip(grid, grid[1:])):
        raise ValueError("overlapping_grid")
    slots, observations = set(grid), {}
    for row in rows:
        time = parse(row.get("openTime"))
        if time not in slots:
            raise ValueError("outside_grid")
        if time in observations:
            raise ValueError("duplicate_bar")
        close = row.get("close")
        if isinstance(close, bool) or not isinstance(close, (int, float)) or not math.isfinite(close) or close <= 0:
            raise ValueError("invalid_close")
        observations[time] = close
    iso = lambda value: value.isoformat(timespec="milliseconds").replace("+00:00", "Z")
    return [{"openTime": iso(time), "endExclusive": iso(time + interval), "close": observations.get(time), "status": "observed" if time in observations else "missing"} for time in grid]

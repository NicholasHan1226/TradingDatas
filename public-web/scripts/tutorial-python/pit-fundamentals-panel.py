def select_as_of(rows, cutoff):
    """Select the latest published eligible version, without overwriting inputs."""
    from datetime import datetime, timezone
    import math
    import re

    def parse(value):
        if not isinstance(value, str) or not re.search(r"T.*(Z|[+-]\d{2}:\d{2})$", value):
            raise ValueError("timezone_required")
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            raise ValueError("timezone_required") from None

    boundary = parse(cutoff)
    eligible, identities, publication_orders = {}, set(), set()
    for row in rows:
        value = row.get("value")
        if (not all(row.get(field) for field in ("entity", "period", "metric", "unit"))
                or type(value) not in (int, float) or not math.isfinite(value)):
            raise ValueError("invalid_record")
        published, observed = parse(row.get("publishedAt")), parse(row.get("firstSeenAt"))
        key = tuple(row[field] for field in ("entity", "period", "metric", "unit"))
        identity = (key, row.get("version"))
        if not row.get("version") or identity in identities:
            raise ValueError("duplicate_or_missing_version")
        identities.add(identity)
        available = max(published, observed)
        if available > boundary:
            continue
        publication_order = (key, published)
        if publication_order in publication_orders:
            raise ValueError("ambiguous_publication_order")
        publication_orders.add(publication_order)
        if key not in eligible or published > eligible[key][0]:
            timestamp = available.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
            eligible[key] = (published, dict(row, availableAt=timestamp))
    return [eligible[key][1] for key in sorted(eligible)]

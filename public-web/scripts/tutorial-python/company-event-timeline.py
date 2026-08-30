def align_events(events, session_opens):
    """Map an event to the first opening strictly after its availability."""
    from datetime import datetime, timezone
    import re

    def parse(value):
        if not isinstance(value, str) or not re.search(r"T.*(Z|[+-]\d{2}:\d{2})$", value):
            return None
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None

    if not session_opens or any(parse(value) is None for value in session_opens):
        raise ValueError("invalid_calendar")
    sessions = sorted(set(session_opens), key=parse)
    seen, output = {}, []
    for event in events:
        if not event.get("id") or not event.get("version"):
            raise ValueError("missing_event_identity")
        key = (event["id"], event["version"])
        if key in seen:
            if seen[key] != event:
                raise ValueError("conflicting_event_version")
            continue
        seen[key] = dict(event)
        published, observed = parse(event.get("publishedAt")), parse(event.get("firstSeenAt"))
        if published is None or observed is None:
            output.append(dict(event, sessionOpen=None, status="needs_review"))
            continue
        available = max(published, observed)
        session = next((value for value in sessions if parse(value) > available), None)
        timestamp = available.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        output.append(dict(event, availableAt=timestamp, sessionOpen=session,
                           status="aligned" if session else "outside_calendar"))
    return output

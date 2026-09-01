// Synthetic teaching data. No network requests.
function alignEvents(events, sessionOpens) {
  const validTime = (value) => typeof value === "string" && /T.*(Z|[+-]\d{2}:\d{2})$/.test(value) && Number.isFinite(Date.parse(value));
  if (!sessionOpens.length || sessionOpens.some((value) => !validTime(value))) throw new Error("invalid_calendar");
  const sessions = [...new Set(sessionOpens)].sort((a, b) => Date.parse(a) - Date.parse(b));
  const seen = new Map();
  return events.flatMap((event) => {
    if (!event.id || !event.version) throw new Error("missing_event_identity");
    const key = JSON.stringify([event.id, event.version]);
    const fingerprint = JSON.stringify(event);
    if (seen.has(key)) {
      if (seen.get(key) !== fingerprint) throw new Error("conflicting_event_version");
      return [];
    }
    seen.set(key, fingerprint);
    if (!validTime(event.publishedAt) || !validTime(event.firstSeenAt)) return [{ ...event, sessionOpen: null, status: "needs_review" }];
    const available = Math.max(Date.parse(event.publishedAt), Date.parse(event.firstSeenAt));
    // Conservative daily convention: first session opening strictly after availability.
    const sessionOpen = sessions.find((value) => Date.parse(value) > available) || null;
    return [{ ...event, availableAt: new Date(available).toISOString(), sessionOpen, status: sessionOpen ? "aligned" : "outside_calendar" }];
  });
}

const inputs = [
  [
    {
      "id": "DEMO-A",
      "version": "v1",
      "publishedAt": "2025-01-03T18:00:00+08:00",
      "firstSeenAt": "2025-01-03T18:02:00+08:00"
    },
    {
      "id": "DEMO-A",
      "version": "v1",
      "publishedAt": "2025-01-03T18:00:00+08:00",
      "firstSeenAt": "2025-01-03T18:02:00+08:00"
    },
    {
      "id": "DEMO-B",
      "version": "v1",
      "publishedAt": "2025-01-06",
      "firstSeenAt": "2025-01-06T10:00:00+08:00"
    }
  ],
  [
    "2025-01-03T09:30:00+08:00",
    "2025-01-06T09:30:00+08:00",
    "2025-01-07T09:30:00+08:00"
  ]
];
console.log(alignEvents(...inputs));

// Small, deterministic teaching examples. No provider calls or production writes.
export function adjustPrices(rows, anchorDate) {
  if (!rows.length) throw new Error("empty_input");
  const seen = new Set();
  const security = rows[0].security;
  for (const row of rows) {
    if (row.security !== security || !row.security) throw new Error("one_security_required");
    const time = Date.parse(`${row.date}T00:00:00Z`);
    if (!/^\d{4}-\d{2}-\d{2}$/.test(row.date) || !Number.isFinite(time) || new Date(time).toISOString().slice(0, 10) !== row.date || seen.has(row.date)) throw new Error("invalid_or_duplicate_date");
    if (!Number.isFinite(row.close) || row.close <= 0 || !Number.isFinite(row.factor) || row.factor <= 0) throw new Error("invalid_price_or_factor");
    seen.add(row.date);
  }
  const anchor = rows.find((row) => row.date === anchorDate);
  if (!anchor) throw new Error("missing_anchor");
  return [...rows].sort((a, b) => a.date.localeCompare(b.date)).map((row) => ({ ...row, anchorDate, adjustedClose: Number((row.close * row.factor / anchor.factor).toFixed(6)) }));
}

export function selectAsOf(rows, cutoff) {
  const parse = (value) => {
    if (typeof value !== "string" || !/T.*(Z|[+-]\d{2}:\d{2})$/.test(value) || !Number.isFinite(Date.parse(value))) throw new Error("timezone_required");
    return Date.parse(value);
  };
  const boundary = parse(cutoff);
  const eligible = new Map();
  const identities = new Set();
  const publicationOrders = new Set();
  for (const row of rows) {
    if (!row.entity || !row.period || !row.metric || !row.unit || !Number.isFinite(row.value)) throw new Error("invalid_record");
    const published = parse(row.publishedAt), observed = parse(row.firstSeenAt);
    const key = JSON.stringify([row.entity, row.period, row.metric, row.unit]);
    const identity = JSON.stringify([key, row.version]);
    if (!row.version || identities.has(identity)) throw new Error("duplicate_or_missing_version");
    identities.add(identity);
    const available = Math.max(published, observed);
    if (available > boundary) continue;
    const publicationOrder = JSON.stringify([key, published]);
    if (publicationOrders.has(publicationOrder)) throw new Error("ambiguous_publication_order");
    publicationOrders.add(publicationOrder);
    const previous = eligible.get(key);
    if (!previous || published > previous.published) eligible.set(key, { published, row: { ...row, availableAt: new Date(available).toISOString() } });
  }
  return [...eligible.values()].map(({ row }) => row).sort((a, b) => JSON.stringify([a.entity, a.period, a.metric, a.unit]).localeCompare(JSON.stringify([b.entity, b.period, b.metric, b.unit])));
}

export function alignEvents(events, sessionOpens) {
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

export const tutorialExamples = {
  "adjusted-price-series": {
    execute: adjustPrices,
    args: [[{ security: "DEMO", date: "2025-01-02", close: 100, factor: 1 }, { security: "DEMO", date: "2025-01-03", close: 50, factor: 2 }, { security: "DEMO", date: "2025-01-06", close: 51, factor: 2 }], "2025-01-06"],
  },
  "pit-fundamentals-panel": {
    execute: selectAsOf,
    args: [[{ entity: "DEMO", period: "2024-12-31", metric: "revenue", unit: "CNY_million", value: 100, version: "v1", publishedAt: "2025-03-20T18:00:00+08:00", firstSeenAt: "2025-03-20T18:05:00+08:00" }, { entity: "DEMO", period: "2024-12-31", metric: "revenue", unit: "CNY_million", value: 105, version: "v2", publishedAt: "2025-04-10T18:00:00+08:00", firstSeenAt: "2025-04-10T18:02:00+08:00" }], "2025-03-31T23:59:59+08:00"],
  },
  "company-event-timeline": {
    execute: alignEvents,
    args: [[{ id: "DEMO-A", version: "v1", publishedAt: "2025-01-03T18:00:00+08:00", firstSeenAt: "2025-01-03T18:02:00+08:00" }, { id: "DEMO-A", version: "v1", publishedAt: "2025-01-03T18:00:00+08:00", firstSeenAt: "2025-01-03T18:02:00+08:00" }, { id: "DEMO-B", version: "v1", publishedAt: "2025-01-06", firstSeenAt: "2025-01-06T10:00:00+08:00" }], ["2025-01-03T09:30:00+08:00", "2025-01-06T09:30:00+08:00", "2025-01-07T09:30:00+08:00"]],
  },
};

export function tutorialCode(id) {
  const example = tutorialExamples[id];
  return `// Synthetic teaching data. No network requests.\n${example.execute.toString()}\n\nconst inputs = ${JSON.stringify(example.args, null, 2)};\nconsole.log(${example.execute.name}(...inputs));`;
}

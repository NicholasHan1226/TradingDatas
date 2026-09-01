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

export function auditBarGrid(rows, expectedOpens, intervalMinutes) {
  const parse = (value) => {
    if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/.test(value) || !Number.isFinite(Date.parse(value)) || new Date(value).toISOString().replace(".000Z", "Z") !== value) throw new Error("utc_seconds_required");
    return Date.parse(value);
  };
  if (!Number.isInteger(intervalMinutes) || intervalMinutes <= 0 || intervalMinutes > 1440) throw new Error("invalid_interval");
  if (!expectedOpens.length || expectedOpens.length > 10000) throw new Error("invalid_grid");
  const grid = expectedOpens.map(parse).sort((a, b) => a - b);
  if (grid.some((time, index) => index > 0 && time - grid[index - 1] < intervalMinutes * 60000)) throw new Error("overlapping_grid");
  const slots = new Set(grid), observations = new Map();
  for (const row of rows) {
    const time = parse(row.openTime);
    if (!slots.has(time)) throw new Error("outside_grid");
    if (observations.has(time)) throw new Error("duplicate_bar");
    if (!Number.isFinite(row.close) || row.close <= 0) throw new Error("invalid_close");
    observations.set(time, row.close);
  }
  return grid.map((time) => ({ openTime: new Date(time).toISOString(), endExclusive: new Date(time + intervalMinutes * 60000).toISOString(), close: observations.get(time) ?? null, status: observations.has(time) ? "observed" : "missing" }));
}

export function preserveDocumentVersions(rows, cutoff) {
  const parse = (value) => {
    if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/.test(value) || !Number.isFinite(Date.parse(value)) || new Date(value).toISOString().replace(".000Z", "Z") !== value) throw new Error("utc_seconds_required");
    return Date.parse(value);
  };
  const boundary = parse(cutoff), identities = new Map(), eligible = [];
  for (const row of rows) {
    if (![row.publisher, row.documentId, row.version].every((value) => typeof value === "string" && value.length) || !/^[a-f0-9]{64}$/.test(row.contentHash)) throw new Error("invalid_document_identity");
    const available = Math.max(parse(row.publishedAt), parse(row.firstSeenAt));
    const key = JSON.stringify([row.publisher, row.documentId, row.version]);
    const fingerprint = JSON.stringify([row.contentHash, row.publishedAt, row.firstSeenAt]);
    if (identities.has(key)) {
      if (identities.get(key) !== fingerprint) throw new Error("conflicting_document_version");
      continue;
    }
    identities.set(key, fingerprint);
    if (available <= boundary) eligible.push({ ...row, availableAt: new Date(available).toISOString() });
  }
  const compare = (a, b) => a < b ? -1 : a > b ? 1 : 0;
  eligible.sort((a, b) => compare(a.availableAt, b.availableAt) || compare(JSON.stringify([a.publisher, a.documentId, a.version]), JSON.stringify([b.publisher, b.documentId, b.version])));
  const previous = new Map();
  return eligible.map((row) => {
    const key = JSON.stringify([row.publisher, row.documentId]), prior = previous.get(key);
    if (prior?.availableAt === row.availableAt) throw new Error("ambiguous_revision_order");
    previous.set(key, row);
    return { ...row, status: !prior ? "first_observation" : prior.contentHash === row.contentHash ? "unchanged_content" : "changed_content" };
  });
}

export function alignSpotAndOpenInterest(bars, observations, maxAgeSeconds, expectedUnit) {
  const parse = (value) => {
    if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/.test(value) || !Number.isFinite(Date.parse(value)) || new Date(value).toISOString().replace(".000Z", "Z") !== value) throw new Error("utc_seconds_required");
    return Date.parse(value);
  };
  if (!Number.isInteger(maxAgeSeconds) || maxAgeSeconds < 0 || maxAgeSeconds > 86400 || typeof expectedUnit !== "string" || !expectedUnit) throw new Error("invalid_alignment_contract");
  const oiTimes = new Set();
  const oi = observations.map((row) => {
    const time = parse(row.observedAt), available = Math.max(time, parse(row.firstSeenAt));
    if (oiTimes.has(time)) throw new Error("duplicate_observation");
    oiTimes.add(time);
    if (!Number.isFinite(row.value) || row.value < 0 || row.unit !== expectedUnit) throw new Error("invalid_open_interest_unit_or_value");
    return { row, time, available };
  }).sort((a, b) => b.time - a.time);
  const barTimes = new Set();
  return [...bars].sort((a, b) => parse(a.endExclusive) - parse(b.endExclusive)).map((bar) => {
    const start = parse(bar.openTime), end = parse(bar.endExclusive);
    if (end - start !== 300000 || start % 300000 !== 0 || barTimes.has(start)) throw new Error("invalid_or_duplicate_bar");
    barTimes.add(start);
    if (!Number.isFinite(bar.close) || bar.close <= 0) throw new Error("invalid_close");
    // Teaching convention: decisions at endExclusive may use observations available by it.
    const candidate = oi.find((item) => item.time <= end && item.available <= end);
    const ageSeconds = candidate ? (end - candidate.time) / 1000 : null;
    const status = !candidate ? "no_available_observation" : ageSeconds > maxAgeSeconds ? "stale" : "aligned";
    return { ...bar, oiObservedAt: candidate?.row.observedAt ?? null, ageSeconds, openInterest: status === "aligned" ? candidate.row.value : null, unit: expectedUnit, status };
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
  "minute-bar-gaps": {
    execute: auditBarGrid,
    args: [[{ openTime: "2025-01-06T01:30:00Z", close: 100 }, { openTime: "2025-01-06T01:40:00Z", close: 102 }], ["2025-01-06T01:30:00Z", "2025-01-06T01:35:00Z", "2025-01-06T01:40:00Z"], 5],
  },
  "document-version-ledger": {
    execute: preserveDocumentVersions,
    args: [[
      { publisher: "DEMO", documentId: "DOC-1", version: "v1", contentHash: "a".repeat(64), publishedAt: "2025-01-06T08:00:00Z", firstSeenAt: "2025-01-06T08:01:00Z" },
      { publisher: "DEMO", documentId: "DOC-1", version: "v1", contentHash: "a".repeat(64), publishedAt: "2025-01-06T08:00:00Z", firstSeenAt: "2025-01-06T08:01:00Z" },
      { publisher: "DEMO", documentId: "DOC-1", version: "v2", contentHash: "b".repeat(64), publishedAt: "2025-01-07T08:00:00Z", firstSeenAt: "2025-01-07T08:01:00Z" },
      { publisher: "DEMO", documentId: "DOC-1", version: "v3", contentHash: "b".repeat(64), publishedAt: "2025-01-08T08:00:00Z", firstSeenAt: "2025-01-08T08:01:00Z" },
    ], "2025-01-08T09:00:00Z"],
  },
  "crypto-observation-alignment": {
    execute: alignSpotAndOpenInterest,
    args: [[
      { openTime: "2025-01-06T00:00:00Z", endExclusive: "2025-01-06T00:05:00Z", close: 100 },
      { openTime: "2025-01-06T00:05:00Z", endExclusive: "2025-01-06T00:10:00Z", close: 101 },
      { openTime: "2025-01-06T00:10:00Z", endExclusive: "2025-01-06T00:15:00Z", close: 102 },
    ], [
      { observedAt: "2025-01-06T00:04:00Z", firstSeenAt: "2025-01-06T00:06:00Z", value: 10, unit: "BTC" },
      { observedAt: "2025-01-06T00:09:00Z", firstSeenAt: "2025-01-06T00:09:30Z", value: 12, unit: "BTC" },
    ], 300, "BTC"],
  },
};

export function tutorialCode(id) {
  const example = tutorialExamples[id];
  return `// Synthetic teaching data. No network requests.\n${example.execute.toString()}\n\nconst inputs = ${JSON.stringify(example.args, null, 2)};\nconsole.log(${example.execute.name}(...inputs));`;
}

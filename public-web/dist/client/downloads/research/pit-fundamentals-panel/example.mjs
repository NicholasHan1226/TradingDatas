// Synthetic teaching data. No network requests.
function selectAsOf(rows, cutoff) {
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

const inputs = [
  [
    {
      "entity": "DEMO",
      "period": "2024-12-31",
      "metric": "revenue",
      "unit": "CNY_million",
      "value": 100,
      "version": "v1",
      "publishedAt": "2025-03-20T18:00:00+08:00",
      "firstSeenAt": "2025-03-20T18:05:00+08:00"
    },
    {
      "entity": "DEMO",
      "period": "2024-12-31",
      "metric": "revenue",
      "unit": "CNY_million",
      "value": 105,
      "version": "v2",
      "publishedAt": "2025-04-10T18:00:00+08:00",
      "firstSeenAt": "2025-04-10T18:02:00+08:00"
    }
  ],
  "2025-03-31T23:59:59+08:00"
];
console.log(selectAsOf(...inputs));

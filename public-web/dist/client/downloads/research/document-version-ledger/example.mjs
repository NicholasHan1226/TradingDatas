// Synthetic teaching data. No network requests.
function preserveDocumentVersions(rows, cutoff) {
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

const inputs = [
  [
    {
      "publisher": "DEMO",
      "documentId": "DOC-1",
      "version": "v1",
      "contentHash": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
      "publishedAt": "2025-01-06T08:00:00Z",
      "firstSeenAt": "2025-01-06T08:01:00Z"
    },
    {
      "publisher": "DEMO",
      "documentId": "DOC-1",
      "version": "v1",
      "contentHash": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
      "publishedAt": "2025-01-06T08:00:00Z",
      "firstSeenAt": "2025-01-06T08:01:00Z"
    },
    {
      "publisher": "DEMO",
      "documentId": "DOC-1",
      "version": "v2",
      "contentHash": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
      "publishedAt": "2025-01-07T08:00:00Z",
      "firstSeenAt": "2025-01-07T08:01:00Z"
    },
    {
      "publisher": "DEMO",
      "documentId": "DOC-1",
      "version": "v3",
      "contentHash": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
      "publishedAt": "2025-01-08T08:00:00Z",
      "firstSeenAt": "2025-01-08T08:01:00Z"
    }
  ],
  "2025-01-08T09:00:00Z"
];
console.log(preserveDocumentVersions(...inputs));

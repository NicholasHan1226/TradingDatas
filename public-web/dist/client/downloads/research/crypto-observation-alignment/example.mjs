// Synthetic teaching data. No network requests.
function alignSpotAndOpenInterest(bars, observations, maxAgeSeconds, expectedUnit) {
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

const inputs = [
  [
    {
      "openTime": "2025-01-06T00:00:00Z",
      "endExclusive": "2025-01-06T00:05:00Z",
      "close": 100
    },
    {
      "openTime": "2025-01-06T00:05:00Z",
      "endExclusive": "2025-01-06T00:10:00Z",
      "close": 101
    },
    {
      "openTime": "2025-01-06T00:10:00Z",
      "endExclusive": "2025-01-06T00:15:00Z",
      "close": 102
    }
  ],
  [
    {
      "observedAt": "2025-01-06T00:04:00Z",
      "firstSeenAt": "2025-01-06T00:06:00Z",
      "value": 10,
      "unit": "BTC"
    },
    {
      "observedAt": "2025-01-06T00:09:00Z",
      "firstSeenAt": "2025-01-06T00:09:30Z",
      "value": 12,
      "unit": "BTC"
    }
  ],
  300,
  "BTC"
];
console.log(alignSpotAndOpenInterest(...inputs));

// Synthetic teaching data. No network requests.
function auditBarGrid(rows, expectedOpens, intervalMinutes) {
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

const inputs = [
  [
    {
      "openTime": "2025-01-06T01:30:00Z",
      "close": 100
    },
    {
      "openTime": "2025-01-06T01:40:00Z",
      "close": 102
    }
  ],
  [
    "2025-01-06T01:30:00Z",
    "2025-01-06T01:35:00Z",
    "2025-01-06T01:40:00Z"
  ],
  5
];
console.log(auditBarGrid(...inputs));

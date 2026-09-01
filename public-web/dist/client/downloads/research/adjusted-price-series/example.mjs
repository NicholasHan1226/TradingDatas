// Synthetic teaching data. No network requests.
function adjustPrices(rows, anchorDate) {
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

const inputs = [
  [
    {
      "security": "DEMO",
      "date": "2025-01-02",
      "close": 100,
      "factor": 1
    },
    {
      "security": "DEMO",
      "date": "2025-01-03",
      "close": 50,
      "factor": 2
    },
    {
      "security": "DEMO",
      "date": "2025-01-06",
      "close": 51,
      "factor": 2
    }
  ],
  "2025-01-06"
];
console.log(adjustPrices(...inputs));

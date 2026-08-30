import assert from "node:assert/strict";
import { test } from "node:test";
import { runInNewContext } from "node:vm";
import { adjustPrices, selectAsOf, alignEvents, tutorialExamples, tutorialCode } from "../src/tutorialExamples.js";
import { preparationTutorials } from "../src/preparationTutorials.js";
import { papers } from "../src/researchCatalog.js";
import { researchReaderNotes as researchEditorial } from "../src/researchReaderNotes.js";
import { readFileSync } from "node:fs";
const registry = ["provider_native_dataset_registry.yaml", "crypto_binance_canary_registry.v1.yaml"].map(name => readFileSync(new URL(`../../config/${name}`, import.meta.url), "utf8")).join("\n");

test("six bilingual tutorials have sources, inputs, steps, outputs and working research links", () => {
  assert.equal(Object.keys(preparationTutorials).length, 6);
  for (const [id, tutorial] of Object.entries(preparationTutorials)) {
    assert.ok(tutorialExamples[id]);
    assert.ok(tutorial.datasetIds.length >= 2 && tutorial.steps.length >= 4);
    for (const datasetId of tutorial.datasetIds) assert.ok(registry.includes(`- dataset_id: ${datasetId}\n`), datasetId);
    assert.ok(tutorial.sources.every(source => source.url.startsWith("https://")));
    assert.ok(tutorial.research.every(title => papers.some(paper => paper.title === title)));
    for (const locale of ["zh", "en"]) for (const step of tutorial.steps) assert.ok(step.title[locale] && step.body[locale].length > 80);
  }
});
test("forty source-grounded bilingual guides keep a bounded internal review scope", () => {
  assert.equal(Object.keys(researchEditorial).length, 40);
  for (const [title, guide] of Object.entries(researchEditorial)) {
    assert.ok(papers.some(paper => paper.title === title), title);
    assert.ok(guide.sections.length >= 4);
    assert.ok(guide.evidenceScope && guide.evidenceUrl.startsWith("https://"));
    for (const section of guide.sections) for (const locale of ["zh", "en"]) assert.ok(section.body[locale].length > 60, title);
  }
});
test("adjustment preserves raw inputs, anchors and rejects missing/invalid factors", () => {
  const example = tutorialExamples["adjusted-price-series"];
  const before = JSON.stringify(example.args);
  assert.deepEqual(adjustPrices(...example.args).map(row => row.adjustedClose), [50, 50, 51]);
  assert.equal(JSON.stringify(example.args), before);
  assert.throws(() => adjustPrices([{security: "X", date: "2025-01-01", close: 2}], "2025-01-01"), /invalid_price_or_factor/);
  assert.throws(() => adjustPrices(example.args[0], "missing"), /missing_anchor/);
  assert.throws(() => adjustPrices([...example.args[0], example.args[0][0]], example.args[1]), /duplicate/);
  assert.throws(() => adjustPrices([{ ...example.args[0][0], date: "2025-02-30" }], "2025-02-30"), /invalid_or_duplicate_date/);
});
test("as-of selection excludes unreleased, late-captured and revised future records", () => {
  const rows = tutorialExamples["pit-fundamentals-panel"].args[0];
  assert.equal(selectAsOf(rows, "2025-03-01T00:00:00Z").length, 0);
  assert.equal(selectAsOf(rows, "2025-03-31T23:59:59+08:00")[0].value, 100);
  assert.equal(selectAsOf(rows, "2025-04-11T00:00:00+08:00")[0].value, 105);
  assert.equal(selectAsOf([{ ...rows[0], firstSeenAt: "2025-05-01T00:00:00Z" }], "2025-04-30T00:00:00Z").length, 0);
  assert.throws(() => selectAsOf(rows, "2025-03-31"), /timezone_required/);
  assert.throws(() => selectAsOf([rows[0], { ...rows[0], version: "other" }], "2025-05-01T00:00:00Z"), /ambiguous/);
  assert.throws(() => selectAsOf([rows[1], rows[0], { ...rows[0], version: "other" }], "2025-05-01T00:00:00Z"), /ambiguous/);
  assert.deepEqual(selectAsOf([...rows].reverse(), "2025-05-01T00:00:00Z"), selectAsOf(rows, "2025-05-01T00:00:00Z"));
});
test("event alignment deduplicates, respects timezone and leaves date-only/short-calendar gaps visible", () => {
  const [events, sessions] = tutorialExamples["company-event-timeline"].args;
  const result = alignEvents(events, sessions);
  assert.equal(result.length, 2);
  assert.equal(result[0].sessionOpen, "2025-01-06T09:30:00+08:00");
  assert.equal(result[1].status, "needs_review");
  assert.equal(result[1].sessionOpen, null);
  assert.equal(alignEvents([events[0]], [sessions[0]])[0].status, "outside_calendar");
  const equivalent = { ...events[0], publishedAt: "2025-01-03T10:00:00Z", firstSeenAt: "2025-01-03T10:02:00Z" };
  assert.equal(alignEvents([equivalent], sessions)[0].sessionOpen, result[0].sessionOpen);
  assert.throws(() => alignEvents([events[0], {...events[0], publishedAt: "2025-01-04T00:00:00Z"}], sessions), /conflicting/);
});
test("displayed copyable example code executes the same tested functions without network access", () => {
  for (const [id, example] of Object.entries(tutorialExamples)) {
    let output;
    runInNewContext(tutorialCode(id), { console: { log(value) { output = value; } } }, { timeout: 500 });
    assert.equal(JSON.stringify(output), JSON.stringify(example.execute(...example.args)));
    assert.doesNotMatch(tutorialCode(id), /fetch\(|XMLHttpRequest|localStorage/);
  }
});

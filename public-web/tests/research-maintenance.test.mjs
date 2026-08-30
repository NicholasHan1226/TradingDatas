import test from "node:test";
import assert from "node:assert/strict";
import { auditContent, sourceUrls, classifyLink, checkLinks, comparePublication, checkPublicationMetadata } from "../scripts/audit-research-content.mjs";
import { papers } from "../src/researchCatalog.js";
import { researchReaderNotes } from "../src/researchReaderNotes.js";

test("read-only maintenance distinguishes valid structure from editorial depth candidates", () => {
  const report = auditContent({ today: "2026-08-30" });
  assert.deepEqual(report.errors, []);
  assert.equal(report.records, 200);
  assert.equal(report.guides, 24);
  assert.equal(report.tutorials, 6);
  assert.equal(report.review.filter(item => item.code === "summary_only").length, 176);
  assert.equal(new Set(sourceUrls()).size, sourceUrls().length);
});

test("duplicate identities, omitted translations, broken paths and internal prose are actionable", () => {
  const records = structuredClone(papers), guides = structuredClone(researchReaderNotes);
  records[1].id = records[0].id;
  records[1].sourceTitle = records[0].sourceTitle;
  records[1].evidence.doi = records[0].evidence.doi;
  records[2].summary.en = "";
  records[3].verifiedAt = "2027-01-01";
  const title = Object.keys(guides)[0];
  guides[title].sections[0].body.zh = "出版信息已核对";
  const report = auditContent({ records, guides, paths: [{ id: "broken", titles: ["Missing work"] }], today: "2026-08-30" });
  for (const code of ["duplicate_id", "duplicate_title", "duplicate_doi", "missing_translation", "future_review_date", "broken_reading_path", "internal_note_in_prose"]) assert.ok(report.errors.some(item => item.code === code), code);
});

test("review dates, source versions and repeated prose remain review items, never automatic rewrites", () => {
  const guides = structuredClone(researchReaderNotes), titles = Object.keys(guides);
  guides[titles[1]].sections[0].body = structuredClone(guides[titles[0]].sections[0].body);
  guides[titles[0]].reviewedAt = "2020-01-01";
  const report = auditContent({ guides, today: "2026-08-30" });
  assert.ok(report.review.some(item => item.code === "repeated_paragraph"));
  assert.ok(report.review.some(item => item.code === "review_age"));
  assert.ok(report.review.some(item => item.code === "check_reading_scope"));
  assert.deepEqual(report.errors, []);
});

test("link checks distinguish broken, restricted, throttled and transient responses with bounded concurrency", async () => {
  for (const [status, expected] of [[200, "reachable_not_content_verified"], [404, "broken"], [410, "broken"], [403, "access_restricted"], [429, "rate_limited"], [503, "needs_retry_or_review"]]) assert.equal(classifyLink(status), expected);
  const calls = [], urls = ["https://example.org/fallback", "https://example.org/missing", "https://example.org/restricted", "https://example.org/network"];
  let active = 0, peak = 0, canceled = 0;
  const results = await checkLinks(urls, { fetcher: async (url, options) => {
    active++; peak = Math.max(peak, active); calls.push([url, options.method]);
    await new Promise(resolve => setTimeout(resolve, 1)); active--;
    if (url.endsWith("network")) throw new TypeError("network");
    return { status: url.endsWith("fallback") ? options.method === "HEAD" ? 405 : 200 : url.endsWith("missing") ? 404 : 403, url, body: { cancel: async () => { canceled++; } } };
  } });
  assert.deepEqual(results.map(item => item.state), ["reachable_not_content_verified", "broken", "access_restricted", "network_error"]);
  assert.ok(peak <= 2);
  assert.equal(calls.filter(item => item[1] === "GET").length, 1);
  assert.equal(canceled, 4);
  const timed = await checkLinks([urls[0]], { timeoutMs: 2, fetcher: async (_, { signal }) => new Promise((_, reject) => signal.addEventListener("abort", () => reject(new Error("aborted")))) });
  assert.equal(timed[0].state, "timeout");
});

test("publication checks flag changed fields and publisher updates without changing saved identities", async () => {
  const record = { id: "demo", evidence: { title: "Original Work", doi: "10.1/example", venue: "Journal", year: 2020, authors: ["A Reader"] } };
  const work = { title: ["Original Work"], DOI: "10.1/example", "container-title": ["Journal"], "published-print": { "date-parts": [[2020]] }, author: [{ given: "A", family: "Reader" }] };
  assert.equal(comparePublication(record, work).state, "registered_metadata_matches");
  const changed = { ...work, title: ["Corrected Work"], "update-to": [{ DOI: "10.1/correction", type: "correction" }] };
  assert.deepEqual(comparePublication(record, changed).changedFields, ["title"]);
  const before = structuredClone(record);
  const result = await checkPublicationMetadata([record], { fetcher: async () => ({ ok: true, json: async () => ({ message: changed }) }) });
  assert.equal(result[0].state, "metadata_needs_review");
  assert.equal(result[0].updates.length, 1);
  assert.deepEqual(record, before);
  const blocked = await checkPublicationMetadata([record], { fetcher: async () => ({ ok: false, status: 429 }) });
  assert.equal(blocked[0].state, "rate_limited");
});

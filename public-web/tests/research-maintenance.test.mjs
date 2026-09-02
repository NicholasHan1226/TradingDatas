import test from "node:test";
import assert from "node:assert/strict";
import { auditContent, sourceUrls, classifyLink, checkLinks, comparePublication, checkPublicationMetadata, parseEditorialResponse } from "../scripts/audit-research-content.mjs";
import { papers } from "../src/researchCatalog.js";
import { researchReaderNotes } from "../src/researchReaderNotes.js";

test("read-only maintenance distinguishes valid structure from editorial depth candidates", () => {
  const report = auditContent({ today: "2026-09-01" });
  assert.deepEqual(report.errors, []);
  assert.equal(report.records, 200);
  assert.equal(report.guides, 180);
  assert.equal(report.tutorials, 6);
  assert.equal(report.review.filter(item => item.code === "summary_only").length, 20);
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
  const report = auditContent({ guides, today: "2026-09-01" });
  assert.ok(report.review.some(item => item.code === "repeated_paragraph"));
  assert.ok(report.review.some(item => item.code === "review_age"));
  assert.ok(!report.review.some(item => item.code === "check_reading_scope"));
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

test("direct-file links flag HTML shells and distinguish unconfirmed types without downloading bodies", async () => {
  const cases = [
    ["https://example.org/paper.PDF?download=1", 200, "text/html; charset=UTF-8", "unexpected_content_type"],
    ["https://example.org/paper.txt", 200, "application/xhtml+xml", "unexpected_content_type"],
    ["https://example.org/paper.pdf", 200, "Application/PDF", "reachable_not_content_verified"],
    ["https://example.org/paper.txt", 200, "text/plain; charset=utf-8", "reachable_not_content_verified"],
    ["https://example.org/paper.pdf", 200, "application/octet-stream", "file_type_unconfirmed"],
    ["https://example.org/paper.pdf", 200, "", "file_type_unconfirmed"],
    ["https://example.org/paper.pdf", 403, "text/html", "access_restricted"],
    ["https://example.org/paper.pdf", 404, "text/html", "broken"],
    ["https://example.org/paper.pdf", 429, "text/html", "rate_limited"],
    ["https://example.org/landing?file=paper.pdf", 200, "text/html", "reachable_not_content_verified"],
  ];
  let calls = 0;
  const results = await checkLinks(cases.map(([url]) => url), { concurrency: 1, fetcher: async (_, options) => {
    const [url, status, contentType] = cases[calls++];
    assert.equal(options.method, "HEAD");
    return { status, url: `${new URL(url).origin}/landing`, headers: new Headers({ "Content-Type": contentType }) };
  } });
  assert.deepEqual(results.map(item => item.state), cases.map(item => item[3]));
  assert.equal(calls, cases.length);
  assert.equal(results[0].expectedContentType, "application/pdf");
  assert.equal(results[0].contentType, "text/html");
  assert.equal(results[0].finalUrl, "https://example.org/landing");
});

test("curl response metadata uses the final content type and leaves JSON parsing intact", async () => {
  const response = parseEditorialResponse('{"message":{"DOI":"10.1/demo"}}\nTD_EDITORIAL_HTTP:200\thttps://example.org/final\tapplication/json; charset=utf-8');
  assert.equal(response.status, 200);
  assert.equal(response.contentType, "application/json; charset=utf-8");
  assert.deepEqual(await response.json(), { message: { DOI: "10.1/demo" } });
  const head = parseEditorialResponse('HTTP/1.1 302 Found\r\nContent-Type: text/html\r\n\r\nHTTP/2 200\r\nContent-Type: application/pdf\r\n\nTD_EDITORIAL_HTTP:200\thttps://example.org/file.pdf\tapplication/pdf');
  assert.equal(head.contentType, "application/pdf");
  assert.throws(() => parseEditorialResponse("unframed output"), /missing_http_status/);
});

test("unsupported HEAD checks the fallback type while preserving the existing request bound", async () => {
  const calls = [];
  let canceled = 0;
  const result = await checkLinks(["https://example.org/paper.pdf"], { fetcher: async (url, options) => {
    calls.push(options);
    return { url, status: options.method === "HEAD" ? 405 : 206, contentType: "text/html; charset=utf-8", body: { cancel: async () => { canceled++; } } };
  } });
  assert.deepEqual(calls.map(call => call.method), ["HEAD", "GET"]);
  assert.equal(calls[1].headers.Range, "bytes=0-0");
  assert.equal(canceled, 2);
  assert.equal(result[0].state, "unexpected_content_type");
});

// Read-only editorial maintenance. No refresh, rewrite, ingestion or publication.
import { pathToFileURL } from "node:url";
import { execFile } from "node:child_process";
import { promisify } from "node:util";
import { papers, readingPaths } from "../src/researchCatalog.js";
import { researchReaderNotes } from "../src/researchReaderNotes.js";
import { preparationTutorials } from "../src/preparationTutorials.js";
import { researchJourneys } from "../src/researchJourneys.js";

const normalize = value => String(value ?? "").normalize("NFKC").toLowerCase().replace(/[^\p{L}\p{N}]/gu, "");
const validUrl = value => { try { return new URL(value).protocol === "https:"; } catch { return false; } };
const validDate = value => typeof value === "string" && /^\d{4}-\d{2}-\d{2}$/.test(value) && Number.isFinite(Date.parse(value)) && new Date(value).toISOString().slice(0, 10) === value;
const run = promisify(execFile);

// Reuse the repository verifier's system-curl transport and certificate trust.
// TLS verification stays enabled. Bodies are bounded and never persisted.
export async function fetchEditorialSource(url, options = {}) {
  if (!validUrl(url)) throw new Error("https_required");
  const args = ["--silent", "--show-error", "--location", "--proto", "=https", "--proto-redir", "=https", "--max-redirs", "5", "--max-time", "30"];
  if (options.method === "HEAD") args.push("--head");
  for (const [key, value] of Object.entries(options.headers || {})) args.push("--header", `${key}: ${value}`);
  args.push("--write-out", "\nTD_EDITORIAL_HTTP:%{http_code}\t%{url_effective}\t%{content_type}", url);
  const { stdout } = await run("curl", args, { signal: options.signal, maxBuffer: 4 * 1024 * 1024 });
  return parseEditorialResponse(stdout);
}

export function parseEditorialResponse(stdout) {
  const marker = stdout.lastIndexOf("\nTD_EDITORIAL_HTTP:");
  if (marker < 0) throw new Error("missing_http_status");
  const [statusText, finalUrl, contentType = ""] = stdout.slice(marker + "\nTD_EDITORIAL_HTTP:".length).split("\t");
  const status = Number(statusText), body = stdout.slice(0, marker);
  return { status, url: finalUrl, contentType, ok: status >= 200 && status < 300, json: async () => JSON.parse(body) };
}

export function auditContent({ records = papers, guides = researchReaderNotes, tutorials = preparationTutorials, paths = readingPaths, journeys = researchJourneys, today = new Date().toISOString().slice(0, 10) } = {}) {
  if (!validDate(today)) throw new Error("invalid_audit_date");
  const errors = [], review = [];
  const issue = (list, code, id, field) => list.push({ code, id, field });
  const seen = { id: new Map(), title: new Map(), doi: new Map() }, prose = new Map();
  const bilingual = (value, id, field) => {
    for (const locale of ["zh", "en"]) {
      if (typeof value?.[locale] !== "string" || !value[locale].trim()) issue(errors, "missing_translation", id, `${field}.${locale}`);
      if (/出版信息已核对|准备状态|来源核验|TODO|PLACEHOLDER|AUTODEV_RETURN/.test(value?.[locale] || "")) issue(errors, "internal_note_in_prose", id, `${field}.${locale}`);
    }
    if (value?.zh && !/[\u3400-\u9fff]/.test(value.zh)) issue(review, "check_chinese_translation", id, field);
    if (value?.en && /[\u3400-\u9fff]/.test(value.en)) issue(review, "check_english_translation", id, field);
  };
  const source = (url, id, field) => { if (!validUrl(url)) issue(errors, "invalid_https_source", id, field); };
  const date = (value, id, field, maxAge) => {
    if (!validDate(value)) issue(errors, "invalid_date", id, field);
    else if (value > today) issue(errors, "future_review_date", id, field);
    else if ((Date.parse(today) - Date.parse(value)) / 86400000 > maxAge) issue(review, "review_age", id, field);
  };
  const titles = new Set(records.flatMap(row => [row.title, row.sourceTitle]));
  for (const row of records) {
    for (const [field, value] of [["id", row.id], ["title", normalize(row.sourceTitle)], ["doi", row.evidence?.doi?.toLowerCase()]]) {
      if (!value && field !== "doi") issue(errors, "missing_identity", row.id, field);
      if (!value) continue;
      if (seen[field].has(value)) issue(errors, `duplicate_${field}`, row.id, seen[field].get(value));
      seen[field].set(value, row.id);
    }
    bilingual({ zh: row.titleZh, en: row.sourceTitle }, row.id, "title");
    bilingual(row.summary, row.id, "summary");
    if (!row.sources?.length) issue(errors, "missing_sources", row.id, "sources");
    for (const item of row.sources || []) source(item.url, row.id, "sources");
    date(row.verifiedAt, row.id, "source_identity_checked_at", row.year === "living" ? 90 : 365);
    if (row.sourceNote) bilingual(row.sourceNote, row.id, "sourceNote");
    if (!guides[row.title]) issue(review, "summary_only", row.id, "editorial_depth");
  }
  for (const [title, guide] of Object.entries(guides)) {
    if (!titles.has(title)) issue(errors, "orphan_guide", title, "title");
    source(guide.evidenceUrl, title, "evidenceUrl");
    date(guide.reviewedAt, title, "editorial_reviewed_at", 365);
    if (!guide.evidenceScope?.trim()) issue(errors, "missing_reading_scope", title, "evidenceScope");
    if (/abstract/i.test(guide.evidenceScope || "") && !/not.*abstract|beyond.*abstract/i.test(guide.evidenceScope || "")) issue(review, "check_reading_scope", title, "evidenceScope");
    bilingual(guide.limits, title, "limits");
    if ((guide.sections?.length || 0) < 4) issue(review, "short_guide", title, "sections");
    for (const [index, section] of (guide.sections || []).entries()) {
      bilingual(section.title, title, `sections.${index}.title`);
      bilingual(section.body, title, `sections.${index}.body`);
      if (section.reference) { source(section.reference.url, title, `sections.${index}.reference`); bilingual(section.reference.label, title, `sections.${index}.reference.label`); }
      for (const locale of ["zh", "en"]) {
        const text = section.body?.[locale] || "", key = normalize(text);
        if (text.length < (locale === "zh" ? 60 : 120)) issue(review, "short_paragraph", title, `sections.${index}.${locale}`);
        if (key && prose.has(key)) issue(review, "repeated_paragraph", title, prose.get(key));
        if (key) prose.set(key, `${title}:${index}:${locale}`);
      }
    }
  }
  for (const [id, tutorial] of Object.entries(tutorials)) {
    for (const field of ["title", "summary", "goal", "expected"]) bilingual(tutorial[field], id, field);
    for (const [index, step] of (tutorial.steps || []).entries()) { bilingual(step.title, id, `steps.${index}.title`); bilingual(step.body, id, `steps.${index}.body`); }
    for (const field of ["fields", "pitfalls"]) for (const [index, value] of (tutorial[field] || []).entries()) bilingual(value, id, `${field}.${index}`);
    for (const item of tutorial.sources || []) { source(item.url, id, "sources"); bilingual(item.label, id, "source_label"); }
    for (const title of tutorial.research || []) if (!titles.has(title)) issue(errors, "broken_research_reference", id, title);
  }
  for (const path of paths) for (const title of path.titles) if (!titles.has(title)) issue(errors, "broken_reading_path", path.id, title);
  for (const [id, journey] of Object.entries(journeys)) for (const item of journey) {
    if (!titles.has(item.title)) issue(errors, "broken_journey", id, item.title);
    bilingual(item.reason, id, "journey.reason");
  }
  return { auditDate: today, records: records.length, guides: Object.keys(guides).length, tutorials: Object.keys(tutorials).length, errors, review, note: "Review items are editorial candidates, not proven defects. Length, HTTP success and a source date do not certify content quality or full-text review." };
}

export function sourceUrls({ records = papers, guides = researchReaderNotes, tutorials = preparationTutorials } = {}) {
  return [...new Set([
    ...records.flatMap(row => (row.sources || []).map(item => item.url)),
    ...Object.values(guides).flatMap(guide => [guide.evidenceUrl, ...(guide.sections || []).flatMap(section => section.reference ? [section.reference.url] : [])]),
    ...Object.values(tutorials).flatMap(tutorial => (tutorial.sources || []).map(item => item.url)),
  ].filter(validUrl))].sort();
}

export function classifyLink(status) {
  if (status >= 200 && status < 300) return "reachable_not_content_verified";
  if (status === 404 || status === 410) return "broken";
  if ([401, 403, 451].includes(status)) return "access_restricted";
  if (status === 429) return "rate_limited";
  return "needs_retry_or_review";
}

export function comparePublication(record, work) {
  const registered = {
    title: work.title?.[0], doi: work.DOI, venue: work["container-title"]?.[0] || work.publisher,
    year: (work["published-print"] || work.published || work["published-online"])?.["date-parts"]?.[0]?.[0],
    authors: (work.author || []).map(author => [author.given, author.family || author.name].filter(Boolean).join(" ")),
  };
  const changedFields = ["title", "doi", "venue", "year", "authors"].filter(field => normalize(registered[field]) !== normalize(record.evidence?.[field]));
  const updates = work["update-to"] || [];
  return { id: record.id, doi: record.evidence?.doi, state: changedFields.length || updates.length ? "metadata_needs_review" : "registered_metadata_matches", changedFields, updates, note: "Metadata comparison only; no automatic version replacement or full-text validation." };
}

export async function checkPublicationMetadata(records, { fetcher = fetchEditorialSource, timeoutMs = 8000 } = {}) {
  if (!Number.isFinite(timeoutMs) || timeoutMs < 1 || timeoutMs > 30000 || records.length > 50) throw new Error("invalid_metadata_budget");
  const results = [];
  // Intentionally serial and bounded. No DOI discovery or recursive update fetches.
  for (const record of records) {
    if (!record.evidence?.doi) continue;
    const url = `https://api.crossref.org/works/${encodeURIComponent(record.evidence.doi)}`;
    const controller = new AbortController(), timer = setTimeout(() => controller.abort(), timeoutMs);
    try {
      const response = await fetcher(url, { signal: controller.signal, headers: { "User-Agent": "TradingDatasEditorialMetadataCheck/1.0" } });
      if (!response.ok) { results.push({ id: record.id, url, status: response.status, state: classifyLink(response.status) }); await response.body?.cancel(); }
      else { const body = await response.json(); if (!body.message?.DOI) throw new Error("invalid_crossref_response"); results.push({ ...comparePublication(record, body.message), url }); }
    } catch (error) { results.push({ id: record.id, url, state: controller.signal.aborted ? "timeout" : "metadata_unavailable", error: error.name }); }
    finally { clearTimeout(timer); }
  }
  return results;
}

export async function checkLinks(urls, { fetcher = fetchEditorialSource, timeoutMs = 8000, concurrency = 2 } = {}) {
  if (!Number.isInteger(concurrency) || concurrency < 1 || concurrency > 4 || timeoutMs < 1 || timeoutMs > 30000) throw new Error("invalid_link_budget");
  const results = new Array(urls.length);
  let cursor = 0;
  await Promise.all(Array.from({ length: concurrency }, async () => {
    while (cursor < urls.length) {
      const index = cursor++, url = urls[index];
      if (!validUrl(url)) { results[index] = { url, state: "invalid_url" }; continue; }
      const controller = new AbortController(), timer = setTimeout(() => controller.abort(), timeoutMs);
      try {
        const options = { method: "HEAD", signal: controller.signal, redirect: "follow", headers: { "User-Agent": "TradingDatasEditorialLinkCheck/1.0" } };
        let response = await fetcher(url, options);
        if ([405, 501].includes(response.status)) {
          await response.body?.cancel();
          response = await fetcher(url, { ...options, method: "GET", headers: { ...options.headers, Range: "bytes=0-0" } });
        }
        const contentType = String(response.headers?.get?.("content-type") ?? response.contentType ?? "").split(";")[0].trim().toLowerCase();
        // Only explicit file paths carry a format expectation. A DOI or landing
        // page is not assumed to serve a PDF, even if its query mentions one.
        const path = new URL(url).pathname.toLowerCase();
        const expectedContentType = path.endsWith(".pdf") ? "application/pdf" : path.endsWith(".txt") ? "text/plain" : null;
        let state = classifyLink(response.status);
        if (state === "reachable_not_content_verified" && expectedContentType && contentType !== expectedContentType) {
          state = !contentType || contentType === "application/octet-stream" ? "file_type_unconfirmed" : "unexpected_content_type";
        }
        results[index] = { url, finalUrl: response.url || url, status: response.status, contentType, expectedContentType, state };
        await response.body?.cancel();
      } catch (error) { results[index] = { url, state: controller.signal.aborted ? "timeout" : "network_error", error: error.name }; }
      finally { clearTimeout(timer); }
    }
  }));
  return results;
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const args = process.argv.slice(2);
  const option = (name, fallback, max) => {
    const flag = args.find(value => value.startsWith(`--${name}=`));
    const value = flag ? Number(flag.split("=")[1]) : fallback;
    if (!Number.isInteger(value) || value < 0 || value > max) throw new Error(`invalid_${name}`);
    return value;
  };
  if (args.some(arg => !["--links", "--metadata"].includes(arg) && !/^--(limit|offset|timeout-ms)=\d+$/.test(arg))) throw new Error("unknown_argument");
  const report = auditContent();
  if (args.includes("--links")) {
    const urls = sourceUrls(), offset = option("offset", 0, urls.length), limit = option("limit", 20, 300);
    report.linkCheck = { totalUrls: urls.length, offset, limit, results: await checkLinks(urls.slice(offset, offset + limit), { timeoutMs: option("timeout-ms", 8000, 30000) }) };
  }
  if (args.includes("--metadata")) {
    const records = papers.filter(row => row.evidence?.doi), offset = option("offset", 0, records.length), limit = option("limit", 20, 50);
    report.metadataCheck = { totalRecords: records.length, offset, limit, results: await checkPublicationMetadata(records.slice(offset, offset + limit), { timeoutMs: option("timeout-ms", 8000, 30000) }) };
  }
  console.log(JSON.stringify(report, null, 2));
  if (report.errors.length || report.linkCheck?.results.some(item => item.state === "broken")) process.exitCode = 1;
}

import assert from "node:assert/strict";
import { after, before, test } from "node:test";
import { fileURLToPath } from "node:url";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { createServer } from "vite";
import { papers, legacySourceChecks } from "../src/researchCatalog.js";
import { researchReaderNotes } from "../src/researchReaderNotes.js";
import { projectResearchIndex } from "../scripts/research-public-projection.mjs";
import { comparisonReadings } from "../src/researchConnections.js";
import { readingJourney } from "../src/researchJourneys.js";

let server;
let ResearchRecord;
const escapeHtml = value => value.replace(/[&<>"']/g, char => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#x27;" }[char]));
before(async () => {
  server = await createServer({ root: fileURLToPath(new URL("..", import.meta.url)), configFile: false, logLevel: "silent", server: { middlewareMode: true, hmr: false, watch: null }, esbuild: { jsx: "automatic" } });
  ({ ResearchRecord } = await server.ssrLoadModule("/src/ResearchRecord.jsx"));
});
after(async () => server?.close());

test("all guide comparisons retain core journeys and localize reasons across body states", () => {
  for (const title of Object.keys(researchReaderNotes)) {
    const paper = projectResearchIndex(papers.find(p => p.title === title));
    const journey = readingJourney(paper, papers);
    const comparisons = comparisonReadings(paper, papers, journey?.links.map(l => l.paper.id));
    for (const locale of ["zh", "en"]) for (const bodyStatus of ["loading", "error", "ready"]) {
      const html = renderToStaticMarkup(createElement(ResearchRecord, { paper, locale, bodyStatus, onRetryBody() {}, topicLabel: paper.topic, kindLabel: paper.kind, related: [], furtherReading: papers.slice(0, 3), saved: false, onToggleBookmark() {}, onNavigate() {} }));
      assert.ok(html.includes(locale === "zh" ? 'aria-label="对照阅读"' : 'aria-label="Read alongside"'));
      assert.doesNotMatch(html, /research-next-list/);
      for (const { paper: target, reason } of comparisons) {
        assert.ok(html.includes(`href="/research/${target.id}"`));
        assert.ok(html.includes(escapeHtml(reason[locale])));
        assert.ok(!html.includes(escapeHtml(reason[locale === "zh" ? "en" : "zh"])));
      }
      if (journey) assert.ok(html.includes(locale === "zh" ? 'aria-label="主题阅读顺序"' : 'aria-label="Topic reading sequence"'));
    }
  }
});

test("uncurated summary records retain the same-topic fallback", () => {
  const paper = papers.find(p => !p.readingNotes?.length && !readingJourney(p, papers) && !comparisonReadings(p, papers).length);
  assert.ok(paper);
  const html = renderToStaticMarkup(createElement(ResearchRecord, { paper, locale: "en", topicLabel: paper.topic, kindLabel: paper.kind, related: [], furtherReading: papers.slice(0, 3), saved: false, onToggleBookmark() {}, onNavigate() {} }));
  assert.match(html, /research-next-list/);
  assert.doesNotMatch(html, /research-comparison-readings/);
});

test("all 200 records render in both languages with direct sources and no internal QA text", () => {
  for (const paper of papers) for (const locale of ["zh", "en"]) {
    const html = renderToStaticMarkup(createElement(ResearchRecord, { paper, locale, topicLabel: paper.topic, kindLabel: paper.kind, related: [], furtherReading: [], saved: false, onToggleBookmark() {}, onNavigate() {} }));
    assert.ok(html.includes(paper.sources[0].url.replaceAll("&", "&amp;")), paper.id);
    assert.match(html, /aria-pressed="false"/);
    assert.doesNotMatch(html, /准备状态|来源核验|出版信息已核对|三项检查|Bibliography checked|Preparation blueprint/);
    assert.doesNotMatch(html, /undefined|\[object Object\]/);
    assert.ok(html.includes(locale === "zh" ? "阅读原文" : "Read original"));
    const guide = researchReaderNotes[paper.title];
    if (guide) {
      assert.ok(!html.includes(escapeHtml(guide.evidenceScope)), `internal reading scope leaked: ${paper.id}`);
      assert.ok(html.includes(escapeHtml(guide.limits[locale])), `missing source limitation: ${paper.id}:${locale}`);
    }
    for (const [index, section] of (paper.readingNotes || []).entries()) {
      assert.ok(html.includes(`href="#research-section-${index+1}"`));
      assert.ok(html.includes(`id="research-section-${index+1}"`));
      assert.ok(html.includes(escapeHtml(section.title[locale])), `missing section title: ${paper.id}:${locale}`);
      assert.ok(html.includes(escapeHtml(section.body[locale])), `missing section body: ${paper.id}:${locale}`);
      if (section.reference) {
        assert.ok(html.includes(escapeHtml(section.reference.label[locale])));
        assert.ok(html.includes(escapeHtml(section.reference.url)));
      }
    }
  }
});

test("specific reading notes have bilingual text and a dated primary-source reference", () => {
  for (const [title, note] of Object.entries(researchReaderNotes)) {
    assert.ok(papers.some((paper) => paper.title === title));
    assert.match(note.evidenceUrl, /^https:\/\//);
    assert.match(note.reviewedAt, /^\d{4}-\d{2}-\d{2}$/);
    for (const locale of ["zh", "en"]) {
      assert.ok(note.limits[locale]);
      for (const section of note.sections) assert.ok(section.title[locale] && section.body[locale].length > 40);
    }
  }
});

test("intentionally empty materials hide the disclosure while selected materials remain navigable", () => {
  const paper = papers.find(p => p.title === "DeFi Risks and the Decentralisation Illusion");
  for (const locale of ["zh", "en"]) {
    const render = related => renderToStaticMarkup(createElement(ResearchRecord, { paper, locale, topicLabel: paper.topic, kindLabel: paper.kind, related, furtherReading: [], saved: false, onToggleBookmark() {}, onNavigate() {} }));
    assert.doesNotMatch(render([]), /research-related-disclosure/);
    const selected = render([{ id: "document-version-ledger", label: "Method", title: "Document versions", href: "/recipes/document-version-ledger" }]);
    assert.match(selected, /research-related-disclosure/);
    assert.match(selected, /href="\/recipes\/document-version-ledger"/);
    assert.ok(selected.includes(locale === "zh" ? "不等同于论文原始样本" : "not the paper’s original sample"));
  }
});

test("legacy official-source check dates are explicit per-record history", () => {
  for (const [title, date] of Object.entries(legacySourceChecks)) {
    const paper = papers.find((item) => item.title === title);
    assert.equal(paper.verifiedAt, date);
    assert.equal(paper.evidence.checkedAt, date);
  }
});

test("loading and error shells retain source actions and expose bilingual status and retry", () => {
  const paper = projectResearchIndex(papers.find(p => p.id === "lazy-prices"));
  for (const locale of ["zh", "en"]) for (const bodyStatus of ["loading", "error"]) {
    const html = renderToStaticMarkup(createElement(ResearchRecord, { paper, locale, bodyStatus, onRetryBody() {}, topicLabel: paper.topic, kindLabel: paper.kind, related: [], furtherReading: [], saved: false, onToggleBookmark() {}, onNavigate() {} }));
    assert.ok(html.includes(paper.sources[0].url.replaceAll("&", "&amp;")));
    assert.ok(html.includes(locale === "zh" ? "阅读原文" : "Read original"));
    assert.match(html, bodyStatus === "loading" ? /role="status"/ : /role="alert"/);
    assert.doesNotMatch(html, /undefined|\[object Object\]|id="research-section-1"/);
    if (bodyStatus === "error") assert.ok(html.includes(locale === "zh" ? "重试" : "Try again"));
  }
});

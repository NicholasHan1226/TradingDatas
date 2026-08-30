import assert from "node:assert/strict";
import { after, before, test } from "node:test";
import { fileURLToPath } from "node:url";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { createServer } from "vite";
import { papers, legacySourceChecks } from "../src/researchCatalog.js";
import { researchReaderNotes } from "../src/researchReaderNotes.js";

let server;
let ResearchRecord;
const escapeHtml = value => value.replace(/[&<>"']/g, char => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#x27;" }[char]));
before(async () => {
  server = await createServer({ root: fileURLToPath(new URL("..", import.meta.url)), configFile: false, logLevel: "silent", server: { middlewareMode: true, hmr: false, watch: null }, esbuild: { jsx: "automatic" } });
  ({ ResearchRecord } = await server.ssrLoadModule("/src/ResearchRecord.jsx"));
});
after(async () => server?.close());

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

test("legacy official-source check dates are explicit per-record history", () => {
  for (const [title, date] of Object.entries(legacySourceChecks)) {
    const paper = papers.find((item) => item.title === title);
    assert.equal(paper.verifiedAt, date);
    assert.equal(paper.evidence.checkedAt, date);
  }
});

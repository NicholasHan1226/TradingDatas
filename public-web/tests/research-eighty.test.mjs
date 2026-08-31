import test from "node:test";
import assert from "node:assert/strict";
import { papers } from "../src/researchCatalog.js";
import { researchReaderNotes } from "../src/researchReaderNotes.js";
import { researchSeventyGuides } from "../src/researchSeventyGuides.js";
import { researchEightyGuides } from "../src/researchEightyGuides.js";
import { researchConnections, comparisonReadings } from "../src/researchConnections.js";
import { projectResearchIndex } from "../scripts/research-public-projection.mjs";
import { auditContent } from "../scripts/audit-research-content.mjs";

const additions = { ...researchSeventyGuides, ...researchEightyGuides };
test("two disjoint batches add twenty bounded bilingual guides within the same 200 works", () => {
  assert.equal(Object.keys(researchSeventyGuides).length, 10);
  assert.equal(Object.keys(researchEightyGuides).length, 10);
  assert.equal(Object.keys(additions).length, 20);
  assert.equal(papers.length, 200);
  assert.equal(new Set(papers.map(p => p.id)).size, 200);
  assert.equal(Object.keys(researchReaderNotes).length, 120);
  assert.equal(Object.values(researchReaderNotes).filter(g => g.sections.length === 6).length, 119);
  for (const [title, guide] of Object.entries(additions)) {
    assert.equal(papers.filter(p => p.title === title).length, 1, title);
    assert.equal(researchReaderNotes[title], guide);
    assert.equal(guide.sections.length, 6);
    assert.equal(guide.reviewedAt, "2026-08-31");
    assert.ok(guide.evidenceScope.length > 90);
    assert.deepEqual(guide.related, {});
    assert.deepEqual(papers.find(p => p.title === title).related, {});
    for (const locale of ["zh", "en"]) {
      assert.ok(guide.limits[locale].length > 30);
      for (const section of guide.sections) {
        assert.ok(section.title[locale]);
        assert.ok(section.body[locale].length >= (locale === "zh" ? 60 : 120));
        assert.ok(section.reference.label[locale]);
        assert.equal(section.reference.url, guide.evidenceUrl);
      }
    }
  }
  const audit = auditContent();
  assert.deepEqual(audit.errors, []);
  assert.equal(audit.review.filter(r => r.code === "summary_only").length, 80);
});

test("measurement, edition and source-access limits survive expansion", () => {
  const prose = title => additions[title].sections.map(s => s.body.en).join(" ");
  assert.match(prose("A Simple Approximate Long-Memory Model of Realized Volatility"), /square root/);
  assert.match(prose("Comparing Predictive Accuracy"), /median.*not generally its mean/);
  assert.match(prose("Law, Finance, and Economic Growth in China"), /17/);
  assert.match(prose("Credit Spreads and Business Cycle Fluctuations"), /half the error variance/);
  assert.match(prose("In Search of Attention"), /zero/i);
  assert.match(prose("Measuring the Effects of Monetary Policy: A Factor-Augmented Vector Autoregressive \(FAVAR\) Approach"), /rule/);
  assert.equal(researchReaderNotes["The Stationary Bootstrap"], undefined);
  assert.equal(researchReaderNotes["Textual Analysis in Accounting and Finance: A Survey"], undefined);
});

test("85 authored comparison pairs resolve to real works and have localized reasons", () => {
  assert.equal(researchConnections.length, 85);
  const seen = new Set();
  for (const pair of researchConnections) {
    assert.notEqual(pair.left, pair.right);
    const key = [pair.left, pair.right].sort().join("\n");
    assert.ok(!seen.has(key)); seen.add(key);
    for (const title of [pair.left, pair.right]) assert.equal(papers.filter(p => p.title === title).length, 1, title);
    for (const locale of ["zh", "en"]) assert.ok(pair.reason[locale].length > 30);
  }
});

test("all twenty additions have bounded comparisons using metadata only", () => {
  const catalog = papers.map(projectResearchIndex);
  for (const title of Object.keys(additions)) {
    const paper = catalog.find(p => p.title === title);
    const readings = comparisonReadings(paper, catalog);
    assert.ok(readings.length >= 1 && readings.length <= 3, title);
    assert.equal(new Set(readings.map(r => r.paper.id)).size, readings.length);
    assert.ok(readings.every(r => r.paper.id !== paper.id && !r.paper.readingNotes));
    assert.deepEqual(comparisonReadings(paper, catalog, catalog.map(p => p.id)), []);
  }
  assert.deepEqual(comparisonReadings({ id: "missing", title: "Uncurated work" }, catalog), []);
  assert.deepEqual(comparisonReadings(catalog.find(p => p.title === "Time Series Momentum"), []), []);
});

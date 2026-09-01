import test from "node:test";
import assert from "node:assert/strict";
import { researchEditorial } from "../src/researchEditorial.js";
import { researchDeepReads } from "../src/researchDeepReads.js";
import { researchGuideDepthExpansion } from "../src/researchGuideDepthExpansion.js";
import { researchReaderNotes } from "../src/researchReaderNotes.js";
import { researchMethodsMarketsGuides } from "../src/researchMethodsMarketsGuides.js";
import { papers } from "../src/researchCatalog.js";
import { sourceUrls, auditContent } from "../scripts/audit-research-content.mjs";

const pending = [
  "The Quality of Accruals and Earnings: The Role of Accrual Estimation Errors",
];

test("15 supported extensions coexist with 160 guides, 200 works and one honest source gap", () => {
  assert.equal(Object.keys(researchGuideDepthExpansion).length, 15);
  assert.equal(papers.length, 200);
  assert.equal(new Set(papers.map(p => p.id)).size, 200);
  assert.equal(Object.keys(researchReaderNotes).length, 160);
  assert.equal(Object.values(researchReaderNotes).filter(g => g.sections.length === 6).length, 159);
  assert.deepEqual(Object.entries(researchReaderNotes).filter(([, g]) => g.sections.length === 4).map(([title]) => title).sort(), [...pending].sort());
  for (const title of pending) {
    assert.equal(researchReaderNotes[title], researchEditorial[title]);
    assert.match(researchReaderNotes[title].evidenceScope, /abstract/i);
  }
  for (const [title, guide] of Object.entries(researchDeepReads)) assert.equal(researchReaderNotes[title], guide);
});

test("extensions preserve original sections and integrate bilingual, individually located evidence", () => {
  const knownUrls = new Set(sourceUrls());
  const paragraphs = new Set();
  for (const [title, guide] of Object.entries(researchGuideDepthExpansion)) {
    const original = researchEditorial[title];
    assert.equal(original.sections.length, 4, `baseline mutated: ${title}`);
    assert.equal(guide.sections.length, 6);
    assert.equal(guide.reviewedAt, "2026-08-30");
    assert.ok(guide.evidenceScope.length > 80);
    assert.match(guide.evidenceUrl, /^https:\/\//);
    const effective = researchMethodsMarketsGuides[title] || guide;
    assert.deepEqual(papers.find(p => p.title === title).readingNotes, effective.sections);
    for (const [oldIndex, newIndex] of [[0, 0], [1, 2], [3, 5]]) {
      if (title === "Lazy Prices" && oldIndex === 1) {
        assert.match(guide.sections[newIndex].reference.label.en, /§II, pp\. 11, 14/);
        assert.equal(original.sections[oldIndex].title.en, "Start with a comparable pair");
        continue;
      }
      assert.deepEqual(guide.sections[newIndex], original.sections[oldIndex]);
      assert.notEqual(guide.sections[newIndex], original.sections[oldIndex]);
    }
    for (const index of [1, 4]) {
      const section = guide.sections[index];
      // Superseded source URLs remain historical evidence, not active public links.
      if (effective === guide) assert.ok(knownUrls.has(section.reference.url));
      for (const locale of ["zh", "en"]) {
        assert.ok(section.title[locale] && section.reference.label[locale]);
        assert.ok(section.body[locale].length >= (locale === "zh" ? 85 : 200));
        assert.ok(!paragraphs.has(section.body[locale]), `duplicated paragraph: ${title}`);
        paragraphs.add(section.body[locale]);
      }
      assert.match(section.body.zh, /[\u3400-\u9fff]/);
      assert.doesNotMatch(section.body.en, /[\u3400-\u9fff]/);
    }
  }
  assert.deepEqual(auditContent({ today: "2026-09-01" }).errors, []);
});

test("working-copy caveats and estimator-specific adjustments survive public projection", () => {
  for (const title of ["Lazy Prices", "Bitcoin: Economics, Technology, and Governance", "Estimating Standard Errors in Finance Panel Data Sets: Comparing Approaches"]) {
    const guide = researchGuideDepthExpansion[title];
    assert.match(guide.limits.en, /working paper|author draft/);
    assert.match(guide.limits.zh, /工作论文|作者草稿/);
  }
  const spread = researchGuideDepthExpansion["A Simple Way to Estimate Bid-Ask Spreads from Daily High and Low Prices"];
  assert.match(spread.sections[4].body.en, /12 observations/);
  assert.match(spread.sections[4].body.en, /not a general gap-filling rule/);
  assert.doesNotMatch(spread.limits.en, /abstract-based overview/);
  const crossSection = researchGuideDepthExpansion["The Cross-Section of Expected Stock Returns"];
  assert.match(crossSection.sections[4].body.en, /full-sample/);
  assert.match(crossSection.sections[4].body.en, /already available/);
});

test("Nelson–Siegel distinguishes its working-paper source and maturity extrapolation", () => {
  const guide = researchGuideDepthExpansion["Parsimonious Modeling of Yield Curves"];
  const paper = papers.find(p => p.title === "Parsimonious Modeling of Yield Curves");
  assert.match(guide.evidenceUrl, /w1594\/w1594\.pdf$/);
  assert.deepEqual(paper.readerLimits, guide.limits);
  for (const locale of ["zh", "en"]) {
    assert.match(guide.limits[locale], /1985/);
    assert.match(guide.limits[locale], /1987/);
    for (const index of [1, 4]) assert.match(guide.sections[index].reference.label[locale], /1985/);
  }
  assert.match(guide.sections[1].body.en, /Conditional on a decay parameter/);
  assert.match(guide.sections[4].body.en, /not the observation date/);
  assert.doesNotMatch(guide.limits.en, /abstract-based/);
});

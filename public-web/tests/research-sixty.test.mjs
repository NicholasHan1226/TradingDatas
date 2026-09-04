import test from "node:test";
import assert from "node:assert/strict";
import { papers } from "../src/researchCatalog.js";
import { researchReaderNotes } from "../src/researchReaderNotes.js";
import { researchSixtyGuides } from "../src/researchSixtyGuides.js";
import { researchGuideMaterials } from "../src/researchGuideMaterials.js";
import { researchSummaryMaterials } from "../src/researchSummaryMaterials.js";
import { auditContent } from "../scripts/audit-research-content.mjs";

test("ten earlier source-bounded additions coexist within 180 guides without inventing works", () => {
  assert.equal(papers.length, 200);
  assert.equal(Object.keys(researchReaderNotes).length, 200);
  assert.equal(Object.keys(researchSixtyGuides).length, 10);
  for (const [title, guide] of Object.entries(researchSixtyGuides)) {
    assert.equal(papers.filter(p => p.title === title).length, 1, title);
    assert.equal(guide.sections.length, 6, title);
    assert.ok(guide.evidenceScope.length > 90);
    assert.equal(guide.reviewedAt, "2026-08-31");
    for (const s of guide.sections) {
      assert.equal(s.reference.url, guide.evidenceUrl);
      for (const lang of ["zh", "en"]) {
        assert.ok(s.title[lang] && s.reference.label[lang]);
        assert.ok(s.body[lang].length >= (lang === "zh" ? 60 : 120), `${title}: ${s.title[lang]}`);
      }
    }
  }
  assert.deepEqual(auditContent().errors, []);
  assert.equal(auditContent().review.filter(r => r.code === "summary_only").length, 0);
});

test("all 200 material selections are explicit; a topic never supplies a fallback", () => {
  assert.equal(Object.keys(researchSummaryMaterials).length, 150);
  for (const paper of papers) {
    const selected = researchReaderNotes[paper.title]?.related ?? researchGuideMaterials[paper.title] ?? researchSummaryMaterials[paper.title];
    assert.notEqual(selected, undefined, paper.title);
    assert.deepEqual(paper.related, selected);
  }
  for (const title of ["Why DeFi Lending? Evidence from Aave V2", "Flash Boys 2.0: Frontrunning in Decentralized Exchanges, Miner Extractable Value, and Consensus Instability"]) {
    assert.deepEqual(papers.find(p => p.title === title).related, {});
  }
});

test("new guides distinguish editions, units and what was actually read", () => {
  const en = title => researchSixtyGuides[title].sections.map(s => s.body.en).join(" ");
  assert.match(researchSixtyGuides["Size and Value in China"].limits.en, /appendix/i);
  assert.match(en("Regularization and Variable Selection via the Elastic Net"), /double shrinkage/);
  assert.match(en("Discretion versus Policy Rules in Practice"), /four quarters/);
  assert.match(en("The Probability of Backtest Overfitting"), /median/);
  assert.match(en("Forecasting Using Principal Components From a Large Number of Predictors"), /sign/);
  assert.match(en("Why DeFi Lending? Evidence from Aave V2"), /seven exchanges/);
  assert.match(en("Presidential Address: Discount Rates"), /terminal/);
});

import test from "node:test";
import assert from "node:assert/strict";
import { papers } from "../src/researchCatalog.js";
import { researchReaderNotes } from "../src/researchReaderNotes.js";
import { researchMicrostructure120 } from "../src/researchMicrostructure120.js";
import { researchCrypto120 } from "../src/researchCrypto120.js";
import { researchMacro120 } from "../src/researchMacro120.js";
import { researchSummaryMaterials } from "../src/researchSummaryMaterials.js";
import { auditContent } from "../scripts/audit-research-content.mjs";
import { comparisonReadings } from "../src/researchConnections.js";
import { projectResearchIndex } from "../scripts/research-public-projection.mjs";
const additions = { ...researchMicrostructure120, ...researchCrypto120, ...researchMacro120 };

test("160 bilingual guides keep the 200 identities and the honest accrual source gap", () => {
  assert.equal(papers.length, 200);
  assert.equal(Object.keys(researchReaderNotes).length, 160);
  assert.equal(Object.keys(additions).length, 20);
  assert.deepEqual([researchMicrostructure120, researchCrypto120, researchMacro120].map(x => Object.keys(x).length), [7, 7, 6]);
  assert.equal(Object.values(researchReaderNotes).filter(g => g.sections.length === 6).length, 159);
  assert.equal(auditContent().review.filter(x => x.code === "summary_only").length, 40);
  assert.deepEqual(auditContent().errors, []);
});

test("new guides have located original bilingual prose and explicit material choices", () => {
  const catalog = papers.map(projectResearchIndex);
  for (const [title, g] of Object.entries(additions)) {
    assert.equal(researchReaderNotes[title], g);
    assert.equal(papers.filter(p => p.title === title).length, 1, title);
    assert.ok(g.evidenceScope.length > 90, title);
    assert.equal(g.reviewedAt, "2026-08-31");
    assert.deepEqual(g.related, researchSummaryMaterials[title] ?? {});
    assert.equal(g.sections.length, 6);
    for (const s of g.sections) for (const locale of ["zh", "en"]) {
      assert.ok(s.body[locale].length >= (locale === "zh" ? 60 : 120), title);
      assert.equal(s.reference.url, g.evidenceUrl);
      assert.ok(s.reference.label[locale].length > 15, title);
      assert.ok(g.limits[locale].length > 30, title);
    }
    const p = catalog.find(p => p.title === title);
    assert.ok(comparisonReadings(p, catalog).length > 0, title);
  }
});

test("edition-specific definitions cannot silently become generic current claims", () => {
  const prose = title => additions[title].sections.map(s => s.body.en).join(" ");
  assert.match(prose("SRISK: A Conditional Capital Shortfall Measure of Systemic Risk"), /22.*10%/);
  assert.match(prose("The Macroeconomy and the Yield Curve: A Dynamic Latent Factor Approach"), /short minus long/);
  assert.match(prose("Blockchain Economics"), /full transferability/);
  assert.match(prose("High-Frequency Trading and Price Discovery"), /counterfactual/);
  assert.match(prose("Limit Order Book as a Market for Liquidity"), /before the next trade/);
  assert.match(prose("SoK: Decentralized Finance (DeFi)"), /keepers.*oracles/);
  assert.match(prose("The Stock Market's Reaction to Unemployment News: Why Bad News Is Usually Good for Stocks"), /expansions and contractions/);
  assert.match(additions["Taming Wildcat Stablecoins"].limits.en, /2023.*2021/);
  assert.match(additions["Optimal Execution of Portfolio Transactions"].limits.en, /1999.*2001/);
});

test("new guides retain scope cues without short, repeated or untranslated prose", () => {
  const findings = auditContent().review.filter(r => Object.hasOwn(additions, r.id));
  assert.deepEqual(findings, []);
});

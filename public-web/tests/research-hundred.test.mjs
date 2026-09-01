import test from "node:test";
import assert from "node:assert/strict";
import { papers } from "../src/researchCatalog.js";
import { researchReaderNotes } from "../src/researchReaderNotes.js";
import { comparisonReadings } from "../src/researchConnections.js";
import { projectResearchIndex } from "../scripts/research-public-projection.mjs";
import { readingJourney } from "../src/researchJourneys.js";
import { researchNinetyGuides } from "../src/researchNinetyGuides.js";
import { researchHundredGuides } from "../src/researchHundredGuides.js";
import { researchSummaryMaterials } from "../src/researchSummaryMaterials.js";

test("120 bounded bilingual guides retain 200 bibliography identities", () => {
  assert.equal(papers.length, 200);
  assert.equal(Object.keys(researchReaderNotes).length, 140);
  assert.equal(Object.values(researchReaderNotes).filter(g => g.sections.length === 6).length, 139);
  for (const [title, g] of Object.entries(researchReaderNotes)) {
    assert.equal(papers.filter(p => p.title === title).length, 1, title);
    for (const s of g.sections) for (const locale of ["zh", "en"]) {
      assert.ok(s.body[locale].length >= (locale === "zh" ? 60 : 120), `${title}: ${s.title[locale]}`);
      if (researchNinetyGuides[title] || researchHundredGuides[title]) assert.ok(s.reference?.url, title);
    }
  }
});

test("twenty additions retain source scopes, editions and deliberate preparation links", () => {
  const additions = { ...researchNinetyGuides, ...researchHundredGuides };
  assert.equal(Object.keys(researchNinetyGuides).length, 10);
  assert.equal(Object.keys(researchHundredGuides).length, 10);
  assert.equal(Object.keys(additions).length, 20);
  for (const [title, g] of Object.entries(additions)) {
    assert.equal(researchReaderNotes[title], g);
    assert.ok(g.evidenceScope.length > 90, title);
    assert.equal(g.reviewedAt, "2026-08-31");
    assert.deepEqual(g.related, researchSummaryMaterials[title] ?? {});
    for (const locale of ["zh", "en"]) {
      assert.ok(g.limits[locale].length > 30, title);
      for (const s of g.sections) {
        assert.equal(s.reference.url, g.evidenceUrl);
        assert.ok(s.reference.label[locale]);
      }
    }
  }
  const prose = title => additions[title].sections.map(s => s.body.en).join(" ");
  assert.match(prose("Betting Against Beta"), /conflicts with the model/);
  assert.match(prose("The Sum of All FEARS Investor Sentiment and Asset Prices"), /does not automatically.*fully real-time/);
  assert.match(additions["CSI 300 Index Methodology"].limits.en, /without claiming it is current/);
  assert.match(additions["Does Financial Liberalization Spur Growth?"].evidenceScope, /no revision date/);
  assert.match(additions["Annual Report Readability, Current Earnings, and Earnings Persistence"].sections[0].reference.label.en, /September 15, 2006/);
});

test("every guide offers an authored metadata-only comparison", () => {
  const catalog = papers.map(projectResearchIndex);
  for (const title of Object.keys(researchReaderNotes)) {
    const p = catalog.find(p => p.title === title);
    const excluded = readingJourney(p, catalog)?.links.map(l => l.paper.id) || [];
    const links = comparisonReadings(p, catalog, excluded);
    assert.ok(links.length >= 1 && links.length <= 3, title);
    assert.ok(links.every(r => !excluded.includes(r.paper.id)), title);
    assert.ok(links.every(r => r.paper.id !== p.id && !r.paper.readingNotes));
  }
});

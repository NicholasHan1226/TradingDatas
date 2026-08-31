import test from "node:test";
import assert from "node:assert/strict";
import { papers, researchTitle } from "../src/researchCatalog.js";
import { researchReaderNotes } from "../src/researchReaderNotes.js";
import { researchJourneys, readingJourney } from "../src/researchJourneys.js";

const additions = ["Illiquidity and Stock Returns: Cross-Section and Time-Series Effects", "The Other Side of Value: The Gross Profitability Premium"];
test("two primary-source guides deepen existing identities without changing the eight core sequences", () => {
  assert.equal(papers.length, 200);
  assert.equal(Object.keys(researchReaderNotes).length, 60);
  assert.equal(new Set(Object.values(researchJourneys).flat().map(s => s.title)).size, 24);
  for (const title of additions) {
    const paper = papers.find(p => p.title === title), guide = researchReaderNotes[title];
    assert.ok(paper && guide, title);
    assert.equal(guide.sections.length, 6);
    assert.deepEqual(paper.readingNotes, guide.sections);
    assert.deepEqual(paper.readerLimits, guide.limits);
    assert.equal(readingJourney(paper, papers), null);
    for (const section of guide.sections) {
      assert.equal(section.reference.url, guide.evidenceUrl);
      assert.match(section.reference.label.en, /pp?\./);
      for (const locale of ["zh", "en"]) assert.ok(section.body[locale].length > (locale === "zh" ? 60 : 130));
      assert.doesNotMatch(section.body.en, /[\u3400-\u9fff]/);
    }
  }
});
test("guide caveats preserve units, information timing and edition identity", () => {
  const liquidity = researchReaderNotes[additions[0]];
  const profitability = researchReaderNotes[additions[1]];
  assert.ok(liquidity && profitability);
  assert.match(liquidity.sections.map(s => s.body.en).join(" "), /mean of daily ratios/);
  assert.match(liquidity.sections.map(s => s.body.en).join(" "), /zero/);
  assert.match(profitability.limits.en, /June 2012/);
  assert.match(profitability.limits.en, /2013/);
  assert.match(profitability.sections.map(s => s.body.en).join(" "), /not gross margin/);
  assert.match(profitability.sections.map(s => s.body.en).join(" "), /publication/);
  assert.equal(researchTitle(papers.find(p => p.title === additions[1]), "zh"), "价值的另一面：毛利能力溢价");
});

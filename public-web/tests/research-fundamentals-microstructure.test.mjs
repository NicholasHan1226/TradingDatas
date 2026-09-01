import test from "node:test";
import assert from "node:assert/strict";
import { researchFundamentalsMicrostructureGuides as batch } from "../src/researchFundamentalsMicrostructureGuides.js";
import { researchReaderNotes } from "../src/researchReaderNotes.js";
import { papers } from "../src/researchCatalog.js";
import { researchJourneys, readingJourney } from "../src/researchJourneys.js";
import { auditContent } from "../scripts/audit-research-content.mjs";

test("six located fundamentals guides coexist with forty guides without altering core journeys", () => {
  assert.equal(Object.keys(batch).length, 6);
  assert.equal(papers.length, 200);
  assert.equal(Object.keys(researchReaderNotes).length, 160);
  assert.equal(new Set(Object.values(researchJourneys).flat().map(s => s.title)).size, 24);
  const paragraphs = new Set();
  for (const [title, guide] of Object.entries(batch)) {
    const paper = papers.find(p => p.title === title);
    assert.ok(paper, title);
    assert.equal(readingJourney(paper, papers), null);
    assert.equal(guide.sections.length, 6);
    assert.deepEqual(paper.readingNotes, guide.sections);
    assert.deepEqual(paper.readerLimits, guide.limits);
    assert.match(guide.evidenceUrl, /^https:\/\//);
    assert.ok(guide.evidenceScope.length > 100);
    for (const section of guide.sections) {
      assert.equal(section.reference.url, guide.evidenceUrl);
      assert.match(section.reference.label.en, /pp?\./);
      for (const locale of ["zh", "en"]) {
        assert.ok(section.body[locale].length >= (locale === "zh" ? 60 : 130));
        assert.ok(section.title[locale] && section.reference.label[locale]);
        assert.ok(!paragraphs.has(section.body[locale]));
        paragraphs.add(section.body[locale]);
      }
      assert.doesNotMatch(section.body.en, /[\u3400-\u9fff]/);
    }
  }
  const audit = auditContent({today: "2026-09-01"});
  assert.deepEqual(audit.errors, []);
  assert.equal(audit.review.filter(r => r.code === "summary_only").length, 40);
});

test("edition, measurement direction and timing caveats survive public projection", () => {
  const all = title => batch[title].sections.map(s => s.body.en).join(" ");
  assert.match(all("Value Investing: The Use of Historical Financial Statement Information to Separate Winners from Losers"), /fifth month/);
  assert.match(all("Corporate Governance and Equity Prices"), /higher.*weaker/);
  assert.match(batch["Corporate Governance and Equity Prices"].limits.en, /2001.*2003/);
  assert.match(batch["In Search of Distress Risk"].limits.en, /2005.*2008/);
  assert.match(all("In Search of Distress Risk"), /bankruptcy.*broader failure/);
  assert.match(all("A Simple Implicit Measure of the Effective Bid-Ask Spread in an Efficient Market"), /covariance.*correlation/);
  assert.match(all("Measuring the Information Content of Stock Trades"), /transaction time/);
  assert.match(batch["The Price Impact of Order Book Events"].evidenceUrl, /1011\.6402v3$/);
  assert.match(batch["The Price Impact of Order Book Events"].limits.en, /2011.*2014/);
  assert.match(all("The Price Impact of Order Book Events"), /contemporaneous.*forecast/);
});

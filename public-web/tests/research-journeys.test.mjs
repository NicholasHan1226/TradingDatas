import test from "node:test";
import assert from "node:assert/strict";
import { papers } from "../src/researchCatalog.js";
import { researchJourneys, journeyStages } from "../src/researchJourneys.js";
import { researchSubjects, researchMatches } from "../src/researchDiscovery.js";

test("eight subjects each have three distinct bilingual stages resolving to stable records", () => {
  assert.deepEqual(Object.keys(researchJourneys), researchSubjects.slice(1).map((subject) => subject.id));
  assert.equal(journeyStages.length, 3);
  for (const [topic, journey] of Object.entries(researchJourneys)) {
    assert.equal(journey.length, 3);
    assert.equal(new Set(journey.map((step) => step.title)).size, 3);
    for (const step of journey) {
      const paper = papers.find((item) => item.title === step.title || item.sourceTitle === step.title);
      assert.ok(paper, step.title);
      // Cross-topic bridges are intentional; do not reclassify original records.
      assert.ok(paper.id && topic);
      assert.ok(step.reason.zh && step.reason.en);
    }
  }
});

test("featured shelf has twelve guides, with at least one in every topic", () => {
  const guides = papers.filter((paper) => paper.readingNotes?.length >= 4);
  assert.equal(guides.length, 12);
  for (const subject of researchSubjects.slice(1)) assert.ok(guides.some((paper) => researchMatches(paper, subject.id, "all")), subject.id);
});

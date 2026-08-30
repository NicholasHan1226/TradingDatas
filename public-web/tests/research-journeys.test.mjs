import test from "node:test";
import assert from "node:assert/strict";
import { papers } from "../src/researchCatalog.js";
import { researchJourneys, journeyStages, readingJourney } from "../src/researchJourneys.js";
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

test("all core journey continuations have specific bilingual connections and reciprocal neighbors", () => {
  const guides = papers.filter((paper) => paper.readingNotes?.length >= 4);
  const titles = Object.values(researchJourneys).flat().map((step) => step.title);
  assert.equal(new Set(titles).size, 24);
  for (const paper of guides.filter(paper => titles.includes(paper.title))) {
    const journey = readingJourney(paper, papers);
    assert.ok(journey, paper.title);
    assert.equal(journey.links.length, journey.index === 1 ? 2 : 1);
    for (const link of journey.links) {
      assert.ok(link.reason.zh.length > 20 && link.reason.en.length > 40);
      assert.ok(link.paper.id !== paper.id);
      assert.ok(readingJourney(link.paper, papers).links.some((back) => back.paper.id === paper.id));
    }
  }
  assert.equal(readingJourney({ title: "unknown" }, papers), null);
});

test("featured shelf has twenty-six guides and covers every core journey stage", () => {
  const guides = papers.filter((paper) => paper.readingNotes?.length >= 4);
  assert.equal(guides.length, 26);
  for (const steps of Object.values(researchJourneys)) for (const step of steps) {
    assert.ok(guides.some((paper) => paper.title === step.title), step.title);
  }
  for (const subject of researchSubjects.slice(1)) assert.ok(guides.some((paper) => researchMatches(paper, subject.id, "all")), subject.id);
});

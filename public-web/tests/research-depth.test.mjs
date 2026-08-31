import test from "node:test";
import assert from "node:assert/strict";
import { researchDeepReads } from "../src/researchDeepReads.js";
import { researchReaderNotes } from "../src/researchReaderNotes.js";
import { papers } from "../src/researchCatalog.js";
import { researchSubjects, researchMatches } from "../src/researchDiscovery.js";
import { auditBarGrid, preserveDocumentVersions, alignSpotAndOpenInterest, tutorialExamples } from "../src/tutorialExamples.js";

test("eight original deep reads retain every subject within the expanded guide library", () => {
  assert.equal(Object.keys(researchDeepReads).length, 8);
  assert.equal(Object.keys(researchReaderNotes).length, 50);
  assert.equal(papers.length, 200);
  const deep = Object.entries(researchDeepReads).map(([title, guide]) => {
    const paper = papers.find(item => item.title === title);
    assert.deepEqual(paper.readingNotes, guide.sections);
    assert.equal(guide.sections.length, 6);
    assert.ok(guide.sections.filter(s => s.reference).length >= 2);
    for (const section of guide.sections) for (const locale of ["zh", "en"]) {
      assert.ok(section.body[locale].length > (locale === "zh" ? 80 : 160));
      if (section.reference) assert.ok(section.reference.label[locale] && section.reference.url === guide.evidenceUrl);
    }
    assert.ok(guide.evidenceScope.length > 50);
    return paper;
  });
  for (const subject of researchSubjects.slice(1)) assert.ok(deep.some(paper => researchMatches(paper, subject.id, "all")), subject.id);
});

test("new examples retain raw inputs and visibly distinguish missing, revised and stale observations", () => {
  for (const id of ["minute-bar-gaps", "document-version-ledger", "crypto-observation-alignment"]) {
    const example = tutorialExamples[id], before = structuredClone(example.args);
    example.execute(...example.args);
    assert.deepEqual(example.args, before);
  }
  assert.deepEqual(auditBarGrid(...tutorialExamples["minute-bar-gaps"].args).map(row => row.close), [100, null, 102]);
  assert.deepEqual(preserveDocumentVersions(...tutorialExamples["document-version-ledger"].args).map(row => row.status), ["first_observation", "changed_content", "unchanged_content"]);
  assert.deepEqual(alignSpotAndOpenInterest(...tutorialExamples["crypto-observation-alignment"].args).map(row => row.openInterest), [null, 12, null]);
});

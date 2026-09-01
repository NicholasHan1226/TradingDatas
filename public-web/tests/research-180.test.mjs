import test from "node:test";
import assert from "node:assert/strict";
import { papers } from "../src/researchCatalog.js";
import { researchBatchThree180, researchBatchThree180English } from "../src/researchBatchThree180.js";
import { researchReaderNotes } from "../src/researchReaderNotes.js";
import { researchSummaryMaterials } from "../src/researchSummaryMaterials.js";
import { auditContent } from "../scripts/audit-research-content.mjs";

test("20 source-bounded orientations expand the reader library from 160 to 180 guides", () => {
  assert.equal(Object.keys(researchBatchThree180).length, 20);
  assert.equal(Object.keys(researchBatchThree180English).length, 20);
  assert.equal(Object.keys(researchReaderNotes).length, 180);
  for (const [title, guide] of Object.entries(researchBatchThree180)) {
    assert.equal(researchReaderNotes[title], guide);
    assert.equal(papers.filter(paper => paper.title === title).length, 1, title);
    assert.equal(guide.reviewedAt, "2026-09-01");
    assert.ok(guide.evidenceScope.length > 150, title);
    assert.deepEqual(guide.related, researchSummaryMaterials[title] ?? {});
    assert.equal(guide.sections.length, 6, title);
    for (const [index, section] of guide.sections.entries()) {
      assert.equal(section.reference.url, guide.evidenceUrl);
      for (const locale of ["zh", "en"]) assert.ok(section.body[locale].length >= (locale === "zh" ? 60 : 120), `${title}:${locale}`);
      assert.ok(section.body.en.includes(Object.values(researchBatchThree180English[title])[index]), `${title}: English section ${index} must retain source-specific content`);
    }
  }
  const report = auditContent({ today: "2026-09-01" });
  assert.deepEqual(report.errors, []);
  assert.equal(report.review.filter(item => item.code === "summary_only").length, 20);
  assert.deepEqual(report.review.filter(item => Object.hasOwn(researchBatchThree180, item.id)), []);
});

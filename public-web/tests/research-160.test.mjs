import test from "node:test";
import assert from "node:assert/strict";
import { papers } from "../src/researchCatalog.js";
import { researchBatchTwo160, researchBatchTwo160English } from "../src/researchBatchTwo160.js";
import { researchReaderNotes } from "../src/researchReaderNotes.js";
import { researchSummaryMaterials } from "../src/researchSummaryMaterials.js";
import { auditContent } from "../scripts/audit-research-content.mjs";

test("the prior 20 primary-source orientations remain intact within 180 guides", () => {
  assert.equal(Object.keys(researchBatchTwo160).length, 20);
  assert.equal(Object.keys(researchReaderNotes).length, 200);
  for (const [title, guide] of Object.entries(researchBatchTwo160)) {
    assert.equal(researchReaderNotes[title], guide);
    assert.equal(papers.filter(paper => paper.title === title).length, 1, title);
    assert.equal(guide.reviewedAt, "2026-09-01");
    assert.ok(guide.evidenceScope.length > 150, title);
    assert.deepEqual(guide.related, researchSummaryMaterials[title] ?? {});
    assert.equal(guide.sections.length, 6, title);
    for (const [index, section] of guide.sections.entries()) {
      assert.equal(section.reference.url, guide.evidenceUrl);
      for (const locale of ["zh", "en"]) assert.ok(section.body[locale].length >= (locale === "zh" ? 60 : 120), `${title}:${locale}`);
      assert.ok(section.body.en.includes(Object.values(researchBatchTwo160English[title])[index]), `${title}: English section ${index} must retain source-specific content`);
    }
  }
  const report = auditContent({ today: "2026-09-02" });
  assert.deepEqual(report.errors, []);
  assert.equal(report.review.filter(item => item.code === "summary_only").length, 0);
  assert.deepEqual(report.review.filter(item => Object.hasOwn(researchBatchTwo160, item.id)), []);
});

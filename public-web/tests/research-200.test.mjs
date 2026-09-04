import test from "node:test";
import assert from "node:assert/strict";
import { papers } from "../src/researchCatalog.js";
import { researchBatchFour200, researchBatchFour200English } from "../src/researchBatchFour200.js";
import { researchReaderNotes } from "../src/researchReaderNotes.js";
import { researchSummaryMaterials } from "../src/researchSummaryMaterials.js";
import { auditContent } from "../scripts/audit-research-content.mjs";

test("the final twenty catalog records complete 200 source-bounded bilingual reader guides", () => {
  assert.equal(Object.keys(researchBatchFour200).length, 20);
  assert.equal(Object.keys(researchBatchFour200English).length, 20);
  assert.equal(Object.keys(researchReaderNotes).length, 200);
  for (const [title, guide] of Object.entries(researchBatchFour200)) {
    assert.equal(researchReaderNotes[title], guide);
    assert.equal(papers.filter(paper => paper.title === title).length, 1, title);
    assert.equal(guide.reviewedAt, "2026-09-02");
    assert.ok(guide.evidenceScope.length > 150, title);
    assert.deepEqual(guide.related, researchSummaryMaterials[title] ?? {});
    assert.equal(guide.sections.length, 6, title);
    for (const [index, section] of guide.sections.entries()) {
      assert.equal(section.reference.url, guide.evidenceUrl);
      for (const locale of ["zh", "en"]) assert.ok(section.body[locale].length >= (locale === "zh" ? 60 : 120), `${title}:${locale}`);
      assert.ok(section.body.en.includes(Object.values(researchBatchFour200English[title])[index]), `${title}: English section ${index} must retain source-specific content`);
    }
  }
  const report = auditContent({ today: "2026-09-02" });
  assert.deepEqual(report.errors, []);
  assert.equal(report.records, 200);
  assert.equal(report.guides, 200);
  assert.equal(report.review.filter(item => item.code === "summary_only").length, 0);
  assert.deepEqual(report.review.filter(item => Object.hasOwn(researchBatchFour200, item.id)), []);
});

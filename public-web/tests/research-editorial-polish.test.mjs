import test from "node:test";
import assert from "node:assert/strict";
import { researchReaderNotes } from "../src/researchReaderNotes.js";
import { papers } from "../src/researchCatalog.js";
import { auditContent } from "../scripts/audit-research-content.mjs";

test("disclosure guide distinguishes document pairing, parsing and similarity definitions", () => {
  const guide = researchReaderNotes["Lazy Prices"];
  const text = guide.sections.map(s => s.body.en).join(" ");
  assert.equal(guide.sections.length, 6);
  for (const term of [/same quarter.*prior year/, /numeric.*15%/, /cosine/i, /Jaccard/, /edit distance/, /simple similarity/i]) assert.match(text, term);
  assert.match(guide.evidenceScope, /11–14/);
  assert.match(guide.limits.en, /March 2019/);
});

test("governance guide preserves coding exceptions and firm-level legal applicability", () => {
  const guide = researchReaderNotes["Corporate Governance and Equity Prices"];
  const text = guide.sections.map(s => s.body.en).join(" ");
  assert.match(text, /secret ballots.*cumulative voting.*absent/i);
  assert.match(text, /opt.out/);
  assert.match(text, /binary/i);
  assert.match(guide.evidenceScope, /9–14/);
  assert.match(guide.limits.en, /2001.*2003/);
});

test("accrual orientation stays bounded to the accessible abstract and names firm-specific estimation", () => {
  const guide = researchReaderNotes["The Quality of Accruals and Earnings: The Role of Accrual Estimation Errors"];
  assert.equal(guide.sections.length, 4);
  assert.match(guide.sections[1].body.en, /firm-specific/);
  assert.match(guide.sections[1].body.zh, /公司/);
  for (const section of guide.sections.slice(0, 3)) {
    assert.match(section.reference.label.en, /2001.*abstract/);
    assert.equal(section.reference.url, guide.evidenceUrl);
  }
  assert.equal(papers.length, 200);
  assert.equal(Object.keys(researchReaderNotes).length, 100);
});

test("internal-note guard covers visible headings, summaries and limits, not just paragraphs", () => {
  const guides = structuredClone(researchReaderNotes), records = structuredClone(papers);
  const guide = guides["Lazy Prices"];
  guide.sections[0].title.zh = "来源核验";
  guide.limits.en = "TODO: check source";
  records[0].summary.zh = "出版信息已核对";
  const errors = auditContent({ guides, records }).errors.filter(e => e.code === "internal_note_in_prose");
  assert.equal(errors.length, 3);
  assert.deepEqual(new Set(errors.map(e => e.field)), new Set(["sections.0.title.zh", "limits.en", "summary.zh"]));
  assert.deepEqual(auditContent().errors, []);
});

import test from "node:test";
import assert from "node:assert/strict";
import { researchMethodsMarketsGuides as batch } from "../src/researchMethodsMarketsGuides.js";
import { researchReaderNotes } from "../src/researchReaderNotes.js";
import { papers } from "../src/researchCatalog.js";
import { researchJourneys } from "../src/researchJourneys.js";
import { auditContent, sourceUrls } from "../scripts/audit-research-content.mjs";

test("eight source-located guides remain within 80 without inflating the bibliography", () => {
  assert.equal(Object.keys(batch).length, 9); // Eight new guides plus a deeper existing China guide.
  assert.equal(Object.keys(researchReaderNotes).length, 80);
  assert.equal(papers.length, 200);
  assert.equal(new Set(Object.values(researchJourneys).flat().map(s => s.title)).size, 24);
  const paragraphs = new Set();
  for (const [title, guide] of Object.entries(batch)) {
    const paper = papers.find(p => p.title === title);
    assert.ok(paper, title);
    assert.deepEqual(paper.readingNotes, guide.sections);
    assert.deepEqual(paper.readerLimits, guide.limits);
    assert.equal(guide.sections.length, 6);
    assert.ok(guide.evidenceScope.length > 100);
    for (const section of guide.sections) {
      assert.equal(section.reference.url, guide.evidenceUrl);
      assert.match(section.reference.label.en, /pp?\./);
      for (const locale of ["zh", "en"]) {
        assert.ok(section.body[locale].length >= (locale === "zh" ? 60 : 130), `${title}: ${section.title[locale]}`);
        assert.ok(!paragraphs.has(section.body[locale]));
        paragraphs.add(section.body[locale]);
      }
      assert.doesNotMatch(section.body.en, /[\u3400-\u9fff]/);
    }
  }
  const audit = auditContent({today: "2026-08-31"});
  assert.deepEqual(audit.errors, []);
  assert.equal(audit.review.filter(r => r.code === "summary_only").length, 120);
});

test("measurement, draft editions and source migration stay explicit", () => {
  const body = title => batch[title].sections.map(s => s.body.en).join(" ");
  assert.match(body("A Five-Factor Asset Pricing Model"), /book equity/);
  assert.match(body("Investor Sentiment and the Cross-Section of Stock Returns"), /current and lagged/);
  assert.match(batch["Risks and Returns of Cryptocurrency"].limits.en, /2018.*2021/);
  assert.match(body("The Real Value of China's Stock Market"), /total shares.*nontradable/);
  assert.match(body("Measuring Economic Policy Uncertainty"), /100.*probability/);
  assert.match(body("A Simple, Positive Semi-Definite, Heteroskedasticity and Autocorrelation Consistent Covariance Matrix"), /positive semidefinite.*invertib/);
  assert.match(body("Bootstrap Methods: Another Look at the Jackknife"), /with replacement/);
  assert.match(body("Regression Shrinkage and Selection via the Lasso"), /smaller.*bound.*more shrinkage/);
  assert.ok(!sourceUrls().includes("https://www.bis.org/publ/work1183.htm"));
  assert.ok(sourceUrls().includes("https://www.bis.org/publications/working-paper-1183-why-defi-lending-evidence-aave-v2"));
});

test("the 1993 factor guide explains sorting rather than repeating its intercept discussion", () => {
  const guide = researchReaderNotes["Common risk factors in the returns on stocks and bonds"];
  assert.match(guide.sections[4].body.en, /NYSE.*30th and 70th/);
  assert.match(guide.sections[4].body.zh, /30%和70%/);
  assert.match(guide.sections[4].reference.label.en, /2.1.2/);
});

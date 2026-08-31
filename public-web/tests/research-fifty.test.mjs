import test from "node:test";
import assert from "node:assert/strict";
import { papers } from "../src/researchCatalog.js";
import { researchReaderNotes } from "../src/researchReaderNotes.js";
import { researchGuideMaterials } from "../src/researchGuideMaterials.js";
import { auditContent } from "../scripts/audit-research-content.mjs";

const titles = ["CoVaR", "Liquidity and Leverage", "Text as Data", "Measuring Geopolitical Risk", "Random Forests", "The Chinese Warrants Bubble", "DeFi Risks and the Decentralisation Illusion"];

test("all 50 guides have deliberate material selections, including intentional empty sets", () => {
  assert.equal(Object.keys(researchGuideMaterials).length, 43);
  for (const title of Object.keys(researchGuideMaterials)) assert.ok(researchReaderNotes[title], title);
  for (const [title, guide] of Object.entries(researchReaderNotes)) {
    const chosen = guide.related ?? researchGuideMaterials[title];
    assert.notEqual(chosen, undefined, title);
    assert.deepEqual(papers.find(p => p.title === title).related, chosen);
  }
  const related = title => papers.find(p => p.title === title).related;
  assert.deepEqual(related("A Simple Way to Estimate Bid-Ask Spreads from Daily High and Low Prices"), { datasets: ["cn-equity-daily"] });
  assert.deepEqual(related("The Price Impact of Order Book Events"), {});
  assert.deepEqual(related("Tokenomics: Dynamic Adoption and Valuation"), {});
  assert.deepEqual(related("Lazy Prices"), { recipes: ["document-version-ledger"] });
});

test("seven existing identities gain bilingual guides without expanding the bibliography", () => {
  assert.equal(papers.length, 200);
  assert.equal(Object.keys(researchReaderNotes).length, 50);
  for (const title of titles) {
    const guide = researchReaderNotes[title];
    assert.equal(guide.sections.length, 6, title);
    assert.equal(guide.reviewedAt, "2026-08-31");
    assert.ok(guide.evidenceScope.length > 90);
    assert.deepEqual(papers.find(p => p.title === title).readingNotes, guide.sections);
    for (const section of guide.sections) {
      assert.equal(section.reference.url, guide.evidenceUrl);
      for (const locale of ["zh", "en"]) {
        assert.ok(section.title[locale] && section.reference.label[locale]);
        assert.ok(section.body[locale].length >= (locale === "zh" ? 60 : 120), title);
      }
    }
  }
  assert.deepEqual(auditContent().errors, []);
  assert.equal(auditContent().review.filter(r => r.code === "summary_only").length, 150);
});

test("new guides keep measurement distinctions and historical edition limits", () => {
  const prose = title => researchReaderNotes[title].sections.map(s => s.body.en).join(" ");
  assert.match(prose("CoVaR"), /median/);
  assert.match(prose("CoVaR"), /causal/);
  assert.match(prose("Liquidity and Leverage"), /assets.*equity/);
  assert.match(prose("Text as Data"), /document.*unit/);
  assert.match(prose("Measuring Geopolitical Risk"), /denominator/);
  assert.match(prose("Random Forests"), /out-of-bag/i);
  assert.match(prose("Random Forests"), /chronological/);
  assert.match(prose("The Chinese Warrants Bubble"), /T\+0/);
  assert.match(prose("DeFi Risks and the Decentralisation Illusion"), /collateral/);
});

test("guide-specific materials do not inherit unrelated category-level products", () => {
  const related = title => papers.find(p => p.title === title).related;
  assert.deepEqual(related("DeFi Risks and the Decentralisation Illusion"), {});
  assert.deepEqual(related("The Chinese Warrants Bubble"), {});
  assert.deepEqual(related("Random Forests"), {});
  assert.deepEqual(related("Text as Data"), { recipes: ["document-version-ledger"] });
  assert.deepEqual(related("Measuring Geopolitical Risk"), { recipes: ["document-version-ledger"] });
  assert.deepEqual(related("CoVaR"), { recipes: ["adjusted-price-series"] });
  assert.deepEqual(related("Liquidity and Leverage"), { recipes: ["pit-fundamentals-panel"] });
});

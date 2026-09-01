import assert from "node:assert/strict";
import test from "node:test";
import { papers } from "../src/researchCatalog.js";
import { researchBibTeX, researchRis } from "../src/researchCitationFormats.js";

test("BibTeX and RIS exports preserve the original research identity and primary source", () => {
  const paper = papers.find((item) => item.id === "price-momentum-and-trading-volume");
  const bib = researchBibTeX(paper), ris = researchRis(paper);
  assert.match(bib, /^@article\{/);
  assert.ok(bib.includes(paper.sourceTitle));
  assert.ok(bib.includes(paper.sources[0].url));
  assert.match(ris, /^TY  - JOUR/m);
  assert.ok(ris.includes(`TI  - ${paper.sourceTitle}`));
  assert.ok(ris.includes(`UR  - ${paper.sources[0].url}`));
  assert.match(ris, /ER  -/);
});

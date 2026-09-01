import assert from "node:assert/strict";
import test from "node:test";
import { readFile } from "node:fs/promises";
import { researchViewReducer, initialResearchView, researchCitation } from "../src/researchReader.js";
import { papers } from "../src/researchCatalog.js";

test("full library and question entries reset incompatible filters and page", () => {
  const filtered = { ...initialResearchView, kind: "book", topic: "macro-finance", page: 4 };
  assert.deepEqual(researchViewReducer(filtered, { type: "open", topic: "all" }), { ...initialResearchView, open: true });
  assert.deepEqual(researchViewReducer(filtered, { type: "open", topic: "corporate-fundamentals" }), { ...initialResearchView, open: true, topic: "corporate-fundamentals" });
});

test("filters reset pagination but closing and reopening the view do not lose it", () => {
  let state = researchViewReducer({ ...initialResearchView, open: true }, { type: "page", value: 3 });
  state = researchViewReducer(state, { type: "visibility", value: false });
  state = researchViewReducer(state, { type: "visibility", value: true });
  assert.equal(state.page, 3);
  assert.equal(researchViewReducer(state, { type: "kind", value: "book" }).page, 0);
  assert.equal(researchViewReducer(state, { type: "topic", value: "asset-pricing" }).page, 0);
});

test("citations preserve original identity and source across display languages", () => {
  const paper = papers.at(-1);
  const citation = researchCitation(paper);
  assert.ok(citation.includes(paper.sourceTitle));
  assert.ok(citation.includes(paper.authors));
  assert.ok(citation.includes(paper.sources[0].url));
  assert.ok(!citation.includes("undefined"));
});

test("public reader excludes internal QA/status panels and generic process checklists", async () => {
  const source = await readFile(new URL("../src/ResearchRecord.jsx", import.meta.url), "utf8");
  assert.doesNotMatch(source, /paper\.(evidence|verifiedAt|readiness|checks)/);
  assert.doesNotMatch(source, /准备状态|来源核验|出版信息已核对|Three checks|RESEARCH READINESS/);
  assert.match(source, /Read original/);
  assert.match(source, /aria-pressed/);
  assert.match(source, /role="status"/);
});

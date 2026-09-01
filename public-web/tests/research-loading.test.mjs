import test from "node:test";
import assert from "node:assert/strict";
import { readdir } from "node:fs/promises";
import { createResearchGuideLoader, observeResearchGuide, restoreGuideFragment } from "../src/researchGuideLoading.js";
import { papers } from "../src/researchCatalog.js";
import { projectResearchIndex, publicResearchModule, publicGuideModule, publicResearchLoaderModule, inspectResearchChunks } from "../scripts/research-public-projection.mjs";

test("discovery projection preserves both languages and guide counts without article bodies", async () => {
  const index = await import(`data:text/javascript;base64,${Buffer.from(publicResearchModule()).toString("base64")}`);
  assert.equal(index.papers.length, 200);
  for (const paper of papers) {
    const row = index.papers.find(p => p.id === paper.id);
    assert.deepEqual(row, projectResearchIndex(paper));
    assert.equal(row.guideSectionCount, paper.readingNotes?.length ?? 0);
    assert.equal(row.readingNotes, undefined);
    assert.deepEqual(row.summary, paper.summary);
    if (paper.readingNotes) {
      const body = await import(`data:text/javascript;base64,${Buffer.from(publicGuideModule(paper.id)).toString("base64")}`);
      assert.deepEqual(body.default, { readingNotes: paper.readingNotes, readerLimits: paper.readerLimits });
      assert.equal(row.readerLimits, undefined);
    }
  }
  assert.match(publicResearchLoaderModule(), /import\("virtual:research-guide\//);
});

test("guide loader caches successes, rejects unknown IDs and permits retry after failure", async () => {
  let calls = 0;
  const value = { readingNotes: [], readerLimits: { zh: "范围", en: "Scope" } };
  const load = createResearchGuideLoader({ sample: async () => { calls++; if (calls === 1) throw new Error("offline"); return { default: value }; } });
  await assert.rejects(load("sample"), /offline/);
  assert.deepEqual(await load("sample"), value);
  assert.deepEqual(await load("sample"), value);
  assert.equal(calls, 2);
  await assert.rejects(load("missing"), /unknown_research_guide/);
  await assert.rejects(load("constructor"), /unknown_research_guide/);
});

test("unmounted or replaced articles ignore late success and failure", async () => {
  for (const fails of [false, true]) {
    let settle;
    const promise = new Promise((resolve, reject) => { settle = fails ? reject : resolve; });
    const states = [];
    const cancel = observeResearchGuide("a", () => promise, value => states.push(value));
    cancel(); settle(fails ? new Error("offline") : { readingNotes: [] });
    await new Promise(resolve => setImmediate(resolve));
    assert.deepEqual(states.map(s => s.status), ["loading"]);
  }
});

test("loading and retry states do not report success on a rejected request", async () => {
  const states = [];
  observeResearchGuide("a", async () => { throw new Error("offline"); }, s => states.push(s));
  await new Promise(resolve => setImmediate(resolve));
  assert.deepEqual(states.map(s => s.status), ["loading", "error"]);
});

test("late fragment restoration only targets the current article and a real section", () => {
  const events = [];
  const section = { scrollIntoView: () => events.push("scroll"), focus: () => events.push("focus") };
  const doc = { getElementById: id => id === "research-section-2" ? section : null };
  assert.equal(restoreGuideFragment("a", { pathname: "/research/a/", hash: "#research-section-2" }, doc), true);
  assert.deepEqual(events, ["scroll", "focus"]);
  for (const location of [{ pathname: "/research/b", hash: "#research-section-2" }, { pathname: "/research/a", hash: "#research-section-99" }, { pathname: "/research/a", hash: "#other" }]) assert.equal(restoreGuideFragment("a", location, doc), false);
});

test("bundle guard rejects eager bodies, merged bodies and missing guide chunks", () => {
  const chunk = (fileName, modules, imports = [], isEntry = false) => ({ type: "chunk", fileName, modules, imports, isEntry, code: "export default {};" });
  const prefix = "\0virtual:research-guide/";
  const good = { "index.js": chunk("index.js", {}, ["catalog.js"], true), "catalog.js": chunk("catalog.js", {}), "a.js": chunk("a.js", { [prefix + "a"]: {} }), "b.js": chunk("b.js", { [prefix + "b"]: {} }) };
  assert.equal(inspectResearchChunks(good, ["a", "b"]).guideChunks, 2);
  assert.throws(() => inspectResearchChunks({ ...good, "catalog.js": chunk("catalog.js", {}, ["a.js"]) }, ["a", "b"]), /non-initial/);
  assert.throws(() => inspectResearchChunks({ ...good, "a.js": chunk("a.js", { [prefix + "a"]: {}, [prefix + "b"]: {} }) }, ["a", "b"]), /individual/);
  assert.throws(() => inspectResearchChunks(good, ["a", "b", "c"]), /coverage/);
});

test("built individual body modules preserve the authored payload and discovery stays body-free", async () => {
  const assets = new URL("../dist/client/assets/", import.meta.url);
  const files = await readdir(assets);
  const catalog = await import(new URL(files.find(f => /^research-catalog-.*\.js$/.test(f)), assets));
  const index = Object.values(catalog).find(value => Array.isArray(value) && value.length === papers.length);
  assert.deepEqual(index, papers.map(projectResearchIndex));
  for (const paper of papers.filter(p => p.readingNotes?.length)) {
    const matches = files.filter(f => f.startsWith(`${paper.id}-`) && f.endsWith(".js"));
    assert.equal(matches.length, 1, paper.id);
    const payload = await import(new URL(matches[0], assets));
    assert.deepEqual(payload.default, { readingNotes: paper.readingNotes, readerLimits: paper.readerLimits });
  }
});

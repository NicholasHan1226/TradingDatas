import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { papers } from "../src/researchCatalog.js";
import { projectPaper, publicResearchModule, researchPublicProjection } from "../scripts/research-public-projection.mjs";
import { tutorialCode, tutorialExamples } from "../src/tutorialExamples.js";
import { runInNewContext } from "node:vm";
import { pageMetadata } from "../src/pageMetadata.js";
import { renderResearchPage, researchPageRoutes, escapeHtml } from "../scripts/build-research-pages.mjs";
import { copyText } from "../src/copyText.js";

test("build projection preserves every public record and omits internal verification data", async () => {
  const compiled = await import(`data:text/javascript;base64,${Buffer.from(publicResearchModule()).toString("base64")}`);
  assert.equal(compiled.papers.length, 200);
  for (const paper of papers) {
    const projected = compiled.papers.find((item) => item.id === paper.id);
    assert.deepEqual(projected, projectPaper(paper));
    for (const key of ["evidence", "verifiedAt", "readiness", "checks", "limits", "orientationMinutes"]) assert.equal(key in projected, false);
    assert.equal(compiled.researchTitle(projected, "zh"), paper.titleZh);
  }
  assert.equal(compiled.readingPaths.length, 3);
});

test("all 208 static entries have escaped bilingual titles, descriptions and canonical share URLs", () => {
  const template = readFileSync(new URL("../index.html", import.meta.url), "utf8");
  assert.equal(researchPageRoutes.length, 208);
  assert.equal(new Set(researchPageRoutes).size, 208);
  for (const route of researchPageRoutes) {
    const metadata = pageMetadata(route, "en");
    const html = renderResearchPage(template, route);
    assert.ok(html.includes(`property="og:url" content="${metadata.url}"`), route);
    assert.ok(html.includes(escapeHtml(metadata.title)), route);
    assert.equal((html.match(/rel="canonical"/g) || []).length, 1);
    assert.equal((html.match(/name="description"/g) || []).length, 1);
    assert.ok(!html.includes("undefined"), route);
  }
  assert.equal(escapeHtml('<a title="x">&'), "&lt;a title=&quot;x&quot;&gt;&amp;");
});

test("production tutorial projection keeps readable executable snippets from the same source functions", async () => {
  const source = readFileSync(new URL("../src/tutorialExamples.js", import.meta.url), "utf8");
  const output = researchPublicProjection().transform(source, "/project/src/tutorialExamples.js");
  const compiled = await import(`data:text/javascript;base64,${Buffer.from(output.code).toString("base64")}`);
  for (const [id, example] of Object.entries(tutorialExamples)) {
    const text = compiled.tutorialCode(id);
    assert.equal(text, tutorialCode(id));
    assert.ok(text.includes(`function ${example.execute.name}(`));
    let result;
    runInNewContext(text, { console: { log: (value) => { result = value; } } });
    assert.equal(JSON.stringify(result), JSON.stringify(example.execute(...example.args)));
  }
});

test("locale changes titles but not stable canonical identity; navigation clears article metadata", () => {
  const path = `research/${papers[0].id}`;
  assert.equal(pageMetadata(path, "zh").url, pageMetadata(path, "en").url);
  assert.notEqual(pageMetadata(path, "zh").title, pageMetadata(path, "en").title);
  assert.equal(pageMetadata("home").url, "https://tradingdatas.com/");
  assert.equal(pageMetadata("research").type, "website");
});

test("canonical URLs match directory-index hosting and normalize either incoming slash form", () => {
  for (const route of researchPageRoutes) {
    assert.equal(pageMetadata(route).url, `https://tradingdatas.com/${route}/`);
    assert.equal(pageMetadata(`/${route}/`).url, pageMetadata(route).url);
  }
});

test("clipboard success, denied permission and unavailable API never report false success", async () => {
  let received;
  assert.equal(await copyText("citation", { writeText: async (text) => { received = text; } }), "copied");
  assert.equal(received, "citation");
  assert.equal(await copyText("citation", { writeText: async () => { throw new Error("NotAllowedError"); } }), "failed");
  assert.equal(await copyText("citation", null), "failed");
});

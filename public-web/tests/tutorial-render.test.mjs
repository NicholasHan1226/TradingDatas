import assert from "node:assert/strict";
import { before, after, test } from "node:test";
import { fileURLToPath } from "node:url";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { createServer } from "vite";
import { preparationTutorials } from "../src/preparationTutorials.js";

let server, TutorialPage;
before(async () => {
  server = await createServer({ root: fileURLToPath(new URL("..", import.meta.url)), configFile: false, logLevel: "silent", server: { middlewareMode: true, hmr: false, watch: null }, esbuild: { jsx: "automatic" } });
  ({ default: TutorialPage } = await server.ssrLoadModule("/src/TutorialPage.jsx"));
});
after(async () => { await server?.close(); });

test("three tutorials render in both languages with safe examples, anchors, sources and no maturity panels", () => {
  for (const [id, tutorial] of Object.entries(preparationTutorials)) for (const locale of ["zh", "en"]) {
    const html = renderToStaticMarkup(createElement(TutorialPage, { id, locale, saved: false, onNavigate() {}, onToggleBookmark() {} }));
    assert.ok(html.includes(tutorial.title[locale]));
    assert.ok(html.includes(locale === "zh" ? "运行虚构示例" : "Run synthetic example"));
    assert.ok(html.includes('id="tutorial-example"') && html.includes('id="tutorial-inputs"'));
    assert.ok(html.includes('role="status"'));
    for (const file of ["inputs.json", "example.mjs", `tutorial-${locale}.ipynb`]) {
      assert.ok(html.includes(`/downloads/research/${id}/${file}`));
      assert.ok(html.includes(`download="${id}-${file}"`));
    }
    for (const source of tutorial.sources) assert.ok(html.includes(source.url));
    assert.ok(!html.includes('class="maturity-tag"'));
    assert.ok(!html.includes("/v1/query\\n"), "query shape must use actual line breaks");
  }
});

test("unknown tutorial has a navigable, localized not-found state", () => {
  for (const locale of ["zh", "en"]) {
    const html = renderToStaticMarkup(createElement(TutorialPage, { id: "unknown", locale, onNavigate() {} }));
    assert.ok(html.includes(locale === "zh" ? "教程未找到" : "Tutorial not found"));
    assert.ok(html.includes('href="/research"'));
  }
});

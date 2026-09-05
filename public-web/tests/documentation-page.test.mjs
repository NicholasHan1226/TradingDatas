import test, { before, after } from "node:test";
import assert from "node:assert/strict";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { createServer } from "vite";
import { fileURLToPath } from "node:url";
import { getDocumentation } from "../src/documentation.js";
import { pageMetadata } from "../src/pageMetadata.js";
let server, DocumentationPage;
before(async () => { server = await createServer({ root: fileURLToPath(new URL("..", import.meta.url)), configFile: false, logLevel: "silent", server: { middlewareMode: true, hmr: false, watch: null }, esbuild: { jsx: "automatic" } }); ({DocumentationPage} = await server.ssrLoadModule("/src/DocumentationPage.jsx")); });
after(async () => { await server?.close(); });
test("every public guide renders specific content, navigable anchors and a matching page title in both languages", () => {
 for (const locale of ["zh", "en"]) {
  const documentation = getDocumentation(locale);
  for (const guide of documentation.guides) {
   const html = renderToStaticMarkup(createElement(DocumentationPage,{locale,slug:guide.slug,documentation,onNavigate(){}}));
   assert.equal((html.match(/<h1/g)||[]).length,1);
   assert.match(html,/aria-current="page"/);
   for (const section of guide.sections) { assert.ok(html.includes(`id="${section.id}"`)); assert.ok(html.includes(`href="#${section.id}"`)); }
   assert.ok(pageMetadata(`docs/${guide.slug}`,locale).title.startsWith(guide.title));
   assert.doesNotMatch(html,/Guide structure|说明结构|AUTHORITY|版本化说明/);
  }
 }
});
test("hub and missing guide retain discoverable real document routes without requiring sign-in", () => {
 const documentation = getDocumentation("en");
 for (const slug of ["","missing-guide"]) {
  const html = renderToStaticMarkup(createElement(DocumentationPage,{locale:"en",slug,documentation,onNavigate(){}}));
  for(const guide of documentation.guides) assert.ok(html.includes(`href="/docs/${guide.slug}"`));
  assert.ok(html.includes('<details'));
  assert.ok(html.includes('aria-label="Docs"'));
  assert.ok(html.includes('>Docs</a>'));
  assert.ok(!html.includes('href="/login'));
  if(slug) assert.ok(html.includes('Guide not found'));
 }
});

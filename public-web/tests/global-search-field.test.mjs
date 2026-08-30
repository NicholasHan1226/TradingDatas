import assert from "node:assert/strict";
import { after, before, test } from "node:test";
import { fileURLToPath } from "node:url";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { createServer } from "vite";

let server, GlobalSearchField;
before(async () => {
  server = await createServer({ root: fileURLToPath(new URL("..", import.meta.url)), configFile: false, logLevel: "silent", server: { middlewareMode: true, hmr: false, watch: null }, esbuild: { jsx: "automatic" } });
  ({ GlobalSearchField } = await server.ssrLoadModule("/src/GlobalSearchField.jsx"));
});
after(async () => server?.close());

test("search label remains explicit and independent from the clear button in both layouts and languages", () => {
  for (const layout of ["desktop", "mobile"]) for (const zh of [true, false]) for (const value of ["", "毛利"]) {
    const id = `${layout}-global-search-input`;
    const label = zh ? "搜索数据、研究、方法或文档" : "Search data, research, methods, or docs";
    const html = renderToStaticMarkup(createElement(GlobalSearchField, { id, label, value, clearLabel: zh ? "清除搜索" : "Clear search", shortcut: "⌘K", onChange() {}, onClear() {}, expanded: true, resultsId: `${layout}-results`, activeResultId: `${layout}-result-0` }));
    assert.ok(html.includes(`for="${id}"`));
    assert.ok(html.includes(`id="${id}"`));
    assert.ok(html.includes(`>${label}</label>`));
    assert.doesNotMatch(html, /<label[^>]*>(?:(?!<\/label>)[\s\S])*<button/);
    assert.match(html, /role="combobox"/);
    assert.ok(html.includes(`aria-controls="${layout}-results"`));
    assert.ok(html.includes(`aria-activedescendant="${layout}-result-0"`));
    if (value) assert.match(html, /<button[^>]*type="button"/);
    else assert.match(html, /<kbd aria-hidden="true">/);
  }
});

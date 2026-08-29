import assert from "node:assert/strict";
import test from "node:test";

import { createSearchDocument, getSearchMatchKind, getSearchNavigationIndex, isGlobalSearchShortcut, normalizeSearchValue, rankSearchItem, searchGroups } from "../src/searchIndex.js";

const groups = [
  { key: "data", label: "Data" },
  { key: "research", label: "Research" },
  { key: "methods", label: "Methods" },
  { key: "docs", label: "Docs" },
];

const items = [
  { key: "dataset:cn-equity-daily", id: "cn-equity-daily", group: "data", type: "数据", label: "A 股日线行情", description: "Daily OHLCV market data", aliases: ["A-share daily bars", "market", "postclose_daily"] },
  { key: "dataset:cn-pit-fundamentals", id: "cn-pit-fundamentals", group: "data", type: "数据", label: "时点一致财务数据", description: "Point-in-time fundamentals", aliases: ["财务", "fundamentals"] },
  { key: "dataset:global-pizza-index", id: "global-pizza-index", group: "data", type: "数据", label: "Pizza 指数", description: "Alternative data observations", aliases: ["披萨指数", "alternative"] },
  { key: "research:paper", id: "research-paper", group: "research", type: "研究", label: "Market microstructure paper", description: "External literature", aliases: ["论文", "市场微观结构"] },
  { key: "method:pit", id: "pit-method", group: "methods", type: "研究方法", label: "构建时点一致财务面板", description: "reports and revisions", aliases: ["point-in-time", "fundamentals"] },
  { key: "doc:catalog", id: "catalog-doc", group: "docs", type: "文档", label: "Catalog 接口", description: "API documentation", aliases: ["docs"] },
].map((item) => ({ ...item, searchDocument: createSearchDocument([item.id, item.type, item.label, item.description, item.aliases]) }));

test("normalizes punctuation and spacing", () => {
  assert.equal(normalizeSearchValue(" A-share / Daily_Bars "), "a share daily bars");
});

test("recalls Chinese products from pinyin and English aliases", () => {
  assert.ok(rankSearchItem(items[0], "gupiao") >= 0);
  assert.ok(rankSearchItem(items[0], "rixian") >= 0);
  assert.ok(rankSearchItem(items.find((item) => item.id === "global-pizza-index"), "pisa") >= 0);
});

test("recalls research, methods, and docs from pinyin", () => {
  assert.equal(searchGroups(items, "lunwen", groups)[0].key, "research");
  assert.equal(searchGroups(items, "caiwu", groups)[0].items[0].id, "cn-pit-fundamentals");
  assert.equal(searchGroups(items, "wendang", groups)[0].key, "docs");
});

test("keeps catalog order when relevance scores tie", () => {
  const result = searchGroups(items, "gupiao", groups);
  assert.equal(result[0].items[0].id, "cn-equity-daily");
});

test("allows one restrained Latin typo and preserves intent grouping", () => {
  assert.equal(searchGroups(items, "gupio", groups)[0].items[0].id, "cn-equity-daily");
  assert.equal(searchGroups(items, "lunwe", groups)[0].key, "research");
  assert.equal(searchGroups(items, "wendnag", groups)[0].key, "docs");
  assert.ok(rankSearchItem(items.find((item) => item.id === "cn-pit-fundamentals"), "fundamntals") >= 0);
});

test("does not fuzz short tokens or accept multiple edits", () => {
  assert.equal(searchGroups(items, "apii", groups).length, 0);
  assert.equal(searchGroups(items, "guxxxx", groups).length, 0);
});

test("explains only non-obvious id, alias, and fuzzy matches", () => {
  assert.equal(getSearchMatchKind(items[0], "A 股日线"), null);
  assert.equal(getSearchMatchKind(items[0], "cn-equity-daily"), "id");
  assert.equal(getSearchMatchKind(items[0], "gupiao"), "alias");
  assert.equal(getSearchMatchKind(items[0], "gupio"), "fuzzy");
});

test("recognizes Mac and Windows search shortcuts without capturing plain K", () => {
  assert.equal(isGlobalSearchShortcut({ key: "k", metaKey: true, ctrlKey: false }), true);
  assert.equal(isGlobalSearchShortcut({ key: "k", code: "KeyK", metaKey: false, ctrlKey: true }), true);
  assert.equal(isGlobalSearchShortcut({ key: "k", metaKey: false, ctrlKey: false }), false);
});

test("wraps arrow navigation and supports first/last jumps", () => {
  assert.equal(getSearchNavigationIndex(-1, 6, "ArrowDown"), 0);
  assert.equal(getSearchNavigationIndex(5, 6, "ArrowDown"), 0);
  assert.equal(getSearchNavigationIndex(0, 6, "ArrowUp"), 5);
  assert.equal(getSearchNavigationIndex(3, 6, "Home"), 0);
  assert.equal(getSearchNavigationIndex(3, 6, "End"), 5);
  assert.equal(getSearchNavigationIndex(3, 0, "End"), -1);
});

test("ranks exact dataset ids ahead of descriptive matches", () => {
  const descriptive = { ...items[0], key: "dataset:secondary", id: "secondary", label: "Secondary", description: "cn-equity-daily reference", searchDocument: createSearchDocument(["secondary", "cn-equity-daily reference"]) };
  const result = searchGroups([descriptive, items[0]], "cn-equity-daily", groups);
  assert.equal(result[0].items[0].id, "cn-equity-daily");
});

test("requires every query token and limits each group", () => {
  assert.equal(searchGroups(items, "market missing", groups).length, 0);
  const repeated = Array.from({ length: 6 }, (_, index) => ({ ...items[0], key: `dataset:${index}`, id: `daily-${index}`, label: `Daily ${index}` }));
  const result = searchGroups(repeated, "daily", groups, 4)[0];
  assert.equal(result.items.length, 4);
  assert.equal(result.totalCount, 6);
});

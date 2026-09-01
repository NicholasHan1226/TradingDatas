import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const appSource = await readFile(new URL("../src/App.jsx", import.meta.url), "utf8");
const previewSource = await readFile(new URL("../src/PurchasePreview.jsx", import.meta.url), "utf8");

test("dataset detail offers only authored learning links and a product bookmark", () => {
  assert.match(appSource, /papers\.filter\(\(paper\) => paper\.related\?\.datasets\?\.includes\(item\.id\)\)/);
  assert.match(appSource, /RESEARCH \/ PREPARATION/);
  assert.match(appSource, /They are not TradingDatas conclusions/);
  assert.match(appSource, /dataset-bookmark/);
  assert.match(appSource, /disabled=\{bookmarkState !== "ready"\}/);
  assert.match(appSource, /toggleBookmark\(`dataset:\$\{selectedDataset\.id\}`\)/);
});

test("purchase preview defers available sign-in methods to the login surface", () => {
  assert.match(previewSource, /currently available verification methods/);
  assert.doesNotMatch(previewSource, /Email and phone registration are not open yet/);
  assert.match(previewSource, /Signing in creates no order and grants no data access/);
});

import test from "node:test";
import assert from "node:assert/strict";
import { createReadingPositions, isInPageNavigation, researchSectionTarget } from "../src/researchHistory.js";

test("article entry honors only valid research-section fragments", () => {
  assert.equal(researchSectionTarget("research/detecting-earnings-management", "#research-section-3"), "research-section-3");
  for (const route of ["research", "research/paths/example", "recipes/example", "account"]) assert.equal(researchSectionTarget(route, "#research-section-3"), null);
  for (const hash of ["", "#research-section-0", "#research-section--1", "#research-section-3 extra", "#other"]) assert.equal(researchSectionTarget("research/example", hash), null);
});

test("native section links and their back navigation do not reset page scrolling", () => {
  const base = "https://tradingdatas.com/recipes/adjusted-price-series/";
  assert.equal(isInPageNavigation(base, `${base}#tutorial-example`), true);
  assert.equal(isInPageNavigation(`${base}#tutorial-example`, base), true);
  assert.equal(isInPageNavigation(base, base), false);
  assert.equal(isInPageNavigation(base, `${base}?other=1#tutorial-example`), false);
  assert.equal(isInPageNavigation(base, "https://tradingdatas.com/research/"), false);
});

test("separate library visits retain their own positions through backward and forward traversal", () => {
  const history = createReadingPositions();
  history.save(0, 720);
  history.save(2, 1280);
  assert.equal(history.restore(0), 720);
  assert.equal(history.restore(2), 1280);
  history.save(0, 810);
  assert.equal(history.restore(2), 1280);
  assert.equal(history.restore(0), 810);
  assert.equal(history.restore(99), 0);
  assert.equal(createReadingPositions().restore(0), 0, "positions do not persist after reload");
});

test("invalid positions are ignored, negative values clamped", () => {
  const history = createReadingPositions();
  history.save(0, 50);
  history.save(0, NaN);
  assert.equal(history.restore(0), 50);
  history.save(1, -20);
  assert.equal(history.restore(1), 0);
});

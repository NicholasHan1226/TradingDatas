import test from "node:test";
import assert from "node:assert/strict";
import { createReadingPositions, isInPageNavigation, locationHashId } from "../src/researchHistory.js";

test("native section links and their back navigation do not reset page scrolling", () => {
  const base = "https://tradingdatas.com/recipes/adjusted-price-series/";
  assert.equal(isInPageNavigation(base, `${base}#tutorial-example`), true);
  assert.equal(isInPageNavigation(`${base}#tutorial-example`, base), true);
  assert.equal(isInPageNavigation(base, base), false);
  assert.equal(isInPageNavigation(base, `${base}?other=1#tutorial-example`), false);
  assert.equal(isInPageNavigation(base, "https://tradingdatas.com/research/"), false);
});

test("direct and encoded hashes resolve to stable section identities", () => {
  assert.equal(locationHashId("#tutorial-downloads"), "tutorial-downloads");
  assert.equal(locationHashId("#tutorial%20downloads"), "tutorial downloads");
  assert.equal(locationHashId("#"), "");
  assert.equal(locationHashId(""), "");
  assert.equal(locationHashId("#invalid%2"), "invalid%2");
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

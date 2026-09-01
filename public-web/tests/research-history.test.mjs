import test from "node:test";
import assert from "node:assert/strict";
import { createReadingPositions, isInPageNavigation, locationHashId, observeHashLocation, researchSectionTarget, restoreLocationHashTarget } from "../src/researchHistory.js";

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

test("direct and encoded hashes resolve to stable section identities", () => {
  assert.equal(locationHashId("#tutorial-downloads"), "tutorial-downloads");
  assert.equal(locationHashId("#tutorial%20downloads"), "tutorial downloads");
  assert.equal(locationHashId("#"), "");
  assert.equal(locationHashId(""), "");
  assert.equal(locationHashId("#invalid%2"), "invalid%2");
});

test("cancelled lazy hash restoration cannot scroll after later navigation", () => {
  let observerCallback;
  let disconnected = false;
  let scrollCount = 0;
  let targetAvailable = false;
  class Observer {
    constructor(callback) { observerCallback = callback; }
    observe() {}
    disconnect() { disconnected = true; }
  }
  const windowObject = {
    location: { hash: "#tutorial-downloads" },
    setTimeout: () => 1,
    clearTimeout: () => {},
  };
  const documentObject = {
    body: {},
    querySelector: () => ({}),
    getElementById: () => targetAvailable ? { scrollIntoView: () => { scrollCount += 1; } } : null,
  };

  const cancel = restoreLocationHashTarget({ windowObject, documentObject, Observer });
  cancel();
  targetAvailable = true;
  if (!disconnected) observerCallback();

  assert.equal(disconnected, true);
  assert.equal(scrollCount, 0);
});

test("native hash changes keep the location baseline current for Back", () => {
  let hashListener;
  let removedListener;
  let tracked = "https://tradingdatas.com/recipes/example/#tutorial-inputs";
  const windowObject = {
    location: { href: tracked },
    addEventListener: (type, listener) => { if (type === "hashchange") hashListener = listener; },
    removeEventListener: (type, listener) => { if (type === "hashchange") removedListener = listener; },
  };
  const stop = observeHashLocation(windowObject, (href) => { tracked = href; });
  windowObject.location.href = "https://tradingdatas.com/recipes/example/#tutorial-downloads";
  hashListener();

  assert.equal(tracked, windowObject.location.href);
  assert.equal(isInPageNavigation(tracked, "https://tradingdatas.com/recipes/example/#tutorial-inputs"), true);
  stop();
  assert.equal(removedListener, hashListener);
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

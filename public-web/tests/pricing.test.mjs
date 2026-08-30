import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { BASE_PLANS, formatCny, getBasePlanCards, getPlanPrice } from "../src/pricing.js";

test("approved base tiers have only 200/600/1000 rpm and 99/299/499 monthly prices", () => {
  assert.deepEqual(BASE_PLANS.map(({ id, requestsPerMinute, monthlyMinor }) => [id, requestsPerMinute, monthlyMinor]), [["basic", 200, 9900], ["standard", 600, 29900], ["flagship", 1000, 49900]]);
});
test("annual prices are twelve months at 10 percent off, in integer minor units", () => {
  assert.deepEqual(BASE_PLANS.map(({ id }) => getPlanPrice(id, "annual").totalMinor), [106920, 322920, 538920]);
  assert.deepEqual(BASE_PLANS.map(({ id }) => getPlanPrice(id, "annual").monthlyEquivalentMinor), [8910, 26910, 44910]);
  assert.deepEqual(BASE_PLANS.map(({ id }) => getPlanPrice(id, "annual").savingsMinor), [11880, 35880, 59880]);
  for (const { id, monthlyMinor } of BASE_PLANS) {
    assert.equal(getPlanPrice(id, "monthly").totalMinor, monthlyMinor);
    assert.equal(getPlanPrice(id, "monthly").savingsMinor, 0);
    assert.equal(getPlanPrice(id, "annual").currency, "CNY");
  }
});
test("unknown plan and period fail rather than silently choosing a price", () => {
  assert.throws(() => getPlanPrice("free", "annual"), RangeError);
  assert.throws(() => getPlanPrice("basic", "weekly"), RangeError);
});
test("both languages preserve equal scope and precise currency formatting", () => {
  for (const locale of ["zh", "en"]) {
    const cards = getBasePlanCards(locale);
    assert.equal(new Set(cards.map((card) => card.coverage)).size, 1);
    assert.equal(new Set(cards.map((card) => card.history)).size, 1);
    assert.equal(new Set(cards.map((card) => JSON.stringify(card.includes))).size, 1);
    assert.match(formatCny(106920, locale), /1,069\.20/);
    assert.match(formatCny(9900, locale), /99$/);
  }
});
test("pricing shows annual total distinctly and does not offer unimplemented checkout", async () => {
  const source = await readFile(new URL("../src/App.jsx", import.meta.url), "utf8");
  const component = source.slice(source.indexOf("function BasePlanShowcase"), source.indexOf("function ProductMark"));
  assert.match(component, /aria-pressed=\{billingPeriod === period\}/);
  assert.match(component, /price\.totalMinor/);
  assert.match(component, /price\.monthlyEquivalentMinor/);
  assert.match(component, /price\.savingsMinor/);
  assert.match(component, /支付暂未开放/);
  assert.doesNotMatch(component, /fetch\(|\/checkout/);
});

import assert from "node:assert/strict";
import test from "node:test";
import { requireCommerce, readCommerce, createSandboxOrder } from "../src/accountCommerce.js";
const offer = { id: "basic-month", version: "v1", tier: "basic", period: "monthly", currency: "CNY", amount_minor: 9900, requests_per_minute: 200, environment: "sandbox", terms_version: "sandbox-fixed-days-v1" };
const order = { id: "ord-test", offer_id: offer.id, offer_version: offer.version, tier: "basic", period: "monthly", currency: "CNY", amount_minor: 9900, payment_state: "pending", provisioning_state: "not_provisioned", created_at: "2026-09-05T00:00:00Z", environment: "sandbox" };
const sandbox = { mode: "sandbox", checkout_available: true, subscription: null, orders: [order], offers: [offer] };
test("ledger unavailable remains different from an empty configured sandbox", () => {
  assert.equal(requireCommerce({ mode: "unavailable", checkout_available: false, subscription: null, orders: [], offers: [] }).mode, "unavailable");
  assert.equal(requireCommerce({ ...sandbox, orders: [] }).mode, "sandbox");
  assert.throws(() => requireCommerce({ ...sandbox, mode: "unavailable" }), /commerce_unavailable/);
  assert.throws(() => requireCommerce({ ...sandbox, mode: "live" }), /commerce_unavailable/);
});
test("malformed amounts, production records, and invalid subscription dates fail closed", () => {
  for (const bad of [{ amount_minor: -1 }, { amount_minor: 1.5 }, { environment: "live" }, { payment_state: "paid" }]) {
    assert.throws(() => requireCommerce({ ...sandbox, orders: [{ ...order, ...bad }] }), /commerce_unavailable/);
  }
  const sub = { id: "sub-test", tier: "basic", period: "monthly", starts_at: order.created_at, expires_at: "2026-10-05T00:00:00Z", state: "active", environment: "sandbox", terms_version: "sandbox-fixed-days-v1" };
  assert.equal(requireCommerce({ ...sandbox, subscription: sub }).subscription.state, "active");
  assert.throws(() => requireCommerce({ ...sandbox, subscription: { ...sub, expires_at: "bad" } }), /commerce_unavailable/);
});
test("commerce read uses session credentials and expected identity, outages reject independently", async () => {
  const result = await readCommerce("user-A", undefined, async (url, init) => {
    assert.equal(url, "/api/account/commerce"); assert.equal(init.credentials, "same-origin");
    assert.equal(init.headers.get("X-TD-Identity"), "user-A");
    return Response.json(sandbox);
  });
  assert.equal(result.orders[0].id, order.id);
  await assert.rejects(readCommerce("user-A", undefined, async () => new Response("unavailable", { status: 503 })), /account_unavailable/);
});
test("retry sends identical idempotency key and only server offer identifiers, never price or paid state", async () => {
  const calls = [];
  const fetcher = async (url, init) => { calls.push([url, init]); return Response.json({ mode: "sandbox", order, checkout_available: true }); };
  await createSandboxOrder("user-A", offer, "retry-key-123", fetcher);
  await createSandboxOrder("user-A", offer, "retry-key-123", fetcher);
  for (const [url, init] of calls) {
    assert.equal(url, "/api/account/orders"); assert.equal(init.method, "POST");
    assert.equal(init.headers.get("X-TD-Identity"), "user-A");
    assert.equal(init.headers.get("Idempotency-Key"), "retry-key-123");
    assert.deepEqual(JSON.parse(init.body), { offer_id: offer.id, offer_version: offer.version });
  }
});
test("a different offer or production response cannot be displayed as the saved sandbox order", async () => {
  for (const payload of [{ mode: "live", order }, { mode: "sandbox", order: { ...order, offer_id: "other-offer" } }]) {
    await assert.rejects(createSandboxOrder("user-A", offer, "retry-key-123", async () => Response.json(payload)), /commerce_unavailable/);
  }
});
test("aborted old-account reads cannot become a valid result", async () => {
  const controller = new AbortController(); controller.abort();
  let called = false;
  await assert.rejects(readCommerce("old-user", controller.signal, async () => { called = true; return Response.json(sandbox); }));
  assert.equal(called, false);
});
test("a delayed read rejected after account switch cannot publish stale records", async () => {
  const controller = new AbortController();
  let finish;
  const request = readCommerce("old-user", controller.signal, () => new Promise(resolve => { finish = resolve; }));
  controller.abort(new Error("identity changed"));
  finish(Response.json(sandbox));
  await assert.rejects(request, /identity changed/);
});
test("both rendered commerce sections reset all private state on identity changes", async () => {
  const { readFile } = await import("node:fs/promises");
  const app = await readFile(new URL("../src/App.jsx", import.meta.url), "utf8");
  const instances = app.match(/<AccountCommerce[^>]+\/>/g);
  assert.equal(instances.length, 2);
  for (const instance of instances) assert.match(instance, /key=\{accountData.user_id \|\| accountData.tenant_id\}/);
});

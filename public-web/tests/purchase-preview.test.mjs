import assert from "node:assert/strict";
import test from "node:test";
import { readFile } from "node:fs/promises";
import { buildPreviewPath, readPreviewSelection, safeLoginDestination, getPreviewState } from "../src/purchasePreview.js";
import worker from "../worker/index.js";

test("all six selections have canonical shareable paths and exact totals", () => {
  for (const [plan, monthly, annual] of [["basic", 9900, 106920], ["standard", 29900, 322920], ["flagship", 49900, 538920]]) {
    for (const [period, total] of [["monthly", monthly], ["annual", annual]]) {
      const path = buildPreviewPath(plan, period);
      assert.equal(path, `/pricing/preview?plan=${plan}&period=${period}`);
      const result = readPreviewSelection(path.split("?")[1]);
      assert.equal(result.plan.id, plan);
      assert.equal(result.price.totalMinor, total);
      assert.equal(result.mode, "preview_only");
      assert.equal(result.canPay, false);
      assert.equal(result.order, null);
    }
  }
});

test("invalid, duplicated, or payment-shaped parameters never become an order", () => {
  for (const query of ["", "plan=free&period=monthly", "plan=basic", "plan=basic&period=weekly", "plan=basic&plan=flagship&period=annual", "plan=basic&period=annual&period=monthly", "plan=basic&period=monthly&paid=true", "plan=basic&period=monthly&amount=1", "plan=basic&period=monthly&tenant=other", "plan=basic&period=monthly&order_id=123"]) {
    assert.equal(readPreviewSelection(query), null, query);
  }
  assert.throws(() => buildPreviewPath("free", "monthly"), RangeError);
});

test("login return allows only a canonical preview or Account", () => {
  const target = buildPreviewPath("standard", "annual");
  assert.equal(safeLoginDestination(`?next=${encodeURIComponent(target)}`), target);
  for (const next of ["https://evil.test/", "//evil.test", "/\\evil.test", "/login", "/api/account/session", "/pricing/preview?plan=free&period=annual", target + "&paid=true", target + "#paid", "/account?tenant=other", "javascript:alert(1)"]) {
    assert.equal(safeLoginDestination(`?next=${encodeURIComponent(next)}`), "/account", next);
  }
  assert.equal(safeLoginDestination("?next=/account&next=//evil.test"), "/account");
  assert.equal(safeLoginDestination(""), "/account");
});

test("identity verification does not unlock payment or imply a paid subscription", () => {
  const selection = readPreviewSelection("plan=basic&period=monthly");
  for (const identity of ["checking", "signed_out", "unavailable", "authenticated", "unknown"]) {
    const state = getPreviewState(selection, identity);
    assert.equal(state.canPay, false);
    assert.equal(state.order, null);
    assert.equal(state.accessChanged, false);
    assert.equal(state.canSignIn, identity === "signed_out");
  }
  assert.equal(getPreviewState(null, "authenticated").status, "invalid_selection");
});

test("unimplemented commerce writes and callbacks stay fail-closed", async () => {
  for (const path of ["/api/commerce/orders", "/api/commerce/checkout", "/api/commerce/alipay/notify", "/api/account/orders"]) {
    const response = await worker.fetch(new Request(`https://example.test${path}`, { method: "POST" }), {
      ASSETS: { fetch: async () => new Response("Not found", { status: 404 }) },
    });
    assert.ok([404, 503].includes(response.status));
  }
});

test("preview has no payment network writes, stored selection, or success simulation", async () => {
  const source = await readFile(new URL("../src/PurchasePreview.jsx", import.meta.url), "utf8");
  assert.doesNotMatch(source, /fetch\(|localStorage|sessionStorage|二维码|qr_code|setPaid|payment_success/);
  assert.match(source, /disabled.*preview-payment/);
  assert.match(source, /登录后返回预览/);
});

import assert from "node:assert/strict";
import test from "node:test";
import { accountJson, startAccountSession, readAccountIdentity } from "../src/accountSession.js";

const portal = { tenant_id: "synthetic-tenant", tier: "basic" };

test("login uses only the same-origin gateway and validates its account", async () => {
  const calls = [];
  const result = await startAccountSession(" synthetic-key ", async (url, init) => {
    calls.push([url, init]);
    return Response.json({ portal });
  });
  assert.deepEqual(result, portal);
  assert.equal(calls.length, 1);
  assert.equal(calls[0][0], "/api/account/session");
  assert.equal(calls[0][1].credentials, "same-origin");
  assert.deepEqual(JSON.parse(calls[0][1].body), { access_key: "synthetic-key" });
});

test("a missing or unavailable gateway never downgrades to a direct bearer request", async () => {
  for (const status of [404, 503, 502]) {
    let count = 0;
    await assert.rejects(startAccountSession("synthetic-key", async () => {
      count += 1;
      return Response.json({ error: "unavailable" }, { status });
    }), /account_unavailable/);
    assert.equal(count, 1);
  }
});

test("successful HTTP status alone is not an authenticated account", async () => {
  for (const payload of [null, {}, { portal: {} }, { portal: { tenant_id: "", tier: "basic" } }]) {
    await assert.rejects(readAccountIdentity({}, async () => Response.json(payload)), /account_unavailable/);
  }
});

test("auth, throttling and outage failures remain distinct", async () => {
  for (const [status, error] of [[401, "signed_out"], [403, "access_denied"], [429, "rate_limited"], [503, "account_unavailable"]]) {
    await assert.rejects(accountJson("me", {}, async () => Response.json({}, { status })), new RegExp(error));
  }
  await assert.rejects(startAccountSession("synthetic-key", async () => Response.json({}, { status: 401 })), /invalid_token/);
});

test("timeouts and caller aborts do not leave an unbounded login request", async () => {
  const stalled = (_url, { signal }) => new Promise((_, reject) => {
    signal.addEventListener("abort", () => reject(signal.reason), { once: true });
  });
  await assert.rejects(accountJson("me", {}, stalled, 5), /account_timeout/);
  const controller = new AbortController();
  const pending = accountJson("me", { signal: controller.signal }, stalled);
  controller.abort();
  await assert.rejects(pending, { name: "AbortError" });
});

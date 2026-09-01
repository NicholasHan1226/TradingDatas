import assert from "node:assert/strict";
import test from "node:test";
import { accountJson, startAccountSession, startEmailSession, readAccountIdentity } from "../src/accountSession.js";

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

test("email account accepts only verified unsubscribed identity, not injected grants", async () => {
  const identity = {kind:"email",user_id:"test-user",email:"reader@example.com",email_verified:true,tenant_id:null,subscription_state:"not_subscribed",data_categories:[],session_expires_at:"2030-01-01T00:00:00Z"};
  const valid=await startEmailSession({email:identity.email,challenge_id:"test",code:"12345678"},async(url,init)=>{
    assert.equal(url,"/api/account/email/verify");assert.equal(init.credentials,"same-origin");return Response.json({identity});
  });
  assert.equal(valid.identity_kind,"email");
  for(const patch of [{email_verified:false},{tenant_id:"other-tenant"},{data_categories:["a_share"]},{subscription_state:"active"},{session_expires_at:"invalid"}]) {
    await assert.rejects(readAccountIdentity({},async()=>Response.json({identity:{...identity,...patch}})),/account_unavailable/);
  }
  await assert.rejects(startEmailSession({},async()=>Response.json({},{status:400})),/invalid_code/);
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

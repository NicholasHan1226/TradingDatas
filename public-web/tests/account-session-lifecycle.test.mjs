import assert from "node:assert/strict";
import test from "node:test";
import worker from "../worker/index.js";

// Synthetic credentials and mocked upstream only: never contacts production.
const origin = "https://site.example.test";
const env = {
  ACCOUNT_API_BASE: "https://account.example.test",
  SESSION_ENCRYPTION_KEY: "synthetic-lifecycle-test-secret-not-a-production-key",
};
const projection = { portal: { tenant_id: "fixture-tenant", tier: "basic" } };

function request(path, init = {}) {
  return new Request(`${origin}/api/account/${path}`, init);
}

async function login() {
  const response = await worker.fetch(request("session", {
    method: "POST",
    headers: { origin, "content-type": "application/json" },
    body: JSON.stringify({ access_key: "fixture-access-key" }),
  }), env);
  assert.equal(response.status, 200);
  assert.equal(response.headers.get("cache-control"), "no-store");
  const cookie = response.headers.get("set-cookie");
  assert.match(cookie, /Path=\/api\/account; Max-Age=28800; HttpOnly; Secure; SameSite=Strict/);
  assert.deepEqual(await response.json(), projection);
  return cookie.split(";", 1)[0];
}

test("session expiry is enforced at the eight-hour boundary without calling upstream", async (t) => {
  let now = 1_800_000_000_000;
  t.mock.method(Date, "now", () => now);
  const upstream = t.mock.method(globalThis, "fetch", async () => Response.json(projection));
  const cookie = await login();
  now += 8 * 60 * 60 * 1000 - 1000;
  assert.equal((await worker.fetch(request("me", { headers: { cookie } }), env)).status, 200);
  now += 1000;
  const expired = await worker.fetch(request("me", { headers: { cookie } }), env);
  assert.equal(expired.status, 401);
  assert.match(expired.headers.get("set-cookie"), /Max-Age=0/);
  assert.equal(upstream.mock.callCount(), 2);
});

test("changed ciphertext and a different encryption key cannot authenticate", async (t) => {
  const upstream = t.mock.method(globalThis, "fetch", async () => Response.json(projection));
  const cookie = await login();
  const [name, value] = cookie.split("=");
  const changed = `${name}=${value[0] === "A" ? "B" : "A"}${value.slice(1)}`;
  for (const [candidate, config] of [
    [changed, env],
    [cookie, { ...env, SESSION_ENCRYPTION_KEY: "different-fixture-key" }],
  ]) {
    const response = await worker.fetch(request("me", { headers: { cookie: candidate } }), config);
    assert.equal(response.status, 401);
  }
  assert.equal(upstream.mock.callCount(), 1);
});

test("upstream authentication failures do not issue a session or become success", async (t) => {
  let status = 401;
  t.mock.method(globalThis, "fetch", async () => Response.json({ error: "fixture_failure" }, { status }));
  for (status of [401, 403, 429, 503]) {
    const response = await worker.fetch(request("session", {
      method: "POST", headers: { origin, "content-type": "application/json" },
      body: JSON.stringify({ access_key: "fixture-invalid-key" }),
    }), env);
    assert.equal(response.status, status);
    assert.equal(response.headers.get("set-cookie"), null);
    assert.equal(response.headers.get("cache-control"), "no-store");
  }
});

test("each authenticated read rechecks upstream and preserves usage and key routes", async (t) => {
  const calls = [];
  let status = 200;
  t.mock.method(globalThis, "fetch", async (url, init) => {
    calls.push({ url: String(url), auth: new Headers(init.headers).get("authorization") });
    return Response.json(status === 200 ? projection : { error: "revoked" }, { status });
  });
  const cookie = await login();
  for (const path of ["me", "usage?days=30", "keys"]) {
    assert.equal((await worker.fetch(request(path, { headers: { cookie } }), env)).status, 200);
  }
  assert.deepEqual(calls.slice(1).map((call) => call.url), [
    "https://account.example.test/portal/api/me",
    "https://account.example.test/portal/api/me/usage?days=30",
    "https://account.example.test/portal/api/me/keys",
  ]);
  assert.ok(calls.every((call) => call.auth === "Bearer fixture-access-key"));
  status = 401;
  const revoked = await worker.fetch(request("me", { headers: { cookie } }), env);
  assert.equal(revoked.status, 401);
  assert.match(revoked.headers.get("set-cookie"), /Max-Age=0/);
});

test("logout remains available with missing gateway configuration", async () => {
  const response = await worker.fetch(request("session", { method: "DELETE", headers: { origin } }), {});
  assert.equal(response.status, 200);
  assert.match(response.headers.get("set-cookie"), /Max-Age=0/);
  assert.equal((await worker.fetch(request("session", { method: "DELETE" }), {})).status, 403);
});

test("malformed upstream 200 responses cannot create a session", async (t) => {
  let body;
  t.mock.method(globalThis, "fetch", async () => new Response(body));
  for (body of ["<html>Login</html>", "null", "{}", '{"portal":{"tenant_id":"","tier":"basic"}}', "x".repeat(512 * 1024 + 1)]) {
    const response = await worker.fetch(request("session", { method: "POST", headers: { origin }, body: JSON.stringify({ access_key: "fixture" }) }), env);
    assert.equal(response.status, 502);
    assert.equal(response.headers.get("set-cookie"), null);
  }
});

test("upstream fetch forbids redirects and provides a timeout signal", async (t) => {
  t.mock.method(globalThis, "fetch", async (_url, init) => {
    assert.equal(init.redirect, "manual");
    assert.ok(init.signal instanceof AbortSignal);
    throw new TypeError("synthetic upstream failure with sensitive details");
  });
  const response = await worker.fetch(request("session", { method: "POST", headers: { origin }, body: JSON.stringify({ access_key: "fixture" }) }), env);
  assert.equal(response.status, 502);
  assert.deepEqual(await response.json(), { error: "account_upstream_unavailable" });
  assert.equal(response.headers.get("set-cookie"), null);
});

test("upstream redirects are rejected without forwarding credentials or Location", async (t) => {
  const upstream=t.mock.method(globalThis,"fetch",async(_url,init)=>{
    assert.equal(init.redirect,"manual");
    return new Response(null,{status:302,headers:{location:"https://untrusted.example.test/"}});
  });
  const response=await worker.fetch(request("session",{method:"POST",headers:{origin},body:JSON.stringify({access_key:"fixture"})}),env);
  assert.equal(response.status,502);assert.equal(response.headers.get("location"),null);
  assert.equal(response.headers.get("set-cookie"),null);assert.equal(upstream.mock.callCount(),1);
});

test("request size is bounded without trusting Content-Length", async (t) => {
  const upstream = t.mock.method(globalThis, "fetch", async () => Response.json(projection));
  for (const body of ["null", "x".repeat(16 * 1024 + 1)]) {
    const response = await worker.fetch(request("session", { method: "POST", headers: { origin }, body }), env);
    assert.equal(response.status, 400);
  }
  assert.equal(upstream.mock.callCount(), 0);
});

test("chunked oversized requests cancel their stream before calling upstream", async (t) => {
  let cancelled = false;
  const upstream = t.mock.method(globalThis, "fetch", async () => Response.json(projection));
  const body = new ReadableStream({
    pull(controller) { controller.enqueue(new Uint8Array(9000)); },
    cancel() { cancelled = true; },
  });
  const response = await worker.fetch(request("session", { method: "POST", headers: { origin }, body, duplex: "half" }), env);
  assert.equal(response.status, 400);
  assert.equal(cancelled, true);
  assert.equal(upstream.mock.callCount(), 0);
});

test("only route-specific methods reach the account backend", async (t) => {
  const upstream = t.mock.method(globalThis, "fetch", async () => Response.json(projection));
  for (const [path, method] of [["me", "POST"], ["usage", "PATCH"], ["keys", "PATCH"], ["keys/key_0123456789abcdef", "GET"]]) {
    assert.equal((await worker.fetch(request(path, { method, headers: { origin } }), env)).status, 405);
  }
  assert.equal(upstream.mock.callCount(), 0);
});

test("key writes require same-origin and forward the body without adding authority", async (t) => {
  const calls = [];
  t.mock.method(globalThis, "fetch", async (url, init) => {
    calls.push({ url: String(url), method: init.method, body: init.body });
    return Response.json(projection);
  });
  const cookie = await login();
  for (const headers of [{ cookie }, { cookie, origin: "https://other.example.test" }]) {
    assert.equal((await worker.fetch(request("keys", { method: "POST", headers, body: "{}" }), env)).status, 403);
  }
  assert.equal(calls.length, 1);
  const body = JSON.stringify({ enabled: false });
  const response = await worker.fetch(request("keys/key_0123456789abcdef", {
    method: "PATCH", headers: { cookie, origin, "content-type": "application/json" }, body,
  }), env);
  assert.equal(response.status, 200);
  assert.deepEqual(calls.at(-1), {
    url: "https://account.example.test/portal/api/me/keys/key_0123456789abcdef", method: "PATCH", body,
  });
});

test("logout clears the scoped cookie; cookie removal is not server-side revocation", async (t) => {
  const upstream = t.mock.method(globalThis, "fetch", async () => Response.json(projection));
  const cookie = await login();
  const denied = await worker.fetch(request("session", {
    method: "DELETE", headers: { cookie, origin: "https://other.example.test" },
  }), env);
  assert.equal(denied.status, 403);
  assert.equal(denied.headers.get("set-cookie"), null);
  const logout = await worker.fetch(request("session", { method: "DELETE", headers: { origin, cookie } }), env);
  assert.deepEqual(await logout.json(), { signed_out: true });
  assert.match(logout.headers.get("set-cookie"), /^td_account_session=; Path=\/api\/account; Max-Age=0;/);
  assert.equal((await worker.fetch(request("me"), env)).status, 401);
  assert.equal(upstream.mock.callCount(), 1);
  // The documented stateless bridge cannot revoke a copied cookie individually.
  assert.equal((await worker.fetch(request("me", { headers: { cookie } }), env)).status, 200);
});

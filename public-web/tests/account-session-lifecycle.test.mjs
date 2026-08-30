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
  assert.equal((await worker.fetch(request("me", { headers: { cookie } }), env)).status, 401);
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

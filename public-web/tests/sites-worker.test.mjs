import assert from "node:assert/strict";
import { access } from "node:fs/promises";
import test from "node:test";
import worker from "../worker/index.js";

test("serves existing static assets without a fallback", async () => {
  const calls = [];
  const response = await worker.fetch(new Request("https://example.test/assets/app.js"), {
    ASSETS: {
      fetch: async (request) => {
        calls.push(new URL(request.url).pathname);
        return new Response("asset", { status: 200 });
      },
    },
  });

  assert.equal(response.status, 200);
  assert.deepEqual(calls, ["/assets/app.js"]);
});

test("public site blocks the standalone admin shell but keeps gated admin assets usable", async () => {
  const assetFetch = async (request) => {
    const path = new URL(request.url).pathname;
    if (path === "/app/index.html") {
      return new Response(null, { status: 307, headers: { location: "/app/" } });
    }
    return new Response(path === "/app/" ? "admin-shell" : "admin-asset", { status: 200 });
  };
  for (const path of ["/app", "/app/", "/app/index.html"]) {
    let calls = 0;
    const response = await worker.fetch(new Request(`https://example.test${path}`), {
      ACCOUNT_ADMIN_ENABLED: "true",
      ASSETS: { fetch: async (request) => { calls += 1; return assetFetch(request); } },
    });
    assert.equal(response.status, 404);
    assert.equal(calls, 0);
  }
  const denied = await worker.fetch(new Request("https://example.test/admin"), {
    ACCOUNT_ADMIN_ENABLED: "false", ASSETS: { fetch: assetFetch },
  });
  assert.equal(denied.status, 404);
  const allowed = await worker.fetch(new Request("https://example.test/admin"), {
    ACCOUNT_ADMIN_ENABLED: "true", ASSETS: { fetch: assetFetch },
  });
  assert.equal(allowed.status, 200);
  assert.equal(allowed.headers.get("location"), null);
  assert.equal(await allowed.text(), "admin-shell");
  const asset = await worker.fetch(new Request("https://example.test/app/assets/admin.js"), {
    ACCOUNT_ADMIN_ENABLED: "true", ASSETS: { fetch: assetFetch },
  });
  assert.equal(asset.status, 200);
  assert.equal(await asset.text(), "admin-asset");
});

test("falls back to the root app shell for extensionless GET and HEAD routes without redirecting", async () => {
  for (const request of [
    new Request("https://example.test/account/"),
    new Request("https://example.test/login/"),
    new Request("https://example.test/flow/step-two?source=share", { method: "HEAD" }),
  ]) {
    const calls = [];
    const response = await worker.fetch(request, {
      ASSETS: {
        fetch: async (request) => {
          const url = new URL(request.url);
          calls.push(url.pathname + url.search);
          return new Response(url.pathname === "/" ? "app" : "missing", {
            status: url.pathname === "/" ? 200 : 404,
          });
        },
      },
    });

    assert.equal(response.status, 200);
    assert.equal(calls.at(-1), "/");
  }
});

test("keeps API, asset, extensionful, and write-request 404s fail-closed", async () => {
  for (const request of [
    new Request("https://example.test/api/missing", { headers: { accept: "application/json" } }),
    new Request("https://example.test/assets/missing"),
    new Request("https://example.test/assets/missing.js", { headers: { accept: "text/html" } }),
    new Request("https://example.test/missing.json", { headers: { accept: "text/html" } }),
    new Request("https://example.test/flow", { method: "POST", headers: { accept: "text/html" } }),
  ]) {
    let calls = 0;
    const response = await worker.fetch(request, {
      ASSETS: {
        fetch: async () => {
          calls += 1;
          return new Response("missing", { status: 404 });
        },
      },
    });

    assert.equal(response.status, 404);
    assert.equal(calls, 1);
  }
});

test("account session gateway stays explicitly unavailable until its secret and upstream are bound", async () => {
  let assetCalls = 0;
  const response = await worker.fetch(new Request("https://example.test/api/account/me"), {
    ASSETS: { fetch: async () => { assetCalls += 1; return new Response("missing", { status: 404 }); } },
  });

  assert.equal(response.status, 503);
  assert.equal(assetCalls, 0);
  assert.deepEqual(await response.json(), { error: "identity_gateway_unavailable" });
});

test("account session exchange seals the key in an HttpOnly same-site cookie and proxies reads", async () => {
  const originalFetch = globalThis.fetch;
  const upstreamCalls = [];
  globalThis.fetch = async (request, init = {}) => {
    const url = new URL(request);
    upstreamCalls.push({ path: url.pathname + url.search, authorization: new Headers(init.headers).get("authorization") });
    return Response.json({ portal: { tenant_id: "tenant-a", tier: "basic" } });
  };
  try {
    const env = {
      ACCOUNT_API_BASE: "https://account-api.example.test",
      SESSION_ENCRYPTION_KEY: "test-only-session-secret-with-sufficient-entropy",
      ASSETS: { fetch: async () => new Response("missing", { status: 404 }) },
    };
    const login = await worker.fetch(new Request("https://example.test/api/account/session", {
      method: "POST",
      headers: { "content-type": "application/json", origin: "https://example.test" },
      body: JSON.stringify({ access_key: "customer-secret" }),
    }), env);

    assert.equal(login.status, 200);
    const cookie = login.headers.get("set-cookie");
    assert.match(cookie, /^td_account_session=[A-Za-z0-9_-]+;/u);
    assert.match(cookie, /HttpOnly/u);
    assert.match(cookie, /Secure/u);
    assert.match(cookie, /SameSite=Strict/u);
    assert.ok(!cookie.includes("customer-secret"));

    const sessionPair = cookie.split(";", 1)[0];
    const account = await worker.fetch(new Request("https://example.test/api/account/me", {
      headers: { cookie: sessionPair },
    }), env);
    assert.equal(account.status, 200);
    assert.deepEqual(await account.json(), { portal: { tenant_id: "tenant-a", tier: "basic" } });
    assert.deepEqual(upstreamCalls, [
      { path: "/portal/api/me", authorization: "Bearer customer-secret" },
      { path: "/portal/api/me", authorization: "Bearer customer-secret" },
    ]);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("account session gateway rejects cross-origin mutation and clears invalid sessions", async () => {
  const env = {
    ACCOUNT_API_BASE: "https://account-api.example.test",
    SESSION_ENCRYPTION_KEY: "test-only-session-secret-with-sufficient-entropy",
    ASSETS: { fetch: async () => new Response("missing", { status: 404 }) },
  };
  const crossOrigin = await worker.fetch(new Request("https://example.test/api/account/session", {
    method: "POST",
    headers: { "content-type": "application/json", origin: "https://attacker.test" },
    body: JSON.stringify({ access_key: "customer-secret" }),
  }), env);
  assert.equal(crossOrigin.status, 403);

  const invalid = await worker.fetch(new Request("https://example.test/api/account/me", {
    headers: { cookie: "td_account_session=invalid" },
  }), env);
  assert.equal(invalid.status, 401);
  assert.match(invalid.headers.get("set-cookie"), /Max-Age=0/u);
});

test("emits the files required by Sites packaging", async () => {
  await access(new URL("../dist/client/index.html", import.meta.url));
  await access(new URL("../dist/server/index.js", import.meta.url));
  await access(new URL("../dist/server/email-identity.js", import.meta.url));
  await access(new URL("../dist/server/email-templates.js", import.meta.url));
  await access(new URL("../dist/.openai/hosting.json", import.meta.url));
});

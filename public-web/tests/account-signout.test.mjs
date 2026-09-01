import assert from "node:assert/strict";
import test from "node:test";
import { confirmAccountSignOut } from "../src/accountSession.js";

test("confirms same-site logout only from an explicit successful response", async () => {
  const calls = [];
  await confirmAccountSignOut(async (url, init) => {
    calls.push({ url, method: init.method, identity: init.headers.get("X-TD-Identity"), credentials: init.credentials, signal: init.signal });
    return Response.json({ signed_out: true, user_id: "user-a" });
  }, 10_000, "user-a");
  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, "/api/account/session");
  assert.equal(calls[0].method, "DELETE");
  assert.equal(calls[0].identity, "user-a");
  assert.equal(calls[0].credentials, "same-origin");
  assert.ok(calls[0].signal instanceof AbortSignal);
});

test("identity-bound logout rejects a stale tab without treating it as success", async () => {
  await assert.rejects(confirmAccountSignOut(async (_url, init) => {
    assert.equal(init.headers.get("X-TD-Identity"), "user-a");
    return Response.json({ error: "identity_changed" }, { status: 409 });
  }, 10_000, "user-a"), { message: "identity_changed" });
  await assert.rejects(confirmAccountSignOut(async () => Response.json({ signed_out: true, user_id: "user-b" }), 10_000, "user-a"));
});

test("network errors, non-success codes and malformed confirmations cannot report logout", async () => {
  for (const fetchImpl of [
    async () => { throw new TypeError("offline"); },
    async () => Response.json({ signed_out: true }, { status: 503 }),
    async () => Response.json({ error: "unauthenticated" }, { status: 401 }),
    async () => new Response("<html>fallback</html>"),
    async () => Response.json({ signed_out: false }),
    async () => Response.json({ signed_out: "true" }),
    async () => Response.json(null),
  ]) await assert.rejects(confirmAccountSignOut(fetchImpl));
});

test("an interrupted logout can be retried successfully", async () => {
  let attempts = 0;
  const fetchImpl = async () => ++attempts === 1
    ? Response.json({ error: "unavailable" }, { status: 503 })
    : Response.json({ signed_out: true });
  await assert.rejects(confirmAccountSignOut(fetchImpl));
  await confirmAccountSignOut(fetchImpl);
  assert.equal(attempts, 2);
});

test("a stalled request is aborted and bounded", async () => {
  let signal;
  const fetchImpl = (_url, init) => new Promise((_resolve, reject) => {
    signal = init.signal;
    signal.addEventListener("abort", () => reject(signal.reason), { once: true });
  });
  await assert.rejects(confirmAccountSignOut(fetchImpl, 5));
  assert.equal(signal.aborted, true);
});

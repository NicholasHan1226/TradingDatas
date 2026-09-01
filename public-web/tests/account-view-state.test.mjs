import assert from "node:assert/strict";
import test from "node:test";
import { getAccountViewState } from "../src/accountSession.js";

test("pending identity verification is never presented as signed out", () => {
  for (const account of [null, { tenant_id: "synthetic", tier: "basic" }]) {
    assert.equal(getAccountViewState({ loading: true, account, error: "" }), "checking");
  }
});

test("connection failure differs from confirmed absence of a session", () => {
  assert.equal(getAccountViewState({ loading: false, account: null, error: "account_unavailable" }), "unavailable");
  assert.equal(getAccountViewState({ loading: false, account: null, error: "" }), "signed_out");
  assert.equal(getAccountViewState({ loading: false, account: null, error: "invalid_token" }), "signed_out");
  assert.equal(getAccountViewState({ loading: false, account: null, error: "signed_out" }), "signed_out");
  assert.equal(getAccountViewState({ loading: false, account: { tenant_id: "synthetic", tier: "basic" }, error: "" }), "authenticated");
});

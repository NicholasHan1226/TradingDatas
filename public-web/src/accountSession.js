// Only the same-site gateway may exchange credentials for a browser session.
// Keep transport failure distinct from authentication failure; never downgrade.
export function getAccountViewState({ loading, account, error }) {
  if (loading) return "checking";
  if (account) return "authenticated";
  if (error === "invalid_token" || error === "signed_out") return "signed_out";
  return error ? "unavailable" : "signed_out";
}

export async function accountJson(endpoint, init = {}, fetchImpl = fetch, timeoutMs = 12_000) {
  const { expectedIdentity, ...requestInit } = init;
  const headers = new Headers(init.headers);
  if (expectedIdentity) headers.set("X-TD-Identity", expectedIdentity);
  const controller = new AbortController();
  const abort = () => controller.abort(init.signal.reason);
  if (init.signal?.aborted) abort();
  else init.signal?.addEventListener("abort", abort, { once: true });
  const timeout = setTimeout(() => controller.abort(new Error("account_timeout")), timeoutMs);
  try {
    controller.signal.throwIfAborted();
    const response = await fetchImpl(`/api/account/${endpoint}`, {
      ...requestInit, headers, credentials: "same-origin", signal: controller.signal,
    });
    if (!response.ok) {
      if ([403, 409].includes(response.status)) {
        const failure = await response.json().catch(() => null);
        if (["recent_sign_in_required", "identity_changed", "library_full", "connection_exists", "invalid_access_key"].includes(failure?.error)) throw new Error(failure.error);
      }
      throw new Error(endpoint === "email/verify" && response.status === 400 ? "invalid_code" : response.status === 401 ? "signed_out" : response.status === 403 ? "access_denied" : response.status === 429 ? "rate_limited" : "account_unavailable");
    }
    if (!response.headers.get("content-type")?.includes("application/json")) throw new Error("account_unavailable");
    const payload = await response.json();
    controller.signal.throwIfAborted();
    return payload;
  } catch (error) {
    if (controller.signal.aborted) throw controller.signal.reason;
    if (["signed_out", "access_denied", "rate_limited", "account_unavailable", "invalid_code", "recent_sign_in_required", "identity_changed", "library_full", "connection_exists", "invalid_access_key"].includes(error.message)) throw error;
    throw new Error("account_unavailable");
  } finally {
    clearTimeout(timeout);
    init.signal?.removeEventListener("abort", abort);
  }
}

function requireAccount(payload) {
  const identity = payload?.identity;
  if (identity) {
    if (identity.kind !== "email" || identity.email_verified !== true || typeof identity.user_id !== "string" || !identity.user_id || typeof identity.email !== "string" || !identity.email || identity.tenant_id !== null || identity.subscription_state !== "not_subscribed" || !Array.isArray(identity.data_categories) || identity.data_categories.length !== 0 || !Number.isFinite(Date.parse(identity.session_expires_at))) throw new Error("account_unavailable");
    const access = payload.data_access;
    const portal = access?.state === "connected" ? access.portal : null;
    if (portal && (typeof portal.tenant_id !== "string" || !portal.tenant_id || typeof portal.tier !== "string" || portal.enabled !== true || !Array.isArray(portal.data_categories) || !Array.isArray(portal.scopes))) throw new Error("account_unavailable");
    if (access?.state === "connected" && !portal) throw new Error("account_unavailable");
    return { ...portal, ...identity, ...(portal ? { tenant_id: portal.tenant_id, data_categories: portal.data_categories } : {}), identity_kind: "email", capabilities: payload.capabilities || {}, data_access_state: access?.state || "none", data_connection_present: access?.present === true, admin_available: Boolean(portal && access.admin === true && payload.capabilities?.admin_console === true) };
  }
  const account = payload?.portal;
  if (!account || typeof account.tenant_id !== "string" || !account.tenant_id.trim() || typeof account.tier !== "string" || !account.tier.trim()) throw new Error("account_unavailable");
  return account;
}

export async function startEmailSession(payload, fetchImpl = fetch) {
  return requireAccount(await accountJson("email/verify", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email: payload.email, challenge_id: payload.challenge_id, code: payload.code }),
  }, fetchImpl));
}

export async function readAccountIdentity(init = {}, fetchImpl = fetch) {
  return requireAccount(await accountJson("me", init, fetchImpl));
}

export async function requestProfileDeletion(fetchImpl = fetch, expectedIdentity) {
  const payload = await accountJson("profile/deletion", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ confirmation: "DELETE" }),
    expectedIdentity,
  }, fetchImpl);
  const receipt = payload?.deletion;
  if (!expectedIdentity || receipt?.user_id !== expectedIdentity || receipt?.state !== "accepted" || !Number.isFinite(Date.parse(receipt.requested_at)) || !Number.isFinite(Date.parse(receipt.delete_by))) throw new Error("deletion_unconfirmed");
  return receipt;
}

export async function startAccountSession(accessKey, fetchImpl = fetch) {
  try {
    return requireAccount(await accountJson("session", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ access_key: accessKey.trim() }),
    }, fetchImpl));
  } catch (error) {
    if (error.message === "signed_out") throw new Error("invalid_token");
    throw error;
  }
}

// UI state must not claim logout until the same-site cookie clear is confirmed.
export async function confirmAccountSignOut(fetchImpl = fetch, timeoutMs = 10_000) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetchImpl("/api/account/session", {
      method: "DELETE",
      credentials: "same-origin",
      signal: controller.signal,
    });
    if (!response.ok) throw new Error("signout_unconfirmed");
    const payload = await response.json();
    if (payload?.signed_out !== true) throw new Error("signout_unconfirmed");
  } finally {
    clearTimeout(timeout);
  }
}

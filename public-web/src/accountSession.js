// Only the same-site gateway may exchange credentials for a browser session.
// Keep transport failure distinct from authentication failure; never downgrade.
export function getAccountViewState({ loading, account, error }) {
  if (loading) return "checking";
  if (account) return "authenticated";
  if (error === "invalid_token" || error === "signed_out") return "signed_out";
  return error ? "unavailable" : "signed_out";
}

export async function accountJson(endpoint, init = {}, fetchImpl = fetch, timeoutMs = 12_000) {
  const controller = new AbortController();
  const abort = () => controller.abort(init.signal.reason);
  if (init.signal?.aborted) abort();
  else init.signal?.addEventListener("abort", abort, { once: true });
  const timeout = setTimeout(() => controller.abort(new Error("account_timeout")), timeoutMs);
  try {
    controller.signal.throwIfAborted();
    const response = await fetchImpl(`/api/account/${endpoint}`, {
      ...init, credentials: "same-origin", signal: controller.signal,
    });
    if (!response.ok) throw new Error(response.status === 401 ? "signed_out" : response.status === 403 ? "access_denied" : response.status === 429 ? "rate_limited" : "account_unavailable");
    if (!response.headers.get("content-type")?.includes("application/json")) throw new Error("account_unavailable");
    const payload = await response.json();
    controller.signal.throwIfAborted();
    return payload;
  } catch (error) {
    if (controller.signal.aborted) throw controller.signal.reason;
    if (["signed_out", "access_denied", "rate_limited", "account_unavailable"].includes(error.message)) throw error;
    throw new Error("account_unavailable");
  } finally {
    clearTimeout(timeout);
    init.signal?.removeEventListener("abort", abort);
  }
}

function requireAccount(payload) {
  const account = payload?.portal;
  if (!account || typeof account.tenant_id !== "string" || !account.tenant_id.trim() || typeof account.tier !== "string" || !account.tier.trim()) throw new Error("account_unavailable");
  return account;
}

export async function readAccountIdentity(init = {}, fetchImpl = fetch) {
  return requireAccount(await accountJson("me", init, fetchImpl));
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

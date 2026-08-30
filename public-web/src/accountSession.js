// UI state must not claim logout until the same-site cookie clear is confirmed.
export async function confirmAccountSignOut(mode, fetchImpl = fetch, timeoutMs = 10_000) {
  if (mode === "direct") return;
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

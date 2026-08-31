import { handleEmailIdentity } from "./email-identity.js";
import { runIdentityMaintenance } from "./identity-retention.js";

const SESSION_COOKIE = "td_account_session";
const SESSION_TTL_SECONDS = 8 * 60 * 60;
const SESSION_AAD = new TextEncoder().encode("tradingdatas-account-session-v1");
const MAX_SESSION_BODY_BYTES = 16 * 1024;
const MAX_ACCOUNT_BODY_BYTES = 512 * 1024;

function jsonResponse(payload, status = 200, extraHeaders = {}) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: {
      "content-type": "application/json; charset=utf-8",
      "cache-control": "no-store",
      ...extraHeaders,
    },
  });
}

function base64UrlEncode(bytes) {
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary).replaceAll("+", "-").replaceAll("/", "_").replace(/=+$/u, "");
}

function base64UrlDecode(value) {
  const normalized = value.replaceAll("-", "+").replaceAll("_", "/");
  const padded = normalized + "=".repeat((4 - (normalized.length % 4)) % 4);
  const binary = atob(padded);
  return Uint8Array.from(binary, (character) => character.charCodeAt(0));
}

async function sessionKey(secret) {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(secret));
  return crypto.subtle.importKey("raw", digest, { name: "AES-GCM" }, false, ["encrypt", "decrypt"]);
}

async function sealSession(accessKey, secret) {
  const now = Math.floor(Date.now() / 1000);
  const payload = new TextEncoder().encode(JSON.stringify({ token: accessKey, iat: now, exp: now + SESSION_TTL_SECONDS }));
  const iv = crypto.getRandomValues(new Uint8Array(12));
  const ciphertext = await crypto.subtle.encrypt(
    { name: "AES-GCM", iv, additionalData: SESSION_AAD },
    await sessionKey(secret),
    payload,
  );
  const combined = new Uint8Array(iv.byteLength + ciphertext.byteLength);
  combined.set(iv, 0);
  combined.set(new Uint8Array(ciphertext), iv.byteLength);
  return base64UrlEncode(combined);
}

async function openSession(value, secret) {
  try {
    if (!value || value.length > 8192) return null;
    const combined = base64UrlDecode(value);
    if (combined.byteLength < 29) return null;
    const plaintext = await crypto.subtle.decrypt(
      { name: "AES-GCM", iv: combined.slice(0, 12), additionalData: SESSION_AAD },
      await sessionKey(secret),
      combined.slice(12),
    );
    const payload = JSON.parse(new TextDecoder().decode(plaintext));
    const now = Math.floor(Date.now() / 1000);
    if (!payload || typeof payload.token !== "string" || !payload.token || !Number.isInteger(payload.exp) || payload.exp <= now) return null;
    return payload;
  } catch {
    return null;
  }
}

function readCookie(request, name) {
  const raw = request.headers.get("cookie") || "";
  for (const part of raw.split(";")) {
    const [key, ...rest] = part.trim().split("=");
    if (key === name) return rest.join("=");
  }
  return "";
}

function sessionCookie(value, maxAge = SESSION_TTL_SECONDS) {
  return `${SESSION_COOKIE}=${value}; Path=/api/account; Max-Age=${maxAge}; HttpOnly; Secure; SameSite=Strict`;
}

function sameOriginMutation(request) {
  const origin = request.headers.get("origin");
  return Boolean(origin && origin === new URL(request.url).origin);
}

function identityConfigured(env) {
  return Boolean(env.SESSION_ENCRYPTION_KEY && env.ACCOUNT_API_BASE);
}

async function boundedText(message, limit) {
  if (Number(message.headers.get("content-length") || 0) > limit) throw new Error("body_too_large");
  if (!message.body) return "";
  const reader = message.body.getReader();
  const decoder = new TextDecoder();
  let size = 0;
  let text = "";
  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) return text + decoder.decode();
      size += value.byteLength;
      if (size > limit) {
        await reader.cancel();
        throw new Error("body_too_large");
      }
      text += decoder.decode(value, { stream: true });
    }
  } finally { reader.releaseLock(); }
}

async function upstreamRequest(env, path, accessKey, init = {}) {
  const target = new URL(path, env.ACCOUNT_API_BASE);
  const headers = new Headers(init.headers || {});
  headers.set("authorization", `Bearer ${accessKey}`);
  headers.set("accept", "application/json");
  // Never forward a bearer credential through an upstream redirect.
  const response = await fetch(target, { ...init, headers, redirect: "manual", signal: AbortSignal.timeout(8_000) });
  if (response.status >= 300 && response.status < 400) {
    await response.body?.cancel();
    throw new Error("account_upstream_redirect_rejected");
  }
  const responseHeaders = { "content-type": response.headers.get("content-type") || "application/json; charset=utf-8" };
  return new Response(response.body, { status: response.status, headers: { ...responseHeaders, "cache-control": "no-store" } });
}

function accountUpstreamPath(url) {
  if (url.pathname === "/api/account/me") return "/portal/api/me";
  if (url.pathname === "/api/account/usage") return `/portal/api/me/usage${url.search}`;
  if (url.pathname === "/api/account/keys") return "/portal/api/me/keys";
  const keyMatch = url.pathname.match(/^\/api\/account\/keys\/(key_[a-f0-9]{16})$/u);
  return keyMatch ? `/portal/api/me/keys/${keyMatch[1]}` : null;
}

async function handleAccountApi(request, env) {
  const url = new URL(request.url);
  const identityResponse = await handleEmailIdentity(request, env);
  if (identityResponse) return identityResponse;
  // Clearing a browser cookie must work even during an upstream/config outage.
  if (url.pathname === "/api/account/session" && request.method === "DELETE") {
    if (!sameOriginMutation(request)) return jsonResponse({ error: "origin_not_allowed" }, 403);
    return jsonResponse({ signed_out: true }, 200, { "set-cookie": sessionCookie("", 0) });
  }
  if (!identityConfigured(env)) return jsonResponse({ error: "identity_gateway_unavailable" }, 503);

  if (url.pathname === "/api/account/session" && request.method === "POST") {
    if (!sameOriginMutation(request)) return jsonResponse({ error: "origin_not_allowed" }, 403);
    let payload;
    try {
      payload = JSON.parse(await boundedText(request, MAX_SESSION_BODY_BYTES));
    } catch {
      return jsonResponse({ error: "invalid_request" }, 400);
    }
    const accessKey = typeof payload?.access_key === "string" ? payload.access_key.trim() : "";
    if (!accessKey || accessKey.length > 1024) return jsonResponse({ error: "invalid_request" }, 400);
    const upstream = await upstreamRequest(env, "/portal/api/me", accessKey);
    if (!upstream.ok) return upstream;
    let account;
    try {
      account = JSON.parse(await boundedText(upstream, MAX_ACCOUNT_BODY_BYTES));
    } catch { return jsonResponse({ error: "invalid_account_projection" }, 502); }
    if (typeof account?.portal?.tenant_id !== "string" || !account.portal.tenant_id.trim() || typeof account.portal.tier !== "string" || !account.portal.tier.trim()) return jsonResponse({ error: "invalid_account_projection" }, 502);
    const sealed = await sealSession(accessKey, env.SESSION_ENCRYPTION_KEY);
    return new Response(JSON.stringify(account), {
      status: 200,
      headers: {
        "content-type": "application/json; charset=utf-8",
        "cache-control": "no-store",
        "set-cookie": sessionCookie(sealed),
      },
    });
  }

  const upstreamPath = accountUpstreamPath(url);
  if (!upstreamPath) return jsonResponse({ error: "not_found" }, 404);
  const methods = url.pathname === "/api/account/keys" ? ["GET", "POST"] : url.pathname.startsWith("/api/account/keys/") ? ["PATCH"] : ["GET"];
  if (!methods.includes(request.method)) return jsonResponse({ error: "method_not_allowed" }, 405);
  if (request.method !== "GET" && !sameOriginMutation(request)) return jsonResponse({ error: "origin_not_allowed" }, 403);

  const session = await openSession(readCookie(request, SESSION_COOKIE), env.SESSION_ENCRYPTION_KEY);
  if (!session) return jsonResponse({ error: "unauthenticated" }, 401, { "set-cookie": sessionCookie("", 0) });
  const headers = new Headers();
  let body;
  if (request.method !== "GET") {
    headers.set("content-type", "application/json");
    try { body = await boundedText(request, MAX_SESSION_BODY_BYTES); }
    catch { return jsonResponse({ error: "invalid_request" }, 400); }
  }
  const response = await upstreamRequest(env, upstreamPath, session.token, { method: request.method, headers, body });
  if (response.status === 401) response.headers.set("set-cookie", sessionCookie("", 0));
  return response;
}

export default {
  async scheduled(_controller, env) {
    try {
      const result = await runIdentityMaintenance(env);
      console.log(JSON.stringify({ event: "identity_retention", ...result }));
      if (result.state === "backlog") throw new Error("identity_retention_backlog");
    } catch {
      // Do not log database errors that could contain PII or SQL parameters.
      throw new Error("identity_retention_incomplete");
    }
  },
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname === "/admin" || url.pathname.startsWith("/admin/")) {
      if (env.ACCOUNT_ADMIN_ENABLED !== "true" || !["GET", "HEAD"].includes(request.method)) return jsonResponse({ error: "not_found" }, 404);
      const shell = new URL("/app/index.html", url.origin);
      return env.ASSETS.fetch(new Request(shell, request));
    }
    if (url.pathname === "/api/account" || url.pathname.startsWith("/api/account/")) {
      try { return await handleAccountApi(request, env); }
      catch (error) { return jsonResponse({ error: "account_upstream_unavailable" }, error.name === "TimeoutError" ? 504 : 502); }
    }
    const response = await env.ASSETS.fetch(request);
    const normalizedPath = url.pathname.replace(/\/+$/, "") || "/";
    const terminalSegment = normalizedPath.slice(normalizedPath.lastIndexOf("/") + 1);
    const isAppRoute =
      normalizedPath !== "/" &&
      !normalizedPath.startsWith("/api/") &&
      !normalizedPath.startsWith("/assets/") &&
      !terminalSegment.includes(".");

    if (response.status !== 404 || !isAppRoute || !["GET", "HEAD"].includes(request.method)) {
      return response;
    }

    const indexUrl = new URL(url);
    indexUrl.pathname = "/";
    indexUrl.search = "";
    return env.ASSETS.fetch(new Request(indexUrl, request));
  },
};

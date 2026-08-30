import http from "node:http";
import { readFile } from "node:fs/promises";
import { resolve, extname } from "node:path";
import { fileURLToPath } from "node:url";

// Local, single-reviewer synthetic UI harness. No real credentials/upstream.
const root = fileURLToPath(new URL("../dist/client/", import.meta.url));
const port = Number(process.env.TRADINGDATAS_QA_PORT || 5193);
if (!Number.isInteger(port) || port < 1024 || port > 65535) throw new Error("Invalid loopback QA port");
let signedIn = false;
let scenario = "normal";
let logoutAttempts = 0;
let loginAttempts = 0;
const portal = { tenant_id: "SYNTHETIC-QA-ONLY", tier: "basic", scopes: ["read"], enabled: true,
  expires_at: "2027-01-01T00:00:00Z", minute_request_limit: 200, data_categories: ["a_share"], usage: { today_count: 12 } };
const cases = ["normal", "invalid", "unavailable", "malformed", "usage-failure", "logout-retry", "slow-login", "slow-identity", "identity-outage", "expired", "late-key"];
const pause = (ms) => new Promise((done) => setTimeout(done, ms));
http.createServer(async (req, res) => {
  const url = new URL(req.url, `http://127.0.0.1:${port}`);
  const json = (status, value) => { res.writeHead(status, { "content-type": "application/json", "cache-control": "no-store" }); res.end(JSON.stringify(value)); };
  if (url.pathname === "/__qa") {
    const selected = url.searchParams.get("case");
    if (cases.includes(selected)) { scenario = selected; signedIn = false; logoutAttempts = 0; loginAttempts = 0; }
    res.writeHead(200, { "content-type": "text/html; charset=utf-8" });
    return res.end(`<h1>Synthetic login QA — never enter a real key</h1><p>Scenario: ${scenario}. Use any synthetic test string.</p><p>POST login count: ${loginAttempts}</p>${cases.map((item) => `<p><a href="/__qa?case=${item}">${item}</a></p>`).join("")}<a href="/login">Open login</a>`);
  }
  if (url.pathname.startsWith("/api/account/")) {
    if (url.pathname === "/api/account/me") {
      if (scenario === "slow-identity") await pause(1800);
      if (scenario === "identity-outage") return json(503, { error: "synthetic_identity_outage" });
    }
    if (url.pathname === "/api/account/session" && req.method === "DELETE") {
      await pause(300);
      if (scenario === "logout-retry" && ++logoutAttempts === 1) return json(503, { error: "synthetic_failure" });
      signedIn = false;
      return json(200, { signed_out: true });
    }
    if (url.pathname === "/api/account/session" && req.method === "POST") {
      loginAttempts += 1;
      req.resume();
      if (scenario === "slow-login") await pause(1800);
      if (scenario === "invalid") return json(401, { error: "synthetic_invalid" });
      if (scenario === "unavailable") return json(503, { error: "synthetic_unavailable" });
      if (scenario === "malformed") return json(200, {});
      signedIn = true;
      return json(200, { portal });
    }
    if (!signedIn || scenario === "expired") return json(401, { error: "synthetic_unauthenticated" });
    if (url.pathname === "/api/account/me") return json(200, { portal });
    if (url.pathname === "/api/account/usage") return scenario === "usage-failure" ? json(503, {}) : json(200, { portal_usage: { today_count: 12, history: [] } });
    if (url.pathname === "/api/account/keys") {
      if (req.method === "POST") {
        req.resume();
        if (scenario === "late-key") await pause(2000);
        return json(200, { api_key: { key_id: "key_0123456789abcdef", label: "SYNTHETIC", fingerprint: "fixture…only", enabled: true }, key: "synthetic-new-key-not-valid" });
      }
      return json(200, { api_keys: [] });
    }
    return json(404, {});
  }
  const file = resolve(root, "." + (extname(url.pathname) ? url.pathname : "/index.html"));
  if (!file.startsWith(root)) return json(404, {});
  try {
    const bytes = await readFile(file);
    res.writeHead(200, { "content-type": { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".png": "image/png", ".svg": "image/svg+xml" }[extname(file)] || "application/octet-stream" });
    res.end(bytes);
  } catch { json(404, {}); }
}).listen(port, "127.0.0.1", () => console.log(`Synthetic-only login QA: http://127.0.0.1:${port}/__qa`));

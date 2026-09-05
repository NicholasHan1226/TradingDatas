#!/usr/bin/env node
import { copyFileSync, cpSync, existsSync, mkdirSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const dist = path.join(root, "dist");
const index = path.join(dist, "client", "index.html");
const worker = path.join(root, "worker", "index.js");
const hosting = path.join(root, ".openai", "hosting.json");

for (const file of [index, worker, hosting]) {
  if (!existsSync(file)) throw new Error("Missing Sites build input: " + file);
}

mkdirSync(path.join(dist, "server"), { recursive: true });
mkdirSync(path.join(dist, ".openai"), { recursive: true });
copyFileSync(worker, path.join(dist, "server", "index.js"));
copyFileSync(path.join(root, "worker", "data-api.js"), path.join(dist, "server", "data-api.js"));
copyFileSync(path.join(root, "worker", "email-identity.js"), path.join(dist, "server", "email-identity.js"));
copyFileSync(path.join(root, "worker", "email-templates.js"), path.join(dist, "server", "email-templates.js"));
copyFileSync(path.join(root, "worker", "identity-retention.js"), path.join(dist, "server", "identity-retention.js"));
copyFileSync(path.join(root, "worker", "account-continuity.js"), path.join(dist, "server", "account-continuity.js"));
copyFileSync(path.join(root, "worker", "portal-errors.js"), path.join(dist, "server", "portal-errors.js"));
copyFileSync(path.join(root, "worker", "commerce.js"), path.join(dist, "server", "commerce.js"));
// Keep offers derived from the same pricing source used by the browser.
mkdirSync(path.join(dist, "src"), { recursive: true });
copyFileSync(path.join(root, "src", "pricing.js"), path.join(dist, "src", "pricing.js"));
copyFileSync(hosting, path.join(dist, ".openai", "hosting.json"));
// Reuse the versioned admin build. The Worker serves its shell at /admin/;
// assets remain under /app/. No cookie or credential enters these files.
const adminBuild = path.resolve(root, "../static/app");
if (!existsSync(path.join(adminBuild, "index.html"))) throw new Error("Missing versioned admin build; build frontend first");
cpSync(adminBuild, path.join(dist, "client", "app"), { recursive: true });

console.log("Prepared Sites build: dist/server/index.js and dist/.openai/hosting.json");

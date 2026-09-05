import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import {
  connectedCoverage,
  landscapeMeta,
  roadmapPhases,
  sourceCandidates,
} from "../src/dataSourceLandscape.js";

test("keeps connected contract counts explicit and non-inflated", async () => {
  const snapshot = JSON.parse(
    await readFile(new URL("../src/connectedInterfaceSnapshot.json", import.meta.url), "utf8"),
  );
  assert.equal(snapshot.authority, "contract_config_only");
  assert.equal(snapshot.interfaces.length, 192);
  assert.equal(snapshot.interfaces.filter((item) => item.provider === "tushare").length, 190);
  assert.equal(snapshot.interfaces.filter((item) => item.provider === "firecrawl").length, 2);
  assert.equal(snapshot.interfaces.filter((item) => item.provider === "tushare" && item.activation === "active").length, 136);
  assert.equal(snapshot.interfaces.filter((item) => item.provider === "firecrawl" && item.activation === "active").length, 1);
  assert.equal(connectedCoverage.some((item) => item.family === "crypto"), false);
  assert.equal(sourceCandidates.some((item) => item.family === "crypto"), false);
  assert.equal(connectedCoverage.find((item) => item.id === "firecrawl-news").pausedCount, 1);
});

test("keeps pre-runtime domestic candidates separate from runtime contracts", async () => {
  const snapshot = JSON.parse(
    await readFile(new URL("../src/discoveryInterfaceSnapshot.json", import.meta.url), "utf8"),
  );
  assert.equal(snapshot.authority, "capability_scope_only");
  assert.equal(snapshot.candidates.length, 25);
  assert.deepEqual(snapshot.candidates.find((item) => item.apiName === "dc_hot"), {
    apiName: "dc_hot", contractState: "review_required",
  });
  assert.equal(snapshot.candidates.some((item) => Object.hasOwn(item, "datasetId")), false);
});

test("keeps paused-contract preflight separate from observation and access", async () => {
  const snapshot = JSON.parse(
    await readFile(new URL("../src/pausedContractPreflightSnapshot.json", import.meta.url), "utf8"),
  );
  assert.equal(snapshot.authority, "compiled_contract_preflight_only");
  const ready = snapshot.groups.find((group) => group.id === "ready_for_bounded_https_probe");
  const seedRequired = snapshot.groups.find((group) => group.id === "requires_seed_receipt");
  assert.equal(ready.interfaces.length, 3);
  assert.equal(ready.interfaces.some((item) => item.apiName === "forecast"), false);
  assert.deepEqual(ready.interfaces.find((item) => item.apiName === "fut_daily"), {
    apiName: "fut_daily", datasetId: "cn.dataset.fut_daily",
  });
  assert.equal(seedRequired.interfaces.length, 4);
  assert.equal(snapshot.warning.includes("no provider call"), true);
});

test("candidate sources carry official evidence, rights state, and a roadmap phase", () => {
  const phaseIds = new Set(roadmapPhases.map((phase) => phase.id));
  assert.equal(landscapeMeta.status, "research_registry");
  assert.ok(sourceCandidates.length >= 20);
  for (const source of sourceCandidates) {
    assert.match(source.officialUrl, /^https?:\/\//);
    assert.ok(source.rights);
    assert.ok(source.stage);
    assert.ok(phaseIds.has(source.phase));
  }
});

test("candidate sources progressively disclose roadmap phases without a second search", async () => {
  const app = await readFile(new URL("../src/App.jsx", import.meta.url), "utf8");
  assert.match(app, /useState\("P1"\)/);
  assert.match(app, /sourcePhase === "all"/);
  assert.match(app, /sourceCandidates\.filter\(\(source\) => source\.phase === sourcePhase\)/);
  assert.match(app, /source-phase-control/);
  assert.match(app, /source-contract-index/);
  assert.match(app, /source-discovery-groups/);
  assert.match(app, /source-preflight-groups/);
  assert.match(app, /PRE-FLIGHT QUEUE/);
  assert.match(app, /PRE-RUNTIME CANDIDATES/);
  assert.match(app, /contractState === "all"/);
  assert.match(app, /item\.activation === contractState/);
  assert.match(app, /Global search still finds a specific source/);
});

test("public source maintenance guidance matches the reviewed snapshot", async () => {
  const guide = await readFile(new URL("../../docs/product/DATA_SOURCE_LANDSCAPE.md", import.meta.url), "utf8");
  assert.match(guide, /Crypto.*internal|internal.*Crypto/);
  assert.match(guide, /compact material-family\s+index/);
  assert.match(guide, /## Updating the public snapshot/);
  assert.match(guide, /landscapeMeta\.reviewedAt/);
});

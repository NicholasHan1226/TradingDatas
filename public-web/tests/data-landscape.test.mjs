import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import {
  connectedCoverage,
  collectionHistory,
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
  const tushare = snapshot.interfaces.filter((item) => item.provider === "tushare");
  const summary = connectedCoverage.find((item) => item.id === "tushare-quicksync");
  const activeCount = tushare.filter((item) => item.activation === "active").length;
  const pausedCount = tushare.filter((item) => item.activation === "paused").length;
  assert.equal(summary.contractCount, tushare.length);
  assert.equal(summary.activeCount, activeCount);
  assert.equal(summary.pausedCount, pausedCount);
  assert.match(summary.note.zh, new RegExp(`${tushare.length} 个标准化运行合同；${activeCount} 个配置为 active`));
  assert.match(summary.note.en, new RegExp(`${tushare.length} normalized runtime contracts; ${activeCount} are configured active`));
  assert.match(summary.note.zh, /active 不等于/);
  assert.match(summary.note.en, /does not mean/);
  assert.equal(snapshot.interfaces.filter((item) => item.provider === "firecrawl" && item.activation === "active").length, 1);
  assert.equal(connectedCoverage.some((item) => item.family === "crypto"), false);
  assert.equal(sourceCandidates.some((item) => item.family === "crypto"), false);
  assert.equal(connectedCoverage.find((item) => item.id === "firecrawl-news").pausedCount, 1);
});

test("dates the current contract review while preserving historical observations", () => {
  assert.equal(landscapeMeta.reviewedAt, "2026-09-05");
  const current = collectionHistory.find((entry) => entry.date === "2026-09-05");
  assert.equal(current.status, "registry_snapshot");
  assert.match(current.title.en, /138 active, 52 paused/);
  assert.match(current.detail.zh, /实际 receipt、覆盖与采集状态请查看账户认证目录/);
  assert.match(current.detail.en, /authenticated account catalog for actual receipts, coverage and collection status/);
  assert.match(collectionHistory.find((entry) => entry.date === "2026-08-27").detail.en, /133 active and 57 paused/);
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
  assert.equal(ready.interfaces.length, 0);
  const windowRequired = snapshot.groups.find((group) => group.id === "requires_activation_window_contract");
  assert.deepEqual(windowRequired.interfaces, [{
    apiName: "stk_nineturn", datasetId: "cn.dataset.stk_nineturn",
    probeState: "executable", reasonCode: "activation_window_contract_unsupported",
  }]);
  assert.equal(snapshot.groups.some((group) => group.interfaces.some((item) => ["fut_daily", "opt_basic"].includes(item.apiName))), false);
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
  assert.match(app, /requires_activation_window_contract/);
  assert.match(app, /可验证上游，采集窗口合同仍待补齐/);
  assert.match(app, /Upstream validation is possible, but the collection-window contract still needs completion/);
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

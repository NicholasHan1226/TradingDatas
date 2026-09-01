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
  assert.equal(snapshot.interfaces.filter((item) => item.provider === "tushare" && item.activation === "active").length, 133);
  assert.equal(connectedCoverage.find((item) => item.id === "binance-public").contractCount, 6);
});

test("candidate sources carry official evidence, rights state, and a roadmap phase", () => {
  const phaseIds = new Set(roadmapPhases.map((phase) => phase.id));
  assert.equal(landscapeMeta.status, "research_registry");
  assert.ok(sourceCandidates.length >= 25);
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
  assert.match(app, /Global search still finds a specific source/);
});

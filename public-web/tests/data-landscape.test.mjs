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

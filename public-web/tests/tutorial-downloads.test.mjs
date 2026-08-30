import test from "node:test";
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import vm from "node:vm";
import { tutorialDownloadFiles, pythonFunctionNames as names } from "../scripts/build-tutorial-downloads.mjs";
import { tutorialExamples } from "../src/tutorialExamples.js";

const python = process.env.TD_NOTEBOOK_PYTHON || "python3";
function runPython(source, args, name) {
  return JSON.parse(execFileSync(python, ["-c", `${source}\nimport json, sys\ntry:\n print(json.dumps({"result": ${name}(*json.load(sys.stdin))}))\nexcept ValueError as error:\n print(json.dumps({"error": str(error)}))`], { input: JSON.stringify(args), encoding: "utf8" }));
}

test("download artifacts share synthetic inputs and JS output, and twelve notebooks execute top-to-bottom", () => {
  for (const [id, example] of Object.entries(tutorialExamples)) {
    const files = tutorialDownloadFiles(id);
    assert.equal(Object.keys(files).length, 4);
    const input = JSON.parse(files["inputs.json"]);
    assert.equal(input.identity, "synthetic");
    assert.deepEqual(input.args, example.args);
    assert.deepEqual(input.expected, example.execute(...example.args));
    let logged;
    vm.runInNewContext(files["example.mjs"], { console: { log: (value) => { logged = JSON.parse(JSON.stringify(value)); } } });
    assert.deepEqual(logged, input.expected);
    for (const locale of ["zh", "en"]) {
      const notebook = JSON.parse(files[`tutorial-${locale}.ipynb`]);
      assert.equal(notebook.nbformat, 4);
      assert.equal(notebook.cells.length, 10);
      assert.equal(new Set(notebook.cells.map((cell) => cell.id)).size, 10);
      const code = notebook.cells.filter((cell) => cell.cell_type === "code").map((cell) => cell.source.join("")).join("\n");
      const output = execFileSync(python, ["-c", code], { encoding: "utf8" });
      assert.ok(output.includes(locale === "zh" ? "通过" : "Passed"));
      assert.doesNotMatch(code, /requests\.|urllib|fetch\(|subprocess|socket/);
    }
  }
});

test("Python companions agree with JavaScript on alternate inputs and failure cases", () => {
  for (const [id, example] of Object.entries(tutorialExamples)) {
    const notebook = JSON.parse(tutorialDownloadFiles(id)["tutorial-en.ipynb"]);
    const source = notebook.cells.find((cell) => cell.id === "implementation").source.join("");
    const cases = [structuredClone(example.args)];
    if (id === "adjusted-price-series") {
      cases.push([example.args[0], "2000-01-01"], [[], example.args[1]], [[...example.args[0], example.args[0][0]], example.args[1]]);
      const bad = structuredClone(example.args); bad[0][0].factor = 0; cases.push(bad);
    } else if (id === "pit-fundamentals-panel") {
      cases.push([example.args[0], "2025-04-30T23:59:59Z"], [example.args[0], "2025-01-01T00:00:00Z"], [example.args[0], "2025-03-31"]);
      const ambiguous = structuredClone(example.args); ambiguous[0][1].publishedAt = ambiguous[0][0].publishedAt; ambiguous[0][1].firstSeenAt = ambiguous[0][0].firstSeenAt; cases.push(ambiguous);
    } else if (id === "company-event-timeline") {
      cases.push([example.args[0], []], [example.args[0], ["2025-01-03T09:30:00+08:00"]]);
      const conflict = structuredClone(example.args); conflict[0][1].publishedAt = "2025-01-04T18:00:00+08:00"; cases.push(conflict);
    } else if (id === "minute-bar-gaps") {
      cases.push([[], example.args[1], 5], [example.args[0], [], 5], [example.args[0], example.args[1], 0]);
      const duplicate = structuredClone(example.args); duplicate[0].push(duplicate[0][0]); cases.push(duplicate);
      const date = structuredClone(example.args); date[1][0] = "2025-02-30T00:00:00Z"; cases.push(date);
      const overlap = structuredClone(example.args); overlap[1][1] = overlap[1][0]; cases.push(overlap);
      const offGrid = structuredClone(example.args); offGrid[0][0].openTime = "2025-01-06T01:31:00Z"; cases.push(offGrid);
      const bad = structuredClone(example.args); bad[0][0].close = true; cases.push(bad);
    } else if (id === "document-version-ledger") {
      cases.push([example.args[0], "2025-01-06T09:00:00Z"], [example.args[0], "2025-01-01T00:00:00Z"], [[...example.args[0]].reverse(), example.args[1]]);
      const conflict = structuredClone(example.args); conflict[0][1].contentHash = "c".repeat(64); cases.push(conflict);
      const tied = structuredClone(example.args); tied[0][2].publishedAt = tied[0][0].publishedAt; tied[0][2].firstSeenAt = tied[0][0].firstSeenAt; cases.push(tied);
      const late = structuredClone(example.args); late[0][2].firstSeenAt = "2025-02-01T00:00:00Z"; cases.push(late);
      const invalid = structuredClone(example.args); invalid[0][0].contentHash = "missing"; cases.push(invalid);
      const multilingual = structuredClone(example.args); multilingual[0].push({ ...multilingual[0][0], publisher: "另一发布方" }, { ...multilingual[0][0], publisher: "a-publisher" }); cases.push(multilingual);
    } else if (id === "crypto-observation-alignment") {
      cases.push([example.args[0], [], 300, "BTC"], [example.args[0], example.args[1], 0, "BTC"], [example.args[0], example.args[1], 300, "USDT"]);
      const duplicate = structuredClone(example.args); duplicate[1].push(duplicate[1][0]); cases.push(duplicate);
      const boundary = structuredClone(example.args); boundary[1][0].observedAt = "2025-01-06T00:05:00Z"; boundary[1][0].firstSeenAt = "2025-01-06T00:05:00Z"; cases.push(boundary);
      const invalid = structuredClone(example.args); invalid[0][0].endExclusive = "2025-01-06T00:04:00Z"; cases.push(invalid);
    }
    for (const args of cases) {
      let expected;
      try { expected = { result: example.execute(...args) }; } catch (error) { expected = { error: error.message }; }
      assert.deepEqual(runPython(source, args, names[id]), expected, `${id}: ${JSON.stringify(args)}`);
    }
  }
});
